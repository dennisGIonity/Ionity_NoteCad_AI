# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""What roles cost (ADR 0014, decision 31): the 2,000-node synthetic farm (tools/seed_synthetic_farm.py) in memory,
with Admin > Finance restricted to owners, timed as the owner, an employee and an employee bound to one area. Needs
no running brain and touches no database on disk.

    .venv\\Scripts\\python.exe tools\\perf_roles.py                       # print the table
    .venv\\Scripts\\python.exe tools\\perf_roles.py --out ..\\..\\docs\\perf\\roles.json
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[2] / "companion"))
sys.path.insert(0, str(HERE.parent))

from notecad_brain.config import Settings  # noqa: E402
from notecad_brain.permissions import View, load_principal, owner_principal  # noqa: E402
from notecad_brain.pipeline import Brain  # noqa: E402
from notecad_brain.routers import RouterChain, RulesRouter  # noqa: E402
from seed_synthetic_farm import seed  # noqa: E402


def median_ms(fn, runs: int) -> float:
    fn()  # warm (caches, vectors)
    out = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(out), 2)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", type=int, default=2000)
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--out")
    a = ap.parse_args()
    from notecad_companion.embed import HashEmbedder
    s = Settings()
    s.db_url, s.worker, s.stt_engines = "sqlite:///:memory:", False, ""
    b = Brain(s, routers=RouterChain([RulesRouter()]), embedder=HashEmbedder(256), stt=None)
    ws = "perf-roles"
    info = seed(b.db, ws, a.nodes, random.Random(7))
    g = b.graph
    area = {n["title"]: n["id"] for n in g.nodes(ws) if n["depth"] == 1}
    finance = next(n["id"] for n in g.nodes(ws) if n["title"] == "Finance")
    emp = g.add_member(ws, "Thandi", role="employee")
    scoped = g.add_member(ws, "Lerato", role="employee")
    b.db.insert("member_scopes", {"workspace_id": ws, "member_id": scoped, "node_id": area["Irrigation"],
                                  "created_at": "2026-10-29T08:00:00Z"})
    t0 = time.perf_counter()
    g.set_visibility(finance, "owner", 1)
    finance_ms = (time.perf_counter() - t0) * 1000
    fields = [n for n in g.nodes(ws) if n["path"].startswith(g.node(area["Fields"])["path"])]
    t0 = time.perf_counter()
    g.set_visibility(area["Fields"], "manager", 1)
    branch_ms = (time.perf_counter() - t0) * 1000
    g.set_visibility(area["Fields"], "all", 1)
    who = {"owner": owner_principal(b.db, ws), "employee": load_principal(b.db, ws, emp),
           "scoped employee": load_principal(b.db, ws, scoped)}
    rows = []
    for name, p in who.items():
        rows.append({"viewer": name,
                     "view_ms": median_ms(lambda p=p: View(b.db, p, ws), a.runs),
                     "mindmap_ms": median_ms(lambda p=p: b.mindmap(ws, view=View(b.db, p, ws)), a.runs),
                     "retrieval_ms": median_ms(lambda p=p: b.retriever.candidates(ws, "check the oil on tractor unit 12",
                                                                                  view=View(b.db, p, ws)), a.runs),
                     "digest_ms": median_ms(lambda p=p: b.digest(ws, view=View(b.db, p, ws)), a.runs),
                     "nodes_seen": len(b.mindmap(ws, view=View(b.db, p, ws))["nodes"])})
    out = {"nodes": info["nodes"], "tasks": info["tasks"], "alerts": info["alerts"], "runs": a.runs,
           "restrict_finance_ms": round(finance_ms, 2), "restrict_branch_ms": round(branch_ms, 2),
           "branch_nodes": len(fields), "viewers": rows}
    print(json.dumps(out, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
