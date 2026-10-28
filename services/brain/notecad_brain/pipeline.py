# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""The capture pipeline (blueprint 3.2):

  capture -> 1 STT -> normalise -> 2 split into events -> per event: 3 candidates -> 4 route ->
  5 validate -> 6 apply (notes, tasks, alerts, branches, links, delegation)  or  Inbox (ask the owner)
  -> live events -> companion learns from the applied note.

States: queued -> transcribing -> routing -> applied | needs_review | failed. Every step is idempotent on
the capture id, so a retried upload or a re-run job never writes twice.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import delegate, onboarding, text
from .apply import Applier
from .common import PROVENANCE, new_id, now_iso, parse_iso, uuid7
from .config import Settings
from .db import Database, loads
from .events import Broker
from .graph import Graph, GraphError
from .retrieve import Retriever
from .routers import (ClaudeRouter, LocalRouter, RouteContext, RouterChain, RulesRouter, build_actions,
                      assignee_from_text)
from .stt import STT, STTError, make_stt
from .validate import check


AUDIO_EXT = {"audio/ogg": ".ogg", "audio/opus": ".opus", "audio/webm": ".webm", "video/webm": ".webm",
             "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
             "audio/wave": ".wav", "audio/vnd.wave": ".wav", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
             "audio/aac": ".aac", "audio/flac": ".flac"}


def routers_pronoun(ev: str) -> bool:
    from .routers import PRONOUN
    return bool(PRONOUN.search(ev))


class CompanionLink:
    """Best-effort hand-off to the owner's companion (learns from every applied note, adds its keyterms)."""

    def __init__(self, base_url: str | None, timeout: float = 3.0, transport=None):
        self.base_url = base_url.rstrip("/") if base_url else None
        self._timeout = timeout
        self._transport = transport

    def _client(self):
        return httpx.Client(base_url=self.base_url or "", timeout=self._timeout, transport=self._transport)

    def observe(self, owner: str, body: str, node_path: str | None) -> None:
        if not self.base_url:
            return
        try:
            with self._client() as c:
                c.post(f"/v1/{owner}/observe", json={"text": body, "node_path": node_path, "source": "note"})
        except Exception:
            pass

    def keyterms(self, owner: str) -> list[str]:
        if not self.base_url:
            return []
        try:
            with self._client() as c:
                return c.get(f"/v1/{owner}/keyterms").json().get("keyterms", [])
        except Exception:
            return []


def make_routers(settings: Settings) -> RouterChain:
    chain = []
    for name in [n.strip() for n in settings.routers.split(",") if n.strip()]:
        if name == "claude":
            chain.append(ClaudeRouter(settings.claude_model))
        elif name == "local":
            from notecad_companion.llm import OpenAICompatLLM
            chain.append(LocalRouter(OpenAICompatLLM(settings.local_base_url, settings.local_model, timeout=60)))
        elif name == "rules":
            chain.append(RulesRouter())
    return RouterChain(chain or [RulesRouter()], fast_path=settings.rules_fast_path)


def make_embedder(settings: Settings):
    if settings.embed_backend == "openai":
        from notecad_companion.embed import OpenAICompatEmbedder
        return OpenAICompatEmbedder(settings.embed_base_url, settings.embed_model)
    if settings.embed_backend == "hash":
        from notecad_companion.embed import HashEmbedder
        return HashEmbedder(256)
    return None


