<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# ADR 0014: Roles, seats and permission-aware sync

Status: accepted, 2026-10-29, with the recommended answer to all three questions (end of this record). Author: Dennis Grobler.
Builds on ADR 0012 (sync, phones) and ADR 0013 (hardening). Brief: `docs\prompts\PROMPT_hierarchy_roles_seats_sync.md`.

## Context

NoteCad is a one-owner workspace today:

- `members.role` (`owner|editor|viewer`) is only used for delegation and for who hears a critical alert
  (`delegate.alert_audience`). Nobody signs in as a member.
- The desktop on loopback is trusted. Phones and other workers share one token (`NC_BRAIN_API_TOKEN`), which can
  read and change everything (`api.check_auth`).
- Workers (desktop, Edge AI Node, Supabase) hold full copies and sync every row through `sync_changes`
  (`sync.TABLES`). Phones hold no copy: they fetch the mind map and keep an outbox of recordings.
- Every read (mind map, digest, retrieval, export, events, history, audio) returns the whole workspace. Roll-ups
  on a node count every descendant. A node's history shows the full capture transcript and its audio.
- Supabase RLS (0001) allows any member to read everything; `owner` and `editor` may write.

The brief turns this into one business map shared by many people, each limited by a role level. What they may not
see must never reach their device.

## Decisions

### A. Roles and one permission matrix

1. **Four levels, checked as `actor.level <= required`.** `system` 0 (brain workers, migrations, the seat ledger;
   never a person or a device), `owner` 1, `manager` 2, `employee` 3. `members.role` stays. Migration 0007 adds
   `level`, `read_only`, `status` (`active|revoked`) and `seat_id`, and maps `owner` to 1, `editor` with a login
   (`user_id`) to `manager` 2, `editor` without one (the people added for delegation) to `employee` 3, and `viewer` to
   `employee` 3 with `read_only = 1` (a read-only employee cannot capture). The last active owner cannot be
   removed, demoted or revoked: the API refuses it and a database trigger backs that up.
