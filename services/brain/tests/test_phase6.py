# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Phase 6: regressions found in the full pass (ADR 0013). One test per bug."""
from datetime import datetime, timezone

from notecad_brain.routers import RouteContext, RulesRouter


def _ctx(event: str, candidates: list[dict], **kw) -> RouteContext:
    return RouteContext(capture_id="c1", event_index=0, event=event, transcript=event,
                        captured_at=datetime(2026, 10, 28, 8, tzinfo=timezone.utc), lang="en",
                        candidates=candidates, spine=[], **kw)


def _cand(nid, path, kind, score, aliases=(), parent=None):
    return {"node_id": nid, "path": path, "title": path.split(" > ")[-1], "kind": kind, "score": score,
            "aliases": list(aliases), "parent_id": parent}


def test_rules_prefer_the_named_child_over_its_one_word_parent():
    """Showcase note 3 with EmbeddingGemma scores: "Water" (alias water) out-scored its child "North Borehole Pump"
    by 0.02 and the task landed on the category. The child is named in the note, so it wins."""
    cands = [
        _cand("pump", "Water > North Borehole Pump", "asset", 0.918,
              ["noord boorgat", "noord pomp", "north borehole", "north borehole pump"], "water"),
        _cand("water", "Water", "category", 0.885, ["boorgate", "boreholes", "water"]),
        _cand("sipho", "Admin > Staff > Sipho", "person", 0.885, ["foreman", "sipho dlamini", "voorman"], "staff"),
        _cand("north", "Fields > North Block", "group", 0.818, ["noord", "north"], "fields"),
    ]
    out = RulesRouter().route(_ctx("Ask Sipho to check the water pump on the North borehole", cands,
                                   people=[{"name": "Sipho Dlamini"}]))
    task = next(a for a in out["actions"] if a["type"] == "create_task")
    assert task["node_id"] == "pump" and task["assignee_hint"] == "Sipho"


def test_rules_keep_the_parent_when_no_child_is_named():
    cands = [_cand("water", "Water", "category", 0.9, ["water"]),
             _cand("pump", "Water > North Borehole Pump", "asset", 0.86, ["north borehole"], "water")]
    out = RulesRouter().route(_ctx("Water pressure is low today", cands))
    assert {a["node_id"] for a in out["actions"]} == {"water"}


# ---------------------------------------------------------------- rule words (text.py)
def test_english_more_is_not_afrikaans_tomorrow():
    from notecad_brain.text import parse_due
    at = datetime(2026, 10, 28, 8, tzinfo=timezone.utc)
    assert parse_due("Need more diesel for the bakkie", at) is None
    assert parse_due("Ons moet more die pomp regmaak", at) is not None  # Afrikaans: môre without the accent


def test_brand_new_and_sit_down_are_not_critical():
    from notecad_brain.text import CRITICAL
    assert not CRITICAL.search("We bought a brand new pump")
    assert not CRITICAL.search("Sit down with Sipho about the fence")
    assert CRITICAL.search("The borehole pump is down") and CRITICAL.search("Die skuur is aan die brand")


def test_no_one_is_not_unit_number_one():
    from notecad_brain.text import normalise
    assert normalise("No one fed the dogs") == "No one fed the dogs"
    assert normalise("John Deere no. one").endswith("no. 1") and normalise("tractor number one").endswith("number 1")


# ---------------------------------------------------------------- live events, worker, decay
def test_event_ids_survive_a_restart():
    """Ids restarted at 1, so a desktop reconnecting with Last-Event-ID 4000 dropped every new event."""
    from notecad_brain.events import Broker
    old = Broker()
    for _ in range(3):
        old.publish("ws", "node.updated", {})
    new = Broker()  # the brain restarted
    m = new.publish("ws", "node.updated", {})
    assert m["id"] > old.last_id - 3 and new.since("ws", 10**15) == []  # an id from the future: nothing missed


def test_full_client_queue_does_not_raise_in_the_loop():
    import asyncio
    from notecad_brain.events import Broker
    b = Broker()
    errors = []

    async def main():
        asyncio.get_running_loop().set_exception_handler(lambda _l, ctx: errors.append(ctx))
        q = b.subscribe("ws")
        for _ in range(1005):
            b.publish("ws", "x", {})
        await asyncio.sleep(0.05)
        return q.qsize()

    assert asyncio.run(main()) == 1000 and errors == []


