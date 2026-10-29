# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Phase 4: archive and remove a workspace, health for the start-up script, and the showcase notes."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from farm import make_brain, seed_farm
from notecad_brain.api import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
LEAK = "The tractor hydraulic hose is leaking. Ask Sipho to replace it tomorrow."


def test_export_then_delete_workspace_leaves_others(farm, tmp_path):
    b, ids = farm
    b.settings.audio_dir = str(tmp_path / "audio")
    other = b.graph.create_workspace("Other Farm", owner_name="Dennis")
    r = b.register_capture(ids["ws"], text=LEAK, enqueue=False)
    b.process(r["capture_id"])
    a = b.register_capture(ids["ws"], audio=b"OggS", mime="audio/ogg")  # queued job + audio file
    assert (tmp_path / "audio" / ids["ws"]).is_dir()
    arch = b.export_workspace(ids["ws"])
    assert arch["workspace"]["id"] == ids["ws"] and len(arch["tables"]["nodes"]) > 15
    assert arch["tables"]["tasks"] and arch["tables"]["action_log"] and arch["tables"]["capture_events"]
    json.dumps(arch)  # the archive is plain JSON
    res = b.delete_workspace(ids["ws"])
    assert res["counts"]["nodes"] == len(arch["tables"]["nodes"]) and res["counts"]["tasks"] >= 1
    assert b.graph.workspace(ids["ws"]) is None
    for t in ("nodes", "notes", "tasks", "alerts", "captures", "action_log", "members", "inbox"):
        assert b.db.one(f"select count(*) as c from {t} where workspace_id=?", (ids["ws"],))["c"] == 0, t
    assert b.db.one("select count(*) as c from jobs where payload like ?", (f"%{a['capture_id']}%",))["c"] == 0
    assert not (tmp_path / "audio" / ids["ws"]).exists()
    assert b.graph.workspace(other["id"]) is not None and len(b.graph.nodes(other["id"])) == 1


def test_delete_workspace_api_needs_confirmation(tmp_path):
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}")
    ids = seed_farm(b)
    c = TestClient(create_app(b))
    assert c.get(f"/api/v1/workspaces/{ids['ws']}/export").json()["format"] == "notecad-workspace-archive/1"
    assert c.delete(f"/api/v1/workspaces/{ids['ws']}").status_code == 400
    assert c.delete(f"/api/v1/workspaces/{ids['ws']}?confirm={ids['ws']}").json()["deleted"] == ids["ws"]
    assert c.get(f"/api/v1/workspaces/{ids['ws']}").status_code == 404
    assert c.delete("/api/v1/workspaces/nope?confirm=nope").status_code == 404


def test_health_reports_speech_model_state(tmp_path):
    import threading
    gate = threading.Event()

    class FakeSTT:
        name = "faster-whisper"
        active_device = "cuda"

        def warm(self):
            gate.wait(5)
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}", stt=FakeSTT())
    b.settings.worker = True
    with TestClient(create_app(b)) as c:
        h = c.get("/api/health").json()
        assert h["stt"] == "faster-whisper" and h["stt_ready"] is False and h["stt_device"] == "cuda"
        gate.set()
        import time
        for _ in range(50):
            if c.get("/api/health").json()["stt_ready"] is True:
                break
            time.sleep(0.05)
        assert c.get("/api/health").json()["stt_ready"] is True
    assert TestClient(create_app(make_brain())).get("/health").json()["stt_ready"] is None


@pytest.fixture(params=["sqlite"] + (["postgres"] if __import__("os").environ.get("NC_BRAIN_TEST_PG_URL") else []))
def showcase(request):
    import conftest
    from seed_farm_showcase import LocalBrain, build
    if request.param == "postgres":
        url, schema = conftest._pg_url_with_schema()
        b = make_brain(url)
    else:
        b = make_brain()
    api = LocalBrain(b)
    build(api)
    yield b, api
    if request.param == "postgres":
        b.db.close()
        import psycopg
        with psycopg.connect(conftest.PG, autocommit=True) as c:
            c.execute(f"drop schema {schema} cascade")


def test_showcase_notes_with_rules_only(showcase):
    """The three showcase notes land right with no model at all (Gemma and Claude only add to this)."""
    from seed_farm_showcase import NOTES, run_note
    b, api = showcase
    for i in range(1, 4):
        ok, detail, _ = run_note(api, "showcase", i, out=lambda *_: None)
        assert ok, f"note {i} ({NOTES[i - 1]}): {detail}"
    mm = api.mindmap("showcase")
    jd2 = next(n for n in mm["nodes"] if n["title"] == "John Deere 9550 #2")
    assert jd2["counts"]["open_tasks"] == 0 and jd2["display_status"] == "ok"


def test_showcase_reset_archives_and_rebuilds(tmp_path, monkeypatch):
    import seed_farm_showcase as sc
    monkeypatch.setattr(sc, "ROOT", tmp_path)
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}")
    api = sc.LocalBrain(b)
    sc.build(api)
    sc.run_note(api, "showcase", 2, out=lambda *_: None)
    p = sc.archive(api, "showcase")
    api.delete("showcase")
    assert p.exists() and json.loads(p.read_text(encoding="utf-8"))["workspace"]["id"] == "showcase"
    n = sc.build(api)
    mm = api.mindmap("showcase")
    assert n > 25 and all(next(x for x in mm["nodes"] if x["title"] == f)["progress_pct"] == 0 for f in sc.FIELDS)
    rows = [{"id": "demo-farm-3", "name": "Demo Farm"}, {"id": "abc", "name": "Phase 2 Demo Farm"},
            {"id": "showcase", "name": "Wabakipi Farm"}, {"id": "real", "name": "My Farm"}]
    assert [w["id"] for w in sc.stale_of(rows, "showcase")] == ["demo-farm-3", "abc"]


def test_a_problem_the_owner_says_needs_doing_becomes_a_task(showcase):
    """Live on WABAKIPI Gemma filed the wheel note as a warning with an alert but no task."""
    from notecad_companion.llm import ScriptedLLM
    from notecad_brain.routers import LocalRouter, RouterChain
    from seed_farm_showcase import run_note
    b, api = showcase
    jd1 = next(n for n in api.mindmap("showcase")["nodes"] if n["title"] == "John Deere 9550 #1")["id"]

    def fn(msgs, schema):
        return json.dumps({"node_id": jd1, "kind": "problem", "severity": "warning", "note": "Wheel needs changing.",
                           "task_title": "Change wheel", "assignee": "", "place_node_id": "none",
                           "new_item_title": "", "confidence": 0.9})
    b.routers = RouterChain([LocalRouter(ScriptedLLM(fn))])
    ok, detail, _ = run_note(api, "showcase", 1, out=lambda *_: None)
    assert ok and "Change wheel" in detail
    assert b.db.one("select count(*) as c from alerts where node_id=?", (jd1,))["c"] == 1  # the warning stays
