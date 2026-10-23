# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Phase 5: multi-worker sync. Two brains over HTTP (desktop and Edge AI Node), a Postgres hub (Supabase) between
workers, last-writer-wins, deletes, relays, action_log.synced_at, and no echo."""
import os
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import conftest
from farm import make_brain, seed_farm
from notecad_brain.api import create_app
from notecad_brain.sync import SEP, SyncEngine

LEAK = "The main water pump is leaking badly. Ask Sipho to fix it tomorrow."


def bridge(client: TestClient) -> httpx.MockTransport:
    """An httpx transport served by a FastAPI app in this process (the hub brain)."""
    def handler(req: httpx.Request) -> httpx.Response:
        r = client.request(req.method, req.url.raw_path.decode(), content=req.content,
                           headers={k: v for k, v in req.headers.items() if k.lower() in ("content-type", "authorization")})
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": r.headers.get("content-type", "")})
    return httpx.MockTransport(handler)


def brain(name: str, url: str = "sqlite:///:memory:"):
    b = make_brain(url)
    b.journal.set_state("worker_id", name)
    b.journal.worker_id = name
    return b


def link(worker, hub_brain, **kw) -> SyncEngine:
    tc = TestClient(create_app(hub_brain))
    worker.sync = SyncEngine(worker, "http://hub", transport=bridge(tc), **kw)
    return worker.sync


def snapshot(b, ws: str) -> dict:
    """What the owner sees: the map's nodes with their status and counts, tasks, notes."""
    mm = b.mindmap(ws)
    nodes = {n["id"]: (n["title"], n.get("display_status"), n["counts"].get("open_tasks"), n["counts"].get("open_alerts"))
             for n in mm["nodes"] if n["type"] in ("root", "category", "entity")}
    tasks = sorted((t["id"], t["title"], t["state"], t["assignee_member"]) for t in b.db.query(
        "select * from tasks where workspace_id=?", (ws,)))
    notes = sorted(n["id"] for n in b.db.query("select id from notes where workspace_id=?", (ws,)))
    return {"nodes": nodes, "tasks": tasks, "notes": notes}


def journal_size(b) -> int:
    return b.journal.last_seq()


def test_desktop_and_edge_node_converge_without_echo():
    desk, edge = brain("desktop"), brain("edge-node")
    ids = seed_farm(desk)
    r = desk.register_capture(ids["ws"], text=LEAK, enqueue=False)
    desk.process(r["capture_id"])
    assert desk.db.one("select count(*) as c from action_log where synced_at is null")["c"] > 0
    eng = link(desk, edge)

    first = eng.run_once()
    assert first["ok"] and first["pushed"] > 50 and first["pulled"] == 0
    assert snapshot(edge, ids["ws"]) == snapshot(desk, ids["ws"])
    pump = edge.graph.node(ids["pump"])
    assert pump["status"] == "critical" and pump["open_alerts"] == 1  # roll-up recomputed on the edge node
    assert desk.db.one("select count(*) as c from action_log where synced_at is null")["c"] == 0
    assert edge.db.one("select count(*) as c from action_log where synced_at is null")["c"] == 0

    # nothing new: nothing moves, in either direction, and neither journal grows
    sizes = (journal_size(desk), journal_size(edge))
    again = eng.run_once()
    assert again["pushed"] == 0 and again["pulled"] == 0
    assert (journal_size(desk), journal_size(edge)) == sizes
    assert desk.sync.status()["pending_changes"] == 0


