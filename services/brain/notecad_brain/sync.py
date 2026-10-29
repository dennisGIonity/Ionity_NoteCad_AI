# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Multi-worker sync (Phase 5): the desktop, an Edge AI Node on the farm and Supabase keep the same map.

How it works
  1  Capture. Database triggers write every insert, update and delete on the shared tables into `sync_changes`
     (the journal), with the worker that made it and a millisecond UTC time. Triggers catch every code path, the
     owner's notes, Undo, a task ticked off, a branch renamed.
  2  Push and pull. A worker pushes the journal rows it has not sent yet to its hub and pulls what the hub has from
     everyone else. A hub is another brain (an Edge AI Node, over HTTP: /v1/sync/push and /v1/sync/pull) or a
     Postgres database (Supabase: the journal and the tables live there, with row-level security for the apps).
  3  Apply. Each incoming change is applied to its row unless this worker already has a newer change for that row
     (last writer wins, by time then worker id). Applying runs with capture switched off, so nothing echoes back,
     and the status roll-up is recomputed locally.
  4  action_log.synced_at is set when a change has reached the hub (and on arrival for changes made elsewhere), so
     "waiting to sync" on the desktop counts only this worker's unsent work.

Not synced: node_embeddings (rebuilt per worker, per model), jobs (each worker's own queue), audio files (stay
where they were recorded; the capture row travels).
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Iterable

from .common import now_iso
from .db import Database

log = logging.getLogger("notecad.sync")

SEP = "\x1f"  # joins composite primary keys into one text key, the same on SQLite and Postgres

# table -> (primary key columns, how to find its workspace)
TABLES: dict[str, tuple[list[str], str]] = {
    "workspaces": (["id"], "id"),
    "members": (["id"], "workspace_id"),
    "member_scopes": (["member_id", "node_id"], "workspace_id"),  # ADR 0014: who may do what, where
    "seats": (["id"], "workspace_id"),
    "invites": (["id"], "workspace_id"),
    "devices": (["id"], "workspace_id"),  # token hashes only, so every worker refuses a revoked phone
    "nodes": (["id"], "workspace_id"),
    "node_aliases": (["node_id", "alias"], "nodes:node_id"),
    "edges": (["id"], "workspace_id"),
    "captures": (["id"], "workspace_id"),
    "capture_events": (["capture_id", "idx"], "captures:capture_id"),
    "notes": (["id"], "workspace_id"),
    "tasks": (["id"], "workspace_id"),
    "alerts": (["id"], "workspace_id"),
    "profile_facts": (["workspace_id", "key"], "workspace_id"),
    "inbox": (["id"], "workspace_id"),
    "action_log": (["id"], "workspace_id"),
    "notifications": (["id"], "workspace_id"),
    "route_corrections": (["id"], "workspace_id"),
}
ORDER = list(TABLES)  # parents before children
IGNORED_COLUMNS = {"action_log": {"synced_at"}, "devices": {"last_seen_at"}}  # bookkeeping, not a change
# The tables supabase/migrations/0005 was generated for. 0005 has shipped and never changes: a table added later gets
# its capture trigger from the migration that adds it (0007 for the ADR 0014 tables).
PHASE6_TABLES = ["workspaces", "members", "nodes", "node_aliases", "edges", "captures", "capture_events", "notes",
                 "tasks", "alerts", "profile_facts", "inbox", "action_log", "notifications", "route_corrections"]

# ADR 0014: each journal row also says who made the change, the node the row hangs off, how visible that node was
# (its eff_level) and which version of the row the author edited (base). nc_sync_annotate fills what the insert left
# empty: a local change takes the actor of its transaction and the row's last journaled version; a change received
# from a peer keeps what the peer sent. A delete takes the node and level of the row's last journaled version.
JOURNAL_COLUMNS = [("author_member_id", "text"), ("author_level", "integer"), ("node_id", "text"), ("vis", "integer"),
                   ("base_ts", "text"), ("base_origin", "text")]
NODE_COLUMN = {"nodes": "id", "node_aliases": "node_id", "edges": "src_id", "notes": "node_id", "tasks": "node_id",
               "alerts": "node_id", "route_corrections": "node_id", "action_log": "node_id",
               "member_scopes": "node_id"}

JOURNAL_SQLITE = """
create table if not exists sync_state (key text primary key, value text);
create table if not exists sync_changes (
  seq integer primary key autoincrement, tbl text not null, pk text not null, op text not null, row text, ws text,
  origin text not null, ts text not null, origin_seq integer, via text, received_at text);
create index if not exists sync_changes_row on sync_changes(tbl, pk, ts);
create index if not exists sync_changes_origin on sync_changes(origin, origin_seq);
create index if not exists sync_changes_ws on sync_changes(ws);
create table if not exists sync_rejects (
  id integer primary key autoincrement, tbl text not null, pk text not null, origin text not null, origin_seq integer,
  ts text, error text not null, change text not null, at text not null);
create table if not exists sync_conflicts (
  id integer primary key autoincrement, tbl text not null, pk text not null, node_id text, winner text not null,
  loser text not null, at text not null);
create index if not exists sync_conflicts_node on sync_conflicts(node_id)
"""
JOURNAL_PG = """
create table if not exists sync_state (key text primary key, value text);
create table if not exists sync_changes (
  seq bigserial primary key, tbl text not null, pk text not null, op text not null, row text, ws text,
  origin text not null, ts text not null, origin_seq bigint, via text, received_at text);
create index if not exists sync_changes_row on sync_changes(tbl, pk, ts);
create index if not exists sync_changes_origin on sync_changes(origin, origin_seq);
create index if not exists sync_changes_ws on sync_changes(ws);
create table if not exists sync_rejects (
  id bigserial primary key, tbl text not null, pk text not null, origin text not null, origin_seq bigint,
  ts text, error text not null, change text not null, at text not null);
create table if not exists sync_conflicts (
  id bigserial primary key, tbl text not null, pk text not null, node_id text, winner text not null,
  loser text not null, at text not null);
create index if not exists sync_conflicts_node on sync_conflicts(node_id);
alter table sync_conflicts enable row level security
"""
# The workspace lookup for tables without workspace_id comes from TABLES, so a new table needs one edit (TABLES).
# security definer: an app writing through PostgREST under row-level security can still journal its change.
# search_path from current: the schema the function is created in (public on Supabase, a test schema in tests).
PG_FUNCTION_TEMPLATE = r"""
create or replace function nc_sync_capture() returns trigger language plpgsql security definer
set search_path from current as $f$
declare r jsonb; o jsonb; keys text[] := '{}'; c text; w text; src text;
begin
  if coalesce(current_setting('notecad.applying', true), '') = '1' then return null; end if;
  if TG_OP = 'DELETE' then r := to_jsonb(OLD); else r := to_jsonb(NEW); end if;
  if TG_OP = 'UPDATE' then
    o := to_jsonb(OLD);
    if (o - 'synced_at') = (r - 'synced_at') then return null; end if;
  end if;
  foreach c in array TG_ARGV loop keys := keys || (r->>c); end loop;
{WORKSPACE}
  src := coalesce(nullif(current_setting('notecad.worker', true), ''),
                  (select value from sync_state where key = 'worker_id'), 'cloud');
  insert into sync_changes(tbl, pk, op, row, ws, origin, ts)
  values (TG_TABLE_NAME, array_to_string(keys, chr(31)), case when TG_OP = 'DELETE' then 'D' else 'U' end,
          case when TG_OP = 'DELETE' then null else r::text end, w, src,
          to_char(clock_timestamp() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'));
  return null;
end $f$
"""


