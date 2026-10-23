<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# NoteCad Master Architecture and Implementation Plan

Document PLAN-0001 · 22 October 2026 · Blueprint ION-ARC-NOTECAD-2026-001 v1.2 · builds on ADR 0007 (companion) and ADR 0008 (brain).

## 0. Summary

NoteCad already turns a typed or spoken note into notes, tasks, alerts, delegation and status on a graph, with Undo and a companion
that reads the open work. Three things are missing for the product described in the brief:

1. **The graph does not yet understand identities, ranges, progress or reminders.** "John Deere 9550 number 1" becomes a note on
   `Tractors`; "south 704 to 708" is one event on one node; there is no progress roll-up and no reminder scheduler.
2. **The data layer is single-device.** IDs are random UUIDv4 strings, times have one-second precision, Undo and delete remove rows,
   and `action_log` has no device, clock or sync cursor. It works today but would not merge cleanly with a second worker.
3. **There is no frontend.** No `apps/` folder exists; the brain has no CORS and its SSE stream needs an `Authorization` header that a
   browser `EventSource` cannot send.

The plan keeps every current module and test, extends them in place, and adds `apps/web` (recorder HUD + mind map) and later
`apps/desktop` (Tauri overlay). Ten phases, each ending with tests that run on WABAKIPI.

### Decisions to confirm before Phase 3

| # | Decision | Proposal |
|---|---|---|
| D1 | Auto-create branches from a voice note | Create missing asset, field and group nodes automatically under an existing category; create a missing **top-level** category only when it is in the taxonomy list (Vehicles, Fields, Livestock, Irrigation, Infrastructure, Staff, Admin and their Afrikaans names), otherwise ask in the Inbox |
| D2 | Default reminder for maintenance with no date ("wheel needs changing") | Next working day 07:00 local, configurable per workspace |
| D3 | Farm-level progress weighting | By `area_ha` when every child has it, otherwise by count |
| D4 | Desktop overlay under Smart App Control | Ship the HUD first as a web page / installed PWA; build the Tauri overlay once a code-signing certificate is in place (unsigned self-built `.exe` files are blocked on WABAKIPI, as llama.cpp was) |
| D5 | Claude key | Store in `E:\.claude\_vault\notecad.env`; until then the local Gemma router stays primary |

## 1. What was inspected (22 October 2026)

| Path | Finding |
|---|---|
| `CLAUDE.md` | Empty (0 bytes). No repo rules for agents yet |
| `NoteCad_Master_Blueprint.md` | v1.1 text; sections 1-9. Defines `node_layouts`, `routines`, `sensor_bindings`, hybrid logical clocks for field conflicts, PowerSync replica, React Flow + d3-force, Tiptap + Yjs |
| `packages/schema/actions.schema.json` | 9 action types: append_note, create_node, set_status, create_alert, create_task, update_attributes, link_nodes, upsert_profile_fact, ask_user. Node kinds: category, channel, asset, animal, group, field, place, person, project, topic. No range, progress or reminder actions |
| `packages/schema/golden_notes.json` | 20 notes / 21 events for the seeded farm. No identity or range notes |
| `supabase/migrations/0001_notecad_core.sql` | 17 tables, all text-typed, 31 RLS policies keyed on `members.user_id = auth.uid()::text`, Realtime publication for nodes/notes/tasks/alerts/inbox/captures. No sync tables, no tombstones |
| `services/brain/notecad_brain/db.py` | Same 17 tables for SQLite and Postgres; schema applied with `create table if not exists` (no migration versions). Missing from the blueprint: `node_layouts`, `routines`, `sensor_bindings` |
| `common.py` | `new_id()` = UUIDv4, `uuid7()` only for captures; `now_iso()` has one-second precision |
| `graph.py` | Materialised path tree, move with cycle check, roll-up of status/echo/counts, decay. `delete_subtree` hard-deletes |
| `apply.py` | One transaction per event, inverse per change, `action_log(seq, actor, action, inverse, provenance, undone_at)`. Undo hard-deletes created rows |
| `text.py` | Number words, event splitting, due words, problem words (EN/AF). No unit numbers ("#1", "nommer 1") and no ranges ("704 to 708") |
| `retrieve.py` | Fuzzy alias match (token coverage, compound words), EmbeddingGemma, channels, 1-hop, previous event |
| `routers.py` | Claude (forced tool), local Gemma (flat schema + guards), rules. `build_actions` emits one target per event |
| `validate.py` | JSON schema + known ids + no new top-level category + numeric caps + confidence 0.6 |
| `pipeline.py` | Capture state machine, Inbox resolve with alias learning, Undo, tasks, alerts, digest, onboarding |
| `api.py` | 27 routes incl. `captures/audio`, SSE `events`, `digest`. No CORS; bearer token required on SSE |
| `services/companion` | Chat, feedback, observe, card, keyterms, nudges, route-offline, digest link. Chat has no node context |
| `apps/` | Does not exist |

