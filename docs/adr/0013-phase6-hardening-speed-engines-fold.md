<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# ADR 0013: Phase 6: everything works, faster, current engines, a foldable mind map

Status: accepted, 2026-10-28. Author: Dennis Grobler. Builds on ADR 0012. Plan: `docs\plans\PHASE6.md`.
Numbers: `docs\perf\baseline-phase6.md`, `docs\perf\stage2.md`, `docs\perf\stage4-map.md`.

## Context

Phase 5 left a working stack with no front-end tests, no linters, a sync engine that could leave notes unsynced, and
a 12 s capture for "Today I planted field south 704 to 708". Phase 6 went through every part: fix, measure, speed
up, upgrade, and add a mind map that folds.

## Decisions

### Stage 1: everything works

1. **Each bug found gets a regression test** (`services\brain\tests\test_phase6.py`, `test_tus.py`, companion
   `test_companion.py`, `apps\*\src\**\*.test.ts`, `apps\desktop\e2e\flows.spec.ts`). The list of what was broken is
   in `docs\plans\PHASE6.md` (B1-B13, S1-S12, K1-K4, D1-D9, P1-P5).
2. **Sync guarantees "nothing unsynced after a sync"**: push reads the journal's end first; cursor and
   `synced_at` move in one transaction; the puller acknowledges (`POST /v1/sync/ack`) so the hub marks its own notes;
   one savepoint per incoming change with `sync_rejects` for rows that cannot be applied; journals carry an epoch so a
   wiped hub is noticed; a failed peer is dropped and retried with back-off up to 5 minutes. Supabase `0005` is
   generated from `sync.py` (`tools\gen_sync_migration.py`) and runs the capture trigger as `security definer`.
3. **A browser page on this PC is not trusted**: a state-changing request from a foreign `Origin` needs the token,
   even on loopback (a multipart POST needs no CORS preflight). Tokens are compared in constant time and accepted in
   the query string only on GET (EventSource, `<audio src>`).
4. **A pairing link is an offer**: the phone shows where notes would go and the owner confirms. `allowBackup` is off.
5. **Voice notes play back** in the node's history: `GET /v1/captures/{id}/audio` (files under the audio folder only).
6. **Static checks are part of the build**: ruff (pyflakes, bugbear) and pyright (basic) for both services; Biome for
   both apps. `db.one()` is Optional and is reported as a warning, not an error, on aggregate queries.
7. **Schema changes are numbered and forward-only**: `schema_migrations` in the SQLite runner, the same numbers as
   `supabase\migrations` (0006 adds the hot-query indexes); a test keeps them in step.

### Stage 2: speed (each kept change has numbers in `docs\perf\stage2.md`)

8. **The model sees short labels** (`n1`, `n2` …), not node ids, and answers one line of JSON: 2.34 → 1.74 s per
   Gemma call, golden notes 90.5 → 95.2 %.
9. **Rules answer alone when they are sure** of a plain field-work report (`rules_are_sure`; router `rules:sure` in
   provenance; `NC_BRAIN_RULES_FAST_PATH=0` turns it off): note 2 12.1 → 0.10 s in process.
10. **No N+1 on paths**, vectors kept as one matrix per workspace: retrieval on 2,000 nodes 297 → 76 ms, mind map
    634 → 83 ms. **sqlite-vec is not adopted**: at farm scale a numpy matrix product is under 1 ms.
11. **Start-up probes ports before HTTP** (Windows takes ~2 s to refuse a loopback connection), starts the companion
    and brain side by side and warms the models in the background: cold 28 → 17.5 s, warm 22 → 17.5 s.
    `OLLAMA_KEEP_ALIVE=-1` keeps the models loaded between notes.

### Stage 3: engines

Latest stable versions were looked up on the registries (npm, PyPI) and the web on 28 October 2026.

