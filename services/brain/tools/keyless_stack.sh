#!/usr/bin/env bash
# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
#
# The stack without keys, models or a GPU, for a clone on Linux (cloud sessions, CI). WABAKIPI uses
# services\start_notecad.ps1 instead; this script only mirrors the env vars that start_brain.ps1 sets.
#   tools/keyless_stack.sh start [DATA_DIR]   brain :8788 (rules router, no STT, hash vectors), companion :8787,
#                                             Edge AI Node :8789 (hub only) as the brain's sync target
#   tools/keyless_stack.sh seed  [DATA_DIR]   showcase (3 notes, rules), roles-showcase, perf-2000
#   tools/keyless_stack.sh stop  [DATA_DIR]
# Playwright against it (apps/desktop): NC_E2E_CHANNEL=chromium NC_BRAIN_LOG=DATA_DIR/brain/logs/api.log npx playwright test
# PY (default services/brain/.venv/bin/python) picks the interpreter. Nothing here reads a secret.
set -euo pipefail
cmd="${1:-start}"
here="$(cd "$(dirname "$0")/.." && pwd)"          # services/brain
root="$(cd "$here/../.." && pwd)"
data="${2:-${NC_KEYLESS_DATA:-$root/data/keyless}}"
py="${PY:-$here/.venv/bin/python}"
mkdir -p "$data/brain/logs" "$data/edge-node/logs" "$data/companion"

wait_up() {  # url, name
  for _ in $(seq 1 120); do curl -fsS "$1" >/dev/null 2>&1 && { echo "  $2 up: $1"; return 0; }; sleep 0.5; done
  echo "  $2 did not answer at $1" >&2; return 1
}

brain_env() {  # name port
  export NC_BRAIN_DB_URL="sqlite:///$data/$1/brain.db" NC_BRAIN_AUDIO_DIR="$data/$1/audio"
  export NC_BRAIN_ROUTERS=rules NC_BRAIN_STT=none NC_BRAIN_EMBED_BACKEND=hash NC_BRAIN_BIND=127.0.0.1
  export NC_BRAIN_COMPANION_URL=http://127.0.0.1:8787 NC_BRAIN_WORKER_ID="$1"
  unset ANTHROPIC_API_KEY NC_BRAIN_DEEPGRAM_KEY NC_BRAIN_SYNC_TARGET NC_BRAIN_TLS_PORT NC_BRAIN_TLS_CERT || true
}

case "$cmd" in
  start)
    ( brain_env edge-node 8789; export NC_BRAIN_WORKER=0
      cd "$here"; nohup "$py" -m notecad_brain.serve --port 8789 --logs "$data/edge-node/logs" \
        >"$data/edge-node/serve.out" 2>&1 & echo $! >"$data/edge-node.pid" )
    ( export NC_COMPANION_DATA_DIR="$data/companion" NC_COMPANION_LLM_BACKEND=none NC_COMPANION_EMBED_BACKEND=hash
      cd "$root/services/companion"; nohup "$py" -m uvicorn notecad_companion.api:app --host 127.0.0.1 --port 8787 \
        >"$data/companion/serve.out" 2>&1 & echo $! >"$data/companion.pid" )
    # the brain answers voice notes with a fixed transcript (FixtureSTT): no speech model on a clone
    ( brain_env brain 8788; export NC_BRAIN_WORKER=1 NC_BRAIN_SYNC_TARGET=http://127.0.0.1:8789 NC_BRAIN_STT=fixture
      cd "$here"; nohup "$py" -m notecad_brain.serve --port 8788 --logs "$data/brain/logs" \
        >"$data/brain/serve.out" 2>&1 & echo $! >"$data/brain.pid" )
    wait_up http://127.0.0.1:8789/health edge-node
    wait_up http://127.0.0.1:8787/health companion
    wait_up http://127.0.0.1:8788/health brain
    ;;
  seed)
    cd "$here"
    db="$data/brain/brain.db"
    "$py" tools/seed_farm_showcase.py --reset-clean --auto          # the three notes through the running brain
    "$py" tools/seed_farm_showcase.py --check
    "$py" tools/seed_farm_showcase.py --reset-clean --id roles-showcase
    "$py" tools/seed_synthetic_farm.py --db "$db"
    # the fake microphone of e2e/flows.spec.ts plays data/samples/showcase/showcase_3.wav. WABAKIPI has the spoken
    # note; a clone gets a 5 s voice-like tone (no STT runs here, so only its length and format matter)
    wav="$root/data/samples/showcase/showcase_3.wav"
    [ -f "$wav" ] || "$py" - "$wav" <<'PY'
import math, struct, sys, wave
from pathlib import Path
out = Path(sys.argv[1]); out.parent.mkdir(parents=True, exist_ok=True)
rate = 16000
with wave.open(str(out), "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(b"".join(struct.pack("<h", int(9000 * (0.6 + 0.4 * math.sin(2 * math.pi * 3 * t / rate))
        * (math.sin(2 * math.pi * 180 * t / rate) + 0.5 * math.sin(2 * math.pi * 360 * t / rate)) / 1.5))
        for t in range(rate * 5)))
print(f"  wrote {out} (tone)")
PY
    ;;
  stop)
    for n in brain companion edge-node; do
      f="$data/$n.pid"; [ -f "$f" ] && { kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; }
    done
    ;;
  *) echo "usage: $0 start|seed|stop [DATA_DIR]" >&2; exit 2 ;;
esac
