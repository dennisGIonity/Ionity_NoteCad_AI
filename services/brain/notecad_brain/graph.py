# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""The workspace graph: one tree of nodes (folders) plus cross-links (mind map), and the status roll-up."""
from __future__ import annotations

from typing import overload

from datetime import timedelta

import numpy as np

from .common import STATUS_RANK, new_id, now_iso, parse_iso, short_label, worst
from .db import Database, loads


class GraphError(ValueError):
    pass


class Graph:
    def __init__(self, db: Database):
        self.db = db

    # ================================================================ workspaces and members
    def create_workspace(self, name: str, *, persona: str | None = None, owner_name: str = "Owner",
                         owner_user: str | None = None, locale: str = "en-ZA", workspace_id: str | None = None) -> dict:
        ws = workspace_id or new_id()
        now = now_iso()
        with self.db.tx():
            self.db.insert("workspaces", {"id": ws, "name": name, "persona": persona, "locale": locale,
                                          "owner_user": owner_user, "created_at": now})
            root = self._insert_node(ws, None, name, "root", created_by="user")
            self.db.insert("members", {"id": new_id(), "workspace_id": ws, "user_id": owner_user,
                                       "display_name": owner_name, "role": "owner", "contact": None,
                                       "person_node_id": None, "created_at": now})
        return {"id": ws, "root_id": root}

    def workspace(self, ws: str) -> dict | None:
        return self.db.one("select * from workspaces where id=?", (ws,))

    def root(self, ws: str) -> dict:
        r = self.db.one("select * from nodes where workspace_id=? and parent_id is null", (ws,))
        if r is None:
            raise GraphError("workspace has no root")
        return self._row(dict(r))

    def add_member(self, ws: str, display_name: str, *, role: str = "editor", contact: str | None = None,
                   user_id: str | None = None, person_node_id: str | None = None) -> str:
        mid = new_id()
        self.db.insert("members", {"id": mid, "workspace_id": ws, "user_id": user_id, "display_name": display_name,
                                   "role": role, "contact": contact, "person_node_id": person_node_id,
                                   "created_at": now_iso()})
        return mid

    def members(self, ws: str) -> list[dict]:
        return self.db.query("select * from members where workspace_id=? order by created_at", (ws,))

    # ================================================================ nodes
    def _insert_node(self, ws: str, parent_id: str | None, title: str, kind: str, *, attributes: dict | None = None,
                     created_by: str = "user", node_id: str | None = None, sort_key: str = "m") -> str:
        nid = node_id or new_id()
        if parent_id:
            parent = self.db.one("select path, depth, workspace_id from nodes where id=?", (parent_id,))
            if parent is None or parent["workspace_id"] != ws:
                raise GraphError(f"parent {parent_id} not in workspace")
            path, depth = f"{parent['path']}/{short_label(nid)}", parent["depth"] + 1
        else:
            path, depth = short_label(nid), 0
        now = now_iso()
        self.db.insert("nodes", {"id": nid, "workspace_id": ws, "parent_id": parent_id, "path": path, "depth": depth,
                                 "sort_key": sort_key, "kind": kind, "title": title.strip()[:80], "summary": None,
                                 "attributes": attributes or {}, "status": "ok", "status_reason": None,
                                 "status_since": now, "display_status": "ok", "child_worst": "ok", "open_tasks": 0,
                                 "open_alerts": 0, "version": 1, "created_by": created_by, "created_at": now,
                                 "updated_at": now})
        return nid

    def add_node(self, ws: str, parent_id: str, title: str, kind: str = "topic", *, aliases: list[str] | None = None,
                 attributes: dict | None = None, created_by: str = "user", node_id: str | None = None) -> str:
        if kind == "root":
            raise GraphError("only one root per workspace")
        with self.db.tx():
            nid = self._insert_node(ws, parent_id, title, kind, attributes=attributes, created_by=created_by,
                                    node_id=node_id)
            for a in aliases or []:
                self.add_alias(nid, a)
        return nid

    @overload
    def _row(self, r: dict) -> dict: ...
    @overload
    def _row(self, r: None) -> None: ...
    def _row(self, r: dict | None) -> dict | None:
        if r is None:
            return None
        r = dict(r)
        r["attributes"] = loads(r.get("attributes"), {})
        return r

    def node(self, node_id: str) -> dict | None:
        return self._row(self.db.one("select * from nodes where id=?", (node_id,)))

    def nodes(self, ws: str) -> list[dict]:
        return [self._row(r) for r in self.db.query("select * from nodes where workspace_id=? order by path", (ws,))]

    def children(self, node_id: str) -> list[dict]:
        return [self._row(r) for r in self.db.query("select * from nodes where parent_id=? order by sort_key, title",
                                                    (node_id,))]

    def ancestors(self, node_id: str) -> list[dict]:
        out, n = [], self.node(node_id)
        while n and n["parent_id"]:
            n = self.node(n["parent_id"])
            out.append(n)
        return out

    def path_titles(self, node_id: str, sep: str = " > ", include_root: bool = False) -> str:
        """'Vehicles > Tractors > John Deere 9550 #1': one recursive query (it was one query per ancestor)."""
        chain = self.db.query("with recursive up(id, parent_id, title, kind, d) as ("
                              "select id, parent_id, title, kind, 0 from nodes where id=? union all "
                              "select n.id, n.parent_id, n.title, n.kind, up.d + 1 from nodes n join up on n.id = up.parent_id) "
                              "select title, kind from up order by d desc", (node_id,))
        return sep.join(c["title"] for c in chain if include_root or c["kind"] != "root")

    @staticmethod
    def paths(rows: list[dict], sep: str = " > ") -> dict[str, str]:
        """path_titles for every row at once, from rows already loaded (retrieval, the mind map): no queries."""
        by = {r["id"]: r for r in rows}
        memo: dict[str, str] = {}

        def path(nid: str) -> str:
            if nid in memo:
                return memo[nid]
            chain, cur = [], by.get(nid)
            while cur is not None and cur["id"] not in memo:
                chain.append(cur)
                cur = by.get(cur["parent_id"]) if cur["parent_id"] else None
            base = memo[cur["id"]] if cur is not None else ""
            for n in reversed(chain):
                own = "" if n["kind"] == "root" else n["title"]
                base = memo[n["id"]] = sep.join(x for x in (base, own) if x)
            return memo[nid]
        for r in rows:
            path(r["id"])
        return memo

    def spine(self, ws: str, max_depth: int = 2) -> list[dict]:
        return [self._row(r) for r in self.db.query(
            "select * from nodes where workspace_id=? and depth between 1 and ? order by path", (ws, max_depth))]

    def tree(self, ws: str) -> dict:
        rows = self.nodes(ws)
        by_id = {r["id"]: {**r, "children": []} for r in rows}
        root = None
        for r in rows:
            if r["parent_id"]:
                by_id[r["parent_id"]]["children"].append(by_id[r["id"]])
            else:
                root = by_id[r["id"]]
        return root or {}

    def rename(self, node_id: str, title: str) -> None:
        self.db.update("nodes", {"id": node_id}, {"title": title.strip()[:80], "updated_at": now_iso()})

    def move(self, node_id: str, new_parent_id: str) -> None:
        n, p = self.node(node_id), self.node(new_parent_id)
        if n is None or p is None or n["workspace_id"] != p["workspace_id"]:
            raise GraphError("unknown node")
        if p["path"] == n["path"] or p["path"].startswith(n["path"] + "/"):
            raise GraphError("cannot move a node under itself")
        old_parent = n["parent_id"]
        new_prefix = f"{p['path']}/{short_label(node_id)}"
        delta = p["depth"] + 1 - n["depth"]
        with self.db.tx():
            for d in self.db.query("select id, path, depth from nodes where workspace_id=? and (path=? or path like ?)",
                                   (n["workspace_id"], n["path"], n["path"] + "/%")):
                self.db.update("nodes", {"id": d["id"]}, {"path": new_prefix + d["path"][len(n["path"]):],
                                                          "depth": d["depth"] + delta})
            self.db.update("nodes", {"id": node_id}, {"parent_id": new_parent_id, "updated_at": now_iso()})
            self.rollup([node_id] + ([old_parent] if old_parent else []))

    def delete_subtree(self, node_id: str) -> None:
        n = self.node(node_id)
        if n is None or n["kind"] == "root":
            raise GraphError("cannot delete")
        with self.db.tx():
            ids = [r["id"] for r in self.db.query(
                "select id from nodes where workspace_id=? and (path=? or path like ?) order by depth desc",
                (n["workspace_id"], n["path"], n["path"] + "/%"))]
            for i in ids:
                self.db.execute("delete from nodes where id=?", (i,))
            if n["parent_id"]:
                self.rollup([n["parent_id"]])

    # ================================================================ aliases and embeddings
    def add_alias(self, node_id: str, alias: str, weight: float = 1.0, lang: str | None = None) -> None:
        alias = alias.strip().lower()
        if not alias:
            return
        if self.db.one("select 1 from node_aliases where node_id=? and alias=?", (node_id, alias)):
            self.db.execute("update node_aliases set weight=weight+? where node_id=? and alias=?", (weight, node_id, alias))
        else:
            self.db.insert("node_aliases", {"node_id": node_id, "alias": alias, "lang": lang, "weight": weight})

    def aliases(self, node_id: str) -> list[str]:
        return [r["alias"] for r in self.db.query("select alias from node_aliases where node_id=? order by weight desc",
                                                  (node_id,))]

    def all_aliases(self, ws: str) -> dict[str, list[tuple[str, float]]]:
        out: dict[str, list[tuple[str, float]]] = {}
        for r in self.db.query("select a.node_id, a.alias, a.weight from node_aliases a join nodes n on n.id=a.node_id "
                               "where n.workspace_id=?", (ws,)):
            out.setdefault(r["node_id"], []).append((r["alias"], r["weight"]))
        return out

    def set_embedding(self, node_id: str, vec: np.ndarray, model: str) -> None:
        blob = np.asarray(vec, dtype=np.float32).tobytes()
        if self.db.one("select 1 from node_embeddings where node_id=?", (node_id,)):
            self.db.update("node_embeddings", {"node_id": node_id}, {"model": model, "vec": blob})
        else:
            self.db.insert("node_embeddings", {"node_id": node_id, "model": model, "vec": blob})

    def embeddings(self, ws: str, model: str) -> dict[str, np.ndarray]:
        rows = self.db.query("select e.node_id, e.vec from node_embeddings e join nodes n on n.id=e.node_id "
                             "where n.workspace_id=? and e.model=?", (ws, model))
        return {r["node_id"]: np.frombuffer(bytes(r["vec"]), dtype=np.float32) for r in rows}

    # ================================================================ status and roll-up
    def set_status(self, node_id: str, status: str, reason: str | None) -> dict:
        n = self.node(node_id)
        self.db.update("nodes", {"id": node_id}, {"status": status, "status_reason": reason, "status_since": now_iso(),
                                                  "version": n["version"] + 1, "updated_at": now_iso()})
        return {"status": n["status"], "status_reason": n["status_reason"]}

    def rollup(self, node_ids: list[str]) -> None:
        """Recompute counts, channel mirroring and echo dots for these nodes and every ancestor (blueprint 1.2)."""
        seen: set[str] = set()
        queue = [i for i in node_ids if i]
        order: list[str] = []
        while queue:
            nid = queue.pop()
            if nid in seen:
                continue
            seen.add(nid)
            order.append(nid)
            n = self.db.one("select parent_id from nodes where id=?", (nid,))
            if n and n["parent_id"]:
                queue.append(n["parent_id"])
        nodes = {i: self.db.one("select id, depth from nodes where id=?", (i,)) for i in order}
        for nid in sorted((i for i in order if nodes[i]), key=lambda i: -nodes[i]["depth"]):  # deepest first
            n = self.db.one("select * from nodes where id=?", (nid,))
            tasks = self.db.one("select count(*) as c from tasks where node_id=? and state='open'", (nid,))["c"]
            alerts = self.db.one("select count(*) as c from alerts where node_id=? and resolved_at is null", (nid,))["c"]
            kids = self.db.query("select kind, status, display_status, child_worst from nodes where parent_id=?", (nid,))
            channel_status = [k["display_status"] for k in kids if k["kind"] == "channel"]
            display = worst(n["status"], *channel_status) if channel_status else n["status"]
            child_worst = worst("ok", *[worst(k["display_status"], k["child_worst"]) for k in kids])
            if STATUS_RANK[child_worst] < STATUS_RANK["ok"]:
                child_worst = "ok"
            self.db.update("nodes", {"id": nid}, {"open_tasks": tasks, "open_alerts": alerts, "display_status": display,
                                                  "child_worst": child_worst})

    def decay(self, ws: str, now_dt=None) -> int:
        """Info rings fade after 24 h, done marks after 48 h (server-side so every device agrees)."""
        from datetime import datetime, timezone
        now_dt = now_dt or datetime.now(timezone.utc)
        changed = []
        for n in self.db.query("select id, status, status_since, open_alerts from nodes where workspace_id=? "
                               "and status in ('info','done')", (ws,)):
            since = parse_iso(n["status_since"])
            if since is None:  # a row synced without a time: nothing to fade from
                continue
            age = now_dt - since
            if (n["status"] == "info" and age > timedelta(hours=24)) or (n["status"] == "done" and age > timedelta(hours=48)):
                self.db.update("nodes", {"id": n["id"]}, {"status": "ok", "status_reason": None,
                                                          "status_since": now_iso(now_dt.timestamp())})
                changed.append(n["id"])
        if changed:
            self.rollup(changed)
        return len(changed)
