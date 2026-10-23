-- Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
-- Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
-- Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
--
-- 0001 core schema for Supabase. Same tables the brain creates itself on SQLite (services/brain/notecad_brain/db.py),
-- plus row-level security: a signed-in user reads and writes only workspaces they are a member of
-- (members.user_id = auth.uid()); viewers read only; the audit log is read-only for everyone.
-- The brain worker connects with the service role, which bypasses RLS, and always filters by workspace_id itself.

create table if not exists workspaces (
  id text primary key, name text not null, persona text, locale text not null default 'en-ZA',
  owner_user text, created_at text not null);
create table if not exists members (
  id text primary key, workspace_id text not null references workspaces(id) on delete cascade,
  user_id text, display_name text not null, role text not null default 'editor', contact text,
  person_node_id text, created_at text not null);
create index if not exists members_ws on members(workspace_id);
create table if not exists nodes (
  id text primary key, workspace_id text not null references workspaces(id) on delete cascade,
  parent_id text references nodes(id), path text not null, depth integer not null, sort_key text not null default 'm',
  kind text not null, title text not null, summary text, attributes text not null default '{}',
  status text not null default 'ok', status_reason text, status_since text not null,
  display_status text not null default 'ok', child_worst text not null default 'ok',
  open_tasks integer not null default 0, open_alerts integer not null default 0,
  version integer not null default 1, created_by text not null default 'user',
  created_at text not null, updated_at text not null);
create index if not exists nodes_ws_parent on nodes(workspace_id, parent_id);
create index if not exists nodes_ws_path on nodes(workspace_id, path);
create table if not exists node_aliases (
  node_id text not null references nodes(id) on delete cascade, alias text not null, lang text,
  weight real not null default 1, primary key (node_id, alias));
create table if not exists node_embeddings (
  node_id text primary key references nodes(id) on delete cascade, model text not null, vec bytea not null);
create table if not exists edges (
  id text primary key, workspace_id text not null references workspaces(id) on delete cascade,
  src_id text not null references nodes(id) on delete cascade, dst_id text not null references nodes(id) on delete cascade,
  edge_type text not null, weight real not null default 1, created_by text not null default 'user',
  unique (src_id, dst_id, edge_type));
create table if not exists captures (
  id text primary key, workspace_id text not null references workspaces(id) on delete cascade,
  user_id text, source text not null default 'phone', audio_path text, sha256 text, recorded_at text not null,
  geo text, lang_hint text, state text not null default 'queued', text text, transcript text, lang text,
  router text, error text, created_at text not null, updated_at text not null);
create index if not exists captures_ws on captures(workspace_id, created_at);
create table if not exists capture_events (
  capture_id text not null references captures(id) on delete cascade, idx integer not null, text text not null,
  candidates text, routed text, router text, confidence real, state text not null default 'new',
  primary key (capture_id, idx));
create table if not exists notes (
  id text primary key, workspace_id text not null, node_id text not null references nodes(id) on delete cascade,
  capture_id text, body text not null, tags text not null default '[]', author text not null default 'user',
  created_at text not null);
create index if not exists notes_node on notes(node_id, created_at);
create table if not exists tasks (
  id text primary key, workspace_id text not null, node_id text not null references nodes(id) on delete cascade,
  capture_id text, title text not null, priority text not null default 'normal', due_at text,
  assignee_member text, assignee_hint text, state text not null default 'open', done_at text, created_at text not null);
create index if not exists tasks_ws_state on tasks(workspace_id, state);
create table if not exists alerts (
  id text primary key, workspace_id text not null, node_id text not null references nodes(id) on delete cascade,
  capture_id text, severity text not null, category text not null, title text not null, resolved_at text,
  created_at text not null);
create index if not exists alerts_ws on alerts(workspace_id, resolved_at);
create table if not exists profile_facts (
  workspace_id text not null, key text not null, value text not null, confidence real not null default 1,
  source text not null, updated_at text not null, primary key (workspace_id, key));
create table if not exists inbox (
  id text primary key, workspace_id text not null, capture_id text, event_idx integer, question text not null,
  options text not null default '[]', event_text text, proposal text, state text not null default 'open',
  resolution text, created_at text not null, resolved_at text);
create index if not exists inbox_ws on inbox(workspace_id, state);
create table if not exists action_log (
  id text primary key, workspace_id text not null, capture_id text, event_idx integer, seq integer not null,
  actor text not null, action text not null, inverse text not null, provenance text not null,
  undone_at text, created_at text not null);
create index if not exists action_log_capture on action_log(capture_id, seq);
create table if not exists notifications (
  id text primary key, workspace_id text not null, member_id text, kind text not null, payload text not null,
  created_at text not null, sent_at text);
create table if not exists route_corrections (
  id text primary key, workspace_id text not null, phrase text not null, node_id text not null, created_at text not null);
create table if not exists jobs (
  id text primary key, kind text not null, payload text not null, state text not null default 'queued',
  attempts integer not null default 0, run_after text not null, last_error text, created_at text not null);
create index if not exists jobs_state on jobs(state, run_after);;

