<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# Phase 6 plan: make it all work, make it fast, upgrade the engines, foldable mind map

Written 28 October 2026 after Stage 0 (`docs\perf\baseline-phase6.md`). Decision record: ADR 0013.
Three read-only audits ran in parallel (brain; sync engine, edge node and companion; desktop and phone apps). Their
findings are merged below, de-duplicated and ordered by what they break. "C" = confirmed by running code or reading
it end to end, "S" = suspected.

## Findings to fix in Stage 1

### Brain

| # | Finding | Fix | Test |
|---|---|---|---|
| B1 | C. Rules-only showcase note 3 fails ("Ask Sipho to check the water pump on the North borehole": no task) | find the rules regression | `test_showcase` rules case |
| B2 | C. Live events go deaf after a brain restart: broker ids restart at 1, a reconnecting client's `Last-Event-ID` is higher, so every new event is dropped | broker ids start from a boot epoch (ms clock), and an id above the broker's last id is treated as "from now" | restart test |
| B3 | C. A job left `running` by a killed brain is never picked up again | re-queue `running` jobs on start | test |
| B4 | C. Rule false positives: "more" = môre (due tomorrow), "brand"/"down" = critical, "No one" = "No 1" | tighten the patterns | one test each |
| B5 | C. Stored `info` / `done` statuses never fade: `decay()` runs only from `POST /maintenance` | run decay from the worker loop every 10 minutes | test |
| B6 | C. A full SSE client queue raises inside the event loop (QueueFull escapes the try) | put on the loop through a guarded helper | test |
| B7 | C. Inbox insert and event upsert are two transactions | one transaction | |
| B8 | C. `retrieve.py:34` backslash in an f-string: SyntaxError on Python 3.11, which `pyproject` allows | rewrite | ruff |
| B9 | C. 46 ResourceWarnings: no `Brain.close()`, multipart forms never closed | close both | `-W error::ResourceWarning` |
| B10 | S. CSRF from any web page on this PC: loopback is trusted and a multipart POST needs no preflight | loopback requests with a foreign `Origin` header must carry the token | test |
| B11 | C. Token compared with `!=`; `?token=` accepted on every route (ends in logs) | `hmac.compare_digest`; query token only on GET | test |
| B12 | C. Undo of a capture that created a node also deletes notes and tasks later captures put on it | keep a created node when later captures used it | test |
| B13 | C. `node_parent` built for every event and never used (`validate.py:49`) | remove | |

### Sync engine and edge node

| # | Finding | Fix | Test |
|---|---|---|---|
| S1 | C. Race: an empty push jumps the cursor to `last_seq()` read later, skipping a capture committed in between; it is never pushed or marked | read the max seq first, move the cursor only to what was scanned | test |
| S2 | C. Push cursor and `synced_at` saved in two transactions | one transaction | |
| S3 | C. Rows written on the hub itself never get `synced_at` (only the pusher marks) | the puller acknowledges what it applied; the hub marks those rows | Phase 6 gate test: nothing unsynced after a sync both ways |
| S4 | S. One failing change rolls back the whole batch and blocks sync forever (edge unique key, FK) | a savepoint per change, failures go to `sync_rejects`, edges upsert on their natural key | test |
| S5 | C. Postgres hub: seq visible in commit order, so a concurrent pusher can make a puller skip rows | pull re-reads a window behind the cursor (dedup makes repeats free) | unit test of the window; Postgres not available here |
| S6 | C. A reset hub is never noticed: cursors keyed by worker id only | journal epoch returned by `/sync/status`; cursors reset when it changes or the cursor is ahead | test |
| S7 | C. Postgres connection never reconnected; fixed 15 s retry, no back-off, no log | drop the peer on error, exponential back-off to 5 min, log | test |
| S8 | C. 4 round trips per change against Postgres | prefetch dedup and latest per batch | |
| S9 | S. Supabase: the capture trigger is not `security definer`, so app writes through PostgREST fail on RLS | migration `0005` | generated-SQL test |
| S10 | C. 0004 is a hand copy of `sync.py`; a new table is silently not synced | generator + test that 0004/0005 match `sync.py` | test |
| S11 | C. tus: a crash between write and offset save leaves extra bytes that the next PATCH appends after | write at the stored offset and truncate | test |
| S12 | C. tus file I/O and `finish()` block the event loop | thread pool | |

### Companion

| # | Finding | Fix |
|---|---|---|
| K1 | C. `/route-offline` 500s when the model returns a JSON list or a non-number confidence | guard |
| K2 | C. Brain digest call: no `raise_for_status`, no token | fix |
| K3 | C. `/chat` holds the global model lock across a 2 s brain call and the Ollama call, serialising owners | lock only for in-process llama.cpp |
| K4 | C. Starlette test-client deprecation (httpx) | use the replacement the warning names |

### Desktop app

