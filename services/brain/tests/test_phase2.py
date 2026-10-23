# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Phase 2: the mind map payload, live events (SSE), context-anchored capture and the companion's map awareness."""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from farm import make_brain, seed_farm
from notecad_brain import mindmap
from notecad_brain.api import create_app
from notecad_brain.common import parse_iso
from notecad_brain.stt import Transcript

AT = "2026-10-19T06:00:00+00:00"  # Monday 08:00 SAST
LEAK = "The tractor hydraulic hose is leaking. Ask Sipho to replace it tomorrow."


def _capture(b, ws, text, **kw):
    r = b.register_capture(ws, text=text, recorded_at=AT, enqueue=False, **kw)
    return b.process(r["capture_id"])


def _nodes(mm):
    return {n["id"]: n for n in mm["nodes"]}


def _parse_sse(raw: str) -> list[dict]:
    out = []
    for block in raw.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "data" in fields:
            out.append({"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])})
    return out


# ==================================================================== mind map payload
def test_mindmap_payload_structure(farm):
    b, ids = farm
    res = _capture(b, ids["ws"], LEAK)
    cid = res["capture_id"]
    now = datetime(2026, 10, 19, 9, tzinfo=timezone.utc)
    mm = b.mindmap(ids["ws"], now=now)
    nodes = _nodes(mm)

    assert set(mm) >= {"workspace", "generated_at", "cursor", "root", "stats", "nodes", "edges"}
    assert mm["cursor"] == b.broker.last_id > 0
    assert nodes[mm["root"]]["type"] == "root" and nodes[mm["root"]]["title"] == "Highveld Farm"
    types = {n["type"] for n in mm["nodes"]}
    assert types == {"root", "category", "entity", "task", "member"}
    assert not any(n.get("kind") == "channel" for n in mm["nodes"])  # channels fold into their parent

    # category roll-ups: Tractors carries the leak (on its Maintenance channel), Vehicles shows the echo dot
    tractors, vehicles = nodes[ids["tractors"]], nodes[nodes[ids["tractors"]]["parent_id"]]
    assert tractors["type"] == "category" and vehicles["title"] == "Vehicles"
    assert tractors["display_status"] in ("warning", "critical") and tractors["counts"]["open_alerts"] == 1
    assert tractors["counts"]["open_tasks"] == 1 and tractors["needs_work"]
    assert tractors["channels"][0]["title"] == "Maintenance" and tractors["alerts"][0]["channel"] == "Maintenance"
    assert vehicles["echo_dot"] and vehicles["echo_status"] == tractors["display_status"]
    assert vehicles["counts"]["subtree_open_tasks"] == 1 and vehicles["counts"]["subtree_open_alerts"] == 1
    assert nodes[mm["root"]]["counts"]["subtree_open_tasks"] == mm["stats"]["open_tasks"] == 1

    # entity: server-side status, decay, progress
    beans = nodes[ids["beans"]]
    assert beans["type"] == "entity" and beans["progress_pct"] == pytest.approx(93.3)
    assert beans["progress"]["done"] == 2800 and beans["progress"]["total"] == 3000 and beans["progress"]["verb"] == "planted"
    assert nodes[nodes[ids["beans"]]["parent_id"]]["progress_pct"] == pytest.approx(93.3)  # Crops: area-weighted roll-up
    for n in mm["nodes"]:
        if n["type"] in ("entity", "category", "root") and not n.get("virtual"):
            assert {"display_status", "child_worst", "echo_dot", "decay", "counts", "progress_pct", "reminders",
                    "recent_notes"} <= set(n)
            assert n["decay"]["state"] in ("fresh", "fading", "settled", "active") and 0 <= n["decay"]["score"] <= 1
    assert tractors["decay"]["state"] == "active"

    # task leaf, reminder, delegation
    task = next(n for n in mm["nodes"] if n["type"] == "task")
    assert task["parent_id"] == ids["tractors"] and task["assignee"] == "Sipho Dlamini"
    assert task["due_state"] == "due_soon" and task["provenance"]["capture_id"] == cid
    assert tractors["reminders"][0]["state"] == "due_soon"
    people = nodes[mindmap.PEOPLE_ID]
    assert people["virtual"] and people["counts"]["delegated_open_tasks"] == 1
    sipho = nodes[f"member:{ids['sipho']}"]
    assert sipho["counts"]["open_tasks"] == 1 and sipho["person_node_id"] == ids["sipho_node"]

    # notes with provenance
    note = tractors["recent_notes"][0]
    assert note["provenance"]["capture_id"] == cid and note["provenance"]["router"] == "rules"

    # edges: the four types, every end is a node in the payload
    by_type = {}
    for e in mm["edges"]:
        assert e["source"] in nodes and e["target"] in nodes, e
        by_type.setdefault(e["type"], []).append(e)
    assert set(by_type) == {"belongs_to_category", "has_task", "assigned_to", "related_to"}
    assert {"source": ids["tractors"], "target": task["id"]} in [{k: e[k] for k in ("source", "target")} for e in by_type["has_task"]]
    assert any(e["source"] == task["id"] and e["target"] == sipho["id"] for e in by_type["assigned_to"])
    assert any(e["source"] == ids["tractors"] and e["target"] == ids["sipho_node"] for e in by_type["assigned_to"])
    assert any(e["relation"] == "same_person" for e in by_type["related_to"])

    # a day later the reminder is overdue; the info ring of a plain note fades
    later = _nodes(b.mindmap(ids["ws"], now=parse_iso(task["due_at"]) + timedelta(hours=1)))
    assert later[task["id"]]["due_state"] == "overdue" and later[ids["tractors"]]["counts"]["overdue_tasks"] == 1


def test_decay_and_progress_rules():
    t0 = datetime(2026, 10, 19, 6, tzinfo=timezone.utc)
    info = {"status": "info", "status_since": t0.isoformat()}
    assert mindmap.decay_of(info, t0 + timedelta(hours=6))["state"] == "fresh"
    assert mindmap.decay_of(info, t0 + timedelta(hours=18))["state"] == "fading"
    assert mindmap.decay_of(info, t0 + timedelta(hours=30))["score"] == 0
    assert mindmap.decay_of({"status": "done", "status_since": t0.isoformat()}, t0 + timedelta(hours=30))["state"] == "fading"
    node = {"kind": "field", "status": "ok", "attributes": {"area_ha": 400, "planted_ha": 400, "harvested_ha": 100,
                                                            "phase": "harvest"}}
    assert mindmap.progress_of(node)["pct"] == 25.0 and mindmap.progress_of(node)["verb"] == "harvested"
    assert mindmap.progress_of({"kind": "project", "status": "ok", "attributes": {}}, 3, 1)["pct"] == 75.0
    assert mindmap.progress_of({"kind": "asset", "status": "ok", "attributes": {"progress_pct": 40}})["pct"] == 40
    assert mindmap.progress_of({"kind": "asset", "status": "ok", "attributes": {}}, 3, 1) is None


def test_mindmap_api_under_api_prefix_and_token(tmp_path):
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}")
    b.settings.api_token = "s3cret"
    ids = seed_farm(b)
    c = TestClient(create_app(b))
    url = f"/api/v1/workspaces/{ids['ws']}/mindmap"
    assert c.get(url).status_code == 401
    h = {"Authorization": "Bearer s3cret"}
    mm = c.get(url, headers=h).json()
    assert mm["root"] == ids["root"] and any(n["id"] == ids["beans"] for n in mm["nodes"])
    assert c.get(f"/v1/workspaces/{ids['ws']}/mindmap?tasks=false", headers=h).status_code == 200
    assert c.get(url + "?token=s3cret").status_code == 200  # EventSource-style token
    p = c.patch(f"/api/v1/nodes/{ids['pivot']}", headers=h, json={"attributes": {"progress_pct": 40}}).json()
    assert p["attributes"] == {"progress_pct": 40}
    mm = c.get(url, headers=h).json()
    assert next(n for n in mm["nodes"] if n["id"] == ids["pivot"])["progress_pct"] == 40
    assert c.get("/api/v1/workspaces/nope/mindmap", headers=h).status_code == 404
    pre = c.options(url, headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
                                  "Access-Control-Request-Headers": "authorization"})
    assert pre.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ==================================================================== live events
