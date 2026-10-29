# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Delegation: who a task goes to, and who hears about an alert.

A task's assignee_hint ("Sipho") is matched against workspace members and person nodes. A match assigns the
task, links the node to the person (assigned_to) and queues a notification for that member. No match: the task
stays with the owner and keeps the hint, so the owner sees "for Sipho?" and can assign it in one tap.
Critical alerts notify every owner and manager (ADR 0014: and only those who can see the node, once that filter is in).
"""
from __future__ import annotations

from rapidfuzz import fuzz

from .common import new_id, now_iso
from .db import Database


def _first(name: str) -> str:
    return (name or "").strip().split()[0].lower() if (name or "").strip() else ""


def resolve(db: Database, ws: str, hint: str | None) -> dict | None:
    if not hint or not hint.strip():
        return None
    h = hint.strip().lower()
    best, best_score = None, 0.0
    for m in db.query("select * from members where workspace_id=?", (ws,)):
        name = m["display_name"].lower()
        s = max(fuzz.ratio(h, name), fuzz.ratio(h, _first(name)) if " " not in h else 0)
        if s > best_score:
            best, best_score = {"member_id": m["id"], "person_node_id": m["person_node_id"], "name": m["display_name"],
                                "matched_by": "member"}, s
    for p in db.query("select id, title from nodes where workspace_id=? and kind='person'", (ws,)):
        names = [p["title"].lower()] + [a["alias"] for a in db.query("select alias from node_aliases where node_id=?", (p["id"],))]
        s = max(max(fuzz.ratio(h, n), fuzz.ratio(h, _first(n)) if " " not in h else 0) for n in names)
        if s > best_score:
            linked = db.one("select id from members where workspace_id=? and person_node_id=?", (ws, p["id"]))
            best, best_score = {"member_id": linked["id"] if linked else None, "person_node_id": p["id"],
                                "name": p["title"], "matched_by": "person node"}, s
    return best if best_score >= 85 else None


def notify(db: Database, ws: str, member_id: str | None, kind: str, payload: dict) -> str:
    nid = new_id()
    db.insert("notifications", {"id": nid, "workspace_id": ws, "member_id": member_id, "kind": kind,
                                "payload": payload, "created_at": now_iso(), "sent_at": None})
    return nid


def alert_audience(db: Database, ws: str) -> list[str]:
    return [m["id"] for m in db.query("select id from members where workspace_id=? and level<=2 and status='active' "
                                      "order by level, created_at", (ws,))]


def owner_member(db: Database, ws: str) -> str | None:
    r = db.one("select id from members where workspace_id=? and level=1 and status='active' order by created_at", (ws,))
    return r["id"] if r else None
