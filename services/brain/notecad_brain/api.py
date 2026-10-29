# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Brain HTTP API.   uvicorn notecad_brain.api:app --host 127.0.0.1 --port 8788

Every route is served under /v1/... and, for the app, also under /api/v1/... (same handlers)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import threading
from contextlib import asynccontextmanager
import time

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from . import __version__
from .common import PROVENANCE, now_iso
from .events import for_view
from .config import Settings
from .graph import GraphError
from .permissions import (ALLOW, OWNER, ROLES, Principal, View, capabilities, load_principal,
                          owner_principal)
from .people import handin_ok
from .pipeline import AUDIO_EXT, Brain, CaptureConflict

log = logging.getLogger("notecad.brain")

AUDIO_TYPES = set(AUDIO_EXT) | {"application/ogg"}
EXT_TYPES = {".wav": "audio/wav", ".webm": "audio/webm", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".oga": "audio/ogg",
             ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac"}


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    owner_name: str = "Owner"
    persona: str | None = None
    workspace_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class OnboardIn(BaseModel):
    answer: str = Field(min_length=3, max_length=4000)
    apply: bool = True


class MemberIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    role: str = Field(default="employee", pattern="^(owner|manager|employee|editor|viewer)$")  # editor, viewer: Phase 1 names
    contact: str | None = None
    person_node_id: str | None = None


class NodeIn(BaseModel):
    parent_id: str
    title: str = Field(min_length=1, max_length=80)
    kind: str = "topic"
    aliases: list[str] = []


class NodePatch(BaseModel):
    title: str | None = None
    parent_id: str | None = None
    add_aliases: list[str] = []
    attributes: dict | None = None  # merged into the node's numbers (area_ha, planted_ha, progress_pct...); null removes a key


class CaptureIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    capture_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{8,64}$")
    recorded_at: str | None = None
    source: str = "phone"
    lang_hint: str | None = None
    geo: dict | None = None
    wait: bool = True  # process now and return the result (False: queue for the worker)


class CaptureAny(BaseModel):
    """POST /capture: text, or audio (multipart file / raw body), plus the node open on the map while recording."""
    text: str | None = Field(default=None, max_length=8000)
    capture_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{8,64}$")
    recorded_at: str | None = None
    source: str = "phone"
    lang_hint: str | None = Field(default=None, max_length=16)
    geo: dict | None = None
    context_node_id: str | None = Field(default=None, max_length=64)
    wait: bool | None = None  # default: typed notes are processed now, audio is queued for the worker


class SyncPushIn(BaseModel):
    worker: str = Field(min_length=1, max_length=120)
    changes: list[dict] = Field(max_length=5000)


class SyncAckIn(BaseModel):
    worker: str = Field(min_length=1, max_length=120)
    cursor: int = Field(ge=0)
    workspaces: list[str] | None = None


class ResolveIn(BaseModel):
    node_id: str | None = None  # where a held note goes (kind place)
    decision: str | None = Field(default=None, pattern="^(approve|reject)$")  # a proposal (ADR 0014)
    reason: str | None = Field(default=None, max_length=500)


class DismissIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class VisibilityIn(BaseModel):
    visibility: str = Field(pattern="^(all|manager|owner)$")


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    context_node_id: str | None = Field(default=None, max_length=64)


class SeatsIn(BaseModel):
    role: str = Field(pattern="^(manager|employee)$")
    count: int = Field(default=1, ge=1, le=100)


class InviteIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(default="employee", pattern="^(manager|employee)$")
    contact: str | None = Field(default=None, max_length=120)
    person_node_id: str | None = Field(default=None, max_length=64)
    scope_node_ids: list[str] = Field(default=[], max_length=20)
    hours: int = Field(default=72, ge=1, le=168)


class JoinIn(BaseModel):
    code: str = Field(min_length=6, max_length=64)
    device_name: str = Field(default="Phone", max_length=60)
    platform: str | None = Field(default=None, max_length=20)


class RoleIn(BaseModel):
    role: str | None = Field(default=None, pattern="^(owner|manager|employee)$")
    scope_node_ids: list[str] | None = Field(default=None, max_length=20)


class TaskPatch(BaseModel):
    state: str | None = Field(default=None, pattern="^(open|done|cancelled)$")
    assignee_member: str | None = None
    due_at: str | None = None


def create_app(brain: Brain | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or (brain.settings if brain else Settings())
    brain = brain or Brain(settings)
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(_app):
        if settings.worker:  # background worker: queued captures are processed while the phone waits on events
            brain.recover_jobs()  # captures a killed brain left half done

            def loop():
                next_decay = 0.0
                while not stop.is_set():
                    try:
                        if time.monotonic() >= next_decay:  # info rings and done marks fade without anyone asking
                            next_decay = time.monotonic() + 600
                            brain.decay_all()
                        if brain.run_jobs() == 0:
                            stop.wait(0.5)
                    except Exception:
                        log.exception("worker loop")
                        stop.wait(2)
            threading.Thread(target=loop, name="notecad-worker", daemon=True).start()
        warm = getattr(brain.stt, "warm", None)
        if warm is not None and settings.worker:  # load the speech model now, not on the owner's first note
            app.state.stt_ready = False

            def warm_up():
                try:
                    warm()
                    app.state.stt_ready = True
                except Exception as ex:
                    app.state.stt_ready = f"{type(ex).__name__}: {ex}"[:200]
            threading.Thread(target=warm_up, name="notecad-stt-warm", daemon=True).start()
        if settings.worker:
            brain.sync.start()  # background push / pull when NC_BRAIN_SYNC_TARGET is set
        yield
        stop.set()
        brain.sync.stop()

    app = FastAPI(title="NoteCad Brain", version=__version__, lifespan=lifespan,
                  description="Voice note -> branch, note, task, alert, delegation. Policy 986 AED | License AED 900.")
    app.state.brain = brain
    app.state.stt_ready = None  # None: no speech engine to warm; False: loading; True: ready; str: error
    origins = [o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()]
    if origins:
        from .tus import ALLOW as TUS_ALLOW, EXPOSE as TUS_EXPOSE
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"],
                           allow_headers=["Authorization", "Content-Type", "Last-Event-ID", *TUS_ALLOW],
                           expose_headers=TUS_EXPOSE, allow_credentials=False)
    r = APIRouter()

    LOOPBACK = {"127.0.0.1", "::1", "localhost"}
    _ips: list[str] = []

    def lan_ips() -> list[str]:
        if not _ips:
            try:
                import socket as _s
                _ips.extend(str(a[-1][0]) for a in _s.getaddrinfo(_s.gethostname(), None, _s.AF_INET))
            except OSError:
                pass
            _ips.append("-")  # looked once
        return _ips

    def is_local(request: Request) -> bool:
        return bool(request.client) and request.client.host in LOOPBACK

    def local_host(request: Request) -> bool:
        """The Host this PC's own clients use: loopback names, or this PC's LAN address when phones are on."""
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in LOOPBACK or host == settings.bind_host or host in lan_ips()

    allowed_origins = set(origins)

    DEVICE = "nct_"  # a per-device token (ADR 0014); the brain keeps only its SHA-256
    HANDIN = re.compile(r"^(/api)?/v1/(workspaces/[^/]+/(capture|uploads)(/[^/]+)?|device/wiped)$")
    joins: dict[str, list[float]] = {}  # client address -> recent join attempts (at most 10 a minute)
    REVOKED = {"code": "revoked", "wipe": True, "detail": "this device was removed from the business: its copy is wiped"}

    def bearer(request: Request) -> str | None:
        hdr = request.headers.get("authorization") or ""
        if hdr.startswith("Bearer "):
            return hdr[7:].strip()
        if request.method in ("GET", "HEAD"):  # only where a header cannot be set: EventSource, <audio src>
            return request.query_params.get("token")
        return None

    def token_ok(request: Request) -> bool:
        """The shared token (NC_BRAIN_API_TOKEN): other brains, and phones paired before seats."""
        if not settings.api_token:
            return False
        tok = bearer(request)
        return tok is not None and hmac.compare_digest(tok.encode(), settings.api_token.encode())

    def device_of(request: Request) -> dict | None:
        """A device token: its device row, or 410 with the order to wipe when the device or its member was revoked."""
        tok = bearer(request)
        if not tok or not tok.startswith(DEVICE):
            return None
        d = brain.db.one("select * from devices where token_hash=?", (hashlib.sha256(tok.encode()).hexdigest(),))
        if d is None:
            raise HTTPException(401, "missing or wrong token")
        m = brain.db.one("select status from members where id=?", (d["member_id"],))
        if d["revoked_at"] or m is None or m["status"] != "active":
            # a revoked phone may still hand in what it recorded before (held for an owner) and say it has wiped
            if not HANDIN.match(request.url.path) or request.method not in ("POST", "PATCH", "HEAD"):
                raise HTTPException(410, REVOKED)
            request.state.revoked_at = d["revoked_at"] or now_iso()
        now = now_iso()
        if (d.get("last_seen_at") or "")[:16] != now[:16]:  # at most once a minute
            brain.db.update("devices", {"id": d["id"]}, {"last_seen_at": now})
        return d

    def check_auth(request: Request) -> None:
        """This PC is trusted (the desktop app needs no token); phones and other workers on the LAN send the token
        as a Bearer header, or ?token= on a GET where a header cannot be set (EventSource). Plain HTTP: LAN or VPN
        only. A web page open on this PC is not trusted: a change sent from a browser origin that is not one of
        NoteCad's own needs the token (a multipart POST needs no CORS preflight, so CORS alone does not stop it).
        ADR 0014: a device token is looked at first and names the member everything is done as."""
        d = device_of(request)
        if d is not None:
            request.state.device = d
            return
        origin = request.headers.get("origin")
        foreign = (origin is not None and origin not in allowed_origins
                   and request.method not in ("GET", "HEAD", "OPTIONS"))
        if token_ok(request):
            return
        if foreign:
            raise HTTPException(403, "this origin may not change NoteCad without the token")
        if is_local(request) and not local_host(request):
            # a page on this PC whose name was pointed at 127.0.0.1 (DNS rebinding) sends no Origin on a GET; its
            # Host is its own name, not this PC's, so without the token it reads nothing
            raise HTTPException(403, "use http://127.0.0.1 or localhost on this PC, or send the token")
        if not settings.api_token or (settings.trust_loopback and is_local(request)):
            return
        raise HTTPException(401, "missing or wrong token")

    def auth(request: Request) -> None:
        check_auth(request)

    def device(request: Request) -> dict | None:
        return getattr(request.state, "device", None)

    def local_principal(ws: str) -> Principal:
        if settings.local_member:
            p = load_principal(brain.db, ws, settings.local_member)
            if p is not None and p.active:
                return p
        return owner_principal(brain.db, ws)

    def who(request: Request, ws: str) -> Principal:
        """The member a request acts for in a workspace, from its credential alone (ADR 0014, decision 4): a device's
        member, the first owner for the shared token (question 3) and for this PC (or NC_BRAIN_LOCAL_MEMBER)."""
        d = device(request)
        if d is not None:
            if d["workspace_id"] != ws:
                raise HTTPException(404, "no such workspace")
            p = load_principal(brain.db, ws, d["member_id"], d["id"])
            if p is None or (not p.active and getattr(request.state, "revoked_at", None) is None):
                raise HTTPException(410, REVOKED)
        elif token_ok(request):
            if not settings.legacy_token_owner:
                raise HTTPException(403, "this phone was paired with the shared token: pair it again with a seat")
            p = owner_principal(brain.db, ws)
        else:
            p = local_principal(ws)
        as_member = request.query_params.get("as_member")
        if as_member and request.method in ("GET", "HEAD") and p.level <= OWNER:
            # the companion reading for a member: an owner (or this PC) may look as anyone, which only ever shows less
            q = load_principal(brain.db, ws, as_member)
            if q is None:
                raise HTTPException(404, "no such member")
            return q
        return p

    def view_of(request: Request, ws: str) -> View:
        return View(brain.db, who(request, ws), ws)

    def worker_only(request: Request) -> None:
        """/v1/sync/*: between brains (the shared token, or this PC), never from a member's device."""
        if device(request) is not None:
            raise HTTPException(403, "sync is between brains")

    def ws_ok(ws: str) -> str:
        if brain.graph.workspace(ws) is None:
            raise HTTPException(404, "no such workspace")
        return ws

    def ws_of(table: str, row_id: str) -> str:
        r = brain.db.one(f"select workspace_id from {table} where id=?", (row_id,))
        if r is None:
            raise HTTPException(404, "not found")
        return r["workspace_id"]

    def need(p: Principal, action: str, what: str) -> None:
        if p.decide(action) != ALLOW:
            raise HTTPException(403, f"you cannot {what}")

    def guard(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError:
            raise HTTPException(404, "not found")
        except PermissionError as e:
            raise HTTPException(403, str(e) or "not allowed")
        except CaptureConflict as e:
            raise HTTPException(409, str(e))
        except GraphError as e:
            raise HTTPException(400, str(e))

    def changed(res: dict, ok):
        """An edit from the apps: refused (403 with the reason), held for approval (202 with the proposal), or done."""
        if res.get("status") == "refused":
            raise HTTPException(403, res["refused"][0]["reason"] if res.get("refused") else "not allowed")
        if res.get("status") == "held" or (res.get("proposal") and not res.get("nodes")):
            return JSONResponse({"proposal": res.get("proposal"), "detail": "waiting for approval"}, status_code=202)
        return ok()

    A = [Depends(auth)]
    W = [Depends(auth), Depends(worker_only)]

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "db": brain.db.kind, "routers": brain.routers.name,
                "stt": getattr(brain.stt, "name", None), "stt_ready": app.state.stt_ready,
                "stt_device": next((getattr(e, "active_device", None) for e in getattr(brain.stt, "engines", [brain.stt])
                                    if getattr(e, "active_device", None)), None),
                "embedder": getattr(brain.embedder, "name", None),
                "provenance": PROVENANCE}

    # ---------------------------------------------------------------- workspaces, people, onboarding
    @r.post("/v1/workspaces", dependencies=A)
    def create_ws(body: WorkspaceIn, request: Request):
        if device(request) is not None:
            raise HTTPException(403, "a new business is made on the owner's PC")
        return brain.graph.create_workspace(body.name, persona=body.persona, owner_name=body.owner_name,
                                            workspace_id=body.workspace_id)

    @r.get("/v1/workspaces", dependencies=A)
    def list_ws(request: Request):
        rows = brain.db.query("select w.id, w.name, w.persona, w.created_at, (select count(*) from nodes n where "
                              "n.workspace_id=w.id) as nodes from workspaces w order by w.created_at desc")
        d = device(request)
        if d is not None:  # a member's device knows one business, and only what it sees of it
            v = view_of(request, d["workspace_id"])
            rows = [{**w, "nodes": len(v.rows_ids | v.stub_ids) if not v.all else w["nodes"]}
                    for w in rows if w["id"] == d["workspace_id"]]
        return rows

    @r.get("/v1/workspaces/{ws}/me", dependencies=A)
    def me(ws: str, request: Request):
        """Who this app is acting as, and what it may offer them (the brain still decides every request)."""
        p = who(request, ws_ok(ws))
        return {"workspace_id": ws, "member_id": p.member_id, "name": p.name, "level": p.level,
                "role": ROLES.get(p.level), "read_only": p.read_only, "scopes": list(p.scopes),
                "device_id": p.device_id, "capabilities": capabilities(p)}

    @r.get("/v1/workspaces/{ws}/export", dependencies=A)
    def export_ws(ws: str, request: Request):
        ws_ok(ws)
        v = view_of(request, ws)
        need(v.p, "export", "export this business")
        return guard(brain.export_workspace, ws, v)

    @r.delete("/v1/workspaces/{ws}", dependencies=A)
    def delete_ws(ws: str, request: Request, confirm: str | None = None):
        """Removes the workspace and all its notes, tasks and audio. ?confirm=<workspace id> is required."""
        if confirm != ws:
            raise HTTPException(400, "add ?confirm=<workspace id> to remove a workspace")
        need(who(request, ws_ok(ws)), "manage_workspace", "remove this business")
        return guard(brain.delete_workspace, ws)

    @r.get("/v1/workspaces/{ws}", dependencies=A)
    def get_ws(ws: str, request: Request):
        row = brain.graph.workspace(ws_ok(ws)) or {}
        return {**row, "root_id": brain.graph.root(ws)["id"], "members": brain.members(ws, view_of(request, ws))}

    @r.post("/v1/workspaces/{ws}/onboard", dependencies=A)
    def onboard(ws: str, body: OnboardIn, request: Request):
        need(who(request, ws_ok(ws)), "manage_workspace", "lay out the business")
        return brain.onboard(ws, body.answer, body.apply)

    @r.post("/v1/workspaces/{ws}/members", dependencies=A)
    def add_member(ws: str, body: MemberIn, request: Request):
        need(who(request, ws_ok(ws)), "set_role", "add people")
        return {"id": guard(brain.graph.add_member, ws, body.display_name, role=body.role, contact=body.contact,
                            person_node_id=body.person_node_id)}

    @r.get("/v1/workspaces/{ws}/members", dependencies=A)
    def members(ws: str, request: Request):
        return brain.members(ws_ok(ws), view_of(request, ws))

    @r.get("/v1/workspaces/{ws}/audit", dependencies=A)
    def audit(ws: str, request: Request, limit: int = Query(default=200, ge=1, le=1000)):
        """Who did what (ADR 0014): owners everything, managers their branches and their own, employees their own."""
        return brain.audit(ws_ok(ws), view_of(request, ws), limit)

    # ---------------------------------------------------------------- the graph
    @r.get("/v1/workspaces/{ws}/tree", dependencies=A)
    def tree(ws: str, request: Request):
        v = view_of(request, ws_ok(ws))
        return brain.graph.tree(ws, keep=None if v.all else v.node)

    @r.post("/v1/workspaces/{ws}/nodes", dependencies=A)
    def add_node(ws: str, body: NodeIn, request: Request):
        p = who(request, ws_ok(ws))
        act = {"type": "create_node", "temp_id": "tmp:new", "parent_id": body.parent_id, "title": body.title,
               "kind": body.kind, "aliases": body.aliases}
        res = guard(brain.change, p, ws, [act], text=f'new branch "{body.title}"')
        return changed(res, lambda: {"id": res["created"]["tmp:new"]})

    def node_ws(request: Request, node_id: str) -> tuple[str, View]:
        ws = ws_of("nodes", node_id)
        v = view_of(request, ws)
        if not v.node(node_id):
            raise HTTPException(404, "not found")
        return ws, v

    @r.get("/v1/nodes/{node_id}", dependencies=A)
    def node(node_id: str, request: Request):
        _, v = node_ws(request, node_id)
        return guard(brain.node_detail, node_id, v)

    @r.get("/v1/nodes/{node_id}/history", dependencies=A)
    def node_history(node_id: str, request: Request, limit: int = Query(default=100, ge=1, le=500)):
        _, v = node_ws(request, node_id)
        return guard(brain.history, node_id, limit, v)

    @r.patch("/v1/nodes/{node_id}", dependencies=A)
    def patch_node(node_id: str, body: NodePatch, request: Request):
        ws, v = node_ws(request, node_id)
        acts: list[dict] = []
        if body.title:
            acts.append({"type": "rename_node", "node_id": node_id, "title": body.title})
        if body.parent_id:
            acts.append({"type": "move_node", "node_id": node_id, "parent_id": body.parent_id})
        acts += [{"type": "add_alias", "node_id": node_id, "alias": a} for a in body.add_aliases]
        if body.attributes:
            acts.append({"type": "update_attributes", "node_id": node_id, "set": body.attributes})
        if not acts:
            return guard(brain.node_detail, node_id, v)
        res = guard(brain.change, v.p, ws, acts, text=f"edit {brain.graph.node(node_id)['title']}")
        return changed(res, lambda: brain.node_detail(node_id, View(brain.db, v.p, ws)))

    @r.delete("/v1/nodes/{node_id}", dependencies=A)
    def delete_node(node_id: str, request: Request):
        ws, v = node_ws(request, node_id)
        if brain.graph.node(node_id)["kind"] == "root":
            raise HTTPException(400, "cannot delete")
        res = guard(brain.change, v.p, ws, [{"type": "delete_node", "node_id": node_id}],
                    text=f"delete {brain.graph.node(node_id)['title']}")
        return changed(res, lambda: {"deleted": node_id})

    @r.post("/v1/nodes/{node_id}/visibility", dependencies=A)
    def set_visibility(node_id: str, body: VisibilityIn, request: Request):
        """Who may see a branch: all, manager (managers and owners), owner (owners only). ADR 0014, decision 15."""
        ws, v = node_ws(request, node_id)
        res = guard(brain.change, v.p, ws, [{"type": "set_visibility", "node_id": node_id,
                                             "visibility": body.visibility}],
                    text=f"who can see {brain.graph.node(node_id)['title']}")
        return changed(res, lambda: brain.node_detail(node_id, View(brain.db, v.p, ws)))

    # ---------------------------------------------------------------- captures
    @r.post("/v1/workspaces/{ws}/captures", dependencies=A)
    def capture_text(ws: str, body: CaptureIn, request: Request):
        p = who(request, ws_ok(ws))
        r = guard(brain.register_capture, ws, text=body.text, capture_id=body.capture_id, recorded_at=body.recorded_at,
                  source=body.source, lang_hint=body.lang_hint, geo=body.geo, enqueue=not body.wait, principal=p)
        if body.wait and not r["duplicate"]:
            return brain.process(r["capture_id"])
        return brain.capture_summary(r["capture_id"], View(brain.db, p, ws)) if r["duplicate"] else r

    @r.post("/v1/workspaces/{ws}/captures/audio", dependencies=A)
    async def capture_audio(ws: str, request: Request, capture_id: str | None = None, recorded_at: str | None = None,
                            source: str = "phone", lang_hint: str | None = None):
        p = who(request, ws_ok(ws))
        audio = await request.body()
        if not audio:
            raise HTTPException(400, "empty body")
        if len(audio) > 25 * 1024 * 1024:
            raise HTTPException(413, "audio over 25 MB")
        return guard(brain.register_capture, ws, audio=audio, mime=request.headers.get("content-type"),
                     capture_id=capture_id, recorded_at=recorded_at, source=source, lang_hint=lang_hint, principal=p)

    def capture_view(request: Request, cid: str) -> View:
        return view_of(request, ws_of("captures", cid))

    @r.get("/v1/captures/{cid}", dependencies=A)
    def capture(cid: str, request: Request):
        return guard(brain.capture_summary, cid, capture_view(request, cid))

    @r.get("/v1/captures/{cid}/audio", dependencies=A)
    def capture_audio_file(cid: str, request: Request):
        """The recording, for playback in the node's history. <audio src> cannot send a header: ?token= on a GET."""
        from fastapi.responses import FileResponse
        p = guard(brain.capture_audio, cid, capture_view(request, cid))
        return FileResponse(p, media_type=EXT_TYPES.get(p.suffix.lower(), "application/octet-stream"),
                            headers={"Cache-Control": "private, max-age=3600"})

    @r.post("/v1/captures/{cid}/undo", dependencies=A)
    def undo(cid: str, request: Request):
        return guard(brain.undo, cid, who(request, ws_of("captures", cid)))

    # ---------------------------------------------------------------- inbox, tasks, alerts, notifications
    @r.get("/v1/workspaces/{ws}/inbox", dependencies=A)
    def inbox(ws: str, request: Request):
        return brain.inbox(ws_ok(ws), view_of(request, ws))

    @r.post("/v1/inbox/{item_id}/resolve", dependencies=A)
    def resolve(item_id: str, body: ResolveIn, request: Request):
        """A held note placed on a branch (node_id), or a proposal approved or rejected (decision, ADR 0014)."""
        p = who(request, ws_of("inbox", item_id))
        return guard(brain.resolve_inbox, item_id, body.node_id, principal=p, decision=body.decision,
                     reason=body.reason)

    @r.post("/v1/inbox/{item_id}/dismiss", dependencies=A)
    def dismiss(item_id: str, request: Request, body: DismissIn | None = None):
        p = who(request, ws_of("inbox", item_id))
        guard(brain.dismiss_inbox, item_id, principal=p, reason=body.reason if body else None)
        return {"dismissed": item_id}

    @r.get("/v1/workspaces/{ws}/tasks", dependencies=A)
    def tasks(ws: str, request: Request, state: str | None = "open", assignee: str | None = None):
        return brain.tasks(ws_ok(ws), state or None, assignee, view_of(request, ws))

    @r.patch("/v1/tasks/{task_id}", dependencies=A)
    def patch_task(task_id: str, body: TaskPatch, request: Request):
        ws = ws_of("tasks", task_id)
        p = who(request, ws)
        t = brain.db.one("select node_id from tasks where id=?", (task_id,))
        if not View(brain.db, p, ws).rows(t["node_id"]):
            raise HTTPException(404, "not found")
        out = guard(brain.update_task, task_id, state=body.state, assignee_member=body.assignee_member,
                    due_at=body.due_at, principal=p)
        if out.get("proposal"):
            return JSONResponse({"proposal": out["proposal"], "detail": "waiting for approval"}, status_code=202)
        return out

    @r.get("/v1/workspaces/{ws}/alerts", dependencies=A)
    def alerts(ws: str, request: Request, open_only: bool = True):
        return brain.alerts(ws_ok(ws), open_only, view_of(request, ws))

    @r.post("/v1/alerts/{alert_id}/resolve", dependencies=A)
    def resolve_alert(alert_id: str, request: Request):
        ws = ws_of("alerts", alert_id)
        p = who(request, ws)
        a = brain.db.one("select node_id from alerts where id=?", (alert_id,))
        if not View(brain.db, p, ws).rows(a["node_id"]):
            raise HTTPException(404, "not found")
        out = guard(brain.resolve_alert, alert_id, p)
        if out.get("proposal"):
            return JSONResponse({**out, "detail": "waiting for approval"}, status_code=202)
        return out

    @r.get("/v1/workspaces/{ws}/notifications", dependencies=A)
    def notifications(ws: str, request: Request, member: str | None = None, unsent: bool = True):
        return brain.notifications(ws_ok(ws), member, unsent, view_of(request, ws))

    @r.get("/v1/workspaces/{ws}/digest", dependencies=A)
    def digest(ws: str, request: Request, focus: str | None = None):
        return brain.digest(ws_ok(ws), focus=focus, view=view_of(request, ws))

    @r.post("/v1/workspaces/{ws}/ask", dependencies=A)
    async def ask(ws: str, body: AskIn, request: Request):
        """The companion, for a member on another device (ADR 0014, decision 13): the brain checks who is asking and
        that the node they have open is theirs to see, then asks the companion on this PC as that member."""
        p = who(request, ws_ok(ws))
        if body.context_node_id and not View(brain.db, p, ws).rows(body.context_node_id):
            raise HTTPException(404, "not found")
        if not settings.companion_url:
            raise HTTPException(503, "no companion on this brain")
        first = owner_principal(brain.db, ws).member_id
        import httpx
        async with httpx.AsyncClient(timeout=60) as c:
            res = await c.post(f"{settings.companion_url.rstrip('/')}/v1/{ws}/chat",
                               json={"text": body.text, "context_node_id": body.context_node_id,
                                     **({"as_member": p.member_id} if p.member_id and p.member_id != first else {})})
        if res.status_code >= 400:
            raise HTTPException(502, "the companion did not answer")
        return res.json()

    # ---------------------------------------------------------------- mind map (Phase 2)
    @r.get("/v1/workspaces/{ws}/mindmap", dependencies=A)
    def mindmap(ws: str, request: Request, tasks: bool = True, notes: int = Query(default=3, ge=0, le=20)):
        """The whole map, UI-ready: root, categories with roll-ups, entities with status, echo dot, decay, reminders
        and progress, open tasks as leaves, People / Delegation; edges belongs_to_category, has_task, assigned_to,
        related_to. `cursor` is the last live-event id: open the event stream with Last-Event-ID = cursor.
        ADR 0014: as the caller sees it."""
        return brain.mindmap(ws_ok(ws), view=view_of(request, ws), tasks=tasks, notes_per_node=notes)

    # ---------------------------------------------------------------- one capture endpoint (Phase 2)
    async def _capture_any(ws: str, request: Request):
        """multipart/form-data (file or audio = WAV / WebM / Opus / Ogg / MP3 / M4A, and/or text, context_node_id,
        capture_id, recorded_at, source, lang_hint, wait), application/json (same fields), or a raw audio/* body
        (fields as query parameters). context_node_id: the node open on the map while recording; it and its
        neighbours are preferred when the brain decides where the note goes."""
        ws_ok(ws)
        principal = who(request, ws)
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        fields: dict = {k: v for k, v in request.query_params.items() if k != "token"}
        audio = mime = None
        if ctype in ("multipart/form-data", "application/x-www-form-urlencoded"):
            form = await request.form()
            request.state.form = form  # closed below: its temp files are released at once
            for key, val in form.multi_items():
                if not isinstance(val, str):  # an uploaded file
                    if key in ("file", "audio") and audio is None:
                        audio = await val.read()
                        mime = (val.content_type or "").split(";")[0].strip().lower()
                        if mime not in AUDIO_TYPES:
                            ext = "." + (val.filename or "").rsplit(".", 1)[-1].lower() if "." in (val.filename or "") else ""
                            mime = EXT_TYPES.get(ext, mime)
                elif val != "":
                    fields[key] = val
        elif ctype == "application/json":
            try:
                body = await request.json()
            except ValueError:
                raise HTTPException(400, "body is not JSON")
            if not isinstance(body, dict):
                raise HTTPException(400, "send a JSON object")
            fields.update(body)
        elif ctype in AUDIO_TYPES:
            audio, mime = await request.body(), ctype
        else:
            raise HTTPException(415, "send multipart/form-data, application/json or an audio/* body")
        if isinstance(fields.get("wait"), str):
            fields["wait"] = fields["wait"].lower() in ("1", "true", "yes", "on")
        try:
            body = CaptureAny(**fields)
        except ValidationError as e:
            return JSONResponse({"detail": e.errors(include_url=False, include_context=False)}, status_code=422)
        text = (body.text or "").strip() or None
        if audio is not None:
            if not audio:
                raise HTTPException(400, "empty audio")
            if len(audio) > settings.max_audio_mb * 1024 * 1024:
                raise HTTPException(413, f"audio over {settings.max_audio_mb} MB")
            if mime not in AUDIO_TYPES:
                raise HTTPException(415, f"unsupported audio type {mime or '?'}: use WAV, WebM, Opus/Ogg, MP3 or M4A")
        elif not text:
            raise HTTPException(422, "send text or an audio file")
        rev = getattr(request.state, "revoked_at", None)
        if rev is not None and not handin_ok(rev, body.recorded_at):
            raise HTTPException(410, REVOKED)  # recorded after the revoke, or handed in too late
        wait = body.wait if body.wait is not None else audio is None
        reg = await run_in_threadpool(guard, brain.register_capture, ws, text=None if audio is not None else text,
                                      audio=audio, mime=mime, capture_id=body.capture_id, recorded_at=body.recorded_at,
                                      source=body.source, lang_hint=body.lang_hint, geo=body.geo,
                                      enqueue=not wait, context_node_id=body.context_node_id, principal=principal)
        cid = reg["capture_id"]
        links = {"status_url": f"/v1/captures/{cid}", "events_url": f"/v1/workspaces/{ws}/events/stream",
                 "context_node_id": body.context_node_id}
        if reg["duplicate"]:
            return {**brain.capture_summary(cid, View(brain.db, principal, ws)), "duplicate": True, **links}
        if wait:
            try:
                res = await run_in_threadpool(brain.process, cid)
            except Exception as ex:  # the capture is marked failed and the event stream says why
                raise HTTPException(422 if "STTError" in type(ex).__name__ else 500, f"{type(ex).__name__}: {ex}")
            return {**res, **links}
        return JSONResponse({**reg, **links}, status_code=202)

    @r.post("/v1/workspaces/{ws}/capture", dependencies=A)
    async def capture_any(ws: str, request: Request):
        """multipart/form-data (file or audio = WAV / WebM / Opus / Ogg / MP3 / M4A, and/or text, context_node_id,
        capture_id, recorded_at, source, lang_hint, wait), application/json (same fields), or a raw audio/* body
        (fields as query parameters). context_node_id: the node open on the map while recording; it and its
        neighbours are preferred when the brain decides where the note goes."""
        try:
            return await _capture_any(ws, request)
        finally:
            form = getattr(request.state, "form", None)
            if form is not None:
                await form.close()

    @r.get("/v1/workspaces/{ws}/sync", dependencies=A)
    def sync(ws: str):
        return brain.sync_status(ws_ok(ws))

    @r.get("/v1/workspaces/{ws}/keyterms", dependencies=A)
    def keyterms(ws: str, request: Request):
        return {"keyterms": brain.keyterms(ws_ok(ws), view_of(request, ws))}

    @r.post("/v1/workspaces/{ws}/maintenance", dependencies=A)
    def maintenance(ws: str, request: Request):
        need(who(request, ws_ok(ws)), "manage_workspace", "run maintenance")
        return {"decayed": brain.graph.decay(ws)}

    # ---------------------------------------------------------------- multi-worker sync (this brain as a hub)
    @r.get("/v1/sync/status", dependencies=W)
    def sync_status():
        return {"ok": True, **brain.sync.status()}

    @r.post("/v1/sync/push", dependencies=W)
    def sync_push(body: SyncPushIn):
        """Another worker (a desktop, an Edge AI Node) sends the changes it made. ADR 0014: each is checked against its
        author's role here, now; one that is not allowed is not applied, and goes back with the reason and this hub's
        row so the sender can put its own back."""
        res = brain.journal.receive(body.changes, via=body.worker,
                                    on_applied=lambda ids: brain.graph.rollup(sorted(ids)), check=True,
                                    propose=brain.sync_proposal)
        brain.after_sync(res, body.worker)
        return {"hub": brain.journal.worker_id, **{k: v for k, v in res.items() if k != "touched"}}

    @r.get("/v1/sync/pull", dependencies=W)
    def sync_pull(worker: str, since: int = Query(default=0, ge=0), limit: int = Query(default=500, ge=1, le=5000),
                  workspaces: str | None = None):
        """Another worker asks for everything after its cursor that it did not make itself."""
        ws = [w for w in (workspaces or "").split(",") if w] or None
        changes, cursor, more = brain.journal.to_serve(worker, since, limit, ws)
        return {"hub": brain.journal.worker_id, "changes": [c.as_dict() for c in changes], "cursor": cursor, "more": more}

    @r.post("/v1/sync/ack", dependencies=W)
    def sync_ack(body: SyncAckIn):
        """A worker has applied everything up to its pull cursor: the notes it took from here are synced."""
        return {"hub": brain.journal.worker_id, "marked": brain.journal.ack(body.worker, body.cursor, body.workspaces)}

    @r.post("/v1/sync/now", dependencies=W)
    async def sync_now():
        return await run_in_threadpool(brain.sync.run_once)

    # ---------------------------------------------------------------- live events (server-sent events)
    @r.get("/v1/workspaces/{ws}/events/stream", dependencies=A)
    @r.get("/v1/workspaces/{ws}/events", dependencies=A, include_in_schema=False)
    async def events(ws: str, request: Request, last_event_id: int | None = Query(default=None, ge=0),
                     types: str | None = None, limit: int | None = Query(default=None, ge=1),
                     last_event_header: str | None = Header(default=None, alias="Last-Event-ID")):
        """capture.queued, stt.transcribing, stt.completed, router.resolving, action.applied, inbox.created,
        capture.completed, capture.failed, action.undone, node.updated, task.updated, alert.updated, inbox.resolved,
        action.refused. Reconnect with Last-Event-ID (header, or ?last_event_id=) to get what was missed. ?types=a,b
        filters by name or prefix (types=stt,action); ?limit=n closes the stream after n events. ADR 0014: only what
        the caller may see; a change to their role or scope closes the stream, and they reconnect with the new view."""
        ws_ok(ws)
        view = view_of(request, ws)
        start = last_event_id
        if start is None and last_event_header and last_event_header.strip().isdigit():
            start = int(last_event_header.strip())
        want = [t.strip() for t in (types or "").split(",") if t.strip()]

        def wanted(m: dict) -> dict | None:
            if want and not any(m["type"] == w or m["type"].startswith(w + ".") for w in want):
                return None
            return for_view(m, view)

        q = brain.broker.subscribe(ws)  # subscribe before replay, so nothing falls in between

        async def gen():
            nonlocal view
            sent, last = 0, start or 0
            if last > brain.broker.last_id:  # an id this brain never sent (it restarted): everything new is wanted
                last = 0
            try:
                yield "retry: 2000\n\n"
                backlog = brain.broker.since(ws, start) if start is not None else []
                for msg in backlog:
                    last = max(last, msg["id"])
                    out = wanted(msg)
                    if out is not None:
                        yield brain.broker.sse(out)
                        sent += 1
                        if limit and sent >= limit:
                            return
                while not await request.is_disconnected():
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        if not view.all or view.p.level != 0:
                            now_p = load_principal(brain.db, ws, view.p.member_id) if view.p.member_id else view.p
                            if now_p is None or (now_p.level, now_p.scopes, now_p.active, now_p.read_only) != \
                                    (view.p.level, view.p.scopes, view.p.active, view.p.read_only):
                                return  # their role changed: the app reconnects and gets the new view
                            if not view.all:
                                view.refresh()
                        yield f": keep-alive {int(time.time())}\n\n"
                        continue
                    if msg["id"] <= last:
                        continue
                    last = msg["id"]
                    out = wanted(msg)
                    if out is None:
                        continue
                    yield brain.broker.sse(out)
                    sent += 1
                    if limit and sent >= limit:
                        return
            finally:
                brain.broker.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------------- phones: resumable uploads and pairing
    from . import tus
    if settings.upload_dir is None:
        from pathlib import Path as _P
        settings.upload_dir = str(_P(settings.audio_dir).parent / "uploads")
    tr = tus.router(brain, settings, check_auth, ws_ok, who)
    r.include_router(tr)

    # ---------------------------------------------------------------- people: seats, invites, joining, devices
    def lan_urls(port: int) -> list[str]:
        import socket
        ips: list[str] = []
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("192.0.2.1", 9))  # picks the LAN interface; sends nothing
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
        try:
            for *_, addr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = str(addr[0])
                if ip not in ips and not ip.startswith("127."):
                    ips.append(ip)
        except OSError:
            pass
        return [f"http://{ip}:{port}" for ip in ips]

    def brain_urls(request: Request) -> list[str]:
        """Where a phone reaches this brain: this PC's LAN addresses when asked here, else the address that was used."""
        if is_local(request) and local_host(request):
            return lan_urls(request.url.port or 8788) or [str(request.base_url).rstrip("/")]
        return [str(request.base_url).rstrip("/")]

    def throttle(request: Request) -> None:
        """The join routes need no token: at most 10 tries a minute from one address."""
        ip = request.client.host if request.client else "?"
        now = time.monotonic()
        recent = [t for t in joins.get(ip, []) if now - t < 60]
        if len(recent) >= 10:
            raise HTTPException(429, "too many tries: wait a minute")
        joins[ip] = recent + [now]

    @r.get("/v1/workspaces/{ws}/seats", dependencies=A)
    def seats(ws: str, request: Request):
        return brain.people.seats(who(request, ws_ok(ws)), ws)

    @r.post("/v1/workspaces/{ws}/seats", dependencies=A)
    def add_seats(ws: str, body: SeatsIn, request: Request):
        """An owner adds seats by hand (the local ledger: no billing provider yet)."""
        return {"seats": guard(brain.people.add_seats, who(request, ws_ok(ws)), ws, body.role, body.count)}

    @r.post("/v1/seats/{seat_id}/remove", dependencies=A)
    def remove_seat(seat_id: str, request: Request):
        return guard(brain.people.remove_seat, who(request, ws_of("seats", seat_id)), seat_id)

    @r.get("/v1/workspaces/{ws}/invites", dependencies=A)
    def invites(ws: str, request: Request):
        return brain.people.invites(who(request, ws_ok(ws)), ws)

    @r.post("/v1/workspaces/{ws}/invites", dependencies=A)
    def invite(ws: str, body: InviteIn, request: Request):
        """A one-time code for a free seat, with the person's profile. The code and the join links are in this answer
        only (the brain keeps a hash): show them as a QR now."""
        p = who(request, ws_ok(ws))
        return guard(brain.people.invite, p, ws, name=body.name, role=body.role, contact=body.contact,
                     person_node_id=body.person_node_id, scope_node_ids=body.scope_node_ids, hours=body.hours,
                     base_urls=brain_urls(request))

    @r.post("/v1/invites/{invite_id}/revoke", dependencies=A)
    def revoke_invite(invite_id: str, request: Request):
        return guard(brain.people.revoke_invite, who(request, ws_of("invites", invite_id)), invite_id)

    @r.get("/v1/join")
    def join_preview(request: Request, c: str = Query(min_length=6, max_length=64)):
        """What joining with this code means, for the phone to show before anything happens. No token needed."""
        throttle(request)
        try:
            return brain.people.preview(c)
        except KeyError:
            raise HTTPException(404, "this invite is not valid: it was used, it expired, or the code is wrong")

    @r.post("/v1/join")
    def join(body: JoinIn, request: Request):
        """Join with an invite code: the member, their seat, and this device's own token (shown once). No token
        needed: the one-time code is the proof."""
        throttle(request)
        try:
            return brain.people.join(body.code, body.device_name, body.platform)
        except KeyError:
            raise HTTPException(404, "this invite is not valid: it was used, it expired, or the code is wrong")
        except GraphError as e:
            raise HTTPException(409, str(e))

    @r.patch("/v1/members/{member_id}", dependencies=A)
    def set_role(member_id: str, body: RoleIn, request: Request):
        ws = ws_of("members", member_id)
        return guard(brain.people.set_role, who(request, ws), ws, member_id, role=body.role,
                     scope_node_ids=body.scope_node_ids)

    @r.post("/v1/members/{member_id}/revoke", dependencies=A)
    def revoke_member(member_id: str, request: Request):
        """They leave: their devices stop at once and wipe on their next contact; the seat is free again."""
        ws = ws_of("members", member_id)
        return guard(brain.people.revoke_member, who(request, ws), ws, member_id)

    @r.get("/v1/workspaces/{ws}/devices", dependencies=A)
    def devices(ws: str, request: Request):
        return brain.people.devices(who(request, ws_ok(ws)), ws)

    @r.post("/v1/devices/{device_id}/revoke", dependencies=A)
    def revoke_device(device_id: str, request: Request):
        return guard(brain.people.revoke_device, who(request, ws_of("devices", device_id)), device_id)

    # ---------------------------------------------------------------- a member's device copy (ADR 0014, decision 21)
    def on_device(request: Request) -> Principal:
        d = device(request)
        if d is None:
            raise HTTPException(403, "this is for a member's device (a device token)")
        return who(request, d["workspace_id"])

    @r.get("/v1/device/snapshot", dependencies=A)
    def device_snapshot(request: Request):
        """Everything this member may see now, and a cursor for /device/pull."""
        return brain.devices.snapshot(on_device(request))

    @r.get("/v1/device/pull", dependencies=A)
    def device_pull(request: Request, cursor: str | None = None, limit: int = Query(default=500, ge=1, le=2000)):
        """What changed since the cursor, as this member may see it now; tombstones for what they no longer may;
        reset: true when they should wipe and take a new snapshot."""
        return brain.devices.pull(on_device(request), cursor, limit)

    @r.post("/v1/device/wiped", dependencies=A)
    def device_wiped(request: Request):
        """A revoked phone says it has wiped its copy (the owner sees it confirmed)."""
        d = device(request)
        if d is None:
            raise HTTPException(403, "this is for a member's device")
        brain.db.update("devices", {"id": d["id"]}, {"wipe_acked_at": now_iso()})
        return {"wiped": True}

    @r.get("/v1/pairing")
    def pairing(request: Request, ws: str | None = None):
        """For the desktop app only: what a phone needs to connect (shown as a QR code to scan with the phone)."""
        if not is_local(request) or not local_host(request):  # this PC, by its own name (no rebound domain)
            raise HTTPException(403, "pairing is only shown on this PC")
        from urllib.parse import urlencode
        lan = settings.bind_host not in ("127.0.0.1", "localhost", "::1")
        urls = lan_urls(request.url.port or 8788)  # also the addresses an invite's join link carries (ADR 0014)
        wss = brain.db.query("select id, name from workspaces order by created_at desc")
        target = ws or (wss[0]["id"] if wss else None)
        links = [f"notecad://pair?{urlencode({'u': u, 't': settings.api_token or '', 'w': target or ''})}" for u in urls]
        return {"lan": lan, "token_set": bool(settings.api_token), "urls": urls, "workspace": target,
                "workspaces": wss, "links": links,
                "ready": lan and bool(settings.api_token) and bool(urls),
                "hint": None if lan and settings.api_token else
                "Start with: services\\start_notecad.ps1 -Lan (listens on the LAN and sets a phone token in the vault)"}

    app.include_router(r)
    app.include_router(r, prefix="/api", include_in_schema=False)

    # the desktop app (apps/desktop, built with `npm run build`) at http://127.0.0.1:8788/app/
    from pathlib import Path
    ui = Path(settings.ui_dir) if settings.ui_dir else Path(__file__).resolve().parents[3] / "apps" / "desktop" / "dist"
    if settings.ui_dir != "" and (ui / "index.html").exists():
        from fastapi.responses import RedirectResponse
        from fastapi.staticfiles import StaticFiles
        app.mount("/app", StaticFiles(directory=ui, html=True), name="app")

        @app.get("/", include_in_schema=False)
        def to_app():
            return RedirectResponse("/app/")

    @app.get("/api/health", include_in_schema=False)
    def api_health():
        return health()

    return app


def __getattr__(name: str):
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