def test_sse_event_sequence_for_capture_inbox_and_undo(farm):
    b, ids = farm
    ws = ids["ws"]
    res = _capture(b, ws, "The main water pump is leaking badly.")
    cid = res["capture_id"]
    seq = [m["type"] for m in b.broker.of(ws, cid)]
    assert seq[:4] == ["capture.queued", "stt.completed", "router.resolving", "action.applied"]
    assert seq[-1] == "capture.completed" and "node.updated" in seq
    msgs = b.broker.of(ws, cid)
    assert [m["id"] for m in msgs] == sorted(m["id"] for m in msgs)
    applied = next(m for m in msgs if m["type"] == "action.applied")
    assert ids["pump"] in applied["node_ids"] and {ids["water"], ids["infra"]} <= set(applied["affected_node_ids"])
    assert applied["alerts"] == 1 and "create_alert" in applied["actions"]
    assert next(m for m in msgs if m["type"] == "stt.completed")["typed"] is True

    held = _capture(b, ws, "Remember to phone the co-op about the invoice.")
    inbox = next(m for m in b.broker.of(ws, held["capture_id"]) if m["type"] == "inbox.created")
    assert inbox["options"] and inbox["inbox_id"] and inbox["text"].startswith("Remember")
    assert b.broker.of(ws, held["capture_id"])[-1]["state"] == "needs_review"

    b.undo(cid)
    undone = next(m for m in b.broker.of(ws, cid) if m["type"] == "action.undone")
    assert ids["pump"] in undone["node_ids"] and undone["reverted"] > 0
    node_after = [m for m in b.broker.of(ws, cid) if m["type"] == "node.updated" and m["node_id"] == ids["pump"]][-1]
    assert node_after["open_alerts"] == 0


