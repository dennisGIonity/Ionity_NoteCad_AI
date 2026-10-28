<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# NoteCad build status

Newest phase first. Each phase: what was built, what was verified on WABAKIPI, what is still open.

## Phase 6: everything works, faster, current engines, a foldable mind map (28 October 2026)

Decision record: ADR 0013. Plan and findings: `docs\plans\PHASE6.md`. Numbers: `docs\perf\baseline-phase6.md`,
`stage2.md`, `stage4-map.md`. Screens: `docs\media\fold-*.png`.

**Built**
- About 50 defects fixed with a regression test each: live events that went deaf after a brain restart, jobs stuck
  after a crash, statuses that never faded, rule words ("more", "brand new", "No one"), a CSRF hole and DNS rebinding
  on this PC, Undo deleting later notes and keeping what an Inbox answer taught, notes never marked synced, skipped or
  blocked sync batches, a wiped hub never noticed, tus resumes that could corrupt audio, a silently re-pairable phone,
  phone battery drain, and the desktop not redrawing synced changes.
- Voice playback in the node's history; numbered migrations (`schema_migrations`, Supabase 0005-0006).
- Speed: rules answer plain field reports alone; Gemma sees short labels; no N+1 path queries; vectors as one
  matrix; hot-query indexes; faster start-up; map and QR load on first use.
- Engines: Vite 8, TypeScript 7, Capacitor 8.6, FastAPI 0.162, CTranslate2 4.8.4; d3-hierarchy for the map layout
  (dagre kept as fallback); Biome lint; Vitest and Playwright (installed Edge) added.
- The foldable mind map (main areas, levels, branches, all; badges with what is hidden; keyboard tree; animation;
  light and dark), and a foldable "Record onto" picker on the phone.

**Verified (WABAKIPI, SQLite)**

| Suite | Result |
|---|---|
| Brain pytest | 113 passed, 1 skipped (Postgres sync test: no Postgres here), 4 live deselected |
| Companion pytest | 45 passed |
| Desktop / phone | `tsc` 0 errors, Biome clean, Vitest 29 / 2 passed, npm audit 0 |
| Playwright (Edge, live stack) | 22 passed: 8 owner flows, 12 fold flows, 2 performance |
| ruff / pyright | clean / 0 errors (Optional-row warnings reported) on brain and companion |
| pip-audit | no known vulnerabilities |
| Showcase | 3/3 typed, 3/3 spoken, 3/3 rules only, 3/3 Gemma + rules in process |
| Golden notes | Gemma + rules 20/21 = 95.2 % (was 90.5 %); rules only 17/21 = 81.0 % |
| Sync | nothing left unsynced on either side after "Sync now" with the Edge AI Node |

| Metric | Baseline (Stage 0) | Phase 6 |
|---|---|---|
| Cold start (with `-Showcase`) | 28 s | 22 s (17.5 s without the showcase step) |
| Warm start | 22 s | 17.5-19.4 s |
| Note 2 "south 704 to 708", typed, in process | 11.7 s | **0.1 s** |
| Showcase typed, in process | 2.7 / 11.7 / 2.5 s | 3.3 / 0.1 / 1.8 s (note 1: GPU in a lower power state in the final run, Gemma 82 vs 98 tok/s) |
| Showcase spoken, live | 4.2 / 13.6 / 3.1 s | 4.9 / 2.5 / 3.6 s (same power caveat) |
| Gemma call per event | 2.34 s | 1.74 s (same session) |
| Retrieval per event, 2,000 nodes | 297 ms | 76 ms |
| Mind map payload, 2,000 nodes (HTTP p50) | 462 ms | 244 ms |
| 2,000-node map, first draw | 3.3 s | 1.4 s |
| Expand all / Collapse all, 2,000 nodes | n/a | 94 / 81 ms (target < 300 ms) |
| Panning, 2,000 nodes all open | 142.6 fps at 144 Hz (56 cards drawn) | 54.4 fps on a panel idling at 54.2 fps (60 Hz), 0 long frames |
| Capture's change on the map after `action.applied` | 521 ms | 266 ms |
| Desktop JavaScript loaded with the HUD | 560.7 KB raw / 183.5 KB gzip | 286 KB / 90.6 KB |
| VRAM, NoteCad's share | about 3.5 GB of 8 GB | unchanged (Whisper kept at float16) |
| SQL statements for the three showcase notes | 1,907 | 593 |

**Open**
- Postgres: the Postgres test parametrisation and Supabase migrations 0005-0006 were not run against a database
  (no Postgres on WABAKIPI). Before using Supabase: run the suite with `NC_BRAIN_TEST_PG_URL`.
- Tauri shell: `cargo check` and the installer need Rust + MSVC (not installed); the window also needs code signing
  for Smart App Control.
- Android: unit tests and the APK need a writable Android SDK with build-tools 35 and accepted licences; the Java
  changes of this phase were not compiled. The APK has not been tried on a device. iOS needs a Mac with Xcode 16+.
- Afrikaans speech: no Afrikaans recordings on this PC; Whisper settings were kept rather than tuned blind.
- Claude routing and prompt caching: no `ANTHROPIC_API_KEY` in the vault, so not measured.
- Ollama runtime 0.40.8 (0.40.12 is out; changes are Apple-specific); Python 3.14.4 on C: (3.14.9 is out).
- Phone app's foldable picker is type-checked, linted and built, not driven in a browser.

## Phase 5: multi-worker sync, phone capture, on-device outbox (23 October 2026)

From ADR 0012. Changes captured by database triggers into `sync_changes`, last writer wins per row, push/pull with
an Edge AI Node (`-EdgeNode`, :8789) or Supabase (`postgresql://...`), `action_log.synced_at` for "waiting to sync".
Phones upload with tus 1.0.0 and keep an outbox (IndexedDB, Android native files + WorkManager); "Pair a phone" shows
a QR; the LAN needs a token, this PC does not. Android capture bubble and iOS App Intent.

Verified: brain 76 passed on SQLite (1 skipped), 106 with Postgres; tuspy, tus-js-client and the Android
`TusUploader` (on a JVM) resume after drops; desktop and edge node converge without echo. Open then: APK on a device,
iOS on a Mac, Supabase project.
