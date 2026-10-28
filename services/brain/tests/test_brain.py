# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Golden tests: the blueprint's sheep/tractor and beans/pump notes, delegation, Inbox, Undo, idempotency."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from farm import make_brain, seed_farm
from notecad_brain import text
from notecad_brain.routers import RouterChain
from notecad_brain.validate import check

MON_0800 = "2026-10-19T06:00:00+00:00"  # Monday 08:00 in Johannesburg


def actions_of(b, cid, kind=None):
    rows = [json.loads(r["action"]) for r in b.db.query("select action from action_log where capture_id=? and undone_at is null "
                                                         "order by event_idx, seq", (cid,))]
    return [r for r in rows if kind is None or r.get("type") == kind]


# ------------------------------------------------------------------ text
def test_normalise_numbers_and_units():
    assert text.normalise("Just finished planting the last two hundred hectares of beans") == \
        "Just finished planting the last 200 ha of beans"
    assert text.normalise("One of the ewes, uh, broke her leg") == "One of the ewes, broke her leg"


def test_split_events_blueprint_examples():
    assert text.split_events("One of the ewes in the south paddock broke her back left leg, and the John Deere "
                             "tractor's hydraulic hose just burst near the bean fields.") == [
        "One of the ewes in the south paddock broke her back left leg",
        "the John Deere tractor's hydraulic hose just burst near the bean fields."]
    assert len(text.split_events("Just finished planting the last 200 ha of beans, but the main water pump is leaking badly.")) == 2
    assert len(text.split_events("Die hoofpomp lek weer en die skape moet gedip word")) == 2
    assert text.split_events("Check the fence and gate") == ["Check the fence and gate"]


def test_due_words():
    ref = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)  # Monday 08:00 SAST
    local = lambda s: datetime.fromisoformat(text.parse_due(s, ref)).astimezone(ZoneInfo("Africa/Johannesburg"))
    assert local("fix it tomorrow").strftime("%a %H") == "Tue 17"
    assert local("doen dit môre oggend").strftime("%a %H") == "Tue 09"
    assert local("before Friday").strftime("%a") == "Fri"
    assert local("Vrydag").strftime("%a") == "Fri"
    assert local("in 3 days").strftime("%a") == "Thu"
    assert text.parse_due("the pump is leaking", ref) is None


# ------------------------------------------------------------------ retrieval
def test_candidates_find_owner_words(farm):
    b, ids = farm
    top = b.retriever.candidates(ids["ws"], "the main water pump is leaking badly")
    assert top[0]["node_id"] == ids["pump"]
    top = b.retriever.candidates(ids["ws"], "die groot pomp lek baie erg")
    assert top[0]["node_id"] == ids["pump"]
    top = b.retriever.candidates(ids["ws"], "One of the ewes broke her leg")
    assert top[0]["node_id"] == ids["sheep"]
    assert any(c["node_id"] == ids["sheep_health"] for c in top)  # the channel is offered with its parent


# ------------------------------------------------------------------ golden notes, rules router (no model)
def test_sheep_and_tractor_note(farm):
    b, ids = farm
    r = b.register_capture(ids["ws"], text="One of the ewes in the south paddock broke her back left leg, and the John "
                                           "Deere tractor's hydraulic hose just burst near the bean fields.",
                           recorded_at=MON_0800, enqueue=False)
    out = b.process(r["capture_id"])
    assert out["state"] == "applied" and len(out["events"]) == 2
    health, maint = b.graph.node(ids["sheep_health"]), b.graph.node(ids["tractor_maint"])
    assert health["status"] == "critical" and maint["status"] == "critical"
    # channel mirroring: Sheep and Tractors turn red; ancestors get the echo dot
    assert b.graph.node(ids["sheep"])["display_status"] == "critical"
    assert b.graph.node(ids["tractors"])["display_status"] == "critical"
    assert b.graph.node(ids["livestock"])["child_worst"] == "critical"
    assert b.graph.node(ids["ops"])["child_worst"] == "critical"
    tasks = b.tasks(ids["ws"])
    assert len(tasks) == 2 and all(t["priority"] == "urgent" for t in tasks)
    assert {a["category"] for a in b.db.query("select category from alerts")} == {"health", "breakdown"}
    assert b.graph.node(ids["sheep_health"])["open_alerts"] == 1
    # owner and Sipho (editor) both get the critical alerts
    assert len(b.db.query("select * from notifications where kind='critical_alert'")) == 4