## 2. Current vs target gap analysis

| Area | Exists | Gap | Change |
|---|---|---|---|
| Identity of assets | Nodes with title + aliases | No make/model/unit number; "number 1" and "#1" not parsed; duplicates likely | `text.py`: `parse_identity()`; `retrieve.py`: identity match; node `attributes.identity`; schema `identity` on create_node |
| Category creation | Blocked at root, Inbox instead | Example A needs `Vehicles / Tractors` created when missing | New action `ensure_path`; taxonomy whitelist (D1) in `onboarding.py` / new `taxonomy.py` |
| Ranges | None | "south 704 to 708" must become 5 field nodes | `text.py`: `expand_ranges()`; new action `upsert_range`; `apply.py` expands deterministically |
| Progress | `attributes` free JSON, status `done` | No metric, no history, no roll-up | New table `progress_events`, node columns `progress_metric/progress_value/progress_target`; new action `record_progress`; `graph.rollup` aggregates |
| Reminders | `tasks.due_at` | No scheduler, no recurrence, status `routine_due` unused | New tables `reminders`, `routines`; worker job `fire_reminders`; new action `create_reminder` |
| Layout | None | Mind-map positions per lens | Table `node_layouts` (blueprint 4.2); `PUT /v1/nodes/{id}/layout` |
| Context capture | None | "Record here" from a node | `captures.anchor_node_id`; retriever boosts the anchor and its subtree |
| Provenance view | `action_log`, captures, audio files | No history endpoint, no audio playback | `GET /v1/nodes/{id}/history`, `GET /v1/captures/{id}/audio` |
| Sync readiness | Text UUIDs, workspace_id everywhere, action_log | UUIDv4 ids, 1 s timestamps, hard deletes, no device/HLC/cursor | Migration 0002 (section 4) |
| Schema versions | `create table if not exists` | Cannot alter tables safely | `schema_migrations` table + numbered SQL files shared by SQLite runner and Supabase |
| Browser access | Bearer header | No CORS; EventSource cannot send headers | CORS for `http://localhost:5173`, `tauri://localhost`; SSE token via short-lived `?t=` ticket |
| Frontend | None | Recorder HUD, mind map, node drawer | `apps/web`, `packages/core`, `packages/api`, `packages/ui`; later `apps/desktop` |
| Companion | Owner-level chat | Talk about one node | `chat` accepts `context_node_id`; brain `GET /v1/nodes/{id}` injected |
| Repo rules | Empty `CLAUDE.md` | Agents have no conventions | Fill `CLAUDE.md` (Phase 0) |

## 3. Graph and action schema extensions

### 3.1 Node taxonomy

Keep the existing kinds and use attributes for identity rather than inventing kinds per domain.

```
Root (workspace)
└── category        Vehicles · Fields · Livestock · Irrigation · Infrastructure · Staff · Admin
    └── group       Tractors · South Block · Sheep · Water
        ├── asset   John Deere 9550 #1        attributes.identity = {make, model, unit_no}
        ├── field   South 704 … South 708     attributes.identity = {block: "South", number: 704}, area_ha
        ├── animal / place / person / project
        └── channel Maintenance · Health Alerts   (problems; mirror status to parent)
             tasks, alerts, notes, reminders, progress hang off any node
```

