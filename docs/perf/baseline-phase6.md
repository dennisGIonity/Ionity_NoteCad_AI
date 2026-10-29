<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# Phase 6 baseline (Stage 0)

Measured 28 October 2026 on WABAKIPI (Windows 11, RTX 4060 Laptop 8 GB, 144 Hz panel), at commit `58fa962`,
before any Phase 6 change. Nothing was changed to take these numbers except the new measuring tools listed at the end.
`data\` was copied to `data\archive\pre-phase6-20261028-180749\` first.

## Inventory

| Part | Language / runtime | Key packages (installed) | Entry point | Port | Tests |
|---|---|---|---|---|---|
| Brain | Python 3.14.4 (`services\brain\.venv`) | FastAPI 0.159.1, Starlette 1.9.0, Pydantic 2.14.1, uvicorn 0.54.0, faster-whisper 1.2.1, CTranslate2 4.8.3, PyAV 15.1.0, numpy 2.5.4, httpx 0.28.1, RapidFuzz 3.14.6, jsonschema 4.26.0 | `notecad_brain.api:create_app` via `tools\start_brain.ps1` | 8788 (edge node 8789) | pytest, 9 files |
| Companion | Python 3.14.4 (`services\companion\.venv`) | FastAPI, Pydantic 2, httpx, numpy | `notecad_companion.api` via `tools\start_local.ps1` | 8787 | pytest, 1 file |
| Models | Ollama (`runtime\ollama`, signed) | `notecad-gemma4-e2b` (Gemma 4 E2B Q4_K_M), `notecad-embeddinggemma` (300M Q8_0); Whisper large-v3-turbo (CTranslate2, `models\whisper`) | `ollama serve` | 11434 | live-marked pytest |
| Desktop app | TypeScript 5.9.3, Node 24.20.0 | React 19.3, Vite 7.3, Tailwind 4.3, @xyflow/react 12.12, @dagrejs/dagre 3.1, zustand 5.0, qrcode, lucide-react; Tauri 2.12 (`src-tauri`) | `apps\desktop\dist` served at `/app/`; `npm run dev` on 5173 | 8788/app, 5173 | none before Phase 6 (no lint, no Vitest, no Playwright) |
| Phone app | TypeScript 5.9.3 | Capacitor 8.5, React 19.3, idb 8, tus-js-client 4.3, zustand 5; Android Gradle project (minSdk 24, target 36), Java sources for the bubble, outbox and tus uploader | `apps\mobile` (`npm run dev` on 5174) | 5174 dev | template Android tests only |
| Scripts | Windows PowerShell 5.1 | `services\start_notecad.ps1`, `services\brain\tools\start_brain.ps1`, `services\companion\tools\start_local.ps1`, `services\allow_phones_firewall.ps1` | | | |
| Tools | Python | `seed_farm_showcase.py`, `field_test.py`, `e2e_demo.py`, `phase2_demo.py` (brain); `demo_owner.py`, `train_lora.py`, `lora_smoke.py` (companion) | | | |
| Cloud schema | SQL | `supabase\migrations\0001`-`0004` | | | |

## Test suites

| Suite | Command | Result | Last known |
|---|---|---|---|
| Brain, SQLite | `.venv\Scripts\python.exe -m pytest -q` | **76 passed, 1 skipped, 4 deselected** in 9.9 s (skip: `test_sync.py:198`, `NC_BRAIN_TEST_PG_URL` not set) | 76 / 1 |
| Brain, Postgres | `NC_BRAIN_TEST_PG_URL=... pytest` | **not run: no Postgres on WABAKIPI** (no server, no Docker) | 106 |
| Companion | `.venv\Scripts\python.exe -m pytest -q` | **42 passed, 3 deselected**, 1 warning (Starlette: `httpx` with the test client is deprecated) | 42 |
| Desktop `tsc` | `npx tsc -b --noEmit` | 0 errors (strict on) | |
| Desktop lint / Vitest / Playwright | | **did not exist** | |
| Phone `tsc` | `npx tsc -b --noEmit` | 0 errors | |
| Android unit tests | `android\gradlew.bat test` | **BUILD FAILED**: Android SDK incomplete (only `platforms\android-36` and `cmdline-tools` in a read-only `C:\Program Files (x86)\Android\android-sdk`; build-tools 35 licence not accepted). The only tests are the template examples | |
| Tauri shell | `cargo check` | **not run: no Rust toolchain** (`cargo`, `rustc` not installed) | compiled once elsewhere |

## Running stack

| Check | Result |
|---|---|
| Cold start `start_notecad.ps1 -Showcase -NoOpen` (Ollama not running) | **All green in 28 s** (script's own clock) |
| Warm start (Ollama running, models unloaded, files cached) | **22 s** wall clock to "All green" |
| Router chain | `claude, local, rules`. The vault has **no `ANTHROPIC_API_KEY`**, so Claude fails at once and Gemma files everything: this baseline is the offline path |
| `seed_farm_showcase.py --reset-clean --auto` (typed, live brain) | **3/3**: 3.5 s, **12.6 s**, 2.5 s |
| `seed_farm_showcase.py --reset-clean --audio data\samples\showcase` (spoken) | **3/3**: 4.2 s, **13.6 s**, 3.1 s. Whisper heard "track to model" and "Sifo"; still filed right |
| `seed_farm_showcase.py --check` | 3/3 |
| `field_test.py --showcase --routers local,rules --embed openai` | **3/3**: 2.7 s, 11.7 s, 2.5 s |
| `field_test.py --showcase --routers rules` | **2/3: FAIL note 3** ("no task for Sipho on North Borehole Pump"). ADR 0011 recorded 3/3 |
| `field_test.py --routers local,rules --embed openai` (20 golden notes, 21 events) | 19/21 = **90.5 %** in 43.7 s |
| `field_test.py --routers rules --embed openai` | 17/21 = **81.0 %** (target 85 %) |

## Metrics

| Metric | Baseline | Target (PLAN-0001 / prompt) |
|---|---|---|
| Cold start | 28 s | |
| Warm start | 22 s | < 20 s |
| Typed showcase latency (live, Gemma) | 3.5 / 12.6 / 2.5 s | typed p95 < 4 s |
| Spoken showcase latency | 4.2 / 13.6 / 3.1 s | |
| Gemma 4 E2B decode speed | **98 tokens/s** (p50 of 5) | |
| Gemma time to first token (warm, short prompt) | **72 ms** p50 | |
| Whisper large-v3-turbo real-time factor (float16, beam 5, VAD; 5 files, 34.7 s of audio) | **0.068** (2.35 s for 34.7 s) | |
| VRAM, idle desktop without IBMM | 3,259 MiB (Windows shell, browsers, Claude app) | |
| VRAM, full stack steady | **6,814 / 8,188 MiB**: IBMM about 3.55 GB (Gemma 1.6 GB, EmbeddingGemma 0.4 GB, Whisper about 1.5 GB) | fits with headroom |
| RAM | brain 809 MB, companion 72 MB, Ollama 57 MB (+ llama-server runners, not counted) | |
| Desktop bundle (raw) | `index` 319.9 KB, `flow` 240.8 KB, CSS 55.5 KB, Tauri `window` 13.5 KB (gzip: 103.6 + 79.9 + 10.0 KB). Map code loads with the HUD | |
| 2,000-node map, first draw | **3.3 s** | |
| 2,000-node map, panning | **142.6 fps** (p95 frame 7.1 ms, 0 long frames; 56 nodes rendered after fit, viewport culling on) | 60 fps |
| Capture's change on the map after `action.applied` | **521 ms** (refetch starts at 497 ms: a 250 ms debounce restarted by later events, then the whole map) | < 1 s |
| `GET .../mindmap` showcase (35 nodes) | p50 6.2 ms, p95 7.6 ms | |
| `GET .../mindmap` perf-2000 (2,000 nodes, 2.08 MB) | **p50 462 ms**, p95 491 ms | |

Brain route latency (30 calls each, loopback, p50 / p95 ms): health 1.2 / 1.4; workspaces 1.5 / 1.9; digest 4.8 / 5.8;
workspace sync 10.0 / 10.9; inbox 1.3 / 1.8; tasks 1.6 / 2.3; node 1.6 / 2.2; node history 2.0 / 3.1;
sync status 1.7 / 2.1. Raw numbers: `docs\perf\probe-baseline.json`.

Whisper variants measured at the same time (same 5 files; all transcripts identical except punctuation and
"number one"/"number 1"):

| compute | beam | VAD / batch | RTF |
|---|---|---|---|
| float16 | 5 | VAD | 0.068 |
| int8_float16 | 5 | VAD | 0.061 |
| float16 | 1 | VAD | 0.061 |
| int8_float16 | 1 | VAD | 0.056 |
| float16 | 5 | batched 8 | 0.061 |

## Why showcase note 2 takes 12 s (first look)

"Today I planted field south 704 to 708" is split by `expand_ranges` into five events, and each event makes its own
Gemma call (about 2.3 s each), its own query embedding, apply transaction, roll-up and companion call, one after the
other. Whisper is about 0.4 s of a spoken note. The fix belongs in Stage 2: skip the model when the rules are already
sure (each "field south 70x" is an exact alias hit with matching numbers) and do per-capture work once.

## Failures and gaps, with how to reproduce

| # | What | Reproduce |
|---|---|---|
| F1 | Rules-only showcase note 3 fails: no task for Sipho on North Borehole Pump | `cd services\brain; .venv\Scripts\python.exe tools\field_test.py --showcase --routers rules` |
| F2 | Postgres suite cannot run on WABAKIPI (no Postgres) | `pytest -rs` shows `test_sync.py:198` skipped |
| F3 | No Rust toolchain: `cargo check` for `src-tauri` cannot run | `where cargo` |
| F4 | Android unit tests do not build: SDK incomplete and read-only | `cd apps\mobile\android; .\gradlew.bat test` |
| F5 | Desktop has no lint, unit or browser tests | `apps\desktop\package.json` scripts |
| F6 | Companion test run warns: `httpx` with Starlette's test client is deprecated | companion `pytest -q` |
| F7 | Brain tests leak 46 ResourceWarnings (SQLite connections and multipart temp files not closed) | brain `pytest -q -W default` |
| F8 | Rules-only golden notes 81 % (below the 85 % field gate; Gemma 90.5 %) | `field_test.py --routers rules --embed openai` |
| F9 | Ollama is called through `/v1/chat/completions`, which sends no `keep_alive`; `OLLAMA_KEEP_ALIVE` is unset, so models unload after 5 idle minutes and the next note pays a reload | `curl :11434/api/ps` after 6 idle minutes |
| F10 | The desktop never refreshes on `sync.applied` (listed as refreshing but never subscribed) | `apps\desktop\src\lib\store.ts:13-16` |

Code-level findings from the Stage 0 audits (brain, sync + companion, desktop + phone) are merged into
`docs\plans\PHASE6.md`.

## Tools added for measuring (no behaviour change)

- `services\brain\tools\seed_synthetic_farm.py`: workspace `perf-2000`, 2,000 nodes in 7 main areas, statuses, 292
  open tasks, 66 alerts.
- `services\brain\tools\perf_probe.py`: route p50/p95, Gemma TTFT and tokens/s, Whisper RTF by compute type and
  beam, VRAM and RAM.
- `apps\desktop\playwright.config.ts`, `apps\desktop\e2e\perf.spec.ts`: map first draw, panning frame rate and
  capture-to-map time in the installed Microsoft Edge.