| Dependency | Was | Latest | Decision |
|---|---|---|---|
| Python | 3.14.4 | 3.14.9 (21 Oct) | **Keep**: the base interpreter lives on C:, which this phase does not touch. Upgrade with the next interpreter refresh |
| FastAPI / Starlette | 0.159.1 / 1.9.0 | 0.162.0 / 1.10.0 | **Upgraded**, suites green |
| Pydantic, uvicorn, numpy, httpx, RapidFuzz, jsonschema | | current | already latest |
| faster-whisper / CTranslate2 | 1.2.1 / 4.8.3 | 1.2.1 / 4.8.4 | **CTranslate2 upgraded** |
| PyAV | 15.1.0 | 19.0.2 | **Keep < 16**: faster-whisper still passes `metadata_errors`, removed in 16 |
| Ollama | 0.40.8 | 0.40.12 (27 Oct) | **Keep**: the changes since 0.40.8 are Apple-silicon speed-ups and Apple-only models; upgrading means a new signed runtime download (ask first). Next time the runtime is refreshed |
| Gemma 4 E2B / EmbeddingGemma 300M | | | **Keep** (below) |
| React / React DOM | 19.3.1 | 19.3.1 | latest |
| Vite | 7.3.7 | 8.3.5 | **Upgraded** (Rolldown runs under Smart App Control): build 3.7 → 0.25 s |
| @vitejs/plugin-react | 5.2.0 | 6.1.2 | **Upgraded** |
| Tailwind, @xyflow/react, Zustand, Tauri | | current | already latest |
| TanStack Query, framer-motion (motion) | not used | 5.105 / 14.7 | **Not added**: the store already does requests; fold animation uses CSS transitions on React Flow's transforms (no 40 KB dependency) |
| Capacitor | 8.5.3 | 8.6.0 | **Upgraded** |
| TypeScript | 5.9.3 | 7.0.2 | **Upgraded**: the Go compiler runs under Smart App Control; type check 2.6 → 0.33 s; only used for checking |
| Android Gradle Plugin / SDK | 8.13.0 / 36 | 9.x / 36 | **Keep**: AGP 9 needs Gradle 9 and Capacitor 8's templates are on 8.13; nothing can be built here without a full SDK |
| Lint | none | ESLint 10.13 / Biome 2.6.3 | **Biome**: one MIT binary (runs under Smart App Control), React hook rules included, 15-20 ms for each app |
| Python tooling | pip + venv | uv 0.13.6 | **Not switched**: uv runs under Smart App Control, but the venvs, CLAUDE.md and the start scripts are pip-based and installs are rare; adopt with the Python refresh |
| Test runners | pytest | pytest 9.2, Vitest 5, Playwright 1.64 | pytest upgraded; Vitest + Playwright added (Playwright drives the installed, signed Edge: no browser download) |

**Speech to text**

