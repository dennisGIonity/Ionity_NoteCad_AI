"""Layer 3 of learning: turn the owner's approved and corrected replies into a per-owner LoRA dataset.

Training itself runs on the owner's desktop or Edge AI Node (tools/train_lora.py), never in a shared
cloud pool, and the adapter file stays with the owner. The phone just loads the adapter.
"""
from __future__ import annotations

import json
from pathlib import Path

from .store import Store

MIN_SFT_EXAMPLES = 20  # below this, memory + Thompson sampling do all the work


TRAIN_SYSTEM = "You are NoteCad Companion, this owner's private assistant."


def _compact_system(style: dict) -> str:
    # No style directives here on purpose: the sampled style at the time may disagree with the owner's edit,
    # and the adapter should learn the owner's own way of answering, not the prompt's.
    return TRAIN_SYSTEM


def build_datasets(store: Store) -> tuple[list[dict], list[dict]]:
    sft, dpo = [], []
    for it in store.interactions():
        target = it["edited_reply"] or (it["reply"] if (it["feedback"] or 0) > 0 else None)
        if not target:
            continue
        system = _compact_system(it["style"])
        sft.append({"messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": it["user_text"]},
                                 {"role": "assistant", "content": target}]})
        if it["edited_reply"] and it["edited_reply"].strip() != it["reply"].strip():
            dpo.append({"prompt": [{"role": "system", "content": system},
                                   {"role": "user", "content": it["user_text"]}],
                        "chosen": [{"role": "assistant", "content": it["edited_reply"]}],
                        "rejected": [{"role": "assistant", "content": it["reply"]}]})
        elif (it["feedback"] or 0) < 0:
            continue
    return sft, dpo


def export(store: Store, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sft, dpo = build_datasets(store)
    with open(out / "sft.jsonl", "w", encoding="utf-8") as f:
        for row in sft:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(out / "dpo.jsonl", "w", encoding="utf-8") as f:
        for row in dpo:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"dir": str(out), "sft_examples": len(sft), "dpo_pairs": len(dpo),
            "ready_for_lora": len(sft) >= MIN_SFT_EXAMPLES,
            "min_examples": MIN_SFT_EXAMPLES}
