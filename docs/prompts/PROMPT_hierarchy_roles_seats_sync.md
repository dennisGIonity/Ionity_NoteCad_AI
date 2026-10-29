<!--
Ionity Global (Pty) Ltd | AEDI | Author: Dennis Grobler (Wabakipi)
Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-->

# Build prompt: NoteCad hierarchy, roles, seats and permission-aware sync

Paste everything below the line into a Claude Code session opened at `E:\.claude\Ionity\.NoteCad`.

---

You are working in the NoteCad repo (read `CLAUDE.md` first, then `docs/adr/0007`-`0013`, `docs/plans/PHASE6.md`,
`supabase/migrations/0001_notecad_core.sql`, `services/brain/notecad_brain/{db,sync,api,apply,delegate,pipeline}.py`).
Follow every rule in `CLAUDE.md` (licence headers, vault-only secrets, nothing on C:, forward-only numbered
migrations kept in step with Supabase, backup `data\` before touching a database, guard + regression test).

## Goal

Turn NoteCad from a one-owner workspace into a **business hierarchy that many devices share**. One business
(e.g. the farm) has one mapped mind map. People join it by being given a **seat**; their app then syncs to the
already-mapped business and they work on it according to their **role level**. Everyone uses the same app and the
same voice-capture flow; the role decides what they may see and change.

## Roles (levels)

| Level | Role | Can |
|---|---|---|
| 0 | `system` | Ionity service role / brain worker. Schema, migrations, sync plumbing, seat ledger. Not a person. |
| 1 | `owner` | Everything in the business: structure the map (create, rename, move, merge, delete nodes), edit and delete any data, buy/assign/revoke seats, set roles, set visibility on any branch, see all audit logs, export, delete the workspace. At least one owner always exists; the last owner cannot be removed or demoted. |
| 2 | `manager` | Everything an employee can, plus: edit existing notes/tasks/alerts, approve or reject employee proposals, assign tasks, create nodes inside the branches they manage, mark branches restricted (only up to their own level), invite employees into seats the owner has already bought. Cannot change owners, cannot buy seats, cannot see branches restricted to `owner`. |
| 3 | `employee` | **Add and feed data only**: voice/text captures, new notes, new tasks, progress updates and completing tasks assigned to them, attach photos/audio. Cannot rename, move, merge, delete or edit existing nodes or other people's entries. Never receives restricted data. |

Design rules:

- Keep the existing `members.role` column (today `owner|editor|viewer`); migrate `editor` → `manager`,
  `viewer` → `employee` with a read-only flag, and add a numeric `level` so checks are `actor.level <= required`.
  Put the permission matrix in one place (`notecad_brain/permissions.py`) and generate the Supabase RLS from it
  the way `tools/gen_sync_migration.py` derives 0005, with a `--check` that CI runs.
- Optional scoping: a manager can be bound to one or more subtree roots (e.g. "North section", "Workshop");
  their manager rights apply only below those nodes. Employees can be scoped the same way for what they see.

## Employee captures do not change the map

When an employee's capture would **modify** existing data (rename, move, merge, edit a note they didn't write,
change a task they aren't assigned), the brain must not apply it. It becomes a **proposal** in the Inbox (reuse
`POST /v1/inbox/{id}/resolve`), routed to the employee's manager, or the owner if none. Pure additions (new note on
an existing node, new task, progress on their own task) apply directly. Enforce this in `apply.py` after validation,
not only in the router, so no model mistake can bypass it. Regression tests: employee rename → proposal; employee
delete → refused; employee new note → applied; manager approves → applied with the employee as author and the
manager as approver in `action_log`.

## Restricted branches (e.g. financials)

- Add `visibility` per node: `all` (default), `manager` (owners + managers), `owner` (owners only). Visibility
  **inherits down the tree**: a child is at least as restricted as its most restricted ancestor. Store the effective
  level so queries stay cheap at 2,000+ nodes (check with `seed_synthetic_farm.py` and `perf_probe.py`, record in
  `docs/perf/`).
- Notes, tasks, alerts, captures, audio, embeddings, aliases and edges inherit their node's restriction. An edge is
  hidden from anyone who can't see both ends.
- Owners and managers set visibility by voice ("make Financials owner only") or in the node drawer. A manager can
  never set a level above their own, nor un-restrict something an owner restricted.
- **Restricted data must never reach a device that isn't allowed to see it.** Hiding it in the UI is not enough.
  The brain, the companion (digest, map lines, "this one" context), retrieval (`retrieve.py`), export, SSE events
  and **sync pull** all filter by the caller's effective level. Gemma/Claude prompts built for an employee contain
  only data that employee may see. Tests must prove an employee's pull, digest, mindmap, search, export and SSE
  stream contain zero restricted rows.
- If a branch becomes restricted after an employee already synced it, the next pull sends tombstones so the device
  removes those rows (and their audio files).

## Seats and joining

- New tables (SQLite migration N and the Supabase file with the same number): `seats` (id, workspace_id,
  role_level, status `available|assigned|revoked|expired`, assigned_member_id, purchased_at, expires_at,
  external_ref for a future billing provider) and `invites` (one-time code, seat_id, expires_at, used_at).
  Billing itself is out of scope: a `SeatLedger` interface with a manual/local implementation now, so a payment
  provider can be plugged in later.
- Flow: owner adds a seat (manager or employee) → owner or manager creates an invite with the person's profile
  (name, contact, optional person node to link, optional subtree scope) → the person scans a QR / opens a
  `notecad://join?...` link (extend the existing phone pairing and `GET /v1/pairing`) → the device gets a
  **per-member device token** (not the shared `NC_BRAIN_API_TOKEN`) → first sync pulls exactly what their level and
  scope allow. Revoking a seat invalidates its tokens immediately and the next contact wipes the device's local copy.
- The member row links to their person node, so delegation ("Ask Sipho to …", `delegate.py`) notifies the right
  device.

## Sync changes (extend ADR 0012, don't replace it)

- Every `sync_changes` row carries `author_member_id`, `author_level` and the node's effective visibility.
- On **push**, the receiving node (edge hub or Supabase) re-checks every change against the author's *current*
  role and rejects it, or turns it into a proposal, if not allowed. A device can be tampered with; the hub is the
  authority. Rejections go back to the device and show as a toast.
- On **pull**, the hub filters by the requesting member's level and scope.
- Last-writer-wins stays for rows the writer may write; if an employee edit and a manager edit conflict, the higher
  level wins regardless of time and the other is kept in history.
- Role and scope changes sync like any other change; the device re-filters on receipt.
- Offline phones keep their outbox and replay on reconnect; anything no longer allowed becomes a proposal, never
  silently dropped.

## Surfaces

- Desktop and phone: a **People & seats** panel (owner: add seat, invite, change role/scope, revoke; manager: invite
  into available seats, see their team); lock badge and level on restricted nodes; edit/rename/delete controls hidden
  for employees; Inbox shows proposals with Approve/Reject for managers and owners.
- Voice: "Make Johan a manager", "Who can see Financials?", "Restrict Financials to owner only" are owner/manager
  commands; an employee saying them gets a polite refusal, logged.
- Audit: every permission-relevant action in `action_log` (who, level, what, approved by). Owners see all, managers
  their scope, employees their own.

## Deliverables, in this order

1. `docs/adr/0014-roles-seats-permission-aware-sync.md` with these decisions plus a threat model (stolen phone,
   tampered device, revoked employee offline, model mis-routing). **Show it to me before writing code.**
2. Back up `data\` to `data\archive\roles-<time>\`, then the migrations (SQLite + Supabase, same number, RLS
   generated from `permissions.py`, `--check` in CI).
3. `permissions.py` and enforcement in api, apply, retrieve, companion context, export, SSE, sync push/pull.
4. Seats, invites, device tokens and the join flow (desktop + phone).
5. UI: People & seats, lock badges, proposals, role-aware controls.
6. Tests: brain + companion pytest (SQLite and Postgres in CI), Vitest for UI role gating, a Playwright e2e that
   joins an employee seat in a second browser context and proves Financials never appears, an Android unit test for
   the tombstone wipe. Extend the showcase seed: one owner, a manager scoped to North section, two employees (Sipho,
   Thandi) and a Financials branch restricted to owner.
7. Update `CLAUDE.md`, `docs/BUILD_STATUS.md` and the data-flow diagram.

Ask me before: choosing a billing provider, changing whether employees may create new child nodes (default: no),
or anything that deletes existing workspace data.
