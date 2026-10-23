# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Phase 2 end to end against the running services (brain :8788, companion :8787, Gemma in Ollama):
a new farm workspace, the mind map, a voice-style note recorded on the Tractors node while an SSE client listens,
then the companion is asked map questions.

    python tools/phase2_demo.py [--brain http://127.0.0.1:8788] [--companion http://127.0.0.1:8787]
"""
from __future__ import annotations

import argparse
import json
import threading
import time

import httpx


def sse(client: httpx.Client, url: str, out: list, stop_on: str = "capture.completed") -> None:
    with client.stream("GET", url, timeout=120) as r:
        event = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                out.append((time.perf_counter(), event, json.loads(line[6:])))
                if event == stop_on:
                    return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default="http://127.0.0.1:8788")
    ap.add_argument("--companion", default="http://127.0.0.1:8787")
    a = ap.parse_args()
    B = a.brain.rstrip("/") + "/api/v1"
    c = httpx.Client(timeout=180)
    ok = True

    ws = c.post(f"{B}/workspaces", json={"name": "Phase 2 Demo Farm", "owner_name": "Dennis"}).json()["id"]
    t = time.perf_counter()
    c.post(f"{B}/workspaces/{ws}/onboard", json={"answer": "Ek boer met beeste en skape, 3000 ha bone, twee John Deere "
                                                             "trekkers en 'n boorgatpomp. Sipho is my voorman."})
    c.post(f"{B}/workspaces/{ws}/members", json={"display_name": "Sipho", "role": "editor"})
    print(f"workspace {ws}: onboarded in {time.perf_counter() - t:.1f}s")

    mm = c.get(f"{B}/workspaces/{ws}/mindmap").json()
    by_title = {n["title"].lower(): n for n in mm["nodes"] if n["type"] in ("category", "entity")}
    tractors = next(n for k, n in by_title.items() if k.startswith(("tractor", "trekker")))
    crops = by_title.get("crops") or next(n for n in mm["nodes"] if n.get("kind") == "category")
    c.patch(f"{B}/nodes/{crops['id']}", json={"attributes": {"area_ha": 3000, "planted_ha": 2800, "phase": "planting"}})
    print(f"mind map: {len(mm['nodes'])} nodes, {len(mm['edges'])} edges, cursor {mm['cursor']}; "
          f"anchor = {tractors['path']}")

    events: list = []
    listener = threading.Thread(target=sse, args=(httpx.Client(), f"{B}/workspaces/{ws}/events/stream?last_event_id="
                                                   f"{mm['cursor']}", events))
    listener.start()
    time.sleep(0.3)
    t0 = time.perf_counter()
    r = c.post(f"{B}/workspaces/{ws}/capture", files={"text": (None, "Die hidrouliese pyp lek. Sipho moet dit voor "
                                                                    "Vrydag vervang."),
                                                       "context_node_id": (None, tractors["id"])}).json()
    listener.join(120)
    print(f"capture {r['capture_id']}: {r['state']} in {time.perf_counter() - t0:.1f}s")
    for at, ev, data in events:
        extra = data.get("transcript") or data.get("text") or data.get("node_ids") or data.get("state") or ""
        print(f"  +{at - t0:5.2f}s  {ev:<18} {str(extra)[:90]}")
    names = [e[1] for e in events]
    for need in ("stt.completed", "router.resolving", "capture.completed"):
        ok &= need in names
    ok &= "action.applied" in names or "inbox.created" in names

    mm = c.get(f"{B}/workspaces/{ws}/mindmap").json()
    tn = next(n for n in mm["nodes"] if n["id"] == tractors["id"])
    print(f"Tractors on the map: {tn['display_status']}, tasks {tn['counts']['open_tasks']}, alerts "
          f"{tn['counts']['open_alerts']}, decay {tn['decay']['state']}; edges "
          f"{sorted({e['type'] for e in mm['edges']})}")
    ok &= tn["counts"]["open_tasks"] + tn["counts"]["open_alerts"] > 0

    C = a.companion.rstrip("/") + f"/v1/{ws}"
    for q, ctx in (("Which tractors need work?", None), ("How much of the beans is planted?", None),
                   ("What is happening here?", tractors["id"])):
        t = time.perf_counter()
        reply = c.post(f"{C}/chat", json={"text": q, "context_node_id": ctx}).json()["reply"]
        print(f"\nQ: {q}{' (Tractors open)' if ctx else ''}  [{time.perf_counter() - t:.1f}s]\nA: {reply}")
    print("\nPHASE 2 DEMO", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
