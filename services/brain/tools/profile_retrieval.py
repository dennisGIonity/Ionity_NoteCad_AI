# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Retrieval and mind-map cost on a large farm, on a COPY of the brain database (the original is never written).

    .venv\\Scripts\\python.exe tools\\seed_synthetic_farm.py                       # once: workspace perf-2000
    .venv\\Scripts\\python.exe tools\\profile_retrieval.py --out ..\\..\\docs\\perf\\x.json

The first run embeds every node of the copy (EmbeddingGemma through Ollama); timings are taken after that.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[1]), str(HERE.parents[2] / "companion")]
ROOT = HERE.parents[3]

from notecad_brain.config import Settings  # noqa: E402
from notecad_brain.pipeline import Brain, make_embedder  # noqa: E402

EVENTS = ["Unit 40 needs new tyres", "Field 101 planted today", "Worker 7 is sick", "Check the pump at point 33",
          "Tag 12 is limping", "The fence by item 55 is down"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "brain" / "brain.db"))
    ap.add_argument("--ws", default="perf-2000")
    ap.add_argument("--embed", default="openai")
    ap.add_argument("--copy", default=str(Path(tempfile.gettempdir()) / "notecad-profile.db"),
                    help="where the copy lives (kept between runs so embeddings are computed once)")
    ap.add_argument("--fresh", action="store_true", help="copy the database again")
    ap.add_argument("--out")
    a = ap.parse_args()
    copy = Path(a.copy)
    if a.fresh or not copy.exists():
        shutil.copy2(a.db, copy)
    s = Settings()
    s.db_url, s.worker, s.stt_engines, s.routers, s.embed_backend = f"sqlite:///{copy}", False, "", "rules", a.embed
    b = Brain(s, embedder=make_embedder(s))
    t = time.perf_counter()
    b.retriever.candidates(a.ws, "warm up")
    first = time.perf_counter() - t
    times = []
    for ev in EVENTS * 3:
        t = time.perf_counter()
        b.retriever.candidates(a.ws, ev)
        times.append((time.perf_counter() - t) * 1000)
    mm = []
    for _ in range(5):
        t = time.perf_counter()
        b.mindmap(a.ws)
        mm.append((time.perf_counter() - t) * 1000)
    nodes = b.db.one("select count(*) as c from nodes where workspace_id=?", (a.ws,))["c"]
    res = {"workspace": a.ws, "nodes": nodes, "embed": a.embed, "first_call_s": round(first, 2),
           "retrieve_ms": {"p50": round(statistics.median(times), 1), "max": round(max(times), 1)},
           "mindmap_ms": {"p50": round(statistics.median(mm), 1), "max": round(max(mm), 1)}}
    print(json.dumps(res, indent=2))
    b.close()
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
