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
