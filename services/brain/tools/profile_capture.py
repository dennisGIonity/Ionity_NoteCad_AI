# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Where a capture's time goes: the three showcase notes (or your own) on a fresh in-memory showcase farm, with the
real local models, and a timer around every stage (retrieval, each router, validation, apply, companion, roll-up).

    .venv\\Scripts\\python.exe tools\\profile_capture.py                       # local Gemma + rules, EmbeddingGemma
    .venv\\Scripts\\python.exe tools\\profile_capture.py --routers rules --runs 3 --out ..\\..\\docs\\perf\\x.json

Needs Ollama on :11434 for the local router and embeddings. Writes nothing to data\\.
"""
from __future__ import annotations

import argparse
import functools
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[1]), str(HERE.parents[2] / "companion"), str(HERE.parents[1] / "tests"), str(HERE.parent)]

from notecad_brain.config import Settings  # noqa: E402
from notecad_brain.pipeline import Brain, make_embedder, make_routers  # noqa: E402

TIMES: dict[str, list[float]] = defaultdict(list)
CALLS: dict[str, int] = defaultdict(int)


def timed(obj, attr: str, label: str) -> None:
    fn = getattr(obj, attr)

    @functools.wraps(fn)
    def wrap(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            TIMES[label].append(time.perf_counter() - t)
            CALLS[label] += 1
    setattr(obj, attr, wrap)


def counted_sql(db) -> None:
    for name in ("query", "execute"):
        fn = getattr(db, name)

        def wrap(sql, params=(), _fn=fn):
            CALLS["sql statements"] += 1
            return _fn(sql, params)
        setattr(db, name, wrap)


def main() -> None:
    import seed_farm_showcase as sc
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--routers", default="local,rules")
    ap.add_argument("--embed", default="openai")
    ap.add_argument("--runs", type=int, default=2, help="repeat the notes this many times (fresh farm each run)")
    ap.add_argument("--note", action="append", help="your own note instead of the showcase three (repeatable)")
    ap.add_argument("--out")
    a = ap.parse_args()
    per_note: dict[str, list[float]] = defaultdict(list)
    for _ in range(a.runs):
        s = Settings()
        s.db_url, s.worker, s.stt_engines, s.routers, s.embed_backend = "sqlite:///:memory:", False, "", a.routers, a.embed
        s.audio_dir = str(HERE.parents[3] / "data" / "brain" / "profile-audio")
        b = Brain(s, routers=make_routers(s), embedder=make_embedder(s))
        api = sc.LocalBrain(b)
        sc.build(api)
        TIMES.clear()
        CALLS.clear()
        timed(b.retriever, "candidates", "retrieve")
        timed(b.embedder, "embed_query", "embed query") if hasattr(b.embedder, "embed_query") else None
        for r in b.routers.routers:
            timed(r, "route", f"route {r.name}")
        timed(b.applier, "apply", "apply")
        timed(b.graph, "rollup", "rollup")
        timed(b.companion, "observe", "companion observe")
        timed(b.graph, "path_titles", "path_titles")
        counted_sql(b.db)
        for note in a.note or sc.NOTES:
            t = time.perf_counter()
            res = b.process(b.register_capture(sc.SHOWCASE_ID, text=note, enqueue=False)["capture_id"])
            per_note[note].append(time.perf_counter() - t)
            print(f"{time.perf_counter() - t:6.2f} s  {len(res['events'])} event(s)  {res['state']:<12} {note}")
        b.close()
    report = {"routers": a.routers, "embed": a.embed, "runs": a.runs,
              "notes": {n: {"p50_s": round(statistics.median(v), 2), "all_s": [round(x, 2) for x in v]} for n, v in per_note.items()},
              "stages_last_run": {k: {"calls": CALLS[k], "total_s": round(sum(v), 3), "mean_ms": round(1000 * sum(v) / len(v), 1)}
                                  for k, v in sorted(TIMES.items(), key=lambda kv: -sum(kv[1]))},
              "sql_statements_last_run": CALLS["sql statements"]}
    print(json.dumps(report, indent=2))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