New kind values: `job` (a piece of work that is itself a node, e.g. "Harvest 2026") and `block` (a named set of numbered fields or
units). Both are added to the enum in `actions.schema.json` and the Supabase check list.

### 3.2 Hierarchical assets: Example A

> "Wheel needs changing on tractor model John Deere 9550 - number 1"

| Step | Module | Result |
|---|---|---|
| Parse identity | `text.parse_identity` | `{class: "tractor", make: "John Deere", model: "9550", unit_no: 1}` from "number 1", "no. 1", "#1", "nommer 1", "nr 1", "tractor 1" |
| Find the asset | `retrieve.py` | exact identity match first (`attributes.identity` equal), then aliases, then embeddings. A different `unit_no` never matches ("#2" is not "#1") |
| Find the parent | `taxonomy.py` | class word → group: tractor → `Vehicles / Tractors`; trekker → same |
| Missing nodes | router emits `ensure_path` | creates `Vehicles` (whitelisted, D1) and `Tractors` if absent; creates `John Deere 9550 #1` asset with aliases `jd 9550 1`, `9550 #1`, `tractor 1` |
| Work | `create_task` + `create_reminder` + `set_status` | task "Change wheel" (priority normal), reminder due by D2, node status `routine_due` (amber) until the task is done |
| Undo | inverses | ensure_path records which nodes it created; Undo tombstones only those |

Display title rule: `"{make} {model} #{unit_no}"`; the owner can rename, the identity stays in attributes.

### 3.3 Ranges: Example B

> "Today I planted field south 704 to 708"

| Step | Module | Result |
|---|---|---|
| Expand | `text.expand_ranges` | `{prefix: "South", from: 704, to: 708}` from "704 to 708", "704-708", "704 tot 708", "704 through 708", "704, 705 and 706". Cap 200 items; above that the Inbox asks |
| Resolve | `retrieve.py` | looks for field nodes with `identity.block = "South"` and numbers in range; missing numbers listed |
| Route | router emits **one** `upsert_range` + **one** `record_progress` with `target: {range}` | the model never lists 5 ids; the brain expands deterministically |
| Apply | `apply.py` | creates missing `South 704..708` under `Fields / South Block` (group created by `ensure_path` if needed), then writes one `progress_events` row per field and sets `progress_value = 1` for metric `planted` |
| Roll up | `graph.rollup` | `South Block` planted 5/12 (or by area, D3), `Fields` and the farm root show the aggregate bar |
| Undo | inverses | one inverse per field; Undo removes all five progress events together |

### 3.4 Progress model

- Node columns: `progress_metric` (text, e.g. `planted`, `harvested`, `sprayed`, `serviced`), `progress_value` (0-1 or absolute),
  `progress_target` (number, default 1), `progress_unit`, `progress_updated_at`.
- `progress_events(id, workspace_id, node_id, metric, value, delta, unit, capture_id, op_id, recorded_at)` append-only history.
- Roll-up per metric over children: `sum(min(value/target,1) * weight) / sum(weight)`, weight = `area_ha` or 1 (D3). Stored on the
  parent as `rollup_progress` JSON `{planted: {done: 5, total: 12, pct: 0.42}}` so the UI reads it without recomputing.
- A metric reaching 100 % sets status `done` (existing 48 h decay back to ok); season reset is an explicit action later.

### 3.5 Reminders and routines

- `reminders(id, workspace_id, node_id, task_id, due_at, state[scheduled|fired|done|cancelled], fired_at, channel, op_id, hlc, deleted_at)`.
- `routines(id, workspace_id, node_id, title, rrule, window_days, next_due, approved)` from blueprint 4.2; the nightly job proposes
  routines from repeated notes, the owner approves them in the Inbox.
- Worker job `fire_reminders` every minute: due reminders become notifications, the node turns `routine_due` within the window and
  `warning` when overdue; completing the task closes the reminder.

### 3.6 `actions.schema.json` v2

`schema_version: 2` at the top level; v1 payloads stay valid. New action types (all carry `confidence` and `evidence`):