def test_sse_stream_over_http_replay_filter_and_live(tmp_path):
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}")
    ids = seed_farm(b)
    c = TestClient(create_app(b))
    ws = ids["ws"]
    cursor = c.get(f"/api/v1/workspaces/{ws}/mindmap").json()["cursor"]
    r = c.post(f"/api/v1/workspaces/{ws}/capture", json={"text": "The main water pump is leaking badly.", "recorded_at": AT})
    assert r.status_code == 200 and r.json()["state"] == "applied"

    # replay with Last-Event-ID: the whole sequence, in order, with ids
    with c.stream("GET", f"/api/v1/workspaces/{ws}/events/stream?limit=4",
                  headers={"Last-Event-ID": str(cursor)}) as s:
        assert s.headers["content-type"].startswith("text/event-stream")
        evs = _parse_sse(s.read().decode())
    assert [e["event"] for e in evs] == ["capture.queued", "stt.completed", "router.resolving", "action.applied"]
    assert all(e["id"] > cursor for e in evs) and evs[0]["data"]["id"] == evs[0]["id"]

    # filtered: only the action.* and capture.completed events
    raw = c.get(f"/v1/workspaces/{ws}/events/stream?last_event_id={cursor}&types=action,capture.completed&limit=2").text
    assert [e["event"] for e in _parse_sse(raw)] == ["action.applied", "capture.completed"]

    # live: a client listening while a note comes in
    last = b.broker.last_id
    got: list = []

    def listen():
        with c.stream("GET", f"/api/v1/workspaces/{ws}/events/stream?last_event_id={last}&types=stt,router,action&limit=3") as s:
            got.extend(_parse_sse(s.read().decode()))
    t = threading.Thread(target=listen)
    t.start()
    time.sleep(0.2)
    c.post(f"/api/v1/workspaces/{ws}/capture", json={"text": "Fencing done on the north side.", "recorded_at": AT})
    t.join(10)
    assert not t.is_alive()
    assert [e["event"] for e in got] == ["stt.completed", "router.resolving", "action.applied"]


