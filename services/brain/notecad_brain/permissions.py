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

from .common import STATUS_RANK

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


# ==================================================================== who is asking, and what they see
@dataclass(frozen=True)
class Principal:
    """Who a request or a change acts for: a member of one workspace, or the brain itself (level 0). Taken from the
    credential alone (ADR 0014, decision 4): nothing a client says about itself is believed."""
    level: int
    workspace_id: str | None = None
    member_id: str | None = None
    read_only: bool = False
    scopes: tuple[str, ...] = ()  # the paths of the member's scope roots
    device_id: str | None = None
    name: str | None = None
    active: bool = True

    def decide(self, action: str, *, in_scope: bool = True, own: bool = False, assigned: bool = False) -> str:
        if not self.active:  # a revoked member's writes wait for an owner (ADR 0014, question 2); reads stop
            return REFUSE if action in READS else PROPOSE
        return decide(self.level, action, in_scope=in_scope, own=own, assigned=assigned, read_only=self.read_only)


SYSTEM_PRINCIPAL = Principal(SYSTEM)


def load_principal(db, ws: str, member_id: str | None, device_id: str | None = None) -> Principal | None:
    if not member_id:
        return None
    m = db.one("select * from members where id=? and workspace_id=?", (member_id, ws))
    if m is None:
        return None
    scopes = tuple(sorted(r["path"] for r in db.query(
        "select n.path from member_scopes s join nodes n on n.id=s.node_id where s.member_id=? and s.workspace_id=?",
        (member_id, ws))))
    return Principal(int(m["level"]), ws, m["id"], bool(m["read_only"]), scopes, device_id, m["display_name"],
                     m["status"] == "active")


def owner_principal(db, ws: str) -> Principal:
    """The workspace's first active owner: this PC's own app, and phones paired with the shared token for one more
    release (ADR 0014, question 3). The brain itself when a workspace has no owner row."""
    r = db.one("select id from members where workspace_id=? and level=1 and status='active' order by created_at", (ws,))
    return (load_principal(db, ws, r["id"]) if r else None) or Principal(SYSTEM, ws)


def under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def sees_row(p: Principal, path: str, eff_level: int) -> bool:
    """May this principal see what hangs off a node (its notes, tasks, alerts)? Without loading a whole View."""
    if p.level <= OWNER:
        return p.active or p.level == SYSTEM
    if not p.active or p.level > eff_level:
        return False
    return p.level < EMPLOYEE or not p.scopes or any(under(path, s) for s in p.scopes)


class View:
    """What one principal sees in one workspace, worked out once (per request, per change batch) from every node's
    effective level and path. The brain itself and owners see everything and skip the work.

    rows: the node and everything hanging off it. stub: an ancestor of a scoped employee's scope root, shown by title
    and kind only so their tree stays connected."""

    def __init__(self, db, p: Principal, ws: str):
        self.db, self.p, self.ws = db, p, ws
        self.all = p.level == SYSTEM or (p.level == OWNER and p.active)
        self.rows_ids: set[str] = set()
        self.stub_ids: set[str] = set()
        self.known: set[str] = set()
        self.paths: dict[str, str] = {}
        if not self.all:
            self.refresh()

    def refresh(self) -> "View":
        rows = self.db.query("select id, path, eff_level from nodes where workspace_id=?", (self.ws,))
        rows_ids, stubs = set(), set()
        for r in rows:
            if not self.p.active or self.p.level > r["eff_level"]:
                continue
            if not self.scoped or any(under(r["path"], s) for s in self.p.scopes):
                rows_ids.add(r["id"])
            elif any(under(s, r["path"]) for s in self.p.scopes):
                stubs.add(r["id"])
        self.rows_ids, self.stub_ids = rows_ids, stubs
        self.known = {r["id"] for r in rows}
        self.paths = {r["id"]: r["path"] for r in rows}
        return self

    @property
    def scoped(self) -> bool:
        """An employee bound to subtrees sees only those (a scoped manager sees the map; only their rights are bound)."""
        return self.p.level >= EMPLOYEE and bool(self.p.scopes)

    def node(self, nid: str | None) -> bool:
        return bool(nid) and (self.all or nid in self.rows_ids or nid in self.stub_ids)

    def rows(self, nid: str | None) -> bool:
        return bool(nid) and (self.all or nid in self.rows_ids)

    def stub(self, nid: str | None) -> bool:
        return not self.all and nid in self.stub_ids

    def edge(self, src: str, dst: str) -> bool:
        return self.rows(src) and self.rows(dst)

    def capture(self, cap: dict) -> bool:
        """A capture's text and audio: its author, or someone who sees the strictest node it touched."""
        if self.all:
            return True
        if cap.get("member_id") and cap["member_id"] == self.p.member_id:
            return True
        return self.p.active and self.p.level <= (cap.get("eff_level") or EMPLOYEE) and not self.scoped

    def in_scope(self, nid: str | None) -> bool:
        """Inside the branches this principal manages: owners everywhere, a manager in their scope (or everywhere)."""
        if self.p.level <= OWNER:
            return True
        if self.p.level != MANAGER or not self.p.active:
            return False
        if not self.p.scopes:
            return True
        path = self.paths.get(nid or "") or (self.db.one("select path from nodes where id=?", (nid,)) or {}).get("path")
        return bool(path) and any(under(path, s) for s in self.p.scopes)

    def fact(self, visibility: str | None) -> bool:
        return self.all or VISIBILITY.get(visibility or "all", EMPLOYEE) >= self.p.level

    def inbox(self, item: dict) -> bool:
        if self.all:
            return True
        me = self.p.member_id
        return bool(me) and (item.get("author_member_id") == me or me in (_ids(item.get("route_member_ids"))))

    def audit(self, row: dict) -> bool:
        """action_log: owners everything, managers their scope and their own, employees their own."""
        if self.all:
            return True
        if row.get("member_id") and row["member_id"] == self.p.member_id:
            return True
        return self.p.level == MANAGER and self.rows(row.get("node_id")) and self.in_scope(row.get("node_id"))

    def member(self, m: dict) -> dict:
        """Everyone sees who is in the business; contact details and logins only managers and owners."""
        if self.p.level <= MANAGER:
            return m
        return {**m, "contact": None, "user_id": None}