def test_beans_and_pump_note(farm):
    b, ids = farm
    r = b.register_capture(ids["ws"], text="Just finished planting the last two hundred hectares of beans, but the "
                                           "main water pump is leaking badly.", recorded_at=MON_0800, enqueue=False)
    out = b.process(r["capture_id"])
    assert out["text"].startswith("Just finished planting the last 200 ha of beans")
    assert b.graph.node(ids["beans"])["status"] == "done"
    pump = b.graph.node(ids["pump"])
    assert pump["status"] == "critical" and pump["open_tasks"] == 1 and pump["open_alerts"] == 1
    assert b.graph.node(ids["water"])["child_worst"] == "critical"
    assert b.graph.node(ids["infra"])["child_worst"] == "critical"
    notes = b.db.query("select node_id, body from notes")
    assert {n["node_id"] for n in notes} == {ids["beans"], ids["pump"]}


# ------------------------------------------------------------------ the blueprint's model output (scripted Claude)
class Scripted:
    name = "scripted-claude"

    def __init__(self, fn):
        self.fn = fn

    def route(self, ctx):
        return self.fn(ctx)


def test_model_output_is_applied_with_attribute_guard(farm):
    b0, ids = farm
    beans = ids["beans"]

    def fn(ctx):
        return {"capture_id": ctx.capture_id, "event_index": ctx.event_index, "summary": "Bean planting completed",
                "actions": [{"type": "update_attributes", "node_id": beans, "increment": {"planted_ha": 200},
                             "set": {"phase": "planted"}, "confidence": 0.92, "evidence": "last 200 ha of beans"},
                            {"type": "append_note", "node_id": ids["planting_log"], "text": "Planted the final 200 ha.",
                             "tags": ["planting"], "confidence": 0.93, "evidence": "finished planting"},
                            {"type": "set_status", "node_id": beans, "status": "done", "reason": "3,000 / 3,000 ha",
                             "confidence": 0.88, "evidence": "finished planting"}]}
    b0.routers = RouterChain([Scripted(fn)])
    r = b0.register_capture(ids["ws"], text="Just finished planting the last 200 ha of beans", enqueue=False)
    assert b0.process(r["capture_id"])["state"] == "applied"
    n = b0.graph.node(beans)
    assert n["attributes"]["planted_ha"] == 3000 and n["attributes"]["phase"] == "planted"
    # the same note again would push planted_ha past area_ha: guard sends it to the Inbox instead
    r2 = b0.register_capture(ids["ws"], text="Just finished planting the last 200 ha of beans", enqueue=False)
    assert b0.process(r2["capture_id"])["state"] == "needs_review"
    item = b0.db.one("select * from inbox where capture_id=?", (r2["capture_id"],))
    assert "above area_ha" in json.loads(item["proposal"])["reason"]
    assert b0.graph.node(beans)["attributes"]["planted_ha"] == 3000


def test_new_node_temp_ids_and_links(farm):
    b, ids = farm

    def fn(ctx):
        return {"capture_id": ctx.capture_id, "event_index": 0, "summary": "New ewe tagged",
                "actions": [{"type": "create_node", "temp_id": "tmp:1", "parent_id": ids["sheep"], "title": "Ewe 0412",
                             "kind": "animal", "aliases": ["tag 412"], "confidence": 0.9, "evidence": "tag 412"},
                            {"type": "append_note", "node_id": "tmp:1", "text": "New ewe tagged 412.", "confidence": 0.9,
                             "evidence": "tag 412"},
                            {"type": "link_nodes", "src_id": "tmp:1", "dst_id": ids["south_paddock"],
                             "edge_type": "located_at", "confidence": 0.8, "evidence": "south paddock"}]}
    b.routers = RouterChain([Scripted(fn)])
    r = b.register_capture(ids["ws"], text="Tagged a new ewe, tag 412, in the south paddock", enqueue=False)
    b.process(r["capture_id"])
    ewe = b.db.one("select * from nodes where title='Ewe 0412'")
    assert ewe["parent_id"] == ids["sheep"] and b.graph.aliases(ewe["id"]) == ["tag 412"]
    assert b.db.one("select * from edges where src_id=? and dst_id=?", (ewe["id"], ids["south_paddock"]))
    assert b.graph.path_titles(ewe["id"]) == "Operations > Livestock > Sheep > Ewe 0412"


