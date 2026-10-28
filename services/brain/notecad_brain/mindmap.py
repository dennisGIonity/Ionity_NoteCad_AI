# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""The mind map read model (Phase 2): the owner's whole map in one UI-ready payload.

  root      the workspace, with totals
  category  category and group nodes (Vehicles, Tractors, Fields, Infrastructure) with rolled-up counts and
            average progress of what is under them; plus a virtual People / Delegation category
  entity    the things themselves (asset, animal, field, place, person, project, topic) with display status,
            echo dot, decay, reminders, progress_pct and their recent notes (with provenance)
  task      one leaf per open task, attached to the node it is on
  member    the people tasks are delegated to (under People / Delegation)

Channels (Maintenance, Health Alerts, Planting Log) are folded into their parent: the parent's display status
already mirrors them, and their notes and tasks are shown on the parent with the channel named.

Edges: belongs_to_category (child -> parent), has_task (node -> task), assigned_to (task -> member, and
node -> person from delegation), related_to (cross-links: located_at, affects, related_to).

Everything is computed here, server-side, so the phone, the desktop and the companion show the same thing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .common import STATUS_RANK, now_iso, parse_iso

CATEGORY_KINDS = {"category", "group"}
PEOPLE_ID = "virtual:people"
DECAY_HOURS = {"info": 24, "done": 48}  # same rule as Graph.decay
DUE_SOON = timedelta(hours=48)
# (numerator, denominator, verb, unit): the first pair found in a node's attributes gives its progress
PROGRESS_PAIRS = [
    ("progress_done", "progress_total", "done", None),
    ("completed", "total", "completed", None),
    ("planted_ha", "area_ha", "planted", "ha"),
    ("harvested_ha", "area_ha", "harvested", "ha"),
    ("sprayed_ha", "area_ha", "sprayed", "ha"),
    ("done_ha", "area_ha", "done", "ha"),
    ("installed_m", "length_m", "installed", "m"),
    ("done_m", "length_m", "done", "m"),
]
PHASE_PAIR = {"planting": "planted_ha", "harvest": "harvested_ha", "harvesting": "harvested_ha",
              "spraying": "sprayed_ha"}


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def progress_of(node: dict, done_tasks: int = 0, open_tasks: int = 0) -> dict | None:
    """Progress of one node: stated percentage, a done/total pair in its attributes, its task list (projects and
    fields only), or done status. None when nothing says how far along it is."""
    attrs = node.get("attributes") or {}
    pct = _num(attrs.get("progress_pct", attrs.get("progress")))
    if pct is not None:
        pct = pct * 100 if 0 < pct <= 1 and "progress" in attrs and "progress_pct" not in attrs else pct
        return {"pct": round(max(0.0, min(pct, 100.0)), 1), "source": "attribute", "verb": "done", "unit": "%",
                "done": None, "total": None, "weight": 1.0}
    pairs = list(PROGRESS_PAIRS)
    preferred = PHASE_PAIR.get(str(attrs.get("phase", "")).lower())
    if preferred:
        pairs.sort(key=lambda p: p[0] != preferred)
    for num, den, verb, unit in pairs:
        a, b = _num(attrs.get(num)), _num(attrs.get(den))
        if a is not None and b:
            return {"pct": round(max(0.0, min(a / b * 100, 100.0)), 1), "source": f"attributes:{num}/{den}",
                    "verb": verb, "unit": unit, "done": a, "total": b, "weight": b if unit == "ha" else 1.0}
    if node["kind"] in ("project", "field") and done_tasks + open_tasks:
        return {"pct": round(done_tasks / (done_tasks + open_tasks) * 100, 1), "source": "tasks", "verb": "done",
                "unit": "tasks", "done": done_tasks, "total": done_tasks + open_tasks, "weight": 1.0}
    if node["status"] == "done":
        return {"pct": 100.0, "source": "status", "verb": "done", "unit": None, "done": None, "total": None,
                "weight": 1.0}
    return None


