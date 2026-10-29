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
  action.refused {refused}              (ADR 0014: what the speaker may not do, and why)

ADR 0014: a message carries who it is about (`_author`, `_route`: kept here, never sent) and each stream passes only
what its member may see (`for_view`).
"""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
from collections import deque

from .common import now_iso

# what only the speaker (and the owners) hear about: their own capture on its way, and what they may not do
AUTHOR_ONLY = {"capture.queued", "stt.transcribing", "stt.completed", "router.resolving", "capture.completed",
               "capture.failed", "action.refused", "sync.refused", "capture.answer"}
NODE_LISTS = ("node_ids", "affected_node_ids", "created_node_ids", "map_node_ids")
NODE_EVENTS = {"action.applied", "action.undone", "sync.applied", "node.updated", "task.updated", "alert.updated"}


def _offer(q: asyncio.Queue, msg: dict) -> None:
    """Runs on the subscriber's loop: a client too slow to drain 1,000 events misses some (it can resync with
    Last-Event-ID) rather than raising inside the event loop."""
    try:
        q.put_nowait(msg)
    except asyncio.QueueFull:
        pass


def for_view(msg: dict, view) -> dict | None:
    """The message as this viewer may see it, or None. Node lists are cut to what they see; an event about one node
    they cannot see is dropped; anything not known to be safe goes to owners only."""
    if view.all:
        return msg
    me = view.p.member_id
    kind = msg["type"]
    if kind in AUTHOR_ONLY:
        return msg if me and msg.get("_author") == me else None
    if kind.startswith("inbox."):
        return msg if me and (msg.get("_author") == me or me in (msg.get("_route") or [])) else None
    if kind == "workspace.deleted":
        return msg
    if kind not in NODE_EVENTS:
        return None
    if msg.get("node_id") and not _sees(view, msg["node_id"]):
        return None
    out = dict(msg)
    had = False
    for k in NODE_LISTS:
        if k in out:
            had = had or bool(out[k])
            out[k] = [n for n in out[k] or [] if _sees(view, n)]
    if "removed_node_ids" in out:  # gone now: the viewer had them if they could see them before
        out["removed_node_ids"] = [n for n in out["removed_node_ids"] or [] if view.node(n)]
    if "nodes" in out:
        out["nodes"] = [n for n in out["nodes"] or [] if _sees(view, n.get("id")) and _sees(view, n.get("map_id"))]
    if had and not any(out.get(k) for k in NODE_LISTS) and kind != "sync.applied":
        return None
    return out


def _sees(view, nid: str | None) -> bool:
    if not nid:
        return False
    if nid not in view.known and nid not in view.rows_ids:
        view.refresh()  # a node made after the stream opened
    return view.node(nid)


class Broker:
    def __init__(self, history: int = 500):
        self._subs: list[tuple[str, asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()
        # ids start at this boot's clock (ms), so a client that reconnects after a restart with an old Last-Event-ID
        # is behind the new ids, never ahead of them (ids restarting at 1 made the desktop drop every new event)
        self._ids = itertools.count(int(time.time() * 1000))
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

    def publish(self, ws: str, kind: str, data: dict, *, author: str | None = None,
                route: list[str] | None = None) -> dict:
        """author: the member whose capture or change this is; route: the members an Inbox item is for."""
        with self._lock:
            msg = {"id": next(self._ids), "type": kind, "workspace_id": ws, "at": now_iso(), **data,
                   "_author": author, "_route": route}
            self.recent.append(msg)
            subs = list(self._subs)
        for sws, loop, q in subs:
            if sws == ws:
                try:
                    loop.call_soon_threadsafe(_offer, q, msg)
                except RuntimeError:  # that client's loop is gone
                    pass
        return msg

    def since(self, ws: str, last_id: int) -> list[dict]:
        """What a reconnecting client missed (Last-Event-ID), oldest first. An id from the future (another brain,
        or a clock set back) means nothing here is known to be missed."""
        with self._lock:
            if self.recent and last_id > self.recent[-1]["id"]:
                return []
            return [m for m in self.recent if m["workspace_id"] == ws and m["id"] > last_id]

    def of(self, ws: str, capture_id: str | None = None) -> list[dict]:
        with self._lock:
            return [m for m in self.recent if m["workspace_id"] == ws
                    and (capture_id is None or m.get("capture_id") == capture_id)]

    @staticmethod
    def sse(msg: dict) -> str:
        public = {k: v for k, v in msg.items() if not k.startswith("_")}
        return f"id: {msg['id']}\nevent: {msg['type']}\ndata: {json.dumps(public, ensure_ascii=False, default=str)}\n\n"
