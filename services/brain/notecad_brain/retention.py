# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""How long personal information is kept (POPIA s14; the POPIA review's fixes 1 and 2).

Each workspace has its own periods, set by an owner (workspaces.retention, migration 9). Nothing is deleted until an
owner sets them: the owner is the responsible party and decides. The worker runs purge_all() every few hours:

  audio_days        voice recordings: the file is deleted and the capture keeps its transcript
  transcript_days   what was said: the capture's text and transcript and its split events are blanked. The notes,
                    tasks and alerts the owner keeps on the map are business records and stay until deleted
  log_days          who did what: action log rows that every peer has, sent notifications, sync rejects and set-aside
                    conflict copies

Every purge also compacts the sync journal of that workspace: of each row only the newest change is kept, so an old
copy of something deleted or changed does not live on in sync_changes. A peer behind gets the newest change; a delete
stays as a tombstone (op D, no row data), so every peer still deletes it.

The archives under data/archive (workspaces written out before removal, backups before big changes) are kept for
NC_BRAIN_ARCHIVE_DAYS when that is set (the PC's setting: their workspaces no longer exist)."""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from .common import now_iso

log = logging.getLogger("notecad.retention")
DAY = 86400

KEYS = ("audio_days", "transcript_days", "log_days")
# what the privacy notice suggests; the owner picks (None keeps)
RECOMMENDED = {"audio_days": 90, "transcript_days": 365, "log_days": 365}
MAX_DAYS = 3650


def cutoff(days: int, now: float | None = None) -> str:
    return now_iso((now or time.time()) - days * 86400)


def read(db, ws: str) -> dict:
    """The workspace's periods: {key: days or None}."""
    r = db.one("select retention from workspaces where id=?", (ws,))
    got = {}
    if r and r["retention"]:
        try:
            got = json.loads(r["retention"]) if isinstance(r["retention"], str) else dict(r["retention"])
        except ValueError:
            got = {}
    return {k: (int(got[k]) if isinstance(got.get(k), (int, float)) and got[k] else None) for k in KEYS}


def clean(values: dict) -> dict:
    """Whole days, 1 to 3650, or None (keep). Unknown keys are refused."""
    bad = set(values) - set(KEYS)
    if bad:
        raise ValueError(f"unknown retention setting: {', '.join(sorted(bad))}")
    out = {}
    for k in KEYS:
        v = values.get(k)
        if v is None or v == "":
            out[k] = None
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not 1 <= int(v) <= MAX_DAYS:
            raise ValueError(f"{k}: a whole number of days from 1 to {MAX_DAYS}, or empty to keep")
        out[k] = int(v)
    return out


def compact_journal(db, ws: str) -> int:
    """Keep only the newest change of each row of this workspace in sync_changes (tombstones carry no data)."""
    n = db.execute(
        "delete from sync_changes where ws=? and seq < (select max(s2.seq) from sync_changes s2 "
        "where s2.tbl=sync_changes.tbl and s2.pk=sync_changes.pk)", (ws,))
    db.execute("update sync_changes set row=null where ws=? and op='D' and row is not null", (ws,))
    return n


def purge(brain, ws: str, now: float | None = None) -> dict:
    """Apply one workspace's periods now. Returns what went, by kind."""
    db = brain.db
    days = read(db, ws)
    out = {"audio": 0, "transcripts": 0, "companion": 0, "log": 0, "journal": 0}
    if not any(days.values()):
        return out
    if days["audio_days"]:
        old = db.query("select id, audio_path from captures where workspace_id=? and audio_path is not null "
                       "and recorded_at < ?", (ws, cutoff(days["audio_days"], now)))
        root = Path(brain.settings.audio_dir).resolve()
        for c in old:
            p = Path(c["audio_path"]).resolve()
            if p.is_relative_to(root):
                p.unlink(missing_ok=True)
            db.update("captures", {"id": c["id"]}, {"audio_path": None})
        out["audio"] = len(old)
    if days["transcript_days"]:
        cut = cutoff(days["transcript_days"], now)
        ids = [r["id"] for r in db.query("select id from captures where workspace_id=? and recorded_at < ? and "
                                         "(text is not null or transcript is not null)", (ws, cut))]
        with db.tx():
            for cid in ids:
                db.update("captures", {"id": cid}, {"text": None, "transcript": None})
                db.execute("update capture_events set text='' where capture_id=?", (cid,))
        out["transcripts"] = len(ids)
        # what the companions learned from those notes ages out with them
        members = [r["id"] for r in db.query("select id from members where workspace_id=?", (ws,))]
        got = brain.companion.forget(ws, None, members, before=time.time() - days["transcript_days"] * DAY)
        out["companion"] = sum(got.values()) if got else 0
    if days["log_days"]:
        cut = cutoff(days["log_days"], now)
        with db.tx():
            # an action another worker does not have yet stays until it does (sync needs it); without a sync
            # target nothing waits
            waiting = "" if not brain.settings.sync_target else " and synced_at is not null"
            n = db.execute(f"delete from action_log where workspace_id=? and created_at < ?{waiting}", (ws, cut))
            n += db.execute("delete from notifications where workspace_id=? and created_at < ?", (ws, cut))
        out["log"] = n
    out["journal"] = compact_journal(db, ws)
    # a Supabase hub keeps its own journal: the worker that syncs with it compacts that one too
    hub = getattr(getattr(brain, "sync", None), "peer", None)
    hub_db = getattr(getattr(hub, "journal", None), "db", None)
    if hub_db is not None and hub_db is not db:
        try:
            out["journal"] += compact_journal(hub_db, ws)
        except Exception:  # noqa: BLE001 - the hub may be unreachable now; the next run tries again
            log.warning("retention: the hub journal of %s could not be compacted now", ws)
    if any(out.values()):
        log.info("retention %s: %s", ws, out)
    return out


def purge_archives(folder: str | Path, days: int, now: float | None = None) -> int:
    """Archives (workspace JSON files, backup folders) older than `days`, by their time on disk."""
    folder = Path(folder)
    if not days or not folder.is_dir():
        return 0
    edge = (now or time.time()) - days * 86400
    n = 0
    for f in folder.iterdir():
        if f.stat().st_mtime >= edge:
            continue
        if f.is_dir():
            shutil.rmtree(f, ignore_errors=True)
        else:
            f.unlink(missing_ok=True)
        n += 1
    return n


def purge_all(brain, now: float | None = None) -> dict:
    """Every workspace's periods, then the PC's archive period. The worker calls this every few hours."""
    done = {}
    for w in brain.db.query("select id from workspaces where retention is not null"):
        try:
            got = purge(brain, w["id"], now)
            if any(got.values()):
                done[w["id"]] = got
        except Exception:  # noqa: BLE001 - one workspace must not stop the others
            log.exception("retention for %s", w["id"])
    s = brain.settings
    if s.archive_days:
        n = purge_archives(s.archive_dir or Path(s.audio_dir).resolve().parent.parent / "archive", s.archive_days, now)
        if n:
            done["archives"] = n
            log.info("retention: %s archives older than %s days removed", n, s.archive_days)
    return done


def next_run(last: float | None, every_h: float = 6.0) -> float:
    return (last or 0) + every_h * 3600


def describe(days: dict) -> str:
    """One line for the privacy notice."""
    parts = []
    for k, label in (("audio_days", "recordings"), ("transcript_days", "transcripts"), ("log_days", "activity log")):
        parts.append(f"{label} {days[k]} days" if days.get(k) else f"{label} until deleted")
    return ", ".join(parts)
