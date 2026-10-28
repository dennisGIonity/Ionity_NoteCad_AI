# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Resumable uploads (tus 1.0.0: core, creation, creation-with-upload, termination, expiration) for phone captures.

The phone records into its outbox, then uploads with tus: if the signal drops halfway, it asks for the offset
(HEAD) and sends only the rest (PATCH). When the last byte arrives the recording becomes a capture with the
phone's own capture id (UUIDv7, from Upload-Metadata), so a retried upload never makes a second note.

  POST   /api/v1/workspaces/{ws}/uploads          Upload-Length, Upload-Metadata: capture_id, filetype, filename,
                                                 context_node_id, recorded_at, source, lang_hint
  HEAD   /api/v1/workspaces/{ws}/uploads/{id}     -> Upload-Offset
  PATCH  /api/v1/workspaces/{ws}/uploads/{id}     Upload-Offset + application/offset+octet-stream body
  DELETE /api/v1/workspaces/{ws}/uploads/{id}     give up
The finished upload answers with NoteCad-Capture-Id; follow it on the event stream like any capture.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

TUS_VERSION = "1.0.0"
CAPTURE_ID = re.compile(r"[0-9a-fA-F-]{8,64}")
EXTENSIONS = "creation,creation-with-upload,termination,expiration"
EXPIRES = timedelta(hours=24)
OCTET = "application/offset+octet-stream"
EXPOSE = ["Upload-Offset", "Upload-Length", "Upload-Metadata", "Upload-Expires", "Location", "Tus-Resumable",
          "Tus-Version", "Tus-Extension", "Tus-Max-Size", "NoteCad-Capture-Id"]
ALLOW = ["Tus-Resumable", "Upload-Length", "Upload-Metadata", "Upload-Offset", "Upload-Defer-Length",
         "X-HTTP-Method-Override", "X-Requested-With"]


