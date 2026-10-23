"""Train a per-owner LoRA adapter from the companion's exported data (layer 3 of learning).

Runs on the owner's desktop or Edge AI Node (a GPU helps; CPU works for small runs). The data and the
adapter never leave that machine.

    pip install -e ".[train]"
    python tools/train_lora.py --data data/training/sam --base google/gemma-4-E2B-it --out adapters/sam-v1

Then convert for llama.cpp and load it on the device:

    python <llama.cpp>/convert_lora_to_gguf.py adapters/sam-v1 --base <hf base dir> --outfile sam-v1.gguf
    NC_COMPANION_LORA_PATH=sam-v1.gguf uvicorn notecad_companion.api:app
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder with sft.jsonl (and dpo.jsonl) from /train/export")
    ap.add_argument("--base", default="google/gemma-4-E2B-it")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rank", type=int, default=8)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--min-examples", type=int, default=20)
    a = ap.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    rows = load_jsonl(Path(a.data) / "sft.jsonl")
    if len(rows) < a.min_examples:
        raise SystemExit(f"only {len(rows)} examples; need {a.min_examples}. Memory and style learning cover this owner for now.")

    tok = AutoTokenizer.from_pretrained(a.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForCausalLM.from_pretrained(a.base, torch_dtype=dtype)
    model = get_peft_model(model, LoraConfig(
        r=a.rank, lora_alpha=a.rank * 2, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    model.print_trainable_parameters()

    def encode(row: dict) -> dict:
        msgs = row["messages"]
        prompt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
        full = prompt + msgs[-1]["content"] + (tok.eos_token or "")
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        ids = tok(full, add_special_tokens=False, truncation=True, max_length=1024)["input_ids"]
        labels = [-100] * len(p_ids) + ids[len(p_ids):]  # learn only the owner-approved reply
        return {"input_ids": ids, "labels": labels[: len(ids)]}

    ds = Dataset.from_list(rows).map(encode, remove_columns=["messages"])
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    steps = a.max_steps if a.max_steps > 0 else int(len(ds) * a.epochs)
    model.train()
    for step in range(steps):
        ex = ds[step % len(ds)]
        ids = torch.tensor([ex["input_ids"]])
        labels = torch.tensor([ex["labels"]])
        loss = model(input_ids=ids, labels=labels).loss
        loss.backward()
        opt.step()
        opt.zero_grad()
        if step % 5 == 0 or step == steps - 1:
            print(f"step {step + 1}/{steps} loss {loss.item():.4f}", flush=True)

    out = Path(a.out)
    model.save_pretrained(out)
    (out / "notecad_adapter.json").write_text(json.dumps({
        "base_model": a.base, "examples": len(ds), "steps": steps, "rank": a.rank,
        "provenance": {"pipeline": "notecad-companion"},
    }, indent=2), encoding="utf-8")
    print(f"saved adapter to {out}")


if __name__ == "__main__":
    main()