def _ids(v) -> list[str]:
    import json
    if not v:
        return []
    if isinstance(v, list):
        return v
    try:
        out = json.loads(v)
        return out if isinstance(out, list) else []
    except (TypeError, ValueError):
        return []


# ==================================================================== a change from another worker (decision 23)
CONTEXT_EDGES = {"located_at", "affects", "assigned_to"}  # links a note makes about itself: part of feeding data
ENTRY_AUTHOR = {"notes": "member_id", "tasks": "created_by_member", "alerts": "member_id"}
NODE_EDITS = {"title", "parent_id", "visibility", "vis_set_by", "attributes", "status", "summary", "kind"}


def classify(tbl: str, op: str, row: dict | None, cur: dict | None,
             author: str) -> list[tuple[str, str | None, bool, bool]]:
    """What a row change amounts to in the matrix: (action, node, own, assigned) for each part. Columns the brain
    works out itself (paths, roll-ups, levels) are no one's action. "refuse" marks what nobody else may write."""
    new, old = row or {}, cur or {}
    both = new or old
    if tbl == "nodes":
        if op == "D":
            return [("delete_node", old.get("id"), False, False)] if old else []
        if not old:
            return [("create_node", new.get("parent_id"), False, False)]
        out: list[tuple[str, str | None, bool, bool]] = []
        nid = old["id"]
        if new.get("title") != old.get("title") or new.get("kind") != old.get("kind"):
            out.append(("rename_node", nid, False, False))
        if new.get("parent_id") != old.get("parent_id"):
            out += [("move_node", nid, False, False), ("move_node", new.get("parent_id"), False, False)]
        if (new.get("visibility"), new.get("vis_set_by")) != (old.get("visibility"), old.get("vis_set_by")):
            out.append(("set_visibility", nid, False, False))
        if new.get("attributes") != old.get("attributes") or new.get("summary") != old.get("summary"):
            a, b = _json(new.get("attributes")), _json(old.get("attributes"))
            keys = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
            out.append(("progress" if keys <= PROGRESS_KEYS and new.get("summary") == old.get("summary")
                        else "update_attributes", nid, False, False))
        if new.get("status") != old.get("status"):
            was, now = str(old.get("status")), str(new.get("status"))
            lowering = STATUS_RANK.get(was, 2) >= STATUS_RANK["routine_due"] and STATUS_RANK.get(now, 2) < STATUS_RANK.get(was, 2)
            out.append(("lower_status" if lowering else "raise_status", nid, False, False))
        return out
    if tbl in ENTRY_AUTHOR:
        node = both.get("node_id")
        own = both.get(ENTRY_AUTHOR[tbl]) == author
        if op == "D":
            return [("undo" if own else "delete_entry", node, own, False)]
        if not old:
            out = [({"notes": "append_note", "tasks": "create_task", "alerts": "create_alert"}[tbl], node, own, False)]
            if tbl == "tasks" and new.get("assignee_member") not in (None, author):
                out.append(("assign_task", node, own, False))
            return out
        changed = {k for k in set(new) | set(old) if new.get(k) != old.get(k)} - {"synced_at"}
        if tbl == "tasks":
            out = []
            if changed & {"state", "done_at"}:
                out.append(("complete_task", node, own, old.get("assignee_member") == author))
            if changed & {"assignee_member", "due_at"}:
                out.append(("assign_task", node, own, False))
            if changed & {"title", "priority", "node_id"}:
                out.append(("edit_entry", node, own, False))
            return out
        if tbl == "alerts":
            return ([("resolve_alert", node, own, False)] if "resolved_at" in changed else []) + \
                   ([("edit_entry", node, own, False)] if changed - {"resolved_at"} else [])
        return [("edit_entry", node, own, False)] if changed else []
    if tbl == "edges":
        what = "append_note" if both.get("edge_type") in CONTEXT_EDGES else "link_nodes"
        return [(what, both.get("src_id"), False, False), (what, both.get("dst_id"), False, False)]
    if tbl in ("node_aliases", "route_corrections"):
        return [("teach_alias", both.get("node_id"), False, False)]
    if tbl == "captures":
        if op == "D":
            return [("manage_workspace", None, False, False)]
        if not old:
            return [("capture", None, True, False)] if new.get("member_id") == author else [("refuse", None, False, False)]
        return [("refuse", None, False, False)] if new.get("member_id") != old.get("member_id") else []
    if tbl == "profile_facts":
        return [("profile_fact", None, False, False)]
    if tbl in ("members", "member_scopes"):
        return [("set_role", None, False, False)]
    if tbl == "seats" or tbl == "devices" or (tbl == "invites" and old):
        return [("manage_seats", None, False, False)]
    if tbl == "invites":
        return [("invite", None, False, False)]
    if tbl == "workspaces":
        return [("manage_workspace", None, False, False)]
    if tbl == "inbox" and old and old.get("author_member_id") != author:
        return [("approve", None, False, False)]
    return []  # capture_events, action_log, notifications, an Inbox item's own author: written by the brain