def parse_metadata(header: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in (header or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, val = pair.partition(" ")
        try:
            out[key] = base64.b64decode(val, validate=True).decode("utf-8") if val else ""
        except Exception:
            raise HTTPException(400, f"Upload-Metadata: {key} is not base64")
    return out


def _http_date(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


class UploadStore:
    def __init__(self, root: Path, max_bytes: int):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock(self, uid: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(uid, threading.Lock())

    def _info_path(self, uid: str) -> Path:
        return self.root / f"{uid}.json"

    def data_path(self, uid: str) -> Path:
        return self.root / f"{uid}.part"

    def info(self, uid: str) -> dict | None:
        if not uid.isalnum():
            return None
        p = self._info_path(uid)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def save(self, info: dict) -> None:
        tmp = self._info_path(info["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(info), encoding="utf-8")
        tmp.replace(self._info_path(info["id"]))

    def create(self, ws: str, length: int, meta: dict) -> dict:
        uid = uuid.uuid4().hex
        info = {"id": uid, "ws": ws, "length": length, "offset": 0, "meta": meta, "capture_id": None,
                "created": time.time(), "expires": (datetime.now(timezone.utc) + EXPIRES).timestamp()}
        self.data_path(uid).write_bytes(b"")
        self.save(info)
        return info

    def delete(self, uid: str) -> None:
        for p in (self._info_path(uid), self.data_path(uid)):
            p.unlink(missing_ok=True)

    def sweep(self) -> int:
        """Remove expired, unfinished uploads."""
        n = 0
        for p in self.root.glob("*.json"):
            try:
                info = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if info.get("expires", 0) < time.time():
                self.delete(info["id"])
                n += 1
        return n


def router(brain, settings, auth, ws_ok) -> APIRouter:
    r = APIRouter()
    store = UploadStore(Path(settings.upload_dir), settings.max_audio_mb * 1024 * 1024)
    brain.uploads = store

    def tus_headers(extra: dict | None = None) -> dict:
        return {"Tus-Resumable": TUS_VERSION, "Cache-Control": "no-store", **(extra or {})}

    def check_version(request: Request) -> None:
        if request.headers.get("tus-resumable") != TUS_VERSION:
            raise HTTPException(412, "Tus-Resumable 1.0.0 required", headers={"Tus-Version": TUS_VERSION})

    def get(ws: str, uid: str) -> dict:
        info = store.info(uid)
        if info is None or info["ws"] != ws:
            raise HTTPException(404, "no such upload", headers=tus_headers())
        if info["expires"] < time.time() and info["offset"] < info["length"]:
            store.delete(uid)
            raise HTTPException(410, "upload expired", headers=tus_headers())
        return info

    def finish(info: dict) -> str:
        meta = info["meta"]
        audio = store.data_path(info["id"]).read_bytes()
        res = brain.register_capture(info["ws"], audio=audio, mime=meta.get("filetype") or "audio/ogg",
                                     capture_id=meta.get("capture_id") or None, recorded_at=meta.get("recorded_at") or None,
                                     source=meta.get("source") or "phone", lang_hint=meta.get("lang_hint") or None,
                                     context_node_id=meta.get("context_node_id") or None, enqueue=True)
        info["capture_id"] = res["capture_id"]
        store.save(info)
        store.data_path(info["id"]).unlink(missing_ok=True)  # the audio now lives with the capture
        return res["capture_id"]

    async def append(request: Request, info: dict, offset: int | None = None) -> None:
        if offset is None:
            try:
                offset = int(request.headers.get("upload-offset", "-1"))
            except ValueError:
                offset = -1
        if offset != info["offset"]:
            raise HTTPException(409, f"offset is {info['offset']}", headers=tus_headers({"Upload-Offset": str(info["offset"])}))
        path = store.data_path(info["id"])
        path.touch()
        if path.stat().st_size < info["offset"]:
            # the offset was saved but the bytes never reached the disk: continue from what is really there, never
            # from a gap (seek + truncate past the end would pad the recording with silence)
            info["offset"] = path.stat().st_size
            store.save(info)
            raise HTTPException(409, f"offset is {info['offset']}", headers=tus_headers({"Upload-Offset": str(info["offset"])}))
        with path.open("r+b") as f:
            # write at the offset the brain recorded, and drop anything after it: bytes written just before a crash
            # (or a failed save of the offset) would otherwise sit in front of the resumed upload and corrupt the audio
            f.seek(info["offset"])
            f.truncate()
            async for chunk in request.stream():
                if info["offset"] + len(chunk) > info["length"]:
                    raise HTTPException(413, "more bytes than Upload-Length", headers=tus_headers())
                f.write(chunk)
                f.flush()
                info["offset"] += len(chunk)  # progress is kept even if the connection drops mid-body
                store.save(info)

    def done_headers(info: dict) -> dict:
        h = {"Upload-Offset": str(info["offset"]),
             "Upload-Expires": _http_date(datetime.fromtimestamp(info["expires"], timezone.utc))}
        if info.get("capture_id"):
            h["NoteCad-Capture-Id"] = info["capture_id"]
        return tus_headers(h)

    base = "/v1/workspaces/{ws}/uploads"

    @r.options(base)
    @r.options(base + "/{uid}")
    def options(ws: str, uid: str | None = None):
        return Response(status_code=204, headers={"Tus-Resumable": TUS_VERSION, "Tus-Version": TUS_VERSION,
                                                  "Tus-Extension": EXTENSIONS, "Tus-Max-Size": str(store.max_bytes)})

    @r.post(base)
    async def create(ws: str, request: Request):
        auth(request)
        ws_ok(ws)
        # tus-js-client may tunnel PATCH / DELETE / HEAD through POST
        override = (request.headers.get("x-http-method-override") or "").upper()
        if override:
            raise HTTPException(405, "method override only on an upload URL")
        check_version(request)
        store.sweep()
        try:
            length = int(request.headers["upload-length"])
        except (KeyError, ValueError):
            raise HTTPException(400, "Upload-Length required (deferred length is not supported)", headers=tus_headers())
        if length <= 0 or length > store.max_bytes:
            raise HTTPException(413, f"recordings up to {store.max_bytes // 1048576} MB", headers=tus_headers())
        meta = parse_metadata(request.headers.get("upload-metadata"))
        if meta.get("capture_id") and not CAPTURE_ID.fullmatch(meta["capture_id"]):
            raise HTTPException(400, "capture_id must be a UUID", headers=tus_headers())
        if meta.get("context_node_id"):
            n = brain.graph.node(meta["context_node_id"])
            if n is None or n["workspace_id"] != ws:
                raise HTTPException(400, "context_node_id is not in this workspace", headers=tus_headers())
        info = store.create(ws, length, meta)
        if request.headers.get("content-type", "").startswith(OCTET):  # creation-with-upload
            with store.lock(info["id"]):
                await append(request, info, offset=0)
                if info["offset"] == info["length"]:
                    finish(info)
        loc = f"{str(request.url).rstrip('/')}/{info['id']}"
        return Response(status_code=201, headers={**done_headers(info), "Location": loc})

    @r.head(base + "/{uid}")
    def head(ws: str, uid: str, request: Request):
        auth(request)
        check_version(request)
        info = get(ws, uid)
        return Response(status_code=200, headers={**done_headers(info), "Upload-Length": str(info["length"]),
                                                  "Upload-Metadata": ",".join(
                                                      f"{k} {base64.b64encode(v.encode()).decode()}" for k, v in info["meta"].items())})

    async def patch(ws: str, uid: str, request: Request):
        auth(request)
        check_version(request)
        if not request.headers.get("content-type", "").startswith(OCTET):
            raise HTTPException(415, f"Content-Type must be {OCTET}", headers=tus_headers())
        lock = store.lock(uid)
        if not lock.acquire(blocking=False):
            raise HTTPException(423, "upload busy", headers=tus_headers())
        try:
            info = get(ws, uid)
            if info["offset"] < info["length"]:
                await append(request, info)
            if info["offset"] == info["length"] and not info.get("capture_id"):
                finish(info)
            return Response(status_code=204, headers=done_headers(info))
        finally:
            lock.release()

    def delete(ws: str, uid: str, request: Request):
        auth(request)
        check_version(request)
        get(ws, uid)
        store.delete(uid)
        return Response(status_code=204, headers=tus_headers())

    r.add_api_route(base + "/{uid}", patch, methods=["PATCH"])
    r.add_api_route(base + "/{uid}", delete, methods=["DELETE"])

    @r.post(base + "/{uid}")
    async def override(ws: str, uid: str, request: Request):
        m = (request.headers.get("x-http-method-override") or "").upper()
        if m == "PATCH":
            return await patch(ws, uid, request)
        if m == "DELETE":
            return delete(ws, uid, request)
        if m == "HEAD":
            return head(ws, uid, request)
        raise HTTPException(405, "use PATCH, HEAD or DELETE")

    return r
