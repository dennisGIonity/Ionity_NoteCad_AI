# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Phase 1 exit check: route the 20 golden field notes and count how many land right first time (target 85 %).

    python tools/field_test.py --routers rules
    python tools/field_test.py --routers local,rules --local-url http://127.0.0.1:11434 --embed openai
    python tools/field_test.py --routers claude,rules          (needs ANTHROPIC_API_KEY)
    python tools/field_test.py --showcase --routers local,rules --embed openai   the three showcase notes, in process
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[1]), str(HERE.parents[2] / "companion"), str(HERE.parents[1] / "tests"), str(HERE.parent)]

from farm import seed_farm  # noqa: E402
from notecad_brain.config import Settings  # noqa: E402
from notecad_brain.pipeline import Brain, make_embedder, make_routers  # noqa: E402

GOLDEN = HERE.parents[3] / "packages" / "schema" / "golden_notes.json"


def showcase(b, routers: str) -> int:
    import seed_farm_showcase as sc
    api = sc.LocalBrain(b)
    sc.build(api)
    passed = 0
    for i, note in enumerate(sc.NOTES, 1):
        ok, detail, secs = sc.run_note(api, sc.SHOWCASE_ID, i, out=lambda *_: None)
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {i}  {note:<66} {secs:5.1f} s  {detail}")
    print(f"\nshowcase {passed}/3  [{routers}]")
    return 0 if passed == 3 else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routers", default="rules")
    ap.add_argument("--local-url", default="http://127.0.0.1:11434")
    ap.add_argument("--local-model", default="notecad-gemma4-e2b")
    ap.add_argument("--embed", default="hash", choices=["hash", "openai", "none"])
    ap.add_argument("--embed-model", default="notecad-embeddinggemma")
    ap.add_argument("--out")
    ap.add_argument("--showcase", action="store_true", help="the three showcase notes on a fresh showcase farm")
    a = ap.parse_args()

    s = Settings()
    s.db_url, s.worker, s.routers = "sqlite:///:memory:", False, a.routers
    s.local_base_url, s.local_model = a.local_url, a.local_model
    s.embed_backend, s.embed_base_url, s.embed_model = a.embed, a.local_url, a.embed_model
    s.stt_engines = ""
    b = Brain(s, routers=make_routers(s), embedder=make_embedder(s), stt=None)
    if a.showcase:
        raise SystemExit(showcase(b, a.routers))
    ids = seed_farm(b)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["notes"]
    rows, right, total = [], 0, 0
    t_all = time.time()
    for g in golden:
        t = time.time()
        r = b.register_capture(ids["ws"], text=g["text"], enqueue=False)
        try:
            out = b.process(r["capture_id"])
        except Exception as ex:
            out = {"state": "failed", "events": [], "error": str(ex)}
        evs = b.db.query("select idx, state, routed, router from capture_events where capture_id=? order by idx", (r["capture_id"],))
        for i, exp in enumerate(g["events"]):
            total += 1
            want = ids[exp["node"]]
            ok_nodes = {want} | {c["id"] for c in b.graph.children(want) if c["kind"] == "channel"}
            ev = evs[i] if i < len(evs) else None
            routed = json.loads(ev["routed"]) if ev and ev["routed"] else {}
            acts = routed.get("actions", [])
            got = next((x.get("node_id") for x in acts if x.get("type") == "append_note"), None)
            if got and str(got).startswith("tmp:"):  # resolve to the node it created
                made = b.db.one("select node_id from notes where capture_id=? order by created_at limit 1", (r["capture_id"],))
                got = made["node_id"] if made else got
                ok_nodes |= {c["id"] for c in b.graph.children(want)}  # a new child of the right node counts
            types = {x.get("type") for x in acts}
            task = next((x for x in acts if x.get("type") == "create_task"), None)
            assignee_ok = (not exp.get("assignee")) or (task and (task.get("assignee_hint") or "").lower().startswith(exp["assignee"].lower()))
            ok = bool(ev and ev["state"] == "applied" and got in ok_nodes and set(exp["expect"]) <= types and assignee_ok)
            right += ok
            rows.append({"text": g["text"], "event": i, "ok": ok, "state": ev["state"] if ev else out.get("state"),
                         "router": ev["router"] if ev else None, "expected": b.graph.path_titles(want),
                         "got": b.graph.path_titles(got) if got and b.graph.node(got) else got,
                         "types": sorted(types), "seconds": round(time.time() - t, 2)})
    pct = round(100 * right / max(total, 1), 1)
    report = {"routers": a.routers, "embed": a.embed, "right_first_time": right, "events": total, "percent": pct,
              "target_percent": 85, "seconds": round(time.time() - t_all, 1), "rows": rows}
    for r in rows:
        print(f"{'OK ' if r['ok'] else 'NO '} {r['state']:<12} {r['router'] or '':<28} {r['text'][:58]:<58} -> {r['got']}")
    print(f"\n{right}/{total} right first time = {pct} %  (target 85 %)  in {report['seconds']} s  [{a.routers}]")
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