def test_changes_on_the_edge_node_come_back_and_the_map_updates():
    desk, edge = brain("desktop"), brain("edge-node")
    ids = seed_farm(desk)
    desk.process(desk.register_capture(ids["ws"], text=LEAK, enqueue=False)["capture_id"])
    eng = link(desk, edge)
    eng.run_once()
    # a worker on the farm ticks the task off and resolves the alert on the edge node
    for t in edge.tasks(ids["ws"]):
        edge.update_task(t["id"], state="done")
    for a in edge.db.query("select id from alerts where resolved_at is null"):
        edge.resolve_alert(a["id"])
    seen = []
    desk.broker.publish = lambda ws, kind, data: seen.append(kind) or {}
    res = eng.run_once()
    assert res["pulled"] > 0 and "sync.applied" in seen
    assert desk.tasks(ids["ws"]) == [] and desk.graph.node(ids["pump"])["status"] == "ok"
    assert snapshot(desk, ids["ws"]) == snapshot(edge, ids["ws"])
    assert eng.run_once()["pulled"] == 0


def test_last_writer_wins_on_the_same_task():
    desk, edge = brain("desktop"), brain("edge-node")
    ids = seed_farm(desk)
    desk.process(desk.register_capture(ids["ws"], text=LEAK, enqueue=False)["capture_id"])
    eng = link(desk, edge)
    eng.run_once()
    tid = desk.tasks(ids["ws"])[0]["id"]
    desk.db.update("tasks", {"id": tid}, {"title": "desk title"})
    time.sleep(0.01)
    edge.db.update("tasks", {"id": tid}, {"title": "edge title (later)"})
    eng.run_once()
    eng.run_once()
    t1 = desk.db.one("select title from tasks where id=?", (tid,))["title"]
    t2 = edge.db.one("select title from tasks where id=?", (tid,))["title"]
    assert t1 == t2 == "edge title (later)"


def test_deletes_and_undo_travel():
    desk, edge = brain("desktop"), brain("edge-node")
    ids = seed_farm(desk)
    cid = desk.process(desk.register_capture(ids["ws"], text=LEAK, enqueue=False)["capture_id"])["capture_id"]
    eng = link(desk, edge)
    eng.run_once()
    desk.undo(cid)
    eng.run_once()
    assert edge.db.one("select count(*) as c from notes where capture_id=?", (cid,))["c"] == 0
    assert edge.graph.node(ids["pump"])["open_alerts"] == 0
    desk.delete_workspace(ids["ws"])
    eng.run_once()
    assert edge.graph.workspace(ids["ws"]) is None
    assert edge.db.one("select count(*) as c from nodes where workspace_id=?", (ids["ws"],))["c"] == 0


def test_data_from_before_sync_is_baselined_once():
    desk = brain("desktop")
    ids = seed_farm(desk)
    desk.db.execute("delete from sync_changes")  # as if this farm was made before Phase 5
    desk.journal.set_state("baseline_at", None)
    n = desk.journal.baseline()
    assert n > 20 and desk.journal.baseline() == 0
    edge = brain("edge-node")
    link(desk, edge).run_once()
    assert len(edge.graph.nodes(ids["ws"])) == len(desk.graph.nodes(ids["ws"]))


def test_workspace_filter_keeps_other_farms_home():
    desk, edge = brain("desktop"), brain("edge-node")
    ids = seed_farm(desk)
    private = desk.graph.create_workspace("Private notes", owner_name="Dennis")
    link(desk, edge, workspaces=[ids["ws"]]).run_once()
    assert edge.graph.workspace(ids["ws"]) is not None and edge.graph.workspace(private["id"]) is None


def test_a_third_worker_gets_changes_through_the_hub():
    desk, edge, laptop = brain("desktop"), brain("edge-node"), brain("laptop")
    ids = seed_farm(desk)
    link(desk, edge).run_once()
    tc = TestClient(create_app(edge))
    lap = SyncEngine(laptop, "http://hub", transport=bridge(tc))
    laptop.sync = lap
    assert lap.run_once()["pulled"] > 20
    assert laptop.graph.node(ids["pump"])["title"] == "Main Water Pump"
    laptop.process(laptop.register_capture(ids["ws"], text=LEAK, enqueue=False)["capture_id"])
    lap.run_once()
    desk.sync.run_once()
    assert snapshot(desk, ids["ws"]) == snapshot(laptop, ids["ws"]) == snapshot(edge, ids["ws"])