# ==================================================================== context-anchored capture
def test_anchor_routes_unnamed_note_to_open_node_but_named_thing_wins(farm):
    b, ids = farm
    ws = ids["ws"]
    plain = _capture(b, ws, "Needs new tyres before the season.")
    assert plain["events"][0]["state"] == "needs_review"  # no anchor, nothing named: the owner is asked

    on = _capture(b, ws, "Needs new tyres before the season.", context_node_id=ids["tractors"])
    assert on["events"][0]["state"] == "applied"
    assert b.db.one("select node_id from notes where capture_id=?", (on["capture_id"],))["node_id"] == ids["tractors"]
    assert b.db.one("select anchor_node_id from captures where id=?", (on["capture_id"],))["anchor_node_id"] == ids["tractors"]
    resolving = next(m for m in b.broker.of(ws, on["capture_id"]) if m["type"] == "router.resolving")
    assert resolving["context_node_id"] == ids["tractors"]

    named = _capture(b, ws, "The main water pump is leaking badly.", context_node_id=ids["tractors"])
    assert b.db.one("select node_id from notes where capture_id=?", (named["capture_id"],))["node_id"] == ids["pump"]

    problem = _capture(b, ws, "Hydraulic oil is leaking badly.", context_node_id=ids["tractors"])
    assert b.db.one("select node_id from alerts where capture_id=?", (problem["capture_id"],))["node_id"] == ids["tractor_maint"]

    with pytest.raises(Exception):
        b.register_capture(ws, text="x", context_node_id="not-a-node")


def test_anchor_boosts_one_hop_neighbours(farm):
    b, ids = farm
    cands = {c["node_id"]: c for c in b.retriever.candidates(ids["ws"], "needs a service", anchor=ids["tractors"])}
    assert cands[ids["tractors"]]["via"].startswith("anchor")
    assert ids["tractor_maint"] in cands and cands[ids["tractor_maint"]]["score"] >= 0.6
    top = max(cands.values(), key=lambda c: c["score"])
    assert top["node_id"] == ids["tractors"]
    pump = {c["node_id"]: c for c in b.retriever.candidates(ids["ws"], "needs a service", anchor=ids["pump"])}
    assert pump[ids["water"]]["score"] >= 0.5  # its parent group is one hop away
    assert max(pump.values(), key=lambda c: c["score"])["node_id"] == ids["pump"]


def test_local_router_gets_the_anchor(farm):
    from notecad_companion.llm import ScriptedLLM
    from notecad_brain.routers import LocalRouter, RouterChain
    b, ids = farm
    seen = {}

    def fn(msgs, schema):
        seen["system"], seen["user"] = msgs[0]["content"], msgs[1]["content"]
        return json.dumps({"node_id": ids["tractors"], "kind": "todo", "severity": "none", "note": "Tractor needs new tyres.",
                           "task_title": "Fit new tyres", "assignee": "", "place_node_id": "none",
                           "new_item_title": "", "confidence": 0.9})
    b.routers = RouterChain([LocalRouter(ScriptedLLM(fn))])
    _capture(b, ids["ws"], "Needs new tyres before the season.", context_node_id=ids["tractors"])
    assert "Operations > Vehicles > Tractors" in seen["system"] and ids["tractors"] in seen["system"]
    assert seen["user"].split("NODES:\n")[1].startswith(ids["tractors"])  # listed first


