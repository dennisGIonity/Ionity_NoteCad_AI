<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# IBMM build status

Newest phase first. Each phase: what was built, what was verified on WABAKIPI, what is still open.

## POPIA action audit: every action checked, every open finding fixed (29 October 2026)

`docs\compliance\popia-action-register.md` is generated from the code by `tools\popia_inventory.py` (`--check` in CI):
**133 actions** (75 brain routes, 15 companion routes, 3 spoken commands, 4 background threads, 19 synced tables,
5 files and copies, 12 app actions): **120 compliant, 13 need a human decision**
(`docs\compliance\popia-human-actions.md`, 11 items). Assessment v1.1:
`docs\compliance\Ionity_NoteCad_POPIA_Assessment_v1.1.docx` + PDF.

**Built** (the seven findings v1.0 left open, and what the audit found)

| What | Where | Proof |
|---|---|---|
| One person's copy (s23) and erasure (s24), member or a person on the map | `subjects.py`, People & seats, Inspector, phone menu | `test_popia_actions.py`, `e2e/popia.spec.ts` |
| Cloud transfer gate (s72): off by default, owner per workspace, logged; restricted branches never leave | `routers.py`, `stt.local_only`, `privacy.py` | `test_no_note_leaves_this_pc_while_the_gate_is_off` |
| The notice before a member's first note (s18); notice v2: Information Officer, workplace monitoring, cloud | `privacy.must_read`, `PrivacyNotice.tsx`, `PrivacySheet.tsx` | `test_a_member_records_nothing_before_reading_the_notice`, e2e |
| Security headers + CSP; security log (refusals, exports, erasures, deletions, transfers); breach runbook | `api.py`, `breach-runbook.md` | `test_answers_carry_security_headers_and_refusals_are_logged` |
| Invite code never in a URL: `POST /v1/join/preview`, desktop `#join=` | `api.py`, `App.tsx` | e2e network log + `api.log` |
| A worker's health or disciplinary details held for the owners (s26-33) | `text.sensitive_about`, pipeline | `test_a_note_with_a_workers_health_is_held_for_the_owners` |
| Phone token in the Android Keystore | `TokenVault.java` | `TokenVaultTest` (CI) |
| Retention on hubs too; a Supabase hub's journal compacted; the companion forgets with the period and on deletion | `api.py`, `retention.py`, companion `/forget` | `test_forget_reaches_the_companion_memory` |
| Disk encryption and the loopback note in the status table | `start_notecad.ps1` | WABAKIPI shows `WARN`: not encrypted |

**Fixed while testing:** the join throttle counted this PC (e2e joins got 429): now only network callers; a flaky
fold keyboard test (it pressed ArrowDown before focus had moved): now waits for focus; leftover test members matched
the erasure check: the spec uses a unique name per run.

**Verified.** Brain 193 (169 before), companion 48 (47), desktop 40 (37), phone 10 (7); ruff, pyright,
`gen_sync`/`gen_rls`/`popia_inventory --check`; `npm ci`, build, lint, test for both apps: all exit 0. CI green
(Postgres 17, Supabase 0001-0009 twice, Android with TlsPinTest and TokenVaultTest, APK, Tauri). Field test 20/21
(95.2 %, as before), showcase 3/3. Playwright: three full runs in a row, 25 passed and 1 skipped each (Sync now needs
the edge node); report in `docs\media\playwright-report`; frame rates at the panel's idle rate.

**Open.** The 11 human actions (Information Officer, operator agreements, lawful basis, legal review of the notice,
retention on real workspaces, archive period, disk encryption on WABAKIPI, LoRA training, breach owners, the cloud
gate, children). Needs a real phone: the WebView pinning and Keystore on a device. Needs a Mac: iOS. The `-Lan` path
was checked with a pinned client on this PC, not from a phone.

## POPIA: the five high-priority fixes (29 October 2026)

`docs\compliance\Ionity_NoteCad_POPIA_Assessment_v1.0` (technical, not legal advice) found IBMM not yet compliant in
four areas and listed twelve fixes. The five high ones are built:

