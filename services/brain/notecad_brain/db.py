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
        else:
            import psycopg
            from psycopg.rows import dict_row
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
