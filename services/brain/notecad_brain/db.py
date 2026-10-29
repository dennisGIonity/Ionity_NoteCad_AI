# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""One small database layer for two engines.

  sqlite:///path/notecad.db      desktop, Edge AI Node, tests (no server needed)
  postgresql://user@host/db      Supabase / any Postgres 15+ (supabase/migrations adds RLS on top)

The schema uses portable types (TEXT ids, ISO-8601 UTC timestamps, JSON as TEXT) so the brain runs the same
SQL on both. Placeholders are written as ? and translated for Postgres.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

SCHEMA = """
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
  node_id text primary key references nodes(id) on delete cascade, model text not null, vec {BLOB} not null);
create table if not exists edges (
  id text primary key, workspace_id text not null references workspaces(id) on delete cascade,
  src_id text not null references nodes(id) on delete cascade, dst_id text not null references nodes(id) on delete cascade,
  edge_type text not null, weight real not null default 1, created_by text not null default 'user',
  unique (src_id, dst_id, edge_type));
create table if not exists captures (
  id text primary key, workspace_id text not null references workspaces(id) on delete cascade,
  user_id text, source text not null default 'phone', audio_path text, sha256 text, recorded_at text not null,
  geo text, lang_hint text, state text not null default 'queued', text text, transcript text, lang text,
  router text, error text, anchor_node_id text, created_at text not null, updated_at text not null);
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
create index if not exists jobs_state on jobs(state, run_after);
"""

# Columns added after a table first shipped: (table, column, type). migrate() adds them to older databases.
ADDED_COLUMNS = [
    ("captures", "anchor_node_id", "text"),  # Phase 2: the node the owner was looking at while recording
    ("action_log", "synced_at", "text"),  # Phase 3: set when a change has reached the other workers (Phase 4 sync)
]