def test_stream_after_restart_delivers_new_events(farm):
    from fastapi.testclient import TestClient
    from notecad_brain.api import create_app
    b, ids = farm
    b.settings.worker = False
    c = TestClient(create_app(b))
    b.broker.publish(ids["ws"], "node.updated", {"n": 1})
    with c.stream("GET", f"/api/v1/workspaces/{ids['ws']}/events/stream?limit=1",
                  headers={"Last-Event-ID": str(b.broker.last_id + 10**9)}) as r:
        b.broker.publish(ids["ws"], "node.updated", {"n": 2})
        body = "".join(r.iter_text())
    assert '"n": 2' in body


def test_running_jobs_are_requeued_on_start(farm):
    b, ids = farm
    r = b.register_capture(ids["ws"], text="The main pump is leaking", enqueue=True)
    b.db.execute("update jobs set state='running'")  # the brain died mid-capture
    assert b.run_jobs() == 0
    assert b.recover_jobs() == 1 and b.run_jobs() == 1
    assert b.db.one("select state from captures where id=?", (r["capture_id"],))["state"] in ("applied", "needs_review")


def test_decay_runs_for_every_workspace(farm):
    b, ids = farm
    b.graph.set_status(ids["pump"], "info", "old news")
    b.db.execute("update nodes set status_since='2026-01-01T00:00:00+00:00' where id=?", (ids["pump"],))
    assert b.decay_all() == 1 and b.graph.node(ids["pump"])["status"] == "ok"
    assert b.broker.recent[-1]["type"] == "node.updated"


# ---------------------------------------------------------------- tokens and other web pages
def _app(b, token=None):
    from fastapi.testclient import TestClient
    from notecad_brain.api import create_app
    b.settings.worker, b.settings.api_token = False, token
    return TestClient(create_app(b))