def decay_of(node: dict, now: datetime) -> dict:
    """How fresh the node's ring is: info rings fade over 24 h, done marks over 48 h; problems do not fade."""
    st, since = node["status"], parse_iso(node.get("status_since"))
    if st in ("warning", "critical", "routine_due") or node.get("display_status") in ("warning", "critical", "routine_due"):
        return {"state": "active", "score": 1.0, "since": node.get("status_since"), "expires_at": None}
    hours = DECAY_HOURS.get(st)
    if not hours or since is None:
        return {"state": "settled", "score": 0.0, "since": node.get("status_since"), "expires_at": None}
    left = 1 - (now - since).total_seconds() / (hours * 3600)
    score = round(max(0.0, min(left, 1.0)), 3)
    return {"state": "fresh" if score > 0.5 else "fading" if score > 0 else "settled", "score": score,
            "since": node.get("status_since"), "expires_at": (since + timedelta(hours=hours)).isoformat(timespec="seconds")}


def _reminder(t: dict, now: datetime) -> dict:
    due = parse_iso(t.get("due_at"))
    state = "overdue" if due and due < now else "due_soon" if due and due - now <= DUE_SOON else "scheduled"
    return {"task_id": t["id"], "title": t["title"], "due_at": t["due_at"], "state": state,
            "priority": t["priority"], "assignee": t.get("assignee_name") or t.get("assignee_hint")}


