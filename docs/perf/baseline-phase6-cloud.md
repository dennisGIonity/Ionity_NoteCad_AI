<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# Phase 6 baseline from a clone (cloud)

Measured 22 November 2026 at commit `0e4ac11` (main) on the cloud machine in `env-cloud.md`: Linux, 4 vCPU, no GPU.
The stack ran keyless: rules router, hash vectors, no Gemma, no EmbeddingGemma, no Whisper
(`services/brain/tools/keyless_stack.sh`). **Every number on this page is cloud.** They compare only with later runs
on the same kind of machine, not with WABAKIPI. The WABAKIPI figures are at the end, copied from the build notes.

Phase 6 itself was built, measured and verified on WABAKIPI on 28 October 2026 (`baseline-phase6.md`, `stage2.md`,
`stage4-map.md`). This page adds what a clone can reproduce.

## Test suites (cloud)

| Suite | Command | Result |
|---|---|---|
| Brain, SQLite | `python -m pytest -q` | 193 passed, 1 skipped (Postgres sync test: no URL), 4 live deselected; **196 passed** with the 3 new cloud tests |
| Brain, SQLite + Postgres 16 | `NC_BRAIN_TEST_PG_URL=... python -m pytest -q` | **295 passed** (298 with the new tests) |
| Brain live tests | `-m live` | 4 skipped: need `NC_BRAIN_LIVE_URL` (Ollama) |
| Companion | `python -m pytest -q` | 48 passed, 3 deselected |
| ruff (brain, companion) | `ruff check .` | clean |
| pyright (brain) | `pyright` | **33 errors before** (only with psycopg installed, as on CI), 0 after; 76 Optional warnings (reported, as configured) |
| pyright (companion) | `pyright` | 0 errors, 1 warning |
| Generated files | `gen_sync_migration`, `gen_rls_migration`, `popia_inventory --check` | up to date (133 actions) |
| pip-audit | brain venv | no known vulnerabilities |
| npm audit | desktop / phone | 0 / 3 moderate (glob, minimatch, rimraf: dev tooling under `@capacitor/cli`; nothing high or critical) |
| Desktop | `npm run build`, `lint`, `test` | build ok, Biome clean, Vitest 40 passed |
| Phone | `npm run build`, `lint`, `test` | build ok, Biome clean, Vitest 10 passed |
| Playwright (Chromium 153, keyless stack) | `NC_E2E_CHANNEL=chromium npx playwright test` | **24/26 before**: the voice flow failed (no speech engine) and the POPIA log check read a fixed path. **26/26 after** (FixtureSTT, `NC_BRAIN_LOG`); "Sync now" with the Edge AI Node runs here and leaves nothing unsynced on either side |
| Showcase, live brain | `seed_farm_showcase.py --reset-clean --auto`, then `--check` | 3/3, then 3/3 |
| Showcase, in process | `field_test.py --showcase --routers rules` | 3/3 |
| Golden notes, rules only | `field_test.py --routers rules` | 17/21 = 81.0 % (WABAKIPI: 17/21) |

## Brain routes (cloud), 30 calls each, `perf_probe.py --only routes`

| Route | p50 ms | p95 ms |
|---|---|---|
| health | 1.8 | 2.0 |
| workspaces | 2.0 | 2.6 |
| mindmap showcase | 6.4 | 8.1 |
| mindmap perf-2000 (2,000 nodes) | 200.2 | 255.1 |
| digest | 4.4 | 4.9 |
| sync (workspace) | 7.1 | 8.1 |
| inbox | 2.1 | 4.2 |
| tasks | 2.4 | 2.9 |
| node | 2.4 | 6.0 |
| node history | 2.6 | 3.1 |
| sync status | 2.4 | 2.8 |

## Capture, apply and roll-up (cloud), `profile_capture.py --routers rules --embed hash --runs 3`

| Note | p50 |
|---|---|
| 1 "Wheel needs changing on tractor model John Deere 9550 - number 1" | 0.01 s |
| 2 "Today I planted field south 704 to 708" | 0.02 s |
| 3 "Ask Sipho to check the water pump on the North borehole" | 0.01 s |

