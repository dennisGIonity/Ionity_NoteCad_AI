# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Step 6: write one event's actions in one transaction, with an inverse for every change (Undo) and an
action_log row carrying the provenance."""
from __future__ import annotations

import json

from . import delegate
from .common import PROVENANCE, new_id, now_iso
from .db import Database, loads
from .graph import Graph

ALREADY = "already applied"


class Applier:
    def __init__(self, db: Database, graph: Graph):
        self.db = db
        self.graph = graph

    def apply(self, ws: str, capture_id: str | None, event_idx: int | None, actions: list[dict], actor: str,
              extra_provenance: dict | None = None) -> dict:
        if capture_id is not None and self.db.one(
                "select 1 from action_log where capture_id=? and event_idx=? and undone_at is null", (capture_id, event_idx)):
            return {"status": ALREADY, "applied": []}
        tmp: dict[str, str] = {}
        touched: set[str] = set()
        log: list[tuple[dict, dict]] = []
        notes = tasks = alerts = 0
        delegated: list[dict] = []
        source = actor.split(":")[0]

        def ref(x: str) -> str:
            return tmp.get(x, x)

        with self.db.tx():
            for a in actions:
                t = a["type"]
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
                                             "created_at": now_iso()})
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
                                              "resolved_at": None, "created_at": now_iso()})
                    touched.add(nid)
                    alerts += 1
                    log.append(({**a, "node_id": nid, "alert_id": aid}, {"op": "delete", "table": "alerts", "id": aid}))
                    if a["severity"] == "critical":
                        for m in delegate.alert_audience(self.db, ws):
                            nn = delegate.notify(self.db, ws, m, "critical_alert",
                                                 {"alert_id": aid, "node_id": nid, "title": a["title"],
                                                  "path": self.graph.path_titles(nid)})
                            log.append(({"type": "notify", "id": nn}, {"op": "delete", "table": "notifications", "id": nn}))
                elif t == "create_task":
                    nid, tid = ref(a["node_id"]), new_id()
                    who = delegate.resolve(self.db, ws, a.get("assignee_hint"))
                    member = who["member_id"] if who else None
                    self.db.insert("tasks", {"id": tid, "workspace_id": ws, "node_id": nid, "capture_id": capture_id,
                                             "title": a["title"], "priority": a.get("priority", "normal"),
                                             "due_at": a.get("due_at"), "assignee_member": member,
                                             "assignee_hint": a.get("assignee_hint"), "state": "open", "done_at": None,
                                             "created_at": now_iso()})
                    touched.add(nid)
                    tasks += 1
                    log.append(({**a, "node_id": nid, "task_id": tid, "assignee": who},
                                {"op": "delete", "table": "tasks", "id": tid}))
                    if who and who.get("person_node_id"):
                        eid = self._link(ws, nid, who["person_node_id"], "assigned_to", source)
                        if eid:
                            log.append(({"type": "link_nodes", "edge_id": eid}, {"op": "delete", "table": "edges", "id": eid}))
                    target = member or delegate.owner_member(self.db, ws)
                    nn = delegate.notify(self.db, ws, target, "task_assigned" if member else "task_created",
                                         {"task_id": tid, "title": a["title"], "due_at": a.get("due_at"),
                                          "priority": a.get("priority", "normal"), "node_id": nid,
                                          "path": self.graph.path_titles(nid), "assignee_hint": a.get("assignee_hint")})
                    log.append(({"type": "notify", "id": nn}, {"op": "delete", "table": "notifications", "id": nn}))
                    if who:
                        delegated.append({"task_id": tid, "to": who["name"], "member_id": member})
                elif t == "update_attributes":
                    nid = ref(a["node_id"])
                    n = self.graph.node(nid)
                    old = dict(n["attributes"])
                    new = {**old, **(a.get("set") or {})}
                    for k, inc in (a.get("increment") or {}).items():
                        new[k] = (new.get(k) or 0) + inc
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
            self.graph.rollup(sorted(touched))
            prov = {**PROVENANCE, **(extra_provenance or {})}
            for seq, (act, inv) in enumerate(log):
                self.db.insert("action_log", {"id": new_id(), "workspace_id": ws, "capture_id": capture_id,
                                              "event_idx": event_idx, "seq": seq, "actor": actor, "action": act,
                                              "inverse": inv, "provenance": prov, "undone_at": None,
                                              "created_at": now_iso()})
        return {"status": "applied", "notes": notes, "tasks": tasks, "alerts": alerts, "delegated": delegated,
                "nodes": sorted(touched), "created": tmp}

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
        touched: set[str] = set()
        with self.db.tx():
            for r in rows:
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
                self.db.update("action_log", {"id": r["id"]}, {"undone_at": now_iso()})
            self.graph.rollup([t for t in touched if self.graph.node(t)])
        return len(rows)
