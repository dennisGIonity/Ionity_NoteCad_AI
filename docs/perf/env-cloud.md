<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# The cloud machine (Phase 6 cloud gap-fill, 22 November 2026)

Every number marked **cloud** in `docs\perf\` was taken here. It is a Linux container with no GPU. Its figures only
compare before and after on this same machine and are **not WABAKIPI figures** (Windows 11, RTX 4060 8 GB).

## Machine

| | cloud |
|---|---|
| OS | Ubuntu 24.04.5 LTS, Linux 6.18 (container) |
| CPU | Intel Xeon @ 2.10 GHz, 4 vCPU |
| RAM | 15 GiB |
| GPU | none: no CUDA, Whisper, Gemma or EmbeddingGemma here |
| Python | 3.14.6 (uv-managed venv in `services/brain/.venv`; companion installed into the same venv) |
| uv | 0.11.32 |
| Node / npm | 22.23.5 / 10.9.9 (WABAKIPI and CI: Node 24) |
| Postgres | 16.15 (throwaway cluster on :5432; CI uses 17) |
| Java | OpenJDK 21.0.13 |
| Rust | 1.97.0 (no MSVC: the Tauri window is still built on CI's Windows runner) |
| Chromium | Chrome for Testing 153.0.8010.12 (preinstalled, `/opt/pw-browsers/chromium`); Playwright 1.64.1 wants build 1248, so `NC_E2E_BROWSER_PATH` points at the one on the machine |
| pwsh / PSScriptAnalyzer | absent (see the PR for whether they could be installed) |
| Ollama | absent: no models, keyless only |
| Android SDK | absent: the APK and Android unit tests stay on CI |

## Python packages (installed from `pyproject.toml`; there is no Python lockfile, only lower bounds)

FastAPI 0.165.0, Starlette 1.10.0, Pydantic 2.14.4, uvicorn 0.54.0, numpy 2.5.5, httpx 0.28.1, RapidFuzz 3.14.6,
jsonschema 4.26.0, psycopg 3.3.9, cryptography 50.0.2, python-multipart 0.0.34; pytest 9.2.0, ruff 0.17.6,
pyright 1.1.414, pip-audit 2.10.1. faster-whisper is not installed (the `[whisper]` extra; no GPU).

## Node packages (from the lockfiles, `npm ci --include=dev`)

| | Desktop (`apps/desktop`) | Phone (`apps/mobile`) |
|---|---|---|
| Runtime | React 19.3.1, @xyflow/react 12.12.0, d3-hierarchy 3.1.2, @dagrejs/dagre 3.1.3, zustand 5.0.16, qrcode 1.5.4, lucide-react 1.63.0, @tauri-apps/api 2.12.4 | React 19.3.1, Capacitor 8.6.0 (core, android, ios; app 8.1.2), idb 8.0.4, tus-js-client 4.3.1, zustand 5.0.16 |
| Tooling | TypeScript 7.0.2, Vite 8.3.5, Tailwind 4.3.3, Biome 2.6.3, Vitest 5.0.5, jsdom 30.1.3, Playwright 1.64.1, @tauri-apps/cli 2.12.4 | TypeScript 7.0.2, Vite 8.3.5, Tailwind 4.3.3, Biome 2.6.3, Vitest 5.0.5, fake-indexeddb 6.2.6 |

## Entry points and ports

| Service | Entry point | Port |
|---|---|---|
| Brain | `python -m notecad_brain.serve --port 8788` (WABAKIPI: `services\brain\tools\start_brain.ps1`) | 8788 (HTTP, loopback), 9788 HTTPS with `--lan` |
| Edge AI Node | the same, `--port 8789`, `NC_BRAIN_WORKER=0` (`-HubOnly`) | 8789 |
| Companion | `python -m uvicorn notecad_companion.api:app` (`services\companion\tools\start_local.ps1`) | 8787 |
| Desktop app | `apps/desktop/dist`, served by the brain at `/app/`; `npm run dev` | 8788/app, 5173 |
| Phone app (browser) | `apps/mobile`, `npm run dev` | 5174 |
| Ollama (WABAKIPI only) | `runtime\ollama` | 11434 |
| Keyless stack (Linux, CI) | `services/brain/tools/keyless_stack.sh start|seed|stop` | 8787, 8788, 8789 |