def test_capture_endpoint_multipart_audio_json_and_errors(tmp_path):
    heard = {}

    class FakeSTT:
        name = "fake"

        def transcribe(self, audio, *, mime, lang_hint, keyterms):
            heard["mime"] = mime
            return Transcript(text="needs new tyres before the season", language="en", confidence=0.9, engine="fake")
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}", audio_dir=str(tmp_path / "audio"), stt=FakeSTT())
    ids = seed_farm(b)
    c = TestClient(create_app(b))
    ws = ids["ws"]
    url = f"/api/v1/workspaces/{ws}/capture"

    # multipart WebM, processed now, anchored on Tractors
    r = c.post(url, files={"file": ("note.webm", b"\x1aE\xdf\xa3webm", "audio/webm")},
               data={"context_node_id": ids["tractors"], "wait": "true", "recorded_at": AT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "applied" and body["context_node_id"] == ids["tractors"] and heard["mime"] == "audio/webm"
    assert b.db.one("select node_id from notes where capture_id=?", (body["capture_id"],))["node_id"] == ids["tractors"]
    seq = [m["type"] for m in b.broker.of(ws, body["capture_id"])]
    assert seq[:5] == ["capture.queued", "stt.transcribing", "stt.completed", "router.resolving", "action.applied"]
    assert next(m for m in b.broker.of(ws, body["capture_id"]) if m["type"] == "stt.completed")["transcript"] == \
        "needs new tyres before the season"

    # Opus from the phone, queued for the worker (default for audio): 202, then the worker routes it
    r = c.post(url, files={"audio": ("clip.opus", b"OggS-opus", "application/octet-stream")})
    assert r.status_code == 202 and r.json()["state"] == "queued" and b.run_jobs() == 1
    assert heard["mime"] == "audio/ogg"
    # WAV as a raw body, query parameters
    r = c.post(url + f"?context_node_id={ids['pump']}", content=b"RIFF....WAVE", headers={"content-type": "audio/wav"})
    assert r.status_code == 202 and b.run_jobs() == 1
    assert b.capture_summary(r.json()["capture_id"])["context_node_id"] == ids["pump"]

    # typed note as JSON and as a form field
    r = c.post(url, json={"text": "Fencing done on the north side.", "context_node_id": ids["north_fence"]})
    assert r.status_code == 200 and r.json()["state"] == "applied"
    r = c.post(url, data={"text": "The main water pump is leaking badly."})
    assert r.status_code == 200 and r.json()["events"][0]["state"] == "applied"
    # idempotent on capture_id
    again = c.post(url, json={"text": "The main water pump is leaking badly.", "capture_id": r.json()["capture_id"]})
    assert again.json()["duplicate"] is True

    # errors
    assert c.post(url, content=b"hello", headers={"content-type": "text/plain"}).status_code == 415
    assert c.post(url, json={"text": "   "}).status_code == 422
    assert c.post(url, json={"text": "x", "context_node_id": "nope"}).status_code == 400
    assert c.post(url, files={"file": ("a.txt", b"abc", "text/plain")}).status_code == 415
    assert c.post(url, json={"text": "x", "capture_id": "bad id!"}).status_code == 422


# ==================================================================== companion: map awareness
def test_digest_carries_map_lines_and_focus(farm):
    b, ids = farm
    _capture(b, ids["ws"], LEAK)
    d = b.digest(ids["ws"], focus=ids["beans"])
    lines = d["map"]["lines"]
    assert any(l.startswith("NEEDS WORK Operations > Vehicles > Tractors") and "Ask Sipho" in l for l in lines)
    assert "PROGRESS Operations > Crops > Beans: 2800 of 3000 ha planted (93.3%)" in lines
    assert d["focus"]["title"] == "Beans" and d["focus"]["progress"]["pct"] == pytest.approx(93.3)
    assert b.digest(ids["ws"], focus=ids["tractor_maint"])["focus"]["title"] == "Tractors"  # a channel shows its parent


def test_companion_answers_map_questions_from_the_brain(tmp_path):
    """The companion reads the real brain API: 'Which tractors need work?' and 'How much is planted?' are
    answered from map lines, and a question asked with a node open gets that node's facts."""
    from notecad_companion.api import brain_digest
    from notecad_companion.companion import Companion
    from notecad_companion.embed import HashEmbedder
    from notecad_companion.llm import ScriptedLLM
    from notecad_companion.store import Store

    b = make_brain(f"sqlite:///{tmp_path/'b.db'}")
    ids = seed_farm(b)
    _capture(b, ids["ws"], LEAK)
    tc = TestClient(create_app(b))
    import httpx

    def bridge(req: httpx.Request) -> httpx.Response:  # the companion's HTTP client, served by the real brain app
        r = tc.request(req.method, req.url.raw_path.decode())
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": r.headers["content-type"]})
    fetch = brain_digest("http://brain", ids["ws"], transport=httpx.MockTransport(bridge))
    comp = Companion(Store(":memory:"), ScriptedLLM(), HashEmbedder(256), open_work=fetch, llm_fact_extraction=False)

    comp.chat("Which tractors need work?")
    system = comp.llm.calls[-1][0][0]["content"]
    assert "NEEDS WORK Operations > Vehicles > Tractors" in system and "hydraulic hose" in system
    assert "PROGRESS Operations > Crops > Beans: 2800 of 3000 ha planted (93.3%)" in system
    assert "Ask Sipho to replace it tomorrow - Operations > Vehicles > Tractors - Sipho Dlamini, due" in system

    comp.chat("How much of this is planted?", context_node_id=ids["beans"])
    system = comp.llm.calls[-1][0][0]["content"]
    assert "OPEN ON SCREEN NOW" in system and "Operations > Crops > Beans" in system and "2800 of 3000 ha planted" in system


def test_local_router_anchor_beats_an_unnamed_model_pick(farm):
    """Live on WABAKIPI, Gemma filed 'Die hidrouliese pyp lek' (recorded on Tractors) under Water: 'pyp' sounds like
    plumbing. A pick the owner never named loses to the anchor; a thing named outright still wins."""
    from notecad_companion.llm import ScriptedLLM
    from notecad_brain.routers import LocalRouter, RouterChain
    b, ids = farm
    pick = {}

    def fn(msgs, schema):
        return json.dumps({"node_id": pick["id"], "kind": "problem", "severity": "warning", "note": "Pipe leaking.",
                           "task_title": "", "assignee": "", "place_node_id": "none", "new_item_title": "",
                           "confidence": 0.8})
    b.routers = RouterChain([LocalRouter(ScriptedLLM(fn))])
    pick["id"] = ids["water"]
    r = _capture(b, ids["ws"], "Die hidrouliese pyp lek.", context_node_id=ids["tractors"])
    assert b.db.one("select node_id from alerts where capture_id=?", (r["capture_id"],))["node_id"] in \
        (ids["tractors"], ids["tractor_maint"])
    pick["id"] = ids["pump"]
    r = _capture(b, ids["ws"], "Die hoofpomp lek.", context_node_id=ids["tractors"])
    assert b.db.one("select node_id from alerts where capture_id=?", (r["capture_id"],))["node_id"] == ids["pump"]


# ==================================================================== Phase 3 support: ranges, field progress, history, sync
def test_text_number_ranges():
    from notecad_brain.text import expand_ranges
    known = {"704", "705", "706", "708", "2026"}
    assert expand_ranges("Planted field south 704 to 708", known) == [
        "Planted field south 704", "Planted field south 705", "Planted field south 706", "Planted field south 708"]
    assert expand_ranges("Fields 704-706 sprayed", known)[1] == "Fields 705 sprayed"
    assert expand_ranges("Bought 10 to 12 ewes", known) == ["Bought 10 to 12 ewes"]  # not the owner's numbered things
    assert expand_ranges("from 704 to 2026", known) == ["from 704 to 2026"]  # too wide


def _fields(b, ids):
    g = b.graph
    block = g.add_node(ids["ws"], ids["ops"], "South Block", "group")
    out = {}
    for n, ha in ((704, 40), (705, 52), (706, 38), (707, 61), (708, 45)):
        out[n] = g.add_node(ids["ws"], block, f"Field South {n}", "field", aliases=[f"field {n}"],
                            attributes={"area_ha": ha, "planted_ha": 0, "phase": "planting"})
    return block, out


def test_planted_range_updates_five_fields_and_their_progress(farm):
    b, ids = farm
    block, fields = _fields(b, ids)
    res = _capture(b, ids["ws"], "Today I planted field south 704 to 708.")
    assert [e["state"] for e in res["events"]] == ["applied"] * 5
    for n, nid in fields.items():
        assert b.graph.node(nid)["attributes"]["planted_ha"] == b.graph.node(nid)["attributes"]["area_ha"], n
    applied = [m for m in b.broker.of(ids["ws"], res["capture_id"]) if m["type"] == "action.applied"]
    assert sorted(m["nodes"][0]["map_id"] for m in applied) == sorted(fields.values())
    assert applied[0]["nodes"][0]["path"].endswith("South Block > Field South 704")
    mm = _nodes(b.mindmap(ids["ws"]))
    assert all(mm[f]["progress_pct"] == 100 for f in fields.values()) and mm[block]["progress_pct"] == 100
    # a stated number of hectares is added; future work changes nothing
    _capture(b, ids["ws"], "Planted 10 ha on field south 707.")
    assert b.graph.node(fields[707])["attributes"]["planted_ha"] == 61  # already full: capped by validation -> inbox
    _capture(b, ids["ws"], "We will plant field 704 next week.")
    assert b.graph.node(fields[704])["attributes"]["planted_ha"] == 40


def test_planted_hectares_increment(farm):
    b, ids = farm
    _, fields = _fields(b, ids)
    _capture(b, ids["ws"], "Planted 12 ha on field 705 today.")
    assert b.graph.node(fields[705])["attributes"]["planted_ha"] == 12
    assert _nodes(b.mindmap(ids["ws"]))[fields[705]]["progress_pct"] == pytest.approx(23.1)


def test_node_history_sync_status_and_workspace_list(tmp_path):
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}")
    ids = seed_farm(b)
    c = TestClient(create_app(b))
    r = c.post(f"/api/v1/workspaces/{ids['ws']}/capture", json={"text": LEAK, "recorded_at": AT}).json()
    hist = c.get(f"/api/v1/nodes/{ids['tractors']}/history").json()
    types = [h["type"] for h in hist]
    assert "append_note" in types and "create_alert" in types and "create_task" in types
    assert all(h["capture_id"] == r["capture_id"] and h["capture_text"] == LEAK for h in hist)
    assert any(h["channel"] == "Maintenance" for h in hist) and not any(h["undone"] for h in hist)
    c.post(f"/api/v1/captures/{r['capture_id']}/undo")
    assert all(h["undone"] for h in c.get(f"/api/v1/nodes/{ids['tractors']}/history").json())
    s = c.get(f"/api/v1/workspaces/{ids['ws']}/sync").json()
    assert s["ok"] and s["db"] == "sqlite" and s["integrity"] == "ok" and s["journal_mode"] == "wal"
    assert s["pending"]["sync_events"] > 0 and s["pending"]["captures_in_flight"] == 0 and s["last_event_id"] > 0
    ws = c.get("/api/v1/workspaces").json()
    assert ws[0]["id"] == ids["ws"] and ws[0]["nodes"] > 10
    assert c.get("/api/v1/nodes/nope/history").status_code == 404


def test_brain_serves_the_desktop_app(tmp_path):
    ui = tmp_path / "dist"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>NoteCad</title>")
    (ui / "assets" / "a.js").write_text("console.log(1)")
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}")
    b.settings.ui_dir = str(ui)
    c = TestClient(create_app(b))
    assert "NoteCad" in c.get("/app/").text and c.get("/app/assets/a.js").status_code == 200
    assert c.get("/", follow_redirects=False).headers["location"] == "/app/"
    assert c.get("/api/health").json()["ok"]
    b.settings.ui_dir = ""
    assert TestClient(create_app(b)).get("/app/").status_code == 404


