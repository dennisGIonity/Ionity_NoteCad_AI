# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Step 3: find the nodes an event is probably about. Fuzzy alias match + embeddings + one hop of the graph."""
from __future__ import annotations

import hashlib
import re

import numpy as np
from rapidfuzz import fuzz

from .graph import Graph

STOP = {"the", "a", "an", "and", "of", "in", "on", "at", "to", "is", "was", "die", "en", "van", "op", "my",
        "our", "ons", "just", "net", "it", "its", "this", "that"}


def _node_text(n: dict, path: str, aliases: list[str]) -> str:
    parts = [path, n["title"]] + aliases
    if n.get("summary"):
        parts.append(n["summary"])
    return " | ".join(parts)


_NUM = re.compile(r"\b\d+\b")
_TOK = re.compile(r"[\wÀ-ÿ']+")


def _fuzzy(event: str, names: list[tuple[str, float]]) -> float:
    """How well the owner's words name this node. A whole-phrase hit scores highest; otherwise every word of the
    name has to be heard (close spelling allowed), so 'Health Alerts' does not match 'healthy'."""
    ev = event.lower()
    ev_clean = " " + re.sub(r"[^\w\s]", " ", ev) + " "
    ev_toks = [t for t in _TOK.findall(ev) if len(t) >= 3]
    best = 0.0
    for name, weight in names:
        name = name.lower().strip()
        if len(name) < 3 or name in STOP:
            continue
        if f" {name} " in ev_clean:
            s = 0.9 + 0.1 * min(len(name) / 16, 1.0)  # whole-phrase hit; longer phrases are more specific
        else:
            toks = [t for t in _TOK.findall(name) if len(t) >= 3 and t not in STOP] or [name]
            hits = []
            for t in toks:
                r = max((fuzz.ratio(t, e) for e in ev_toks), default=0)
                if r < 88 and len(t) >= 4 and any(len(e) >= 4 and (t in e or e in t) for e in ev_toks):
                    r = 90  # Afrikaans compounds: "pomp" is heard in "hoofpomp", "boorgat" in "boorgatpomp"
                hits.append(r / 100.0 if r >= 88 else 0.0)
            s = sum(hits) / len(toks) * 0.88
            if len(toks) == 1 and len(toks[0]) <= 4:
                s *= 0.85  # short single words match too easily
        s *= min(1.0, 0.85 + 0.15 * min(weight, 2.0) / 2.0)
        best = max(best, s)
    return best


