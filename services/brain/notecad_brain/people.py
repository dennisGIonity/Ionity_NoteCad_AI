# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Seats, invites, joining, roles and devices (ADR 0014, decisions 16-20).

A seat is bought at a level (the LocalLedger: the owner adds it by hand, no money moves). An invite offers one to a
named person with a one-time code. Joining with the code makes the member (or wakes the one already linked to their
person node), takes the seat and gives that device its own token, once. Codes and tokens are kept only as SHA-256
hashes; a token shows up in exactly one response, the join. Revoking a member or a device stops its tokens at once.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlencode

from .common import new_id, now_iso, parse_iso
from .db import loads
from .graph import GraphError
from .permissions import ALLOW, EMPLOYEE, LEVELS, MANAGER, OWNER, ROLES, Principal, View

DEVICE_PREFIX = "nct_"
INVITE_HOURS, INVITE_MAX_HOURS = 72, 7 * 24


HANDIN_DAYS = 14  # how long after a revoke a phone may still hand in what it recorded before it (question 2)


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def handin_ok(revoked_at: str | None, recorded_at: str | None) -> bool:
    """A revoked phone's recording is taken (held for an owner, never applied) only if it was made before the revoke
    and the phone hands it in within HANDIN_DAYS of it."""
    rev, rec = parse_iso(revoked_at), parse_iso(recorded_at)
    if rev is None or rec is None:
        return False
    return rec <= rev and datetime.now(timezone.utc) - rev <= timedelta(days=HANDIN_DAYS)


class SeatLedger(Protocol):
    """Where seats come from. A billing provider plugs in here later (its webhook calls on_event); nothing else in the
    brain changes. Choosing one is the owner's call (ADR 0014, decision 17)."""
    name: str

    def add(self, ws: str, role_level: int, count: int, *, external_ref: str | None = None,
            expires_at: str | None = None) -> list[str]: ...

    def remove(self, seat_id: str) -> None: ...

    def expire_due(self, now: str) -> list[str]: ...

    def on_event(self, event: dict) -> None: ...


class LocalLedger:
    """Seats the owner adds by hand: no provider, no money."""
    name = "local"

    def __init__(self, db):
        self.db = db

    def add(self, ws: str, role_level: int, count: int, *, external_ref: str | None = None,
            expires_at: str | None = None) -> list[str]:
        ids = [new_id() for _ in range(count)]
        with self.db.tx():
            for sid in ids:
                self.db.insert("seats", {"id": sid, "workspace_id": ws, "role_level": role_level, "status": "available",
                                         "assigned_member_id": None, "purchased_at": now_iso(), "expires_at": expires_at,
                                         "external_ref": external_ref, "ledger": self.name})
        return ids

    def remove(self, seat_id: str) -> None:
        self.db.update("seats", {"id": seat_id}, {"status": "revoked"})

    def expire_due(self, now: str) -> list[str]:
        due = [r["id"] for r in self.db.query("select id from seats where expires_at is not null and expires_at<? and "
                                              "status in ('available','assigned')", (now,))]
        for sid in due:
            self.db.update("seats", {"id": sid}, {"status": "expired"})
        return due

    def on_event(self, event: dict) -> None:
        raise NotImplementedError("no billing provider: seats are added by hand")