class Brain:
    def __init__(self, settings: Settings | None = None, *, db: Database | None = None, routers: RouterChain | None = None,
                 embedder=None, stt: STT | None = None, companion: CompanionLink | None = None,
                 broker: Broker | None = None, onboarding_llm=None):
        self.settings = settings or Settings()
        self.db = db or Database(self.settings.db_url)
        self.graph = Graph(self.db)
        self.embedder = embedder if embedder is not None else make_embedder(self.settings)
        self.retriever = Retriever(self.graph, self.embedder)
        self.routers = routers or make_routers(self.settings)
        self.stt = stt if stt is not None else make_stt(self.settings)
        self.companion = companion or CompanionLink(self.settings.companion_url)
        self.broker = broker or Broker()
        self.applier = Applier(self.db, self.graph)
        from .sync import Journal, SyncEngine
        self.journal = Journal(self.db, worker_id=self.settings.worker_id)
        self.journal.baseline()
        self.sync = SyncEngine(self, self.settings.sync_target, token=self.settings.sync_token,
                               interval=self.settings.sync_interval,
                               workspaces=[w.strip() for w in (self.settings.sync_workspaces or "").split(",") if w.strip()])
        if onboarding_llm is None and "local" in self.settings.routers and routers is None:
            from notecad_companion.llm import OpenAICompatLLM  # first-run branches from the owner's own words
            onboarding_llm = OpenAICompatLLM(self.settings.local_base_url, self.settings.local_model, timeout=120)
        self.onboarding_llm = onboarding_llm

    def close(self) -> None:
        self.sync.stop()
        self.db.close()

    # ================================================================ capture in
    def register_capture(self, ws: str, *, text: str | None = None, audio: bytes | None = None, mime: str | None = None,
                         capture_id: str | None = None, recorded_at: str | None = None, source: str = "phone",
                         geo: dict | None = None, lang_hint: str | None = None, user_id: str | None = None,
                         enqueue: bool = True, context_node_id: str | None = None) -> dict:
        if self.graph.workspace(ws) is None:
            raise GraphError("unknown workspace")
        if context_node_id:
            anchor = self.graph.node(context_node_id)
            if anchor is None or anchor["workspace_id"] != ws:
                raise GraphError("context_node_id is not a node in this workspace")
        cid = capture_id or uuid7()
        existing = self.db.one("select * from captures where id=?", (cid,))
        if existing:  # idempotent: the phone may upload twice after a drop-out
            return {"capture_id": cid, "state": existing["state"], "duplicate": True}
        audio_path = sha = None
        if audio:
            d = Path(self.settings.audio_dir) / ws
            d.mkdir(parents=True, exist_ok=True)
            ext = AUDIO_EXT.get((mime or "").split(";")[0].strip().lower(), ".bin")
            p = d / f"{cid}{ext}"
            p.write_bytes(audio)
            audio_path, sha = str(p), hashlib.sha256(audio).hexdigest()
        now = now_iso()
        with self.db.tx():
            self.db.insert("captures", {"id": cid, "workspace_id": ws, "user_id": user_id, "source": source,
                                        "audio_path": audio_path, "sha256": sha, "recorded_at": recorded_at or now,
                                        "geo": geo, "lang_hint": lang_hint, "state": "queued", "text": text,
                                        "transcript": json.dumps({"mime": mime}) if audio else None, "lang": None,
                                        "router": None, "error": None, "anchor_node_id": context_node_id,
                                        "created_at": now, "updated_at": now})
            if enqueue:
                self.db.insert("jobs", {"id": new_id(), "kind": "capture", "payload": {"capture_id": cid},
                                        "state": "queued", "attempts": 0, "run_after": now, "last_error": None,
                                        "created_at": now})
        self.broker.publish(ws, "capture.queued", {"capture_id": cid, "state": "queued", "source": source,
                                                   "kind": "audio" if audio else "text", "context_node_id": context_node_id})
        return {"capture_id": cid, "state": "queued", "duplicate": False, "context_node_id": context_node_id}

    def _state(self, ws: str, cid: str, state: str, **fields) -> None:
        self.db.update("captures", {"id": cid}, {"state": state, "updated_at": now_iso(), **fields})
        if state in ("applied", "needs_review", "failed"):  # the other states have their own, finer events
            self.broker.publish(ws, "capture.failed" if state == "failed" else "capture.completed",
                                {"capture_id": cid, "state": state,
                                 **{k: v for k, v in fields.items() if k in ("error", "router")}})

    def _node_event(self, ws: str, nid: str, cid: str | None = None) -> None:
        n = self.graph.node(nid)
        if n:
            self.broker.publish(ws, "node.updated", {"node_id": nid, "capture_id": cid, "status": n["status"],
                                                     "display_status": n["display_status"],
                                                     "child_worst": n["child_worst"], "open_tasks": n["open_tasks"],
                                                     "open_alerts": n["open_alerts"]})

    # ================================================================ the pipeline
    def process(self, cid: str) -> dict:
        cap = self.db.one("select * from captures where id=?", (cid,))
        if cap is None:
            raise KeyError(cid)
        ws = cap["workspace_id"]
        if cap["state"] in ("applied", "needs_review", "undone"):
            return self.capture_summary(cid)
        try:
            # 1 speech to text
            transcript_text = cap["text"]
            anchor = cap.get("anchor_node_id")
            if anchor and self.graph.node(anchor) is None:
                anchor = None  # the node was deleted while the capture waited
            if not transcript_text:
                if not cap["audio_path"]:
                    raise STTError("capture has neither text nor audio")
                if self.stt is None:
                    raise STTError("no speech-to-text engine configured (set NC_BRAIN_DEEPGRAM_KEY or install faster-whisper)")
                self._state(ws, cid, "transcribing")
                self.broker.publish(ws, "stt.transcribing", {"capture_id": cid, "engine": getattr(self.stt, "name", None)})
                meta = loads(cap["transcript"], {}) or {}
                t = self.stt.transcribe(Path(cap["audio_path"]).read_bytes(), mime=meta.get("mime") or "audio/ogg",
                                        lang_hint=cap["lang_hint"], keyterms=self.keyterms(ws))
                transcript_text = t.text
                self.db.update("captures", {"id": cid}, {"text": t.text, "transcript": t.as_dict(), "lang": t.language})
                self.broker.publish(ws, "stt.completed", {"capture_id": cid, "transcript": t.text, "language": t.language,
                                                          "confidence": t.confidence, "engine": t.engine, "typed": False})
            else:  # typed note: no speech to text, but the same event so the UI follows one sequence
                self.broker.publish(ws, "stt.completed", {"capture_id": cid, "transcript": transcript_text,
                                                          "language": cap["lang_hint"], "confidence": 1.0,
                                                          "engine": None, "typed": True})
            clean = text.normalise(transcript_text)
            # 2 events
            self._state(ws, cid, "routing")
            known_numbers = {t for n in self.graph.nodes(ws) for t in re.findall(r"\d+", n["title"])}
            events = [e for ev in text.split_events(clean) for e in text.expand_ranges(ev, known_numbers)]
            captured_at = parse_iso(cap["recorded_at"]) or datetime.now(timezone.utc)
            results, review, routers_used = [], 0, set()
            spine = [{"node_id": n["id"], "path": self.graph.path_titles(n["id"]), "kind": n["kind"]}
                     for n in self.graph.spine(ws)]
            profile = {r["key"]: loads(r["value"], r["value"]) for r in
                       self.db.query("select key, value from profile_facts where workspace_id=?", (ws,))}
            people = [{"name": m["display_name"], "role": m["role"]} for m in self.graph.members(ws)] + \
                     [{"name": p["title"], "role": "person"} for p in
                      self.db.query("select title from nodes where workspace_id=? and kind='person'", (ws,))]
            root_id = self.graph.root(ws)["id"]
            previous: str | None = None
            for idx, ev in enumerate(events):
                done = self.db.one("select state from capture_events where capture_id=? and idx=?", (cid, idx))
                if done and done["state"] in ("applied", "needs_review"):
                    results.append({"idx": idx, "state": done["state"]})
                    review += done["state"] == "needs_review"
                    continue
                self.broker.publish(ws, "router.resolving", {"capture_id": cid, "idx": idx, "text": ev,
                                                             "events": len(events), "context_node_id": anchor})
                # 3 candidates
                cands = self.retriever.candidates(ws, ev, anchor=anchor)
                if previous and previous not in {c["node_id"] for c in cands}:
                    pn = self.graph.node(previous)
                    if pn:
                        cands.insert(0 if routers_pronoun(ev) else len(cands), {"node_id": previous, "path": self.graph.path_titles(previous), "title": pn["title"],
                                      "kind": pn["kind"], "status": pn["status"], "aliases": self.graph.aliases(previous)[:6],
                                      "summary": pn.get("summary"), "attributes": pn["attributes"],
                                      "parent_id": pn["parent_id"], "score": 0.5, "fuzzy": 0, "embedding": 0,
                                      "via": "previous event in this note"})
                ctx = RouteContext(capture_id=cid, event_index=idx, event=ev, transcript=clean, captured_at=captured_at,
                                   lang=cap["lang"] or cap["lang_hint"], candidates=cands, spine=spine,
                                   profile=profile, people=people, timezone=self.settings.timezone,
                                   previous_node_id=previous, anchor_node_id=anchor)
                # 4 route
                payload, router_name, errors = self.routers.route(ctx)
                routers_used.add(router_name)
                # 5 validate
                allowed = {c["node_id"] for c in cands} | {s["node_id"] for s in spine}
                attrs = {c["node_id"]: c.get("attributes") or {} for c in cands}
                checked = check(payload, allowed_ids=allowed, root_id=root_id, node_attrs=attrs)
                row = {"capture_id": cid, "idx": idx, "text": ev,
                       "candidates": [{k: c[k] for k in ("node_id", "path", "score", "via")} for c in cands],
                       "routed": payload, "router": router_name,
                       "confidence": min([a.get("confidence", 0) for a in payload.get("actions", [])] or [0])}
                if checked.gate:
                    # Inbox: the owner decides; the proposal is kept so one tap applies it
                    opts = checked.options or [{"label": c["path"], "node_id": c["node_id"]} for c in cands[:3]]
                    inbox_id = new_id()
                    with self.db.tx():  # one transaction: a retry after a crash must not ask twice
                        self.db.insert("inbox", {"id": inbox_id, "workspace_id": ws, "capture_id": cid, "event_idx": idx,
                                               "question": checked.question or f'Where should this go? "{ev}"',
                                               "options": opts, "event_text": ev,
                                               "proposal": {"actions": checked.actions, "reason": checked.gate,
                                                            "errors": checked.errors, "router": router_name},
                                               "state": "open", "resolution": None, "created_at": now_iso(),
                                               "resolved_at": None})
                        self._upsert_event(row, "needs_review")
                    self.broker.publish(ws, "inbox.created", {
                        "capture_id": cid, "idx": idx, "inbox_id": inbox_id, "text": ev, "reason": checked.gate,
                        "question": checked.question or f'Where should this go? "{ev}"', "options": opts,
                        "router": router_name})
                    review += 1
                    results.append({"idx": idx, "state": "needs_review", "reason": checked.gate, "router": router_name})
                    continue
                # 6 apply
                res = self.applier.apply(ws, cid, idx, checked.actions, f"ai:{router_name}",
                                         {"router": router_name, "fallbacks": errors})
                self._upsert_event(row, "applied")
                results.append({"idx": idx, "state": "applied", "router": router_name,
                                **{k: res.get(k) for k in ("notes", "tasks", "alerts", "delegated", "nodes")}})
                affected = self._with_ancestors(res.get("nodes", []))
                info = self._map_info(res.get("nodes", []))
                self.broker.publish(ws, "action.applied", {
                    "capture_id": cid, "idx": idx, "router": router_name, "node_ids": res.get("nodes", []),
                    "affected_node_ids": affected, "created_node_ids": sorted(res.get("created", {}).values()),
                    "nodes": info, "map_node_ids": sorted({i["map_id"] for i in info}),
                    "actions": [a["type"] for a in checked.actions],
                    **{k: res.get(k) for k in ("notes", "tasks", "alerts", "delegated")}})
                for nid in affected:
                    self._node_event(ws, nid, cid)
                note = next((a for a in checked.actions if a["type"] == "append_note"), None)
                if note:
                    target = res["created"].get(note["node_id"], note["node_id"])
                    tn = self.graph.node(target)
                    previous = tn["parent_id"] if tn and tn["kind"] == "channel" else target
                    self.companion.observe(ws, note["text"], self.graph.path_titles(target))
            final = "needs_review" if review else "applied"
            self._state(ws, cid, final, router=",".join(sorted(routers_used)) or None, error=None)
            return {"capture_id": cid, "state": final, "text": clean, "events": results}
        except Exception as ex:
            self._state(ws, cid, "failed", error=f"{type(ex).__name__}: {ex}"[:500])
            raise

    def _upsert_event(self, row: dict, state: str) -> None:
        if self.db.one("select 1 from capture_events where capture_id=? and idx=?", (row["capture_id"], row["idx"])):
            self.db.update("capture_events", {"capture_id": row["capture_id"], "idx": row["idx"]},
                           {k: v for k, v in {**row, "state": state}.items() if k not in ("capture_id", "idx")})
        else:
            self.db.insert("capture_events", {**row, "state": state})

    def _map_info(self, node_ids: list[str]) -> list[dict]:
        """Title, path and the id the mind map shows it under (a channel is drawn as its parent)."""
        out = []
        for nid in node_ids:
            n = self.graph.node(nid)
            if not n:
                continue
            shown = n
            while shown["kind"] == "channel" and shown["parent_id"]:
                shown = self.graph.node(shown["parent_id"])
            out.append({"id": nid, "title": n["title"], "kind": n["kind"], "path": self.graph.path_titles(nid),
                        "map_id": shown["id"], "map_path": self.graph.path_titles(shown["id"])})
        return out

    def history(self, node_id: str, limit: int = 100) -> list[dict]:
        """The action log for one node (and its channels): what changed, from which note, by which router, undone."""
        n = self.graph.node(node_id)
        if n is None:
            raise KeyError(node_id)
        ids = [node_id] + [c["id"] for c in self.graph.children(node_id) if c["kind"] == "channel"]
        rows: list[dict] = []
        for i in ids:
            rows += self.db.query("select a.id, a.capture_id, a.event_idx, a.seq, a.actor, a.action, a.provenance, "
                                  "a.undone_at, a.created_at, c.text as capture_text, c.source, "
                                  "c.audio_path is not null as has_audio "
                                  "from action_log a left join captures c on c.id=a.capture_id "
                                  "where a.workspace_id=? and a.action like ? order by a.created_at desc limit ?",
                                  (n["workspace_id"], f"%{i}%", limit))
        seen, out = set(), []
        for r in sorted(rows, key=lambda r: (r["created_at"], r["seq"]), reverse=True):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            a = loads(r["action"], {}) or {}
            if a.get("type") == "notify" or (a.get("type") == "set_status" and a.get("auto")):
                continue  # notifications and the automatic "new note" ring are not history the owner needs
            prov = loads(r["provenance"], {}) or {}
            out.append({"id": r["id"], "at": r["created_at"], "type": a.get("type"), "capture_id": r["capture_id"],
                        "event_idx": r["event_idx"], "actor": r["actor"], "router": prov.get("router"),
                        "undone": r["undone_at"] is not None, "capture_text": r["capture_text"], "source": r["source"],
                        "audio": bool(r["has_audio"]),
                        "channel": self.graph.node(a["node_id"])["title"] if a.get("node_id") not in (None, node_id)
                        and self.graph.node(a["node_id"]) else None,
                        "detail": {k: a[k] for k in ("text", "title", "status", "severity", "set", "increment",
                                                    "edge_type", "due_at", "assignee_hint", "reason") if k in a}})
        return out[:limit]

    def sync_status(self, ws: str) -> dict:
        """Local store health and what is waiting to sync (Phase 4 multi-worker sync reads the same counters)."""
        t0 = time.perf_counter()
        info: dict = {"db": self.db.kind, "ok": True}
        try:
            if self.db.kind == "sqlite":
                info["integrity"] = self.db.one("pragma quick_check")["quick_check"]
                info["journal_mode"] = self.db.one("pragma journal_mode")["journal_mode"]
                path = Path(self.db.url.removeprefix("sqlite:///").removeprefix("sqlite://"))
                if path.name and path.exists():
                    info["size_bytes"] = path.stat().st_size
                    wal = path.with_name(path.name + "-wal")
                    info["wal_bytes"] = wal.stat().st_size if wal.exists() else 0
                info["ok"] = info["integrity"] == "ok"
            else:
                self.db.one("select 1 as one")
                info["integrity"] = "ok"
        except Exception as ex:
            info.update(ok=False, integrity=f"{type(ex).__name__}: {ex}"[:200])
        q = lambda sql: self.db.one(sql, (ws,))["c"]  # noqa: E731
        info["pending"] = {
            "sync_events": q("select count(*) as c from action_log where workspace_id=? and synced_at is null"),
            "jobs_queued": self.db.one("select count(*) as c from jobs where state in ('queued','running')")["c"],
            "jobs_failed": self.db.one("select count(*) as c from jobs where state='failed'")["c"],
            "notifications_unsent": q("select count(*) as c from notifications where workspace_id=? and sent_at is null"),
            "inbox_open": q("select count(*) as c from inbox where workspace_id=? and state='open'"),
            "captures_in_flight": q("select count(*) as c from captures where workspace_id=? and state in "
                                    "('queued','transcribing','routing')"),
        }
        info["sync"] = self.sync.status()
        info.update(last_event_id=self.broker.last_id, worker=self.settings.worker, sync_target=info["sync"]["target"],
                    checked_ms=round((time.perf_counter() - t0) * 1000, 1), at=now_iso())
        return info

    def _with_ancestors(self, node_ids: list[str]) -> list[str]:
        """The changed nodes and every ancestor whose roll-up (counts, echo dot) changed with them."""
        out: list[str] = []
        for nid in node_ids:
            for n in [self.graph.node(nid)] + self.graph.ancestors(nid):
                if n and n["id"] not in out:
                    out.append(n["id"])
        return out

    def capture_audio(self, cid: str) -> Path:
        """The recording behind a capture (provenance: what the owner actually said). Only files under audio_dir."""
        cap = self.db.one("select audio_path from captures where id=?", (cid,))
        if cap is None or not cap["audio_path"]:
            raise KeyError(cid)
        p = Path(cap["audio_path"]).resolve()
        if not p.is_file() or not p.is_relative_to(Path(self.settings.audio_dir).resolve()):
            raise KeyError(cid)
        return p

    def capture_summary(self, cid: str) -> dict:
        cap = self.db.one("select * from captures where id=?", (cid,))
        if cap is None:
            raise KeyError(cid)
        evs = self.db.query("select idx, text, router, confidence, state from capture_events where capture_id=? "
                            "order by idx", (cid,))
        return {"capture_id": cid, "state": cap["state"], "text": cap["text"], "error": cap["error"],
                "router": cap["router"], "context_node_id": cap.get("anchor_node_id"), "events": evs}

    # ================================================================ worker
    def recover_jobs(self) -> int:
        """A brain killed mid-capture leaves its job 'running' and the capture half done; queue them again."""
        return self.db.execute("update jobs set state='queued' where state='running'")

    def decay_all(self) -> int:
        """Fade stored info / done statuses in every workspace (graph.decay) and tell the maps."""
        total = 0
        for w in self.db.query("select id from workspaces"):
            n = self.graph.decay(w["id"])
            if n:
                self.broker.publish(w["id"], "node.updated", {"reason": "decay", "count": n})
                total += n
        return total

    def run_jobs(self, limit: int = 10) -> int:
        n = 0
        for job in self.db.query("select * from jobs where state='queued' and run_after<=? order by created_at limit ?",
                                 (now_iso(), limit)):
            if self.db.execute("update jobs set state='running', attempts=attempts+1 where id=? and state='queued'",
                               (job["id"],)) != 1:
                continue
            payload = loads(job["payload"], {})
            try:
                if job["kind"] == "capture":
                    self.process(payload["capture_id"])
                self.db.update("jobs", {"id": job["id"]}, {"state": "done"})
            except Exception as ex:
                attempts = job["attempts"] + 1
                retry = attempts < 4 and not isinstance(ex, (STTError, GraphError, KeyError))
                self.db.update("jobs", {"id": job["id"]}, {
                    "state": "queued" if retry else "failed", "last_error": traceback.format_exc()[-1500:],
                    "run_after": now_iso(time.time() + 30 * 2 ** attempts)})
                if retry:  # the capture goes back to queued so the phone keeps waiting, not failing
                    cid = payload.get("capture_id")
                    if cid:
                        self.db.update("captures", {"id": cid}, {"state": "queued"})
            n += 1
        return n

    # ================================================================ owner decisions (Inbox) and Undo
    def resolve_inbox(self, item_id: str, node_id: str | None, *, learn_alias: bool = True) -> dict:
        item = self.db.one("select * from inbox where id=?", (item_id,))
        if item is None or item["state"] != "open":
            raise KeyError(item_id)
        ws = item["workspace_id"]
        node = self.graph.node(node_id) if node_id else None
        if node_id is None or node is None or node["workspace_id"] != ws:
            raise GraphError("choose a node from this workspace")
        proposal = loads(item["proposal"], {}) or {}
        acts = [a for a in proposal.get("actions", []) if a.get("type") != "ask_user"]
        options = {o["node_id"] for o in loads(item["options"], [])}
        if acts:  # retarget the model's proposal onto the owner's choice
            targets = {a.get("node_id") for a in acts if a.get("node_id")} | options
            for a in acts:
                for k in ("node_id", "parent_id", "src_id"):
                    if a.get(k) in targets and not str(a.get(k)).startswith("tmp:"):
                        a[k] = node_id
                a["confidence"] = 1.0
        else:  # nothing usable proposed: decide note / problem / task from the words, on the chosen node
            cap = self.db.one("select recorded_at from captures where id=?", (item["capture_id"],)) if item["capture_id"] else None
            ctx = RouteContext(capture_id=item["capture_id"] or "", event_index=item["event_idx"] or 0,
                               event=item["event_text"] or "", transcript=item["event_text"] or "",
                               captured_at=(parse_iso(cap["recorded_at"]) if cap else None) or datetime.now(timezone.utc),
                               lang=None, candidates=[{"node_id": node_id, "path": self.graph.path_titles(node_id),
                                                       "kind": node["kind"], "score": 1.0, "parent_id": node["parent_id"]}],
                               spine=[], timezone=self.settings.timezone)
            ev = ctx.event
            sev = text.severity_of(ev)
            kind = "problem" if sev else "done" if text.DONE.search(ev) else "todo" if text.TODO.search(ev) else "note"
            acts = build_actions(ctx, node_id=node_id, kind=kind, severity=sev, note=ev[:1].upper() + ev[1:],
                                 task_title=None, due=text.parse_due(ev, ctx.captured_at, self.settings.timezone),
                                 assignee=assignee_from_text(ev), place_id=None, new_item=None, confidence=1.0)["actions"]
        res = self.applier.apply(ws, item["capture_id"], item["event_idx"], acts, "user:inbox")
        with self.db.tx():
            # what placing it taught the brain is kept with the item, so Undo of the note takes the lesson back too
            correction = new_id()
            self.db.insert("route_corrections", {"id": correction, "workspace_id": ws, "phrase": item["event_text"] or "",
                                                 "node_id": node_id, "created_at": now_iso()})
            learned = None
            if learn_alias and item["event_text"]:
                phrase = self._alias_phrase(item["event_text"], node)
                if phrase:
                    self.graph.add_alias(node_id, phrase, weight=0.5)
                    learned = {"node_id": node_id, "alias": phrase.strip().lower(), "weight": 0.5}
            self.db.update("inbox", {"id": item_id}, {"state": "resolved", "resolved_at": now_iso(),
                                                      "resolution": {"node_id": node_id, "result": res.get("status"),
                                                                     "correction_id": correction, "learned_alias": learned}})
            if item["capture_id"] and item["event_idx"] is not None:
                self.db.update("capture_events", {"capture_id": item["capture_id"], "idx": item["event_idx"]},
                               {"state": "applied"})
                left = self.db.one("select count(*) as c from inbox where capture_id=? and state='open'", (item["capture_id"],))
                if left["c"] == 0:
                    self.db.update("captures", {"id": item["capture_id"]}, {"state": "applied", "updated_at": now_iso()})
        self.broker.publish(ws, "inbox.resolved", {"inbox_id": item_id, "capture_id": item["capture_id"],
                                                   "node_id": node_id, "node_ids": res.get("nodes", [])})
        for nid in self._with_ancestors(res.get("nodes", [])):
            self._node_event(ws, nid, item["capture_id"])
        return {"resolved": item_id, **res}

    @staticmethod
    def _alias_phrase(event: str, node: dict) -> str | None:
        """The owner's own words for the thing they just filed ("die groot pomp" -> Main Water Pump)."""
        from notecad_companion.textutil import content_terms
        title_words = set(node["title"].lower().split())
        terms = [t for t in content_terms(event) if t not in title_words and not t.isdigit()]
        words = event.lower().split()
        for size in (3, 2):  # a short run of the owner's words that contains a content term
            for i in range(len(words) - size + 1):
                chunk = [w.strip(".,!?") for w in words[i:i + size]]
                if chunk[-1] in terms and chunk[0] in terms + ["die", "the", "my", "ons", "our"]:
                    return " ".join(chunk)
        return terms[0] if terms else None

    def dismiss_inbox(self, item_id: str) -> None:
        self.db.update("inbox", {"id": item_id}, {"state": "dismissed", "resolved_at": now_iso()})

    def undo(self, cid: str) -> dict:
        cap = self.db.one("select workspace_id from captures where id=?", (cid,))
        if cap is None:
            raise KeyError(cid)
        touched: list[str] = []
        for r in self.db.query("select action from action_log where capture_id=? and undone_at is null", (cid,)):
            a = loads(r["action"], {}) or {}
            for k in ("node_id", "src_id", "dst_id", "parent_id"):
                if a.get(k) and a[k] not in touched and not str(a[k]).startswith("tmp:"):
                    touched.append(a[k])
        created = [loads(r["action"], {}).get("node_id") for r in self.db.query(
            "select action from action_log where capture_id=? and undone_at is null", (cid,))
            if (loads(r["action"], {}) or {}).get("type") == "create_node"]
        n = self.applier.undo(cap["workspace_id"], cid)
        with self.db.tx():
            # an Inbox answer for this note also taught the brain a phrase: forget it with the note
            for item in self.db.query("select resolution from inbox where capture_id=? and state='resolved'", (cid,)):
                r = loads(item["resolution"], {}) or {}
                if r.get("correction_id"):
                    self.db.execute("delete from route_corrections where id=?", (r["correction_id"],))
                la = r.get("learned_alias")
                if la:
                    self.db.execute("update node_aliases set weight=weight-? where node_id=? and alias=?",
                                    (la["weight"], la["node_id"], la["alias"]))
                    self.db.execute("delete from node_aliases where node_id=? and alias=? and weight<=0.0001",
                                    (la["node_id"], la["alias"]))
            self.db.execute("update inbox set state='dismissed' where capture_id=? and state='open'", (cid,))
            self.db.execute("update capture_events set state='undone' where capture_id=?", (cid,))
            self.db.update("captures", {"id": cid}, {"state": "undone", "updated_at": now_iso()})
        alive = [t for t in touched if self.graph.node(t)]
        self.broker.publish(cap["workspace_id"], "action.undone", {
            "capture_id": cid, "reverted": n, "node_ids": alive, "removed_node_ids": [c for c in created if c],
            "affected_node_ids": self._with_ancestors(alive)})
        for nid in self._with_ancestors(alive):
            self._node_event(cap["workspace_id"], nid, cid)
        return {"capture_id": cid, "reverted": n, "node_ids": alive}

    # ================================================================ tasks, alerts, delegation by hand
    def update_task(self, task_id: str, *, state: str | None = None, assignee_member: str | None = None,
                    due_at: str | None = None) -> dict:
        t = self.db.one("select * from tasks where id=?", (task_id,))
        if t is None:
            raise KeyError(task_id)
        fields: dict = {}
        if state:
            fields.update(state=state, done_at=now_iso() if state == "done" else None)
        if due_at is not None:
            fields["due_at"] = due_at or None
        with self.db.tx():
            if assignee_member is not None:
                m = self.db.one("select * from members where id=? and workspace_id=?", (assignee_member, t["workspace_id"]))
                if m is None:
                    raise GraphError("unknown member")
                fields["assignee_member"] = assignee_member
                delegate.notify(self.db, t["workspace_id"], assignee_member, "task_assigned",
                                {"task_id": task_id, "title": t["title"], "due_at": t["due_at"],
                                 "path": self.graph.path_titles(t["node_id"])})
            if fields:
                self.db.update("tasks", {"id": task_id}, fields)
            self.graph.rollup([t["node_id"]])
        self.broker.publish(t["workspace_id"], "task.updated", {"task_id": task_id, "node_id": t["node_id"], **fields})
        for nid in self._with_ancestors([t["node_id"]]):
            self._node_event(t["workspace_id"], nid)
        return self.db.one("select * from tasks where id=?", (task_id,)) or {}

    def set_attributes(self, node_id: str, changes: dict) -> dict:
        """The owner edits a node's numbers on the map (area, planted, progress); the map and the companion follow."""
        n = self.graph.node(node_id)
        if n is None:
            raise KeyError(node_id)
        attrs = {k: v for k, v in {**n["attributes"], **changes}.items() if v is not None}
        self.db.update("nodes", {"id": node_id}, {"attributes": attrs, "version": n["version"] + 1, "updated_at": now_iso()})
        self.broker.publish(n["workspace_id"], "node.updated", {"node_id": node_id, "attributes": attrs,
                                                               "status": n["status"], "display_status": n["display_status"],
                                                               "child_worst": n["child_worst"], "open_tasks": n["open_tasks"],
                                                               "open_alerts": n["open_alerts"]})
        return attrs

    def resolve_alert(self, alert_id: str) -> dict:
        a = self.db.one("select * from alerts where id=?", (alert_id,))
        if a is None:
            raise KeyError(alert_id)
        with self.db.tx():
            self.db.update("alerts", {"id": alert_id}, {"resolved_at": now_iso()})
            left = self.db.one("select count(*) as c from alerts where node_id=? and resolved_at is null", (a["node_id"],))
            n = self.graph.node(a["node_id"])
            if left["c"] == 0 and n["status"] in ("warning", "critical"):
                self.graph.set_status(a["node_id"], "ok", "alert resolved")
            self.graph.rollup([a["node_id"]])
        self.broker.publish(a["workspace_id"], "alert.updated", {"alert_id": alert_id, "node_id": a["node_id"],
                                                                 "resolved": True})
        for nid in self._with_ancestors([a["node_id"]]):
            self._node_event(a["workspace_id"], nid)
        return {"resolved": alert_id}

    # ================================================================ read models
    def keyterms(self, ws: str, limit: int = 100) -> list[str]:
        terms: list[str] = []
        for n in self.graph.nodes(ws):
            if n["kind"] not in ("root", "channel"):
                terms.append(n["title"])
        for al in self.graph.all_aliases(ws).values():
            terms += [a for a, _ in sorted(al, key=lambda x: -x[1])]
        terms += self.companion.keyterms(ws)
        seen, out = set(), []
        for t in terms:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out[:limit]

    def node_detail(self, node_id: str) -> dict:
        n = self.graph.node(node_id)
        if n is None:
            raise KeyError(node_id)
        return {**n, "path_titles": self.graph.path_titles(node_id), "aliases": self.graph.aliases(node_id),
                "notes": self.db.query("select * from notes where node_id=? order by created_at desc limit 100", (node_id,)),
                "tasks": self.db.query("select * from tasks where node_id=? order by state, created_at desc", (node_id,)),
                "alerts": self.db.query("select * from alerts where node_id=? order by created_at desc", (node_id,)),
                "edges": self.db.query("select * from edges where src_id=? or dst_id=?", (node_id, node_id)),
                "children": [{"id": c["id"], "title": c["title"], "kind": c["kind"], "display_status": c["display_status"]}
                             for c in self.graph.children(node_id)]}

    def tasks(self, ws: str, state: str | None = "open", assignee: str | None = None) -> list[dict]:
        sql = ("select t.*, m.display_name as assignee_name from tasks t left join members m on m.id=t.assignee_member "
               "where t.workspace_id=?")
        args: list = [ws]
        if state:
            sql += " and t.state=?"
            args.append(state)
        if assignee:
            sql += " and t.assignee_member=?"
            args.append(assignee)
        rows = self.db.query(sql + " order by t.due_at is null, t.due_at, t.created_at", args)
        for r in rows:
            r["path"] = self.graph.path_titles(r["node_id"])
        return rows

    def mindmap(self, ws: str, **kw) -> dict:
        from . import mindmap
        return mindmap.build(self, ws, **kw)

    def digest(self, ws: str, focus: str | None = None) -> dict:
        """What is open right now, plus the map's facts (what needs work, how far along things are); the companion
        uses this for 'what do I still need to do?', 'which tractors need work?', 'how much is planted?'.
        focus: the node the owner has open on the map, so 'this one' in a question means that node."""
        from . import mindmap
        alerts = self.db.query("select * from alerts where workspace_id=? and resolved_at is null order by created_at desc", (ws,))
        for a in alerts:
            a["path"] = self.graph.path_titles(a["node_id"])
        mm = mindmap.build(self, ws)
        out_focus = None
        if focus:
            n = next((x for x in mm["nodes"] if x["id"] == focus), None)
            if n is None and self.graph.node(focus) is not None and self.graph.node(focus)["workspace_id"] == ws:
                parent = self.graph.node(focus)["parent_id"]  # a channel: show its parent
                n = next((x for x in mm["nodes"] if x["id"] == parent), None)
            if n is not None:
                kids = [x for x in mm["nodes"] if x.get("parent_id") == n["id"] and x["type"] in ("category", "entity")]
                out_focus = {k: n.get(k) for k in ("id", "title", "path", "type", "kind", "display_status",
                                                   "status_reason", "progress", "counts", "alerts", "reminders",
                                                   "recent_notes", "attributes")}
                out_focus["tasks"] = [x["title"] for x in mm["nodes"] if x["type"] == "task" and x["parent_id"] == n["id"]]
                out_focus["children"] = [{"title": k["title"], "display_status": k["display_status"],
                                          "open_tasks": k["counts"]["open_tasks"], "progress_pct": k["progress_pct"]}
                                         for k in kids]
        return {"tasks": self.tasks(ws), "alerts": alerts, "map": mindmap.summary(mm), "focus": out_focus,
                "inbox": self.db.query("select id, question, event_text, created_at from inbox where workspace_id=? and state='open'", (ws,)),
                "recent_captures": self.db.query("select id, state, text, created_at from captures where workspace_id=? "
                                                 "order by created_at desc limit 10", (ws,))}

    # ================================================================ archive and remove a workspace
    WS_TABLES = ["members", "nodes", "edges", "captures", "notes", "tasks", "alerts", "profile_facts", "inbox",
                 "action_log", "notifications", "route_corrections"]

    def export_workspace(self, ws: str) -> dict:
        """Everything in one workspace as plain rows (the archive written before a workspace is removed)."""
        w = self.graph.workspace(ws)
        if w is None:
            raise KeyError(ws)
        out: dict = {"format": "notecad-workspace-archive/1", "exported_at": now_iso(), "provenance": PROVENANCE,
                     "workspace": w, "tables": {}}
        for t in self.WS_TABLES:
            out["tables"][t] = self.db.query(f"select * from {t} where workspace_id=?", (ws,))
        node_ids = [n["id"] for n in out["tables"]["nodes"]]
        cap_ids = [c["id"] for c in out["tables"]["captures"]]
        out["tables"]["node_aliases"] = [r for i in node_ids for r in self.db.query("select * from node_aliases where node_id=?", (i,))]
        out["tables"]["capture_events"] = [r for i in cap_ids for r in self.db.query("select * from capture_events where capture_id=?", (i,))]
        return out

    def delete_workspace(self, ws: str) -> dict:
        """Remove a workspace and everything in it, its recorded audio included. Not reversible: archive first."""
        if self.graph.workspace(ws) is None:
            raise KeyError(ws)
        counts: dict[str, int] = {}
        caps = [c["id"] for c in self.db.query("select id from captures where workspace_id=?", (ws,))]
        with self.db.tx():
            for cid in caps:
                self.db.execute("delete from jobs where payload like ?", (f'%{cid}%',))
                self.db.execute("delete from capture_events where capture_id=?", (cid,))
            for t in ["edges", "notes", "tasks", "alerts", "profile_facts", "inbox", "action_log", "notifications",
                      "route_corrections", "captures"]:
                counts[t] = self.db.execute(f"delete from {t} where workspace_id=?", (ws,))
            nodes = self.db.query("select id from nodes where workspace_id=? order by depth desc", (ws,))
            for n in nodes:  # deepest first: children before parents
                self.db.execute("delete from node_aliases where node_id=?", (n["id"],))
                self.db.execute("delete from node_embeddings where node_id=?", (n["id"],))
                self.db.execute("delete from nodes where id=?", (n["id"],))
            counts["nodes"] = len(nodes)
            counts["members"] = self.db.execute("delete from members where workspace_id=?", (ws,))
            self.db.execute("delete from workspaces where id=?", (ws,))
        audio = Path(self.settings.audio_dir) / ws
        if audio.is_dir():
            import shutil
            shutil.rmtree(audio, ignore_errors=True)
        self.broker.publish(ws, "workspace.deleted", {"counts": counts})
        return {"deleted": ws, "counts": counts}

    def onboard(self, ws: str, answer: str, apply: bool = True) -> dict:
        spine = onboarding.propose(answer, self.onboarding_llm)
        created = onboarding.apply_spine(self.graph, ws, spine) if apply else 0
        return {"proposal": spine, "created": created}