def check_change(db, ws: str | None, tbl: str, op: str, row: dict | None, cur: dict | None, author: str | None,
                 cache: dict) -> tuple[str, str] | None:
    """None when the author may make this change now; else (PROPOSE or REFUSE, why). The receiving worker is the
    authority (ADR 0014, decision 23): it judges by its own, current copy of the author's role. A change with no
    author is the brain's own (or from a worker before ADR 0014): workers are trusted, roles are what can lag."""
    if not author or not ws:
        return None
    if (ws, author) not in cache:
        p = load_principal(db, ws, author)
        cache[(ws, author)] = (p, View(db, p, ws) if p else None)
    p, view = cache[(ws, author)]
    if p is None or view is None:
        return None  # a member this worker has not heard of yet: their row is on its way
    verdict: tuple[str, str] | None = None
    for action, node, own, assigned in classify(tbl, op, row, cur, author):
        if action == "refuse":
            return REFUSE, "a capture can only be written by the member who spoke it"
        if node and not view.all:
            if node not in view.known:
                view.refresh()  # a node that arrived in this batch
            if not view.rows(node) and not (op == "D" and node not in view.known):  # (a delete of what is gone here)
                return REFUSE, "not on their map"
        if tbl == "nodes" and action == "set_visibility" and p.level > OWNER:
            if (row or {}).get("visibility") == "owner" or (cur or {}).get("vis_set_by") == OWNER:
                return REFUSE, "only an owner sets or lifts an owner-only branch"
        out = p.decide(action, in_scope=view.in_scope(node) if node else True, own=own, assigned=assigned)
        if out == REFUSE:
            return REFUSE, f"a {ROLES.get(p.level, 'member')} may not {action.replace('_', ' ')}"
        if out == PROPOSE:
            verdict = (PROPOSE, f"{action.replace('_', ' ')} needs approval")
    return verdict


def rank(level: int | None) -> int:
    """Who wins two edits made at the same time to the same row: the brain, then owner, manager, employee."""
    return 4 if level in (None, SYSTEM) else 4 - level


def _json(v) -> dict:
    import json
    if isinstance(v, dict):
        return v
    try:
        out = json.loads(v) if v else {}
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}


def capabilities(p: Principal) -> dict[str, str]:
    """What the apps may offer this member, inside their own branches (the brain still decides every request)."""
    return {a: p.decide(a, in_scope=True, own=True, assigned=True) for a in MATRIX}


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