def test_validation_rejects_unknown_ids_and_top_level(farm):
    b, ids = farm
    root = ids["root"]
    bad = {"capture_id": "c", "event_index": 0, "summary": "x",
           "actions": [{"type": "append_note", "node_id": "invented", "text": "x", "confidence": 0.9, "evidence": "x"}]}
    assert check(bad, allowed_ids={ids["pump"]}, root_id=root, node_attrs={}).gate == "nothing usable"
    top = {"capture_id": "c", "event_index": 0, "summary": "x",
           "actions": [{"type": "create_node", "temp_id": "tmp:1", "parent_id": root, "title": "Bees", "kind": "category",
                        "confidence": 0.9, "evidence": "x"}]}
    assert check(top, allowed_ids={root}, root_id=root, node_attrs={}).gate == "new top-level category"
    schema_bad = {"capture_id": "c", "event_index": 0, "summary": "x",
                  "actions": [{"type": "set_status", "node_id": ids["pump"], "status": "on fire", "reason": "x",
                               "confidence": 0.9, "evidence": "x"}]}
    assert check(schema_bad, allowed_ids={ids["pump"]}, root_id=root, node_attrs={}).gate == "schema"


# ------------------------------------------------------------------ delegation
def test_task_delegated_to_named_person(farm):
    b, ids = farm
    r = b.register_capture(ids["ws"], text="Ask Sipho to fix the north fence tomorrow", recorded_at=MON_0800, enqueue=False)
    b.process(r["capture_id"])
    t = b.tasks(ids["ws"])[0]
    assert t["assignee_member"] == ids["sipho"] and t["assignee_name"] == "Sipho Dlamini"
    due = datetime.fromisoformat(t["due_at"]).astimezone(ZoneInfo("Africa/Johannesburg"))
    assert due.strftime("%a %H:%M") == "Tue 17:00"
    note = b.db.one("select * from notifications where kind='task_assigned'")
    assert note["member_id"] == ids["sipho"]
    assert b.db.one("select * from edges where edge_type='assigned_to' and dst_id=?", (ids["sipho_node"],))
    assert b.tasks(ids["ws"], assignee=ids["sipho"])[0]["id"] == t["id"]


def test_unknown_person_keeps_hint_and_owner_is_told(farm):
    b, ids = farm
    r = b.register_capture(ids["ws"], text="Ask Thabo to service the tractor on Friday", recorded_at=MON_0800, enqueue=False)
    b.process(r["capture_id"])
    t = b.tasks(ids["ws"])[0]
    assert t["assignee_member"] is None and t["assignee_hint"] == "Thabo"
    owner = b.db.one("select id from members where role='owner'")["id"]
    assert b.db.one("select * from notifications where kind='task_created'")["member_id"] == owner
    # owner delegates by hand
    b.update_task(t["id"], assignee_member=ids["sipho"])
    assert b.tasks(ids["ws"], assignee=ids["sipho"])


def test_afrikaans_delegation():
    from notecad_brain.routers import assignee_from_text
    assert assignee_from_text("Vra Sipho om die hek reg te maak") == "Sipho"
    assert assignee_from_text("Sipho moet die pomp nagaan") == "Sipho"
    assert assignee_from_text("The pump must be checked") is None


# ------------------------------------------------------------------ Inbox, Undo, idempotency
def test_vague_note_goes_to_inbox_then_learns_alias(farm):
    b, ids = farm
    r = b.register_capture(ids["ws"], text="Die ou Lister lek weer olie", enqueue=False)
    out = b.process(r["capture_id"])
    assert out["state"] == "needs_review"
    item = b.db.one("select * from inbox where capture_id=?", (r["capture_id"],))
    res = b.resolve_inbox(item["id"], ids["pump"])
    assert res["status"] == "applied"
    assert b.db.one("select state from captures where id=?", (r["capture_id"],))["state"] == "applied"
    assert b.graph.node(ids["pump"])["status"] == "warning"
    assert any("lister" in a for a in b.graph.aliases(ids["pump"]))
    # next time the owner's own word finds the pump
    assert b.retriever.candidates(ids["ws"], "die ou Lister maak weer geraas")[0]["node_id"] == ids["pump"]


def test_undo_restores_everything(farm):
    b, ids = farm
    r = b.register_capture(ids["ws"], text="The main water pump is leaking badly", enqueue=False)
    b.process(r["capture_id"])
    assert b.graph.node(ids["pump"])["status"] == "critical"
    b.undo(r["capture_id"])
    pump = b.graph.node(ids["pump"])
    assert pump["status"] == "ok" and pump["open_tasks"] == 0 and pump["open_alerts"] == 0
    assert b.graph.node(ids["water"])["child_worst"] == "ok"
    assert b.db.one("select count(*) as c from notes")["c"] == 0
    assert b.db.one("select count(*) as c from notifications")["c"] == 0