| Action | Fields | Rules |
|---|---|---|
| `ensure_path` | `path: [{title, kind, identity?, aliases?}]`, `temp_id` for the last element | Each element is matched before it is created; top-level creation only for whitelisted taxonomy (D1) |
| `upsert_range` | `parent_ref`, `prefix`, `from`, `to`, `kind`, `step?`, `temp_id` (names the set) | `to - from` ≤ 200; brain expands, never the model |
| `record_progress` | `target: {node_id} | {range_ref}`, `metric`, `value`, `unit?`, `mode: set|increment` | Numbers only from the transcript (router rule 6); caps from `progress_target` |
| `create_reminder` | `node_id`, `task_ref?`, `due_at?`, `rrule?` | `due_at` only from words or D2 default |
| `complete_task` | `task_id` or `match: {node_id, title_like}` | "Changed the wheel on number 1" closes the open task |
| `resolve_alert` | `alert_id` or `match` | "Pump is fixed" resolves the open leak alert |

`create_node` gains `identity` (object) and the kind enum gains `job`, `block`. Golden notes grow by at least 12 (identity, range,
progress, completion, Afrikaans variants), each with expected nodes, metric and values.

### 3.7 Database changes (migration 0002)

| Table | Change |
|---|---|
| all synced tables | `hlc text`, `origin_device text`, `deleted_at text` (tombstone); ids UUIDv7 going forward |
| `nodes` | `identity_key text` (normalised `john-deere/9550/1`, unique per workspace when not null), progress columns, `rollup_progress text` |
| new | `progress_events`, `reminders`, `routines`, `node_layouts`, `schema_migrations`, `devices`, `sync_state` |
| `captures` | `anchor_node_id text` |
| `action_log` | sync columns (section 4) |

## 4. Sync-ready local-first data layer

Goal: one person works offline on WABAKIPI or a phone today; later a second worker joins the same farm and both replicas converge
through Supabase with RLS, without rewriting the data model. No sharing UI now.

### 4.1 Identity

| Item | Today | Change now |
|---|---|---|
| Workspace | `workspaces.id` | unchanged; becomes the RLS and sync partition |
| Person | `members` row, `user_id` null locally | `local_identity` row (uuid generated at install) used as `user_id`; bound to `auth.uid()` on first sign-in by one mapping update |
| Device | none | `devices(id uuid7, workspace_id, label, created_at)`; every write carries `origin_device` |
| Row ids | uuid4 text | uuid7 text for every new row (time-ordered, globally unique, safe to create offline) |

### 4.2 Clock and ordering

- Hybrid logical clock string per write: `{physical_ms:013d}-{counter:04d}-{device8}`; comparable as text in SQLite and Postgres.
- Timestamps move to millisecond ISO-8601 UTC. Existing rows keep their values.

### 4.3 `action_log` becomes the replication log

| Column | Meaning |
|---|---|
| `op_id` | uuid7, globally unique, idempotency key for push and replay |
| `workspace_id`, `capture_id`, `event_idx`, `seq` | as today |
| `origin_device`, `actor_user` | who and where |
| `hlc` | causal order across devices |
| `lsn` | local monotonic integer (push order) |
| `server_seq` | assigned by Postgres on ingest; null until synced |
| `action` | **materialised** action: every generated id, timestamp, resolved node id and expanded range is stored, so replay never re-runs a model or a fuzzy match |
| `inverse`, `provenance`, `undone_at` | as today; Undo is itself a new op (`type: undo`, `undoes: op_id`) instead of mutating history |

Rules that keep it replayable: apply is a pure function of (current state, materialised op); deletes are tombstones; Undo writes
tombstones and status reversals as new ops; derived fields (roll-up, counts, display status) are never synced, always recomputed.

### 4.4 Push / pull (built in Phase 9, designed now)

```
local SQLite                              Supabase Postgres (RLS)
action_log where server_seq is null  ──►  rpc ingest_ops(ops jsonb)     security definer, checks membership
   ordered by lsn, batches of 200          ├─ skip if op_id exists (idempotent)
                                           ├─ validate + apply with the same rules (SQL or edge function)
                                           └─ assign server_seq, return [(op_id, server_seq)]
sync_state.last_pulled_seq           ◄──  select ops where workspace_id = ? and server_seq > cursor
apply remote ops locally (skip own op_ids), recompute roll-ups for touched nodes
Realtime broadcast "ops:{workspace}" only nudges a pull; it never carries data
```

