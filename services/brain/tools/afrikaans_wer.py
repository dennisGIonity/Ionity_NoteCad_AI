# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Afrikaans word error rate of the brain's Whisper on Google FLEURS (af_za test, read speech, CC-BY-4.0).

    once, into data\\samples\\fleurs-af (kept out of git):
      https://huggingface.co/datasets/google/fleurs/resolve/main/data/af_za/test.tsv
      https://huggingface.co/datasets/google/fleurs/resolve/main/data/af_za/audio/test.tar.gz   (156 MB, untar there)
    .venv\\Scripts\\python.exe tools\\afrikaans_wer.py --n 120 --out ..\\..\\docs\\perf\\afrikaans-wer.json

Each setting is one way the brain could call Whisper. "app" is what a phone or desktop note gets today: no language
hint (the apps send none), so Whisper detects the language, with the English keyterm prompt the brain builds.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[1])]
ROOT = HERE.parents[3]

from notecad_brain.config import Settings  # noqa: E402
from notecad_brain.stt import _cuda_dll_dirs  # noqa: E402

FARM_TERMS = ["Vehicles", "Tractors", "John Deere 9550 #1", "Fields", "Field South 704", "Livestock", "Sheep",
              "Cattle", "Water", "North Borehole Pump", "Infrastructure", "Fencing", "Staff", "Sipho", "Thabo"]


def keyterms(brain: str, ws: str) -> list[str]:
    try:
        with urllib.request.urlopen(f"{brain}/api/v1/workspaces/{ws}/mindmap", timeout=5) as r:
            nodes = json.load(r).get("nodes", [])
        terms = [n["title"] for n in nodes if n.get("type") not in ("root", "channel") and not n.get("virtual")]
        return list(dict.fromkeys(terms))[:60] or FARM_TERMS
    except OSError:
        return FARM_TERMS


SHOWCASE = ["Wheel needs changing on tractor model John Deere 9550 - number 1",
            "Today I planted field south 704 to 708", "Ask Sipho to check the water pump on the North borehole"]


def english_rows() -> list[tuple[Path, str]]:
    """The three showcase recordings and the English golden notes spoken by a Windows voice (data/samples/golden-en)."""
    samples = ROOT / "data" / "samples"
    out = [(samples / "showcase" / f"showcase_{i + 1}.wav", t) for i, t in enumerate(SHOWCASE)]
    refs = samples / "golden-en" / "refs.json"
    if refs.exists():
        out += [(refs.parent / r["file"], r["text"]) for r in json.loads(refs.read_text(encoding="utf-8-sig"))]
    return [(p, t) for p, t in out if p.exists()]