| Stage, last run (7 events) | mean ms |
|---|---|
| retrieve | 2.5 |
| apply | 1.3 |
| route (rules) | 0.5 |
| roll-up | 0.4 |
| SQL statements for the three notes | 702 (WABAKIPI, with Gemma: 593) |

## Retrieval (cloud), `profile_retrieval.py --embed hash`, on a copy of the database

| Workspace | Nodes | retrieve p50 / max | mind map p50 / max |
|---|---|---|---|
| showcase | 39 | 1.6 / 7.1 ms | 1.2 / 1.8 ms |
| perf-2000 | 2,000 | 49.3 / 68.1 ms | 55.6 / 72.6 ms |

Hash vectors only. The WABAKIPI figure (76 ms per event at 2,000 nodes) includes EmbeddingGemma.

## Sync between two brains (cloud), `perf_sync.py --nodes 1000 --runs 3`

The desktop brain is on :18788 and the Edge AI Node on :18789, both real `notecad_brain.serve` processes over HTTP.
Each run writes a 1,000-node synthetic farm (about 1,500 journal changes) on one side and then calls "Sync now"
once.

| Run | Push | Pull | Same rows both sides | Waiting after |
|---|---|---|---|---|
| 1 | 1,525 changes in 502 ms | 1,548 in 561 ms | yes | 0 |
| 2 | 1,516 in 499 ms | 1,518 in 543 ms | yes | 0 |
| 3 | 1,471 in 505 ms | 1,524 in 585 ms | yes | 0 |
| **median** | **1,516 in 502 ms (about 3,000 changes/s)** | **1,524 in 561 ms** | | |

## Desktop and phone builds (cloud)

| | Desktop | Phone |
|---|---|---|
| `vite build` (after `tsc -b`), 3 runs | 1.29-1.45 s | 1.22 s |
| JavaScript, all chunks | 623.5 KB raw / 197.2 KB gzip | 358.9 KB / 107.5 KB |
| Largest chunks | index 302.9 KB, flow (React Flow, on first map open) 236.8 KB, MindMap 25.1 KB, browser 23.7 KB | |

Phase 6 measured the JavaScript loaded with the HUD on WABAKIPI as 286 KB / 90.6 KB. The figure here is every
chunk, including the map, the QR code and the panels that load on first use.

## Map in headless Chromium (cloud), `e2e/perf.spec.ts` and `e2e/fold.spec.ts`

| Measure | cloud | Target |
|---|---|---|
| 2,000-node farm, first draw | 1,721 ms | |
| Panning 2,000 nodes | 60 fps, p95 frame 16.8 ms, 0 long frames, 9 cards drawn | 60 fps: **confirm on WABAKIPI** (headless frames are capped at 60) |
| Expand all / Collapse all, 2,000 nodes | 123 / 76 ms | < 300 ms: met (cloud) |
| Panning with everything open | 60 fps, 0 long frames | |
| Capture to map (after `action.applied`) | 285-301 ms | < 1 s: met (cloud) |

## WABAKIPI reference figures (not reproducible here)

| Measure | Before Phase 6 | Phase 6 (28 October 2026) |
|---|---|---|
| Cold / warm start | 37 s / 22 s (the Phase 6 brief); Stage 0: 28 s / 22 s | 22 s with `-Showcase` / 17.5-19.4 s |
| Showcase typed (notes 1 / 2 / 3) | 3.3 / 11.6 / 2.3 s | 3.3 / 0.1 / 1.8 s |
| Showcase spoken | 4.0 / 12.4 / 2.8 s | 4.9 / 2.5 / 3.6 s |
| Retrieval per event, 2,000 nodes | 297 ms | 76 ms |
| Capture to map | 521 ms | 266 ms |
| Expand all / Collapse all, 2,000 nodes | n/a | 94 / 81 ms |
| Golden notes, Gemma + rules | 90.5 % | 95.2 % (20/21) |

`tools\verify_phase6.ps1` measures these again on WABAKIPI and writes `docs\perf\phase6-wabakipi.md`.