### 4.5 Conflict rules

| Data | Rule |
|---|---|
| Creates (nodes, notes, tasks, alerts, progress events, reminders) | Never conflict: uuid7 ids, append-only |
| Node fields (title, status, attributes, progress_value) | Per-field last-writer-wins by HLC; a user edit beats an AI edit with an earlier HLC (blueprint 2.2) |
| Moves | Later HLC wins; server rejects a move that creates a cycle and the losing device gets an Inbox item |
| Deletes | Tombstone wins over edits with an earlier HLC; edits after a tombstone go to the Inbox |
| Identity duplicates (two devices create "JD 9550 #1") | `identity_key` unique: the later create becomes a merge op (aliases + children moved) |
| Rich text notes | Stay append-only log lines now; Yjs only when co-editing arrives (ADR 0006) |

### 4.6 What is deliberately not built now

Invites, roles UI, presence, per-member views, Supabase auth screens. The `members` table, RLS and notifications already carry
assignment, so one worker's tasks will appear on another's device as soon as sync exists.

## 5. Frontend architecture

### 5.1 Layout and stack

```
apps/
  web/                 Vite + React 19 + TypeScript; PWA; both modes; also the Tauri webview content
  desktop/             Tauri 2 shell (Phase 8): transparent always-on-top HUD window + main window, global hotkey, tray
packages/
  core/                types generated from actions.schema.json and the brain's OpenAPI; graph store; status → visual map
  api/                 typed client for brain :8788 and companion :8787; SSE client with reconnect and resume
  ui/                  Ionity design tokens (--ionity-*, --nc-*), buttons, chips, toast, sheet, progress ring
  mindmap/             React Flow nodes, layout worker, level-of-detail rules
  recorder/            audio capture, waveform, push-to-talk, upload, state machine
```

Libraries: `@xyflow/react`, `d3-hierarchy` + `d3-force` (layout worker), `zustand`, `@tanstack/react-query`, `framer-motion`
(shared-element morphs, reduced-motion aware), `idb-keyval` (offline outbox in the browser), Vitest, Playwright. pnpm workspaces,
Node 24.

### 5.2 State

| Store | Holds | Fed by |
|---|---|---|
| `graphStore` (Zustand) | normalised `nodes`, `edges`, `tasks`, `alerts`, `reminders`, `progress` by id; `childrenOf`; `selectedId`; `lens` | `GET /v1/workspaces/{ws}/graph` snapshot, then SSE deltas (`node`, `task`, `alert`, `progress`, `capture`, `inbox`) |
| `captureStore` | one entry per capture: state, transcript, events, applied node ids, undo availability | recorder + SSE `capture` events |
| `uiStore` | HUD open/collapsed, hotkey, theme, density, reduced motion | local |
| TanStack Query | request/response reads: node history, inbox list, companion chat | REST |

SSE delivery: brain emits a monotonically increasing `event_id`; the client reconnects with `Last-Event-ID` and receives missed
events from the broker ring buffer (exists, 200 deep; raise to 1,000 and key by workspace).

### 5.3 Mode 1: transparent recorder HUD

```
HudRoot (fixed, bottom-centre pill; glass: backdrop-filter blur 18px, rgba surface 0.55, 1px border, brand gradient ring)
├── RecordButton        hold Space / hold the pill / Ctrl+Shift+Space (desktop); tap-to-toggle on touch
├── Waveform            canvas, AnalyserNode RMS bars at 30 fps; idle = flat line; reduced-motion = level meter
├── StatusLine          queued → transcribing → routing → applied | needs review | failed  (from SSE `capture`)
├── ResultToast         "Filed 2: Tractors › John Deere 9550 #1 — task + reminder · South 704–708 planted" + Undo (6 s) + Open
├── InboxChip           count of open questions; opens QuickPick with the 2-3 suggested branches, one tap resolves
└── AnchorBadge         shows the node the next note is anchored to (when recording from the mind map)
```

