<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# ADR 0009: Mind map read model, live events and context-anchored capture (Phase 2)

Status: accepted, 2026-10-22. Author: Dennis Grobler. Builds on ADR 0008.

## Decisions

1. **One mind map payload, computed by the brain** (`notecad_brain/mindmap.py`, `GET .../mindmap`). Node types:
   root, category (category and group kinds, plus a virtual People / Delegation), entity, task (open-task leaf),
   member. Channels fold into their parent. Each node carries display status, echo dot, decay
   (fresh / fading / settled / active), reminders (scheduled / due soon / overdue), `progress_pct`, roll-up counts and
   its latest notes with provenance (capture, router, source, anchor). Edges: `belongs_to_category`, `has_task`,
   `assigned_to`, `related_to`. Every device shows the same thing because nothing is computed on the client.
2. **Progress from what the owner said.** A stated `progress_pct`, else a done/total pair in the attributes
   (`planted_ha / area_ha`, phase-aware: harvest prefers `harvested_ha`), else done/open tasks for projects and fields,
   else done status. Categories average their entities, weighted by hectares where there are hectares.
3. **Granular live events with ids.** `capture.queued -> stt.transcribing -> stt.completed -> router.resolving ->
   action.applied | inbox.created -> capture.completed`, `action.undone`, `node.updated`. Every event has a rising id;
   the mind map returns `cursor`, so the UI loads the map, then opens the stream with `Last-Event-ID = cursor` and
   misses nothing. The old `/events` path still works.
4. **One capture endpoint** for multipart audio, raw audio, JSON or form text. Typed notes are processed at once,
   audio is queued for the worker unless `wait=true`. Typed notes also emit `stt.completed` so the UI follows one
   sequence.
5. **Context anchor.** `context_node_id` is stored on the capture (`captures.anchor_node_id`, Supabase migration
   0002). Retrieval lifts the anchor (floor 0.72) and its 1-hop neighbours (parent, children, channels, links); the
   rules router uses the anchor when nothing else is named outright; Gemma sees the anchor first and is told about
   it. A thing named outright still wins ("the main water pump is leaking" said on Tractors goes to the pump).
6. **The companion reads the map.** The brain digest carries `map.lines` (NEEDS WORK, PROGRESS, ALL OK) and, with
   `?focus=`, the open node. The companion's chat takes `context_node_id`, so "how much of this is planted?" is
   answered for the node on screen.

## Results (22 October)

- 46 brain tests on SQLite, 67 with Postgres; 42 companion tests.
