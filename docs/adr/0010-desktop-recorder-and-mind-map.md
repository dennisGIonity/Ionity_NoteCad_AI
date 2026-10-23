<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# ADR 0010: Desktop recorder HUD and interactive mind map (Phase 3)

Status: accepted, 2026-10-23. Author: Dennis Grobler. Builds on ADR 0009.

## Decisions

1. **One web app, two shells.** `apps/desktop` (React 19, TypeScript, Vite 7, Tailwind 4, React Flow 12, Dagre,
   zustand) runs in a browser, is served by the brain at `/app/`, and is wrapped by a Tauri v2 transparent window
   (`src-tauri/`). No second server on the desktop.
2. **The brain's live events drive everything.** The app loads the map, then opens the event stream from its
   `cursor`; the status ticker, the toast, node pulses and map refreshes all come from those events, so a note
   recorded on the phone shows on the desktop the same way.
3. **Capture is fire-and-follow.** Audio (MediaRecorder, Opus) and typed notes are posted with `wait=false`; the
   upload returns at once and the stream reports transcription, filing and the result.
4. **Tasks on things sit inside their card; tasks on categories are leaves.** Keeps the map readable at farm scale.
5. **Undo and placement are one tap.** Undo calls the brain's inverse transaction; branch pills resolve the Inbox
   item, which also teaches the brain the owner's words.
6. **Sync readiness now, sync later.** `action_log.synced_at` (migration 0003) counts changes not yet shared with
   another worker; the corner indicator shows it with local store health (`GET /workspaces/{id}/sync`).

## Brain changes made for the UI

- `GET /workspaces` (list), `GET /nodes/{id}/history` (action log per node), `GET /workspaces/{id}/sync`,
  `PATCH /nodes/{id}` attributes; `action.applied` carries node titles, paths and the id the map shows them under.
- **Number ranges**: "planted field south 704 to 708" becomes one event per numbered node the owner has.
- **Field jobs**: "planted / harvested / sprayed" on a field sets its hectares (the whole field, or the hectares
  said), so progress fills on the map. Future or negated work changes nothing; validation caps at the field area.
- **Numbers must agree**: a node whose name has a different number than the one said ("field 704" vs Field South
  705) is capped in retrieval, whatever the embeddings say.
- CORS on both services for the Vite, Tauri and `/app/` origins.

- **Speech to text on WABAKIPI**: faster-whisper large-v3-turbo on the RTX 4060 (CUDA libraries from the
  nvidia-cublas / nvidia-cudnn wheels in the brain venv, no system CUDA), model in `models\whisper`, warmed at
  startup, CPU fallback. PyAV is held below 16 (faster-whisper still passes `metadata_errors`). The vocabulary prompt
  is a punctuated sentence: a bare word list made Whisper drop punctuation, and the note then did not split.
- **Reported field work is done work**: Gemma once called "Today I planted field south 705" a to-do; a past-tense
  field job with no to-do words now always fills progress and never creates a task.

## Results (23 October, WABAKIPI)

- Typed "Today I planted field south 704 to 708" with the map open: five fields filled to 100 %, the ticker counted
  "filing 2 of 5", the toast read "Updated 5 nodes in Fields / South Block"; Undo reverted all 20 changes.
- Spoken "John Deere two needs a new hydraulic hose. Ask Thabo to fix it before Friday." (WAV): transcribed, split
  into two events, filed on John Deere 9550 #2 with a task for Thabo due Friday in 6.5 s (Whisper on the GPU plus
  two Gemma calls); 7.2 s for the first note after a restart.
- Companion asked from the John Deere 9550 #2 drawer answered with that tractor's task, owner and due date.
- Brain 55 tests on SQLite and 80 with Postgres, 4 live Gemma tests; companion 42; desktop type-checks and builds
  on WABAKIPI.

## Not done yet

- The Tauri installer is not built: WABAKIPI has no Rust toolchain. The shell compiles (`cargo check`).
- Voice was tested with synthesised speech files; recording from the microphone in the browser needs a person.
