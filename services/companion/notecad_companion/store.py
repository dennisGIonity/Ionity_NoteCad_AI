# Ionity Business Mind Map (IBMM) - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""The owner model on disk: one SQLite file per owner, kept on the owner's device or Edge node."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .embed import from_blob, to_blob

SCHEMA = """
create table if not exists meta (key text primary key, value text not null);
create table if not exists facts (
  key text primary key, value text not null, confidence real not null, source text not null,
  updated_at real not null, history text not null default '[]');
create table if not exists memories (
  id text primary key, text text not null, kind text not null, importance real not null,
  embedding blob, embed_model text, source text not null, created_at real not null,
  last_access real not null, access_count integer not null default 0);
create index if not exists memories_created on memories(created_at);
create table if not exists arms (
  dim text not null, option text not null, alpha real not null, beta real not null,
  primary key (dim, option));
create table if not exists style (key text primary key, value real not null, n integer not null default 0);
create table if not exists vocab (term text primary key, count real not null, last_seen real not null);
create table if not exists rhythm (slot integer primary key, count real not null);
create table if not exists rhythm_terms (slot integer not null, term text not null, count real not null,
  primary key (slot, term));
create table if not exists interactions (
  id text primary key, created_at real not null, user_text text not null, reply text not null,
  style text not null, model text not null, persona_hash text, feedback integer, edited_reply text,
  comment text);
create index if not exists interactions_created on interactions(created_at);
create table if not exists adapters (
  version text primary key, path text not null, base_model text not null, created_at real not null,
  n_examples integer not null, active integer not null default 0);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.db.execute("begin")
        try:
            yield self.db
            self.db.execute("commit")
        except Exception:
            self.db.execute("rollback")
            raise

    # ---------------------------------------------------------------- meta
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        r = self.db.execute("select value from meta where key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("insert into meta values(?,?) on conflict(key) do update set value=excluded.value",
                        (key, value))

    # ---------------------------------------------------------------- facts
    def get_fact(self, key: str) -> dict | None:
        r = self.db.execute("select * from facts where key=?", (key,)).fetchone()
        return None if r is None else {**dict(r), "value": json.loads(r["value"]),
                                       "history": json.loads(r["history"])}

    def all_facts(self, min_conf: float = 0.0) -> list[dict]:
        rows = self.db.execute("select * from facts where confidence>=? order by key", (min_conf,)).fetchall()
        return [{**dict(r), "value": json.loads(r["value"]), "history": json.loads(r["history"])} for r in rows]

    def put_fact(self, key: str, value: Any, confidence: float, source: str, history: list) -> None:
        self.db.execute(
            "insert into facts values(?,?,?,?,?,?) on conflict(key) do update set value=excluded.value,"
            " confidence=excluded.confidence, source=excluded.source, updated_at=excluded.updated_at,"
            " history=excluded.history",
            (key, json.dumps(value, ensure_ascii=False), confidence, source, time.time(), json.dumps(history[-10:])),
        )

    def delete_fact(self, key: str) -> bool:
        return self.db.execute("delete from facts where key=?", (key,)).rowcount > 0

    # ---------------------------------------------------------------- memories
    def add_memory(self, text: str, kind: str, importance: float, embedding: np.ndarray | None,
                   embed_model: str, source: str, created_at: float | None = None) -> str:
        mid = str(uuid.uuid4())
        now = created_at or time.time()
        self.db.execute("insert into memories values(?,?,?,?,?,?,?,?,?,0)",
                        (mid, text, kind, importance, None if embedding is None else to_blob(embedding),
                         embed_model, source, now, now))
        return mid

    def memories(self) -> list[dict]:
        rows = self.db.execute("select * from memories").fetchall()
        return [{**dict(r), "embedding": from_blob(r["embedding"])} for r in rows]

    def touch_memories(self, ids: list[str]) -> None:
        now = time.time()
        self.db.executemany("update memories set last_access=?, access_count=access_count+1 where id=?",
                            [(now, i) for i in ids])

    def update_memory(self, mid: str, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"update memories set {cols} where id=?", (*fields.values(), mid))

    def delete_memory(self, mid: str) -> None:
        self.db.execute("delete from memories where id=?", (mid,))

    # ---------------------------------------------------------------- arms (Thompson sampling)
    def arm(self, dim: str, option: str, prior: tuple[float, float] = (1.0, 1.0)) -> tuple[float, float]:
        r = self.db.execute("select alpha, beta from arms where dim=? and option=?", (dim, option)).fetchone()
        if r is None:
            self.db.execute("insert into arms values(?,?,?,?)", (dim, option, *prior))
            return prior
        return r["alpha"], r["beta"]

    def set_arm(self, dim: str, option: str, alpha: float, beta: float) -> None:
        self.db.execute("insert into arms values(?,?,?,?) on conflict(dim,option) do update set"
                        " alpha=excluded.alpha, beta=excluded.beta", (dim, option, alpha, beta))

    def all_arms(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("select * from arms order by dim, option").fetchall()]

    # ---------------------------------------------------------------- style EMA
    def style(self) -> dict[str, tuple[float, int]]:
        return {r["key"]: (r["value"], r["n"]) for r in self.db.execute("select * from style").fetchall()}

    def set_style(self, key: str, value: float, n: int) -> None:
        self.db.execute("insert into style values(?,?,?) on conflict(key) do update set value=excluded.value,"
                        " n=excluded.n", (key, value, n))

    # ---------------------------------------------------------------- vocabulary + rhythm
    def bump_vocab(self, terms: list[str], weight: float = 1.0, now: float | None = None) -> None:
        now = now or time.time()
        self.db.executemany(
            "insert into vocab values(?,?,?) on conflict(term) do update set count=count+excluded.count,"
            " last_seen=excluded.last_seen", [(t, weight, now) for t in terms])

    def vocab(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "select term, count, last_seen from vocab order by count desc, last_seen desc limit ?", (limit,))]

    def bump_rhythm(self, slot: int, terms: list[str]) -> None:
        self.db.execute("insert into rhythm values(?,1) on conflict(slot) do update set count=count+1", (slot,))
        self.db.executemany("insert into rhythm_terms values(?,?,1) on conflict(slot,term) do update set"
                            " count=count+1", [(slot, t) for t in set(terms)])

    def rhythm(self) -> dict[int, float]:
        return {r["slot"]: r["count"] for r in self.db.execute("select * from rhythm")}

    def rhythm_terms(self, min_count: float = 3) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "select * from rhythm_terms where count>=? order by count desc", (min_count,))]

    # ---------------------------------------------------------------- interactions
    def add_interaction(self, user_text: str, reply: str, style: dict, model: str, persona_hash: str,
                        created_at: float | None = None) -> str:
        iid = str(uuid.uuid4())
        self.db.execute("insert into interactions values(?,?,?,?,?,?,?,null,null,null)",
                        (iid, created_at or time.time(), user_text, reply, json.dumps(style), model, persona_hash))
        return iid

    def get_interaction(self, iid: str) -> dict | None:
        r = self.db.execute("select * from interactions where id=?", (iid,)).fetchone()
        return None if r is None else {**dict(r), "style": json.loads(r["style"])}

    def set_feedback(self, iid: str, feedback: int | None, edited: str | None, comment: str | None) -> None:
        self.db.execute("update interactions set feedback=coalesce(?,feedback), edited_reply=coalesce(?,edited_reply),"
                        " comment=coalesce(?,comment) where id=?", (feedback, edited, comment, iid))

    def recent_interactions(self, n: int) -> list[dict]:
        rows = self.db.execute("select * from interactions order by created_at desc limit ?", (n,)).fetchall()
        return [{**dict(r), "style": json.loads(r["style"])} for r in reversed(rows)]

    def interactions(self) -> list[dict]:
        rows = self.db.execute("select * from interactions order by created_at").fetchall()
        return [{**dict(r), "style": json.loads(r["style"])} for r in rows]

    # ---------------------------------------------------------------- adapters
    def add_adapter(self, version: str, path: str, base_model: str, n_examples: int) -> None:
        self.db.execute("update adapters set active=0")
        self.db.execute("insert into adapters values(?,?,?,?,?,1)", (version, path, base_model, time.time(), n_examples))

    def active_adapter(self) -> dict | None:
        r = self.db.execute("select * from adapters where active=1").fetchone()
        return dict(r) if r else None

    # ---------------------------------------------------------------- export / wipe (POPIA)
    def export(self) -> dict:
        out: dict[str, Any] = {}
        for t in ("meta", "facts", "memories", "arms", "style", "vocab", "rhythm", "rhythm_terms",
                  "interactions", "adapters"):
            rows = [dict(r) for r in self.db.execute(f"select * from {t}")]
            for r in rows:
                r.pop("embedding", None)
            out[t] = rows
        return out

    def forget(self, before: float | None = None, terms: list[str] | None = None) -> dict:
        """POPIA (the brain's retention.py and per-person erasure): memories and conversations from before `before`,
        and everything that names one of `terms` (a person's name and aliases): memories, conversations, facts whose
        value names them, vocabulary."""
        out = {"memories": 0, "interactions": 0, "facts": 0, "vocab": 0}
        with self.tx():
            if before:
                out["memories"] += self.db.execute("delete from memories where created_at < ?", (before,)).rowcount
                out["interactions"] += self.db.execute("delete from interactions where created_at < ?",
                                                       (before,)).rowcount
            for t in [x.strip().lower() for x in (terms or []) if x and len(x.strip()) >= 2]:
                like = f"%{t}%"
                out["memories"] += self.db.execute("delete from memories where lower(text) like ?", (like,)).rowcount
                out["interactions"] += self.db.execute(
                    "delete from interactions where lower(user_text) like ? or lower(reply) like ? "
                    "or lower(coalesce(edited_reply, '')) like ?", (like, like, like)).rowcount
                out["facts"] += self.db.execute("delete from facts where lower(value) like ? or lower(key) like ?",
                                                (like, like)).rowcount
                out["vocab"] += self.db.execute("delete from vocab where lower(term) like ?", (like,)).rowcount
                self.db.execute("delete from rhythm_terms where lower(term) like ?", (like,))
        return out

    def wipe(self) -> None:
        for t in ("facts", "memories", "arms", "style", "vocab", "rhythm", "rhythm_terms", "interactions",
                  "adapters", "meta"):
            self.db.execute(f"delete from {t}")
        self.db.execute("vacuum")