# Numbered, forward-only schema changes from Phase 6 on: (version, name, statements). The same numbers are the
# files in supabase/migrations (0006_*.sql ...), so a SQLite brain and Supabase move together. Each runs once, in its
# own transaction, and is recorded in schema_migrations. Never edit a shipped one: add the next number.
MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (6, "hot query indexes", [
        "create index if not exists tasks_node on tasks(node_id, state)",            # roll-up, mind map, history
        "create index if not exists alerts_node on alerts(node_id, resolved_at)",    # roll-up
        "create index if not exists nodes_parent on nodes(parent_id)",               # children, roll-up
        "create index if not exists edges_dst on edges(dst_id)",                     # retrieval 1-hop
        "create index if not exists inbox_capture on inbox(capture_id)",             # undo, resolve
        "create index if not exists action_log_unsynced on action_log(workspace_id, synced_at)",  # sync status
    ]),
    # ADR 0014. Written so that it can run twice (a Supabase hub that already has 0007): "add column if not exists"
    # is native on Postgres and checked by migrate() on SQLite; the updates only match rows not yet mapped.
    (7, "roles, seats and permission-aware sync", [
        # members: a numeric level (1 owner, 2 manager, 3 employee; 0 is the brain itself), read-only, status, seat
        "alter table members add column if not exists level integer not null default 3",
        "alter table members add column if not exists read_only integer not null default 0",
        "alter table members add column if not exists status text not null default 'active'",
        "alter table members add column if not exists seat_id text",
        "update members set level=1 where role='owner'",
        # an editor with a login becomes a manager; people added only for delegation become employees (ADR 0014, q1)
        "update members set role='manager', level=2 where role='editor' and coalesce(user_id, '')<>''",
        "update members set role='employee', level=3 where role='editor'",
        "update members set role='employee', level=3, read_only=1 where role='viewer'",
        # restricted branches: what was set on the node, by which level, and its effect after the ancestors
        "alter table nodes add column if not exists visibility text not null default 'all'",
        "alter table nodes add column if not exists vis_set_by integer",
        "alter table nodes add column if not exists eff_level integer not null default 3",
        "alter table nodes add column if not exists rollup_tiers text",  # roll-ups as levels 2 and 3 see them
        "create index if not exists nodes_ws_eff on nodes(workspace_id, eff_level)",
        # who wrote what; a capture is as restricted as the strictest node it touched
        "alter table captures add column if not exists member_id text",
        "alter table captures add column if not exists eff_level integer not null default 3",
        "alter table notes add column if not exists member_id text",
        "alter table tasks add column if not exists created_by_member text",
        "alter table alerts add column if not exists member_id text",
        "alter table profile_facts add column if not exists visibility text not null default 'all'",
        # proposals wait in the Inbox for a manager or an owner
        "alter table inbox add column if not exists kind text not null default 'place'",
        "alter table inbox add column if not exists author_member_id text",
        "alter table inbox add column if not exists approver_level integer",
        "alter table inbox add column if not exists route_member_ids text",
        "alter table inbox add column if not exists decided_by text",
        # the audit: who, at which level, approved by whom, on which node
        "alter table action_log add column if not exists member_id text",
        "alter table action_log add column if not exists member_level integer",
        "alter table action_log add column if not exists approved_by text",
        "alter table action_log add column if not exists node_id text",
        "create index if not exists action_log_member on action_log(workspace_id, member_id)",
        # subtree roots a member is bound to, seats, one-time invites and per-device tokens (stored as hashes)
        "create table if not exists member_scopes (\n"
        "  workspace_id text not null references workspaces(id) on delete cascade, member_id text not null,\n"
        "  node_id text not null, created_at text not null, primary key (member_id, node_id))",
        "create index if not exists member_scopes_ws on member_scopes(workspace_id, member_id)",
        "create table if not exists seats (\n"
        "  id text primary key, workspace_id text not null references workspaces(id) on delete cascade,\n"
        "  role_level integer not null, status text not null default 'available', assigned_member_id text,\n"
        "  purchased_at text not null, expires_at text, external_ref text, ledger text not null default 'local')",
        "create index if not exists seats_ws on seats(workspace_id, status)",
        "create table if not exists invites (\n"
        "  id text primary key, workspace_id text not null references workspaces(id) on delete cascade,\n"
        "  seat_id text not null, code_hash text not null, created_by text, profile text not null default '{}',\n"
        "  created_at text not null, expires_at text not null, used_at text, used_by_device text, revoked_at text)",
        "create unique index if not exists invites_code on invites(code_hash)",
        "create table if not exists devices (\n"
        "  id text primary key, workspace_id text not null references workspaces(id) on delete cascade,\n"
        "  member_id text not null, name text not null, platform text, token_hash text not null,\n"
        "  created_at text not null, last_seen_at text, revoked_at text, wipe_acked_at text)",
        "create unique index if not exists devices_token on devices(token_hash)",
        "create index if not exists devices_member on devices(member_id)",
    ]),
    # ADR 0014 step 4: what the joining, the device copy and the Inbox routing look up (Supabase 0008 also corrects
    # the Inbox policy of 0007)
    (8, "invites, devices and Inbox lookups", [
        "create index if not exists inbox_ws_kind on inbox(workspace_id, state, kind)",
        "create index if not exists invites_ws on invites(workspace_id, created_at)",
        "create index if not exists devices_ws on devices(workspace_id, member_id)",
        "create index if not exists seats_member on seats(assigned_member_id)",
    ]),
]

_ADD_COLUMN = re.compile(r"alter table (\w+) add column if not exists (\w+) (.+)", re.S)