class Retriever:
    def __init__(self, graph: Graph, embedder=None, top_k: int = 8, max_candidates: int = 12):
        self.graph = graph
        self.embedder = embedder
        self.top_k = top_k
        self.max_candidates = max_candidates

    def _ensure_embeddings(self, ws: str, nodes: list[dict], paths: dict[str, str],
                           aliases: dict[str, list[tuple[str, float]]]) -> dict[str, np.ndarray]:
        if self.embedder is None:
            return {}
        have = {r["node_id"]: r["model"] for r in self.graph.db.query(
            "select e.node_id, e.model from node_embeddings e join nodes n on n.id=e.node_id where n.workspace_id=?", (ws,))}
        out: dict[str, np.ndarray] = {}
        for n in nodes:
            text = _node_text(n, paths[n["id"]], [a for a, _ in aliases.get(n["id"], [])])
            tag = f"{self.embedder.name}#{hashlib.sha1(text.encode()).hexdigest()[:10]}"
            if have.get(n["id"]) != tag:
                self.graph.set_embedding(n["id"], self.embedder.embed_doc(text), tag)
        for r in self.graph.db.query("select e.node_id, e.vec from node_embeddings e join nodes n on n.id=e.node_id "
                                     "where n.workspace_id=?", (ws,)):
            out[r["node_id"]] = np.frombuffer(bytes(r["vec"]), dtype=np.float32)
        return out

    def neighbours(self, node_id: str) -> list[tuple[str, str]]:
        """One hop around a node: parent, children and cross-links, as (node_id, how)."""
        n = self.graph.node(node_id)
        if n is None:
            return []
        out = [(n["parent_id"], "parent")] if n["parent_id"] and n["depth"] > 1 else []
        out += [(c["id"], "channel" if c["kind"] == "channel" else "child") for c in self.graph.children(node_id)]
        for e in self.graph.db.query("select src_id, dst_id, edge_type from edges where src_id=? or dst_id=?",
                                     (node_id, node_id)):
            out.append((e["dst_id"] if e["src_id"] == node_id else e["src_id"], e["edge_type"]))
        return out

    def candidates(self, ws: str, event: str, anchor: str | None = None) -> list[dict]:
        """anchor: the node the owner had open on the map while recording. It and its 1-hop neighbours are
        boosted, so "needs new tyres" said on the Tractors node lands there, but a thing named outright still wins."""
        nodes = [n for n in self.graph.nodes(ws) if n["kind"] != "root"]
        if not nodes:
            return []
        by_id = {n["id"]: n for n in nodes}
        paths = {n["id"]: self.graph.path_titles(n["id"]) for n in nodes}
        aliases = self.graph.all_aliases(ws)
        vecs = self._ensure_embeddings(ws, nodes, paths, aliases)
        q = self.embedder.embed_query(event) if (self.embedder is not None and vecs) else None
        ev_nums = set(_NUM.findall(event))
        scored = []
        for n in nodes:
            names = [(n["title"], 2.0)] + aliases.get(n["id"], [])
            fz = _fuzzy(event, names)
            em = float(np.dot(q, vecs[n["id"]])) if q is not None and n["id"] in vecs else 0.0
            # embeddings from small models sit around 0.2-0.6; stretch them onto the fuzzy scale
            em_s = max(0.0, min(1.0, (em - 0.15) / 0.45)) if q is not None else 0.0
            score = max(fz * 0.95, em_s) + (0.05 if fz > 0.6 and em_s > 0.5 else 0.0)
            node_nums = set(_NUM.findall(n["title"]))
            alias_nums = [set(_NUM.findall(a)) for a, _ in aliases.get(n["id"], [])]
            if ev_nums and node_nums and not (node_nums & ev_nums) and not any(x and x <= ev_nums for x in alias_nums):
                score = min(score, 0.45)  # "field 704" is not Field South 705, however alike they read
            elif ev_nums and node_nums - ev_nums and not any(x and x <= ev_nums for x in alias_nums):
                score = min(score, 0.62)  # "John Deere 9550 number 1": #2 shares 9550 but its own number was not said
            scored.append((round(min(score, 1.0), 3), n["id"], round(fz, 3), round(em, 3)))
        scored.sort(reverse=True)
        top = scored[: self.top_k]
        picked: dict[str, dict] = {}
        for score, nid, fz, em in top:
            picked[nid] = {"score": score, "fuzzy": fz, "embedding": em, "via": None}
        # one hop: channel children (Maintenance, Health Alerts), cross-links and the parent of the best hits
        for score, nid, _, _ in top[:3]:
            for c in self.graph.children(nid):
                if c["kind"] == "channel" and c["id"] not in picked:
                    picked[c["id"]] = {"score": round(score * 0.9, 3), "fuzzy": 0, "embedding": 0, "via": f"channel of {by_id[nid]['title']}"}
            for e in self.graph.db.query("select src_id, dst_id, edge_type from edges where src_id=? or dst_id=?", (nid, nid)):
                other = e["dst_id"] if e["src_id"] == nid else e["src_id"]
                if other in by_id and other not in picked:
                    picked[other] = {"score": round(score * 0.6, 3), "fuzzy": 0, "embedding": 0,
                                     "via": f"1-hop: {e['edge_type']} {by_id[nid]['title']}"}
        if anchor and anchor in by_id:
            a = picked.setdefault(anchor, {"score": 0.0, "fuzzy": 0, "embedding": 0, "via": None})
            a["score"] = round(min(1.0, max(a["score"], 0.62) + 0.1), 3)
            a["via"] = "anchor: open on the map while recording"
            for nid, how in self.neighbours(anchor):
                if nid not in by_id:
                    continue
                b = picked.setdefault(nid, {"score": 0.0, "fuzzy": 0, "embedding": 0, "via": None})
                floor = 0.6 if how == "channel" else 0.45
                b["score"] = round(min(1.0, max(b["score"], floor) + 0.05), 3)
                b["via"] = b["via"] or f"anchor 1-hop: {how} of {by_id[anchor]['title']}"
        ranked = sorted(picked.items(), key=lambda kv: kv[1]["score"], reverse=True)[: self.max_candidates]
        out = []
        for nid, s in ranked:
            n = by_id[nid]
            out.append({"node_id": nid, "path": paths[nid], "title": n["title"], "kind": n["kind"], "status": n["status"],
                        "aliases": [a for a, _ in aliases.get(nid, [])][:6], "summary": n.get("summary"),
                        "attributes": n["attributes"], "parent_id": n["parent_id"], **s})
        return out
