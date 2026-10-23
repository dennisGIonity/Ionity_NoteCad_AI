"""HTTP API. One process can serve several owners (desktop / Edge node); each owner has their own SQLite file.

Run:  uvicorn notecad_companion.api:app --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import PROVENANCE, __version__, trainer
from .companion import Companion
from .config import Settings
from .embed import make_embedder
from .llm import make_llm
from .store import Store

OWNER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Registry:
    """Shares one loaded model and embedder across owners; keeps owners' data apart."""

    def __init__(self, settings: Settings, llm=None, embedder=None):
        self.settings = settings
        self.llm = llm if llm is not None else make_llm(settings)
        self.embedder = embedder if embedder is not None else make_embedder(settings)
        self._owners: dict[str, Companion] = {}
        self._lock = threading.Lock()
        self.model_lock = threading.Lock()  # llama.cpp contexts are not thread safe

    def get(self, owner_id: str) -> Companion:
        if not OWNER_ID.match(owner_id):
            raise HTTPException(400, "bad owner id")
        with self._lock:
            if owner_id not in self._owners:
                store = Store(Path(self.settings.data_dir) / f"{owner_id}.sqlite")
                self._owners[owner_id] = Companion(
                    store, self.llm, self.embedder, history_turns=self.settings.history_turns,
                    memory_top_k=self.settings.memory_top_k, max_reply_tokens=self.settings.max_reply_tokens,
                    llm_fact_extraction=self.settings.llm_fact_extraction)
            return self._owners[owner_id]

    def drop(self, owner_id: str) -> None:
        with self._lock:
            self._owners.pop(owner_id, None)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class FeedbackIn(BaseModel):
    interaction_id: str
    rating: int | None = Field(default=None, ge=-1, le=1)
    edited_reply: str | None = Field(default=None, max_length=8000)
    comment: str | None = Field(default=None, max_length=2000)


class ObserveIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    source: str = "note"
    node_path: str | None = None
    ts: float | None = None


class FactIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+){0,3}$")
    value: str | int | float | list[str]


class Candidate(BaseModel):
    node_id: str
    path: str
    kind: str = ""
    aliases: list[str] = []


class RouteIn(BaseModel):
    capture_id: str
    event_index: int = 0
    event: str
    candidates: list[Candidate] = Field(min_length=1, max_length=12)


def create_app(settings: Settings | None = None, llm=None, embedder=None) -> FastAPI:
    settings = settings or Settings()
    reg = Registry(settings, llm, embedder)
    app = FastAPI(title="NoteCad Companion", version=__version__,
                  description="Private on-device assistant that learns its owner.")
    app.state.registry = reg

    def auth(authorization: str | None = Header(default=None)) -> None:
        if settings.api_token and authorization != f"Bearer {settings.api_token}":
            raise HTTPException(401, "missing or wrong token")

    def owner(owner_id: str, _: None = Depends(auth)) -> Companion:
        return reg.get(owner_id)

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "model": getattr(reg.llm, "name", None),
                "embedder": reg.embedder.name, "provenance": PROVENANCE}

    @app.post("/v1/{owner_id}/chat")
    def chat(body: ChatIn, c: Companion = Depends(owner)):
        t0 = time.perf_counter()
        with reg.model_lock:
            out = c.chat(body.text)
        out["ms"] = round((time.perf_counter() - t0) * 1000)
        return out

    @app.post("/v1/{owner_id}/feedback")
    def feedback(body: FeedbackIn, c: Companion = Depends(owner)):
        try:
            with reg.model_lock:
                return c.feedback(body.interaction_id, body.rating, body.edited_reply, body.comment)
        except KeyError:
            raise HTTPException(404, "no such interaction")

    @app.post("/v1/{owner_id}/observe")
    def observe(body: ObserveIn, c: Companion = Depends(owner)):
        with reg.model_lock:
            return c.observe(body.text, source=body.source, ts=body.ts, node_path=body.node_path)

    @app.put("/v1/{owner_id}/facts")
    def put_fact(body: FactIn, c: Companion = Depends(owner)):
        return c.learner.put_fact(body.key, body.value, 0.99, "user")

    @app.delete("/v1/{owner_id}/facts/{key}")
    def delete_fact(key: str, c: Companion = Depends(owner)):
        if not c.store.delete_fact(key):
            raise HTTPException(404, "no such fact")
        return {"deleted": key}

    @app.get("/v1/{owner_id}/card")
    def card(c: Companion = Depends(owner)):
        return c.card()

    @app.get("/v1/{owner_id}/keyterms")
    def keyterms(limit: int = 100, c: Companion = Depends(owner)):
        return {"keyterms": c.keyterms(limit)}

    @app.get("/v1/{owner_id}/nudges")
    def nudges(c: Companion = Depends(owner)):
        return {"nudges": c.nudges()}

    @app.post("/v1/{owner_id}/consolidate")
    def consolidate(c: Companion = Depends(owner)):
        return c.consolidate()

    @app.post("/v1/{owner_id}/route-offline")
    def route_offline(body: RouteIn, c: Companion = Depends(owner)):
        if reg.llm is None:
            raise HTTPException(503, "no local model loaded")
        with reg.model_lock:
            return c.route_offline(body.event, [x.model_dump() for x in body.candidates], body.capture_id,
                                   body.event_index)

    @app.post("/v1/{owner_id}/train/export")
    def train_export(owner_id: str, c: Companion = Depends(owner)):
        return trainer.export(c.store, Path(settings.data_dir) / "training" / owner_id)

    @app.get("/v1/{owner_id}/export")
    def export(c: Companion = Depends(owner)):
        return {"provenance": PROVENANCE, "exported_at": time.time(), "data": c.store.export()}

    @app.delete("/v1/{owner_id}")
    def wipe(owner_id: str, c: Companion = Depends(owner)):
        c.store.wipe()
        reg.drop(owner_id)
        return {"wiped": owner_id}

    return app


def __getattr__(name: str):
    # `uvicorn notecad_companion.api:app` builds the app on first access, so importing this module
    # (tests, tools) never loads a model by accident.
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
