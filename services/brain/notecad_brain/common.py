# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Ids, time and the status order shared by every module."""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

# Severity order: max() over these ranks gives the worst status (blueprint 1.2 / 4.2)
STATUS_RANK = {"done": 0, "pending": 1, "ok": 2, "info": 3, "routine_due": 4, "warning": 5, "critical": 6}
KINDS = ["root", "category", "channel", "asset", "animal", "group", "field", "place", "person", "project", "topic", "sketch"]
PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "urgent": 3}

PROVENANCE = {"policy": "986 AED", "license": "AED 900", "org": "Ionity Global (Pty) Ltd", "pipeline": "notecad-brain 0.1.0"}


def worst(*statuses: str) -> str:
    return max((s for s in statuses if s), key=lambda s: STATUS_RANK.get(s, 2), default="ok")


def uuid7() -> str:
    """Time-ordered UUID (RFC 9562 v7). Python 3.14 has uuid.uuid7; this works on 3.11+."""
    ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | ((rand >> 62) & 0xFFF) << 64 | 0b10 << 62 | (rand & ((1 << 62) - 1))
    return str(uuid.UUID(int=value))


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc).isoformat(timespec="seconds")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def short_label(node_id: str) -> str:
    return node_id.replace("-", "")[:12]