def _pg_workspace() -> str:
    lines = []
    for t, (_, how) in TABLES.items():
        if how == "workspace_id":
            continue
        kw = "if" if not lines else "elsif"
        if ":" in how:
            parent, col = how.split(":")
            lines.append(f"  {kw} TG_TABLE_NAME = '{t}' then select x.workspace_id into w from {parent} x "
                         f"where x.id = r->>'{col}';")
        else:
            lines.append(f"  {kw} TG_TABLE_NAME = '{t}' then w := r->>'{how}';")
    return "\n".join(lines) + "\n  else w := r->>'workspace_id'; end if;"


PG_FUNCTION = PG_FUNCTION_TEMPLATE.replace("{WORKSPACE}", _pg_workspace())


def _annotate_sqlite() -> str:
    node = " ".join(f"when '{t}' then json_extract(NEW.row, '$.{c}')" for t, c in NODE_COLUMN.items() if t != "nodes")
    prev = ("(select p.{col} from sync_changes p where p.tbl = NEW.tbl and p.pk = NEW.pk and p.seq < NEW.seq "
            "order by p.seq desc limit 1)")
    local = "NEW.via is null and NEW.base_ts is null"
    level = "(select n.eff_level from nodes n where n.id = json_extract(NEW.row, '$.{end}'))"
    return f"""create trigger nc_sync_annotate after insert on sync_changes begin
  update sync_changes set
    author_member_id = coalesce(NEW.author_member_id, (select value from sync_state where key = 'actor_member')),
    author_level = coalesce(NEW.author_level, (select cast(value as integer) from sync_state where key = 'actor_level')),
    base_ts = case when {local} then {prev.format(col="ts")} else NEW.base_ts end,
    base_origin = case when {local} then {prev.format(col="origin")} else NEW.base_origin end,
    node_id = coalesce(NEW.node_id, case NEW.tbl when 'nodes' then NEW.pk {node} end, {prev.format(col="node_id")})
  where seq = NEW.seq;
  update sync_changes set vis = coalesce(NEW.vis, case NEW.tbl
      when 'nodes' then json_extract(NEW.row, '$.eff_level')
      when 'captures' then json_extract(NEW.row, '$.eff_level')
      when 'capture_events' then (select c.eff_level from captures c where c.id = json_extract(NEW.row, '$.capture_id'))
      when 'edges' then min({level.format(end="src_id")}, {level.format(end="dst_id")})
      when 'profile_facts' then case json_extract(NEW.row, '$.visibility') when 'owner' then 1 when 'manager' then 2
                                when 'all' then 3 end
      else (select n.eff_level from nodes n where n.id = sync_changes.node_id) end, {prev.format(col="vis")})
  where seq = NEW.seq;
end"""


def _annotate_pg() -> str:
    node = " ".join(f"when '{t}' then r->>'{c}'" for t, c in NODE_COLUMN.items() if t != "nodes")
    level = "(select n.eff_level from nodes n where n.id = r->>'{end}')"
    return f"""create or replace function nc_sync_annotate() returns trigger language plpgsql security definer
set search_path from current as $f$
declare r jsonb; p_ts text; p_origin text; p_node text; p_vis integer;
begin
  select s.ts, s.origin, s.node_id, s.vis into p_ts, p_origin, p_node, p_vis from sync_changes s
    where s.tbl = NEW.tbl and s.pk = NEW.pk order by s.seq desc limit 1;
  if NEW.row is not null then r := NEW.row::jsonb; end if;
  NEW.author_member_id := coalesce(NEW.author_member_id, nullif(current_setting('notecad.member', true), ''));
  NEW.author_level := coalesce(NEW.author_level, nullif(current_setting('notecad.level', true), '')::integer);
  if NEW.via is null and NEW.base_ts is null then
    NEW.base_ts := p_ts;
    NEW.base_origin := p_origin;
  end if;
  NEW.node_id := coalesce(NEW.node_id, case NEW.tbl when 'nodes' then NEW.pk {node} end, p_node);
  NEW.vis := coalesce(NEW.vis, case NEW.tbl
    when 'nodes' then (r->>'eff_level')::integer
    when 'captures' then (r->>'eff_level')::integer
    when 'capture_events' then (select c.eff_level from captures c where c.id = r->>'capture_id')
    when 'edges' then least({level.format(end="src_id")}, {level.format(end="dst_id")})
    when 'profile_facts' then case r->>'visibility' when 'owner' then 1 when 'manager' then 2 when 'all' then 3 end
    else (select n.eff_level from nodes n where n.id = NEW.node_id) end, p_vis);
  return NEW;
end $f$"""