Capture path: `MediaRecorder` (audio/webm;codecs=opus, mono) → chunk to IndexedDB outbox with a client uuid7 `capture_id` →
`POST /captures/audio?capture_id=` (retry with back-off; same id is idempotent) → SSE drives the status line. Typed notes use the same
pill (press `/`). Glass colours come from tokens with an opaque fallback when `backdrop-filter` is unsupported; contrast ≥ 4.5:1 on text.

### 5.4 Mode 2: interactive mind map

| Concern | Design |
|---|---|
| Layout | Radial tree from `d3-hierarchy` for parent edges (stable, deterministic); `d3-force` relaxes only cross-links and collisions in a Web Worker; pinned positions saved to `node_layouts` per lens |
| Level of detail | zoom < 0.6: categories with roll-up bars; 0.6–1.2: groups and assets; > 1.2: task chips, reminders, last note line |
| Node renderers | `CategoryNode` (progress ring per metric), `AssetNode` (status fill, badge = open tasks + alerts, reminder clock), `FieldNode` (progress fill, area label), `BlockNode` (grid of its numbered children as mini-cells, 704–708 lit), `PersonNode` (open tasks assigned), `ChannelNode` (small, hidden at low zoom) |
| Status | colour from `display_status`, echo dot from `child_worst`, info ring and done check fade with server `status_since` decay, pulse only for critical and never under reduced motion |
| Edges | parent edges solid, `located_at` dotted, `affects` dashed, `assigned_to` purple; edge labels on hover |
| Live updates | SSE delta → store → only changed React Flow nodes re-render (`nodeTypes` memoised, selectors per id); new nodes animate in from their parent |
| Lenses | Mind map ⇄ folder tree share `selectedId`; framer-motion `layoutId` morphs the selected node between lenses |

Node drawer (opens on click, right sheet on desktop, bottom sheet on phone):

```
NodeDrawer
├── Header        title, path, status pill, progress bars, identity (make / model / unit)
├── Actions       Record here (anchored capture) · Ask the companion · Add task · Rename / move
├── OpenWork      tasks (assignee, due, done checkbox → complete_task), reminders, alerts (resolve)
├── History       timeline from GET /nodes/{id}/history: note text, capture time, router, audio ▶ (provenance)
└── Companion     chat scoped with context_node_id; answers cite the notes it used
```

### 5.5 Backend additions the frontend needs

| Endpoint / change | Service |
|---|---|
| CORS for `http://localhost:5173`, `http://127.0.0.1:5173`, `tauri://localhost` | brain, companion |
| `POST /v1/auth/sse-ticket` → 60 s ticket; `GET …/events?t=` | brain |
| `GET /v1/workspaces/{ws}/graph?since=` (snapshot or delta, includes progress + reminders) | brain |
| `GET /v1/nodes/{id}/history`, `GET /v1/captures/{id}/audio` | brain |
| `PUT /v1/nodes/{id}/layout` | brain |
| `captures` accepts `anchor_node_id` | brain |
| `GET/POST/PATCH reminders`, `GET progress` | brain |
| `POST /v1/{owner}/chat` accepts `context_node_id` | companion |
| SSE `id:` field + `Last-Event-ID` resume | brain |

### 5.6 Desktop shell (Phase 8)

Tauri 2 with two windows: `hud` (transparent, decorations off, always on top, skip taskbar, click-through outside the pill) and
`main` (mind map). Global shortcut `Ctrl+Shift+Space` (blueprint 2.1), tray menu (open map, pause listening, quit). The brain and
companion stay separate Python services started by `start_notecad.ps1`; the shell only talks HTTP. Signing is required under Smart
App Control (D4); until then the HUD runs as an installed PWA window.

## 6. Execution phases

Each phase ends with its tests green on WABAKIPI (SQLite) and in CI (Postgres 16), and an entry in the build status doc.

1. **Phase 0 · House rules.** Fill `CLAUDE.md` (paths, start/stop, test commands, never-commit list, licence header, Smart App
   Control note). Add `schema_migrations` runner to `db.py` and move today's schema to `migrations/0001`. *Exit:* 50 + 41 tests green, migrations apply to an existing `brain.db` without loss.