def test_planted_field_is_done_work_even_when_the_model_says_todo(farm):
    """Live on WABAKIPI Gemma called 'Today I planted field south 705' a todo: a task, and no progress."""
    from notecad_companion.llm import ScriptedLLM
    from notecad_brain.routers import LocalRouter, RouterChain
    b, ids = farm
    _, fields = _fields(b, ids)

    def fn(msgs, schema):
        nid = next(f for n, f in fields.items() if str(n) in msgs[1]["content"].split("EVENT:")[1])
        return json.dumps({"node_id": nid, "kind": "todo", "severity": "none", "note": "Field planted.",
                           "task_title": "Plant field", "assignee": "", "place_node_id": "none",
                           "new_item_title": "", "confidence": 0.9})
    b.routers = RouterChain([LocalRouter(ScriptedLLM(fn))])
    res = _capture(b, ids["ws"], "Today I planted field south 704 to 708")
    assert len(res["events"]) == 5
    assert b.db.one("select count(*) as c from tasks where capture_id=?", (res["capture_id"],))["c"] == 0
    assert all(b.graph.node(f)["attributes"]["planted_ha"] == b.graph.node(f)["attributes"]["area_ha"] for f in fields.values())
    _capture(b, ids["ws"], "We must plant field 704 again next week.")  # a real todo stays a todo
    assert b.db.one("select count(*) as c from tasks where node_id=?", (fields[704],))["c"] == 1
