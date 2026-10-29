# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Who may see and do what (ADR 0014). The one place the rules live.

The brain's checks, the apps' capabilities and the Supabase row-level security all come from here
(supabase/migrations/0007 is written by tools/gen_rls_migration.py from rls()).

Levels: 0 system (the brain itself, never a person), 1 owner, 2 manager, 3 employee. A node's visibility is the highest
level that may still see it (all 3, manager 2, owner 1); a member sees a node when `level <= eff_level`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SYSTEM, OWNER, MANAGER, EMPLOYEE = 0, 1, 2, 3
LEVELS = {"system": SYSTEM, "owner": OWNER, "manager": MANAGER, "employee": EMPLOYEE}
ROLES = {v: k for k, v in LEVELS.items()}
VISIBILITY = {"all": EMPLOYEE, "manager": MANAGER, "owner": OWNER}

# What happens when a member does something
ALLOW = "allow"        # done at once
CONFIRM = "confirm"    # done after a one-tap confirm by the same person
PROPOSE = "propose"    # held in the Inbox for a manager (or an owner) to approve
REFUSE = "refuse"      # nothing changes: a polite answer, and a refused row in action_log
SCOPE = "scope"        # a manager inside the branches they manage: allowed; elsewhere the employee's rule applies
OWN = "own"            # "own|propose": allowed on their own entry, else the outcome after the bar
ASSIGNED = "assigned"  # "assigned|propose": allowed on a task assigned to them

# The matrix of ADR 0014, decision 2. Rules that are not a cell are kept with the code that needs them: a manager sets
# visibility only up to `manager` and never loosens an owner's; a manager invites only into employee seats.
MATRIX: dict[str, tuple[str, str, str]] = {
    # action               owner    manager  employee
    "capture":           (ALLOW,   ALLOW,   ALLOW),
    "append_note":       (ALLOW,   ALLOW,   ALLOW),
    "create_alert":      (ALLOW,   ALLOW,   ALLOW),
    "raise_status":      (ALLOW,   ALLOW,   ALLOW),
    "create_task":       (ALLOW,   ALLOW,   ALLOW),               # unassigned, or for themselves
    "progress":          (ALLOW,   ALLOW,   ALLOW),               # PROGRESS_KEYS only
    "assign_task":       (ALLOW,   SCOPE,   PROPOSE),             # also a due date
    "complete_task":     (ALLOW,   SCOPE,   "assigned|propose"),
    "update_attributes": (ALLOW,   SCOPE,   PROPOSE),
    "edit_entry":        (ALLOW,   SCOPE,   "own|propose"),       # a note, task or alert
    "delete_entry":      (ALLOW,   SCOPE,   REFUSE),              # an employee removes their own only by Undo
    "resolve_alert":     (ALLOW,   SCOPE,   PROPOSE),
    "lower_status":      (ALLOW,   SCOPE,   PROPOSE),
    "create_node":       (ALLOW,   SCOPE,   PROPOSE),
    "rename_node":       (ALLOW,   PROPOSE, PROPOSE),
    "move_node":         (ALLOW,   PROPOSE, PROPOSE),
    "merge_nodes":       (ALLOW,   PROPOSE, PROPOSE),
    "delete_node":       (CONFIRM, PROPOSE, REFUSE),
    "link_nodes":        (ALLOW,   SCOPE,   PROPOSE),
    "set_visibility":    (ALLOW,   SCOPE,   REFUSE),
    "approve":           (ALLOW,   SCOPE,   REFUSE),
    "undo":              (ALLOW,   SCOPE,   "own|refuse"),
    "place_note":        (ALLOW,   SCOPE,   "own|refuse"),
    "teach_alias":       (ALLOW,   SCOPE,   REFUSE),
    "profile_fact":      (ALLOW,   PROPOSE, PROPOSE),
    "manage_seats":      (ALLOW,   REFUSE,  REFUSE),
    "set_role":          (ALLOW,   REFUSE,  REFUSE),              # roles and scopes
    "invite":            (ALLOW,   SCOPE,   REFUSE),
    "manage_workspace":  (ALLOW,   REFUSE,  REFUSE),              # rename or delete the business
    "export":            (ALLOW,   ALLOW,   ALLOW),               # what they can see
    "read_audit":        (ALLOW,   SCOPE,   "own|refuse"),
}
READS = {"export", "read_audit"}  # what a read-only member may still do