def pg_journal_upgrade() -> list[str]:
    """ADR 0014's additions to the Postgres journal: the new columns and the function that fills them."""
    return ([f"alter table sync_changes add column if not exists {c} {t}" for c, t in JOURNAL_COLUMNS]
            + [_annotate_pg(), "drop trigger if exists nc_sync_annotate on sync_changes",
               "create trigger nc_sync_annotate before insert on sync_changes for each row "
               "execute function nc_sync_annotate()"])


def pg_triggers(tables: Iterable[str] | None = None) -> list[str]:
    out = []
    for t in tables if tables is not None else TABLES:
        pk = TABLES[t][0]
        args = ", ".join(f"'{k}'" for k in pk)
        out.append(f"drop trigger if exists nc_sync_{t} on {t}")
        out.append(f"create trigger nc_sync_{t} after insert or update or delete on {t} "
                   f"for each row execute function nc_sync_capture({args})")
    return out


def _ws_sql(table: str, ref: str) -> str:
    how = TABLES[table][1]
    if ":" in how:
        parent, col = how.split(":")
        return f"(select workspace_id from {parent} where id = {ref}.{col})"
    return f"{ref}.{how}"


def install(db: Database) -> None:
    """Journal tables and capture triggers. Re-run on every start, so new columns are always captured."""
    with db._lock:
        c = db._conn
        if db.kind == "sqlite":
            for stmt in [s.strip() for s in JOURNAL_SQLITE.split(";") if s.strip()]:
                c.execute(stmt)
            have = {r[1] for r in c.execute("pragma table_info(sync_changes)").fetchall()}
            for col, typ in JOURNAL_COLUMNS:
                if col not in have:
                    c.execute(f"alter table sync_changes add column {col} {typ}")
            c.execute("drop trigger if exists nc_sync_annotate")
            c.execute(_annotate_sqlite())
            for t, (pk, _) in TABLES.items():
                cols = [r[1] for r in c.execute(f"pragma table_info({t})").fetchall()]
                watched = [x for x in cols if x not in IGNORED_COLUMNS.get(t, set())]
                guard = "(select value from sync_state where key='applying') is null"
                key = lambda ref: " || char(31) || ".join(f"cast({ref}.{k} as text)" for k in pk)  # noqa: E731, B023 - used at once, inside this loop
                obj = "json_object(" + ", ".join(f"'{x}', NEW.{x}" for x in cols) + ")"
                ins = (f"insert into sync_changes(tbl, pk, op, row, ws, origin, ts) values ('{t}', {{key}}, '{{op}}', "
                       f"{{row}}, {{ws}}, coalesce((select value from sync_state where key='worker_id'), 'local'), "
                       f"strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
                changed = " or ".join(f"OLD.{x} is not NEW.{x}" for x in watched)
                for name, sql in (
                    ("ins", f"after insert on {t} when {guard} begin "
                            + ins.format(key=key("NEW"), op="U", row=obj, ws=_ws_sql(t, "NEW")) + "; end"),
                    ("upd", f"after update on {t} when {guard} and ({changed}) begin "
                            + ins.format(key=key("NEW"), op="U", row=obj, ws=_ws_sql(t, "NEW")) + "; end"),
                    ("del", f"after delete on {t} when {guard} begin "
                            + ins.format(key=key("OLD"), op="D", row="null", ws=_ws_sql(t, "OLD")) + "; end"),
                ):
                    c.execute(f"drop trigger if exists nc_sync_{t}_{name}")
                    c.execute(f"create trigger nc_sync_{t}_{name} {sql}")
        else:
            for stmt in [s.strip() for s in JOURNAL_PG.split(";") if s.strip()]:
                c.execute(stmt)
            for stmt in pg_journal_upgrade():
                c.execute(stmt)
            c.execute(PG_FUNCTION)
            for stmt in pg_triggers():
                c.execute(stmt)


@dataclass
class Change:
    tbl: str
    pk: str
    op: str
    row: dict | None
    ws: str | None
    origin: str
    ts: str
    origin_seq: int
    seq: int = 0
    # ADR 0014: who made it (and at which level), its node and how visible it was, and the version it edited
    author_member_id: str | None = None
    author_level: int | None = None
    node_id: str | None = None
    vis: int | None = None
    base_ts: str | None = None
    base_origin: str | None = None

    def as_dict(self) -> dict:
        return {"tbl": self.tbl, "pk": self.pk, "op": self.op, "row": self.row, "ws": self.ws,
                "origin": self.origin, "ts": self.ts, "origin_seq": self.origin_seq, "seq": self.seq,
                **{k: getattr(self, k) for k, _ in JOURNAL_COLUMNS}}

    @classmethod
    def of(cls, d: dict) -> "Change":
        row = d.get("row")
        if isinstance(row, str):
            row = json.loads(row)
        lvl = d.get("author_level")
        return cls(d["tbl"], str(d["pk"]), d["op"], row, d.get("ws"), d["origin"], d["ts"],
                   int(d.get("origin_seq") or d.get("seq") or 0), int(d.get("seq") or 0),
                   d.get("author_member_id"), int(lvl) if lvl is not None else None, d.get("node_id"),
                   int(d["vis"]) if d.get("vis") is not None else None, d.get("base_ts"), d.get("base_origin"))


class Journal:
    """The change journal on one database: a brain's own, or a Postgres hub (Supabase)."""

    def __init__(self, db: Database, worker_id: str | None = None, default_worker: str | None = None):
        self.db = db
        install(db)
        self.worker_id = self._worker(worker_id, default_worker)
        if not self.state("epoch"):  # names this journal: a peer whose hub was wiped sees a new epoch
            self.set_state("epoch", uuid.uuid4().hex)
        self.epoch = self.state("epoch")
        self._cols: dict[str, list[str]] = {}

    def _worker(self, wanted: str | None, default: str | None) -> str:
        row = self.db.one("select value from sync_state where key='worker_id'")
        if wanted and (row is None or row["value"] != wanted):
            self.set_state("worker_id", wanted)
            return wanted
        if row:
            return row["value"]
        wid = default or f"{socket.gethostname().lower()}-{uuid.uuid4().hex[:6]}"
        self.set_state("worker_id", wid)
        return wid

    # ---------------------------------------------------------------- state
    def state(self, key: str, default: str | None = None) -> str | None:
        r = self.db.one("select value from sync_state where key=?", (key,))
        return r["value"] if r else default

    def set_state(self, key: str, value: str | None) -> None:
        with self.db.tx():
            self.db.execute("delete from sync_state where key=?", (key,))
            if value is not None:
                self.db.execute("insert into sync_state(key, value) values (?, ?)", (key, value))

    # ---------------------------------------------------------------- read the journal
    def _rows(self, where: str, args: list, limit: int, workspaces: list[str] | None) -> list[Change]:
        if workspaces:
            where += f" and (ws is null or ws in ({', '.join('?' for _ in workspaces)}))"
            args = args + list(workspaces)
        rows = self.db.query(f"select * from sync_changes where {where} order by seq limit ?", args + [limit])
        out = []
        for r in rows:
            ch = Change.of({**r, "origin_seq": r["origin_seq"] or r["seq"]})
            out.append(ch)
        return out

    def to_push(self, after_seq: int, peer: str | None, limit: int = 500, workspaces: list[str] | None = None,
                upto: int | None = None) -> list[Change]:
        """Everything this worker holds after the cursor (up to `upto`), except what came from the peer itself."""
        where, args = "seq > ?", [after_seq]
        if upto is not None:
            where += " and seq <= ?"
            args.append(upto)
        if peer:
            where += " and origin <> ? and (via is null or via <> ?)"
            args += [peer, peer]
        return self._rows(where, args, limit, workspaces)

    def to_serve(self, requester: str, after_seq: int, limit: int = 500, workspaces: list[str] | None = None) -> tuple[list[Change], int, bool]:
        """What a hub hands a worker that asks: everything after its cursor that it did not make itself."""
        rows = self.db.query("select seq, origin from sync_changes where seq > ? order by seq limit ?", (after_seq, limit + 1))
        more = len(rows) > limit
        rows = rows[:limit]
        last = rows[-1]["seq"] if rows else after_seq
        changes = self._rows("seq > ? and seq <= ? and origin <> ? and (via is null or via <> ?)",
                             [after_seq, last, requester, requester], limit, workspaces)
        return changes, last, more

    def baseline(self) -> int:
        """Journal the rows that existed before sync was switched on, once, so the first sync carries them too."""
        if self.state("baseline_at"):
            return 0
        n = 0
        with self.db.tx():
            for t in ORDER:
                pk_cols = TABLES[t][0]
                order = " order by depth" if t == "nodes" else ""
                for r in self.db.query(f"select * from {t}{order}"):
                    key = SEP.join(str(r[k]) for k in pk_cols)
                    if self.db.one("select 1 from sync_changes where tbl=? and pk=?", (t, key)):
                        continue
                    how = TABLES[t][1]
                    if ":" in how:
                        parent, col = how.split(":")
                        p = self.db.one(f"select workspace_id from {parent} where id=?", (r[col],))
                        ws = p["workspace_id"] if p else None
                    else:
                        ws = r[how]
                    row = {k: (bytes(v).hex() if isinstance(v, (bytes, memoryview)) else v) for k, v in r.items()}
                    self.db.execute("insert into sync_changes(tbl, pk, op, row, ws, origin, ts) values (?, ?, 'U', ?, ?, ?, ?)",
                                    (t, key, json.dumps(row, ensure_ascii=False, default=str), ws, self.worker_id,
                                     now_iso().replace("+00:00", ".000Z")))
                    n += 1
        self.set_state("baseline_at", now_iso())
        return n

    def pending(self, after_seq: int, peer: str | None) -> int:
        where, args = "seq > ? and origin = ?", [after_seq, self.worker_id]
        return self.db.one(f"select count(*) as c from sync_changes where {where}", args)["c"]

    def last_seq(self) -> int:
        return self.db.one("select coalesce(max(seq), 0) as s from sync_changes")["s"]

    # ---------------------------------------------------------------- apply what others did
    def _columns(self, table: str) -> list[str]:
        if table not in self._cols:
            if self.db.kind == "sqlite":
                self._cols[table] = [r["name"] for r in self.db.query(f"pragma table_info({table})")]
            else:
                self._cols[table] = [r["column_name"] for r in self.db.query(
                    "select column_name from information_schema.columns where table_name=? and table_schema=current_schema()",
                    (table,))]
        return self._cols[table]

    def _suppress(self, on: bool) -> None:
        if self.db.kind == "sqlite":
            self.db.execute("delete from sync_state where key='applying'")
            if on:
                self.db.execute("insert into sync_state(key, value) values ('applying', '1')")
        else:
            self.db.execute(f"select set_config('notecad.applying', '{1 if on else ''}', true)")

    def _current(self, tbl: str, pk: str) -> dict | None:
        cols = TABLES[tbl][0]
        r = self.db.one(f"select * from {tbl} where " + " and ".join(f"{k}=?" for k in cols), pk.split(SEP))
        if r is None:
            return None
        return {k: (bytes(v).hex() if isinstance(v, (bytes, memoryview)) else v) for k, v in r.items()}

    def receive(self, changes: Iterable[dict | Change], via: str | None = None, on_applied=None, check: bool = False,
                propose=None) -> dict:
        """Apply changes from another worker. Returns counts and the node ids whose status must be rolled up.

        check (ADR 0014, decision 23): judge each change by its author's current role on this worker first. One that
        is not allowed is not applied: it comes back in rejected_keys with the reason and this worker's row
        (`current`), so the sender can put its own back; propose(change, reason) makes the Inbox item for one that
        needs approval (after this transaction, so the proposal itself is journaled and travels)."""
        from .permissions import PROPOSE, check_change, rank

        applied = skipped = dup = rejected = conflicts = 0
        touched: set[str] = set()
        wss: set[str] = set()
        rejected_keys: list[dict] = []
        refusals: list[tuple[Change, str, str, dict]] = []
        cache: dict = {}
        changes = [c if isinstance(c, Change) else Change.of(c) for c in changes]
        with self.db.tx():
            # rows set aside earlier (a parent that had not arrived, a delete that met a child) get another go after
            # this batch; whatever still fails goes back into sync_rejects, once
            retry = self.db.query("select id, change from sync_rejects order by id")
            if retry:
                self.db.execute("delete from sync_rejects")
                changes = changes + [Change.of(json.loads(r["change"])) for r in retry]
            self._suppress(True)
            try:
                for ch in changes:
                    if ch.tbl not in TABLES:
                        skipped += 1
                        continue
                    if self.db.one("select 1 from sync_changes where origin=? and origin_seq=?", (ch.origin, ch.origin_seq)) \
                            or (ch.origin == self.worker_id):
                        dup += 1
                        continue
                    if check:
                        cur = self._current(ch.tbl, ch.pk)
                        verdict = check_change(self.db, ch.ws, ch.tbl, ch.op, ch.row, cur, ch.author_member_id, cache)
                        if verdict is not None:
                            rejected += 1
                            entry = {"tbl": ch.tbl, "pk": ch.pk, "outcome": verdict[0], "reason": verdict[1],
                                     "author_member_id": ch.author_member_id, "current": cur}
                            rejected_keys.append(entry)
                            refusals.append((ch, verdict[0], verdict[1], entry))
                            continue
                    latest = self.db.one("select ts, origin, author_level from sync_changes where tbl=? and pk=? "
                                         "order by ts desc, origin desc limit 1", (ch.tbl, ch.pk))
                    if latest and (latest["ts"], latest["origin"]) != (ch.ts, ch.origin):
                        concurrent = (ch.base_ts is not None
                                      and (ch.base_ts, ch.base_origin) != (latest["ts"], latest["origin"])
                                      and self.db.one("select 1 from sync_changes where tbl=? and pk=? and ts=? and origin=?",
                                                      (ch.tbl, ch.pk, ch.base_ts, ch.base_origin)) is not None)
                        if concurrent:
                            # two edits of the same version (ADR 0014, decision 24): the higher rank wins whatever the
                            # time; the other is kept in sync_conflicts and the node's history
                            theirs = (rank(ch.author_level), ch.ts, ch.origin)
                            mine = (rank(latest["author_level"]), latest["ts"], latest["origin"])
                            loser = ch.as_dict() if theirs < mine else {"tbl": ch.tbl, "pk": ch.pk, "ts": latest["ts"],
                                                                         "origin": latest["origin"],
                                                                         "row": self._current(ch.tbl, ch.pk)}
                            winner = {"ts": latest["ts"], "origin": latest["origin"]} if theirs < mine else \
                                {"ts": ch.ts, "origin": ch.origin, "author_member_id": ch.author_member_id}
                            self.db.execute("insert into sync_conflicts(tbl, pk, node_id, winner, loser, at) values (?, ?, ?, ?, ?, ?)",
                                            (ch.tbl, ch.pk, ch.node_id, json.dumps(winner, default=str),
                                             json.dumps(loser, ensure_ascii=False, default=str), now_iso()))
                            conflicts += 1
                            if theirs < mine:
                                skipped += 1
                                continue
                        elif (latest["ts"], latest["origin"]) > (ch.ts, ch.origin):
                            skipped += 1  # this worker changed the row later: last writer wins
                            continue
                    # one savepoint per change: a row that cannot be applied (a constraint, a parent that is gone)
                    # is set aside in sync_rejects instead of rolling back, and blocking, the whole batch
                    self.db.execute("savepoint nc_change")
                    try:
                        self._apply_row(ch)
                        self.db.execute("insert into sync_changes(tbl, pk, op, row, ws, origin, ts, origin_seq, via, received_at, "
                                        "author_member_id, author_level, node_id, vis, base_ts, base_origin) "
                                        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                        (ch.tbl, ch.pk, ch.op, json.dumps(ch.row, ensure_ascii=False) if ch.row is not None else None,
                                         ch.ws, ch.origin, ch.ts, ch.origin_seq, via, now_iso(), ch.author_member_id,
                                         ch.author_level, ch.node_id, ch.vis, ch.base_ts, ch.base_origin))
                        self.db.execute("release savepoint nc_change")
                    except Exception as ex:  # noqa: BLE001 - any database error on this one row
                        self.db.execute("rollback to savepoint nc_change")
                        self.db.execute("release savepoint nc_change")
                        if not self.db.one("select 1 from sync_rejects where origin=? and origin_seq=?", (ch.origin, ch.origin_seq)):
                            self.db.execute("insert into sync_rejects(tbl, pk, origin, origin_seq, ts, error, change, at) "
                                            "values (?, ?, ?, ?, ?, ?, ?, ?)",
                                            (ch.tbl, ch.pk, ch.origin, ch.origin_seq, ch.ts, f"{type(ex).__name__}: {ex}"[:500],
                                             json.dumps(ch.as_dict(), ensure_ascii=False, default=str), now_iso()))
                        rejected += 1
                        rejected_keys.append({"tbl": ch.tbl, "pk": ch.pk})
                        continue
                    applied += 1
                    if ch.ws:
                        wss.add(ch.ws)
                    r = ch.row or {}
                    if ch.tbl == "nodes":
                        touched.add(ch.pk)
                    elif r.get("node_id") and ch.tbl in ("notes", "tasks", "alerts"):
                        touched.add(r["node_id"])
                if on_applied is not None:
                    on_applied(touched)  # status roll-up, still with capture off: derived, so no echo
            finally:
                self._suppress(False)
        for ch, outcome, reason, entry in refusals:  # journaled, so one proposal travels to every worker
            if outcome == PROPOSE and propose is not None:
                entry["proposal_id"] = propose(ch, reason)
        return {"applied": applied, "skipped": skipped, "duplicates": dup, "rejected": rejected,
                "conflicts": conflicts, "rejected_keys": rejected_keys, "touched": sorted(touched),
                "workspaces": sorted(wss)}

    def restore(self, tbl: str, pk: str, row: dict | None) -> None:
        """Put back a row the hub refused (ADR 0014): written as an ordinary local change, so the journal moves on
        from the refused version and the hub gets this one."""
        if tbl not in TABLES:
            return
        cols = TABLES[tbl][0]
        with self.db.tx():
            if row is None:
                self.db.execute(f"delete from {tbl} where " + " and ".join(f"{k}=?" for k in cols), pk.split(SEP))
            else:
                self._apply_row(Change(tbl, pk, "U", dict(row), None, self.worker_id, now_iso(), 0))

    def rejournal(self, tbl: str, pk: str) -> None:
        """This worker refused a change it pulled: journal its own row again, so the hub (and everyone after it)
        converges on the version this worker holds."""
        cur = self._current(tbl, pk)
        how = TABLES[tbl][1]
        ws = None
        if cur is not None:
            if ":" in how:
                parent, col = how.split(":")
                p = self.db.one(f"select workspace_id from {parent} where id=?", (cur[col],))
                ws = p["workspace_id"] if p else None
            else:
                ws = cur[how]
        self.db.execute("insert into sync_changes(tbl, pk, op, row, ws, origin, ts) values (?, ?, ?, ?, ?, ?, ?)",
                        (tbl, pk, "U" if cur is not None else "D",
                         json.dumps(cur, ensure_ascii=False, default=str) if cur is not None else None, ws,
                         self.worker_id, now_iso().replace("+00:00", ".000Z")))

    def apply_proposal(self, change: dict, principal) -> dict:
        """An approved sync proposal: the row as it was proposed, written now by the approver."""
        ch = Change.of(change)
        if ch.tbl not in TABLES:
            raise KeyError(ch.tbl)
        acting = (principal.member_id, principal.level) if principal.level else (None, None)
        with self.db.tx(), self.db.acting(*acting):
            if ch.op == "D":
                cols = TABLES[ch.tbl][0]
                self.db.execute(f"delete from {ch.tbl} where " + " and ".join(f"{k}=?" for k in cols), ch.pk.split(SEP))
            else:
                self._apply_row(ch)
        node = ch.pk if ch.tbl == "nodes" else (ch.row or {}).get("node_id")
        return {"status": "applied", "nodes": [node] if node else []}

    def _apply_row(self, ch: Change) -> None:
        pk_cols = TABLES[ch.tbl][0]
        keys = ch.pk.split(SEP)
        if ch.op == "D":
            self.db.execute(f"delete from {ch.tbl} where " + " and ".join(f"{k}=?" for k in pk_cols), keys)
            return
        if ch.tbl == "edges":  # two workers linked the same pair: both keep the edge with the smaller id
            other = self.db.one("select id from edges where src_id=? and dst_id=? and edge_type=? and id<>?",
                                (ch.row.get("src_id"), ch.row.get("dst_id"), ch.row.get("edge_type"), ch.pk))
            if other and other["id"] < ch.pk:
                return
            if other:
                self.db.execute("delete from edges where id=?", (other["id"],))
        cols = [c for c in self._columns(ch.tbl) if c in (ch.row or {})]
        if ch.tbl == "action_log":  # it has reached another worker, so it is synced wherever it lands
            ch.row = {**(ch.row or {}), "synced_at": (ch.row or {}).get("synced_at") or now_iso()}
            if "synced_at" not in cols and "synced_at" in self._columns("action_log"):
                cols.append("synced_at")
        vals = [ch.row[c] if not isinstance(ch.row[c], (dict, list)) else json.dumps(ch.row[c]) for c in cols]
        upd = [c for c in cols if c not in pk_cols]
        sql = (f"insert into {ch.tbl} ({', '.join(cols)}) values ({', '.join('?' for _ in cols)}) "
               f"on conflict ({', '.join(pk_cols)}) do " +
               (f"update set {', '.join(f'{c}=excluded.{c}' for c in upd)}" if upd else "nothing"))
        self.db.execute(sql, vals)

    def ack(self, requester: str, cursor: int, workspaces: list[str] | None = None) -> int:
        """A worker has applied everything up to `cursor` that this journal served it: those action_log rows now
        exist on another worker, so they are synced here too (the hub's own notes included). Only rows after the
        worker's last ack and inside the workspaces it pulls are looked at, so the cost does not grow with history."""
        key = f"ack:{requester}" + (f":{','.join(sorted(workspaces))}" if workspaces else "")
        since = int(self.state(key, "0") or 0)
        if cursor <= since:
            return 0
        where, args = "tbl='action_log' and op='U' and seq > ? and seq <= ? and origin <> ? and (via is null or via <> ?)", \
            [since, cursor, requester, requester]
        if workspaces:
            where += f" and ws in ({', '.join('?' for _ in workspaces)})"
            args += list(workspaces)
        ids = [r["pk"] for r in self.db.query(f"select pk from sync_changes where {where}", args)]
        self.mark_synced(ids)
        self.set_state(key, str(cursor))
        return len(ids)

    def mark_synced(self, action_ids: list[str]) -> None:
        if not action_ids:
            return
        with self.db.tx():
            self._suppress(True)
            try:
                for i in range(0, len(action_ids), 400):
                    part = action_ids[i:i + 400]
                    self.db.execute(f"update action_log set synced_at=? where synced_at is null and id in "
                                    f"({', '.join('?' for _ in part)})", [now_iso()] + part)
            finally:
                self._suppress(False)


# ==================================================================== peers
class HttpPeer:
    """Another brain: the Edge AI Node on the farm, or a desktop acting as hub."""

    def __init__(self, base_url: str, token: str | None = None, transport=None, timeout: float = 60):
        import httpx
        self.url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.url, timeout=timeout, transport=transport,
                                   headers={"Authorization": f"Bearer {token}"} if token else {})
        self.id: str | None = None

    def hello(self) -> str:
        r = self.client.get("/api/v1/sync/status")
        r.raise_for_status()
        j = r.json()
        self.id, self.epoch, self.last_seq = j["worker_id"], j.get("epoch"), j.get("journal_seq")
        return str(self.id)

    def ack(self, worker: str, cursor: int, workspaces: list[str] | None = None) -> None:
        r = self.client.post("/api/v1/sync/ack", json={"worker": worker, "cursor": cursor, "workspaces": workspaces})
        if r.status_code != 404:  # an older hub without /sync/ack
            r.raise_for_status()

    def close(self) -> None:
        self.client.close()

    def push(self, worker: str, changes: list[Change]) -> dict:
        r = self.client.post("/api/v1/sync/push", json={"worker": worker, "changes": [c.as_dict() for c in changes]})
        r.raise_for_status()
        return r.json()

    def pull(self, worker: str, since: int, limit: int, workspaces: list[str] | None) -> dict:
        r = self.client.get("/api/v1/sync/pull", params={"worker": worker, "since": since, "limit": limit,
                                                         **({"workspaces": ",".join(workspaces)} if workspaces else {})})
        r.raise_for_status()
        return r.json()