def build(brain, ws: str, *, tasks: bool = True, notes_per_node: int = 3, now: datetime | None = None,
          cursor: int | None = None) -> dict:
    db, graph = brain.db, brain.graph
    now = now or datetime.now(timezone.utc)
    wsrow = graph.workspace(ws)
    rows = graph.nodes(ws)
    by_id = {n["id"]: n for n in rows}
    root = next(n for n in rows if n["parent_id"] is None)

    def visible(nid: str | None) -> str | None:
        """Channels fold into their parent on the map."""
        n = by_id.get(nid)
        while n is not None and n["kind"] == "channel" and n["parent_id"]:
            n = by_id.get(n["parent_id"])
        return n["id"] if n else None

    members = {m["id"]: m for m in graph.members(ws)}
    open_tasks = db.query("select t.*, m.display_name as assignee_name from tasks t left join members m "
                          "on m.id=t.assignee_member where t.workspace_id=? and t.state='open' "
                          "order by t.due_at is null, t.due_at, t.created_at", (ws,))
    done_counts: dict[str, int] = {}
    for r in db.query("select node_id, count(*) as c from tasks where workspace_id=? and state='done' "
                      "group by node_id", (ws,)):
        done_counts[r["node_id"]] = r["c"]
    alerts = db.query("select * from alerts where workspace_id=? and resolved_at is null order by created_at desc", (ws,))
    notes = db.query("select n.id, n.node_id, n.body, n.capture_id, n.author, n.created_at, c.source, c.recorded_at, "
                     "c.anchor_node_id from notes n left join captures c on c.id=n.capture_id "
                     "where n.workspace_id=? order by n.created_at desc limit 2000", (ws,))
    edges = db.query("select * from edges where workspace_id=?", (ws,))

    # ------------------------------------------------------------ per visible node: own items
    own_tasks: dict[str, list] = {}
    for t in open_tasks:
        if (v := visible(t["node_id"])) is not None:
            own_tasks.setdefault(v, []).append(t)
    own_alerts: dict[str, list] = {}
    for a in alerts:
        if (v := visible(a["node_id"])) is not None:
            own_alerts.setdefault(v, []).append(a)
    own_notes: dict[str, list] = {}
    for n in notes:
        v = visible(n["node_id"])
        if v is not None and len(own_notes.setdefault(v, [])) < notes_per_node:
            own_notes[v].append(n)

    # ------------------------------------------------------------ nodes
    channels_of: dict[str, list[dict]] = {}
    for c in rows:
        if c["kind"] == "channel" and c["parent_id"]:
            channels_of.setdefault(c["parent_id"], []).append(c)
    paths = graph.paths(rows)
    out: dict[str, dict] = {}
    for n in rows:
        if n["kind"] == "channel":
            continue
        typ = "root" if n["parent_id"] is None else "category" if n["kind"] in CATEGORY_KINDS else "entity"
        chans = channels_of.get(n["id"], [])
        node_ids = [n["id"]] + [c["id"] for c in chans]
        tl, al = own_tasks.get(n["id"], []), own_alerts.get(n["id"], [])
        done = sum(done_counts.get(i, 0) for i in node_ids)
        echo = n["child_worst"] if STATUS_RANK.get(n["child_worst"], 2) > max(STATUS_RANK.get(n["display_status"], 2),
                                                                             STATUS_RANK["ok"]) else None
        out[n["id"]] = {
            "id": n["id"], "type": typ, "kind": n["kind"], "title": n["title"], "parent_id": n["parent_id"],
            "depth": n["depth"], "path": paths[n["id"]] if n["parent_id"] else n["title"],
            "status": n["status"], "status_reason": n["status_reason"], "display_status": n["display_status"],
            "child_worst": n["child_worst"], "echo_dot": echo is not None, "echo_status": echo,
            "decay": decay_of(n, now),
            "counts": {"open_tasks": len(tl), "open_alerts": len(al), "done_tasks": done,
                       "overdue_tasks": sum(1 for t in tl if _reminder(t, now)["state"] == "overdue"),
                       "subtree_open_tasks": 0, "subtree_open_alerts": 0, "subtree_overdue_tasks": 0,
                       "entities": 0, "entities_needing_work": 0},
            "progress_pct": None, "progress": progress_of(n, done, len(tl)),
            "reminders": [_reminder(t, now) for t in tl if t.get("due_at")],
            "alerts": [{"alert_id": a["id"], "severity": a["severity"], "category": a["category"], "title": a["title"],
                        "created_at": a["created_at"],
                        "channel": by_id[a["node_id"]]["title"] if a["node_id"] != n["id"] else None} for a in al],
            "recent_notes": [{"note_id": x["id"], "body": x["body"], "created_at": x["created_at"],
                              "channel": by_id[x["node_id"]]["title"] if x["node_id"] != n["id"] else None,
                              "provenance": {"capture_id": x["capture_id"], "author": x["author"],
                                             "router": x["author"].split(":", 1)[1] if x["author"].startswith("ai:") else None,
                                             "source": x["source"], "recorded_at": x["recorded_at"],
                                             "context_node_id": x["anchor_node_id"]}}
                             for x in own_notes.get(n["id"], [])],
            "channels": [{"id": c["id"], "title": c["title"], "display_status": c["display_status"],
                          "open_tasks": c["open_tasks"], "open_alerts": c["open_alerts"]} for c in chans],
            "attributes": n["attributes"], "updated_at": n["updated_at"],
        }

    # ------------------------------------------------------------ roll-ups: counts and progress up the tree
    def needs_work(x: dict) -> bool:
        return (STATUS_RANK.get(x["display_status"], 2) >= STATUS_RANK["routine_due"]
                or x["counts"]["open_tasks"] > 0 or x["counts"]["open_alerts"] > 0)

    prog_acc: dict[str, list[tuple[float, float]]] = {}
    for x in sorted(out.values(), key=lambda x: -x["depth"]):
        c = x["counts"]
        c["subtree_open_tasks"] += c["open_tasks"]
        c["subtree_open_alerts"] += c["open_alerts"]
        c["subtree_overdue_tasks"] += c["overdue_tasks"]
        if x["type"] == "entity":
            c["entities"] += 1
            c["entities_needing_work"] += needs_work(x)
            if x["progress"]:
                prog_acc.setdefault(x["id"], []).append((x["progress"]["pct"], x["progress"]["weight"]))
        if x["type"] != "entity" and x["progress"] is None and prog_acc.get(x["id"]):
            vals = prog_acc[x["id"]]
            tw = sum(w for _, w in vals) or 1.0
            x["progress"] = {"pct": round(sum(p * w for p, w in vals) / tw, 1), "source": "rollup", "verb": "average",
                             "unit": "%", "done": None, "total": None, "weight": tw, "of": len(vals)}
        elif x["type"] != "entity" and x["progress"]:
            prog_acc.setdefault(x["id"], []).append((x["progress"]["pct"], x["progress"]["weight"]))
        x["progress_pct"] = x["progress"]["pct"] if x["progress"] else None
        parent = out.get(x["parent_id"]) if x["parent_id"] else None
        if parent is not None:
            pc = parent["counts"]
            for k in ("subtree_open_tasks", "subtree_open_alerts", "subtree_overdue_tasks", "entities",
                      "entities_needing_work"):
                pc[k] += c[k]
            prog_acc.setdefault(parent["id"], []).extend(prog_acc.get(x["id"], []))
        x["needs_work"] = needs_work(x) or c["entities_needing_work"] > 0

    # ------------------------------------------------------------ edges
    E: list[dict] = []
    for x in out.values():
        if x["parent_id"]:
            E.append({"id": f"tree:{x['id']}", "type": "belongs_to_category", "source": x["id"], "target": x["parent_id"]})

    # ------------------------------------------------------------ People / Delegation
    people_tasks: dict[str, list] = {}
    for t in open_tasks:
        if t["assignee_member"]:
            people_tasks.setdefault(t["assignee_member"], []).append(t)
    owner_ids = [m["id"] for m in members.values() if m["role"] == "owner"]
    out[PEOPLE_ID] = {
        "id": PEOPLE_ID, "type": "category", "kind": "people", "title": "People", "parent_id": root["id"], "depth": 1,
        "path": "People", "virtual": True, "status": "ok", "display_status": "ok", "child_worst": "ok",
        "echo_dot": False, "echo_status": None, "decay": {"state": "settled", "score": 0.0},
        "counts": {"members": len(members), "delegated_open_tasks": sum(len(v) for k, v in people_tasks.items()
                                                                        if k not in owner_ids),
                   "unassigned_hints": sum(1 for t in open_tasks if not t["assignee_member"] and t["assignee_hint"]),
                   "subtree_overdue_tasks": 0},
        "progress_pct": None, "progress": None, "needs_work": False,
    }
    E.append({"id": f"tree:{PEOPLE_ID}", "type": "belongs_to_category", "source": PEOPLE_ID, "target": root["id"]})
    for m in members.values():
        mid = f"member:{m['id']}"
        tl = people_tasks.get(m["id"], [])
        overdue = sum(1 for t in tl if _reminder(t, now)["state"] == "overdue")
        out[PEOPLE_ID]["counts"]["subtree_overdue_tasks"] += overdue
        out[mid] = {"id": mid, "type": "member", "kind": "member", "title": m["display_name"], "role": m["role"],
                    "member_id": m["id"], "person_node_id": m["person_node_id"], "parent_id": PEOPLE_ID, "depth": 2,
                    "counts": {"open_tasks": len(tl), "overdue_tasks": overdue},
                    "reminders": [_reminder(t, now) for t in tl if t.get("due_at")],
                    "needs_work": overdue > 0}
        E.append({"id": f"tree:{mid}", "type": "belongs_to_category", "source": mid, "target": PEOPLE_ID})
        if m["person_node_id"] in out:
            E.append({"id": f"same:{mid}", "type": "related_to", "relation": "same_person", "source": mid,
                      "target": m["person_node_id"]})

    # ------------------------------------------------------------ task leaves
    if tasks:
        for t in open_tasks:
            host = visible(t["node_id"])
            if host not in out:
                continue
            tid = f"task:{t['id']}"
            r = _reminder(t, now)
            out[tid] = {"id": tid, "type": "task", "task_id": t["id"], "title": t["title"], "parent_id": host,
                        "node_id": t["node_id"],
                        "channel": by_id[t["node_id"]]["title"] if t["node_id"] != host else None,
                        "priority": t["priority"], "due_at": t["due_at"], "due_state": r["state"],
                        "assignee_member": t["assignee_member"], "assignee": r["assignee"],
                        "provenance": {"capture_id": t["capture_id"], "created_at": t["created_at"]}}
            E.append({"id": f"has:{t['id']}", "type": "has_task", "source": host, "target": tid})
            if t["assignee_member"] and f"member:{t['assignee_member']}" in out:
                E.append({"id": f"asg:{t['id']}", "type": "assigned_to", "source": tid,
                          "target": f"member:{t['assignee_member']}"})

    # ------------------------------------------------------------ cross-links
    for e in edges:
        s, d = visible(e["src_id"]), visible(e["dst_id"])
        if s in out and d in out and s != d:
            E.append({"id": f"edge:{e['id']}", "type": "assigned_to" if e["edge_type"] == "assigned_to" else "related_to",
                      "relation": e["edge_type"], "source": s, "target": d, "weight": e["weight"],
                      "created_by": e["created_by"]})

    r = out[root["id"]]
    return {
        "workspace": {"id": ws, "name": wsrow["name"], "persona": wsrow["persona"], "locale": wsrow["locale"]},
        "generated_at": now_iso(now.timestamp()), "cursor": brain.broker.last_id if cursor is None else cursor,
        "root": root["id"],
        "stats": {"nodes": sum(1 for x in out.values() if x["type"] in ("category", "entity")),
                  "entities": r["counts"]["entities"], "entities_needing_work": r["counts"]["entities_needing_work"],
                  "nodes_needing_work": sum(1 for x in out.values() if x["type"] in ("category", "entity") and not x.get("virtual")
                                            and needs_work(x)),
                  "open_tasks": len(open_tasks), "open_alerts": len(alerts),
                  "overdue_tasks": sum(1 for t in open_tasks if _reminder(t, now)["state"] == "overdue"),
                  "inbox": db.one("select count(*) as c from inbox where workspace_id=? and state='open'", (ws,))["c"],
                  "progress_pct": r["progress_pct"]},
        "nodes": list(out.values()),
        "edges": E,
    }