def test_capture_is_idempotent(farm):
    b, ids = farm
    cid = "0192f7b2-3a10-7c44-8e21-6b5d9f0a1c77"
    b.register_capture(ids["ws"], text="The main water pump is leaking badly", capture_id=cid, enqueue=False)
    assert b.register_capture(ids["ws"], text="again", capture_id=cid)["duplicate"]
    b.process(cid)
    b.db.update("captures", {"id": cid}, {"state": "routing"})  # crash after apply, job re-runs
    b.process(cid)
    assert b.db.one("select count(*) as c from notes")["c"] == 1
    assert b.db.one("select count(*) as c from tasks")["c"] == 1


def test_worker_runs_queued_captures(farm):
    b, ids = farm
    r = b.register_capture(ids["ws"], text="Dipped the ewes in the south paddock")
    assert b.capture_summary(r["capture_id"])["state"] == "queued"
    assert b.run_jobs() == 1
    assert b.capture_summary(r["capture_id"])["state"] == "applied"


def test_resolve_alert_turns_node_back(farm):
    b, ids = farm
    r = b.register_capture(ids["ws"], text="The main water pump is leaking badly", enqueue=False)
    b.process(r["capture_id"])
    a = b.db.one("select id from alerts")["id"]
    b.resolve_alert(a)
    assert b.graph.node(ids["pump"])["status"] == "ok"
    t = b.tasks(ids["ws"])[0]
    b.update_task(t["id"], state="done")
    assert b.graph.node(ids["pump"])["open_tasks"] == 0


def test_decay_info_ring():
    b = make_brain()
    ids = seed_farm(b)
    r = b.register_capture(ids["ws"], text="Dipped the ewes in the south paddock", enqueue=False)
    b.process(r["capture_id"])
    assert b.graph.node(ids["sheep"])["status"] == "info"
    later = datetime.now(timezone.utc).replace(microsecond=0)
    from datetime import timedelta
    assert b.graph.decay(ids["ws"], later + timedelta(hours=25)) >= 1
    assert b.graph.node(ids["sheep"])["status"] == "ok"


def test_move_keeps_paths_and_blocks_cycles(farm):
    b, ids = farm
    b.graph.move(ids["pivot"], ids["beans"])
    assert b.graph.path_titles(ids["pivot"]) == "Operations > Crops > Beans > Centre Pivot 2"
    with pytest.raises(ValueError):
        b.graph.move(ids["ops"], ids["beans"])


def test_onboarding_starter_pack_and_model():
    b = make_brain()
    w = b.graph.create_workspace("Mine", owner_name="Dennis")["id"]
    out = b.onboard(w, "I run a cattle and sheep farm near Bronkhorstspruit with two tractors")
    assert out["proposal"]["source"] == "starter-pack:farm" and out["created"] > 10
    titles = {n["title"] for n in b.graph.nodes(w)}
    assert {"Livestock", "Sheep", "Tractors", "Maintenance"} <= titles

    from notecad_companion.llm import ScriptedLLM
    spine = {"persona": "mechanic", "branches": [
        {"title": "Jobs", "kind": "category", "children": [{"title": "Mr Botha's Hilux", "kind": "asset"}]},
        {"title": "Tools", "kind": "category", "children": [{"title": "Lift 1", "kind": "asset", "aliases": ["the hoist"]}]}]}
    b.onboarding_llm = ScriptedLLM(lambda m, s: json.dumps(spine))
    w2 = b.graph.create_workspace("Shop", owner_name="Dennis")["id"]
    out = b.onboard(w2, "I fix bakkies in my workshop; right now Mr Botha's Hilux is on lift 1")
    assert out["proposal"]["source"] == "starter-pack:workshop+scripted"
    lift = b.db.one("select id from nodes where lower(title)='lift 1'")["id"]
    assert b.graph.aliases(lift) == ["the hoist"]
    assert b.graph.workspace(w2)["persona"] == "mechanic"


def test_digest_lists_open_work(farm):
    b, ids = farm
    for t in ("The main water pump is leaking badly", "Ask Sipho to fix the north fence tomorrow"):
        r = b.register_capture(ids["ws"], text=t, enqueue=False)
        b.process(r["capture_id"])
    d = b.digest(ids["ws"])
    assert len(d["tasks"]) == 2 and len(d["alerts"]) == 1
    assert any(t["assignee_name"] == "Sipho Dlamini" for t in d["tasks"])
    assert "Main Water Pump" in d["alerts"][0]["path"]
