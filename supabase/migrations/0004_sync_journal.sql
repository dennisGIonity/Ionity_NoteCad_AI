-- Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
-- Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
-- Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-- Phase 5: Supabase as the sync hub. Every insert, update and delete on the shared tables is journalled in
-- sync_changes (by triggers), so desktops and Edge AI Nodes can pull what changed and push what they did.
-- Same journal and triggers as services/brain/notecad_brain/sync.py. Workers connect with the service role;
-- the journal is not readable through the API (row-level security on, no policies).

create table if not exists sync_state (key text primary key, value text);
create table if not exists sync_changes (
  seq bigserial primary key, tbl text not null, pk text not null, op text not null, row text, ws text,
  origin text not null, ts text not null, origin_seq bigint, via text, received_at text);
create index if not exists sync_changes_row on sync_changes(tbl, pk, ts);
create index if not exists sync_changes_origin on sync_changes(origin, origin_seq);
create index if not exists sync_changes_ws on sync_changes(ws);

alter table sync_state enable row level security;
alter table sync_changes enable row level security;
insert into sync_state(key, value) values ('worker_id', 'supabase') on conflict (key) do nothing;

create or replace function nc_sync_capture() returns trigger language plpgsql as $f$
declare r jsonb; o jsonb; keys text[] := '{}'; c text; w text; src text;
begin
  if coalesce(current_setting('notecad.applying', true), '') = '1' then return null; end if;
  if TG_OP = 'DELETE' then r := to_jsonb(OLD); else r := to_jsonb(NEW); end if;
  if TG_OP = 'UPDATE' then
    o := to_jsonb(OLD);
    if (o - 'synced_at') = (r - 'synced_at') then return null; end if;
  end if;
  foreach c in array TG_ARGV loop keys := keys || (r->>c); end loop;
  if TG_TABLE_NAME = 'workspaces' then w := r->>'id';
  elsif TG_TABLE_NAME = 'node_aliases' then select n.workspace_id into w from nodes n where n.id = r->>'node_id';
  elsif TG_TABLE_NAME = 'capture_events' then select x.workspace_id into w from captures x where x.id = r->>'capture_id';
  else w := r->>'workspace_id'; end if;
  src := coalesce(nullif(current_setting('notecad.worker', true), ''),
                  (select value from sync_state where key = 'worker_id'), 'cloud');
  insert into sync_changes(tbl, pk, op, row, ws, origin, ts)
  values (TG_TABLE_NAME, array_to_string(keys, chr(31)), case when TG_OP = 'DELETE' then 'D' else 'U' end,
          case when TG_OP = 'DELETE' then null else r::text end, w, src,
          to_char(clock_timestamp() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'));
  return null;
end $f$;

drop trigger if exists nc_sync_workspaces on workspaces;
create trigger nc_sync_workspaces after insert or update or delete on workspaces for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_members on members;
create trigger nc_sync_members after insert or update or delete on members for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_nodes on nodes;
create trigger nc_sync_nodes after insert or update or delete on nodes for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_node_aliases on node_aliases;
create trigger nc_sync_node_aliases after insert or update or delete on node_aliases for each row execute function nc_sync_capture('node_id', 'alias');
drop trigger if exists nc_sync_edges on edges;
create trigger nc_sync_edges after insert or update or delete on edges for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_captures on captures;
create trigger nc_sync_captures after insert or update or delete on captures for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_capture_events on capture_events;
create trigger nc_sync_capture_events after insert or update or delete on capture_events for each row execute function nc_sync_capture('capture_id', 'idx');
drop trigger if exists nc_sync_notes on notes;
create trigger nc_sync_notes after insert or update or delete on notes for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_tasks on tasks;
create trigger nc_sync_tasks after insert or update or delete on tasks for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_alerts on alerts;
create trigger nc_sync_alerts after insert or update or delete on alerts for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_profile_facts on profile_facts;
create trigger nc_sync_profile_facts after insert or update or delete on profile_facts for each row execute function nc_sync_capture('workspace_id', 'key');
drop trigger if exists nc_sync_inbox on inbox;
create trigger nc_sync_inbox after insert or update or delete on inbox for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_action_log on action_log;
create trigger nc_sync_action_log after insert or update or delete on action_log for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_notifications on notifications;
create trigger nc_sync_notifications after insert or update or delete on notifications for each row execute function nc_sync_capture('id');
drop trigger if exists nc_sync_route_corrections on route_corrections;
create trigger nc_sync_route_corrections after insert or update or delete on route_corrections for each row execute function nc_sync_capture('id');
