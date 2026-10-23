# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Step 5: nothing a model says reaches the database unchecked."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "packages" / "schema" / "actions.schema.json"
_VALIDATOR = None


def validator() -> jsonschema.Draft202012Validator:
    global _VALIDATOR
    if _VALIDATOR is None:
        path = SCHEMA_PATH if SCHEMA_PATH.exists() else Path(__file__).with_name("actions.schema.json")
        _VALIDATOR = jsonschema.Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))
    return _VALIDATOR


CAP_PREFIXES = ("area", "total", "capacity", "max", "size")
MIN_CONFIDENCE = 0.6


@dataclass
class Checked:
    actions: list[dict] = field(default_factory=list)
    gate: str | None = None       # reason the event goes to the Inbox instead of being written
    errors: list[str] = field(default_factory=list)
    question: str | None = None
    options: list[dict] = field(default_factory=list)


def _clean(a: dict) -> dict:
    """Drop empty optional fields a flat tool schema may fill with "" or null."""
    keep = {}
    for k, v in a.items():
        if v in ("", None) and k not in ("due_at", "assignee_hint"):
            continue
        keep[k] = v
    return keep


def check(payload: dict, *, allowed_ids: set[str], root_id: str, node_attrs: dict[str, dict],
          node_parent: dict[str, str | None]) -> Checked:
    out = Checked()
    payload = dict(payload)
    payload["actions"] = [_clean(a) for a in payload.get("actions", []) if isinstance(a, dict)]
    payload.setdefault("summary", "")
    payload["summary"] = str(payload["summary"])[:200]
    errs = sorted(validator().iter_errors(payload), key=lambda e: list(e.path))
    if errs:
        out.errors = [f"{'/'.join(map(str, e.path))}: {e.message}"[:200] for e in errs[:8]]
        out.gate = "schema"
        return out

    known = set(allowed_ids)
    seen: set[str] = set()
    for a in payload["actions"]:
        t = a["type"]
        if t == "ask_user":
            out.gate = "model asked"
            out.question = a.get("question")
            out.options = [o for o in a.get("options", []) if o.get("node_id") in known][:3]
            continue
        refs = [a.get(k) for k in ("node_id", "parent_id", "src_id", "dst_id") if a.get(k)]
        bad = [r for r in refs if r not in known]
        if bad:
            out.errors.append(f"{t}: unknown node {bad[0]}")
            continue
        if t == "create_node":
            if a["parent_id"] == root_id:
                out.gate = "new top-level category"
                out.question = f'Create a new top-level branch "{a["title"]}"?'
                continue
            known.add(a["temp_id"])
        if t == "link_nodes" and a["src_id"] == a["dst_id"]:
            continue
        if t == "update_attributes":
            target = node_attrs.get(a["node_id"], {})
            for k, inc in (a.get("increment") or {}).items():
                new = (target.get(k) or 0) + inc
                unit = k.split("_")[-1] if "_" in k else None
                for ck, cv in target.items():
                    if unit and ck != k and ck.endswith(f"_{unit}") and ck.startswith(CAP_PREFIXES) \
                            and isinstance(cv, (int, float)) and new > cv:
                        out.gate = f"{k} would become {new}, above {ck} {cv}"
        if float(a.get("confidence", 0)) < MIN_CONFIDENCE:
            out.gate = out.gate or f"low confidence ({a.get('confidence')}) on {t}"
        sig = json.dumps({k: v for k, v in a.items() if k not in ("confidence", "evidence")}, sort_keys=True)
        if sig in seen:
            continue
        seen.add(sig)
        out.actions.append(a)
    if not out.actions and not out.gate:
        out.gate = "nothing usable" if out.errors else "empty"
    return out
