<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# ADR 0011: One start command, a clean showcase, end-to-end checks (Phase 4)

Status: accepted, 2026-10-23. Author: Dennis Grobler. Builds on ADR 0010.

## Decisions

1. **One command.** `services\start_notecad.ps1` starts Ollama and the companion, loads Gemma 4 E2B and
   EmbeddingGemma onto the GPU, builds the UI only when needed, starts the brain, picks the UI (the Tauri window when
   built, else the app the brain serves at `/app/`; `-Ui dev` for Vite on :5173), then polls every part and prints a
   health table with `[ OK ]` in green. It waits for the speech model to warm and stops waiting for anything still
   down after 30 s. `-Status` prints the table alone.
2. **The brain reports readiness.** `/health` carries `stt_ready` (loading, ready or the error) and `stt_device`.
3. **Workspaces can be archived and removed.** `GET /workspaces/{id}/export` writes every row as JSON;
   `DELETE /workspaces/{id}?confirm={id}` removes the workspace, its jobs and its audio. The showcase tool always
   archives to `data\archive\` before removing, and stale test workspaces are only removed with `--yes`.
4. **A showcase that checks itself.** `tools\seed_farm_showcase.py` builds the same farm and checks the same three
   results over HTTP (live, typed or spoken) and in process (`field_test.py --showcase`, the tests), from the mind
   map payload the desktop draws.

## Brain changes found by the showcase

- "John Deere 9550 - number 1" must beat #2, which shares the 9550: a node whose own number was not said is capped
  below one whose numbers all were. "number one" is normalised to "number 1".
- "Wheel needs changing": "needs changing / fixing / replacing / a service" is a to-do word, and a problem the owner
  says needs doing becomes a task as well as an alert (Gemma filed it as a warning only).

## Results (23 October, WABAKIPI)

- Cold start to all green in 37 s (Ollama, companion, brain, Whisper on CUDA, UI), warm restart 22 s.
- Showcase from a clean workspace with Gemma: 3/3 typed (3.3 s, 11.6 s, 2.3 s) and 3/3 spoken (4.0 s, 12.4 s, 2.8 s;
  Whisper heard "track to model" for "tractor model" and the note still landed on John Deere 9550 #1). Rules alone
  3/3. Brain 61 tests on SQLite, 89 with Postgres; golden notes unchanged (rules 81 %).