| Option | Accuracy (English) | Afrikaans | Speed / VRAM | Offline, licence, SAC | Decision |
|---|---|---|---|---|---|
| faster-whisper large-v3-turbo, float16 (current) | Open ASR ~7.6 % avg WER; all showcase notes filed right | Supported (Whisper's 99 languages) | RTF 0.068 here, 1.5 GB | yes, MIT, CTranslate2 wheels run | **Keep** |
| same, int8_float16 | same transcripts on our 5 samples | not measured (no Afrikaans audio here) | RTF 0.061, 1.3 GB | | not worth 200 MB without Afrikaans evidence |
| NVIDIA Parakeet TDT 0.6B v3 | ~6.3 % avg WER, far faster | **not in its 25 European languages** | very fast | CC-BY-4.0, needs NeMo/PyTorch | rejected: no Afrikaans |
| Canary-Qwen 2.5B | ~5.6 % WER, leaderboard top | not reported | larger | | rejected: no Afrikaans evidence, bigger |
| Deepgram nova-3 (cloud) | | | | needs a key and the internet | stays optional (already wired) |

**Local LLM (router + companion)**

| Option | Fit | Decision |
|---|---|---|
| Gemma 4 E2B Q4_K_M via Ollama (current) | 1.6 GB VRAM, 98 tok/s, JSON-schema output, 95.2 % golden notes after decision 8 | **Keep** |
| Gemma 4 E4B | better reasoning, about 3 GB: with Whisper and the embedder it leaves under 0.5 GB on 8 GB | not clear-cut; do not swap without a field test (the brief asks to stop and ask) |
| Qwen 3.5 / 3.6 small | the reliable-JSON reports are for the larger (27B+) models; no controlled comparison at 2-4B | no evidence to switch |

**Embeddings and vector search**: EmbeddingGemma 300M (0.4 GB) kept; vectors in SQLite as before, searched as one
in-memory numpy matrix per workspace (decision 10). sqlite-vec 0.1.9 not needed at this size.

**Tree layout for the mind map** (judged on the fold feature; `docs\perf\stage4-map.md` has the browser numbers).
Node 24, 2,000-node farm shape:

| Engine | Licence | All 2,000 nodes | Main areas + one level | Visible nodes that move when one branch opens (clicked node held still) |
|---|---|---|---|---|
| **d3-hierarchy `tree()`** (tidy tree) | ISC | **3 ms** | 0.1 ms | 0 of 43 |
| @dagrejs/dagre 3.1.3 (current) | MIT | 401 ms | 5.6 ms | 0 of 43 |
| ELK.js 0.12.1 `mrtree` | EPL-2.0 or GPL-3.0 | 608 ms | 8.6 ms | 0 of 43 |
| ELK.js `layered` | EPL-2.0 or GPL-3.0 | 752 ms | 16.6 ms | **41 of 43** |

**Decision: d3-hierarchy's tidy tree** lays out the tree (variable card heights through its separation function);
dagre stays available as a fallback (`localStorage notecad.layoutEngine = "dagre"`) until the field test passes;
the radial layout is unchanged. At 3 ms for the whole farm, layout stays on the main thread: a worker would cost
more in message passing than the layout itself (measured in Stage 4). ELK is heavier, slower and copyleft.

### Stage 4: the foldable mind map

12. **Fold logic is shared and framework-free**: `packages\core\src\fold.ts`, used by the desktop map and the phone's
    "Record onto" picker, tested on its own (26 Vitest cases).
13. **State = a default depth plus per-node exceptions** (`{ depth, expanded, collapsed }`). The brief asked for
    "expanded ids plus a default depth"; with expanded ids alone, folding one node inside an opened level would mean
    listing every other node, so the state would not stay small. `collapsed` holds only those exceptions.
    Level steps set the depth and clear the exceptions; per-node actions change only the exceptions.
14. **Fold is view state**: `localStorage` per device, workspace and layout (`notecad.fold.<ws>.<layout>`); never in
    `action_log` or `node_layouts`, never synced. The first visit shows the main areas (depth 1).
15. **Live changes never unfold**: a change inside a folded branch pulses the nearest card on screen and updates its
    badge; "Open" on the toast, the Inbox and "Go to" reveal only the path to the node.
16. **Zoom and fold do not fight**: fold decides which cards exist; zoom only decides how much a card shows (task
    lines go below 0.55, cards become status tiles below 0.4).
17. **Keyboard follows the WAI-ARIA tree pattern**; Space stays hold-to-talk and `/` (newly bound) opens the typed
    note; React Flow's own Delete/arrow handling is off. Light mode follows the system theme.
18. **Small models and labels**: with `n1`, `n2` … labels Gemma files more notes right (95.2 %); in the field it
    still sends vague notes ("Sort out the stuff") to the Inbox. An apparent regression in the end-to-end run was
    the brain having *learned* those phrases from the test's Inbox answers; Undo now forgets what an Inbox answer
    taught (decision found and fixed in Stage 4).

## Consequences

- Tests: brain 105 → see the final count in the build status; companion 45; desktop and phone Vitest; Playwright
  flows and map performance against the running stack in Edge.
- Postgres was not available on WABAKIPI: the Postgres parametrisations and the Supabase migrations 0005-0006 were not
  run against a database in this phase.
- No Claude key in the vault: Claude prompt caching is still to do and to measure.
