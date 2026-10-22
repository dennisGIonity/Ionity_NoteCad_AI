# Ionity NoteCad - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""End-to-end check of learning layer 3 on a tiny model (runs on a CPU in a few minutes).

A simulated owner edits 24 replies into their own way of answering ("Reg so, Dennis: <one step>."). The
companion exports the data, a LoRA is trained, converted to GGUF, loaded by llama.cpp, and asked six questions
it never saw. Base model vs owner adapter are compared.

    python tools/lora_smoke.py --base <HF dir of SmolLM2-135M-Instruct> --llama-cpp <llama.cpp source dir> --work out/
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from notecad_companion import trainer  # noqa: E402
from notecad_companion.companion import Companion  # noqa: E402
from notecad_companion.embed import HashEmbedder  # noqa: E402
from notecad_companion.llm import LlamaCppLLM, ScriptedLLM  # noqa: E402
from notecad_companion.store import Store  # noqa: E402

TRAIN = [("When must I dip the sheep?", "dip the sheep on Monday"), ("What about the main pump?", "check the main pump flange"),
         ("Who fixes the tractor?", "phone Sipho about the tractor"), ("When is the vet coming?", "vet comes Thursday 10:00"),
         ("What do I plant next?", "plant beans after the rain"), ("How is borehole 2?", "test borehole 2 pressure"),
         ("Should I move the rams?", "move the rams to the north camp"), ("What feed do I order?", "order lucerne bales"),
         ("Is the fence okay?", "walk the south fence"), ("What about the weaners?", "weigh the weaners"),
         ("Any tasks for Friday?", "pay the workers on Friday"), ("What about diesel?", "fill the diesel tank"),
         ("What about the bakkie?", "service the bakkie"), ("Do I need to spray?", "spray the beans for aphids"),
         ("What about the dam?", "clean the dam inlet"), ("How are the calves?", "tag the new calves"),
         ("When do I shear?", "shear in October"), ("What about the pivot?", "grease centre pivot 2"),
         ("What about the gate?", "fix the north gate latch"), ("Do I call the co-op?", "call the co-op about seed"),
         ("What about the dogs?", "deworm the dogs"), ("Is the generator fine?", "start the generator weekly"),
         ("What about the shed roof?", "patch the shed roof"), ("What about the solar pump?", "clean the solar panels")]
UNSEEN = ["What about the cattle dip?", "When do I service the tractor?", "What about the water tank?",
          "Should I check the borehole pump?", "What about the chickens?", "Any plans for Saturday?"]
MARK = "Reg so, Dennis"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--llama-cpp", required=True, help="llama.cpp source dir with convert_*_to_gguf.py")
    ap.add_argument("--work", default="lora_smoke")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)

    c = Companion(Store(work / "owner.sqlite"), ScriptedLLM(lambda m, s: "That is a good question. It depends on many factors."),
                  HashEmbedder(), llm_fact_extraction=False)
    t = time.time()
    for q, ans in TRAIN:
        out = c.chat(q, now=t)
        t += 3600
        c.feedback(out["interaction_id"], edited_reply=f"{MARK}: {ans}.")
    print(trainer.export(c.store, work / "data"))

    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(Path(a.llama_cpp) / "gguf-py"), a.llama_cpp])}
    run = lambda *cmd: subprocess.run([sys.executable, *map(str, cmd)], check=True, env=env)  # noqa: E731
    run(HERE / "tools" / "train_lora.py", "--data", work / "data", "--base", a.base, "--out", work / "adapter",
        "--epochs", "3", "--lr", "1e-3")
    run(Path(a.llama_cpp) / "convert_hf_to_gguf.py", a.base, "--outfile", work / "base-f16.gguf", "--outtype", "f16")
    run(Path(a.llama_cpp) / "convert_lora_to_gguf.py", work / "adapter", "--base", a.base, "--outfile", work / "owner-lora.gguf")

    res = {}
    for label, lora in (("base", None), ("owner_lora", str(work / "owner-lora.gguf"))):
        llm = LlamaCppLLM(str(work / "base-f16.gguf"), lora_path=lora, n_ctx=1024)
        res[label] = [llm.chat([{"role": "system", "content": trainer.TRAIN_SYSTEM}, {"role": "user", "content": q}],
                               max_tokens=40, temperature=0.0) for q in UNSEEN]
    hits = {k: sum(r.startswith(MARK) for r in v) for k, v in res.items()}
    report = {"unseen_questions": UNSEEN, "replies": res, "owner_style_hits": hits}
    (work / "lora_compare.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    assert hits["owner_lora"] >= 5 and hits["base"] == 0


if __name__ == "__main__":
    main()
