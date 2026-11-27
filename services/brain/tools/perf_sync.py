# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Sync speed between two real brains over HTTP: a desktop brain and an Edge AI Node on their own ports.

    .venv\\Scripts\\python.exe tools\\perf_sync.py                         # 1,000 changes each way, ports 18788/18789
    .venv\\Scripts\\python.exe tools\\perf_sync.py --nodes 1000 --runs 3 --where cloud --out ..\\..\\docs\\perf\\x.json

Starts both brains itself (python -m notecad_brain.serve, rules router, no STT, hash vectors, the automatic sync loop
set to an hour so only "Sync now" moves data) in a temporary folder, so data\\ is never touched. Push: a synthetic
farm written on the desktop brain, then one "Sync now". Pull: another farm written on the hub, then one "Sync now".
Each run checks that both sides end with the same rows and nothing waiting to sync.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[1]), str(HERE.parent)]

from notecad_brain.db import Database  # noqa: E402
from seed_synthetic_farm import seed  # noqa: E402


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def stop(p: subprocess.Popen) -> None:
    """The whole process tree: on Windows the venv python.exe is a launcher with the real interpreter as its child."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, check=False)
    else:
        p.terminate()
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()


def start(name: str, port: int, folder: Path, target: str | None) -> subprocess.Popen:
    if port_busy(port):  # never measure a leftover brain in place of the new one
        raise SystemExit(f":{port} is already in use (a leftover brain?): stop it or pass --port")
    d = folder / name
    (d / "logs").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NC_BRAIN_", "ANTHROPIC_"))}
    env.update({"NC_BRAIN_DB_URL": "sqlite:///" + (d / "brain.db").as_posix(), "NC_BRAIN_AUDIO_DIR": str(d / "audio"),
                "NC_BRAIN_ROUTERS": "rules", "NC_BRAIN_STT": "none", "NC_BRAIN_EMBED_BACKEND": "hash",
                "NC_BRAIN_WORKER": "0", "NC_BRAIN_WORKER_ID": name, "NC_BRAIN_SYNC_INTERVAL": "3600",
                "NC_BRAIN_BIND": "127.0.0.1"})
    if target:
        env["NC_BRAIN_SYNC_TARGET"] = target
    out = open(d / "serve.out", "wb")  # noqa: SIM115 - stays open for the child's lifetime
    p = subprocess.Popen([sys.executable, "-m", "notecad_brain.serve", "--port", str(port), "--logs", str(d / "logs")],
                         cwd=HERE.parents[1], env=env, stdout=out, stderr=subprocess.STDOUT)
    end = time.monotonic() + 60
    while time.monotonic() < end:
        if p.poll() is not None:
            raise SystemExit(f"{name} exited with {p.returncode} before answering: see {d / 'serve.out'}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return p
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    stop(p)
    raise SystemExit(f"{name} on :{port} never answered /health: see {d / 'serve.out'}")


def counts(db_path: Path, ws: str) -> dict:
    db = Database("sqlite:///" + db_path.as_posix())
    try:
        return {t: db.one(f"select count(*) as c from {t} where workspace_id=?", (ws,))["c"] for t in ("nodes", "tasks", "alerts")}
    finally:
        db.close()


def write_farm(db_path: Path, ws: str, nodes: int, rng: random.Random) -> int:
    db = Database("sqlite:///" + db_path.as_posix())
    try:
        before = db.one("select coalesce(max(seq), 0) as s from sync_changes")["s"]
        seed(db, ws, nodes, rng)
        return db.one("select count(*) as c from sync_changes where seq > ?", (before,))["c"]
    finally:
        db.close()


def sync_now(c: httpx.Client) -> tuple[dict, float]:
    t0 = time.perf_counter()
    r = c.post("/api/v1/sync/now", timeout=600).json()
    return r, (time.perf_counter() - t0) * 1000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", type=int, default=1000, help="nodes per synthetic farm (each one journals 1+ changes)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--port", type=int, default=18788, help="desktop brain; the hub is on port + 1")
    ap.add_argument("--where", default="cloud", help="label for the numbers: cloud or WABAKIPI")
    ap.add_argument("--out")
    a = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="ibmm-perf-sync-"))
    hub_port, desk_port = a.port + 1, a.port
    hub = start("edge-node", hub_port, tmp, None)
    try:
        desk = start("desktop", desk_port, tmp, f"http://127.0.0.1:{hub_port}")
    except SystemExit:
        stop(hub)
        raise
    rng = random.Random(6)
    runs: list[dict] = []
    ok = True
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{desk_port}") as c:
            sync_now(c)  # settle: both start empty apart from their own bookkeeping
            for i in range(a.runs):
                ws_push, ws_pull = f"perf-push-{i}", f"perf-pull-{i}"
                n_push = write_farm(tmp / "desktop" / "brain.db", ws_push, a.nodes, rng)
                r_push, ms_push = sync_now(c)
                n_pull = write_farm(tmp / "edge-node" / "brain.db", ws_pull, a.nodes, rng)
                r_pull, ms_pull = sync_now(c)
                st = c.get("/api/v1/sync/status").json()
                same = all(counts(tmp / "desktop" / "brain.db", w) == counts(tmp / "edge-node" / "brain.db", w)
                           for w in (ws_push, ws_pull))
                unsynced = st.get("pending_changes")
                good = bool(r_push.get("ok") and r_pull.get("ok") and same and not unsynced)
                ok &= good
                runs.append({"push_changes": n_push, "pushed": r_push.get("pushed"), "push_ms": round(ms_push),
                             "pull_changes": n_pull, "pulled": r_pull.get("pulled"), "pull_ms": round(ms_pull),
                             "same_rows": same, "pending_after": unsynced, "ok": good})
                print(f"run {i + 1}: push {n_push} changes in {ms_push:.0f} ms, pull {n_pull} in {ms_pull:.0f} ms, "
                      f"same rows {same}, waiting {unsynced}  {'PASS' if good else 'FAIL'}")
    finally:
        for p in (desk, hub):
            stop(p)
    med = {k: statistics.median(r[k] for r in runs) for k in ("push_changes", "push_ms", "pull_changes", "pull_ms")}
    print(f"median ({a.where}): push {med['push_changes']:.0f} changes {med['push_ms']:.0f} ms, "
          f"pull {med['pull_changes']:.0f} changes {med['pull_ms']:.0f} ms")
    if a.out:
        Path(a.out).write_text(json.dumps({"where": a.where, "nodes": a.nodes, "runs": runs, "median": med}, indent=2) + "\n",
                               encoding="utf-8")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