| # | Finding | What changed |
|---|---|---|
| 1 | No retention limit (s14) | `retention.py`: per-workspace periods for recordings, transcripts and the activity log, set by an owner in the privacy notice (nothing is deleted until then); the worker purges every 6 hours; `NC_BRAIN_ARCHIVE_DAYS` for `data\archive` |
| 2 | Deleted data lived on in the sync journal and archives (s14, s24) | each purge keeps only the newest change per row in `sync_changes`; deleting a workspace leaves only data-less tombstones and clears `view_changes`, `sync_conflicts`, `sync_rejects` |
| 3 | Device tokens in the access log (s19) | `POST /v1/tickets`: a 10-minute ticket in EventSource and audio URLs instead of the token; `serve.py` writes `api.log` weekly, 4 weeks kept, with tokens, tickets and invite codes blanked |
| 4 | Plain HTTP on the farm network (s19) | `serve.py --lan`: plain HTTP on loopback only, HTTPS on :9788 with the brain's own certificate (`tls.py`), its SHA-256 in pairing and invite links; Android trusts only that certificate (`TlsPin`, WebView and uploads) and allows no cleartext but localhost |
| 5 | No privacy notice (s18) | migration 9 / Supabase 0009; `GET|PUT .../privacy`, `POST .../privacy/ack`; the desktop notice (owner sets the contact and periods and accepts; "Not now" for a day) and the phone sheet (each member reads it once) |

**Verified.** Brain 182 tests on SQLite (13 new in `test_popia.py`), companion 47, desktop 40, phone 10 (with the new
pinning test), on this PC; a test brain with `--lan` answered pinned HTTPS on the LAN address, refused plain HTTP there,
and an unpinned client was refused. Android (`TlsPinTest`) and Postgres run in CI.

**Open.** Phones paired over plain HTTP must pair again (the app says so). The WebView's pinning is not yet tried on a
real phone. The other seven findings of the report (per-person export and erasure, BitLocker check, Keystore token,
security headers, the cloud-transfer gate, the loopback note, Information Officer and the documents) are still open.

## Roles, seats and permission-aware sync (ADR 0014, 29 October 2026)

One business, one map, many people: owner (1), manager (2), employee (3), and the system (0). Restricted branches
(visibility all / manager / owner) inherit down the tree; every read goes through the caller's view, every write is
judged by the Applier after validation, and sync checks each change against its author's current role.

| Step | What | Commit |
|---|---|---|
| 1 | ADR 0014, the owner's three answers recorded (editors without a login become employees; a revoked phone hands in its last recordings once, as quarantined proposals, then wipes; the shared token acts as the first owner for one release) | af6ac7c |
| 2 | Backups (`data\archive\roles-*`); migrations 7 and 8 on SQLite and Supabase (0007 frozen by hash, 0008 and the RLS generated from `permissions.py` by `tools\gen_rls_migration.py`, `--check` in CI) | 0ba0e6d |
| 3 | `permissions.py` (matrix, `decide`, Principal, View); every write judged (allowed / Inbox proposal / refused and logged), every read filtered (map, digest, search, prompts, history, export, events, audio); sync checked on arrival, rank conflicts kept | 8fb5c85, be97313 |
| 4 | Seats (local ledger, no billing provider), one-time invites in a QR, joining, per-device `nct_` tokens (hashed), 410 + wipe on revoke, the phone's own copy with tombstones and reset | 081d8e7, 96e1873 |
| 5 | People & seats panel, Inbox proposals, lock badges, role-aware controls (desktop and phone), voice admin commands in English and Afrikaans | 4b58e72 |
| 6-7 | Showcase seed with roles, the joining-employee e2e, live numbers, these docs | this commit |

**Verified.** CI on Postgres 17 and SQLite: brain 253, companion 47, Android 13 (the native wipe included), phone 7,
desktop 37 (role gating in Vitest). Live on WABAKIPI after migrations 7 and 8 ran on `data\brain\brain.db`: the
three showcase notes 3/3 (4.1, 1.7, 2.2 s) on `roles-showcase`; Playwright `roles.spec.ts` (an employee joins from a
second browser context and never sees Financials, on the map, in the API or in what the app was sent; revoking stops
the device with 410) and every other suite pass. Numbers in `docs\perf\roles.md`: an employee's map +12.9 % of the
owner's, a 349-node visibility change 14.8 ms, the live 2,000-node map 243.6 → 251.8 ms.

**Open**