def test_a_foreign_web_page_cannot_post_notes_on_this_pc(farm):
    b, ids = farm
    c = _app(b)
    url = f"/api/v1/workspaces/{ids['ws']}/capture"
    assert c.post(url, data={"text": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post(url, data={"text": "Sheep moved", "wait": "false"},
                  headers={"Origin": "http://127.0.0.1:8788"}).status_code == 202  # NoteCad's own app
    assert c.post(url, data={"text": "Sheep moved", "wait": "false"}).status_code == 202  # scripts send no Origin
    assert c.get(f"/api/v1/workspaces/{ids['ws']}/mindmap", headers={"Origin": "https://evil.example"}).status_code == 200


def test_query_token_only_for_reads(farm):
    b, ids = farm
    c = _app(b, token="s3cret")
    # the test client's address is "testclient", not loopback: this is a phone on the LAN
    url = f"/api/v1/workspaces/{ids['ws']}/capture"
    assert c.post(url + "?token=s3cret", json={"text": "x"}).status_code == 401
    assert c.post(url, json={"text": "Sheep moved", "wait": False},
                  headers={"Authorization": "Bearer s3cret"}).status_code == 202
    assert c.get(f"/api/v1/workspaces/{ids['ws']}/mindmap?token=s3cret").status_code == 200


# ---------------------------------------------------------------- undo
def test_undo_keeps_a_created_node_that_later_notes_use(farm):
    b, ids = farm
    first = b.register_capture(ids["ws"], text="x")["capture_id"]
    b.applier.apply(ids["ws"], first, 0, [
        {"type": "create_node", "temp_id": "tmp:new", "parent_id": ids["sheep"], "title": "Ram 7", "kind": "animal",
         "confidence": 0.9, "evidence": "x"}], "user", {})
    ram = b.db.one("select id from nodes where title='Ram 7'")["id"]
    later = b.register_capture(ids["ws"], text="y")["capture_id"]
    b.applier.apply(ids["ws"], later, 0, [{"type": "append_note", "node_id": ram, "text": "Ram 7 is limping",
                                          "confidence": 0.9, "evidence": "y"}], "user", {})
    b.undo(first)
    assert b.graph.node(ram) is not None
    assert b.db.one("select count(*) as c from notes where node_id=?", (ram,))["c"] == 1


# ---------------------------------------------------------------- sync (ADR 0012 hardening)
def _pair():
    from test_sync import brain, link
    from farm import seed_farm
    desk, edge = brain("desktop"), brain("edge-node")
    ids = seed_farm(desk)
    return desk, edge, ids, link(desk, edge)


def _unsynced(b) -> int:
    return b.db.one("select count(*) as c from action_log where synced_at is null")["c"]


def test_nothing_is_left_unsynced_after_a_sync_both_ways():
    """Phase 6 gate. Notes made on the hub itself were never marked: only the pusher marked rows."""
    desk, edge, ids, eng = _pair()
    desk.process(desk.register_capture(ids["ws"], text="The main water pump is leaking")["capture_id"])
    assert eng.run_once()["ok"]
    edge.process(edge.register_capture(ids["ws"], text="Sipho fixed the fence by the south paddock")["capture_id"])
    assert _unsynced(edge) > 0
    res = eng.run_once()
    assert res["ok"] and res["pulled"] > 0
    assert _unsynced(desk) == 0 and _unsynced(edge) == 0


def test_a_note_committed_during_an_empty_push_is_not_skipped():
    desk, edge, ids, eng = _pair()
    assert eng.run_once()["ok"]
    real = desk.journal.to_push
    injected = []

    def racing(*a, **k):
        out = real(*a, **k)
        if not out and not injected:  # the worker thread commits a note right now
            injected.append(desk.graph.add_node(ids["ws"], ids["sheep"], "Ram 9", "animal"))
        return out
    desk.journal.to_push = racing
    eng.run_once()
    desk.journal.to_push = real
    eng.run_once()
    assert edge.graph.node(injected[0]) is not None


def test_one_bad_change_does_not_block_the_batch():
    from notecad_brain.common import now_iso
    desk, edge, ids, _ = _pair()
    good = {"tbl": "profile_facts", "pk": f"{ids['ws']}\x1fcrop", "op": "U", "ws": ids["ws"], "origin": "phone",
            "ts": "2026-10-28T08:00:00.000Z", "origin_seq": 1,
            "row": {"workspace_id": ids["ws"], "key": "crop", "value": '"beans"', "confidence": 1, "source": "t",
                    "updated_at": now_iso()}}
    bad = {**good, "tbl": "nodes", "pk": "orphan", "origin_seq": 2,
           "row": {"id": "orphan", "workspace_id": ids["ws"], "parent_id": "no-such-parent", "path": "x", "depth": 1,
                   "kind": "asset", "title": "Orphan", "status_since": now_iso(), "created_at": now_iso(),
                   "updated_at": now_iso()}}
    res = desk.journal.receive([bad, good], via="phone")
    assert res["applied"] == 1 and res["rejected"] == 1
    assert desk.db.one("select count(*) as c from sync_rejects")["c"] == 1


def test_a_wiped_hub_gets_everything_again():
    from test_sync import brain, link
    desk, edge, ids, eng = _pair()
    assert eng.run_once()["ok"]
    fresh = brain("edge-node")  # same name, new journal: data\edge-node was deleted
    eng2 = link(desk, fresh)
    assert eng2.run_once()["ok"]
    assert fresh.graph.node(ids["pump"]) is not None


def test_sync_backs_off_after_failures():
    desk, edge, ids, eng = _pair()
    eng.failures = 0
    assert eng.next_wait() == eng.interval
    eng.failures = 3
    assert eng.interval * 8 * 0.85 <= eng.next_wait() <= min(eng.interval * 8, 300)
    eng.failures = 20
    assert eng.next_wait() <= 300


def test_two_workers_linking_the_same_pair_keep_one_edge():
    desk, edge, ids, eng = _pair()
    assert eng.run_once()["ok"]
    a = desk.applier._link(ids["ws"], ids["pump"], ids["sipho_node"], "assigned_to", "user")
    b = edge.applier._link(ids["ws"], ids["pump"], ids["sipho_node"], "assigned_to", "user")
    assert eng.run_once()["ok"] and eng.run_once()["ok"]
    q = "select id from edges where src_id=? and dst_id=? and edge_type='assigned_to'"
    assert [r["id"] for r in desk.db.query(q, (ids["pump"], ids["sipho_node"]))] == [min(a, b)]
    assert [r["id"] for r in edge.db.query(q, (ids["pump"], ids["sipho_node"]))] == [min(a, b)]


def test_supabase_migration_matches_the_brain():
    """0004 was a hand copy of sync.py; 0005 is generated, and a table added to sync.TABLES must reach it."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import gen_sync_migration as g
    from notecad_brain.sync import TABLES
    assert g.OUT.read_text(encoding="utf-8") == g.render(), "run tools/gen_sync_migration.py"
    for t in TABLES:
        assert f"create trigger nc_sync_{t} " in g.render()
    assert "security definer" in g.render()


# ---------------------------------------------------------------- audio playback in the node's history
def test_history_plays_the_voice_note(tmp_path):
    from fastapi.testclient import TestClient
    from farm import make_brain, seed_farm
    from notecad_brain.api import create_app
    from notecad_brain.stt import Transcript

    class STT:
        name = "fake"

        def transcribe(self, audio, *, mime, lang_hint, keyterms):
            return Transcript(text="The main water pump is leaking", language="en", confidence=0.9, engine="fake")
    b = make_brain(f"sqlite:///{tmp_path / 'b.db'}", audio_dir=str(tmp_path / "audio"), stt=STT())
    ids = seed_farm(b)
    b.settings.worker = False
    c = TestClient(create_app(b))
    wav = b"RIFF" + bytes(2000)
    r = c.post(f"/api/v1/workspaces/{ids['ws']}/capture", files={"audio": ("n.wav", wav, "audio/wav")},
               data={"wait": "true"}).json()
    hist = c.get(f"/api/v1/nodes/{ids['pump']}/history").json()
    assert any(h["audio"] and h["capture_id"] == r["capture_id"] for h in hist)
    a = c.get(f"/api/v1/captures/{r['capture_id']}/audio")
    assert a.status_code == 200 and a.content == wav and a.headers["content-type"] == "audio/wav"
    typed = c.post(f"/api/v1/workspaces/{ids['ws']}/capture", json={"text": "Sheep moved"}).json()
    assert c.get(f"/api/v1/captures/{typed['capture_id']}/audio").status_code == 404
    b.db.execute("update captures set audio_path=? where id=?", (str(tmp_path / "b.db"), r["capture_id"]))
    assert c.get(f"/api/v1/captures/{r['capture_id']}/audio").status_code == 404  # outside audio_dir: never served


# ---------------------------------------------------------------- Stage 2: the rules fast path
def _field_ctx(event):
    cands = [_cand("f705", "Fields > South Block > Field South 705", "field", 0.99, ["south 705", "field 705"], "sb"),
             _cand("sb", "Fields > South Block", "group", 0.86, ["south block"], "fields")]
    for c in cands:
        c["attributes"] = {"area_ha": 20} if c["kind"] == "field" else {}
    return _ctx(event, cands)


def test_a_plain_field_report_skips_the_model():
    from notecad_brain.routers import RouterChain
    calls = []

    class Model:
        name = "local:test"

        def route(self, ctx):
            calls.append(ctx.event)
            raise RuntimeError("not expected")
    chain = RouterChain([Model(), RulesRouter()], fast_path=True)
    out, name, _ = chain.route(_field_ctx("Today I planted Field South 705."))
    assert name == "rules:sure" and calls == []
    assert any(a["type"] == "update_attributes" and a["set"].get("planted_ha") == 20 for a in out["actions"])


def test_the_fast_path_leaves_anything_else_to_the_model():
    from notecad_brain.routers import rules_are_sure
    for event in ("I will plant Field South 705 tomorrow", "Planted Field South 705, ask Sipho to check the drip lines",
                  "Planted Field South 705 but the pump is leaking", "We planted it yesterday",
                  "Remember to plant Field South 705"):
        assert rules_are_sure(_field_ctx(event)) is None, event


def test_the_fast_path_can_be_switched_off():
    from notecad_brain.routers import RouterChain

    class Model:
        name = "local:test"

        def route(self, ctx):
            return RulesRouter().route(ctx)
    _, name, _ = RouterChain([Model(), RulesRouter()], fast_path=False).route(_field_ctx("Today I planted Field South 705."))
    assert name == "local:test"


# ---------------------------------------------------------------- Stage 2: retrieval and the map without N+1 queries
def test_paths_in_memory_match_path_titles(farm):
    from notecad_brain.graph import Graph
    b, ids = farm
    rows = b.graph.nodes(ids["ws"])
    paths = Graph.paths(rows)
    assert all(paths[r["id"]] == b.graph.path_titles(r["id"]) for r in rows)
    assert paths[ids["pump"]] == "Infrastructure > Water > Main Water Pump"


def test_vectors_are_reused_until_a_node_changes(farm):
    b, ids = farm
    b.retriever.candidates(ids["ws"], "the pump is leaking")
    calls = []
    real = b.embedder.embed_doc
    b.embedder.embed_doc = lambda t: calls.append(t) or real(t)
    first = b.retriever._vecs[ids["ws"]][2]
    b.retriever.candidates(ids["ws"], "the sheep are out")
    assert calls == [] and b.retriever._vecs[ids["ws"]][2] is first  # nothing re-embedded, same matrix
    b.graph.rename(ids["pump"], "Main Borehole Pump")
    top = b.retriever.candidates(ids["ws"], "main borehole pump")
    assert len(calls) == 1 and top[0]["node_id"] == ids["pump"]  # only the renamed node


# ---------------------------------------------------------------- Stage 2: numbered migrations, indexes, pragmas
def test_numbered_migrations_run_once_and_match_supabase(tmp_path):
    from pathlib import Path
    from notecad_brain.db import MIGRATIONS, Database
    url = f"sqlite:///{tmp_path / 'm.db'}"
    db = Database(url)
    assert [r["version"] for r in db.query("select version from schema_migrations")] == [v for v, _, _ in MIGRATIONS]
    db.close()
    db = Database(url)  # a second start applies nothing again
    assert db.one("select count(*) as c from schema_migrations")["c"] == len(MIGRATIONS)
    plan = db.query("explain query plan select count(*) from tasks where node_id=? and state='open'", ("x",))
    assert "tasks_node" in str(plan)
    assert db.one("pragma synchronous")["synchronous"] == 1  # NORMAL under WAL
    db.close()
    sql_dir = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
    for version, _, statements in MIGRATIONS:
        f = next(sql_dir.glob(f"{version:04d}_*.sql"))
        text = f.read_text(encoding="utf-8")
        assert all(s in text for s in statements), f.name


def test_rollup_writes_only_what_changed(farm):
    b, ids = farm
    b.graph.rollup([ids["pump"]])
    writes = []
    real = b.db.update
    b.db.update = lambda t, k, f: writes.append((t, k)) or real(t, k, f)
    b.graph.rollup([ids["pump"]])
    assert writes == []


# ---------------------------------------------------------------- undo forgets what an Inbox answer taught
def test_undo_forgets_the_phrase_an_inbox_answer_taught(farm):
    """The desktop's end-to-end test placed 'Sort out the stuff' from the Inbox and undid the note; the learned
    alias stayed, so the next 'Sort out the stuff' was filed there without asking."""
    b, ids = farm
    cid = b.register_capture(ids["ws"], text="Sort out the stuff by the shed", enqueue=False)["capture_id"]
    b.process(cid)
    item = b.db.one("select id from inbox where capture_id=? and state='open'", (cid,))
    assert item, "a vague note goes to the Inbox"
    b.resolve_inbox(item["id"], ids["pump"])
    learned = {a for a in b.graph.aliases(ids["pump"])} - {"main pump", "die groot pomp", "hoofpomp", "borehole pump"}
    assert learned and b.db.one("select count(*) as c from route_corrections")["c"] == 1
    b.undo(cid)
    assert set(b.graph.aliases(ids["pump"])) & learned == set()
    assert b.db.one("select count(*) as c from route_corrections")["c"] == 0
    again = b.register_capture(ids["ws"], text="Sort out the stuff by the shed", enqueue=False)["capture_id"]
    assert b.process(again)["state"] == "needs_review"


def test_undo_keeps_an_alias_the_owner_already_had(farm):
    b, ids = farm
    b.graph.add_alias(ids["pump"], "the stuff", weight=1.0)
    cid = b.register_capture(ids["ws"], text="Sort out the stuff by the shed", enqueue=False)["capture_id"]
    b.process(cid)
    item = b.db.one("select id from inbox where capture_id=? and state='open'", (cid,))
    if item:
        b.resolve_inbox(item["id"], ids["pump"])
    b.undo(cid)
    assert "the stuff" in b.graph.aliases(ids["pump"])


# ---------------------------------------------------------------- Stage 5 review: sync rejects and acks
def test_a_row_set_aside_applies_when_its_parent_arrives():
    from notecad_brain.common import now_iso
    desk, edge, ids, _ = _pair()
    row = lambda nid, parent, depth: {"id": nid, "workspace_id": ids["ws"], "parent_id": parent, "path": nid, "depth": depth,  # noqa: E731
                                     "kind": "group", "title": nid, "status_since": now_iso(), "created_at": now_iso(),
                                     "updated_at": now_iso()}
    ch = lambda nid, parent, depth, seq: {"tbl": "nodes", "pk": nid, "op": "U", "ws": ids["ws"], "origin": "phone",  # noqa: E731
                                          "ts": f"2026-10-28T08:00:0{seq}.000Z", "origin_seq": seq, "row": row(nid, parent, depth)}
    assert desk.journal.receive([ch("child", "parent", 2, 2)], via="phone")["rejected"] == 1   # the child came first
    desk.journal.receive([ch("child", "parent", 2, 2)], via="phone")  # sent again: still one row aside
    assert desk.db.one("select count(*) as c from sync_rejects")["c"] == 1
    desk.journal.receive([ch("parent", ids["root"], 1, 1)], via="phone")
    assert desk.graph.node("child") is not None
    assert desk.db.one("select count(*) as c from sync_rejects")["c"] == 0


def test_the_pusher_leaves_rows_the_hub_set_aside_unsynced():
    desk, edge, ids, eng = _pair()
    assert eng.run_once()["ok"]
    desk.process(desk.register_capture(ids["ws"], text="The main water pump is leaking")["capture_id"])
    real = eng.peer.push

    def refusing(worker, changes):
        out = real(worker, changes)
        return {**out, "rejected_keys": [{"tbl": c.tbl, "pk": c.pk} for c in changes if c.tbl == "action_log"]}
    eng.peer.push = refusing
    assert eng.run_once()["ok"]
    assert _unsynced(desk) > 0


def test_ack_looks_only_at_what_is_new():
    desk, edge, ids, eng = _pair()
    assert eng.run_once()["ok"]
    cur = edge.journal.last_seq()
    assert edge.journal.ack("desktop", cur) == 0  # already acknowledged by the run
    edge.process(edge.register_capture(ids["ws"], text="Sheep moved to the south paddock")["capture_id"])
    assert eng.run_once()["ok"] and _unsynced(edge) == 0
    assert edge.journal.state("ack:desktop") == str(desk.journal.state(f"pull:{edge.journal.worker_id}"))


def test_a_rebound_name_on_this_pc_reads_nothing_without_the_token(tmp_path):
    """DNS rebinding: evil.example pointed at 127.0.0.1 makes same-origin GETs (no Origin header) from this PC."""
    from fastapi.testclient import TestClient
    from farm import make_brain, seed_farm
    from notecad_brain.api import create_app
    b = make_brain(f"sqlite:///{tmp_path / 'b.db'}")
    ids = seed_farm(b)
    b.settings.worker = False
    url = f"/api/v1/workspaces/{ids['ws']}/export"
    rebound = TestClient(create_app(b), client=("127.0.0.1", 50002), base_url="http://evil.example:8788")
    assert rebound.get(url).status_code == 403
    assert rebound.get("/api/v1/pairing").status_code == 403
    mine = TestClient(create_app(b), client=("127.0.0.1", 50003), base_url="http://localhost:8788")
    assert mine.get(url).status_code == 200


def test_a_resume_never_fills_a_gap_with_silence(tmp_path):
    import base64
    from fastapi.testclient import TestClient
    from farm import make_brain, seed_farm
    from notecad_brain.api import create_app
    b = make_brain(f"sqlite:///{tmp_path / 'b.db'}", audio_dir=str(tmp_path / "audio"))
    ids = seed_farm(b)
    b.settings.worker = False
    c = TestClient(create_app(b))
    v = {"Tus-Resumable": "1.0.0"}
    meta = "filetype " + base64.b64encode(b"audio/ogg").decode()
    url = c.post(f"/api/v1/workspaces/{ids['ws']}/uploads", headers={**v, "Upload-Length": "100", "Upload-Metadata": meta}).headers["location"].split("testserver")[1]
    oct_ = {**v, "Content-Type": "application/offset+octet-stream"}
    assert c.patch(url, headers={**oct_, "Upload-Offset": "0"}, content=b"x" * 40).status_code == 204
    part = next((tmp_path / "uploads").glob("*.part"))
    part.write_bytes(b"x" * 25)  # the last 15 bytes never reached the disk
    r = c.patch(url, headers={**oct_, "Upload-Offset": "40"}, content=b"y" * 60)
    assert r.status_code == 409 and r.headers["upload-offset"] == "25"
    assert c.patch(url, headers={**oct_, "Upload-Offset": "25"}, content=b"y" * 75).status_code == 204
    from pathlib import Path
    audio = Path(b.db.one("select audio_path from captures")["audio_path"]).read_bytes()
    assert audio == b"x" * 25 + b"y" * 75  # no zeros where the lost bytes were


def test_a_parent_cycle_does_not_hang_paths(farm):
    from notecad_brain.graph import Graph
    b, ids = farm
    b.db.execute("update nodes set parent_id=? where id=?", (ids["sheep"], ids["livestock"]))  # two moves met in sync
    assert isinstance(b.graph.path_titles(ids["sheep"]), str)
    assert ids["sheep"] in Graph.paths(b.graph.nodes(ids["ws"]))