2. **Phase 1 · Sync-ready data layer (no sync yet).** uuid7 everywhere, ms timestamps, HLC, `devices`, `local_identity`,
   tombstones instead of deletes (graph delete, Undo), `action_log` sync columns, materialised ops, Undo as an op. Supabase `0002`.
   *Exit:* replay test: rebuild a fresh database from `action_log` alone and get an identical graph; Postgres migration applies.
3. **Phase 2 · Identities and taxonomy.** `parse_identity`, `taxonomy.py`, `identity_key`, `ensure_path`, kinds `job` / `block`,
   retrieval by identity, D1 policy. *Exit:* Example A golden notes (EN + AF, #1 vs #2, missing Vehicles) 100 % with rules and ≥ 90 % with Gemma.
4. **Phase 3 · Ranges and progress.** `expand_ranges`, `upsert_range`, `record_progress`, `progress_events`, roll-up per metric,
   `complete_task`, `resolve_alert`. *Exit:* Example B golden notes; farm-level progress matches a hand calculation; Undo removes a whole range.
5. **Phase 4 · Reminders and routines.** Tables, `create_reminder`, worker `fire_reminders`, `routine_due` window, routine proposals
   in the Inbox. *Exit:* time-travel tests (frozen clock) for due, overdue, done; notification rows created once.
6. **Phase 5 · API for the frontend.** CORS, SSE ticket + resume, `graph` snapshot/delta, history, audio, layout, anchored capture,
   companion `context_node_id`; OpenAPI exported to `packages/core`. *Exit:* contract tests generated from OpenAPI.
7. **Phase 6 · Recorder HUD (web).** `apps/web` scaffold, design tokens, recorder state machine, waveform, IndexedDB outbox, SSE
   status, result toast with Undo, Inbox quick pick. *Exit:* Playwright: record (fake audio) → applied toast in < 6 s on WABAKIPI; offline capture uploads after reconnect; Undo restores.
8. **Phase 7 · Mind map.** Graph store, radial layout worker, LOD, node renderers, progress rings, echo dots, decay, drawer with
   history and audio, anchored recording, companion chat. *Exit:* 2,000-node synthetic farm pans at 60 fps; a capture's change appears on the map < 1 s after `applied`.
9. **Phase 8 · Desktop overlay.** Tauri 2 HUD + main window, hotkey, tray, code signing (D4). *Exit:* signed build runs under Smart App Control; hotkey capture works with the main window closed.
10. **Phase 9 · Multi-worker sync.** `ingest_ops` RPC, push/pull loop, conflict rules, identity merge, Realtime nudge, second-device
    test. *Exit:* two SQLite replicas + Supabase converge after 500 random offline ops each (property test); RLS denies a non-member.

Field gate across phases 2-4: record 20 real notes on the farm (blueprint Phase 1 exit) and keep ≥ 85 % right first time.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Small model invents identities or ranges | Model only emits `{prefix, from, to}` and identity fields; brain expands and matches; validator caps ranges |
| Auto-created categories clutter the map | Whitelist (D1); everything else to the Inbox; Undo removes created nodes |
| Unsigned desktop builds blocked | PWA first, sign before shipping the overlay (D4) |
| Sync retrofit later breaks data | Phase 1 makes ops replayable now and proves it with a rebuild test |
| Mind map slow on large farms | LOD, worker layout, memoised node types, virtualised drawer lists |
| Glass HUD unreadable on bright desktops | token-based tint + opaque fallback; contrast tests in Playwright |

## 8. Test strategy

- **Brain:** existing 50 tests stay; add golden notes for identities, ranges, progress, completion (EN/AF); replay-equivalence test;
  frozen-clock reminder tests; Postgres parity via `NC_BRAIN_TEST_PG_URL`.
- **Sync:** property test with random op interleavings across two replicas; RLS tests on Supabase.
- **Frontend:** Vitest for stores and layout; Playwright for recorder and map flows, light/dark, reduced motion, phone width.
- **Field:** `tools/field_test.py` extended with the new golden set; real-note run before each phase sign-off.
