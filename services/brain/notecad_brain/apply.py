# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Step 6: write one event's actions in one transaction, with an inverse for every change (Undo) and an
action_log row carrying the provenance.

ADR 0014: every write in the brain comes through here, and here each action is judged against the permission matrix
for the member it acts for, after validation, so no router or model mistake can get past it. Allowed actions are
written; the rest come back to the caller to be proposed (an Inbox item for a manager or an owner) or refused (a
`refused` row in action_log and a polite answer)."""
from __future__ import annotations

import json

from . import delegate
from .common import PROVENANCE, STATUS_RANK, new_id, now_iso
from .db import Database, loads
from .graph import Graph
from .permissions import (ALLOW, CONFIRM, CONTEXT_EDGES, ENTRY_AUTHOR, MANAGER, OWNER, PROGRESS_KEYS, PROPOSE, REFUSE,
                          SYSTEM, SYSTEM_PRINCIPAL, VISIBILITY, Principal, View, load_principal, sees_row)

ALREADY = "already applied"
NOT_FOUND = "that is not on your map"
ENTRY_TABLES = ENTRY_AUTHOR  # table -> the column naming its author


def node_of(a: dict) -> str | None:
    """The node an action is about, for the audit log and for routing a proposal."""
    return a.get("node_id") or a.get("src_id") or a.get("parent_id")


class Applier:
    def __init__(self, db: Database, graph: Graph):
        self.db = db
        self.graph = graph

    # ================================================================ may this principal do it?
    def judge(self, view: View, a: dict, made: set[str]) -> tuple[str, str]:
        """ALLOW, CONFIRM, PROPOSE or REFUSE for one validated action, and why when it is not allowed. `made`: temp
        ids this call has already been allowed to create. A node the principal cannot see is "not found", never
        "not allowed", so a refusal says nothing about what is there."""
        p = view.p
        if p.level == SYSTEM:
            return ALLOW, ""
        t = a.get("type")

        def seen(nid: str | None) -> bool:
            return bool(nid) and (nid in made or view.rows(nid))

        def scope(nid: str | None) -> bool:
            return bool(nid) and (nid in made or view.in_scope(nid))

        nid = a.get("node_id")
        if t in ("append_note", "create_alert", "create_task"):
            return (p.decide(t, in_scope=scope(nid)), "") if seen(nid) else (REFUSE, NOT_FOUND)
        if t == "set_status":
            if not seen(nid):
                return REFUSE, NOT_FOUND
            cur = "ok" if nid in made else (self.graph.node(str(nid)) or {}).get("status", "ok")
            lowering = (STATUS_RANK.get(cur, 2) >= STATUS_RANK["routine_due"]
                        and STATUS_RANK.get(str(a.get("status")), 2) < STATUS_RANK.get(cur, 2))
            return p.decide("lower_status" if lowering else "raise_status", in_scope=scope(nid)), ""
        if t == "update_attributes":
            if not seen(nid):
                return REFUSE, NOT_FOUND
            keys = set(a.get("set") or {}) | set(a.get("increment") or {})
            return p.decide("progress" if keys <= PROGRESS_KEYS else "update_attributes", in_scope=scope(nid)), ""
        if t == "link_nodes":
            if not (seen(a.get("src_id")) and seen(a.get("dst_id"))):
                return REFUSE, NOT_FOUND
            what = "append_note" if a.get("edge_type") in CONTEXT_EDGES else "link_nodes"
            return p.decide(what, in_scope=scope(a["src_id"])), ""
        if t == "create_node":
            parent = a.get("parent_id")
            return (p.decide("create_node", in_scope=scope(parent)), "") if seen(parent) else (REFUSE, NOT_FOUND)
        if t == "upsert_profile_fact":
            return p.decide("profile_fact"), ""
        if t in ("rename_node", "delete_node", "add_alias"):
            if not seen(nid):
                return REFUSE, NOT_FOUND
            return p.decide("teach_alias" if t == "add_alias" else t, in_scope=scope(nid)), ""
        if t == "move_node":
            if not (seen(nid) and seen(a.get("parent_id"))):
                return REFUSE, NOT_FOUND
            return p.decide("move_node", in_scope=scope(nid) and scope(a["parent_id"])), ""
        if t == "set_visibility":
            if not seen(nid):
                return REFUSE, NOT_FOUND
            if p.level > OWNER:
                if VISIBILITY.get(a.get("visibility") or "", 0) < MANAGER:
                    return REFUSE, "only an owner can make a branch owner-only"
                if (self.graph.node(str(nid)) or {}).get("vis_set_by") == OWNER:
                    return REFUSE, "an owner set who can see this branch"
            return p.decide("set_visibility", in_scope=scope(nid)), ""
        if t in ("edit_note", "update_task", "resolve_alert", "delete_entry"):
            table = {"edit_note": "notes", "update_task": "tasks", "resolve_alert": "alerts"}.get(t) or a.get("table")
            if table not in ENTRY_TABLES:
                return REFUSE, "unknown entry"
            row = self.db.one(f"select * from {table} where id=?", (a.get("id"),))
            if row is None or not seen(row["node_id"]):
                return REFUSE, NOT_FOUND
            own = bool(p.member_id) and row.get(ENTRY_TABLES[table]) == p.member_id
            where = scope(row["node_id"])
            if t == "update_task":
                keys = {k for k in ("state", "assignee_member", "due_at", "title", "priority") if k in a}
                what = ("complete_task" if keys <= {"state"} else
                        "assign_task" if keys & {"assignee_member", "due_at"} else "edit_entry")
                return p.decide(what, in_scope=where, own=own,
                                assigned=bool(p.member_id) and row.get("assignee_member") == p.member_id), ""
            if t == "resolve_alert":
                return p.decide("resolve_alert", in_scope=where), ""
            return p.decide("edit_entry" if t == "edit_note" else "delete_entry", in_scope=where, own=own), ""
        return REFUSE, f"unknown action {t}"

    def member_sees(self, ws: str, member_id: str, node_id: str) -> bool:
        """Can a member see what hangs off this node (a task for them on it)?"""
        p = load_principal(self.db, ws, member_id)
        n = self.db.one("select path, eff_level from nodes where id=?", (node_id,))
        return p is not None and n is not None and sees_row(p, n["path"], n["eff_level"])

    # ================================================================ write
    def apply(self, ws: str, capture_id: str | None, event_idx: int | None, actions: list[dict], actor: str,
              extra_provenance: dict | None = None, *, principal: Principal = SYSTEM_PRINCIPAL, view: View | None = None,
              author: str | None = None, approved_by: str | None = None, confirmed: bool = False) -> dict:
        """principal: who decides (a member, or the brain itself). author: whose words these are, when not theirs (an
        approved proposal: the employee wrote it, the manager approved it). confirmed: an owner's CONFIRM action (a
        delete) was confirmed by them, so it is written instead of held."""
        if approved_by is None and capture_id is not None and self.db.one(
                "select 1 from action_log where capture_id=? and event_idx=? and undone_at is null", (capture_id, event_idx)):
            return {"status": ALREADY, "applied": [], "held": [], "refused": [], "notices": []}
        view = view or View(self.db, principal, ws)
        author = author or principal.member_id
        author_p = principal if author == principal.member_id else (load_principal(self.db, ws, author) or principal)
        author_level = None if author_p.level == SYSTEM else author_p.level

        # decide first: a new branch that is not allowed holds or refuses what was to go on it
        made: set[str] = set()
        blocked: dict[str, str] = {}
        plan: list[tuple[dict, str, str]] = []
        for a in actions:
            refs = [a.get(k) for k in ("node_id", "parent_id", "src_id", "dst_id") if a.get(k)]
            dep = next((blocked[r] for r in refs if r in blocked), None)
            if dep is not None:
                outcome, reason = dep, "it goes on a new branch that is not made yet"
            else:
                outcome, reason = self.judge(view, a, made)
                if outcome == CONFIRM:
                    outcome = ALLOW if confirmed else PROPOSE
            if a.get("type") == "create_node":
                if outcome == ALLOW:
                    made.add(a["temp_id"])
                else:
                    blocked[a["temp_id"]] = outcome
            plan.append((a, outcome, reason))

        tmp: dict[str, str] = {}
        touched: set[str] = set()
        relevel: list[str] = []
        log: list[tuple[dict, dict]] = []
        held: list[dict] = []
        refused: list[dict] = []
        notices: list[str] = []
        notes = tasks = alerts = 0
        delegated: list[dict] = []
        source = actor.split(":")[0]

        def ref(x: str) -> str:
            return tmp.get(x, x)

        acting = (principal.member_id, principal.level) if principal.level != SYSTEM else (None, None)
        with self.db.tx(), self.db.acting(*acting):
            for a, outcome, reason in plan:
                t = a["type"]
                if outcome == PROPOSE:
                    held.append(a)
                    continue
                if outcome == REFUSE:
                    refused.append({"type": t, "reason": reason})
                    log.append(({"type": "refused", "action": t, "reason": reason,
                                 "node_id": ref(node_of(a) or "") or None}, {"op": "none"}))
                    continue
                if t == "create_node":
                    nid = self.graph.add_node(ws, ref(a["parent_id"]), a["title"], a["kind"], aliases=a.get("aliases"),
                                              attributes=a.get("attributes"), created_by=source)
                    tmp[a["temp_id"]] = nid
                    touched.add(nid)
                    log.append(({**a, "node_id": nid}, {"op": "delete_node", "id": nid}))
                elif t == "append_note":
                    nid, note_id = ref(a["node_id"]), new_id()
                    self.db.insert("notes", {"id": note_id, "workspace_id": ws, "node_id": nid, "capture_id": capture_id,
                                             "body": a["text"], "tags": a.get("tags", []), "author": actor,
                                             "created_at": now_iso(), "member_id": author})
                    n = self.graph.node(nid)
                    if n["status"] == "ok":  # a fresh note shows as a thin info ring for 24 h
                        prev = self.graph.set_status(nid, "info", "new note")
                        log.append(({"type": "set_status", "node_id": nid, "status": "info", "auto": True},
                                    {"op": "set_status", "id": nid, **prev}))
                    touched.add(nid)
                    notes += 1
                    log.append(({**a, "node_id": nid, "note_id": note_id}, {"op": "delete", "table": "notes", "id": note_id}))
                elif t == "set_status":
                    nid = ref(a["node_id"])
                    prev = self.graph.set_status(nid, a["status"], a.get("reason"))
                    touched.add(nid)
                    log.append(({**a, "node_id": nid}, {"op": "set_status", "id": nid, **prev}))
                elif t == "create_alert":
                    nid, aid = ref(a["node_id"]), new_id()
                    self.db.insert("alerts", {"id": aid, "workspace_id": ws, "node_id": nid, "capture_id": capture_id,
                                              "severity": a["severity"], "category": a["category"], "title": a["title"],
                                              "resolved_at": None, "created_at": now_iso(), "member_id": author})
                    touched.add(nid)
                    alerts += 1
                    log.append(({**a, "node_id": nid, "alert_id": aid}, {"op": "delete", "table": "alerts", "id": aid}))
                    if a["severity"] == "critical":
                        for m in delegate.alert_audience(self.db, ws):
                            if not self.member_sees(ws, m, nid):
                                continue  # a critical alert on a restricted branch reaches only those who see it
                            nn = delegate.notify(self.db, ws, m, "critical_alert",
                                                 {"alert_id": aid, "node_id": nid, "title": a["title"],
                                                  "path": self.graph.path_titles(nid)})
                            log.append(({"type": "notify", "id": nn}, {"op": "delete", "table": "notifications", "id": nn}))
                elif t == "create_task":
                    nid, tid = ref(a["node_id"]), new_id()
                    who = delegate.resolve(self.db, ws, a.get("assignee_hint"))
                    member = who["member_id"] if who else None
                    if member and principal.level != SYSTEM and member != author and principal.decide(
                            "assign_task", in_scope=nid in tmp.values() or view.in_scope(nid)) != ALLOW:
                        # an employee's "Ask Thandi to ...": the task is made, the assignment waits for a manager
                        held.append({"type": "update_task", "id": tid, "assignee_member": member,
                                     "assignee_hint": a.get("assignee_hint"), "confidence": 1.0,
                                     "evidence": a.get("evidence", "")})
                        member = None
                    if member and not self.member_sees(ws, member, nid):
                        notices.append(f"{who['name'] if who else 'They'} cannot see {self.graph.path_titles(nid)}: "
                                       f"the task was not assigned to them")
                        member = None
                    self.db.insert("tasks", {"id": tid, "workspace_id": ws, "node_id": nid, "capture_id": capture_id,
                                             "title": a["title"], "priority": a.get("priority", "normal"),
                                             "due_at": a.get("due_at"), "assignee_member": member,
                                             "assignee_hint": a.get("assignee_hint"), "state": "open", "done_at": None,
                                             "created_at": now_iso(), "created_by_member": author})
                    touched.add(nid)
                    tasks += 1
                    log.append(({**a, "node_id": nid, "task_id": tid, "assignee": who if member else None},
                                {"op": "delete", "table": "tasks", "id": tid}))
                    if who and who.get("person_node_id") and (member or not who.get("member_id")):
                        eid = self._link(ws, nid, who["person_node_id"], "assigned_to", source)
                        if eid:
                            log.append(({"type": "link_nodes", "edge_id": eid, "node_id": nid},
                                        {"op": "delete", "table": "edges", "id": eid}))
                    target = member or delegate.owner_member(self.db, ws)
                    nn = delegate.notify(self.db, ws, target, "task_assigned" if member else "task_created",
                                         {"task_id": tid, "title": a["title"], "due_at": a.get("due_at"),
                                          "priority": a.get("priority", "normal"), "node_id": nid,
                                          "path": self.graph.path_titles(nid), "assignee_hint": a.get("assignee_hint")})
                    log.append(({"type": "notify", "id": nn, "node_id": nid},
                                {"op": "delete", "table": "notifications", "id": nn}))
                    if who and member:
                        delegated.append({"task_id": tid, "to": who["name"], "member_id": member})
                elif t == "update_attributes":
                    nid = ref(a["node_id"])
                    n = self.graph.node(nid)
                    old = dict(n["attributes"])
                    new = {**old, **(a.get("set") or {})}
                    for k, inc in (a.get("increment") or {}).items():
                        new[k] = (new.get(k) or 0) + inc
                    new = {k: v for k, v in new.items() if v is not None}  # null removes a number (the drawer's edit)
                    self.db.update("nodes", {"id": nid}, {"attributes": new, "version": n["version"] + 1,
                                                          "updated_at": now_iso()})
                    touched.add(nid)
                    log.append(({**a, "node_id": nid}, {"op": "attrs", "id": nid, "attributes": old}))
                elif t == "link_nodes":
                    eid = self._link(ws, ref(a["src_id"]), ref(a["dst_id"]), a["edge_type"], source)
                    if eid:
                        log.append(({**a, "edge_id": eid}, {"op": "delete", "table": "edges", "id": eid}))
                elif t == "upsert_profile_fact":
                    old = self.db.one("select * from profile_facts where workspace_id=? and key=?", (ws, a["key"]))
                    row = {"value": json.dumps(a["value"], ensure_ascii=False), "confidence": a.get("confidence", 1), "source": f"capture:{capture_id}",
                           "updated_at": now_iso()}
                    if old:
                        self.db.update("profile_facts", {"workspace_id": ws, "key": a["key"]}, row)
                    else:
                        self.db.insert("profile_facts", {"workspace_id": ws, "key": a["key"], **row})
                    log.append((a, {"op": "fact", "key": a["key"], "old": old}))
                elif t == "rename_node":
                    nid = ref(a["node_id"])
                    old = self.graph.node(nid)["title"]
                    self.graph.rename(nid, a["title"])
                    touched.add(nid)
                    log.append(({**a, "node_id": nid, "was": old}, {"op": "rename", "id": nid, "title": old}))
                elif t == "move_node":
                    nid = ref(a["node_id"])
                    n = self.graph.node(nid)
                    relevel += self.graph.move(nid, ref(a["parent_id"]))
                    touched.update(x for x in (nid, n["parent_id"]) if x)
                    log.append(({**a, "node_id": nid, "was": n["parent_id"]},
                                {"op": "move", "id": nid, "parent_id": n["parent_id"]}))
                elif t == "delete_node":
                    nid = ref(a["node_id"])
                    n = self.graph.node(nid)
                    self.graph.delete_subtree(nid)
                    if n["parent_id"]:
                        touched.add(n["parent_id"])
                    log.append(({**a, "node_id": n["parent_id"], "deleted": nid, "title": n["title"]}, {"op": "none"}))
                elif t == "add_alias":
                    nid = ref(a["node_id"])
                    alias, w = a["alias"].strip().lower(), float(a.get("weight", 1.0))
                    self.graph.add_alias(nid, alias, weight=w)
                    log.append(({**a, "node_id": nid}, {"op": "alias", "node_id": nid, "alias": alias, "weight": w}))
                elif t == "set_visibility":
                    nid = ref(a["node_id"])
                    old, changed = self.graph.set_visibility(nid, a["visibility"], principal.level or OWNER)
                    relevel += changed
                    log.append(({**a, "node_id": nid, "was": old}, {"op": "visibility", "id": nid, **old}))
                elif t == "edit_note":
                    row = self.db.one("select * from notes where id=?", (a["id"],))
                    self.db.update("notes", {"id": a["id"]}, {"body": a["text"]})
                    touched.add(row["node_id"])
                    log.append(({**a, "node_id": row["node_id"]},
                                {"op": "field", "table": "notes", "id": a["id"], "set": {"body": row["body"]}}))
                elif t == "update_task":
                    row = self.db.one("select * from tasks where id=?", (a["id"],))
                    fields: dict = {}
                    if a.get("state"):
                        fields.update(state=a["state"], done_at=now_iso() if a["state"] == "done" else None)
                    for k in ("due_at", "title", "priority"):
                        if k in a:
                            fields[k] = (a[k] or None) if k == "due_at" else a[k]
                    if a.get("assignee_member"):
                        fields["assignee_member"] = a["assignee_member"]
                        delegate.notify(self.db, ws, a["assignee_member"], "task_assigned",
                                        {"task_id": a["id"], "title": row["title"], "due_at": row["due_at"],
                                         "path": self.graph.path_titles(row["node_id"])})
                    if fields:
                        self.db.update("tasks", {"id": a["id"]}, fields)
                    touched.add(row["node_id"])
                    log.append(({**a, "node_id": row["node_id"]},
                                {"op": "field", "table": "tasks", "id": a["id"], "set": {k: row[k] for k in fields}}))
                elif t == "resolve_alert":
                    row = self.db.one("select * from alerts where id=?", (a["id"],))
                    self.db.update("alerts", {"id": a["id"]}, {"resolved_at": now_iso()})
                    log.append(({**a, "node_id": row["node_id"]},
                                {"op": "field", "table": "alerts", "id": a["id"], "set": {"resolved_at": None}}))
                    left = self.db.one("select count(*) as c from alerts where node_id=? and resolved_at is null",
                                       (row["node_id"],))
                    n = self.graph.node(row["node_id"])
                    if left["c"] == 0 and n["status"] in ("warning", "critical"):
                        prev = self.graph.set_status(row["node_id"], "ok", "alert resolved")
                        log.append(({"type": "set_status", "node_id": row["node_id"], "status": "ok", "auto": True},
                                    {"op": "set_status", "id": row["node_id"], **prev}))
                    touched.add(row["node_id"])
                elif t == "delete_entry":
                    row = self.db.one(f"select * from {a['table']} where id=?", (a["id"],))
                    self.db.execute(f"delete from {a['table']} where id=?", (a["id"],))
                    touched.add(row["node_id"])
                    log.append(({**a, "node_id": row["node_id"]}, {"op": "restore", "table": a["table"], "row": row}))
            self.graph.rollup(sorted(x for x in touched if self.graph.node(x)))
            if relevel:
                self.graph.relevel_captures(relevel)
            prov = {**PROVENANCE, **(extra_provenance or {})}
            for seq, (act, inv) in enumerate(log):
                self.db.insert("action_log", {"id": new_id(), "workspace_id": ws, "capture_id": capture_id,
                                              "event_idx": event_idx, "seq": seq, "actor": actor, "action": act,
                                              "inverse": inv, "provenance": prov, "undone_at": None,
                                              "created_at": now_iso(), "member_id": author,
                                              "member_level": author_level, "approved_by": approved_by,
                                              "node_id": act.get("node_id")})
        wrote = [a for a, outcome, _ in plan if outcome == ALLOW]
        return {"status": "applied" if wrote or not (held or refused) else "held" if held else "refused",
                "notes": notes, "tasks": tasks, "alerts": alerts, "delegated": delegated, "nodes": sorted(touched),
                "created": tmp, "held": held, "refused": refused, "notices": notices}

    def _link(self, ws: str, src: str, dst: str, edge_type: str, source: str) -> str | None:
        if self.db.one("select 1 from edges where src_id=? and dst_id=? and edge_type=?", (src, dst, edge_type)):
            return None
        eid = new_id()
        self.db.insert("edges", {"id": eid, "workspace_id": ws, "src_id": src, "dst_id": dst, "edge_type": edge_type,
                                 "weight": 1, "created_by": source})
        return eid

    # ================================================================ undo
    def _used_later(self, node_id: str) -> bool:
        """This capture's own rows on the node are already gone (Undo runs newest first), so anything left on it
        came from later captures or the owner, and deleting the node would take those with it."""
        return any(self.db.one(f"select 1 from {t} where {c}=? limit 1", (node_id,)) for t, c in
                   (("nodes", "parent_id"), ("notes", "node_id"), ("tasks", "node_id"), ("alerts", "node_id")))

    def undo(self, ws: str, capture_id: str) -> int:
        rows = self.db.query("select * from action_log where workspace_id=? and capture_id=? and undone_at is null "
                             "order by event_idx desc, seq desc", (ws, capture_id))
        return self.revert(rows)

    def revert(self, rows: list[dict]) -> int:
        """Run the inverses of these action_log rows, newest first (the order given), and mark them undone."""
        touched: set[str] = set()
        relevel: list[str] = []
        with self.db.tx():
            for r in rows:
                ws = r["workspace_id"]
                inv = loads(r["inverse"], {})
                op = inv.get("op")
                if op == "delete":
                    if inv["table"] in ("tasks", "alerts", "notes"):
                        row = self.db.one(f"select node_id from {inv['table']} where id=?", (inv["id"],))
                        if row:
                            touched.add(row["node_id"])
                    self.db.execute(f"delete from {inv['table']} where id=?", (inv["id"],))
                elif op == "delete_node":
                    n = self.graph.node(inv["id"])
                    if n and self._used_later(inv["id"]):
                        touched.add(inv["id"])  # a later note, task or child lives on it: keep the node
                    elif n:
                        if n["parent_id"]:
                            touched.add(n["parent_id"])
                        self.db.execute("delete from nodes where id=?", (inv["id"],))
                        touched.discard(inv["id"])
                elif op == "set_status":
                    self.db.update("nodes", {"id": inv["id"]}, {"status": inv["status"], "status_reason": inv["status_reason"],
                                                                "status_since": now_iso()})
                    touched.add(inv["id"])
                elif op == "attrs":
                    self.db.update("nodes", {"id": inv["id"]}, {"attributes": inv["attributes"], "updated_at": now_iso()})
                    touched.add(inv["id"])
                elif op == "fact":
                    old = inv.get("old")
                    if old:
                        self.db.update("profile_facts", {"workspace_id": ws, "key": inv["key"]},
                                       {"value": old["value"], "confidence": old["confidence"], "source": old["source"]})
                    else:
                        self.db.execute("delete from profile_facts where workspace_id=? and key=?", (ws, inv["key"]))
                elif op == "rename" and self.graph.node(inv["id"]):
                    self.graph.rename(inv["id"], inv["title"])
                    touched.add(inv["id"])
                elif op == "move" and self.graph.node(inv["id"]) and inv.get("parent_id") and self.graph.node(inv["parent_id"]):
                    relevel += self.graph.move(inv["id"], inv["parent_id"])
                    touched.add(inv["id"])
                elif op == "visibility" and self.graph.node(inv["id"]):
                    self.db.update("nodes", {"id": inv["id"]}, {"visibility": inv.get("visibility") or "all",
                                                                "vis_set_by": inv.get("vis_set_by")})
                    relevel += self.graph.recompute_levels(inv["id"])
                elif op == "alias":
                    self.db.execute("update node_aliases set weight=weight-? where node_id=? and alias=?",
                                    (inv["weight"], inv["node_id"], inv["alias"]))
                    self.db.execute("delete from node_aliases where node_id=? and alias=? and weight<=0.0001",
                                    (inv["node_id"], inv["alias"]))
                elif op == "field" and self.db.one(f"select 1 from {inv['table']} where id=?", (inv["id"],)):
                    self.db.update(inv["table"], {"id": inv["id"]}, inv["set"])
                    row = self.db.one(f"select node_id from {inv['table']} where id=?", (inv["id"],))
                    touched.add(row["node_id"])
                elif op == "restore" and not self.db.one(f"select 1 from {inv['table']} where id=?", (inv["row"]["id"],)):
                    self.db.insert(inv["table"], inv["row"])
                    touched.add(inv["row"]["node_id"])
                self.db.update("action_log", {"id": r["id"]}, {"undone_at": now_iso()})
            self.graph.rollup([t for t in touched if self.graph.node(t)])
            if relevel:
                self.graph.relevel_captures(relevel)
        return len(rows)