# Attributes an employee may change: field work they report (ADR 0014, "progress updates")
PROGRESS_KEYS = frozenset({"planted_ha", "harvested_ha", "sprayed_ha", "done_ha", "progress_pct", "phase"})


def decide(level: int, action: str, *, in_scope: bool = True, own: bool = False, assigned: bool = False,
           read_only: bool = False) -> str:
    """ALLOW, CONFIRM, PROPOSE or REFUSE for a member at `level`. `in_scope`: the node is inside the branches they
    manage; `own`: they wrote the entry; `assigned`: the task is theirs."""
    if level == SYSTEM:
        return ALLOW
    if level not in (OWNER, MANAGER, EMPLOYEE) or (read_only and action not in READS):
        return REFUSE
    return _cell(MATRIX[action], level, in_scope, own, assigned)


def _cell(cells: tuple[str, str, str], level: int, in_scope: bool, own: bool, assigned: bool) -> str:
    c = cells[level - 1]
    if c == SCOPE:
        return ALLOW if in_scope else _cell(cells, EMPLOYEE, in_scope, own, assigned)
    if "|" in c:
        cond, otherwise = c.split("|")
        return ALLOW if (own if cond == OWN else assigned) else otherwise
    return c


def member_role(role: str, user_id: str | None = None) -> tuple[str, int, int]:
    """(role, level, read_only) as stored. The Phase 1 names map as migration 7 maps them: an editor with a login is
    a manager, one without (a person added for delegation) an employee; a viewer is a read-only employee."""
    if role == "editor":
        role = "manager" if user_id else "employee"
    elif role == "viewer":
        return "employee", EMPLOYEE, 1
    if role not in LEVELS or role == "system":
        raise ValueError(f"unknown role {role!r}")
    return role, LEVELS[role], 0


# ==================================================================== the last owner
# Members are never deleted on their own (they are revoked); the last active owner cannot be demoted or revoked.
GUARD_SQLITE = [
    "drop trigger if exists nc_last_owner",
    """create trigger nc_last_owner before update of level, status on members
when OLD.level = 1 and OLD.status = 'active' and (NEW.level <> 1 or NEW.status <> 'active')
  and not exists (select 1 from members m where m.workspace_id = OLD.workspace_id and m.id <> OLD.id
                  and m.level = 1 and m.status = 'active')
begin select raise(abort, 'the last owner of a workspace cannot be demoted or revoked'); end""",
]
GUARD_PG = [
    """create or replace function nc_last_owner() returns trigger language plpgsql security definer
set search_path from current as $f$
begin
  if OLD.level = 1 and OLD.status = 'active' and (NEW.level <> 1 or NEW.status <> 'active')
     and not exists (select 1 from members m where m.workspace_id = OLD.workspace_id and m.id <> OLD.id
                     and m.level = 1 and m.status = 'active') then
    raise exception 'the last owner of a workspace cannot be demoted or revoked';
  end if;
  return NEW;
end $f$""",
    "drop trigger if exists nc_last_owner on members",
    "create trigger nc_last_owner before update on members for each row execute function nc_last_owner()",
]


def install_guards(db) -> None:
    """Re-run on every start, after the migrations (the members columns come from migration 7)."""
    with db._lock:
        for stmt in GUARD_SQLITE if db.kind == "sqlite" else GUARD_PG:
            db._conn.execute(stmt)


