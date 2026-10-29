# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
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
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import admin, onboarding, text
from .apply import Applier, node_of
from .common import PROVENANCE, new_id, now_iso, parse_iso, uuid7
from .config import Settings
from .db import Database, loads
from .events import Broker
from .graph import Graph, GraphError
from .permissions import (ALLOW, CONFIRM, EMPLOYEE, MANAGER, OWNER, REFUSE, SYSTEM, SYSTEM_PRINCIPAL, VISIBILITY,
                          Principal, View, load_principal, owner_principal, sees_row)
from .retrieve import Retriever
from .routers import (ClaudeRouter, LocalRouter, RouteContext, RouterChain, RulesRouter, build_actions,
                      assignee_from_text)
from .stt import STT, STTError, make_stt
from .validate import check
log = logging.getLogger("notecad.brain")


AUDIO_EXT = {"audio/ogg": ".ogg", "audio/opus": ".opus", "audio/webm": ".webm", "video/webm": ".webm",
             "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
             "audio/wave": ".wav", "audio/vnd.wave": ".wav", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
             "audio/aac": ".aac", "audio/flac": ".flac"}


def routers_pronoun(ev: str) -> bool:
    from .routers import PRONOUN
    return bool(PRONOUN.search(ev))


class CaptureConflict(GraphError):
    """A capture id another member already used: answered 409, never with their capture (ADR 0014 threat model)."""


def held_level(p: Principal) -> int:
    """Who may see a capture before it lands, or a held Inbox item, besides its author: owners for an owner's words,
    managers and owners for everyone else's."""
    return OWNER if p.level <= OWNER else MANAGER


def describe(a: dict, graph: Graph) -> str:
    """One held action in plain words, for the Inbox."""
    def title(nid: str | None) -> str:
        n = graph.node(nid) if nid and not str(nid).startswith("tmp:") else None
        return n["title"] if n else "a new branch"
    t = a.get("type")
    if t == "set_role":
        role = a.get("role") or ""
        return f"make {a.get('name') or 'them'} {'an' if role[:1] in 'aeiou' else 'a'} {role}"
    if t == "rename_node":
        return f'rename {title(a.get("node_id"))} to "{a.get("title")}"'
    if t == "move_node":
        return f"move {title(a.get('node_id'))} under {title(a.get('parent_id'))}"
    if t == "delete_node":
        return f"delete {title(a.get('node_id'))} and everything under it"
    if t == "create_node":
        return f'add "{a.get("title")}" under {title(a.get("parent_id"))}'
    if t == "set_visibility":
        return f"make {title(a.get('node_id'))} visible to {a.get('visibility')}"
    if t == "update_task":
        if a.get("assignee_member"):
            m = graph.db.one("select display_name from members where id=?", (a["assignee_member"],))
            return f"give the task to {m['display_name'] if m else 'someone'}"
        return "change a task" if set(a) - {"type", "id", "state", "confidence", "evidence"} else f"mark a task {a.get('state')}"
    if t == "resolve_alert":
        return "resolve an alert"
    if t in ("set_status", "update_attributes", "link_nodes", "add_alias"):
        return {"set_status": f"set {title(a.get('node_id'))} to {a.get('status')}",
                "update_attributes": f"change the numbers on {title(a.get('node_id'))}",
                "link_nodes": f"link {title(a.get('src_id'))} to {title(a.get('dst_id'))}",
                "add_alias": f'call {title(a.get("node_id"))} "{a.get("alias")}"'}[t]
    if t in ("edit_note", "delete_entry"):
        return "edit a note" if t == "edit_note" else f"delete an entry from {a.get('table')}"
    return str(t).replace("_", " ")