def test_api_status_push_pull_and_now(tmp_path):
    hub = brain("edge-node", f"sqlite:///{tmp_path/'edge.db'}")
    c = TestClient(create_app(hub))
    s = c.get("/api/v1/sync/status").json()
    assert s["ok"] and s["worker_id"] == "edge-node" and s["target"] is None
    assert c.post("/api/v1/sync/now").json()["ok"] is False  # no target on this one
    ws = hub.graph.create_workspace("Hub farm")["id"]
    pulled = c.get("/api/v1/sync/pull", params={"worker": "desktop", "since": 0}).json()
    assert pulled["hub"] == "edge-node" and any(ch["tbl"] == "workspaces" and ch["pk"] == ws for ch in pulled["changes"])
    assert c.get("/api/v1/sync/pull", params={"worker": "edge-node", "since": 0}).json()["changes"] == []  # own changes
    assert "sync" in c.get(f"/api/v1/workspaces/{ws}/sync").json()


# ==================================================================== Postgres / Supabase hub
PG = os.environ.get("NC_BRAIN_TEST_PG_URL")


@pytest.fixture
def pg_hub():
    if not PG:
        pytest.skip("NC_BRAIN_TEST_PG_URL not set")
    url, schema = conftest._pg_url_with_schema()
    yield url
    import psycopg
    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f"drop schema {schema} cascade")


def test_postgres_hub_between_two_workers(pg_hub):
    desk, laptop = brain("desktop"), brain("laptop")
    ids = seed_farm(desk)
    desk.process(desk.register_capture(ids["ws"], text=LEAK, enqueue=False)["capture_id"])
    d = SyncEngine(desk, pg_hub)
    l = SyncEngine(laptop, pg_hub)
    desk.sync, laptop.sync = d, l
    assert d.run_once()["ok"]
    hub = d.peer.journal.db
    assert hub.one("select count(*) as c from nodes where workspace_id=?", (ids["ws"],))["c"] == len(desk.graph.nodes(ids["ws"]))
    assert hub.one("select status from nodes where id=?", (ids["pump"],))["status"] == "critical"
    assert l.run_once()["pulled"] > 50
    assert snapshot(laptop, ids["ws"]) == snapshot(desk, ids["ws"])
    # an app writing straight into Supabase (through row-level security) is a worker too: origin 'cloud'
    tid = desk.tasks(ids["ws"])[0]["id"]
    hub.execute("update tasks set state='done' where id=?", (tid,))
    assert hub.one("select origin from sync_changes where tbl='tasks' and pk=? order by seq desc limit 1", (tid,))["origin"] in ("supabase", "cloud")
    d.run_once()
    assert desk.db.one("select state from tasks where id=?", (tid,))["state"] == "done"
    assert d.run_once()["pushed"] == 0 and l.run_once()["pushed"] == 0 and d.run_once()["pulled"] == 0


def test_brain_on_postgres_journals_like_sqlite(farm):
    b, ids = farm
    b.process(b.register_capture(ids["ws"], text=LEAK, enqueue=False)["capture_id"])
    rows = b.db.query("select tbl, pk, op, ws, origin from sync_changes where tbl in ('node_aliases', 'capture_events') limit 4")
    assert rows and all(r["ws"] == ids["ws"] and r["origin"] == b.journal.worker_id for r in rows)
    assert any(SEP in r["pk"] for r in rows)
    before = b.journal.last_seq()
    b.db.update("nodes", {"id": ids["pump"]}, {"title": "Main Water Pump"})  # no real change: not journalled
    assert b.journal.last_seq() == before
    b.journal.mark_synced([r["id"] for r in b.db.query("select id from action_log")])  # bookkeeping: not journalled
    assert b.journal.last_seq() == before
