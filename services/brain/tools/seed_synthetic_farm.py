# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""A large synthetic farm for performance work: 7 main areas, groups, assets and fields to about N nodes, with a mix
of statuses, open tasks and alerts so roll-ups, echo dots and fold badges have something to show.

    .venv\\Scripts\\python.exe tools\\seed_synthetic_farm.py                  # workspace perf-2000, 2,000 nodes
    .venv\\Scripts\\python.exe tools\\seed_synthetic_farm.py --nodes 500 --id perf-500
    .venv\\Scripts\\python.exe tools\\seed_synthetic_farm.py --remove          # archive first, then remove

Writes straight into the brain database (WAL lets the running brain keep serving). Deterministic for a given seed.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
ROOT = HERE.parents[3]

from notecad_brain.common import new_id, now_iso  # noqa: E402
from notecad_brain.db import Database  # noqa: E402
from notecad_brain.graph import Graph  # noqa: E402

AREAS = {
    "Vehicles": ("group", ["Tractors", "Bakkies", "Harvesters", "Trailers", "Sprayers"], "asset", "Unit"),
    "Fields": ("group", ["North Block", "South Block", "East Block", "West Block", "River Block", "Hill Block"], "field", "Field"),
    "Livestock": ("group", ["Cattle", "Sheep", "Goats", "Pigs", "Poultry"], "animal", "Tag"),
    "Irrigation": ("group", ["Pivots", "Boreholes", "Dams", "Pipelines", "Valves"], "asset", "Point"),
    "Infrastructure": ("group", ["Sheds", "Fencing", "Roads", "Power", "Housing"], "asset", "Item"),
    "Staff": ("group", ["Field Team", "Workshop", "Office", "Security"], "person", "Worker"),
    "Admin": ("group", ["Compliance", "Finance", "Contracts", "Insurance"], "topic", "File"),
}


def seed(db: Database, ws_id: str, total: int, rng: random.Random) -> dict:
    g = Graph(db)
    ws = g.create_workspace(f"Synthetic Farm ({total})", persona="farmer", owner_name="Perf", workspace_id=ws_id)
    root = ws["root_id"]
    groups: list[tuple[str, str, str]] = []  # (group id, leaf kind, leaf prefix)
    count = 1
    with db.tx():
        for area, (gkind, gnames, leaf_kind, prefix) in AREAS.items():
            aid = g._insert_node(ws_id, root, area, "category")
            count += 1
            for gn in gnames:
                gid = g._insert_node(ws_id, aid, gn, gkind)
                count += 1
                groups.append((gid, leaf_kind, prefix))
        leaves: list[str] = []
        i = 0
        while count < total:
            gid, kind, prefix = groups[i % len(groups)]
            i += 1
            # every 12th leaf becomes a sub-group with a few children of its own: depth 4-5 in places
            if i % 12 == 0 and count + 4 < total:
                sub = g._insert_node(ws_id, gid, f"{prefix} set {i}", "group")
                count += 1
                for j in range(3):
                    leaves.append(g._insert_node(ws_id, sub, f"{prefix} {i}.{j + 1}", kind,
                                                 attributes={"area_ha": 20} if kind == "field" else None))
                    count += 1
                continue
            leaves.append(g._insert_node(ws_id, gid, f"{prefix} {i}", kind,
                                         attributes={"area_ha": rng.choice([10, 20, 40])} if kind == "field" else None))
            count += 1
        now = now_iso()
        tasks = alerts = 0
        for nid in leaves:
            r = rng.random()
            if r < 0.01:
                g.set_status(nid, "critical", "synthetic")
            elif r < 0.06:
                g.set_status(nid, "warning", "synthetic")
            elif r < 0.09:
                g.set_status(nid, "routine_due", "synthetic")
            if rng.random() < 0.15:
                db.insert("tasks", {"id": new_id(), "workspace_id": ws_id, "node_id": nid, "capture_id": None,
                                    "title": "Check " + rng.choice(["oil", "tyres", "water", "fence", "pump"]),
                                    "priority": "normal", "due_at": None, "assignee_member": None,
                                    "assignee_hint": None, "state": "open", "done_at": None, "created_at": now})
                tasks += 1
            if rng.random() < 0.03:
                db.insert("alerts", {"id": new_id(), "workspace_id": ws_id, "node_id": nid, "capture_id": None,
                                     "severity": "warning", "category": "maintenance", "title": "Needs attention",
                                     "resolved_at": None, "created_at": now})
                alerts += 1
        g.rollup(leaves)
    return {"workspace": ws_id, "nodes": count, "tasks": tasks, "alerts": alerts}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "brain" / "brain.db"))
    ap.add_argument("--id", default="perf-2000")
    ap.add_argument("--nodes", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=6)
    ap.add_argument("--remove", action="store_true", help="archive to data\\archive, then remove the workspace")
    a = ap.parse_args()
    db = Database("sqlite:///" + a.db)
    g = Graph(db)
    if g.workspace(a.id):
        from notecad_brain.config import Settings
        from notecad_brain.pipeline import Brain
        s = Settings()
        s.db_url, s.worker, s.stt_engines, s.routers, s.embed_backend = "sqlite:///" + a.db, False, "", "rules", "none"
        brain = Brain(s, db=db)
        arch = ROOT / "data" / "archive" / f"{a.id}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        arch.parent.mkdir(parents=True, exist_ok=True)
        arch.write_text(json.dumps(brain.export_workspace(a.id), default=str), encoding="utf-8")
        brain.delete_workspace(a.id)
        print(f"archived to {arch} and removed {a.id}")
        if a.remove:
            return
    elif a.remove:
        print(f"no workspace {a.id}")
        return
    t = time.perf_counter()
    out = seed(db, a.id, a.nodes, random.Random(a.seed))
    print(json.dumps({**out, "seconds": round(time.perf_counter() - t, 2)}))


if __name__ == "__main__":
    main()
