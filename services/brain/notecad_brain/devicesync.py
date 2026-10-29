# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""A member's device copy (ADR 0014, decision 21): devices are clients, not workers.

  snapshot   everything the member may see now, and a cursor
  pull       what changed since the cursor, as they may see it now:
               rows        the current row of each table that changed (contact details, token and code hashes and
                           audio paths left out; nodes with roll-ups worked out from what they see)
               tombstones  H <node>: they could see it and now cannot: drop it, its subtree and all that hangs off
                           it, cached audio included. D <table, key>: a row that went away (a capture too restricted
                           for them now among them)
               reset       they may see more than before (a branch opened, a role or scope changed) or this brain is
                           not the one that gave the cursor: wipe the copy and take a new snapshot

The cursor is opaque to the device: this brain's worker id and journal epoch, the journal position, the position
in view_changes (every change of a node's level or path on this brain, recorded by a trigger so changes that
arrive by sync count too) and a hash of the member's role and scope.
"""
from __future__ import annotations

import hashlib

from .common import now_iso
from .db import loads
from .mindmap import as_seen
from .permissions import EMPLOYEE, MANAGER, OWNER, Principal, View, under
from .sync import TABLES, Change

SNAPSHOT_TABLES = ["workspaces", "members", "member_scopes", "seats", "invites", "devices", "nodes", "node_aliases",
                   "edges", "captures", "capture_events", "notes", "tasks", "alerts", "profile_facts", "inbox",
                   "notifications"]
HIDDEN_COLUMNS = {"captures": {"audio_path"}, "devices": {"token_hash"}, "invites": {"code_hash"}}


def epoch(p: Principal) -> str:
    """Changes when what the member may see could change: their level, scope, status or read-only flag."""
    raw = f"{p.level}|{int(p.read_only)}|{int(p.active)}|{','.join(sorted(p.scopes))}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def sees_at(p: Principal, path: str | None, eff: int | None) -> bool:
    """Could this member see a node with this path and level (title and kind: path stubs count)?"""
    if path is None or eff is None or not p.active:
        return False
    if p.level <= OWNER:
        return True
    if p.level > eff:
        return False
    if p.level < EMPLOYEE or not p.scopes:
        return True
    return any(under(path, s) or under(s, path) for s in p.scopes)


class DeviceSync:
    def __init__(self, brain):
        self.brain = brain
        self.db = brain.db

    # ---------------------------------------------------------------- cursor
    def _cursor(self, p: Principal, seq: int, vseq: int) -> str:
        j = self.brain.journal
        return f"{j.worker_id}|{j.epoch}|{seq}|{vseq}|{epoch(p)}"

    def _parse(self, cursor: str | None) -> tuple[int, int] | None:
        parts = (cursor or "").split("|")
        j = self.brain.journal
        if len(parts) != 5 or parts[0] != j.worker_id or parts[1] != j.epoch:
            return None
        try:
            return int(parts[2]), int(parts[3])
        except ValueError:
            return None

    def _vtop(self, ws: str) -> int:
        r = self.db.one("select max(seq) as s from view_changes where ws=?", (ws,))
        return int((r or {}).get("s") or 0)

    # ---------------------------------------------------------------- rows as the member may have them
    def _clean(self, tbl: str, row: dict) -> dict:
        drop = HIDDEN_COLUMNS.get(tbl, set())
        return {k: (bytes(v).hex() if isinstance(v, (bytes, memoryview)) else v) for k, v in row.items() if k not in drop}

    def _keep(self, tbl: str, row: dict, view: View) -> dict | None:
        """The row as this member may hold it on their device, or None."""
        p = view.p
        if tbl == "workspaces":
            return row
        if tbl == "members":
            return view.member(row)
        if tbl == "member_scopes":
            return row if p.level <= MANAGER or row["member_id"] == p.member_id else None
        if tbl == "seats":
            if p.level <= OWNER or (p.level == MANAGER and row["role_level"] == EMPLOYEE and row["status"] == "available"):
                return row
            return None
        if tbl in ("invites", "devices"):
            mine = row.get("created_by" if tbl == "invites" else "member_id") == p.member_id
            return row if p.level <= OWNER or mine else None
        if tbl in ("notes", "tasks", "alerts", "node_aliases"):
            return row if view.rows(row["node_id"]) else None
        if tbl == "edges":
            return row if view.edge(row["src_id"], row["dst_id"]) else None
        if tbl == "captures":
            return row if view.capture(row) else None
        if tbl == "capture_events":
            cap = self.db.one("select member_id, eff_level from captures where id=?", (row["capture_id"],))
            return row if cap and view.capture(cap) else None
        if tbl == "profile_facts":
            return row if view.fact(row.get("visibility")) else None
        if tbl == "inbox":
            return row if view.inbox(row) else None
        if tbl == "notifications":
            return row if row["member_id"] == p.member_id or p.level <= OWNER else None
        return None  # action_log (read it through /audit), route_corrections, anything newer: not on devices

    def _nodes(self, ws: str, view: View) -> dict[str, dict]:
        rows = self.brain.graph.nodes(ws)
        if not view.all:
            rows = as_seen(rows, view)
        out = {}
        for n in rows:
            n = dict(n)
            n["attributes"] = n.get("attributes") or {}
            out[n["id"]] = n
        return out

    # ---------------------------------------------------------------- snapshot
    def snapshot(self, p: Principal) -> dict:
        ws = str(p.workspace_id)
        view = View(self.db, p, ws)
        seq = self.brain.journal.last_seq()
        vseq = self._vtop(ws)
        tables: dict[str, list[dict]] = {}
        for t in SNAPSHOT_TABLES:
            if t == "nodes":
                tables[t] = [self._clean(t, n) for n in self._nodes(ws, view).values()]
                continue
            if t == "workspaces":
                rows = self.db.query("select * from workspaces where id=?", (ws,))
            elif t == "node_aliases":
                rows = self.db.query("select a.* from node_aliases a join nodes n on n.id=a.node_id where n.workspace_id=?",
                                     (ws,))
            elif t == "capture_events":
                rows = self.db.query("select e.* from capture_events e join captures c on c.id=e.capture_id "
                                     "where c.workspace_id=?", (ws,))
            else:
                rows = self.db.query(f"select * from {t} where workspace_id=?", (ws,))
            tables[t] = [self._clean(t, k) for k in (self._keep(t, r, view) for r in rows) if k is not None]
        return {"reset": True, "workspace_id": ws, "tables": tables, "cursor": self._cursor(p, seq, vseq),
                "at": now_iso()}

    # ---------------------------------------------------------------- pull
    def pull(self, p: Principal, cursor: str | None, limit: int = 500) -> dict:
        ws = str(p.workspace_id)
        parsed = self._parse(cursor)
        if parsed is None or (cursor or "").split("|")[4] != epoch(p):
            return {"reset": True}
        seq, vseq = parsed
        hidden: list[str] = []
        moves = self.db.query("select * from view_changes where ws=? and seq>? order by seq", (ws, vseq))
        for v in moves:
            before, after = sees_at(p, v["old_path"], v["old_eff"]), sees_at(p, v["new_path"], v["new_eff"])
            if after and not before:
                return {"reset": True}  # more to see: a fresh snapshot is simpler and exact
            if before and not after:
                hidden.append(v["node_id"])
        vtop = moves[-1]["seq"] if moves else vseq
        rows = self.db.query("select * from sync_changes where seq>? and ws=? order by seq limit ?", (seq, ws, limit + 1))
        more = len(rows) > limit
        rows = rows[:limit]
        top = rows[-1]["seq"] if rows else self.brain.journal.last_seq() if not more else seq
        view = View(self.db, p, ws)
        nodes: dict[str, dict] | None = None
        out: dict[tuple[str, str], dict] = {}  # the latest of each row in this page
        for r in rows:
            ch = Change.of({**r, "origin_seq": r.get("origin_seq") or r["seq"]})
            if ch.tbl not in TABLES:
                continue
            key = (ch.tbl, ch.pk)
            if ch.tbl == "nodes":
                if ch.op == "D":
                    if p.level <= (ch.vis or EMPLOYEE):
                        out[key] = {"op": "H", "tbl": "nodes", "pk": ch.pk}
                    continue
                if nodes is None:
                    nodes = self._nodes(ws, view)
                n = nodes.get(ch.pk)
                if n is not None and view.node(ch.pk):
                    out[key] = {"op": "U", "tbl": "nodes", "pk": ch.pk, "row": self._clean("nodes", n)}
                continue
            if ch.op == "D":
                if p.level <= (ch.vis or EMPLOYEE):
                    out[key] = {"op": "D", "tbl": ch.tbl, "pk": ch.pk}
                continue
            cur = self.brain.journal._current(ch.tbl, ch.pk)
            if cur is None:
                continue  # gone since: its delete is further on
            kept = self._keep(ch.tbl, cur, view)
            if kept is not None:
                out[key] = {"op": "U", "tbl": ch.tbl, "pk": ch.pk, "row": self._clean(ch.tbl, kept)}
            elif ch.tbl == "captures" and self._had(ch, p):
                out[key] = {"op": "D", "tbl": "captures", "pk": ch.pk}  # too restricted for them now: and its audio
        changes = list(out.values())
        return {"reset": False, "changes": changes,
                "tombstones": [{"op": "H", "tbl": "nodes", "pk": n} for n in dict.fromkeys(hidden)],
                "cursor": self._cursor(p, top, vtop), "more": more}

    def _had(self, ch: Change, p: Principal) -> bool:
        """Could the member see this capture before this change? (Its previous journaled level, or theirs.)"""
        prev = self.db.one("select row, vis from sync_changes where tbl='captures' and pk=? and seq<? "
                           "order by seq desc limit 1", (ch.pk, ch.seq))
        if prev is None:
            return False
        row = loads(prev["row"], {}) or {}
        return row.get("member_id") == p.member_id or p.level <= (prev["vis"] or EMPLOYEE)
