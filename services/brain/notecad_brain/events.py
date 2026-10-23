# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""In-process live events for server-sent events. On Supabase the same messages go out through Realtime; this keeps
the desktop and the Edge AI Node live without it.

Every message has a rising `id`, so a client that drops off reconnects with Last-Event-ID and gets what it missed
from the ring buffer. Event names the map UI listens for (Phase 2):

  capture.queued -> stt.transcribing -> stt.completed {transcript}
  -> router.resolving {idx, text} -> action.applied {node_ids} | inbox.created {inbox_id, options}
  -> capture.completed {state}          and later  action.undone {node_ids}      or  capture.failed {error}
  node.updated {status, counts}         task.updated, alert.updated, inbox.resolved
"""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
from collections import deque

from .common import now_iso


class Broker:
    def __init__(self, history: int = 500):
        self._subs: list[tuple[str, asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self.recent: deque = deque(maxlen=history)

    @property
    def last_id(self) -> int:
        return self.recent[-1]["id"] if self.recent else 0

    def subscribe(self, ws: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subs.append((ws, asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [s for s in self._subs if s[2] is not q]

    def publish(self, ws: str, kind: str, data: dict) -> dict:
        with self._lock:
            msg = {"id": next(self._ids), "type": kind, "workspace_id": ws, "at": now_iso(), **data}
            self.recent.append(msg)
            subs = list(self._subs)
        for sws, loop, q in subs:
            if sws == ws:
                try:
                    loop.call_soon_threadsafe(q.put_nowait, msg)
                except (RuntimeError, asyncio.QueueFull):
                    pass
        return msg

    def since(self, ws: str, last_id: int) -> list[dict]:
        """What a reconnecting client missed (Last-Event-ID), oldest first."""
        with self._lock:
            return [m for m in self.recent if m["workspace_id"] == ws and m["id"] > last_id]

    def of(self, ws: str, capture_id: str | None = None) -> list[dict]:
        with self._lock:
            return [m for m in self.recent if m["workspace_id"] == ws
                    and (capture_id is None or m.get("capture_id") == capture_id)]

    @staticmethod
    def sse(msg: dict) -> str:
        return f"id: {msg['id']}\nevent: {msg['type']}\ndata: {json.dumps(msg, ensure_ascii=False, default=str)}\n\n"
