<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# ADR 0012: Multi-worker sync, phone capture and the on-device outbox (Phase 5)

Status: accepted, 2026-10-23. Author: Dennis Grobler. Builds on ADR 0008 (brain) and ADR 0011 (start command).

## Context

The desktop brain was the only worker. A farm needs notes from phones in the field, a second machine (the Edge AI
Node in the farm office) that keeps working when the desktop is off, and later the cloud (Supabase). Phones lose
signal all the time, so a note must never depend on the network being there when it is spoken.

## Decisions

1. **Changes are captured by the database, not the code.** Triggers on every synced table write a row to
   `sync_changes` (table, key, U/D, the row as JSON, workspace, origin worker, time, the origin's sequence number).
   This catches every code path (pipeline, undo, inbox, roll-ups) without touching them. SQLite and Postgres use
   the same design; `supabase/migrations/0004_sync_journal.sql` is generated from `notecad_brain/sync.py`.
2. **Last writer wins, per row.** A change is applied only when its `(time, origin)` is newer than what the row
   last saw. Each change is applied once (`origin + origin_seq`). While remote changes are applied, capture is
   switched off (SQLite: a `sync_state` flag; Postgres: `set_config('notecad.applying', '1', true)`), so nothing
   echoes back. Status roll-ups run in the same quiet window.
3. **`action_log.synced_at` means "a peer has it".** It is set after a successful push, and on arrival for rows
   received from a peer. The desktop's "Waiting to sync" counts the rows still without it.
4. **Two kinds of peer, one engine.** `HttpPeer` talks to another brain (`/api/v1/sync/push|pull|status`): the Edge
   AI Node is just a brain started with `-Name edge-node -Port 8789 -HubOnly`. `PostgresHub` writes and reads the
   Supabase journal directly. Set `NC_BRAIN_SYNC_TARGET` (vault) and the brain pushes and pulls every 15 s; a pull
   that changes the map publishes `sync.applied` and the desktop redraws. Embeddings, jobs and audio files are not
   synced: each worker rebuilds embeddings from the synced rows.
5. **Phones upload with tus 1.0.0.** `POST /api/v1/workspaces/{ws}/uploads` (creation, creation-with-upload,
   termination, expiration, `X-HTTP-Method-Override`). The phone names the capture (`capture_id` in the metadata),
   so a retry after a drop-out lands on the same capture. An upload that stopped half way resumes at the offset the
   brain reports.
6. **The phone saves first, sends later.** The web layer keeps an outbox in IndexedDB (audio blob, context node,
   recorded time, state, tus URL, retries with back-off). On Android the capture bubble writes to a native outbox
   (`files/outbox/<id>.m4a` + JSON) and WorkManager uploads it with the same tus protocol when there is a network,
   even with the app closed.
7. **LAN access needs a token; this PC does not.** `start_notecad.ps1 -Lan` binds `0.0.0.0` and writes a random
   `NC_BRAIN_API_TOKEN` into the vault if there is none. Requests from loopback stay trusted
   (`NC_BRAIN_TRUST_LOOPBACK=1`) so the desktop app needs no token. "Pair a phone" in the desktop app shows a QR of
   `notecad://pair?u=<brain>&t=<token>&w=<workspace>`; `GET /api/v1/pairing` only answers this PC.
8. **Capture triggers per platform.**
   - Android: a foreground service (type microphone) with a draggable overlay bubble (tap to record, tap to save,
     long press to close); without the overlay permission, the notification's Record/Stop does the same. A launcher
     shortcut "Record note" opens the app recording.
   - iOS: an App Intent "Record a NoteCad note" (App Shortcut, iOS 16+). Assign it to the Action Button
     (Settings > Action Button > Shortcut), add it to Control Center, or say it to Siri. It opens the app straight
     into recording; the web outbox does the rest. iOS has no background recorder: Apple does not allow one.

## Consequences

- The Android APK builds here (`apps/mobile`, Capacitor 8, minSdk 24, target 36). The iOS project is generated and
  ready, but must be built and signed on a Mac with Xcode 16+.
- Two brains on one PC must not both load Whisper and Gemma: the edge node on this PC runs with `-HubOnly`.
- A Supabase project needs migrations 0001-0004 and `NC_BRAIN_SYNC_TARGET=postgresql://...` in the vault.
- Conflicts are resolved per row, not per field. Two people renaming the same node at the same second keep the later
  one; the other edit stays in `action_log` and can be seen in the node's history.

## Verified

- Brain: 76 tests pass on SQLite (1 skipped), 106 with Postgres (`tests/test_sync.py`, `tests/test_tus.py`): desktop and edge
  node converge without echo, deletes and undo travel, a third worker joins through the Supabase hub, tus resumes
  after a drop and is idempotent, the token is required off this PC.
- Real clients: tuspy and tus-js-client resume after an abort; the Android `TusUploader` (run on a JVM) uploads,
  resumes half-sent files and repeats safely, and stops on a wrong token (401). Stored audio is byte-identical.