# ==================================================================== Supabase row-level security
# The helpers run as their owner (security definer), so a policy on members can ask about members without recursing.
# auth.uid() is the signed-in Supabase user; members.user_id links them to a member.
HELPERS_PG = [
    # the caller's member id, level and write level (a read-only member has none) in a workspace
    """create or replace function nc_member(ws text) returns text language sql stable security definer
set search_path from current as $$
  select id from members where workspace_id = ws and user_id = auth.uid()::text and status = 'active'
  order by level, created_at limit 1 $$""",
    """create or replace function nc_level(ws text) returns integer language sql stable security definer
set search_path from current as $$
  select min(level) from members where workspace_id = ws and user_id = auth.uid()::text and status = 'active' $$""",
    """create or replace function nc_write_level(ws text) returns integer language sql stable security definer
set search_path from current as $$
  select min(level) from members where workspace_id = ws and user_id = auth.uid()::text and status = 'active'
    and read_only = 0 $$""",
    # the paths of the subtree roots the caller is bound to (none: the whole map)
    """create or replace function nc_scope_paths(ws text) returns setof text language sql stable security definer
set search_path from current as $$
  select n.path from member_scopes s join nodes n on n.id = s.node_id
  where s.workspace_id = ws and s.member_id = nc_member(ws) $$""",
    # the node itself: a scoped employee also sees the ancestors of their roots (path stubs: title and kind)
    """create or replace function nc_sees_node(node text) returns boolean language sql stable security definer
set search_path from current as $$
  select exists (select 1 from nodes n where n.id = node and nc_level(n.workspace_id) <= n.eff_level
    and (nc_level(n.workspace_id) <= 2 or not exists (select 1 from nc_scope_paths(n.workspace_id))
         or exists (select 1 from nc_scope_paths(n.workspace_id) as s(path)
                    where n.path = s.path or n.path like s.path || '/%' or s.path like n.path || '/%'))) $$""",
    # what hangs off the node (notes, tasks, alerts, aliases ...): not on a path stub
    """create or replace function nc_sees_rows(node text) returns boolean language sql stable security definer
set search_path from current as $$
  select exists (select 1 from nodes n where n.id = node and nc_level(n.workspace_id) <= n.eff_level
    and (nc_level(n.workspace_id) <= 2 or not exists (select 1 from nc_scope_paths(n.workspace_id))
         or exists (select 1 from nc_scope_paths(n.workspace_id) as s(path)
                    where n.path = s.path or n.path like s.path || '/%'))) $$""",
    # inside the branches the caller manages: owners everywhere, managers in their scope (or everywhere, unscoped)
    """create or replace function nc_in_scope(node text) returns boolean language sql stable security definer
set search_path from current as $$
  select exists (select 1 from nodes n where n.id = node and (nc_level(n.workspace_id) = 1
    or (nc_level(n.workspace_id) = 2 and (not exists (select 1 from nc_scope_paths(n.workspace_id))
        or exists (select 1 from nc_scope_paths(n.workspace_id) as s(path)
                   where n.path = s.path or n.path like s.path || '/%'))))) $$""",
    # a capture's text and audio: its author, or a level that sees the strictest node it touched (not a scoped employee)
    """create or replace function nc_sees_capture(cap text) returns boolean language sql stable security definer
set search_path from current as $$
  select exists (select 1 from captures c where c.id = cap and (c.member_id = nc_member(c.workspace_id)
    or (nc_level(c.workspace_id) <= c.eff_level
        and (nc_level(c.workspace_id) <= 2 or not exists (select 1 from nc_scope_paths(c.workspace_id)))))) $$""",
]
VIEWS_PG = [
    # everyone in a workspace sees who is in it; contact details only for managers and owners
    """create or replace view members_directory as
  select id, workspace_id, display_name, role, level, person_node_id, status,
         case when nc_level(workspace_id) <= 2 then contact end as contact
  from members where nc_level(workspace_id) is not null""",
    # an owner's list of devices, without the token hash (the devices table itself has no policy: nobody reads it)
    """create or replace view devices_list as
  select id, workspace_id, member_id, name, platform, created_at, last_seen_at, revoked_at
  from devices where nc_level(workspace_id) = 1""",
    "grant select on members_directory, devices_list to authenticated",
]