-- row-level security
alter table workspaces enable row level security;
create policy workspaces_read on workspaces for select using (exists (select 1 from members m where m.workspace_id = workspaces.id and m.user_id = auth.uid()::text));
create policy workspaces_write on workspaces for all using (exists (select 1 from members m where m.workspace_id = workspaces.id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = workspaces.id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table members enable row level security;
create policy members_read on members for select using (exists (select 1 from members m where m.workspace_id = members.workspace_id and m.user_id = auth.uid()::text));
create policy members_write on members for all using (exists (select 1 from members m where m.workspace_id = members.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = members.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table nodes enable row level security;
create policy nodes_read on nodes for select using (exists (select 1 from members m where m.workspace_id = nodes.workspace_id and m.user_id = auth.uid()::text));
create policy nodes_write on nodes for all using (exists (select 1 from members m where m.workspace_id = nodes.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = nodes.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table node_aliases enable row level security;
create policy node_aliases_read on node_aliases for select using (exists (select 1 from nodes n join members m on m.workspace_id = n.workspace_id where n.id = node_aliases.node_id and m.user_id = auth.uid()::text));
create policy node_aliases_write on node_aliases for all using (exists (select 1 from nodes n join members m on m.workspace_id = n.workspace_id where n.id = node_aliases.node_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from nodes n join members m on m.workspace_id = n.workspace_id where n.id = node_aliases.node_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table node_embeddings enable row level security;
create policy node_embeddings_read on node_embeddings for select using (exists (select 1 from nodes n join members m on m.workspace_id = n.workspace_id where n.id = node_embeddings.node_id and m.user_id = auth.uid()::text));
create policy node_embeddings_write on node_embeddings for all using (exists (select 1 from nodes n join members m on m.workspace_id = n.workspace_id where n.id = node_embeddings.node_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from nodes n join members m on m.workspace_id = n.workspace_id where n.id = node_embeddings.node_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table edges enable row level security;
create policy edges_read on edges for select using (exists (select 1 from members m where m.workspace_id = edges.workspace_id and m.user_id = auth.uid()::text));
create policy edges_write on edges for all using (exists (select 1 from members m where m.workspace_id = edges.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = edges.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table captures enable row level security;
create policy captures_read on captures for select using (exists (select 1 from members m where m.workspace_id = captures.workspace_id and m.user_id = auth.uid()::text));
create policy captures_write on captures for all using (exists (select 1 from members m where m.workspace_id = captures.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = captures.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table capture_events enable row level security;
create policy capture_events_read on capture_events for select using (exists (select 1 from captures c join members m on m.workspace_id = c.workspace_id where c.id = capture_events.capture_id and m.user_id = auth.uid()::text));
create policy capture_events_write on capture_events for all using (exists (select 1 from captures c join members m on m.workspace_id = c.workspace_id where c.id = capture_events.capture_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from captures c join members m on m.workspace_id = c.workspace_id where c.id = capture_events.capture_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table notes enable row level security;
create policy notes_read on notes for select using (exists (select 1 from members m where m.workspace_id = notes.workspace_id and m.user_id = auth.uid()::text));
create policy notes_write on notes for all using (exists (select 1 from members m where m.workspace_id = notes.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = notes.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table tasks enable row level security;
create policy tasks_read on tasks for select using (exists (select 1 from members m where m.workspace_id = tasks.workspace_id and m.user_id = auth.uid()::text));
create policy tasks_write on tasks for all using (exists (select 1 from members m where m.workspace_id = tasks.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = tasks.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table alerts enable row level security;
create policy alerts_read on alerts for select using (exists (select 1 from members m where m.workspace_id = alerts.workspace_id and m.user_id = auth.uid()::text));
create policy alerts_write on alerts for all using (exists (select 1 from members m where m.workspace_id = alerts.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = alerts.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table profile_facts enable row level security;
create policy profile_facts_read on profile_facts for select using (exists (select 1 from members m where m.workspace_id = profile_facts.workspace_id and m.user_id = auth.uid()::text));
create policy profile_facts_write on profile_facts for all using (exists (select 1 from members m where m.workspace_id = profile_facts.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = profile_facts.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table inbox enable row level security;
create policy inbox_read on inbox for select using (exists (select 1 from members m where m.workspace_id = inbox.workspace_id and m.user_id = auth.uid()::text));
create policy inbox_write on inbox for all using (exists (select 1 from members m where m.workspace_id = inbox.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = inbox.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table action_log enable row level security;
create policy action_log_read on action_log for select using (exists (select 1 from members m where m.workspace_id = action_log.workspace_id and m.user_id = auth.uid()::text));
alter table notifications enable row level security;
create policy notifications_read on notifications for select using (exists (select 1 from members m where m.workspace_id = notifications.workspace_id and m.user_id = auth.uid()::text));
create policy notifications_write on notifications for all using (exists (select 1 from members m where m.workspace_id = notifications.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = notifications.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));
alter table route_corrections enable row level security;
create policy route_corrections_read on route_corrections for select using (exists (select 1 from members m where m.workspace_id = route_corrections.workspace_id and m.user_id = auth.uid()::text));
create policy route_corrections_write on route_corrections for all using (exists (select 1 from members m where m.workspace_id = route_corrections.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor'))) with check (exists (select 1 from members m where m.workspace_id = route_corrections.workspace_id and m.user_id = auth.uid()::text and m.role in ('owner','editor')));

-- live updates for the views (Supabase Realtime)
do $$ begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    alter publication supabase_realtime add table nodes, notes, tasks, alerts, inbox, captures;
  end if;
end $$;