def summary(mm: dict, limit: int = 20) -> dict:
    """Short facts from the map for the companion: what needs work, and how far along things are."""
    nodes = {n["id"]: n for n in mm["nodes"]}
    work, progress = [], []
    for n in mm["nodes"]:
        if n["type"] not in ("entity", "category") or n.get("virtual"):
            continue
        c = n["counts"]
        if STATUS_RANK.get(n["display_status"], 2) >= STATUS_RANK["routine_due"] or c["open_tasks"] or c["open_alerts"]:
            tasks = [x["title"] for x in mm["nodes"] if x["type"] == "task" and x["parent_id"] == n["id"]]
            work.append({"node_id": n["id"], "title": n["title"], "path": n["path"], "type": n["type"],
                         "status": n["display_status"], "open_tasks": c["open_tasks"],
                         "open_alerts": c["open_alerts"], "overdue_tasks": c["overdue_tasks"],
                         "alerts": [a["title"] for a in n.get("alerts", [])][:3], "tasks": tasks[:3]})
        if n["progress"] and n["progress"]["source"] != "status":
            p = n["progress"]
            progress.append({"node_id": n["id"], "title": n["title"], "path": n["path"], "pct": p["pct"],
                             "done": p["done"], "total": p["total"], "unit": p["unit"], "verb": p["verb"],
                             "source": p["source"]})
    work.sort(key=lambda w: (-STATUS_RANK.get(w["status"], 2), -w["overdue_tasks"], -w["open_alerts"], -w["open_tasks"]))
    lines = []
    for w in work[:limit]:
        bits = [w["status"]] if w["status"] not in ("ok", "info") else []
        if w["alerts"]:
            bits.append("alert: " + "; ".join(w["alerts"]))
        if w["tasks"]:
            bits.append(f"{w['open_tasks']} open task(s): " + "; ".join(w["tasks"]))
        if w["overdue_tasks"]:
            bits.append(f"{w['overdue_tasks']} overdue")
        lines.append(f"NEEDS WORK {w['path']}: " + ", ".join(bits or ["check"]))
    for p in progress[:limit]:
        if p["done"] is not None and p["total"] is not None and p["unit"] not in (None, "%"):
            lines.append(f"PROGRESS {p['path']}: {p['done']:g} of {p['total']:g} {p['unit']} {p['verb']} ({p['pct']:g}%)")
        else:
            lines.append(f"PROGRESS {p['path']}: {p['pct']:g}% {p['verb']}")
    ok = [n["path"] for n in nodes.values() if n["type"] == "entity" and not n["needs_work"]]
    if ok:
        lines.append("ALL OK: " + ", ".join(ok[:15]))
    return {"needs_work": work[:limit], "progress": progress[:limit], "lines": lines}