| # | Finding | Fix |
|---|---|---|
| D1 | C. `sync.applied` is never subscribed, so synced changes do not redraw | subscribe |
| D2 | C. A CLOSED event stream is never reopened; quick workspace switches leak a stream | reconnect with back-off; close before awaiting |
| D3 | C. Losing focus while Space is held records for 120 s | stop on `blur` / `visibilitychange` |
| D4 | C. The pill's mic and the typed note ignore the selected node; Space uses it | one rule: the selected node is the context |
| D5 | S. Inbox toast writes back a stale capture snapshot | functional update |
| D6 | C. Escape closes the pairing dialog and also deselects | dialog stops the event |
| D7 | C. React Flow defaults are live: Delete/Backspace remove a node from the view, arrow keys move it | turn both off (the fold keyboard model needs the arrows) |
| D8 | C. Dark only: `colorMode="dark"`, hard-coded slate | colour tokens with light and dark values, follow the system |
| D9 | C. Accessibility: cards not focusable, collapse button without `aria-expanded`, tabs without tabpanels, dialog without focus trap | tree roles (Stage 4), labels, focus |

### Phone app

| # | Finding | Fix |
|---|---|---|
| P1 | C. Security: any `notecad://pair` link silently re-points the phone at another brain; `allowBackup="true"` puts the token in backups | confirm screen; `allowBackup="false"` |
| P2 | C. The live stream never reconnects after unpair, re-pair or CLOSED; old cursor reused on a new brain | reset `es` and `lastEvent` |
| P3 | C. Battery: 5 s poll forever reads every outbox row with its audio; outbox re-read per 256 KB chunk; meter re-renders the whole screen 60 times a second; listeners doubled | poll only while something waits and the stream is down; count without blobs; per-field selectors |
| P4 | C. 401/413 items stay parked forever after re-pairing | clear on pair |
| P5 | C. Android: `OutboxStore.update` not synchronised; HEAD without `Upload-Offset` and 404 retry forever | synchronise; treat as permanent |

### Not fixable on this PC (reported, not hidden)

Postgres suite (no Postgres), `cargo check` (no Rust/MSVC), Android unit tests (SDK incomplete and read-only),
iOS (needs a Mac). No Claude key, so Claude prompt caching can be built and unit-tested but not measured live.

## Stage 2: efficiency (measure, change, measure)

Order by expected payoff, each kept only with numbers in `docs\perf\stage2.md`:

1. **Capture path.** Rules short-circuit when the rules are sure (exact alias hit, numbers agree, clear margin);
   per-capture cache of paths, aliases, vectors and the query embedding; build paths in memory instead of
   `path_titles` per node (about 245 queries per event today); route a range's siblings from one template.
2. **Ollama.** `OLLAMA_KEEP_ALIVE` in the start script so models stay loaded; one pooled HTTP client per router.
3. **Database.** Indexes for `tasks(node_id)`, `alerts(node_id)`, `nodes(parent_id)`, `edges(dst_id)`,
   `inbox(capture_id)`, `action_log(workspace_id, synced_at)`; `synchronous=NORMAL` under WAL; roll-up writes only
   when something changed. Mind-map payload for 2,000 nodes (462 ms) without N+1.
4. **STT.** Whisper compute type and beam: numbers are in the baseline (RTF 0.056-0.068). Only change if VRAM or
   Afrikaans evidence supports it.
5. **Startup.** Overlap warm-ups; target warm start < 20 s.
6. **Desktop.** Lazy map and pairing chunks; per-id selectors; stable node data so memo works; no relayout on
   selection or highlight; patch the map from events instead of refetching the whole map where possible; layout in a
   worker; fold makes layout run on visible nodes only.
7. **Phone.** Bundle, polling, outbox reads (P3).

## Stage 3: engines

Look up current stable versions on the web for every major dependency; compare STT, local LLM, embeddings and vector
search, tree layout (d3-hierarchy, ELK.js, dagre, judged on the fold feature), Python tooling (uv), JS tooling (Biome
vs ESLint + Prettier) and test runners. Smart App Control blocks unsigned native binaries, so every candidate that
ships one is tried on WABAKIPI before it is chosen. Swaps go behind a config flag with the old engine as fallback.

## Stage 4: foldable mind map

- `packages\core\src\fold.ts`: pure functions over `{id, parent_id}` trees: visible set, expand/collapse one level
  (global and per node), subtree, set depth, reveal path, hidden counts and aggregated status (worst status, alerts,
  tasks, progress). State = `{ expanded: string[], depth: number }`, saved per device and lens in `localStorage`
  (never in `action_log`, never synced). Vitest for every function and the edge cases in the brief.
- Desktop: fold slice in the store; chevron + badge (`+14 · 2 alerts · 3 tasks`) on every node with children; folded
  nodes keep status colour, echo dot and progress; toolbar (Main areas, ±1 level, all, level stepper); chevron
  click / Shift+click; context menu (Expand all below, Collapse all below, Focus this branch); WAI-ARIA tree keyboard
  (arrows, Shift+arrows, Enter; Space and `/` untouched, `/` becomes the typed-note shortcut it was documented as);
  first open = Main areas, then last state per lens; grow/fold animation with the clicked node fixed on screen, none
  under reduced motion; captures into folded branches pulse the nearest visible ancestor; "Open" / go-to reveals only
  the path; zoom level of detail only changes how much a visible card shows.
- Phone context picker uses the same fold functions.
- Playwright flows from the brief, plus Expand all / Collapse all under 300 ms on 2,000 nodes.

## Gates

As in the brief: Stage 1 all suites green on SQLite (Postgres not available here), showcase 3/3 typed, spoken and
rules-only, nothing unsynced after a sync; Stage 2 nothing regresses and every kept change has numbers; Stage 3
Stage 1 gates still pass; Stage 4 tests green and a screenshot sequence in `docs\media\`.