2. **The matrix lives in one place: `notecad_brain/permissions.py`.** It holds the table below as data plus the
   read rules. Everything asks it: the API dependencies, `Applier.apply`, sync receive, every read filter, the
   apps (`GET /v1/me` returns the caller's capabilities computed from it; the apps carry no copy of their own), and
   the Supabase RLS, which is generated from it (decision 30).

   | Action | Owner | Manager | Employee |
   |---|---|---|---|
   | See a node and what hangs off it | everything | not `owner`-restricted | `all` only, inside their scope |
   | New note, new alert (status may only go up) | yes | yes | yes, on nodes they see |
   | New task, unassigned or for themselves | yes | yes | yes |
   | Assign or reassign a task, change its due date | yes | in scope | proposal |
   | Complete a task | any | in scope | their own; others' are a proposal |
   | Progress figures (`planted_ha`, `harvested_ha`, `progress_pct`, `phase`) | yes | yes | yes, on nodes they see |
   | Other node attributes (area, model, ...) | yes | in scope | proposal |
   | Edit a note, task or alert | any | in scope | their own entries; others' are a proposal |
   | Delete a note, task or alert | any | in scope | only by Undo of their own capture; else refused |
   | Resolve an alert, lower a status | yes | in scope | proposal |
   | Create a node | yes | inside the branches they manage | proposal (brief's default; ask before changing) |
   | Rename, move, merge a node | yes | proposal to an owner | proposal |
   | Delete a node | yes, after a one-tap confirm | proposal to an owner | **refused** |
   | Link two nodes (`related_to`) | yes | in scope | proposal |
   | Set visibility | any level | up to `manager`, in scope, never loosening an owner's | refused |
   | Approve or reject a proposal | yes | in scope | no |
   | Undo a capture | any | their own, and others' in scope | their own |
   | Place a held note ("where should this go?") | yes, and the brain learns the words | in scope, learns | their own notes, no learning |
   | Workspace profile facts | yes | proposal | proposal |
   | Add or revoke seats, set roles and scopes | yes | no | no |
   | Invite someone | into any seat | into employee seats already bought, scope within their own | no |
   | Read the audit log | all | their scope and their team | their own |
   | Export | everything | their view | their view |
   | Delete the workspace | yes | no | no |

   "Refused" means nothing changes, the person gets a polite answer, and `action_log` records the attempt.
3. **Scope.** `member_scopes(member_id, node_id)` binds a member to subtree roots. A scoped manager has manager
   rights below those roots and employee rights elsewhere, and still sees the whole map within visibility. A
   scoped employee sees only those subtrees, plus the chain of ancestors as **path stubs** (title and kind only,
   no notes, no roll-ups) so the tree stays connected. Owners are never scoped. No scope means the whole map.
4. **Every request has a principal, taken from its credential and nothing else.** A device token gives
   (member, level, scopes, device); member ids or levels sent by a client are ignored. Loopback without a token
   is this PC's local member: `NC_BRAIN_LOCAL_MEMBER`, default the workspace's first owner, so the desktop works as
   it does now. A PC other people use (the farm-office Edge AI Node) runs with `NC_BRAIN_TRUST_LOOPBACK=0` and its app
   is joined like a phone. `NC_BRAIN_API_TOKEN` becomes the **worker credential** (system level, `/v1/sync/*`).
   A node, capture or task the caller may not see answers **404**, the same as one that does not exist.

### B. Employee captures add; everything else is a proposal

5. **Enforced in `Applier.apply`, after validation.** `apply` takes the principal. `permissions.decide` sorts each
   validated action into allow, propose or refuse. Allowed actions are applied in the event's transaction as
   today. Proposed actions become one Inbox item per event (`kind = 'approval'`, the held actions, the author)
   routed to the managers whose scope covers the node, or the owners if there are none. Refused actions change
   nothing and leave a `refused` row in `action_log`. Every write path goes through `apply`: the pipeline, Inbox
   placement, the REST edits (`PATCH /v1/nodes`, `PATCH /v1/tasks` ...) and sync receive. A router or model
   mistake therefore cannot get past it. One event can be split: "the pump is fixed" from an employee appends the
   note at once and holds "resolve the alert" for approval.
6. **Approving reuses `POST /v1/inbox/{id}/resolve`** (`{"decision": "approve"}`; a `node_id` still places a held
   note as today); rejecting uses `/dismiss` with a reason, which the author sees. The approved half is applied
   under its own key (the Inbox item), so it never collides with the half that was applied directly.
   `action_log` gets `member_id` (the author, the employee), `member_level`, `approved_by` (the manager) and `node_id`.
7. **New action types for structure and administration**: `rename_node`, `move_node`, `merge_nodes`,
   `delete_node`, `edit_note`, `update_task`, `resolve_alert`, `set_visibility`, `set_role`. Only the rules router
   produces structural and admin actions, from an explicit command grammar in English and Afrikaans ("rename",
   "move", "delete", "make ... a manager", "restrict ... to owner only", "hernoem", "skuif", "verwyder" ...). The
   action schema given to Gemma and Claude does not contain `set_role`, `set_visibility` or `delete_node` at all, and
   validation drops a structural action from a model unless the event has an explicit command verb (a guard with a
   regression test, as for every field mistake). **Tighten at once, loosen with a confirm**: restricting a branch
   applies at once with Undo; making something more visible, changing a role and deleting by voice come back as a
   one-tap confirm, because Whisper can mishear a name.
8. **Delegation knows who can see what.** A member links to their person node (`members.person_node_id`, as now), so
   "Ask Sipho to ..." notifies Sipho's devices. A task on a node the assignee cannot see is not assigned; the
   person who said it is told why. An employee's "Ask Thandi to ..." creates the task with the name as a hint and
   proposes the assignment to the manager. Critical alerts notify the owners and managers who can see the node.

### C. Restricted branches

9. **Visibility is stored, and stored as its effect.** `nodes.visibility` (`all` default, `manager`, `owner`),
   `nodes.vis_set_by` (the level that set it) and `nodes.eff_level` (3, 2 or 1: the lowest of the node's own and
   every ancestor's). It is recomputed for the subtree, in depth order and one transaction, when a visibility is set
   or a node moves. Reads compare one integer, with an index on `(workspace_id, eff_level)`. `eff_level` is derived:
   like today's roll-up columns it travels with the row, and each worker recomputes it after applying a change.
10. **Everything inherits from its node.** Notes, tasks, alerts, aliases, route corrections and embeddings use their
    node's level. An edge uses the stricter of its two ends. A capture, its events and its audio get
    `captures.eff_level`: the strictest node any of its events touched (a held capture: its author and approvers).
    Someone who may see a note but not its whole capture sees that event's sentence only, with no full transcript and
    no audio. Profile facts get a visibility too (default `all`; a fact learned on a restricted node takes its level).
11. **Roll-ups per tier.** Today's roll-up columns stay the owner's full view. The same roll-up pass also writes
    `rollup_tiers` (JSON) for levels 2 and 3, leaving out descendants restricted above that level. Everyone below
    owner gets their tier's numbers everywhere (API, digest, device pull), so "Admin: 1 critical" never hints at
    Financials. Path stubs carry no roll-up.
12. **One read filter, used by everything that reads.** `permissions.view(principal)` gives the SQL predicates (level,
    scope by `path` prefix, edges by both ends). It is used by the mind map, node detail and history, tasks,
    alerts, Inbox, notifications, digest (map lines and the "this one" focus), retrieval (candidates are masked
    before scoring; the spine, the people list, the numbers used to expand "704 to 708" and the speech-to-text
    keyterms are filtered too), export, the event stream, device pull and audio. The prompts built for Gemma or
    Claude come only from that filtered view.
13. **The companion remembers the person; the brain knows the business.** The companion stays on loopback. A member on
    another device asks through the brain (`POST /v1/workspaces/{ws}/ask`), which checks the device and that
    `context_node_id` is visible, then calls the companion with the member id and the companion's own token. The
    companion fetches the digest as that member (`as_member`, honoured only with the companion's token). Memory and
    style are kept per `<workspace>:<member>` (ADR 0007: owners never share a store), and `observe` goes to the
    author's memory.
14. **Events are filtered per subscriber.** Each published event carries an envelope (level, node ids, author). A
    stream drops what its member may not see. Capture progress (queued, transcribing, transcript) goes to the author
    and the owners; results go to whoever can see the node. A role or scope change closes that member's streams so
    they reconnect with the new view.
15. **Who may restrict.** Owners set any level. A manager sets up to `manager`, only inside their scope, and never
    loosens a node whose `vis_set_by` is an owner; an owner-restricted ancestor still wins through `eff_level`.

### D. Seats, invites, devices and joining

16. **New tables** (SQLite migration 7 and Supabase 0007): `seats` (id, workspace_id, role_level, status
    `available|assigned|revoked|expired`, assigned_member_id, purchased_at, expires_at, external_ref), `invites`
    (id, workspace_id, seat_id, code_hash, created_by, profile JSON with name, contact, person node, scope and role,
    expires_at, used_at, used_by_device), `devices` (id, workspace_id, member_id, name, platform, token_hash,
    created_at, last_seen_at, revoked_at, wipe_acked_at) and `member_scopes`. A seat's `role_level` is the highest role
    it may hold, so a manager seat can hold an employee but not the reverse. Owners need no seat.
17. **`SeatLedger` interface** (add, assign, release, expire, available, apply an external event) with a
    `LocalLedger` now: the owner adds seats by hand and no money moves. No billing provider is chosen; that is the
    owner's call.
18. **Joining.** The owner adds a seat. The owner (or a manager, for an employee seat) creates an invite with the
    person's profile. The desktop shows a QR of `notecad://join?u=<brain>&c=<one-time code>&w=<workspace>`
    (`GET /v1/pairing?invite=<id>`, this PC only, as today); a manager's phone shows the same link in its People panel.
    The QR carries a code, never a token. The phone shows "Join Highveld Farm as an employee, North section?" (a link
    is an offer, ADR 0013) and calls `POST /v1/join` with the code and a device name. This is the only route without
    a token; it is rate limited and compares in constant time. In one transaction the brain creates or links the
    member and their person node, assigns the seat, marks the invite used and creates the device. It returns a
    256-bit token (`nct_...`) once and keeps only its SHA-256. The phone then loads its snapshot (decision 21).
    Invites last 72 hours by default and 7 days at most.
19. **Tokens on the device.** Android: encrypted with an AES-GCM key from the Android Keystore, stored in app prefs
    (backup is off). Web and PWA: IndexedDB. Each device has its own token; the owner sees every device per member
    and can revoke one without the others.
20. **Revoking.** Revoking a seat revokes the member and all their device tokens in one transaction. Device rows sync
    to the other workers as hashes, so the Edge AI Node refuses them too after its next sync. A revoked device gets
    `410 {"wipe": true}` on its next request. The app then deletes its cached map, cached audio, token and pairing,
    and confirms. Recordings still waiting in its outbox are handled per question 2 below.
21. **Devices are clients, not workers.** A device never pushes journal rows. It writes through captures (outbox,
    tus) and small API calls (task done, approve), each checked when it arrives, so an offline replay is judged by the
    member's role at that moment: no longer allowed means a proposal, never a silent drop. It reads through
    `GET /v1/device/snapshot` and `GET /v1/device/pull?since=`, the member's projection of the journal:
    - rows filtered by the member's current view; member rows without contact details below manager; seats,
      invites and devices for owners only (managers see free employee seats);
    - a local, unsynced `view_changes` table records every `eff_level` or path change on that worker. A node the
      member could see before and cannot now is sent as an **`H` tombstone**: drop the node, its subtree, everything
      hanging off them and their cached audio. A capture that moved out of view is sent as a `D`;
    - more visibility, a role change or a scope change sends **`reset`**: the device wipes its cache and loads a new
      snapshot;
    - ids of rows the device never had are never sent;
    - a device that has not reached a brain for 14 days (owner setting) hides and wipes its cache until it does.

### E. Sync (extends ADR 0012)

22. **Journal rows carry who and how visible.** `sync_changes` gains `author_member_id`, `author_level`, `node_id`,
    `vis` (the node's `eff_level` at the time) and `base` (the time and origin of the row version the author edited).
    The capture triggers fill them from a per-transaction setting (SQLite `sync_state`; Postgres
    `set_config('notecad.member', ...)`) and the node's level. The Postgres function is generated into 0007.
23. **The receiver checks.** The HTTP hub on push, every worker on pull, and Supabase through `receive()` against the
    hub's own member tables each turn a row change into an action (title changed = rename, parent changed = move ...)
    and check it against the author's **current** role in their own copy. A change that is not allowed is not
    applied. It becomes a proposal, kept once per change (origin and origin_seq) however many receivers see it. The
    push response carries the reason and the hub's current row; the author's worker puts that row back without echo,
    and the author's device shows a toast. Allowed changes follow last-writer-wins as before.
24. **Rank only decides real conflicts.** Two edits from the same `base` are concurrent. Then the higher rank wins
    (system, owner, manager, employee; the author's level capped at their current one), time breaks ties, and the
    other version goes to `sync_conflicts` and the node's history. Edits made one after the other keep plain
    last-writer-wins, so an employee can still change a row a manager edited earlier, where they are allowed to.
25. **Roles travel like data.** Member, scope, seat and device rows sync like any row. Derived columns (`eff_level`,
    roll-up tiers) are recomputed on arrival. A member change bumps that member's view epoch on each worker, and
    their devices reset.
26. **Workers are full copies on machines the owner controls**, using the worker credential. A member's laptop runs
    the app against a brain with a device token. A partial, member-level brain copy is not supported in this phase.

### F. Surfaces and audit

27. **Apps.** `GET /v1/me` (member, level, scopes, capabilities). A **People & seats** panel on desktop and phone:
    owners add seats, invite (QR), change role and scope, revoke, and see devices; managers invite into free employee
    seats and see their team. A lock badge with the level on nodes restricted themselves, a faint lock on nodes that
    inherit it. Edit, rename and delete controls are hidden when the capability is missing (the server still decides).
    The Inbox shows proposals with Approve and Reject to managers and owners, and "waiting for approval" to the author.
    The phone gets a join screen and shows sync rejections as toasts.
28. **Voice.** "Make Johan a manager", "Who can see Financials?", "Restrict Financials to owner only" come from the
    rules grammar. Owners and managers get the change (decision 7) or the answer ("Financials is owner only: Dennis
    can see it"). An employee gets a polite refusal, and the attempt is logged.
29. **Audit.** Every permission-relevant action goes in `action_log` with who, level, what and approved by,
    refusals included. `GET /v1/workspaces/{ws}/audit`: owners see everything, managers their scope and their team,
    employees their own.

### G. Migrations and generated RLS

30. **Migration 7, the same in SQLite and Supabase.** `db.MIGRATIONS` gets 7, and
    `supabase\migrations\0007_roles_seats_permissions.sql` is written by `tools\gen_rls_migration.py` from the DDL of
    migration 7, the journal additions in `sync.py` (new columns, `nc_sync_annotate()`, triggers for the new tables)
    and `permissions.rls()`. The Phase 6 capture function is unchanged, so 0005 stays exactly as shipped; its check
    now renders it from the Phase 6 table list. `permissions.rls()` renders the SQL helpers
    (`nc_level(ws)`, `nc_sees_node(node_id)`), one select policy per table from the read rules, write policies from
    the matrix, and owner-only access to seats, invites, devices and scopes (`token_hash` never readable). It drops and
    replaces the 0001 policies. `--check` runs in the `brain-postgres` CI job next to `gen_sync_migration.py --check`,
    and a test keeps the matrix, the generated SQL and the SQLite migration in step. The migration deletes no data: it
    adds tables and columns, fills them, and rewrites `members.role` values. `data\` is copied to
    `data\archive\roles-<time>\` before it first runs on this PC.
31. **Speed targets at 2,000 nodes** (`seed_synthetic_farm.py`, `perf_probe.py`, results in `docs\perf\roles.md`): an
    employee's mind map within 15 % of the owner's (83 ms today), retrieval within 10 % (76 ms), a 500-node visibility
    recompute under 50 ms, device pull filtering under 5 ms per 500 changes, a snapshot under 300 ms.

## Threat model

| Threat | The attacker has | What stops it | What is left |
|---|---|---|---|
| **Stolen phone** | The app, its device token and a cache of one member's view; maybe unsent recordings | The cache never held more than that member's level and scope. The token is Keystore-encrypted and not backed up. The owner revokes the device in People & seats: every brain refuses it within one sync interval, and its next contact wipes it. The cache expires after 14 days offline. A phone token cannot make tokens; only a manager's can make invites, only into employee seats already bought, and the owner sees every join | An unlocked phone kept offline shows its cache until it expires. Android file encryption protects it while locked |
| **Tampered device** (modified app, rooted phone, token used from a script) | A valid member token; any request it likes | Member and level come from the token alone. Every write passes `permissions` in `Applier.apply`. `context_node_id`, audio, capture summaries and Undo are checked against the caller's view and authorship. Capture ids are per author: someone else's id answers 409, not their summary (today's duplicate check would leak it). Rate limits per device. Device pull is built on the server. Hidden buttons shown by a modified app only get 403s and proposals | The member can do anything their role allows, at the rate limit, and it is all in the audit log |
| **Revoked employee, offline** | A phone with a cache and maybe an outbox | Revocation is immediate on every brain that has it, and the edge node gets it at its next sync. First contact: 410 and wipe. The 14-day expiry. Outbox recordings are never applied by themselves (question 2) | Until contact or expiry the cache is readable, but it never held restricted data. A phone that only talks to an edge node that has not synced since the revoke is refused once it syncs; the revoke screen shows which brains have confirmed |
| **Model mis-routing or prompt injection** | Gemma or Claude proposing wrong actions; a note that contains instructions | The model sees only the author's view, as `n1`, `n2` labels for visible ids. Validation rejects unknown ids. `Applier` checks permissions after validation. Role, visibility and delete actions are not in the model's schema. Structural actions need an explicit verb. Notes reach a model as information, never as instructions | A wrong placement inside the author's own view, as today: Inbox and Undo |
| **Stale worker** (an edge node offline while a manager was demoted on the desktop) | Changes applied under an old role | The receiver checks the author's current role (decision 23); a refused change becomes a proposal and the hub's row goes back; real conflicts are decided by rank | People on the stale worker see the old role's effects there until it syncs |
| **Leaked invite** (QR photo, forwarded link) | A one-time code | Single use, 72 h default, role and scope fixed by the inviter, a confirm on the phone, every join shown to the owner | Whoever uses it first gets the seat; the owner sees it and revokes |
| **Inference** (counts, search, errors) | Ordinary access, looking for traces | Roll-ups per tier; an edge is hidden if either end is; 404 for hidden ids; search, keyterms and number ranges filtered; tombstones only for rows the device had; capture text and audio at the strictest tier they touched | Gaps can be noticed (Field 705 missing between 704 and 706) |
| **Manager overreach** | Manager rights | Cannot set owner-only, loosen an owner's restriction, change roles, buy or revoke seats, or invite outside their scope; everything is in the owner's audit view | A manager can restrict a branch in their scope from employees, by design |
| **Shared PC** | A seat at a PC where loopback is trusted | `NC_BRAIN_TRUST_LOOPBACK=0` and `NC_BRAIN_LOCAL_MEMBER`; the foreign-origin rules of ADR 0013 stay | On the owner's own PC, whoever is at the keyboard is the owner, as today |
| **Out of scope** | A compromised worker, the Supabase service key, or the `data\` folder on disk | These hold full copies by design. Protect them with the OS account, BitLocker and the vault | Stated, not solved here |

## Where this ADR reads into the brief (please check)

- Managers may edit other node attributes in their scope. Employees may change only progress figures, which the
  brief calls "progress updates", so the showcase "Today I planted field south 704 to 708" applies for an employee.
- Employees may edit their own notes and undo their own captures. They may place their own held notes, but the brain
  learns aliases only from managers and owners.
- A manager's rename, move or delete becomes a proposal to an owner rather than a refusal.
- Tighten at once, loosen with a confirm (decision 7).
- Owners need no seat.
- Devices are clients, not workers (decision 21): the brief's "push" checks apply to worker pushes and to each
  device request or outbox replay.
- Remote members reach the companion through the brain (decision 13).
- Capture text and audio take the strictest level any of their events touched (decision 10).
- A cached view expires after 14 days offline.

## Questions for the owner, answered 2026-10-29

1. **Existing `editor` members.** The brief maps `editor` to `manager`, but every delegation person (Sipho, Thabo in
   the showcase) is an `editor` only because it was `add_member`'s default. **Answer: `editor` members that never had a
   login (`user_id` empty, which is all of them today) become `employee`; the rest become `manager`.** Without a seat
   nobody can sign in, and assigning a seat asks for the role.
2. **A revoked phone's unsent recordings.** **Answer: recordings made before the revoke are handed in once as
   quarantined Inbox proposals for the owner, never applied by themselves; then the phone wipes.**
3. **Phones paired today with the shared token.** **Answer: for one release they keep working as the first owner,
   with a "re-pair with a seat" banner, and a setting turns that off.**

## Consequences

- The build follows the brief's order: backup and migration 7; `permissions.py` and enforcement; seats, invites,
  tokens and joining; the apps; tests; then `CLAUDE.md`, `docs\BUILD_STATUS.md` and the data-flow diagram.
- Tests (the brief's list) include: brain `test_roles.py` (employee rename = proposal, employee delete = refused,
  employee note = applied, manager approval logged with author and approver; zero restricted rows in an employee's
  pull, digest, mind map, search, export and event stream; tombstones after a late restriction; revoke and wipe;
  last-owner guard; receiver re-check), run on SQLite and on Postgres in CI. Also companion tests, Vitest role gating,
  a Playwright test that joins an employee seat in a second browser context and never sees Financials, and an
  Android unit test for the tombstone wipe. The showcase seed gains an owner, a manager scoped to North section,
  employees Sipho and Thandi, and Financials restricted to owner.
- Postgres, Supabase RLS, the Android build and Tauri can only be verified in CI (none of them run on WABAKIPI).
- For today's setup: the desktop keeps working unchanged as the owner on loopback. Paired phones show a re-pair
  banner (question 3). An Edge AI Node on a shared PC should run with `NC_BRAIN_TRUST_LOOPBACK=0`.

## Rejected

- **Hiding restricted data in the apps only**: the brief rules it out, and a modified app would show it.
- **Encrypting each restricted branch with its own key**: key handling for offline phones is heavy, and the server
  filter already keeps the data off devices that may not see it.
- **A separate workspace or copy per role**: the business would no longer be one map, and every change would need
  copying.
- **Supabase Auth as the only identity**: the farm works offline. Device tokens work against the desktop and the
  edge node; `members.user_id` stays for the cloud.
- **Letting the model produce role or visibility changes**: a mishearing or a note containing instructions could
  then grant rights.