class PostgresHub:
    """Supabase (or any Postgres): the hub is the database itself. The apps read it through row-level security;
    workers push and pull through its journal."""

    WINDOW = 64  # Postgres hands out seq at insert but shows rows at commit: re-read a little behind the cursor

    def __init__(self, url: str):
        self.journal = Journal(Database(url), default_worker="supabase")
        self.id = self.journal.worker_id
        self.epoch = self.journal.epoch
        self.last_seq = None
        self.url = url.split("@")[-1]

    def hello(self) -> str:
        self.last_seq = self.journal.last_seq()
        return self.id

    def ack(self, worker: str, cursor: int, workspaces: list[str] | None = None) -> None:
        # behind the re-read window a lower seq may still commit: acknowledge only what is surely settled
        self.journal.ack(worker, max(0, cursor - self.WINDOW), workspaces)

    def close(self) -> None:
        self.journal.db.close()

    def push(self, worker: str, changes: list[Change]) -> dict:
        # the pushing worker judges for the hub, against the hub's own members (ADR 0014, decision 23)
        res = self.journal.receive(changes, via=worker, check=True,
                                   propose=lambda ch, why: sync_proposal(self.journal.db, ch, why))
        return {k: v for k, v in res.items() if k != "touched"}

    def pull(self, worker: str, since: int, limit: int, workspaces: list[str] | None) -> dict:
        # a row with a lower seq that committed after the last pull is picked up now; repeats are dropped as duplicates
        ch, cursor, more = self.journal.to_serve(worker, max(0, since - self.WINDOW), limit, workspaces)
        return {"changes": [c.as_dict() for c in ch], "cursor": max(cursor, since), "more": more, "hub": self.id}


