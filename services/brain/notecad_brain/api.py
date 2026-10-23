# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Brain HTTP API.   uvicorn notecad_brain.api:app --host 127.0.0.1 --port 8788

Every route is served under /v1/... and, for the app, also under /api/v1/... (same handlers)."""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
import time

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from . import __version__
from .common import PROVENANCE
from .config import Settings
from .graph import GraphError
from .pipeline import AUDIO_EXT, Brain

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
    role: str = Field(default="editor", pattern="^(owner|editor|viewer)$")
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


class ResolveIn(BaseModel):
    node_id: str


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
            def loop():
                while not stop.is_set():
                    try:
                        if brain.run_jobs() == 0:
                            stop.wait(0.5)
                    except Exception:
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

    def is_local(request: Request) -> bool:
        return bool(request.client) and request.client.host in LOOPBACK

    def check_auth(request: Request) -> None:
        """This PC is trusted (the desktop app needs no token); phones and other workers on the LAN send the token
        as a Bearer header, or ?token= where a header cannot be set (EventSource). Plain HTTP: LAN or VPN only."""
        if not settings.api_token or (settings.trust_loopback and is_local(request)):
            return
        hdr = request.headers.get("authorization")
        if hdr != f"Bearer {settings.api_token}" and request.query_params.get("token") != settings.api_token:
            raise HTTPException(401, "missing or wrong token")

    def auth(request: Request) -> None:
        check_auth(request)

    def ws_ok(ws: str) -> str:
        if brain.graph.workspace(ws) is None:
            raise HTTPException(404, "no such workspace")
        return ws

    def guard(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError:
            raise HTTPException(404, "not found")
        except GraphError as e:
            raise HTTPException(400, str(e))

    A = [Depends(auth)]

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
    def create_ws(body: WorkspaceIn):
        return brain.graph.create_workspace(body.name, persona=body.persona, owner_name=body.owner_name,
                                            workspace_id=body.workspace_id)

    @r.get("/v1/workspaces", dependencies=A)
    def list_ws():
        rows = brain.db.query("select w.id, w.name, w.persona, w.created_at, (select count(*) from nodes n where "
                              "n.workspace_id=w.id) as nodes from workspaces w order by w.created_at desc")
        return rows

    @r.get("/v1/workspaces/{ws}/export", dependencies=A)
    def export_ws(ws: str):
        return guard(brain.export_workspace, ws)

    @r.delete("/v1/workspaces/{ws}", dependencies=A)
    def delete_ws(ws: str, confirm: str | None = None):
        """Removes the workspace and all its notes, tasks and audio. ?confirm=<workspace id> is required."""
        if confirm != ws:
            raise HTTPException(400, "add ?confirm=<workspace id> to remove a workspace")
        return guard(brain.delete_workspace, ws)

    @r.get("/v1/workspaces/{ws}", dependencies=A)
    def get_ws(ws: str):
        ws_ok(ws)
        return {**brain.graph.workspace(ws), "root_id": brain.graph.root(ws)["id"], "members": brain.graph.members(ws)}

    @r.post("/v1/workspaces/{ws}/onboard", dependencies=A)
    def onboard(ws: str, body: OnboardIn):
        ws_ok(ws)
        return brain.onboard(ws, body.answer, body.apply)

    @r.post("/v1/workspaces/{ws}/members", dependencies=A)
    def add_member(ws: str, body: MemberIn):
        ws_ok(ws)
        return {"id": brain.graph.add_member(ws, body.display_name, role=body.role, contact=body.contact,
                                             person_node_id=body.person_node_id)}

    @r.get("/v1/workspaces/{ws}/members", dependencies=A)
    def members(ws: str):
        return brain.graph.members(ws_ok(ws))

    # ---------------------------------------------------------------- the graph
    @r.get("/v1/workspaces/{ws}/tree", dependencies=A)
    def tree(ws: str):
        return brain.graph.tree(ws_ok(ws))

    @r.post("/v1/workspaces/{ws}/nodes", dependencies=A)
    def add_node(ws: str, body: NodeIn):
        ws_ok(ws)
        return {"id": guard(brain.graph.add_node, ws, body.parent_id, body.title, body.kind, aliases=body.aliases)}

    @r.get("/v1/nodes/{node_id}", dependencies=A)
    def node(node_id: str):
        return guard(brain.node_detail, node_id)

    @r.get("/v1/nodes/{node_id}/history", dependencies=A)
    def node_history(node_id: str, limit: int = Query(default=100, ge=1, le=500)):
        return guard(brain.history, node_id, limit)

    @r.patch("/v1/nodes/{node_id}", dependencies=A)
    def patch_node(node_id: str, body: NodePatch):
        if brain.graph.node(node_id) is None:
            raise HTTPException(404, "not found")
        if body.title:
            brain.graph.rename(node_id, body.title)
        if body.parent_id:
            guard(brain.graph.move, node_id, body.parent_id)
        for a in body.add_aliases:
            brain.graph.add_alias(node_id, a)
        if body.attributes:
            brain.set_attributes(node_id, body.attributes)
        return brain.node_detail(node_id)

    @r.delete("/v1/nodes/{node_id}", dependencies=A)
    def delete_node(node_id: str):
        guard(brain.graph.delete_subtree, node_id)
        return {"deleted": node_id}

    # ---------------------------------------------------------------- captures
    @r.post("/v1/workspaces/{ws}/captures", dependencies=A)
    def capture_text(ws: str, body: CaptureIn):
        ws_ok(ws)
        r = brain.register_capture(ws, text=body.text, capture_id=body.capture_id, recorded_at=body.recorded_at,
                                   source=body.source, lang_hint=body.lang_hint, geo=body.geo, enqueue=not body.wait)
        if body.wait and not r["duplicate"]:
            return brain.process(r["capture_id"])
        return brain.capture_summary(r["capture_id"]) if r["duplicate"] else r

    @r.post("/v1/workspaces/{ws}/captures/audio", dependencies=A)
    async def capture_audio(ws: str, request: Request, capture_id: str | None = None, recorded_at: str | None = None,
                            source: str = "phone", lang_hint: str | None = None):
        ws_ok(ws)
        audio = await request.body()
        if not audio:
            raise HTTPException(400, "empty body")
        if len(audio) > 25 * 1024 * 1024:
            raise HTTPException(413, "audio over 25 MB")
        return brain.register_capture(ws, audio=audio, mime=request.headers.get("content-type"), capture_id=capture_id,
                                      recorded_at=recorded_at, source=source, lang_hint=lang_hint)

    @r.get("/v1/captures/{cid}", dependencies=A)
    def capture(cid: str):
        return guard(brain.capture_summary, cid)

    @r.post("/v1/captures/{cid}/undo", dependencies=A)
    def undo(cid: str):
        return guard(brain.undo, cid)

    # ---------------------------------------------------------------- inbox, tasks, alerts, notifications
    @r.get("/v1/workspaces/{ws}/inbox", dependencies=A)
    def inbox(ws: str):
        return brain.db.query("select * from inbox where workspace_id=? and state='open' order by created_at", (ws_ok(ws),))

    @r.post("/v1/inbox/{item_id}/resolve", dependencies=A)
    def resolve(item_id: str, body: ResolveIn):
        return guard(brain.resolve_inbox, item_id, body.node_id)

    @r.post("/v1/inbox/{item_id}/dismiss", dependencies=A)
    def dismiss(item_id: str):
        brain.dismiss_inbox(item_id)
        return {"dismissed": item_id}

    @r.get("/v1/workspaces/{ws}/tasks", dependencies=A)
    def tasks(ws: str, state: str | None = "open", assignee: str | None = None):
        return brain.tasks(ws_ok(ws), state or None, assignee)

    @r.patch("/v1/tasks/{task_id}", dependencies=A)
    def patch_task(task_id: str, body: TaskPatch):
        return guard(brain.update_task, task_id, state=body.state, assignee_member=body.assignee_member,
                     due_at=body.due_at)

    @r.get("/v1/workspaces/{ws}/alerts", dependencies=A)
    def alerts(ws: str, open_only: bool = True):
        sql = "select * from alerts where workspace_id=?" + (" and resolved_at is null" if open_only else "")
        return brain.db.query(sql + " order by created_at desc", (ws_ok(ws),))

    @r.post("/v1/alerts/{alert_id}/resolve", dependencies=A)
    def resolve_alert(alert_id: str):
        return guard(brain.resolve_alert, alert_id)

    @r.get("/v1/workspaces/{ws}/notifications", dependencies=A)
    def notifications(ws: str, member: str | None = None, unsent: bool = True):
        sql, args = "select * from notifications where workspace_id=?", [ws_ok(ws)]
        if member:
            sql += " and member_id=?"
            args.append(member)
        if unsent:
            sql += " and sent_at is null"
        return brain.db.query(sql + " order by created_at", args)

    @r.get("/v1/workspaces/{ws}/digest", dependencies=A)
    def digest(ws: str, focus: str | None = None):
        return brain.digest(ws_ok(ws), focus=focus)

    # ---------------------------------------------------------------- mind map (Phase 2)
    @r.get("/v1/workspaces/{ws}/mindmap", dependencies=A)
    def mindmap(ws: str, tasks: bool = True, notes: int = Query(default=3, ge=0, le=20)):
        """The whole map, UI-ready: root, categories with roll-ups, entities with status, echo dot, decay, reminders
        and progress, open tasks as leaves, People / Delegation; edges belongs_to_category, has_task, assigned_to,
        related_to. `cursor` is the last live-event id: open the event stream with Last-Event-ID = cursor."""
        return brain.mindmap(ws_ok(ws), tasks=tasks, notes_per_node=notes)

    # ---------------------------------------------------------------- one capture endpoint (Phase 2)
    @r.post("/v1/workspaces/{ws}/capture", dependencies=A)
    async def capture_any(ws: str, request: Request):
        """multipart/form-data (file or audio = WAV / WebM / Opus / Ogg / MP3 / M4A, and/or text, context_node_id,
        capture_id, recorded_at, source, lang_hint, wait), application/json (same fields), or a raw audio/* body
        (fields as query parameters). context_node_id: the node open on the map while recording; it and its
        neighbours are preferred when the brain decides where the note goes."""
        ws_ok(ws)
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        fields: dict = {k: v for k, v in request.query_params.items() if k != "token"}
        audio = mime = None
        if ctype in ("multipart/form-data", "application/x-www-form-urlencoded"):
            form = await request.form()
            for key, val in form.multi_items():
                if hasattr(val, "read"):  # an uploaded file
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
        wait = body.wait if body.wait is not None else audio is None
        reg = await run_in_threadpool(guard, brain.register_capture, ws, text=None if audio is not None else text,
                                      audio=audio, mime=mime, capture_id=body.capture_id, recorded_at=body.recorded_at,
                                      source=body.source, lang_hint=body.lang_hint, geo=body.geo,
                                      enqueue=not wait, context_node_id=body.context_node_id)
        cid = reg["capture_id"]
        links = {"status_url": f"/v1/captures/{cid}", "events_url": f"/v1/workspaces/{ws}/events/stream",
                 "context_node_id": body.context_node_id}
        if reg["duplicate"]:
            return {**brain.capture_summary(cid), "duplicate": True, **links}
        if wait:
            try:
                res = await run_in_threadpool(brain.process, cid)
            except Exception as ex:  # the capture is marked failed and the event stream says why
                raise HTTPException(422 if "STTError" in type(ex).__name__ else 500, f"{type(ex).__name__}: {ex}")
            return {**res, **links}
        return JSONResponse({**reg, **links}, status_code=202)

    @r.get("/v1/workspaces/{ws}/sync", dependencies=A)
    def sync(ws: str):
        return brain.sync_status(ws_ok(ws))

    @r.get("/v1/workspaces/{ws}/keyterms", dependencies=A)
    def keyterms(ws: str):
        return {"keyterms": brain.keyterms(ws_ok(ws))}

    @r.post("/v1/workspaces/{ws}/maintenance", dependencies=A)
    def maintenance(ws: str):
        return {"decayed": brain.graph.decay(ws_ok(ws))}

    # ---------------------------------------------------------------- multi-worker sync (this brain as a hub)
    @r.get("/v1/sync/status", dependencies=A)
    def sync_status():
        return {"ok": True, **brain.sync.status()}

    @r.post("/v1/sync/push", dependencies=A)
    def sync_push(body: SyncPushIn):
        """Another worker (a desktop, an Edge AI Node) sends the changes it made."""
        res = brain.journal.receive(body.changes, via=body.worker,
                                    on_applied=lambda ids: brain.graph.rollup(sorted(ids)))
        for ws in res["workspaces"]:
            ids = [n for n in res["touched"] if (brain.graph.node(n) or {}).get("workspace_id") == ws]
            brain.broker.publish(ws, "sync.applied", {"pulled": res["applied"], "node_ids": ids, "from": body.worker})
        return {"hub": brain.journal.worker_id, **{k: v for k, v in res.items() if k != "touched"}}

    @r.get("/v1/sync/pull", dependencies=A)
    def sync_pull(worker: str, since: int = Query(default=0, ge=0), limit: int = Query(default=500, ge=1, le=5000),
                  workspaces: str | None = None):
        """Another worker asks for everything after its cursor that it did not make itself."""
        ws = [w for w in (workspaces or "").split(",") if w] or None
        changes, cursor, more = brain.journal.to_serve(worker, since, limit, ws)
        return {"hub": brain.journal.worker_id, "changes": [c.as_dict() for c in changes], "cursor": cursor, "more": more}

    @r.post("/v1/sync/now", dependencies=A)
    async def sync_now():
        return await run_in_threadpool(brain.sync.run_once)

    # ---------------------------------------------------------------- live events (server-sent events)
    @r.get("/v1/workspaces/{ws}/events/stream", dependencies=A)
    @r.get("/v1/workspaces/{ws}/events", dependencies=A, include_in_schema=False)
    async def events(ws: str, request: Request, last_event_id: int | None = Query(default=None, ge=0),
                     types: str | None = None, limit: int | None = Query(default=None, ge=1),
                     last_event_header: str | None = Header(default=None, alias="Last-Event-ID")):
        """capture.queued, stt.transcribing, stt.completed, router.resolving, action.applied, inbox.created,
        capture.completed, capture.failed, action.undone, node.updated, task.updated, alert.updated, inbox.resolved.
        Reconnect with Last-Event-ID (header, or ?last_event_id=) to get what was missed. ?types=a,b filters by
        name or prefix (types=stt,action); ?limit=n closes the stream after n events."""
        ws_ok(ws)
        start = last_event_id
        if start is None and last_event_header and last_event_header.strip().isdigit():
            start = int(last_event_header.strip())
        want = [t.strip() for t in (types or "").split(",") if t.strip()]

        def wanted(m: dict) -> bool:
            return not want or any(m["type"] == w or m["type"].startswith(w + ".") for w in want)

        q = brain.broker.subscribe(ws)  # subscribe before replay, so nothing falls in between

        async def gen():
            sent, last = 0, start or 0
            try:
                yield "retry: 2000\n\n"
                backlog = brain.broker.since(ws, start) if start is not None else []
                for msg in backlog:
                    last = max(last, msg["id"])
                    if wanted(msg):
                        yield brain.broker.sse(msg)
                        sent += 1
                        if limit and sent >= limit:
                            return
                while not await request.is_disconnected():
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield f": keep-alive {int(time.time())}\n\n"
                        continue
                    if msg["id"] <= last or not wanted(msg):
                        continue
                    last = msg["id"]
                    yield brain.broker.sse(msg)
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
    tr = tus.router(brain, settings, check_auth, ws_ok)
    r.include_router(tr)

    @r.get("/v1/pairing")
    def pairing(request: Request, ws: str | None = None):
        """For the desktop app only: what a phone needs to connect (shown as a QR code to scan with the phone)."""
        if not is_local(request):
            raise HTTPException(403, "pairing is only shown on this PC")
        import socket
        from urllib.parse import urlencode
        port = request.url.port or 8788
        ips: list[str] = []
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("192.0.2.1", 9))  # picks the LAN interface; sends nothing
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
        try:
            for fam, *_, addr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                if addr[0] not in ips and not addr[0].startswith("127."):
                    ips.append(addr[0])
        except OSError:
            pass
        lan = settings.bind_host not in ("127.0.0.1", "localhost", "::1")
        urls = [f"http://{ip}:{port}" for ip in ips]
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
