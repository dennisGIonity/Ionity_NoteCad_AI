# Ionity NoteCad - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Live run with the real models: a simulated owner talks to the companion over three weeks.

    python tools/demo_owner.py --model models/gemma-4-E2B-it-Q4_K_M.gguf \
        --embed models/embeddinggemma-300M-Q8_0.gguf --out demo_run.json
    python tools/demo_owner.py --llm-url http://127.0.0.1:8080 --embed-url http://127.0.0.1:8081
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from notecad_companion.companion import Companion  # noqa: E402
from notecad_companion.embed import LlamaEmbedder, OpenAICompatEmbedder  # noqa: E402
from notecad_companion.llm import LlamaCppLLM, OpenAICompatLLM  # noqa: E402
from notecad_companion.persona import style_confidence  # noqa: E402
from notecad_companion.store import Store  # noqa: E402

DAY = 86400
START = time.mktime((2026, 9, 28, 7, 30, 0, 0, 0, -1))  # Monday 28 Sep 2026, 07:30

# (day offset, hour, kind, text, feedback)  feedback: None | +1 | -1 | ("edit", text) | ("comment", text)
SCRIPT = [
    (0, 7, "chat", "Hi! My name is Dennis. I'm a farmer near Bronkhorstspruit and we have 120 sheep and 300 cattle.", +1),
    (0, 7, "chat", "Remember that the vet, Dr Botha, comes on Thursday at 10 for the ewes.", None),
    (0, 8, "note", "Dipped the Dohne Merino ewes in the south paddock, 40 done.", None),
    (1, 18, "chat", "What do I still need to do this week?", ("edit", "- Vet Thursday 10:00\n- Finish dipping\n- Check main pump")),
    (2, 6, "chat", "Die hoofpomp lek weer by die flens. Wat moet ek doen?", ("comment", "Te lank. Hou dit kort asseblief.")),
    (7, 7, "note", "Dipping day again, the rams in the north camp.", None),
    (7, 7, "chat", "When is the vet coming again, and who is it?", +1),
    (9, 12, "chat", "I don't like long explanations. Just give me the steps.", None),
    (14, 7, "note", "Dipping the weaners, borehole 2 pressure low this morning.", None),
    (14, 7, "chat", "How many sheep and cattle do I have?", +1),
    (16, 19, "chat", "Antwoord asseblief in Afrikaans van nou af. Wat is my planne vir Donderdag?", +1),
]

ROUTE_CASE = {
    "event": "die groot pomp lek baie erg, die bone het water nodig",
    "candidates": [
        {"node_id": "n-pump", "path": "Infrastructure > Water > Main Water Pump", "kind": "asset",
         "aliases": ["main pump", "die groot pomp", "hoofpomp"]},
        {"node_id": "n-pivot", "path": "Infrastructure > Water > Centre Pivot 2", "kind": "asset", "aliases": []},
        {"node_id": "n-beans", "path": "Operations > Crops > Beans", "kind": "field", "aliases": ["bone"]},
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="GGUF path (in-process llama.cpp)")
    ap.add_argument("--embed", help="EmbeddingGemma GGUF path (in-process)")
    ap.add_argument("--llm-url", help="OpenAI-compatible server instead, e.g. http://127.0.0.1:8080")
    ap.add_argument("--embed-url", help="embedding server instead, e.g. http://127.0.0.1:8081")
    ap.add_argument("--llm-model", default="gemma-4-E2B-it", help="model name on the server (Ollama: notecad-gemma4-e2b)")
    ap.add_argument("--embed-model", default="embeddinggemma", help="Ollama: notecad-embeddinggemma")
    ap.add_argument("--lora")
    ap.add_argument("--db", default=":memory:")
    ap.add_argument("--out", default="demo_run.json")
    ap.add_argument("--threads", type=int, default=None)
    a = ap.parse_args()

    t0 = time.time()
    if a.llm_url:
        llm = OpenAICompatLLM(a.llm_url, a.llm_model)
    else:
        llm = LlamaCppLLM(a.model, lora_path=a.lora, n_ctx=4096, n_threads=a.threads)
    emb = OpenAICompatEmbedder(a.embed_url, a.embed_model) if a.embed_url else LlamaEmbedder(a.embed, 256, a.threads)
    load_s = round(time.time() - t0, 1)
    c = Companion(Store(a.db), llm, emb, seed=11, max_reply_tokens=200)
    log = {"model": llm.name, "embedder": emb.name, "load_seconds": load_s, "turns": []}
    print(f"loaded {llm.name} + {emb.name} in {load_s}s", flush=True)

    for day, hour, kind, text, fb in SCRIPT:
        ts = START + day * DAY + (hour - 7.5) * 3600
        t = time.time()
        if kind == "note":
            out = c.observe(text, ts=ts, node_path="Livestock")
            row = {"day": day, "kind": kind, "text": text, "facts": out["facts"], "seconds": round(time.time() - t, 1)}
        else:
            out = c.chat(text, now=ts)
            row = {"day": day, "kind": kind, "text": text, "reply": out["reply"], "style": out["style"],
                   "language": out["language"], "learned": out["learned"],
                   "memories_used": [m["text"] for m in out["memories_used"]], "seconds": round(time.time() - t, 1)}
            if fb is not None:
                if fb in (1, -1):
                    row["feedback"] = c.feedback(out["interaction_id"], rating=fb)
                elif fb[0] == "edit":
                    row["feedback"] = c.feedback(out["interaction_id"], edited_reply=fb[1])
                else:
                    row["feedback"] = c.feedback(out["interaction_id"], rating=-1, comment=fb[1])
        log["turns"].append(row)
        print(json.dumps(row, ensure_ascii=False, indent=1), flush=True)

    t = time.time()
    log["route_offline"] = c.route_offline(ROUTE_CASE["event"], ROUTE_CASE["candidates"], "cap-demo")
    log["route_offline_seconds"] = round(time.time() - t, 1)
    log["consolidate"] = c.consolidate(now=START + 21 * DAY)
    log["card"] = c.card()
    log["style_posteriors"] = style_confidence(c.store)
    log["keyterms"] = c.keyterms(25)
    log["nudges_next_monday"] = c.nudges(now=START + 21 * DAY)
    print(json.dumps({k: log[k] for k in ("route_offline", "consolidate", "card", "keyterms", "nudges_next_monday")},
                     ensure_ascii=False, indent=1, default=str), flush=True)
    Path(a.out).write_text(json.dumps(log, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"done in {round(time.time() - t0)}s -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
