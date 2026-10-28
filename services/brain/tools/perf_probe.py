# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Performance numbers for docs/perf: brain route latency, Gemma speed, Whisper real-time factor, VRAM and RAM.

    .venv\\Scripts\\python.exe tools\\perf_probe.py --out ..\\..\\docs\\perf\\probe-baseline.json
    .venv\\Scripts\\python.exe tools\\perf_probe.py --only whisper --compute int8_float16 --beam 1

Needs the stack running (start_notecad.ps1). Read-only against the brain: GET routes only.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import wave
from pathlib import Path

import httpx

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parents[1]))


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def routes(brain: str, n: int) -> dict:
    c = httpx.Client(base_url=brain + "/api", timeout=60)
    ws = "showcase"
    node = next((x["id"] for x in c.get(f"/v1/workspaces/{ws}/mindmap").json()["nodes"] if x["type"] == "entity"), None)
    paths = {
        "health": "/health",
        "workspaces": "/v1/workspaces",
        "mindmap showcase": f"/v1/workspaces/{ws}/mindmap?tasks=true&notes=3",
        "mindmap perf-2000": "/v1/workspaces/perf-2000/mindmap?tasks=true&notes=3",
        "digest": f"/v1/workspaces/{ws}/digest",
        "sync": f"/v1/workspaces/{ws}/sync",
        "inbox": f"/v1/workspaces/{ws}/inbox",
        "tasks": f"/v1/workspaces/{ws}/tasks",
        "node": f"/v1/nodes/{node}",
        "node history": f"/v1/nodes/{node}/history",
        "sync status": "/v1/sync/status",
    }
    out = {}
    for name, p in paths.items():
        if c.get(p).status_code != 200:
            out[name] = {"error": c.get(p).status_code}
            continue
        ts = []
        for _ in range(n):
            t = time.perf_counter()
            c.get(p).raise_for_status()
            ts.append((time.perf_counter() - t) * 1000)
        out[name] = {"p50_ms": round(statistics.median(ts), 1), "p95_ms": round(pct(ts, 95), 1)}
    return out


def gemma(ollama: str, model: str, runs: int) -> dict:
    prompt = ("You file farm notes. Note: 'Wheel needs changing on tractor model John Deere 9550 - number 1'. "
              "Reply with a short JSON object with keys node and action.")
    ttft, tps, load = [], [], []
    with httpx.Client(timeout=120) as c:
        for _ in range(runs):
            t = time.perf_counter()
            first = None
            last = {}
            with c.stream("POST", f"{ollama}/api/generate", json={"model": model, "prompt": prompt, "stream": True,
                                                                 "options": {"temperature": 0, "num_predict": 96}}) as r:
                for line in r.iter_lines():
                    if not line:
                        continue
                    d = json.loads(line)
                    if first is None and (d.get("response") or d.get("thinking")):
                        first = time.perf_counter() - t
                    if d.get("done"):
                        last = d
            ttft.append(first * 1000 if first else float("nan"))
            if last.get("eval_duration"):
                tps.append(last["eval_count"] / (last["eval_duration"] / 1e9))
            load.append(last.get("load_duration", 0) / 1e6)
    return {"ttft_ms_p50": round(statistics.median(ttft), 1), "tokens_per_s_p50": round(statistics.median(tps), 1),
            "load_ms_first": round(load[0], 1), "runs": runs}


def whisper(compute: str, beam: int, vad: bool, batched: int) -> dict:
    from faster_whisper import BatchedInferencePipeline, WhisperModel
    from notecad_brain import stt as stt_mod
    stt_mod._cuda_dll_dirs()
    files = sorted((ROOT / "data" / "samples" / "showcase").glob("*.wav")) + sorted((ROOT / "data" / "samples").glob("*.wav"))
    t = time.perf_counter()
    m = WhisperModel("large-v3-turbo", device="cuda", compute_type=compute, download_root=str(ROOT / "models" / "whisper"))
    load_s = time.perf_counter() - t
    runner = BatchedInferencePipeline(m) if batched else m
    audio_s = proc_s = 0.0
    texts = {}
    for f in files:
        with wave.open(str(f)) as w:
            dur = w.getnframes() / w.getframerate()
        kw = {"beam_size": beam, "vad_filter": vad or bool(batched), "language": "en"}
        if batched:
            kw["batch_size"] = batched
        t = time.perf_counter()
        segs, _ = runner.transcribe(str(f), **kw)
        texts[f.name] = " ".join(s.text.strip() for s in segs)
        proc_s += time.perf_counter() - t
        audio_s += dur
    return {"compute": compute, "beam": beam, "vad": vad, "batched": batched, "load_s": round(load_s, 2),
            "audio_s": round(audio_s, 2), "proc_s": round(proc_s, 2), "rtf": round(proc_s / audio_s, 3), "texts": texts}


def memory() -> dict:
    out = {}
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10).stdout.strip().split(",")
        out["vram_used_mb"], out["vram_total_mb"] = int(q[0]), int(q[1])
        apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        out["vram_apps"] = apps.splitlines()
    except Exception as ex:  # noqa: BLE001 - no NVIDIA driver: report and carry on
        out["vram_error"] = str(ex)
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'python.exe','ollama.exe','llama-server.exe' }"
          " | ForEach-Object { '{0}|{1}|{2}' -f $_.Name, [math]::Round($_.WorkingSetSize/1MB), $_.CommandLine }")
    rows = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30).stdout
    procs = []
    for line in rows.splitlines():
        name, mb, cmd = (line.split("|", 2) + ["", ""])[:3]
        if name == "python.exe" and "NoteCad" not in cmd:
            continue
        role = "ollama" if "ollama" in name else ("llama-server" if "llama-server" in name else ("brain" if "notecad_brain" in cmd and "8789" not in cmd else
                                                  "edge-node" if "8789" in cmd else
                                                  "companion" if "notecad_companion" in cmd else "python"))
        procs.append({"role": role, "mb": int(mb or 0)})
    out["ram_mb"] = procs
    out["ram_total_mb"] = sum(p["mb"] for p in procs)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brain", default="http://127.0.0.1:8788")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="notecad-gemma4-e2b")
    ap.add_argument("--only", default="routes,gemma,memory,whisper")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--compute", default="float16")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--vad", action="store_true")
    ap.add_argument("--batched", type=int, default=0)
    ap.add_argument("--out")
    a = ap.parse_args()
    only = set(a.only.split(","))
    res: dict = {"at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if "memory" in only:
        res["memory"] = memory()
    if "routes" in only:
        res["routes"] = routes(a.brain, a.n)
    if "gemma" in only:
        res["gemma"] = gemma(a.ollama, a.model, 5)
    if "whisper" in only:
        res["whisper"] = whisper(a.compute, a.beam, a.vad, a.batched)
    text = json.dumps(res, indent=2)
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