class CompanionLink:
    """Best-effort hand-off to the owner's companion (learns from every applied note, adds its keyterms)."""

    def __init__(self, base_url: str | None, timeout: float = 3.0, transport=None):
        self.base_url = base_url.rstrip("/") if base_url else None
        self._timeout = timeout
        self._transport = transport

    def _client(self):
        return httpx.Client(base_url=self.base_url or "", timeout=self._timeout, transport=self._transport)

    def forget(self, owner: str, terms: list[str] | None, members: list[str], before: float | None = None,
               wipe: str | None = None) -> dict | None:
        """POPIA: what the owner's companion and every member's own companion learned that is older than `before`, or
        that names one of `terms`; `wipe`: a member whose own store goes entirely. None when no companion is set."""
        if not self.base_url:
            return None
        got: dict = {}
        try:
            with self._client() as c:
                for m in [None, *members]:
                    r = c.post(f"/v1/{owner}/forget", json={"before": before, "terms": terms,
                                                            **({"as_member": m} if m else {})})
                    if r.status_code == 200:
                        for k, v in r.json().items():
                            got[k] = got.get(k, 0) + v
                if wipe:
                    c.delete(f"/v1/{owner}", params={"as_member": wipe})
        except Exception:
            log.warning("companion forget for %s did not reach the companion", owner)
            return None
        return got

    def export(self, owner: str, member: str) -> dict | None:
        """A member's own companion store, for their export (POPIA s23)."""
        if not self.base_url:
            return None
        try:
            with self._client() as c:
                r = c.get(f"/v1/{owner}/export", params={"as_member": member})
                return r.json().get("data") if r.status_code == 200 else None
        except Exception:
            return None

    def observe(self, owner: str, body: str, node_path: str | None, member: str | None = None) -> None:
        """member: a member other than the owner said it, so it goes to their own companion memory (ADR 0014)."""
        if not self.base_url:
            return
        try:
            with self._client() as c:
                c.post(f"/v1/{owner}/observe", json={"text": body, "node_path": node_path, "source": "note",
                                                     **({"as_member": member} if member else {})})
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
        from .devicesync import DeviceSync
        from .people import People
        self.people = People(self)  # seats, invites, joining, roles, devices (ADR 0014)
        self.devices = DeviceSync(self)  # a member's device copy: snapshot, pull, tombstones
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
                         enqueue: bool = True, context_node_id: str | None = None,
                         principal: Principal = SYSTEM_PRINCIPAL) -> dict:
        """principal: who is speaking (ADR 0014). Their member id goes on the capture, and the capture is routed and
        applied with their rights and their view of the map."""
        if self.graph.workspace(ws) is None:
            raise GraphError("unknown workspace")
        if context_node_id:
            anchor = self.graph.node(context_node_id)
            if anchor is None or anchor["workspace_id"] != ws or not View(self.db, principal, ws).rows(context_node_id):
                raise GraphError("context_node_id is not a node in this workspace")
        cid = capture_id or uuid7()
        existing = self.db.one("select * from captures where id=?", (cid,))
        if existing:  # idempotent: the phone may upload twice after a drop-out
            if principal.level > OWNER and existing.get("member_id") != principal.member_id:
                raise CaptureConflict("that capture id is already in use")  # not someone else's capture
            return {"capture_id": cid, "state": existing["state"], "duplicate": True}
        if principal.level != SYSTEM and principal.read_only:
            raise PermissionError("a read-only member cannot record notes")
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
                                        "created_at": now, "updated_at": now, "member_id": principal.member_id,
                                        "eff_level": held_level(principal)})
            if enqueue:
                self.db.insert("jobs", {"id": new_id(), "kind": "capture", "payload": {"capture_id": cid},
                                        "state": "queued", "attempts": 0, "run_after": now, "last_error": None,
                                        "created_at": now})
        self.broker.publish(ws, "capture.queued", {"capture_id": cid, "state": "queued", "source": source,
                                                   "kind": "audio" if audio else "text", "context_node_id": context_node_id},
                            author=principal.member_id)
        return {"capture_id": cid, "state": "queued", "duplicate": False, "context_node_id": context_node_id}

    def _state(self, ws: str, cid: str, state: str, **fields) -> None:
        self.db.update("captures", {"id": cid}, {"state": state, "updated_at": now_iso(), **fields})
        if state in ("applied", "needs_review", "failed"):  # the other states have their own, finer events
            author = (self.db.one("select member_id from captures where id=?", (cid,)) or {}).get("member_id")
            self.broker.publish(ws, "capture.failed" if state == "failed" else "capture.completed",
                                {"capture_id": cid, "state": state,
                                 **{k: v for k, v in fields.items() if k in ("error", "router")}}, author=author)

    def capture_principal(self, cap: dict) -> Principal:
        """Who a capture speaks for. One from before ADR 0014 (no member) is the owner's, as it was then."""
        ws = cap["workspace_id"]
        return load_principal(self.db, ws, cap.get("member_id")) or owner_principal(self.db, ws)

    def _touches_restricted(self, cands: list[dict], event: str) -> bool:
        """POPIA s72: is this note about a restricted branch (one of its three best candidates is, or it names one)?
        Then it does not leave this PC. Every restricted candidate is marked, so a cloud router never gets those."""
        low, hit = event.lower(), False
        for i, c in enumerate(cands):
            n = self.graph.node(c["node_id"])
            if n and (n.get("eff_level") or EMPLOYEE) < EMPLOYEE:
                c["restricted"] = True
                names = [n["title"], *c.get("aliases", [])]
                if i < 3 or any(x and len(x) >= 3 and x.lower() in low for x in names):
                    hit = True
        return hit

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
        # ADR 0014: the capture is routed and applied as its author, from what they can see. A revoked member's
        # last notes are routed on the owner's view and held for an owner (Applier: everything they do is proposed).
        principal = self.capture_principal(cap)
        view = View(self.db, principal if principal.active else owner_principal(self.db, ws), ws)
        author = principal.member_id
        from . import privacy
        cloud_ok = privacy.cloud_allowed(self.db, ws)  # POPIA s72: the owner's cloud transfer gate, off by default
        try:
            # 1 speech to text
            transcript_text = cap["text"]
            anchor = cap.get("anchor_node_id")
            if anchor and (self.graph.node(anchor) is None or not view.rows(anchor)):
                anchor = None  # the node was deleted (or hidden from the speaker) while the capture waited
            if not transcript_text:
                if not cap["audio_path"]:
                    raise STTError("capture has neither text nor audio")
                from .stt import local_only
                stt = self.stt if cloud_ok else local_only(self.stt)
                if stt is None:
                    raise STTError("no speech-to-text engine on this PC (the cloud transfer gate is off), or none set")
                if stt is not local_only(stt):
                    log.info("cloud transfer may happen: capture=%s to=%s", cid, getattr(stt, "name", "?"))
                self._state(ws, cid, "transcribing")
                self.broker.publish(ws, "stt.transcribing", {"capture_id": cid, "engine": getattr(stt, "name", None)},
                                    author=author)
                meta = loads(cap["transcript"], {}) or {}
                t = stt.transcribe(Path(cap["audio_path"]).read_bytes(), mime=meta.get("mime") or "audio/ogg",
                                        lang_hint=cap["lang_hint"], keyterms=self.keyterms(ws, view))
                transcript_text = t.text
                self.db.update("captures", {"id": cid}, {"text": t.text, "transcript": t.as_dict(), "lang": t.language})
                self.broker.publish(ws, "stt.completed", {"capture_id": cid, "transcript": t.text, "language": t.language,
                                                          "confidence": t.confidence, "engine": t.engine, "typed": False},
                                    author=author)
            else:  # typed note: no speech to text, but the same event so the UI follows one sequence
                self.broker.publish(ws, "stt.completed", {"capture_id": cid, "transcript": transcript_text,
                                                          "language": cap["lang_hint"], "confidence": 1.0,
                                                          "engine": None, "typed": True}, author=author)
            clean = text.normalise(transcript_text)
            # 2 events
            self._state(ws, cid, "routing")
            seen_nodes = [n for n in self.graph.nodes(ws) if view.rows(n["id"])]
            known_numbers = {t for n in seen_nodes for t in re.findall(r"\d+", n["title"])}
            events = [e for ev in text.split_events(clean) for e in text.expand_ranges(ev, known_numbers)]
            captured_at = parse_iso(cap["recorded_at"]) or datetime.now(timezone.utc)
            results, review, routers_used = [], 0, set()
            spine = [{"node_id": n["id"], "path": self.graph.path_titles(n["id"]), "kind": n["kind"],
                      "restricted": (n.get("eff_level") or EMPLOYEE) < EMPLOYEE}
                     for n in self.graph.spine(ws) if view.rows(n["id"])]
            profile = {r["key"]: loads(r["value"], r["value"]) for r in
                       self.db.query("select key, value, visibility from profile_facts where workspace_id=?", (ws,))
                       if view.fact(r["visibility"])}
            people = [{"name": m["display_name"], "role": m["role"]} for m in self.graph.members(ws)
                      if m["status"] == "active"] + \
                     [{"name": p["title"], "role": "person"} for p in
                      self.db.query("select id, title from nodes where workspace_id=? and kind='person'", (ws,))
                      if view.rows(p["id"])]
            root_id = self.graph.root(ws)["id"]
            previous: str | None = None
            for idx, ev in enumerate(events):
                done = self.db.one("select state from capture_events where capture_id=? and idx=?", (cid, idx))
                if done and done["state"] in ("applied", "needs_review"):
                    results.append({"idx": idx, "state": done["state"]})
                    review += done["state"] == "needs_review"
                    continue
                self.broker.publish(ws, "router.resolving", {"capture_id": cid, "idx": idx, "text": ev,
                                                             "events": len(events), "context_node_id": anchor},
                                    author=author)
                cmd = admin.parse(ev)  # "make Johan a manager", "restrict Financials to owner only": rules, never a model
                if cmd is not None:
                    out = self._admin(ws, cid, idx, ev, cmd, principal, view)
                    review += out["state"] == "needs_review"
                    results.append(out)
                    continue
                # 3 candidates: only nodes the speaker can see, so no prompt for them holds anything else
                cands = self.retriever.candidates(ws, ev, anchor=anchor, view=view)
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
                                   previous_node_id=previous, anchor_node_id=anchor,
                                   cloud=cloud_ok and not self._touches_restricted(cands, ev))
                # 4 route
                payload, router_name, errors = self.routers.route(ctx)
                routers_used.add(router_name)
                # 5 validate
                allowed = {c["node_id"] for c in cands} | {s["node_id"] for s in spine}
                attrs = {c["node_id"]: c.get("attributes") or {} for c in cands}
                checked = check(payload, allowed_ids=allowed, root_id=root_id, node_attrs=attrs)
                owners_only = False
                if not checked.gate:
                    # POPIA s26-33: a person's health or disciplinary details are not filed where everyone sees them
                    # without an owner deciding (restrict the branch, or file it on a restricted one)
                    hit = text.sensitive_about(ev, [x["name"] for x in people])
                    open_targets = [a.get("node_id") for a in checked.actions if a.get("node_id")
                                    and (self.graph.node(a["node_id"]) or {}).get("eff_level", EMPLOYEE) >= EMPLOYEE]
                    if hit and (open_targets or not checked.actions):
                        checked.gate, owners_only = "sensitive", True
                        checked.question = (f"This note names {hit[0]} with {hit[1]} details. File it only where "
                                            f"owners see it, or restrict the branch first?")
                row = {"capture_id": cid, "idx": idx, "text": ev,
                       "candidates": [{k: c[k] for k in ("node_id", "path", "score", "via")} for c in cands],
                       "routed": payload, "router": router_name,
                       "confidence": min([a.get("confidence", 0) for a in payload.get("actions", [])] or [0])}
                if checked.gate:
                    # Inbox: the speaker (an owner) or a manager decides; the proposal is kept so one tap applies it
                    opts = checked.options or [{"label": c["path"], "node_id": c["node_id"]} for c in cands[:3]]
                    inbox_id = new_id()
                    route = ([m.member_id for m in self._members(ws, OWNER) if m.member_id] if owners_only
                             else self._place_route(ws, principal))
                    with self.db.tx():  # one transaction: a retry after a crash must not ask twice
                        self.db.insert("inbox", {"id": inbox_id, "workspace_id": ws, "capture_id": cid, "event_idx": idx,
                                               "question": checked.question or f'Where should this go? "{ev}"',
                                               "options": opts, "event_text": ev,
                                               "proposal": {"actions": checked.actions, "reason": checked.gate,
                                                            "errors": checked.errors, "router": router_name},
                                               "state": "open", "resolution": None, "created_at": now_iso(),
                                               "resolved_at": None, "kind": "place", "author_member_id": author,
                                               "route_member_ids": route,
                                               "approver_level": OWNER if owners_only else held_level(principal)})
                        self._upsert_event(row, "needs_review")
                    self.broker.publish(ws, "inbox.created", {
                        "capture_id": cid, "idx": idx, "inbox_id": inbox_id, "text": ev, "reason": checked.gate,
                        "question": checked.question or f'Where should this go? "{ev}"', "options": opts,
                        "router": router_name, "kind": "place"}, author=author, route=route)
                    review += 1
                    results.append({"idx": idx, "state": "needs_review", "reason": checked.gate, "router": router_name})
                    continue
                # 6 apply: the Applier judges every action against the speaker's role (ADR 0014)
                res = self.applier.apply(ws, cid, idx, checked.actions, f"ai:{router_name}",
                                         {"router": router_name, "fallbacks": errors}, principal=principal, view=view)
                held = res.get("held") or []
                proposal = self._propose(ws, principal, held, cid, idx, ev) if held else None
                wrote = res.get("status") == "applied"
                self._upsert_event(row, "applied" if wrote else "needs_review")
                review += bool(proposal)
                results.append({"idx": idx, "state": "applied" if wrote else "needs_review", "router": router_name,
                                **{k: res.get(k) for k in ("notes", "tasks", "alerts", "delegated", "nodes")},
                                **({"proposal": proposal} if proposal else {}),
                                **({"refused": res["refused"]} if res.get("refused") else {})})
                if res.get("refused"):
                    self.broker.publish(ws, "action.refused", {"capture_id": cid, "idx": idx, "text": ev,
                                                               "refused": res["refused"]}, author=author)
                affected = self._with_ancestors(res.get("nodes", []))
                info = self._map_info(res.get("nodes", []))
                if wrote:
                    self.broker.publish(ws, "action.applied", {
                        "capture_id": cid, "idx": idx, "router": router_name, "node_ids": res.get("nodes", []),
                        "affected_node_ids": affected, "created_node_ids": sorted(res.get("created", {}).values()),
                        "nodes": info, "map_node_ids": sorted({i["map_id"] for i in info}),
                        "actions": [a["type"] for a in checked.actions if a not in held],
                        **({"proposal": proposal, "held": [describe(a, self.graph) for a in held]} if proposal else {}),
                        **({"notices": res["notices"]} if res.get("notices") else {}),
                        **{k: res.get(k) for k in ("notes", "tasks", "alerts", "delegated")}}, author=author)
                for nid in affected:
                    self._node_event(ws, nid, cid)
                note = next((a for a in checked.actions if a["type"] == "append_note" and a not in held), None)
                if note and wrote:
                    target = res["created"].get(note["node_id"], note["node_id"])
                    tn = self.graph.node(target)
                    previous = tn["parent_id"] if tn and tn["kind"] == "channel" else target
                    first = owner_principal(self.db, ws).member_id
                    self.companion.observe(ws, note["text"], self.graph.path_titles(target),
                                           member=author if author and author != first else None)
            held_at = (self.db.one("select min(approver_level) as h from inbox where capture_id=? and state='open'",
                                   (cid,)) or {}).get("h")
            self.graph.capture_level(cid, held_at)
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

    # ================================================================ proposals (ADR 0014)
    def _members(self, ws: str, max_level: int) -> list[Principal]:
        rows = self.db.query("select id from members where workspace_id=? and status='active' and level<=? "
                             "order by level, created_at", (ws, max_level))
        return [p for p in (load_principal(self.db, ws, r["id"]) for r in rows) if p]

    def _place_route(self, ws: str, author: Principal) -> list[str]:
        """Who may place a held note: its author, the owners, and for anyone below owner the managers too. A revoked
        member's: the owners alone (ADR 0014, question 2)."""
        if not author.active:
            return [p.member_id for p in self._members(ws, OWNER) if p.member_id]
        others = [p.member_id for p in self._members(ws, OWNER if author.level <= OWNER else MANAGER)]
        return [m for m in dict.fromkeys(([author.member_id] if author.member_id else []) + others) if m]

    def _approvers(self, ws: str, author: Principal, held: list[dict]) -> list[Principal]:
        """The managers whose branches cover every held action and who may do it themselves; else the owners. An
        owner's own CONFIRM (a delete) goes back to them."""
        made = {a["temp_id"] for a in held if a.get("type") == "create_node"}
        if not author.active:  # a revoked member's last notes: for an owner to look at (ADR 0014, question 2)
            return self._members(ws, OWNER)

        def can(p: Principal) -> bool:
            v = View(self.db, p, ws)
            return all(self.applier.judge(v, a, made)[0] in (ALLOW, CONFIRM) for a in held)
        managers = [p for p in self._members(ws, MANAGER) if p.level == MANAGER and p.member_id != author.member_id]
        picked = [p for p in managers if can(p)]
        if not picked:
            picked = [p for p in self._members(ws, OWNER) if p.member_id != author.member_id and can(p)]
        if not picked and author.level <= OWNER:
            picked = [author]
        return picked or self._members(ws, OWNER)

    def _propose(self, ws: str, author: Principal, held: list[dict], capture_id: str | None, event_idx: int | None,
                 event_text: str | None, kind: str = "approval", extra: dict | None = None,
                 to: list[Principal] | None = None) -> str:
        """Held actions become one Inbox item for the members who may approve them (`to`: a confirm by the speaker)."""
        approvers = to or (self._approvers(ws, author, held) if kind == "approval" else self._members(ws, OWNER))
        route = [p.member_id for p in approvers if p.member_id]
        what = "; ".join(describe(a, self.graph) for a in held)
        who = author.name or "Someone"
        question = (f"{who} asks you to confirm: {what}" if approvers and approvers[0].member_id == author.member_id
                    else f"{who} proposes: {what}")
        item_id = new_id()
        level = max((p.level for p in approvers), default=OWNER)
        with self.db.tx():
            self.db.insert("inbox", {"id": item_id, "workspace_id": ws, "capture_id": capture_id, "event_idx": event_idx,
                                     "question": question[:300], "options": [], "event_text": event_text,
                                     "proposal": {"actions": held, "author": author.member_id, **(extra or {})},
                                     "state": "open", "resolution": None, "created_at": now_iso(), "resolved_at": None,
                                     "kind": kind, "author_member_id": author.member_id, "route_member_ids": route,
                                     "approver_level": level})
            for p in approvers:
                if p.member_id and p.member_id != author.member_id:
                    self.db.insert("notifications", {"id": new_id(), "workspace_id": ws, "member_id": p.member_id,
                                                     "kind": "proposal", "payload": {"inbox_id": item_id, "text": question},
                                                     "created_at": now_iso(), "sent_at": None})
        nodes = [x for x in (node_of(a) for a in held) if x and not str(x).startswith("tmp:")]
        self.broker.publish(ws, "inbox.created", {"inbox_id": item_id, "capture_id": capture_id, "idx": event_idx,
                                                  "kind": kind, "question": question, "text": event_text,
                                                  "node_ids": nodes}, author=author.member_id, route=route)
        return item_id

    # ================================================================ spoken admin commands (admin.py, ADR 0014)
    def _find(self, ws: str, spoken: str, view: View) -> str | None:
        """The branch a command names: its exact title among what the speaker sees, else the best candidate."""
        want = spoken.strip().lower()
        for n in self.graph.nodes(ws):
            if n["title"].lower() == want and view.rows(n["id"]):
                return n["id"]
        cands = self.retriever.candidates(ws, spoken, view=view)
        return cands[0]["node_id"] if cands and cands[0]["score"] >= 0.6 else None

    def _admin(self, ws: str, cid: str, idx: int, ev: str, cmd: admin.Command, p: Principal, view: View) -> dict:
        row = {"capture_id": cid, "idx": idx, "text": ev, "candidates": [], "router": "admin", "confidence": 1.0}

        def say(text: str, state: str = "applied", **extra) -> dict:
            self._upsert_event({**row, "routed": {"admin": cmd.kind, "answer": text}}, state)
            self.broker.publish(ws, "capture.answer", {"capture_id": cid, "idx": idx, "text": text, **extra},
                                author=p.member_id)
            return {"idx": idx, "state": state, "router": "admin", "answer": text, **extra}

        def refuse(reason: str) -> dict:  # polite, and logged (decision 28)
            with self.db.tx():
                self.db.insert("action_log", {"id": new_id(), "workspace_id": ws, "capture_id": cid, "event_idx": idx,
                                              "seq": 0, "actor": "user:voice",
                                              "action": {"type": "refused", "action": cmd.kind, "reason": reason},
                                              "inverse": {"op": "none"}, "provenance": PROVENANCE, "undone_at": None,
                                              "created_at": now_iso(), "member_id": p.member_id,
                                              "member_level": p.level or None, "approved_by": None, "node_id": None})
            self.broker.publish(ws, "action.refused", {"capture_id": cid, "idx": idx, "text": ev,
                                                       "refused": [{"type": cmd.kind, "reason": reason}]},
                                author=p.member_id)
            return say(reason)

        if cmd.kind == "role":
            if p.decide("set_role") != ALLOW:
                return refuse("Only an owner can change someone's role.")
            from rapidfuzz import fuzz

            def score(m: dict) -> float:
                name = m["display_name"].lower()
                return max(fuzz.ratio(cmd.target.lower(), name), fuzz.ratio(cmd.target.lower(), name.split()[0]))
            members = [m for m in self.graph.members(ws) if m["status"] == "active"]
            best = max(members, key=score, default=None)
            if best is None or score(best) < 85:
                return say(f"I do not know who {cmd.target} is.")
            act = {"type": "set_role", "member_id": best["id"], "role": cmd.value, "name": best["display_name"]}
            item = self._propose(ws, p, [act], cid, idx, ev, to=[p])  # a misheard name must not change a role
            text = describe(act, self.graph)
            return say(f"{text[:1].upper()}{text[1:]}? Confirm it in the Inbox.", "needs_review",
                       proposal=item)
        if cmd.kind == "who" and p.level > MANAGER:
            return refuse("Only owners and managers can ask who sees a branch.")
        if cmd.kind == "visibility" and p.decide("set_visibility") == REFUSE:
            return refuse("Only owners and managers can change who sees a branch.")
        node = self._find(ws, cmd.target, view)
        if node is None:
            return say(f"I cannot find {cmd.target} on your map.")
        n = self.graph.node(node) or {}
        label = {"all": "visible to everyone", "manager": "for managers and owners", "owner": "for owners only"}
        if cmd.kind == "who":
            if p.level > MANAGER:
                return refuse("Only owners and managers can ask who sees a branch.")
            names = []
            for m in self.graph.members(ws):
                q = load_principal(self.db, ws, m["id"]) if m["status"] == "active" else None
                if q is not None and sees_row(q, n["path"], n["eff_level"]):
                    names.append(m["display_name"])
            lvl = {1: "owner", 2: "manager"}.get(n["eff_level"], "all")
            return say(f"{n['title']} is {label[lvl]}: {', '.join(names) or 'nobody yet'} can see it.")
        act = {"type": "set_visibility", "node_id": node, "visibility": cmd.value}
        outcome, reason = self.applier.judge(view, act, set())
        if outcome == REFUSE:
            return refuse(reason or "You cannot change who sees that branch.")
        if VISIBILITY[str(cmd.value)] < VISIBILITY.get(n.get("visibility") or "all", EMPLOYEE):  # tighter: at once
            res = self.applier.apply(ws, cid, idx, [act], "user:voice", principal=p, view=view, confirmed=True)
            if res.get("status") == "applied":
                for nid in self._with_ancestors([node]):
                    self._node_event(ws, nid, cid)
                return say(f"Done: {n['title']} is now {label[str(cmd.value)]}.")
            return refuse(res["refused"][0]["reason"] if res.get("refused") else "That needs someone else's approval.")
        item = self._propose(ws, p, [act], cid, idx, ev, to=[p])  # looser: confirm first
        return say(f"Make {n['title']} {label[str(cmd.value)]}? Confirm it in the Inbox.", "needs_review",
                   proposal=item)

    def change(self, principal: Principal, ws: str, actions: list[dict], *, actor: str = "user:app",
               confirmed: bool = True, text: str | None = None) -> dict:
        """An edit from the apps (rename, move, a task done, a new area ...), through the same Applier as a voice
        note: allowed parts are written, the rest proposed or refused. `confirmed`: the app asked the person first."""
        view = View(self.db, principal, ws)
        res = self.applier.apply(ws, None, None, actions, actor, principal=principal, view=view, confirmed=confirmed)
        if res.get("held"):
            res["proposal"] = self._propose(ws, principal, res["held"], None, None, text)
        if res.get("refused"):
            self.broker.publish(ws, "action.refused", {"refused": res["refused"], "text": text},
                                author=principal.member_id)
        for nid in self._with_ancestors(res.get("nodes", [])):
            self._node_event(ws, nid)
        return res

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

    def history(self, node_id: str, limit: int = 100, view: View | None = None) -> list[dict]:
        """The action log for one node (and its channels): what changed, from which note, by which router, undone."""
        n = self.graph.node(node_id)
        if n is None:
            raise KeyError(node_id)
        view = view or View(self.db, SYSTEM_PRINCIPAL, n["workspace_id"])
        if not view.rows(node_id):
            raise KeyError(node_id)
        ids = [node_id] + [c["id"] for c in self.graph.children(node_id) if c["kind"] == "channel" and view.rows(c["id"])]
        rows: list[dict] = []
        for i in ids:
            rows += self.db.query("select a.id, a.capture_id, a.event_idx, a.seq, a.actor, a.action, a.provenance, "
                                  "a.undone_at, a.created_at, a.member_id, a.approved_by, a.node_id, "
                                  "c.text as capture_text, c.source, c.member_id as cap_member, c.eff_level as cap_level, "
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
            if a.get("type") == "refused" and not view.audit(r):
                continue  # someone else's refused attempt is audit, not history
            # the whole capture (its text and recording) only for those who may see everything it touched
            whole = view.capture({"member_id": r["cap_member"], "eff_level": r["cap_level"]})
            prov = loads(r["provenance"], {}) or {}
            out.append({"id": r["id"], "at": r["created_at"], "type": a.get("type"), "capture_id": r["capture_id"],
                        "event_idx": r["event_idx"], "actor": r["actor"], "router": prov.get("router"),
                        "member_id": r["member_id"], "approved_by": r["approved_by"],
                        "undone": r["undone_at"] is not None, "capture_text": r["capture_text"] if whole else None,
                        "source": r["source"], "audio": bool(r["has_audio"]) and whole,
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

    # ================================================================ sync hooks (ADR 0014, decision 23)
    def sync_proposal(self, ch, reason: str) -> str | None:
        """A change from another worker that its author may no longer make: an Inbox item for the owners."""
        from .sync import sync_proposal
        iid = sync_proposal(self.db, ch, reason)
        if iid and ch.ws:
            item = self.db.one("select route_member_ids from inbox where id=?", (iid,))
            self.broker.publish(ch.ws, "inbox.created", {"inbox_id": iid, "kind": "sync", "text": reason},
                                author=ch.author_member_id, route=loads((item or {}).get("route_member_ids"), None))
        return iid

    def sync_refused(self, k: dict) -> None:
        """The hub would not take a change made here: its author sees why (a toast on their device)."""
        ws = None
        if k.get("current"):
            ws = k["current"].get("workspace_id")
        if ws is None and k.get("author_member_id"):
            ws = (self.db.one("select workspace_id from members where id=?", (k["author_member_id"],)) or {}).get("workspace_id")
        if ws:
            self.broker.publish(ws, "sync.refused", {"table": k["tbl"], "reason": k.get("reason"),
                                                     "proposal_id": k.get("proposal_id")},
                                author=k.get("author_member_id"))

    def after_sync(self, res: dict, peer: str | None) -> None:
        """Changes arrived from another worker: levels for the nodes they touched (and their captures), and the maps."""
        changed: list[str] = []
        with self.db.tx():
            for nid in res.get("touched", []):
                if self.graph.node(nid):
                    changed += self.graph.recompute_levels(nid)
            if changed:
                self.graph.relevel_captures(changed)
        for ws in res.get("workspaces", []):
            ids = [n for n in res.get("touched", []) if (self.graph.node(n) or {}).get("workspace_id") == ws]
            self.broker.publish(ws, "sync.applied", {"pulled": res.get("applied", 0), "node_ids": ids, "from": peer})

    def _with_ancestors(self, node_ids: list[str]) -> list[str]:
        """The changed nodes and every ancestor whose roll-up (counts, echo dot) changed with them."""
        out: list[str] = []
        for nid in node_ids:
            for n in [self.graph.node(nid)] + self.graph.ancestors(nid):
                if n and n["id"] not in out:
                    out.append(n["id"])
        return out

    def capture_audio(self, cid: str, view: View | None = None) -> Path:
        """The recording behind a capture (provenance: what the owner actually said). Only files under audio_dir, and
        only for those who may see the whole capture (ADR 0014)."""
        cap = self.db.one("select audio_path, workspace_id, member_id, eff_level from captures where id=?", (cid,))
        if cap is None or not cap["audio_path"] or (view is not None and (view.ws != cap["workspace_id"]
                                                                           or not view.capture(cap))):
            raise KeyError(cid)
        p = Path(cap["audio_path"]).resolve()
        if not p.is_file() or not p.is_relative_to(Path(self.settings.audio_dir).resolve()):
            raise KeyError(cid)
        return p

    def capture_summary(self, cid: str, view: View | None = None) -> dict:
        cap = self.db.one("select * from captures where id=?", (cid,))
        if cap is None or (view is not None and (view.ws != cap["workspace_id"] or not view.capture(cap))):
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
    def resolve_inbox(self, item_id: str, node_id: str | None = None, *, learn_alias: bool = True,
                      principal: Principal = SYSTEM_PRINCIPAL, decision: str | None = None,
                      reason: str | None = None) -> dict:
        """A held note placed on a branch (kind place), or a proposal approved or rejected (kind approval, sync).
        ADR 0014: only those the item is for may decide it, and they may approve only what they may do themselves."""
        item = self.db.one("select * from inbox where id=?", (item_id,))
        if item is None or item["state"] != "open":
            raise KeyError(item_id)
        ws = item["workspace_id"]
        view = View(self.db, principal, ws)
        if not view.inbox(item):
            raise KeyError(item_id)
        kind = item.get("kind") or "place"
        if kind != "place":
            if decision == "reject":
                return self.dismiss_inbox(item_id, principal=principal, reason=reason)
            return self._approve(item, principal, view)
        node = self.graph.node(node_id) if node_id else None
        if node_id is None or node is None or node["workspace_id"] != ws or not view.rows(node_id):
            raise GraphError("choose a node from this workspace")
        author = item.get("author_member_id")
        if principal.decide("place_note", in_scope=view.in_scope(node_id),
                            own=bool(author) and author == principal.member_id) != ALLOW:
            raise PermissionError("you cannot place this note there")
        teach = learn_alias and principal.decide("teach_alias", in_scope=view.in_scope(node_id)) == ALLOW
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
            kind_ = "problem" if sev else "done" if text.DONE.search(ev) else "todo" if text.TODO.search(ev) else "note"
            acts = build_actions(ctx, node_id=node_id, kind=kind_, severity=sev, note=ev[:1].upper() + ev[1:],
                                 task_title=None, due=text.parse_due(ev, ctx.captured_at, self.settings.timezone),
                                 assignee=assignee_from_text(ev), place_id=None, new_item=None, confidence=1.0)["actions"]
        res = self.applier.apply(ws, item["capture_id"], item["event_idx"], acts, "user:inbox", principal=principal,
                                 view=view, author=author or principal.member_id,
                                 approved_by=None if not author or author == principal.member_id else principal.member_id)
        held = res.get("held") or []
        with self.db.tx():
            # what placing it taught the brain is kept with the item, so Undo of the note takes the lesson back too
            correction = learned = None
            if teach:
                correction = new_id()
                self.db.insert("route_corrections", {"id": correction, "workspace_id": ws,
                                                     "phrase": item["event_text"] or "", "node_id": node_id,
                                                     "created_at": now_iso()})
                if item["event_text"]:
                    phrase = self._alias_phrase(item["event_text"], node)
                    if phrase:
                        self.graph.add_alias(node_id, phrase, weight=0.5)
                        learned = {"node_id": node_id, "alias": phrase.strip().lower(), "weight": 0.5}
            self.db.update("inbox", {"id": item_id}, {"state": "resolved", "resolved_at": now_iso(),
                                                      "decided_by": principal.member_id,
                                                      "resolution": {"node_id": node_id, "result": res.get("status"),
                                                                     "correction_id": correction, "learned_alias": learned}})
            self._settle_capture(item)
        if held:  # placing an employee's note that also changes things: the changes wait for a manager
            res["proposal"] = self._propose(ws, load_principal(self.db, ws, author) or principal, held,
                                            item["capture_id"], item["event_idx"], item["event_text"])
        self.broker.publish(ws, "inbox.resolved", {"inbox_id": item_id, "capture_id": item["capture_id"],
                                                   "node_id": node_id, "node_ids": res.get("nodes", [])},
                            author=author, route=loads(item.get("route_member_ids"), None))
        for nid in self._with_ancestors(res.get("nodes", [])):
            self._node_event(ws, nid, item["capture_id"])
        return {"resolved": item_id, **res}

    def _approve(self, item: dict, principal: Principal, view: View) -> dict:
        ws = item["workspace_id"]
        if principal.level > OWNER and principal.member_id not in (loads(item.get("route_member_ids"), []) or []):
            raise PermissionError("this proposal is for someone else")
        proposal = loads(item["proposal"], {}) or {}
        acts = proposal.get("actions", [])
        for a in [a for a in acts if a.get("type") == "set_role"]:  # a spoken role change, confirmed now
            self.people.set_role(principal, ws, a["member_id"], role=a["role"])
        acts = [a for a in acts if a.get("type") != "set_role"]
        if (item.get("kind") or "") == "sync":
            res = self.journal.apply_proposal(proposal.get("change") or {}, principal)
        elif not acts:
            res = {"status": "applied", "nodes": []}
        else:
            res = self.applier.apply(ws, item["capture_id"], item["event_idx"], acts,
                                     "user:approve", principal=principal, view=view,
                                     author=item.get("author_member_id") or principal.member_id,
                                     approved_by=principal.member_id or "system", confirmed=True)
            if res.get("held") or (res.get("refused") and res.get("status") != "applied"):
                raise PermissionError("you cannot approve this yourself: " +
                                      "; ".join(r["reason"] for r in res.get("refused", [])) if res.get("refused") else
                                      "it needs someone who may do it")
        with self.db.tx():
            self.db.update("inbox", {"id": item["id"]}, {"state": "resolved", "resolved_at": now_iso(),
                                                         "decided_by": principal.member_id,
                                                         "resolution": {"approved_by": principal.member_id,
                                                                        "result": res.get("status")}})
            self._settle_capture(item)
        if item["capture_id"]:
            held = (self.db.one("select min(approver_level) as h from inbox where capture_id=? and state='open'",
                                (item["capture_id"],)) or {}).get("h")
            self.graph.capture_level(item["capture_id"], held)
        self.broker.publish(ws, "inbox.resolved", {"inbox_id": item["id"], "capture_id": item["capture_id"],
                                                   "approved": True, "node_ids": res.get("nodes", [])},
                            author=item.get("author_member_id"), route=loads(item.get("route_member_ids"), None))
        for nid in self._with_ancestors(res.get("nodes", [])):
            self._node_event(ws, nid, item["capture_id"])
        return {"resolved": item["id"], "approved": True, **res}

    def _settle_capture(self, item: dict) -> None:
        """The capture behind an Inbox item is applied once nothing of it waits any more."""
        if item["capture_id"] and item["event_idx"] is not None:
            self.db.update("capture_events", {"capture_id": item["capture_id"], "idx": item["event_idx"]},
                           {"state": "applied"})
        if item["capture_id"]:
            left = self.db.one("select count(*) as c from inbox where capture_id=? and state='open'", (item["capture_id"],))
            if left["c"] == 0:
                self.db.update("captures", {"id": item["capture_id"]}, {"state": "applied", "updated_at": now_iso()})

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

    def dismiss_inbox(self, item_id: str, *, principal: Principal = SYSTEM_PRINCIPAL, reason: str | None = None) -> dict:
        """Dismiss a held note, or reject a proposal (its author is told why)."""
        item = self.db.one("select * from inbox where id=?", (item_id,))
        if item is None:
            raise KeyError(item_id)
        if not View(self.db, principal, item["workspace_id"]).inbox(item):
            raise KeyError(item_id)
        self.db.update("inbox", {"id": item_id}, {"state": "dismissed", "resolved_at": now_iso(),
                                                  "decided_by": principal.member_id,
                                                  "resolution": {"rejected_by": principal.member_id, "reason": reason}})
        if item["state"] == "open" and item.get("kind") in ("approval", "sync"):
            self.broker.publish(item["workspace_id"], "inbox.resolved",
                                {"inbox_id": item_id, "capture_id": item["capture_id"], "rejected": True,
                                 "reason": reason}, author=item.get("author_member_id"),
                                route=loads(item.get("route_member_ids"), None))
        return {"dismissed": item_id}

    def undo(self, cid: str, principal: Principal = SYSTEM_PRINCIPAL) -> dict:
        cap = self.db.one("select workspace_id, member_id from captures where id=?", (cid,))
        if cap is None:
            raise KeyError(cid)
        rows = self.db.query("select action, node_id from action_log where capture_id=? and undone_at is null", (cid,))
        touched: list[str] = []
        for r in rows:
            a = loads(r["action"], {}) or {}
            for k in ("node_id", "src_id", "dst_id", "parent_id"):
                if a.get(k) and a[k] not in touched and not str(a[k]).startswith("tmp:"):
                    touched.append(a[k])
        if principal.level != SYSTEM:  # ADR 0014: your own capture, or one in the branches you manage
            view = View(self.db, principal, cap["workspace_id"])
            own = bool(cap["member_id"]) and cap["member_id"] == principal.member_id
            here = [t for t in touched if self.graph.node(t)]
            if not own and not all(view.rows(t) for t in here):
                raise KeyError(cid)
            if principal.decide("undo", in_scope=all(view.in_scope(t) for t in here), own=own) != ALLOW:
                raise PermissionError("you can undo only your own notes")
        created = [(loads(r["action"], {}) or {}).get("node_id") for r in rows
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
            "affected_node_ids": self._with_ancestors(alive)}, author=cap["member_id"])
        for nid in self._with_ancestors(alive):
            self._node_event(cap["workspace_id"], nid, cid)
        return {"capture_id": cid, "reverted": n, "node_ids": alive}

    # ================================================================ tasks, alerts, numbers, structure by hand
    def _outcome(self, res: dict, what: str) -> None:
        """An edit from the apps that was refused outright raises; one held for approval returns its proposal."""
        if res.get("status") == "refused":
            raise PermissionError(res["refused"][0]["reason"] if res.get("refused") else f"you cannot {what}")

    def update_task(self, task_id: str, *, state: str | None = None, assignee_member: str | None = None,
                    due_at: str | None = None, principal: Principal = SYSTEM_PRINCIPAL) -> dict:
        t = self.db.one("select * from tasks where id=?", (task_id,))
        if t is None:
            raise KeyError(task_id)
        if assignee_member is not None and not self.db.one("select 1 from members where id=? and workspace_id=?",
                                                           (assignee_member, t["workspace_id"])):
            raise GraphError("unknown member")
        a: dict = {"type": "update_task", "id": task_id}
        if state:
            a["state"] = state
        if due_at is not None:
            a["due_at"] = due_at
        if assignee_member is not None:
            a["assignee_member"] = assignee_member
        res = self.change(principal, t["workspace_id"], [a], text=f"task: {t['title']}")
        self._outcome(res, "change this task")
        row = self.db.one("select * from tasks where id=?", (task_id,)) or {}
        if res.get("status") == "applied":
            self.broker.publish(t["workspace_id"], "task.updated",
                                {"task_id": task_id, "node_id": t["node_id"],
                                 **{k: row.get(k) for k in ("state", "done_at", "due_at", "assignee_member") if k in a
                                    or (k == "done_at" and "state" in a)}})
        return {**row, **({"proposal": res["proposal"]} if res.get("proposal") else {})}

    def set_attributes(self, node_id: str, changes: dict, principal: Principal = SYSTEM_PRINCIPAL) -> dict:
        """The owner edits a node's numbers on the map (area, planted, progress); the map and the companion follow.
        null removes a number."""
        n = self.graph.node(node_id)
        if n is None:
            raise KeyError(node_id)
        res = self.change(principal, n["workspace_id"], [{"type": "update_attributes", "node_id": node_id,
                                                          "set": changes}], text=f"numbers on {n['title']}")
        self._outcome(res, "change these numbers")
        n = self.graph.node(node_id) or n
        if res.get("status") == "applied":
            self.broker.publish(n["workspace_id"], "node.updated", {
                "node_id": node_id, "attributes": n["attributes"], "status": n["status"],
                "display_status": n["display_status"], "child_worst": n["child_worst"], "open_tasks": n["open_tasks"],
                "open_alerts": n["open_alerts"]})
        return n["attributes"] if not res.get("proposal") else {**n["attributes"], "_proposal": res["proposal"]}

    def resolve_alert(self, alert_id: str, principal: Principal = SYSTEM_PRINCIPAL) -> dict:
        a = self.db.one("select * from alerts where id=?", (alert_id,))
        if a is None:
            raise KeyError(alert_id)
        res = self.change(principal, a["workspace_id"], [{"type": "resolve_alert", "id": alert_id}],
                          text=f"alert: {a['title']}")
        self._outcome(res, "resolve this alert")
        if res.get("proposal"):
            return {"proposal": res["proposal"]}
        self.broker.publish(a["workspace_id"], "alert.updated", {"alert_id": alert_id, "node_id": a["node_id"],
                                                                 "resolved": True})
        return {"resolved": alert_id}

    # ================================================================ read models
    # ADR 0014: each takes the caller's View; without one it is the brain's own (everything). A node, task or capture
    # the caller may not see is "not found".
    def view(self, ws: str, principal: Principal = SYSTEM_PRINCIPAL) -> View:
        return View(self.db, principal, ws)

    def keyterms(self, ws: str, view: View | None = None, limit: int = 100) -> list[str]:
        """The words speech-to-text should expect: titles and aliases the speaker can see (so a restricted name
        never reaches their transcript), plus the owner's own vocabulary for the owner."""
        view = view or self.view(ws)
        terms: list[str] = []
        for n in self.graph.nodes(ws):
            if n["kind"] not in ("root", "channel") and view.rows(n["id"]):
                terms.append(n["title"])
        for nid, al in self.graph.all_aliases(ws).items():
            if view.rows(nid):
                terms += [a for a, _ in sorted(al, key=lambda x: -x[1])]
        if view.all:
            terms += self.companion.keyterms(ws)
        seen, out = set(), []
        for t in terms:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out[:limit]

    def node_detail(self, node_id: str, view: View | None = None) -> dict:
        n = self.graph.node(node_id)
        if n is None:
            raise KeyError(node_id)
        view = view or self.view(n["workspace_id"])
        if view.ws != n["workspace_id"] or not view.node(node_id):
            raise KeyError(node_id)
        kids = [{"id": c["id"], "title": c["title"], "kind": c["kind"], "display_status": c["display_status"]}
                for c in self.graph.children(node_id) if view.node(c["id"])]
        if not view.rows(node_id):  # a path stub: what it is called and what is under it, nothing more
            return {"id": n["id"], "workspace_id": n["workspace_id"], "parent_id": n["parent_id"], "kind": n["kind"],
                    "title": n["title"], "path": n["path"], "depth": n["depth"], "stub": True,
                    "path_titles": self.graph.path_titles(node_id), "aliases": [], "notes": [], "tasks": [],
                    "alerts": [], "edges": [], "children": kids}
        return {**n, "path_titles": self.graph.path_titles(node_id), "aliases": self.graph.aliases(node_id),
                "notes": self.db.query("select * from notes where node_id=? order by created_at desc limit 100", (node_id,)),
                "tasks": self.db.query("select * from tasks where node_id=? order by state, created_at desc", (node_id,)),
                "alerts": self.db.query("select * from alerts where node_id=? order by created_at desc", (node_id,)),
                "edges": [e for e in self.db.query("select * from edges where src_id=? or dst_id=?", (node_id, node_id))
                          if view.edge(e["src_id"], e["dst_id"])],
                "children": kids}

    def tasks(self, ws: str, state: str | None = "open", assignee: str | None = None,
              view: View | None = None) -> list[dict]:
        sql = ("select t.*, m.display_name as assignee_name from tasks t left join members m on m.id=t.assignee_member "
               "where t.workspace_id=?")
        args: list = [ws]
        if state:
            sql += " and t.state=?"
            args.append(state)
        if assignee:
            sql += " and t.assignee_member=?"
            args.append(assignee)
        view = view or self.view(ws)
        rows = [r for r in self.db.query(sql + " order by t.due_at is null, t.due_at, t.created_at", args)
                if view.rows(r["node_id"])]
        for r in rows:
            r["path"] = self.graph.path_titles(r["node_id"])
        return rows

    def alerts(self, ws: str, open_only: bool = True, view: View | None = None) -> list[dict]:
        view = view or self.view(ws)
        sql = "select * from alerts where workspace_id=?" + (" and resolved_at is null" if open_only else "")
        return [a for a in self.db.query(sql + " order by created_at desc", (ws,)) if view.rows(a["node_id"])]

    def inbox(self, ws: str, view: View | None = None) -> list[dict]:
        view = view or self.view(ws)
        return [i for i in self.db.query("select * from inbox where workspace_id=? and state='open' order by created_at",
                                         (ws,)) if view.inbox(i)]

    def notifications(self, ws: str, member: str | None = None, unsent: bool = True,
                      view: View | None = None) -> list[dict]:
        view = view or self.view(ws)
        if not view.all:
            member = view.p.member_id  # a member reads their own, whatever they ask for
        sql, args = "select * from notifications where workspace_id=?", [ws]
        if member:
            sql += " and member_id=?"
            args.append(member)
        if unsent:
            sql += " and sent_at is null"
        return self.db.query(sql + " order by created_at", args)

    def members(self, ws: str, view: View | None = None) -> list[dict]:
        view = view or self.view(ws)
        return [view.member(m) for m in self.graph.members(ws)]

    def audit(self, ws: str, view: View | None = None, limit: int = 200) -> list[dict]:
        """action_log as the caller may read it: owners everything, managers their scope and their own, employees their
        own (ADR 0014, decision 29). Refusals included."""
        view = view or self.view(ws)
        rows = self.db.query("select * from action_log where workspace_id=? order by created_at desc limit ?",
                             (ws, limit * 5 if not view.all else limit))
        out = []
        for r in rows:
            if view.audit(r):
                out.append({**r, "action": loads(r["action"], {}), "inverse": None,
                            "provenance": loads(r["provenance"], {})})
            if len(out) >= limit:
                break
        return out

    def mindmap(self, ws: str, view: View | None = None, **kw) -> dict:
        from . import mindmap
        return mindmap.build(self, ws, view=view, **kw)

    def digest(self, ws: str, focus: str | None = None, view: View | None = None) -> dict:
        """What is open right now, plus the map's facts (what needs work, how far along things are); the companion
        uses this for 'what do I still need to do?', 'which tractors need work?', 'how much is planted?'.
        focus: the node the owner has open on the map, so 'this one' in a question means that node. ADR 0014: all of
        it as the asking member sees it."""
        from . import mindmap
        view = view or self.view(ws)
        alerts = self.alerts(ws, view=view)
        for a in alerts:
            a["path"] = self.graph.path_titles(a["node_id"])
        mm = mindmap.build(self, ws, view=view)
        out_focus = None
        if focus and view.rows(focus):
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
        captures = [c for c in self.db.query("select id, state, text, created_at, member_id, eff_level from captures "
                                             "where workspace_id=? order by created_at desc limit 50", (ws,))
                    if view.capture(c)][:10]
        return {"tasks": self.tasks(ws, view=view), "alerts": alerts, "map": mindmap.summary(mm), "focus": out_focus,
                "inbox": [{k: i[k] for k in ("id", "question", "event_text", "created_at")} for i in self.inbox(ws, view)],
                "recent_captures": [{k: c[k] for k in ("id", "state", "text", "created_at")} for c in captures]}

    # ================================================================ archive and remove a workspace
    WS_TABLES = ["members", "nodes", "edges", "captures", "notes", "tasks", "alerts", "profile_facts", "inbox",
                 "action_log", "notifications", "route_corrections", "member_scopes", "seats", "invites", "devices"]

    def export_workspace(self, ws: str, view: View | None = None) -> dict:
        """Everything in one workspace as plain rows (the archive written before a workspace is removed). ADR 0014: a
        member's export holds what they can see, and nobody's export holds a device token hash."""
        w = self.graph.workspace(ws)
        if w is None:
            raise KeyError(ws)
        view = view or self.view(ws)
        out: dict = {"format": "notecad-workspace-archive/1", "exported_at": now_iso(), "provenance": PROVENANCE,
                     "workspace": w, "tables": {}}
        t = out["tables"]
        for name in self.WS_TABLES:
            t[name] = self.db.query(f"select * from {name} where workspace_id=?", (ws,))
        t["devices"] = [{k: v for k, v in d.items() if k != "token_hash"} for d in t["devices"]]
        t["invites"] = [{k: v for k, v in i.items() if k != "code_hash"} for i in t["invites"]]
        if not view.all:
            t["nodes"] = [{k: n[k] for k in ("id", "workspace_id", "parent_id", "path", "depth", "kind", "title")}
                          if view.stub(n["id"]) else n for n in t["nodes"] if view.node(n["id"])]
            for name in ("notes", "tasks", "alerts", "route_corrections"):
                t[name] = [r for r in t[name] if view.rows(r["node_id"])]
            t["edges"] = [e for e in t["edges"] if view.edge(e["src_id"], e["dst_id"])]
            t["captures"] = [c for c in t["captures"] if view.capture(c)]
            t["members"] = [view.member(m) for m in t["members"]]
            t["profile_facts"] = [f for f in t["profile_facts"] if view.fact(f.get("visibility"))]
            t["inbox"] = [i for i in t["inbox"] if view.inbox(i)]
            t["action_log"] = [a for a in t["action_log"] if view.audit(a)]
            t["notifications"] = [x for x in t["notifications"] if x["member_id"] == view.p.member_id]
            t["member_scopes"] = [s for s in t["member_scopes"] if view.p.level <= MANAGER
                                  or s["member_id"] == view.p.member_id]
            t["seats"] = [s for s in t["seats"] if view.p.level == MANAGER and s["role_level"] == EMPLOYEE
                          and s["status"] == "available"]
            t["invites"] = [i for i in t["invites"] if i.get("created_by") == view.p.member_id]
            t["devices"] = [d for d in t["devices"] if d["member_id"] == view.p.member_id]
        node_ids = [n["id"] for n in t["nodes"] if view.rows(n["id"])]
        cap_ids = [c["id"] for c in t["captures"]]
        t["node_aliases"] = [r for i in node_ids for r in self.db.query("select * from node_aliases where node_id=?", (i,))]
        t["capture_events"] = [r for i in cap_ids for r in self.db.query("select * from capture_events where capture_id=?", (i,))]
        return out

    def delete_workspace(self, ws: str) -> dict:
        """Remove a workspace and everything in it, its recorded audio included. Not reversible: archive first.
        The sync journal keeps no copy of it afterwards: only the deletes (tombstones, no data) stay, so that every
        other worker deletes it too (POPIA review, fix 2)."""
        if self.graph.workspace(ws) is None:
            raise KeyError(ws)
        counts: dict[str, int] = {}
        caps = [c["id"] for c in self.db.query("select id from captures where workspace_id=?", (ws,))]
        members = [m["id"] for m in self.db.query("select id from members where workspace_id=?", (ws,))]
        with self.db.tx():
            for cid in caps:
                self.db.execute("delete from jobs where payload like ?", (f'%{cid}%',))
                self.db.execute("delete from capture_events where capture_id=?", (cid,))
            for t in ["edges", "notes", "tasks", "alerts", "profile_facts", "inbox", "action_log", "notifications",
                      "route_corrections", "captures", "member_scopes", "invites", "devices", "seats"]:
                counts[t] = self.db.execute(f"delete from {t} where workspace_id=?", (ws,))
            nodes = self.db.query("select id from nodes where workspace_id=? order by depth desc", (ws,))
            for n in nodes:  # deepest first: children before parents
                self.db.execute("delete from node_aliases where node_id=?", (n["id"],))
                self.db.execute("delete from node_embeddings where node_id=?", (n["id"],))
                self.db.execute("delete from nodes where id=?", (n["id"],))
            counts["nodes"] = len(nodes)
            counts["members"] = self.db.execute("delete from members where workspace_id=?", (ws,))
            self.db.execute("delete from workspaces where id=?", (ws,))
            node_ids = [n["id"] for n in nodes]
            for i in range(0, len(node_ids), 500):
                part = node_ids[i:i + 500]
                self.db.execute(f"delete from sync_conflicts where node_id in ({', '.join('?' for _ in part)})", part)
            self.db.execute("delete from view_changes where ws=?", (ws,))
            self.db.execute("delete from sync_rejects where change like ?", (f'%"{ws}"%',))
            counts["journal"] = self.db.execute("delete from sync_changes where ws=? and op<>'D'", (ws,))
            self.db.execute("update sync_changes set row=null where ws=? and op='D' and row is not null", (ws,))
        for m in members:  # what each member's own companion learned (POPIA: no copy left behind)
            self.companion.forget(ws, None, [], wipe=m)
        self.companion.forget(ws, None, [], before=time.time() + 1)
        audio = Path(self.settings.audio_dir) / ws
        if audio.is_dir():
            import shutil
            shutil.rmtree(audio, ignore_errors=True)
        self.broker.publish(ws, "workspace.deleted", {"counts": counts})
        logging.getLogger("notecad.security").warning("workspace deleted ws=%s counts=%s", ws, counts)
        return {"deleted": ws, "counts": counts}

    def onboard(self, ws: str, answer: str, apply: bool = True) -> dict:
        spine = onboarding.propose(answer, self.onboarding_llm)
        created = onboarding.apply_spine(self.graph, ws, spine) if apply else 0
        return {"proposal": spine, "created": created}
