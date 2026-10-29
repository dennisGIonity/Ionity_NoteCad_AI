# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""The privacy notice (POPIA s18; the POPIA review's fix 5). The apps show it from what this returns: who is
responsible and how to reach them, what is recorded and why, who sees it, how long it is kept, whether anything goes
abroad, and the rights of the people it is about. The owner fills in the contact and the periods once and accepts the
notice; every member reads it once (on joining, or the first time they open the app) and that is recorded."""
from __future__ import annotations

import json
import os

from . import retention
from .common import now_iso
from .permissions import OWNER, Principal

VERSION = 1  # a new version asks everyone to read it again


def _load(v) -> dict:
    if not v:
        return {}
    try:
        return json.loads(v) if isinstance(v, str) else dict(v)
    except ValueError:
        return {}


def cloud(brain) -> dict:
    """What leaves this PC, and to where (POPIA s72), from the switches actually in use."""
    s = brain.settings
    claude = bool(os.environ.get("ANTHROPIC_API_KEY")) and "claude" in (s.routers or "")
    deepgram = bool(s.deepgram_key or os.environ.get("DEEPGRAM_API_KEY")) and "deepgram" in (s.stt_engines or "")
    sync = s.sync_target or ""
    return {"claude": claude, "deepgram": deepgram,
            "sync": "supabase" if sync.startswith(("postgres://", "postgresql://")) else ("edge node" if sync else None)}


def notice(brain, p: Principal, ws: str) -> dict:
    w = brain.db.one("select name, privacy from workspaces where id=?", (ws,))
    if w is None:
        raise KeyError(ws)
    priv = _load(w["privacy"])
    owners = [r["display_name"] for r in brain.db.query(
        "select display_name from members where workspace_id=? and level=? and status='active' order by created_at",
        (ws, OWNER))]
    me = brain.db.one("select privacy_ack_at from members where id=?", (p.member_id,)) if p.member_id else None
    days = retention.read(brain.db, ws)
    acked = (me or {}).get("privacy_ack_at")
    return {"version": VERSION, "business": w["name"], "owners": owners, "contact": priv.get("contact"),
            "accepted_at": priv.get("accepted_at") if priv.get("version") == VERSION else None,
            "retention": days, "retention_text": retention.describe(days), "recommended": retention.RECOMMENDED,
            "cloud": cloud(brain), "my_ack_at": acked if priv.get("version") == VERSION or acked else None,
            "is_owner": p.level <= OWNER}


def accept(brain, p: Principal, ws: str, contact: str | None, periods: dict | None) -> dict:
    """An owner sets the contact and the periods and accepts the notice. Periods are checked (retention.clean)."""
    if p.level > OWNER or not p.active:
        raise PermissionError("only an owner sets the privacy notice and how long things are kept")
    w = brain.db.one("select privacy from workspaces where id=?", (ws,))
    if w is None:
        raise KeyError(ws)
    priv = _load(w["privacy"])
    if contact is not None:
        priv["contact"] = contact.strip()[:200] or None
    if not priv.get("contact"):
        raise ValueError("give a contact (a name and a phone number or email) for questions about personal information")
    priv.update({"version": VERSION, "accepted_at": now_iso(), "accepted_by": p.member_id})
    fields: dict = {"privacy": json.dumps(priv)}
    if periods is not None:
        fields["retention"] = json.dumps(retention.clean(periods))
    brain.db.update("workspaces", {"id": ws}, fields)
    if p.member_id:
        brain.db.update("members", {"id": p.member_id}, {"privacy_ack_at": now_iso()})
    return notice(brain, p, ws)


def acknowledge(brain, p: Principal, ws: str) -> dict:
    """A member has read the notice."""
    if p.member_id:
        brain.db.update("members", {"id": p.member_id}, {"privacy_ack_at": now_iso()})
    return notice(brain, p, ws)