@dataclass(frozen=True)
class Table:
    read: str | None                                       # who may read a row (SQL); None: nobody, through any API
    writes: dict[str, str] = field(default_factory=dict)  # insert / update / delete -> the action it counts as
    node: str | dict[str, str] | None = None               # the column naming the node a row hangs off (per command)
    ws: str = "workspace_id"                               # the row's workspace (an expression)
    own: str | None = None                                 # the column naming the member who wrote the row
    assigned: str | None = None                            # the column naming the member a task is for
    sees: str | None = None                                # visibility of the row, when not nc_sees_rows(node)
    scope: str | None = None                               # "a manager's branches" for rows without a node


_NODE_WS = "(select x.workspace_id from nodes x where x.id = {t}.node_id)"
_SEES_NODE = "nc_sees_node(id)"
# Where one kind of write covers several actions (an update to nodes can be a rename or a new area) the strictest is
# used: row-level security is the ceiling for direct cloud writes, and the brain decides the finer cases.
RLS_TABLES: dict[str, Table] = {
    "workspaces": Table("nc_level(id) is not null", {"update": "manage_workspace", "delete": "manage_workspace"},
                        ws="id"),
    "members": Table("nc_level(workspace_id) <= 2 or user_id = auth.uid()::text",
                     {"insert": "set_role", "update": "set_role"}),
    "member_scopes": Table("nc_level(workspace_id) <= 2 or member_id = nc_member(workspace_id)",
                           {"insert": "set_role", "delete": "set_role"}),
    "seats": Table("nc_level(workspace_id) = 1 or (nc_level(workspace_id) = 2 and role_level = 3 "
                   "and status = 'available')",
                   {"insert": "manage_seats", "update": "manage_seats", "delete": "manage_seats"}),
    "invites": Table("nc_level(workspace_id) = 1 or created_by = nc_member(workspace_id)",
                     {"insert": "invite", "update": "manage_seats", "delete": "manage_seats"}),
    "devices": Table(None),
    "nodes": Table(_SEES_NODE, {"insert": "create_node", "update": "rename_node", "delete": "delete_node"},
                   node={"insert": "parent_id", "update": "id", "delete": "id"}),
    "node_aliases": Table("nc_sees_rows(node_id)", {"insert": "teach_alias", "update": "teach_alias",
                                                    "delete": "teach_alias"},
                          node="node_id", ws=_NODE_WS.format(t="node_aliases")),
    "node_embeddings": Table("nc_sees_rows(node_id)", ws=_NODE_WS.format(t="node_embeddings")),
    "edges": Table("nc_sees_rows(src_id) and nc_sees_rows(dst_id)",
                   {"insert": "link_nodes", "update": "link_nodes", "delete": "link_nodes"},
                   node="src_id", sees="nc_sees_rows(src_id) and nc_sees_rows(dst_id)"),
    "captures": Table("nc_sees_capture(id)", {"insert": "capture"}, own="member_id"),
    "capture_events": Table("nc_sees_capture(capture_id)"),
    "notes": Table("nc_sees_rows(node_id)", {"insert": "append_note", "update": "edit_entry",
                                             "delete": "delete_entry"}, node="node_id", own="member_id"),
    "tasks": Table("nc_sees_rows(node_id)", {"insert": "create_task", "update": "assign_task",
                                             "delete": "delete_entry"},
                   node="node_id", own="created_by_member", assigned="assignee_member"),
    "alerts": Table("nc_sees_rows(node_id)", {"insert": "create_alert", "update": "resolve_alert",
                                              "delete": "delete_entry"}, node="node_id", own="member_id"),
    "profile_facts": Table("nc_level(workspace_id) <= case visibility when 'owner' then 1 when 'manager' then 2 "
                           "else 3 end",
                           {"insert": "profile_fact", "update": "profile_fact", "delete": "profile_fact"}),
    "inbox": Table("author_member_id = nc_member(workspace_id) or nc_level(workspace_id) = 1 or "
                   "(nc_level(workspace_id) = 2 and (route_member_ids is null or "
                   "strpos(route_member_ids, nc_member(workspace_id)) > 0))",
                   {"update": "approve"},
                   scope="(route_member_ids is null or strpos(route_member_ids, nc_member(workspace_id)) > 0)"),
    "action_log": Table("case nc_level(workspace_id) when 1 then true "
                        "when 2 then member_id = nc_member(workspace_id) or (node_id is not null "
                        "and nc_sees_rows(node_id) and nc_in_scope(node_id)) "
                        "when 3 then member_id = nc_member(workspace_id) else false end"),
    "notifications": Table("member_id = nc_member(workspace_id) or nc_level(workspace_id) = 1"),
    "route_corrections": Table("nc_sees_rows(node_id)", {"insert": "teach_alias", "delete": "teach_alias"},
                               node="node_id"),
}