class Database:
    def __init__(self, url: str):
        self.url = url
        self.kind = "postgres" if url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self._local = threading.local()
        self._lock = threading.RLock()  # sqlite: one writer at a time
        if self.kind == "sqlite":
            path = url.removeprefix("sqlite:///").removeprefix("sqlite://") or ":memory:"
            self._sqlite_path = path
            self._shared = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._shared.row_factory = sqlite3.Row
            self._shared.execute("pragma foreign_keys=on")
            if path != ":memory:":
                self._shared.execute("pragma journal_mode=wal")
                self._shared.execute("pragma synchronous=normal")  # with WAL: durable at checkpoints, far fewer fsyncs
                self._shared.execute("pragma busy_timeout=5000")
        else:
            import psycopg  # pyright: ignore[reportMissingImports]  (optional: pip install .[postgres])
            from psycopg.rows import dict_row  # pyright: ignore[reportMissingImports]
            self._pg = psycopg.connect(url, autocommit=True, row_factory=dict_row)
        self.migrate()

    # ---------------------------------------------------------------- plumbing
    def _sql(self, sql: str) -> str:
        if self.kind == "postgres":
            return re.sub(r"\?", "%s", sql)
        return sql

    @property
    def _conn(self):
        return self._shared if self.kind == "sqlite" else self._pg

    def migrate(self) -> None:
        ddl = SCHEMA.replace("{BLOB}", "blob" if self.kind == "sqlite" else "bytea")
        for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
            self._conn.execute(stmt)
        for table, column, typ in ADDED_COLUMNS:
            if self.kind == "postgres":
                self._conn.execute(f"alter table {table} add column if not exists {column} {typ}")
            elif column not in {r[1] for r in self._conn.execute(f"pragma table_info({table})").fetchall()}:
                self._conn.execute(f"alter table {table} add column {column} {typ}")
        self._conn.execute("create table if not exists schema_migrations (version integer primary key, name text not null, "
                           "applied_at text not null)")
        done = {r[0] if isinstance(r, tuple) else r["version"] for r in
                self._conn.execute("select version from schema_migrations").fetchall()}
        for version, name, statements in MIGRATIONS:
            if version in done:
                continue
            with self.tx():
                for stmt in statements:
                    self.run_migration_statement(stmt)
                self.execute("insert into schema_migrations(version, name, applied_at) values (?, ?, ?)",
                             (version, name, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        from .permissions import install_guards
        install_guards(self)

    def run_migration_statement(self, stmt: str) -> None:
        """One statement of MIGRATIONS, written for Postgres. SQLite has no "add column if not exists": checked here."""
        m = _ADD_COLUMN.fullmatch(stmt) if self.kind == "sqlite" else None
        if m:
            if m[2] in {r["name"] for r in self.query(f"pragma table_info({m[1]})")}:
                return
            stmt = f"alter table {m[1]} add column {m[2]} {m[3]}"
        self.execute(stmt)

    @contextmanager
    def tx(self) -> Iterator["Database"]:
        """One transaction. Nested calls join the outer one."""
        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth += 1
            try:
                yield self
            finally:
                self._local.depth -= 1
            return
        self._lock.acquire()
        self._local.depth = 1
        try:
            self._conn.execute("begin")
            try:
                yield self
                self._conn.execute("commit")
            except BaseException:
                self._conn.execute("rollback")
                raise
        finally:
            self._local.depth = 0
            self._lock.release()

    @contextmanager
    def acting(self, member_id: str | None, level: int | None) -> Iterator[None]:
        """Inside tx(): the member this transaction's writes are journaled for (ADR 0014, sync.nc_sync_annotate).
        SQLite: rows in sync_state, removed before the commit; Postgres: settings local to the transaction."""
        if member_id is None and level is None:
            yield
            return
        if self.kind == "postgres":
            self.execute("select set_config('notecad.member', ?, true), set_config('notecad.level', ?, true)",
                         (member_id or "", "" if level is None else str(level)))
            yield
            return
        keys = [(k, v) for k, v in (("actor_member", member_id), ("actor_level", level)) if v is not None]
        self.execute("delete from sync_state where key in ('actor_member', 'actor_level')")
        for k, v in keys:
            self.execute("insert into sync_state(key, value) values (?, ?)", (k, str(v)))
        try:
            yield
        finally:
            self.execute("delete from sync_state where key in ('actor_member', 'actor_level')")

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        with self._lock:
            cur = self._conn.execute(self._sql(sql), tuple(params))
            return cur.rowcount

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(self._sql(sql), tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def insert(self, table: str, row: dict[str, Any]) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self.execute(f"insert into {table} ({cols}) values ({marks})", [_dump(v) for v in row.values()])

    def update(self, table: str, key: dict[str, Any], fields: dict[str, Any]) -> int:
        sets = ", ".join(f"{k}=?" for k in fields)
        where = " and ".join(f"{k}=?" for k in key)
        return self.execute(f"update {table} set {sets} where {where}",
                            [_dump(v) for v in fields.values()] + list(key.values()))

    def close(self) -> None:
        self._conn.close()


def _dump(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def loads(v: str | None, default: Any = None) -> Any:
    if v is None or v == "":
        return default
    try:
        return json.loads(v)
    except (TypeError, json.JSONDecodeError):
        return default
