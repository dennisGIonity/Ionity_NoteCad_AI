# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""One person's information: a copy of everything about them (POPIA s23) and its erasure (s24).

A subject is a member (a person with a login) or a person on the map who has none (a worker named in notes). Their
names are the member's display name, the person node's title and its aliases.

  export   their member record, devices, seat; what they recorded (transcripts; recordings are listed, not copied);
           every note, task, alert, Inbox item and notification that names them; what they did (action log); what
           the companion learned from them. An owner may export anyone; a member may export themselves.
  erase    an owner only. Their recordings are deleted; every name of theirs in notes, tasks, alerts, captures,
           Inbox items and notifications becomes "[removed]"; the person node becomes "Removed person" with no aliases;
           a member is revoked (devices wiped at their next contact) and renamed "Removed member"; the companion forgets
           them. The change reaches phones (their next pull) and other workers (sync) as ordinary updates, and the
           sync journal of the workspace is compacted so no older copy stays. Kept on purpose: the action log rows
           (who did what and when, the name taken out of their content: the business's audit record) and the archives of
           data/archive until their own period ends (NC_BRAIN_ARCHIVE_DAYS).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .common import now_iso
from .permissions import OWNER, Principal

log = logging.getLogger("notecad.security")
REMOVED = "[removed]"
TEXT_COLUMNS = [("notes", "id", ["body"]), ("tasks", "id", ["title", "assignee_hint"]), ("alerts", "id", ["title"]),
                ("captures", "id", ["text", "transcript"]), ("inbox", "id", ["question", "event_text", "proposal"]),
                ("notifications", "id", ["payload"]), ("invites", "id", ["profile"]),
                ("nodes", "id", ["title", "summary", "status_reason"]), ("action_log", "id", ["action", "inverse"])]


def _names(brain, ws: str, sid: str) -> tuple[dict | None, dict | None, list[str]]:
    """(member row, person node, names) for a member id or a person node id."""
    db = brain.db
    m = db.one("select * from members where id=? and workspace_id=?", (sid, ws))
    node_id = m["person_node_id"] if m else sid
    n = db.one("select * from nodes where id=? and workspace_id=?", (node_id, ws)) if node_id else None
    if n is not None and n["kind"] != "person" and m is None:
        raise KeyError(sid)
    if m is None and n is None:
        raise KeyError(sid)
    if m is None:  # a person node: is there a member for it?
        m = db.one("select * from members where person_node_id=? and workspace_id=?", (n["id"], ws))
    names = []
    if m:
        names += [m["display_name"], *m["display_name"].split()[:1]]
    if n:
        names.append(n["title"])
        names += [a["alias"] for a in db.query("select alias from node_aliases where node_id=?", (n["id"],))]
    seen, out = set(), []
    for x in sorted({x.strip() for x in names if x and len(x.strip()) >= 3}, key=len, reverse=True):
        if x.lower() not in seen and x not in (REMOVED, "Removed member", "Removed person"):
            seen.add(x.lower())
            out.append(x)
    return m, n, out


def _pattern(names: list[str]) -> re.Pattern | None:
    return re.compile(r"\b(" + "|".join(re.escape(x) for x in names) + r")\b", re.I) if names else None


def _rows_naming(db, ws: str, names: list[str]) -> dict[str, list[dict]]:
    pat = _pattern(names)
    out: dict[str, list[dict]] = {}
    if pat is None:
        return out
    for table, _key, cols in TEXT_COLUMNS:
        like = " or ".join(f"lower(coalesce({c}, '')) like ?" for c in cols for _ in names)
        args = [f"%{x.lower()}%" for _ in cols for x in names]
        rows = db.query(f"select * from {table} where workspace_id=? and ({like})", [ws, *args])
        hits = [r for r in rows if any(pat.search(str(r.get(c) or "")) for c in cols)]
        if hits:
            out[table] = hits
    return out


def export(brain, p: Principal, ws: str, sid: str) -> dict:
    m, n, names = _names(brain, ws, sid)
    if p.level > OWNER and not (m and p.member_id == m["id"]):
        raise PermissionError("an owner, or the person themselves")
    db = brain.db
    member_id = m["id"] if m else None
    out: dict = {"format": "notecad-subject-export/1", "exported_at": now_iso(), "workspace": ws, "names": names,
                 "member": {k: v for k, v in m.items()} if m else None,
                 "person_node": {k: n[k] for k in ("id", "title", "kind", "created_at")} if n else None,
                 "naming_them": _rows_naming(db, ws, names)}
    if member_id:
        out["devices"] = [{k: d[k] for k in ("id", "name", "platform", "created_at", "last_seen_at", "revoked_at")
                           if k in d} for d in db.query("select * from devices where member_id=?", (member_id,))]
        out["recorded"] = [{k: c[k] for k in ("id", "recorded_at", "text", "source", "state")} |
                           {"has_recording": bool(c["audio_path"])}
                           for c in db.query("select * from captures where member_id=? order by recorded_at", (member_id,))]
        out["did"] = [{k: a[k] for k in ("id", "created_at", "actor", "action")}
                      for a in db.query("select * from action_log where member_id=? order by created_at", (member_id,))]
        out["companion"] = brain.companion.export(ws, member_id) if hasattr(brain.companion, "export") else None
    log.info("subject export ws=%s subject=%s by=%s", ws, sid, p.member_id)
    return out


def erase(brain, p: Principal, ws: str, sid: str) -> dict:
    if p.level > OWNER or not p.active:
        raise PermissionError("only an owner erases a person")
    m, n, names = _names(brain, ws, sid)
    db = brain.db
    pat = _pattern(names)
    counts = {"texts": 0, "recordings": 0, "aliases": 0}
    if m and m["status"] == "active":
        if m["level"] <= OWNER and db.one("select count(*) as c from members where workspace_id=? and level<=? "
                                          "and status='active'", (ws, OWNER))["c"] <= 1:
            raise PermissionError("the last owner cannot be erased")
        brain.people.revoke_member(p, ws, m["id"])
    with db.tx():
        for table, rows in _rows_naming(db, ws, names).items():
            cols = next(c for t, _, c in TEXT_COLUMNS if t == table)
            for r in rows:
                fields = {c: pat.sub(REMOVED, r[c]) for c in cols if r.get(c) and pat and pat.search(str(r[c]))}
                if fields:
                    db.update(table, {"id": r["id"]}, fields)
                    counts["texts"] += 1
        # each split event of a note keeps its text, its candidates (paths name people) and the router's answer
        likes = " or ".join("lower(e.text || coalesce(e.candidates, '') || coalesce(e.routed, '')) like ?" for _ in names)
        for e in db.query(f"select e.* from capture_events e join captures c on c.id = e.capture_id "
                          f"where c.workspace_id=? and ({likes})", [ws, *[f"%{x.lower()}%" for x in names]]):
            fields = {c: pat.sub(REMOVED, e[c]) for c in ("text", "candidates", "routed")
                      if isinstance(e.get(c), str) and pat and pat.search(e[c])}
            if fields:
                db.execute(f"update capture_events set {', '.join(f'{c}=?' for c in fields)} "
                           "where capture_id=? and idx=?", [*fields.values(), e["capture_id"], e["idx"]])
                counts["texts"] += 1
        if n:
            counts["aliases"] = db.execute("delete from node_aliases where node_id=?", (n["id"],))
            db.execute("delete from node_embeddings where node_id=?", (n["id"],))
            db.update("nodes", {"id": n["id"]}, {"title": "Removed person", "attributes": json.dumps({})})
        if m:
            db.update("members", {"id": m["id"]}, {"display_name": "Removed member", "contact": None})
            db.execute("update tasks set assignee_hint=null where assignee_member=?", (m["id"],))
    if m:
        root = Path(brain.settings.audio_dir).resolve()
        for c in db.query("select id, audio_path from captures where member_id=? and audio_path is not null", (m["id"],)):
            f = Path(c["audio_path"]).resolve()
            if f.is_relative_to(root):
                f.unlink(missing_ok=True)
            db.update("captures", {"id": c["id"]}, {"audio_path": None})
            counts["recordings"] += 1
    from .retention import compact_journal
    counts["journal"] = compact_journal(db, ws)
    counts["companion"] = brain.companion.forget(ws, names, [x["id"] for x in db.query(
        "select id from members where workspace_id=?", (ws,))], wipe=m["id"] if m else None)
    log.info("subject erased ws=%s subject=%s by=%s counts=%s", ws, sid, p.member_id, counts)
    return {"erased": sid, "names": len(names), "counts": counts,
            "kept": ["action log rows (who did what, when), with the name taken out of what they say",
                     "archives in data/archive until NC_BRAIN_ARCHIVE_DAYS"]}