- The phone token is kept in app storage; Android Keystore encryption (ADR 0014, decision 19) is not built yet.
- The Android unit test covers the native wipe; tombstones in the phone's copy are tested in the web layer (Vitest).
- With a Supabase target, the role re-check runs in the pushing worker (RLS guards the rows, not the author's rank).
- The live `showcase` workspace was left as it was (resetting it deletes data): the role-aware farm is
  `roles-showcase` (`seed_farm_showcase.py --reset-clean --id roles-showcase`; e2e with `NC_E2E_WS=roles-showcase`).

## Phase 6 follow-up: the open items (29 October 2026)

What Phase 6 left open because WABAKIPI cannot do it (no Postgres, no Rust or Android SDK, nothing on C:, Smart
App Control blocks self-built binaries) now runs on GitHub: `.github/workflows/ci.yml`, on every push. The repo is
public, so the runners are free. Step logs need a GitHub sign-in; test counts are notices on each run's page.

**Closed**

| Item | How | Result |
|---|---|---|
| Postgres | CI: Postgres 17 service, `NC_BRAIN_TEST_PG_URL` | Brain 158 passed (every `farm` test on SQLite and Postgres, the Postgres sync test included), companion 45 |
| Supabase 0005-0006 | CI: 0001-0006 in order on an empty database (with `auth.uid()`, the API roles and `supabase_realtime` stubbed) | All apply; `gen_sync_migration.py --check` up to date |
| Android Java (Phase 6 changes) | CI: `assembleDebug testDebugUnitTest` on JDK 21 | Compiles; debug APK 4.5 MB kept as a run artifact. 12 unit tests pass (was 1, the template's): new `TusUploaderTest` (6, a fake tus server; also run on the plain JDK here) and `OutboxStoreTest` (5, Robolectric 4.17) |
| Tauri shell | CI (Windows): `cargo check --locked`, `tauri build` | Compiles; unsigned NSIS + MSI installers (5.0 MB) kept as a run artifact |
| Phone "Record onto" picker | Driven in the browser pane at 375 px | Main areas, one branch at a time, search, pick. Fixed: the brain refused the phone dev server's origin (:5174), and the picker reopened on the last search |
| Afrikaans speech | `tools\afrikaans_wer.py` on 120 FLEURS af_za clips (`docs\perf\afrikaans-wer.json`) | See below; `NC_BRAIN_STT_LANGUAGES` added |

**Afrikaans, large-v3-turbo on the RTX 4060** (word error rate on FLEURS' normalised text)

| How Whisper is called | WER | Language found | s/clip |
|---|---|---|---|
| Before: no hint (the apps send none), English keyterm prompt | 35.5 % | af 109, en 6, is 4, nl 1 | 0.71 |
| **Now: no hint, picks English or Afrikaans only** (`NC_BRAIN_STT_LANGUAGES=en,af`) | **35.0 %** | af 109, en 11 | 0.74 |
| Told "af", English prompt / no prompt / Afrikaans prompt | 34.4 / 33.6 / 33.9 % | af 120 | 0.45 |
| Told "af", int8_float16 / beam 1 | 34.3 / 34.9 % | af 120 | 0.43 / 0.40 |

The prompt, compute type and beam move WER by about a point; the model sets the floor. No Icelandic or Dutch text
reaches the router any more, and the English showcase recordings stay English.

**Afrikaans, second pass: the prompt's language and large-v3** (same prompts and GPU load for both models; 19 English
clips added: the showcase recordings and 16 golden notes in a Windows voice; ADR 0013 addendum)

| Whisper, as the brain calls it | Afrikaans | English | s/clip af / en |
|---|---|---|---|
| turbo, English prompt (before) | 36.8 % | 6.1 % | 0.79 / 0.64 |
| **turbo, prompt in the picked language (now, default)** | **34.7 %** | **6.1 %** | 0.80 / 0.63 |
| large-v3, prompt in the picked language (`NC_BRAIN_WHISPER_MODEL=large-v3`) | 32.2 % | 2.8 % | 1.42 / 0.88 |

large-v3 fits in VRAM next to Gemma (7.2 of 8.2 GB in use) but is about twice as slow on Afrikaans; turbo stays the
default until field recordings decide.

**Also fixed in CI itself:** on the Windows runner PowerShell checked only the last command of each step (a failing
lint would have passed); every job now runs bash with `pipefail`. Actions moved to current majors (Node 24). A failing
Android build or test writes its error and cause chain as annotations, readable without a sign-in. Robolectric on
Android 16 + JDK 21 needs `--add-exports=java.base/jdk.internal.access=ALL-UNNAMED` (in `app/build.gradle`).

**Verified** (CI run 7, commit `6ebcb03`): brain 158 passed (SQLite + Postgres 17), companion 45, desktop Vitest 29,
phone Vitest 2, Android unit tests 12, APK and installers built. On WABAKIPI: brain 115 passed / 1 skipped
(Postgres), phone type-check, Biome and Vitest clean.

**Still open**
- Claude routing and prompt caching: needs `ANTHROPIC_API_KEY` in `E:\.claude\_vault\notecad.env`.
- Afrikaans accuracy: 34.7 % WER on turbo with the prompt in the picked language; large-v3 32.2 % at twice the time
  (downloaded, one setting away). Field recordings of the owner should decide between them.
- Code signing: the CI installers and APK are unsigned. Smart App Control will block the Tauri window on WABAKIPI
  until it is signed; the APK needs a release key for anything beyond sideloading.
- The APK on a real phone; iOS on a Mac with Xcode 16+.
- Ollama 0.40.12 (Apple-only changes) and Python 3.14.9 (on C:) left as they are.

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
| VRAM, IBMM's share | about 3.5 GB of 8 GB | unchanged (Whisper kept at float16) |
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
