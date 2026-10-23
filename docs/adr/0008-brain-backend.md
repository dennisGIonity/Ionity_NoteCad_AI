<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# ADR 0008: The brain backend, rebuilt

Status: accepted, 2026-10-22. Author: Dennis Grobler. Blueprint ION-ARC-NOTECAD-2026-001, sections 3.2-3.5, 4.

## Context

The Phase 1 and 2 code reported done on 18 October was not found on WABAKIPI or in Google Drive, so the brain was
rebuilt from the blueprint in `services/brain`, alongside the companion.

## Decisions

1. **One schema for SQLite and Postgres.** Text ids, ISO-8601 UTC times, JSON as text. The desktop and the AEDi
   Edge AI Node run on a single SQLite file; Supabase gets the same tables plus row-level security
   (`supabase/migrations/0001_notecad_core.sql`, checked on Postgres 16, 31 policies). The tree is a materialised
   path; pgvector and ltree can be added later without changing the brain.
2. **Apply in Python, in one transaction, with an inverse per change.** One code path for both databases, and
   Undo is exact. Provenance (Policy 986 AED, router, fallbacks) is written on every `action_log` row.
3. **Router chain: Claude, then local Gemma 4, then rules.** Claude is used when a key is present; the desktop
   GPU runs Gemma 4 E2B through Ollama; rules always answer. The model only proposes; validation decides.
4. **Guards on top of the small model**, each added after a real mistake on WABAKIPI: no new nodes unless the
   owner says something new arrived; a place or a person is not what a note is about; "it" / "dit" points back to
   the previous event; only names the owner said can receive a task; places must be mentioned.
5. **Delegation by name.** "Ask Sipho to...", "Vra Sipho om...", "Sipho moet..." are matched to members and person
   nodes (fuzzy 85). A match assigns the task, links the node to the person and notifies them; no match leaves the
   task with the owner and keeps the name as a hint. Critical alerts notify owners and editors.
6. **Status is computed.** Own status, display status (own plus channel children), child_worst (echo dot), open
   counts, and decay (info 24 h, done 48 h) are all server-side.
7. **The Inbox learns.** When the owner picks the branch for a held note, the proposal is applied there and a
   short phrase of the owner's words becomes an alias, so the same words route on their own next time.

## Results (22 October)

- 34 tests on SQLite, 50 including the Postgres runs, 3 live tests with Gemma 4 on the RTX 4060.
- End to end on WABAKIPI (Ollama, brain :8788, companion :8787): an Afrikaans first-run answer builds the owner's branches
  in 4.7 s (starter pack + Gemma 4, with the owner's own spelling); "Die hoofpomp lek baie erg. Vra Sipho om dit môre reg
  te maak." files a critical alert and urgent task on the pump and a task for Sipho due tomorrow 17:00 in 4.8 s; the
  companion then lists both open tasks in 1.1 s.
- 20 golden field notes (21 events): Gemma 4 with guards 90-95 % right first time (about 2 s per event); rules
  alone 81 %. The guards were tuned on these notes, so the Phase 1 exit check is still 20 notes recorded in the
  field.

## Not done yet

- Claude router not run against the live API (no key on this machine yet).
- Audio on the desktop needs faster-whisper or a Deepgram key; typed notes work today.
- Push delivery (FCM/APNs) reads the `notifications` table; the sender is Phase 3.