def sync_proposal(db: Database, ch: Change, reason: str) -> str | None:
    """A change another worker made that its author may no longer make (ADR 0014): one Inbox item for the owners,
    however many workers refuse it, journaled so it reaches every worker."""
    from .common import new_id
    if not ch.ws:
        return None
    key = f"{ch.origin}:{ch.origin_seq}"
    seen = db.one("select id from inbox where workspace_id=? and kind='sync' and proposal like ?", (ch.ws, f"%{key}%"))
    if seen:
        return seen["id"]
    owners = [r["id"] for r in db.query("select id from members where workspace_id=? and level=1 and status='active'",
                                        (ch.ws,))]
    who = db.one("select display_name from members where id=?", (ch.author_member_id,)) if ch.author_member_id else None
    iid = new_id()
    db.insert("inbox", {"id": iid, "workspace_id": ch.ws, "capture_id": None, "event_idx": None,
                        "question": f"{(who or {}).get('display_name', 'Someone')} changed {ch.tbl} on another device, "
                                    f"and {reason}"[:300],
                        "options": [], "event_text": None, "proposal": {"change": ch.as_dict(), "change_key": key},
                        "state": "open", "resolution": None, "created_at": now_iso(), "resolved_at": None,
                        "kind": "sync", "author_member_id": ch.author_member_id, "route_member_ids": owners,
                        "approver_level": 1})
    return iid