def _sql_cell(cells: tuple[str, str, str], level: int, t: Table, node: str | None) -> str:
    c = cells[level - 1]
    if c in (ALLOW, CONFIRM):
        return "true"
    if c == SCOPE:
        inside = f"nc_in_scope({node})" if node else (t.scope or "true")
        other = _sql_cell(cells, EMPLOYEE, t, node)
        return inside if other == "false" else f"({inside} or {other})"
    if "|" in c:  # the outcome after the bar is a proposal or a refusal: never a direct write
        col = t.own if c.split("|")[0] == OWN else t.assigned
        return f"{col} = nc_member({t.ws})" if col else "false"
    return "false"  # propose, refuse: the brain makes a proposal; nobody writes it directly


def _write_condition(name: str, t: Table, cmd: str, action: str) -> str | None:
    node = t.node.get(cmd) if isinstance(t.node, dict) else t.node
    cases = [(lvl, _sql_cell(MATRIX[action], lvl, t, node)) for lvl in (OWNER, MANAGER, EMPLOYEE)]
    cases = [(lvl, c) for lvl, c in cases if c != "false"]
    if not cases:
        return None
    expr = f"case nc_write_level({t.ws}) " + " ".join(f"when {lvl} then {c}" for lvl, c in cases) + " else false end"
    if node:
        sees = t.sees or ("nc_sees_node(id)" if name == "nodes" and node == "id" else f"nc_sees_rows({node})")
        expr += f" and {sees}"
    return expr


def rls_statements() -> list[str]:
    """Helpers, the last-owner guard, the views and one policy per table and command, from MATRIX and RLS_TABLES.
    Replaces the policies of 0001 (<table>_read, <table>_write)."""
    out = HELPERS_PG + GUARD_PG + VIEWS_PG
    for name, t in RLS_TABLES.items():
        out.append(f"alter table {name} enable row level security")
        out += [f"drop policy if exists {name}_{p} on {name}" for p in ("read", "write", "insert", "update", "delete")]
        if t.read:
            out.append(f"create policy {name}_read on {name} for select to authenticated using ({t.read})")
        for cmd, action in t.writes.items():
            cond = _write_condition(name, t, cmd, action)
            if cond is None:
                continue
            if cmd == "insert":
                check = cond + (f" and {t.own} = nc_member({t.ws})" if t.own else "")
                out.append(f"create policy {name}_insert on {name} for insert to authenticated with check ({check})")
            elif cmd == "update":
                out.append(f"create policy {name}_update on {name} for update to authenticated using ({cond}) "
                           f"with check ({cond})")
            else:
                out.append(f"create policy {name}_delete on {name} for delete to authenticated using ({cond})")
    return out