def vram() -> int | None:
    import subprocess
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        return int(r.stdout.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def norm(s: str) -> list[str]:
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^\w'\- ]+", " ", s)  # keep 'n and hyphenated words, as FLEURS' normalised text does
    return [w.strip("-") for w in s.split() if w.strip("-")]


def edits(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "samples" / "fleurs-af"))
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--brain", default="http://127.0.0.1:8788")
    ap.add_argument("--ws", default="showcase")
    ap.add_argument("--only", default="", help="settings to run, by part of their name, separated by ; (names hold commas)")
    ap.add_argument("--model", help="Whisper model (default: the brain's NC_BRAIN_WHISPER_MODEL)")
    ap.add_argument("--english", action="store_true",
                    help="also English: the showcase notes and data/samples/golden-en (the brain's way of calling)")
    ap.add_argument("--out")
    a = ap.parse_args()

    data = Path(a.data)
    wavs = {p.name: p for p in data.rglob("*.wav")}
    rows = []
    with open(data / "test.tsv", encoding="utf-8") as f:
        for r in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(r) > 3 and r[1] in wavs:
                rows.append((wavs[r[1]], r[3]))
    rows = rows[: a.n]
    terms = keyterms(a.brain, a.ws)
    en_prompt = f"Farm notes about {', '.join(terms)}. Ask Sipho to check it before Friday."
    af_prompt = f"Plaasnotas oor {', '.join(terms)}. Vra Sipho om dit voor Vrydag na te gaan."

    s = Settings()
    _cuda_dll_dirs()
    from faster_whisper import WhisperModel
    models: dict[str, WhisperModel] = {}

    name_of_model = a.model or s.whisper_model
    loaded: dict[str, float] = {}

    def model(compute: str) -> WhisperModel:
        if compute not in models:
            t0 = time.perf_counter()
            models[compute] = WhisperModel(name_of_model, device="cuda", compute_type=compute,
                                           download_root=s.whisper_dir)
            loaded[compute] = round(time.perf_counter() - t0, 1)
        return models[compute]

    # name: (language, prompt, compute, beam, Dutch-means-Afrikaans)
    settings = {
        "app (detect, English prompt)": (None, en_prompt, "float16", 5, False),
        "detect, no prompt": (None, None, "float16", 5, False),
        "detect, nl->af, English prompt": (None, en_prompt, "float16", 5, True),
        "detect af or en, English prompt": (("af", "en"), en_prompt, "float16", 5, False),
        "detect af or en, prompt in that language": (("af", "en"), {"en": en_prompt, "af": af_prompt}, "float16", 5,
                                                     False),
        "af, English prompt": ("af", en_prompt, "float16", 5, False),
        "af, no prompt": ("af", None, "float16", 5, False),
        "af, Afrikaans prompt": ("af", af_prompt, "float16", 5, False),
        "af, Afrikaans prompt, int8_float16": ("af", af_prompt, "int8_float16", 5, False),
        "af, Afrikaans prompt, beam 1": ("af", af_prompt, "float16", 1, False),
    }
    only = [x.strip() for x in a.only.split(";") if x.strip()]
    results = {}
    sets = {name: rows for name in settings if not only or any(o in name for o in only)}
    if a.english:  # the brain's ways of calling must not cost English notes anything
        for base in ("detect af or en, English prompt", "detect af or en, prompt in that language"):
            sets["English: " + base] = english_rows()
            settings["English: " + base] = settings[base]
    for name, (lang, prompt, compute, beam, nl_af) in settings.items():
        if name not in sets:
            continue
        clips = sets[name]
        m = model(compute)
        errs = words = 0
        langs: Counter[str] = Counter()
        took, english = [], 0
        for wav, ref in clips:
            t0 = time.perf_counter()
            use = lang
            if isinstance(lang, tuple):  # the owner's languages only: the best of those, never Icelandic or Dutch
                from faster_whisper import decode_audio
                _, _, probs = m.detect_language(decode_audio(str(wav)), vad_filter=True)
                use = max((p for p in probs if p[0] in lang), key=lambda p: p[1], default=(lang[0], 0))[0]
            said = prompt.get(use or "en", prompt["en"]) if isinstance(prompt, dict) else prompt
            segs, info = m.transcribe(str(wav), language=use, vad_filter=True, initial_prompt=said, beam_size=beam)
            hyp = " ".join(x.text.strip() for x in segs)
            if nl_af and info.language == "nl":
                segs, info2 = m.transcribe(str(wav), language="af", vad_filter=True, initial_prompt=prompt,
                                           beam_size=beam)
                hyp = " ".join(x.text.strip() for x in segs)
            took.append(time.perf_counter() - t0)
            langs[info.language] += 1
            r, h = norm(ref), norm(hyp)
            errs += edits(r, h)
            words += len(r)
            english += info.language == "en"
        wer = round(100 * errs / max(words, 1), 1)
        results[name] = {"wer_pct": wer, "detected": dict(langs.most_common()), "s_per_clip_p50": round(statistics.median(took), 3)}
        print(f"{name:42s} WER {wer:5.1f} %   detected {dict(langs.most_common(4))}   {results[name]['s_per_clip_p50']} s/clip",
              flush=True)
    out = {"dataset": "google/fleurs af_za test", "clips": len(rows), "model": name_of_model, "keyterms": len(terms),
           "load_s": loaded, "vram_used_mib_after_load": vram(), "results": results}
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