def make_peer(target: str, token: str | None = None, transport=None):
    if target.startswith(("postgres://", "postgresql://")):
        return PostgresHub(target)
    return HttpPeer(target, token, transport)


# ==================================================================== the engine
@dataclass
class SyncStats:
    last_sync_at: str | None = None
    last_error: str | None = None
    pushed: int = 0
    pulled: int = 0
    runs: int = 0
    history: list = field(default_factory=list)


class SyncEngine:
    def __init__(self, brain, target: str | None, *, token: str | None = None, interval: float = 15.0,
                 workspaces: list[str] | None = None, transport=None, batch: int = 500):
        self.brain = brain
        self.journal: Journal = brain.journal
        self.target = target
        self.token = token
        self.transport = transport
        self.interval = interval
        self.workspaces = workspaces or None
        self.batch = batch
        self.peer = None
        self.stats = SyncStats(last_sync_at=self.journal.state("last_sync_at"), last_error=self.journal.state("last_error"))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.failures = 0

    def _peer(self):
        if self.peer is None:
            self.peer = make_peer(self.target or "", self.token, self.transport)
            self.peer.hello()
            self._check_epoch(self.peer)
        return self.peer

    def _check_epoch(self, peer) -> None:
        """A hub that was wiped and started again has a new journal: send everything again, read from its start."""
        epoch = getattr(peer, "epoch", None)
        known = self.journal.state(f"epoch:{peer.id}")
        hub_last = getattr(peer, "last_seq", None)
        reset = (epoch and known and epoch != known) or (hub_last is not None and self._cursor("pull") > hub_last)
        if reset:
            log.warning("sync hub %s has a new journal: cursors reset", peer.id)
            self.journal.set_state(f"push:{peer.id}", "0")
            self.journal.set_state(f"pull:{peer.id}", "0")
        if epoch:
            self.journal.set_state(f"epoch:{peer.id}", epoch)

    def _drop_peer(self) -> None:
        """After an error the next run connects again (a dropped Supabase connection never comes back by itself)."""
        if self.peer is not None:
            try:
                self.peer.close()
            except Exception:  # noqa: BLE001 - already broken
                pass
        self.peer = None

    def _cursor(self, kind: str) -> int:
        return int(self.journal.state(f"{kind}:{self.peer.id}", "0") or 0)

    def run_once(self) -> dict:
        """Push this worker's changes, pull everyone else's, then roll up status and tell the open apps."""
        if not self.target:
            return {"ok": False, "error": "no sync target set (NC_BRAIN_SYNC_TARGET)"}
        with self._lock:
            t0 = time.perf_counter()
            pushed = pulled = 0
            touched: set[str] = set()
            wss: set[str] = set()
            try:
                peer = self._peer()
                # push: read the journal's end first, so a note committed while this runs waits for the next run
                # instead of being stepped over by the cursor
                cur = self._cursor("push")
                top = self.journal.last_seq()
                while True:
                    batch = self.journal.to_push(cur, peer.id, self.batch, self.workspaces, upto=top)
                    if not batch:
                        if top > cur:  # only rows that came from the peer (or other workspaces) are left
                            self.journal.set_state(f"push:{peer.id}", str(top))
                        break
                    got = peer.push(self.journal.worker_id, batch) or {}
                    refused = {k["pk"] for k in got.get("rejected_keys", []) if k.get("tbl") == "action_log"}
                    for k in got.get("rejected_keys", []):
                        if k.get("outcome"):  # not allowed at the hub (ADR 0014): put the hub's row back here
                            self.journal.restore(k["tbl"], k["pk"], k.get("current"))
                            self.brain.sync_refused(k)
                    cur = batch[-1].seq
                    with self.journal.db.tx():  # cursor and synced_at move together; rows the hub set aside stay unsynced
                        self.journal.set_state(f"push:{peer.id}", str(cur))
                        self.journal.mark_synced([c.pk for c in batch if c.tbl == "action_log" and c.op == "U" and c.pk not in refused])
                    pushed += len(batch)
                # pull
                cur = self._cursor("pull")
                while True:
                    res = peer.pull(self.journal.worker_id, cur, self.batch, self.workspaces)
                    got = self.journal.receive(res.get("changes", []), via=peer.id,
                                               on_applied=lambda ids: self.brain.graph.rollup(sorted(ids)), check=True,
                                               propose=self.brain.sync_proposal)
                    for k in got.get("rejected_keys", []):
                        if k.get("outcome"):  # the hub took a change this worker does not allow: send ours back
                            self.journal.rejournal(k["tbl"], k["pk"])
                    pulled += got["applied"]
                    touched |= set(got["touched"])
                    wss |= set(got["workspaces"])
                    cur = int(res.get("cursor", cur))
                    self.journal.set_state(f"pull:{peer.id}", str(cur))
                    if not res.get("more"):
                        break
                peer.ack(self.journal.worker_id, cur, self.workspaces)  # the hub marks what this worker now has
                self.stats.last_error = None
                self.failures = 0
                self.journal.set_state("last_error", None)
            except Exception as ex:
                self.stats.last_error = f"{type(ex).__name__}: {ex}"[:300]
                self.journal.set_state("last_error", self.stats.last_error)
                self.failures += 1
                log.warning("sync with %s failed (%d in a row): %s", self._safe_target(), self.failures,
                            self.stats.last_error)
                self._drop_peer()
                return {"ok": False, "error": self.stats.last_error, "pushed": pushed, "pulled": pulled}
            finally:
                self.stats.runs += 1
            self.stats.last_sync_at = now_iso()
            self.journal.set_state("last_sync_at", self.stats.last_sync_at)
            self.stats.pushed += pushed
            self.stats.pulled += pulled
            if pulled:
                self.brain.after_sync({"applied": pulled, "touched": sorted(touched), "workspaces": sorted(wss)},
                                      self.peer.id)
            res = {"ok": True, "pushed": pushed, "pulled": pulled, "peer": self.peer.id,
                   "ms": round((time.perf_counter() - t0) * 1000)}
            self.stats.history = (self.stats.history + [{"at": self.stats.last_sync_at, **res}])[-20:]
            return res

    def status(self) -> dict:
        peer_id = getattr(self.peer, "id", None)
        push_cur = int(self.journal.state(f"push:{peer_id}", "0") or 0) if peer_id else 0
        rejects = self.journal.db.one("select count(*) as c from sync_rejects")["c"]
        return {"worker_id": self.journal.worker_id, "epoch": self.journal.epoch, "target": self._safe_target(),
                "peer": peer_id, "rejected": rejects,
                "interval_s": self.interval if self.target else None, "workspaces": self.workspaces,
                "pending_changes": self.journal.pending(push_cur, peer_id) if self.target else None,
                "journal_seq": self.journal.last_seq(), "last_sync_at": self.stats.last_sync_at,
                "last_error": self.stats.last_error, "pushed": self.stats.pushed, "pulled": self.stats.pulled,
                "history": self.stats.history[-5:]}

    def _safe_target(self) -> str | None:
        if not self.target:
            return None
        if self.target.startswith(("postgres://", "postgresql://")):
            return "postgres://…@" + self.target.split("@")[-1].split("?")[0]  # never show the password
        return self.target

    def next_wait(self) -> float:
        """The interval while sync works; after failures it doubles, up to 5 minutes, with a little jitter."""
        if not self.failures:
            return self.interval
        import random
        return min(self.interval * 2 ** self.failures, 300.0) * random.uniform(0.85, 1.0)

    def loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - run_once reports its own errors; keep the loop alive
                log.exception("sync loop")
            self._stop.wait(self.next_wait())

    def start(self) -> None:
        if self.target:
            threading.Thread(target=self.loop, name="notecad-sync", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