class People:
    def __init__(self, brain, ledger: SeatLedger | None = None):
        self.brain = brain
        self.db = brain.db
        self.graph = brain.graph
        self.ledger: SeatLedger = ledger or LocalLedger(brain.db)

    @staticmethod
    def _need(p: Principal, action: str, what: str, *, in_scope: bool = True) -> None:
        if p.decide(action, in_scope=in_scope) != ALLOW:
            raise PermissionError(f"you cannot {what}")

    # ================================================================ seats
    def add_seats(self, p: Principal, ws: str, role: str, count: int = 1) -> list[str]:
        self._need(p, "manage_seats", "add seats")
        if role not in ("manager", "employee") or not 1 <= count <= 100:
            raise GraphError("a seat is for a manager or an employee (owners need none), 1 to 100 at a time")
        return self.ledger.add(ws, LEVELS[role], count)

    def seats(self, p: Principal, ws: str) -> list[dict]:
        rows = self.db.query("select s.*, m.display_name as member_name from seats s left join members m "
                             "on m.id=s.assigned_member_id where s.workspace_id=? order by s.role_level, s.purchased_at",
                             (ws,))
        if p.level <= OWNER:
            return rows
        if p.level == MANAGER:  # the free employee seats they may invite into
            return [{k: r[k] for k in ("id", "role_level", "status")} for r in rows
                    if r["role_level"] == EMPLOYEE and r["status"] == "available"]
        return []

    def remove_seat(self, p: Principal, seat_id: str) -> dict:
        self._need(p, "manage_seats", "remove seats")
        s = self.db.one("select * from seats where id=?", (seat_id,))
        if s is None or s["workspace_id"] != p.workspace_id:
            raise KeyError(seat_id)
        with self.db.tx():
            if s["assigned_member_id"]:
                self._revoke_member(s["workspace_id"], s["assigned_member_id"], release=False)
            self.ledger.remove(seat_id)
        return {"removed": seat_id}

    def _free_seat(self, ws: str, level: int, prefer: str | None = None) -> dict | None:
        """An available seat that may hold this level: the one asked for, else the closest level."""
        if prefer:
            s = self.db.one("select * from seats where id=? and workspace_id=? and status='available' and role_level<=?",
                            (prefer, ws, level))
            if s:
                return s
        return self.db.one("select * from seats where workspace_id=? and status='available' and role_level<=? "
                           "order by role_level desc, purchased_at", (ws, level))

    # ================================================================ invites
    def invite(self, p: Principal, ws: str, *, name: str, role: str = "employee", contact: str | None = None,
               person_node_id: str | None = None, scope_node_ids: list[str] | None = None,
               hours: int = INVITE_HOURS, base_urls: list[str] | None = None, pin: str | None = None) -> dict:
        """An invite with a one-time code (returned here, once) for a seat that is free now."""
        if role not in ("manager", "employee"):
            raise GraphError("invite a manager or an employee")
        level = LEVELS[role]
        view = View(self.db, p, ws)
        scope = list(dict.fromkeys(scope_node_ids or []))
        for nid in scope + ([person_node_id] if person_node_id else []):
            if not view.rows(nid):
                raise GraphError("that branch is not on your map")
        if p.level > OWNER:  # a manager: employees only, into their own branches (ADR 0014, decision 2)
            if level != EMPLOYEE:
                raise PermissionError("only an owner can invite a manager")
            if p.scopes and (not scope or not all(view.in_scope(n) for n in scope)):
                raise PermissionError("invite them into the branches you manage")
        self._need(p, "invite", "invite people")
        if person_node_id and (self.graph.node(person_node_id) or {}).get("kind") != "person":
            raise GraphError("person_node_id is not a person on the map")
        seat = self._free_seat(ws, level)
        if seat is None:
            raise GraphError(f"no free {role} seat: an owner adds one in People & seats")
        code = secrets.token_urlsafe(9)
        hours = max(1, min(int(hours or INVITE_HOURS), INVITE_MAX_HOURS))
        row = {"id": new_id(), "workspace_id": ws, "seat_id": seat["id"], "code_hash": digest(code),
               "created_by": p.member_id, "created_at": now_iso(),
               "profile": {"name": name.strip()[:80], "role": role, "contact": contact,
                           "person_node_id": person_node_id, "scope_node_ids": scope},
               "expires_at": now_iso((datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp())}
        self.db.insert("invites", row)
        extra = {"f": pin} if pin else {}  # the TLS certificate the phone pins (https links only)
        links = [f"notecad://join?{urlencode({'u': u, 'c': code, 'w': ws, **(extra if u.startswith('https') else {})})}"
                 for u in (base_urls or [])]
        return {"invite": self._public_invite(row), "code": code, "links": links}

    @staticmethod
    def _public_invite(r: dict) -> dict:
        return {**{k: v for k, v in r.items() if k != "code_hash"}, "profile": loads(r.get("profile"), r.get("profile"))}

    def invites(self, p: Principal, ws: str) -> list[dict]:
        rows = self.db.query("select * from invites where workspace_id=? order by created_at desc", (ws,))
        if p.level > OWNER:
            rows = [r for r in rows if r["created_by"] == p.member_id]
        return [self._public_invite(r) for r in rows]

    def revoke_invite(self, p: Principal, invite_id: str) -> dict:
        r = self.db.one("select * from invites where id=?", (invite_id,))
        if r is None or r["workspace_id"] != p.workspace_id or (p.level > OWNER and r["created_by"] != p.member_id):
            raise KeyError(invite_id)
        self.db.update("invites", {"id": invite_id}, {"revoked_at": now_iso()})
        return {"revoked": invite_id}

    def _open_invite(self, code: str) -> dict:
        r = self.db.one("select * from invites where code_hash=?", (digest(code or ""),))
        exp = parse_iso(r["expires_at"]) if r else None
        if r is None or r["used_at"] or r["revoked_at"] or exp is None or exp < datetime.now(timezone.utc):
            raise KeyError("invite")  # one answer for wrong, used, revoked and late: nothing to probe
        return r

    def preview(self, code: str) -> dict:
        """What joining with this code means, shown on the phone before anything happens (a link is an offer)."""
        r = self._open_invite(code)
        prof = loads(r["profile"], {}) or {}
        ws = self.graph.workspace(r["workspace_id"]) or {}
        return {"workspace_id": r["workspace_id"], "workspace": ws.get("name"), "name": prof.get("name"),
                "role": prof.get("role"), "expires_at": r["expires_at"],
                "scope": [self.graph.path_titles(n) for n in prof.get("scope_node_ids") or [] if self.graph.node(n)]}

    # ================================================================ joining
    def join(self, code: str, device_name: str, platform: str | None = None) -> dict:
        """The one step that needs no token: the code is the proof. Makes (or wakes) the member, takes a seat, gives
        this device a token. In one transaction, so a code works once even if two phones try it together."""
        with self.db.tx():
            r = self._open_invite(code)
            ws = r["workspace_id"]
            prof = loads(r["profile"], {}) or {}
            level = LEVELS.get(prof.get("role") or "employee", EMPLOYEE)
            member = None
            if prof.get("person_node_id"):
                member = self.db.one("select * from members where workspace_id=? and person_node_id=?",
                                     (ws, prof["person_node_id"]))
            if member is not None and member["status"] == "active" and member["seat_id"]:
                seat_id = member["seat_id"]  # already in: a second device for them, no second seat
            else:
                seat = self._free_seat(ws, level, prefer=r["seat_id"])
                if seat is None:
                    raise GraphError("no free seat for this invite any more: ask the owner")
                seat_id = seat["id"]
                fields = {"role": ROLES[level], "level": level, "status": "active", "seat_id": seat_id,
                          "read_only": 0}
                if member is None:
                    member = {"id": new_id(), "workspace_id": ws, "user_id": None,
                              "display_name": prof.get("name") or "New member", "contact": prof.get("contact"),
                              "person_node_id": prof.get("person_node_id"), "created_at": now_iso(), **fields}
                    self.db.insert("members", member)
                else:
                    self.db.update("members", {"id": member["id"]}, {**fields, "contact": prof.get("contact")
                                                                     or member["contact"]})
                self.db.update("seats", {"id": seat_id}, {"status": "assigned", "assigned_member_id": member["id"]})
                self._set_scopes(ws, member["id"], prof.get("scope_node_ids") or [])
            token = DEVICE_PREFIX + secrets.token_urlsafe(32)
            device_id = new_id()
            self.db.insert("devices", {"id": device_id, "workspace_id": ws, "member_id": member["id"],
                                       "name": (device_name or "Phone").strip()[:60], "platform": (platform or "")[:20],
                                       "token_hash": digest(token), "created_at": now_iso(), "last_seen_at": now_iso()})
            self.db.update("invites", {"id": r["id"]}, {"used_at": now_iso(), "used_by_device": device_id})
        ws_row = self.graph.workspace(ws) or {}
        return {"token": token, "device_id": device_id, "member_id": member["id"],
                "name": member.get("display_name"), "role": ROLES[level], "level": level, "workspace_id": ws,
                "workspace": ws_row.get("name"), "seat_id": seat_id}

    def _set_scopes(self, ws: str, member_id: str, node_ids: list[str]) -> None:
        self.db.execute("delete from member_scopes where member_id=? and workspace_id=?", (member_id, ws))
        for nid in dict.fromkeys(node_ids):
            n = self.graph.node(nid)
            if n is None or n["workspace_id"] != ws:
                raise GraphError("a scope must be a branch of this business")
            self.db.insert("member_scopes", {"workspace_id": ws, "member_id": member_id, "node_id": nid,
                                             "created_at": now_iso()})

    # ================================================================ roles, scopes, revoking
    def set_role(self, p: Principal, ws: str, member_id: str, *, role: str | None = None,
                 scope_node_ids: list[str] | None = None) -> dict:
        """An owner changes someone's role (with a seat that holds it) or the branches they are bound to."""
        self._need(p, "set_role", "change roles")
        m = self.db.one("select * from members where id=? and workspace_id=?", (member_id, ws))
        if m is None:
            raise KeyError(member_id)
        with self.db.tx():
            if role is not None and role != m["role"]:
                if role not in ("owner", "manager", "employee"):
                    raise GraphError("a role is owner, manager or employee")
                level = LEVELS[role]
                if m["level"] == OWNER and level != OWNER and not self.db.one(
                        "select 1 from members where workspace_id=? and id<>? and level=1 and status='active'",
                        (ws, member_id)):
                    raise GraphError("the last owner of a business stays an owner")
                seat_id = m["seat_id"]
                if level == OWNER:  # owners need no seat: theirs goes back to the pool
                    if seat_id:
                        self.db.update("seats", {"id": seat_id}, {"status": "available", "assigned_member_id": None})
                    seat_id = None
                else:
                    cur = self.db.one("select * from seats where id=?", (seat_id,)) if seat_id else None
                    if cur is None or cur["role_level"] > level or cur["status"] != "assigned":
                        new = self._free_seat(ws, level)
                        if new is None:
                            raise GraphError(f"no free {role} seat: add one in People & seats")
                        if cur is not None:
                            self.db.update("seats", {"id": cur["id"]}, {"status": "available", "assigned_member_id": None})
                        self.db.update("seats", {"id": new["id"]}, {"status": "assigned", "assigned_member_id": member_id})
                        seat_id = new["id"]
                try:
                    self.db.update("members", {"id": member_id}, {"role": role, "level": level, "seat_id": seat_id})
                except Exception as e:  # the database's own guard
                    if "last owner" in str(e):
                        raise GraphError("the last owner of a business stays an owner") from None
                    raise
            if scope_node_ids is not None:
                self._set_scopes(ws, member_id, scope_node_ids)
        return self.db.one("select * from members where id=?", (member_id,)) or {}

    def revoke_member(self, p: Principal, ws: str, member_id: str) -> dict:
        """They leave: their devices stop at once (and wipe on the next contact); their seat is free again."""
        self._need(p, "manage_seats", "remove people")
        m = self.db.one("select * from members where id=? and workspace_id=?", (member_id, ws))
        if m is None:
            raise KeyError(member_id)
        try:
            with self.db.tx():
                self._revoke_member(ws, member_id, release=True)
        except Exception as e:
            if "last owner" in str(e):
                raise GraphError("the last owner of a business cannot be removed") from None
            raise
        return {"revoked": member_id}

    def _revoke_member(self, ws: str, member_id: str, *, release: bool) -> None:
        now = now_iso()
        self.db.update("members", {"id": member_id}, {"status": "revoked", "seat_id": None})
        self.db.execute("update devices set revoked_at=? where member_id=? and revoked_at is null", (now, member_id))
        if release:
            self.db.execute("update seats set status='available', assigned_member_id=null where assigned_member_id=? "
                            "and status='assigned'", (member_id,))

    # ================================================================ devices
    @staticmethod
    def _public_device(d: dict) -> dict:
        return {k: v for k, v in d.items() if k != "token_hash"}

    def devices(self, p: Principal, ws: str) -> list[dict]:
        rows = self.db.query("select d.*, m.display_name as member_name from devices d left join members m "
                             "on m.id=d.member_id where d.workspace_id=? order by d.created_at", (ws,))
        if p.level > OWNER:
            rows = [d for d in rows if d["member_id"] == p.member_id]
        return [self._public_device(d) for d in rows]

    def revoke_device(self, p: Principal, device_id: str) -> dict:
        d = self.db.one("select * from devices where id=?", (device_id,))
        if d is None or d["workspace_id"] != p.workspace_id or (p.level > OWNER and d["member_id"] != p.member_id):
            raise KeyError(device_id)
        self.db.update("devices", {"id": device_id}, {"revoked_at": d["revoked_at"] or now_iso()})
        return {"revoked": device_id}
