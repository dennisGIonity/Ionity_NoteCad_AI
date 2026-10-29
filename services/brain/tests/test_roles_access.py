# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""ADR 0014, step 3: what each role may see and do, enforced in the Applier, every read, the API, the live events and
sync. Runs on SQLite, and on Postgres where the `farm` fixture does (CI)."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from farm import seed_farm
from notecad_brain.api import create_app
from notecad_brain.events import for_view
from notecad_brain.permissions import View, load_principal, owner_principal
from notecad_brain.routers import RouterChain
from test_sync import brain, link

LOAN_NOTE = "Absa loan repayment of R200000 is due Friday"
SECRET = ("Financials", "Bank Loan", "Absa", "R200000", "Loan payment overdue", "Pay the Absa loan", "Payroll")


def leaks(obj) -> list[str]:
    text = json.dumps(obj, default=str)
    return [s for s in SECRET if s in text]


def seed_roles(b, ids: dict) -> dict:
    """On the test farm: Financials (owner only) with a loan, Payroll (managers), Marie (a manager bound to
    Infrastructure), Thandi (an employee) and Lerato (an employee bound to Water). One owner capture touches both the
    loan and the pump."""
    g, ws = b.graph, ids["ws"]
    staff = g.node(ids["sipho_node"])["parent_id"]
    ids["owner"] = owner_principal(b.db, ws).member_id
    ids["thandi_node"] = g.add_node(ws, staff, "Thandi", "person")
    ids["thandi"] = g.add_member(ws, "Thandi Nkosi", role="employee", person_node_id=ids["thandi_node"])
    ids["marie"] = g.add_member(ws, "Marie", role="manager")
    ids["lerato"] = g.add_member(ws, "Lerato", role="employee")
    for member, node in ((ids["marie"], ids["infra"]), (ids["lerato"], ids["water"])):
        b.db.insert("member_scopes", {"workspace_id": ws, "member_id": member, "node_id": node,
                                      "created_at": "2026-10-29T08:00:00Z"})
    ids["financials"] = g.add_node(ws, ids["root"], "Financials", "category")
    ids["loan"] = g.add_node(ws, ids["financials"], "Bank Loan", "topic", aliases=["absa loan"])
    g.set_visibility(ids["financials"], "owner", 1)
    admin = g.node(staff)["parent_id"]
    ids["payroll"] = g.add_node(ws, admin, "Payroll", "topic")
    g.set_visibility(ids["payroll"], "manager", 1)
    owner = as_(b, ids, "owner")
    r = b.register_capture(ws, text=f"{LOAN_NOTE}. The pump oil is low.", enqueue=False, principal=owner)
    ids["owner_capture"] = r["capture_id"]
    for idx, (node, body) in enumerate(((ids["loan"], LOAN_NOTE), (ids["pump"], "The pump oil is low"))):
        b.applier.apply(ws, r["capture_id"], idx, [{"type": "append_note", "node_id": node, "text": body,
                                                    "confidence": 1, "evidence": body}], "user:test", principal=owner)
    b.applier.apply(ws, None, None, [
        {"type": "create_alert", "node_id": ids["loan"], "severity": "critical", "category": "finance",
         "title": "Loan payment overdue", "confidence": 1, "evidence": "x"},
        {"type": "create_task", "node_id": ids["loan"], "title": "Pay the Absa loan", "confidence": 1, "evidence": "x"},
        {"type": "set_status", "node_id": ids["loan"], "status": "critical", "confidence": 1, "evidence": "x"}],
        "user:test", principal=owner)
    g.capture_level(r["capture_id"])
    b.db.update("captures", {"id": r["capture_id"]}, {"state": "applied"})
    return ids


def as_(b, ids: dict, who: str):
    return load_principal(b.db, ids["ws"], ids[who])


@pytest.fixture
def roles(farm):
    b, ids = farm
    return b, seed_roles(b, ids)


class Fixed:
    """A router that answers with the same actions, so a test sees the Applier decide, not the routing."""
    name = "fixed"

    def __init__(self, actions):
        self.actions = actions

    def route(self, ctx):
        return {"capture_id": ctx.capture_id, "event_index": ctx.event_index, "summary": ctx.event,
                "actions": [{**a, "confidence": 1.0, "evidence": ctx.event} for a in self.actions]}


# ---------------------------------------------------------------- what each level sees
def test_restricted_levels_inherit_down_the_tree(roles):
    b, ids = roles
    g = b.graph
    assert g.node(ids["financials"])["eff_level"] == 1 and g.node(ids["loan"])["eff_level"] == 1
    assert g.node(ids["payroll"])["eff_level"] == 2 and g.node(ids["pump"])["eff_level"] == 3
    child = g.add_node(ids["ws"], ids["loan"], "Interest", "topic")
    assert g.node(child)["eff_level"] == 1  # made under a restricted branch: restricted too
    g.move(child, ids["water"])
    assert g.node(child)["eff_level"] == 3  # moved out of it
    assert b.db.one("select eff_level from captures where id=?", (ids["owner_capture"],))["eff_level"] == 1
    with pytest.raises(Exception, match="top of the map"):
        g.set_visibility(ids["root"], "owner", 1)


def test_an_employee_sees_nothing_restricted(roles):
    """The brief: an employee's digest, mind map, search and export hold zero restricted rows."""
    b, ids = roles
    ws = ids["ws"]
    v = View(b.db, as_(b, ids, "thandi"), ws)
    mm = b.mindmap(ws, view=v)
    assert not leaks(mm["nodes"]) and not leaks(mm["edges"])
    root = next(n for n in mm["nodes"] if n["id"] == ids["root"])
    assert root["child_worst"] != "critical"  # the loan's critical alert leaves no echo on the root
    assert not leaks(b.digest(ws, view=v))
    assert not leaks(b.retriever.candidates(ws, "the absa bank loan payment", view=v))
    assert not leaks(b.export_workspace(ws, v)["tables"])
    assert not leaks(b.keyterms(ws, v)) and not leaks(b.tasks(ws, view=v)) and not leaks(b.alerts(ws, view=v))
    hist = b.history(ids["pump"], view=v)
    assert hist and all(h["capture_text"] is None and not h["audio"] for h in hist)  # the loan was in the same note
    for fn, arg in ((b.node_detail, ids["loan"]), (b.capture_summary, ids["owner_capture"]),
                    (b.history, ids["loan"])):
        with pytest.raises(KeyError):
            fn(arg, view=v)
    o = View(b.db, as_(b, ids, "owner"), ws)  # the owner still sees all of it
    assert leaks(b.mindmap(ws, view=o)["nodes"]) and b.history(ids["pump"], view=o)[0]["capture_text"]


def test_managers_see_manager_branches_but_not_owner_only(roles):
    b, ids = roles
    v = View(b.db, as_(b, ids, "sipho"), ids["ws"])
    titles = {n["title"] for n in b.mindmap(ids["ws"], view=v)["nodes"]}
    assert "Payroll" in titles and "Financials" not in titles and "Bank Loan" not in titles


def test_a_scoped_employee_sees_their_branch_and_the_path_to_it(roles):
    b, ids = roles
    v = View(b.db, as_(b, ids, "lerato"), ids["ws"])
    nodes = {n["id"]: n for n in b.mindmap(ids["ws"], view=v)["nodes"] if n["type"] in ("root", "category", "entity")}
    assert ids["pump"] in nodes and ids["sheep"] not in nodes and ids["tractors"] not in nodes
    assert nodes[ids["infra"]].get("stub")  # the path to Water: its title, nothing hanging off it
    assert b.node_detail(ids["infra"], v)["notes"] == [] and b.node_detail(ids["infra"], v).get("stub")


def test_live_events_carry_only_what_the_viewer_sees(roles):
    b, ids = roles
    ws = ids["ws"]
    owner = as_(b, ids, "owner")
    b.change(owner, ws, [{"type": "update_attributes", "node_id": ids["loan"], "set": {"balance": 1}},
                         {"type": "update_attributes", "node_id": ids["pump"], "set": {"hours": 2}}])
    msgs = b.broker.of(ws)
    v = View(b.db, as_(b, ids, "thandi"), ws)
    seen = [m for m in (for_view(m, v) for m in msgs) if m is not None]
    assert not leaks(seen) and not any(ids["loan"] in json.dumps(m) for m in seen)
    assert any(m["type"] == "node.updated" and m.get("node_id") == ids["pump"] for m in seen)
    assert all("_author" not in json.loads(b.broker.sse(m).split("data: ", 1)[1]) for m in seen)


def test_restricted_critical_alerts_reach_only_those_who_see_them(roles):
    b, ids = roles
    got = {r["member_id"] for r in b.db.query("select member_id from notifications where kind='critical_alert'")}
    assert got == {ids["owner"]}  # Sipho and Marie are managers, but the loan is owner only


# ---------------------------------------------------------------- what each level may do
def test_employee_new_note_applies(roles):
    b, ids = roles
    thandi = as_(b, ids, "thandi")
    r = b.register_capture(ids["ws"], text="Centre pivot 2 is running fine today", enqueue=False, principal=thandi)
    out = b.process(r["capture_id"])
    assert out["state"] == "applied"
    note = b.db.one("select * from notes where capture_id=?", (r["capture_id"],))
    assert note["member_id"] == ids["thandi"] and note["node_id"] == ids["pivot"]
    row = b.db.one("select * from action_log where capture_id=? and action like ?", (r["capture_id"], "%append_note%"))
    assert row["member_id"] == ids["thandi"] and row["member_level"] == 3


def test_employee_rename_becomes_a_proposal_for_an_owner(roles):
    b, ids = roles
    res = b.change(as_(b, ids, "thandi"), ids["ws"], [{"type": "rename_node", "node_id": ids["pump"],
                                                       "title": "Big Pump"}])
    assert res["status"] == "held" and b.graph.node(ids["pump"])["title"] == "Main Water Pump"
    item = b.db.one("select * from inbox where id=?", (res["proposal"],))
    assert item["kind"] == "approval" and item["author_member_id"] == ids["thandi"]
    assert json.loads(item["route_member_ids"]) == [ids["owner"]]  # managers cannot rename: the owner decides
    b.resolve_inbox(res["proposal"], decision="approve", principal=as_(b, ids, "owner"))
    assert b.graph.node(ids["pump"])["title"] == "Big Pump"


def test_employee_delete_is_refused_and_logged(roles):
    b, ids = roles
    res = b.change(as_(b, ids, "thandi"), ids["ws"], [{"type": "delete_node", "node_id": ids["pivot"]}])
    assert res["status"] == "refused" and b.graph.node(ids["pivot"]) is not None
    log = b.db.one("select * from action_log where member_id=? and action like ?", (ids["thandi"], "%refused%"))
    assert json.loads(log["action"])["action"] == "delete_node"


def test_a_model_cannot_route_an_employee_onto_a_hidden_branch(roles):
    """The guard is in the Applier: even a router that names the loan for an employee changes nothing there."""
    b, ids = roles
    b.routers = RouterChain([Fixed([{"type": "append_note", "node_id": ids["loan"], "text": "paid"}])])
    r = b.register_capture(ids["ws"], text="The loan is paid", enqueue=False, principal=as_(b, ids, "thandi"))
    b.process(r["capture_id"])
    assert not b.db.one("select 1 from notes where capture_id=?", (r["capture_id"],))


def test_manager_approves_and_the_log_names_writer_and_approver(roles):
    b, ids = roles
    ws = ids["ws"]
    b.change(as_(b, ids, "owner"), ws, [{"type": "set_status", "node_id": ids["pivot"], "status": "critical"}])
    b.routers = RouterChain([Fixed([{"type": "append_note", "node_id": ids["pivot"], "text": "Pivot fixed"},
                                    {"type": "set_status", "node_id": ids["pivot"], "status": "ok",
                                     "reason": "fixed"}])])
    r = b.register_capture(ws, text="Centre pivot 2 is fixed", enqueue=False, principal=as_(b, ids, "thandi"))
    out = b.process(r["capture_id"])
    assert b.db.one("select count(*) as c from notes where capture_id=?", (r["capture_id"],))["c"] == 1  # the note now
    assert b.graph.node(ids["pivot"])["status"] == "critical"  # clearing a problem waits for a manager
    proposal = next(e["proposal"] for e in out["events"] if e.get("proposal"))
    route = json.loads(b.db.one("select route_member_ids from inbox where id=?", (proposal,))["route_member_ids"])
    assert set(route) == {ids["sipho"], ids["marie"]}  # Sipho manages everything, Marie Infrastructure
    with pytest.raises(KeyError):  # not Lerato's to decide (she cannot even see it)
        b.resolve_inbox(proposal, decision="approve", principal=as_(b, ids, "lerato"))
    b.resolve_inbox(proposal, decision="approve", principal=as_(b, ids, "marie"))
    assert b.graph.node(ids["pivot"])["status"] == "ok"
    row = b.db.one("select * from action_log where capture_id=? and approved_by is not null and action like ?",
                   (r["capture_id"], '%"status": "ok"%'))
    assert row["member_id"] == ids["thandi"] and row["approved_by"] == ids["marie"]


def test_employees_assign_tasks_only_to_themselves(roles):
    b, ids = roles
    b.routers = RouterChain([Fixed([{"type": "create_task", "node_id": ids["pump"], "title": "Check the oil",
                                     "priority": "normal", "assignee_hint": "Sipho"}])])
    r = b.register_capture(ids["ws"], text="Ask Sipho to check the oil on the main water pump", enqueue=False,
                           principal=as_(b, ids, "thandi"))
    out = b.process(r["capture_id"])
    task = b.db.one("select * from tasks where capture_id=?", (r["capture_id"],))
    assert task["assignee_member"] is None and task["assignee_hint"] == "Sipho"  # made, not yet given to Sipho
    item = b.db.one("select * from inbox where id=?", (next(e["proposal"] for e in out["events"] if e.get("proposal")),))
    assert json.loads(item["proposal"])["actions"][0] == {**json.loads(item["proposal"])["actions"][0],
                                                          "type": "update_task", "id": task["id"],
                                                          "assignee_member": ids["sipho"]}


def test_a_task_is_not_given_to_someone_who_cannot_see_it(roles):
    b, ids = roles
    res = b.change(as_(b, ids, "owner"), ids["ws"], [{"type": "create_task", "node_id": ids["loan"],
                                                      "title": "Fetch the bank papers", "assignee_hint": "Thandi"}])
    task = b.db.one("select * from tasks where title='Fetch the bank papers'")
    assert task["assignee_member"] is None and res["notices"]  # the owner is told why


def test_managers_restrict_in_their_branches_but_never_to_owner_only(roles):
    b, ids = roles
    marie = as_(b, ids, "marie")
    assert b.change(marie, ids["ws"], [{"type": "set_visibility", "node_id": ids["pump"], "visibility": "manager"}])[
        "status"] == "applied"
    assert b.graph.node(ids["pump"])["eff_level"] == 2
    assert b.change(marie, ids["ws"], [{"type": "set_visibility", "node_id": ids["pivot"], "visibility": "owner"}])[
        "status"] == "refused"
    assert b.change(marie, ids["ws"], [{"type": "set_visibility", "node_id": ids["sheep"], "visibility": "manager"}])[
        "status"] == "refused"  # Sheep is outside her Infrastructure
    b.graph.set_visibility(ids["pivot"], "manager", 1)  # an owner restricted it
    assert b.change(marie, ids["ws"], [{"type": "set_visibility", "node_id": ids["pivot"], "visibility": "all"}])[
        "status"] == "refused"


def test_undo_is_your_own_unless_you_manage_it(roles):
    b, ids = roles
    with pytest.raises(KeyError):  # the owner's capture touched the loan: Thandi cannot even see it
        b.undo(ids["owner_capture"], as_(b, ids, "thandi"))
    r = b.register_capture(ids["ws"], text="Centre pivot 2 is running fine today", enqueue=False,
                           principal=as_(b, ids, "lerato"))
    b.process(r["capture_id"])
    with pytest.raises(PermissionError):
        b.undo(r["capture_id"], as_(b, ids, "thandi"))
    assert b.undo(r["capture_id"], as_(b, ids, "lerato"))["reverted"] >= 1


def test_read_only_members_cannot_record_and_capture_ids_are_per_author(roles):
    b, ids = roles
    viewer = b.graph.add_member(ids["ws"], "Visitor", role="viewer")
    with pytest.raises(PermissionError):
        b.register_capture(ids["ws"], text="hello", enqueue=False, principal=as_(b, {**ids, "v": viewer}, "v"))
    from notecad_brain.pipeline import CaptureConflict
    with pytest.raises(CaptureConflict):  # someone else's capture id: a conflict, never their capture back
        b.register_capture(ids["ws"], text="mine", capture_id=ids["owner_capture"], enqueue=False,
                           principal=as_(b, ids, "thandi"))


# ---------------------------------------------------------------- the API, with a per-device token
def _device(b, ids, who: str, token: str) -> None:
    b.db.insert("devices", {"id": f"dev-{who}", "workspace_id": ids["ws"], "member_id": ids[who],
                            "name": f"{who}'s phone", "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                            "created_at": "2026-10-29T08:00:00Z"})


def test_api_answers_as_the_device_member(roles):
    b, ids = roles
    _device(b, ids, "thandi", "nct_thandi")
    c = TestClient(create_app(b))
    h = {"Authorization": "Bearer nct_thandi"}
    ws = ids["ws"]
    assert c.get(f"/v1/workspaces/{ws}/me", headers=h).json()["role"] == "employee"
    for path in (f"/v1/workspaces/{ws}/mindmap", f"/v1/workspaces/{ws}/digest", f"/v1/workspaces/{ws}/export",
                 f"/v1/workspaces/{ws}/tasks", f"/v1/workspaces/{ws}/alerts", f"/v1/workspaces/{ws}/tree"):
        r = c.get(path, headers=h)
        assert r.status_code == 200 and not leaks(r.json()), path
    assert c.get(f"/v1/nodes/{ids['loan']}", headers=h).status_code == 404
    assert c.get(f"/v1/captures/{ids['owner_capture']}/audio", headers=h).status_code == 404
    assert c.patch(f"/v1/nodes/{ids['pump']}", json={"title": "Big Pump"}, headers=h).status_code == 202
    assert c.delete(f"/v1/nodes/{ids['pivot']}", headers=h).status_code == 403
    assert c.get("/v1/sync/status", headers=h).status_code == 403  # sync is between brains
    b.db.execute("update devices set revoked_at='2026-10-29T09:00:00Z' where id='dev-thandi'")
    r = c.get(f"/v1/workspaces/{ws}/mindmap", headers=h)
    assert r.status_code == 410 and r.json()["detail"]["wipe"] is True


def test_the_companion_reads_as_the_member(roles):
    b, ids = roles
    c = TestClient(create_app(b))  # this PC (no token): the owner, who may look as anyone
    full = c.get(f"/v1/workspaces/{ids['ws']}/digest").json()
    as_thandi = c.get(f"/v1/workspaces/{ids['ws']}/digest", params={"as_member": ids["thandi"]}).json()
    assert leaks(full) and not leaks(as_thandi)


# ---------------------------------------------------------------- sync: the receiver checks (decision 23, 24)
def test_a_stale_worker_cannot_push_what_a_demoted_member_did():
    desk, edge = brain("desktop"), brain("edge")
    ids = seed_farm(desk)
    ws = ids["ws"]
    marie = desk.graph.add_member(ws, "Marie", role="manager")
    eng = link(edge, desk)
    assert eng.run_once()["ok"]
    # the desktop demotes Marie; the edge node has not heard yet, and lets her change the pump's numbers
    desk.db.execute("update members set role='employee', level=3 where id=?", (marie,))
    edge.change(load_principal(edge.db, ws, marie), ws, [{"type": "update_attributes", "node_id": ids["pump"],
                                                          "set": {"flow_lph": 900}}])
    assert edge.graph.node(ids["pump"])["attributes"].get("flow_lph") == 900
    assert eng.run_once()["ok"]
    assert "flow_lph" not in desk.graph.node(ids["pump"])["attributes"]  # the hub did not take it
    item = desk.db.one("select * from inbox where kind='sync'")
    assert item and item["author_member_id"] == marie  # an owner may still approve it
    assert eng.run_once()["ok"]
    assert "flow_lph" not in edge.graph.node(ids["pump"])["attributes"]  # the edge put the hub's row back
    assert edge.db.one("select level from members where id=?", (marie,))["level"] == 3


def test_concurrent_edits_go_to_the_higher_rank():
    desk, edge = brain("desktop"), brain("edge")
    ids = seed_farm(desk)
    ws = ids["ws"]
    thandi = desk.graph.add_member(ws, "Thandi", role="employee")
    desk.change(load_principal(desk.db, ws, thandi), ws, [{"type": "create_task", "node_id": ids["pump"],
                                                           "title": "Grease the bearings"}])
    tid = desk.db.one("select id from tasks where title='Grease the bearings'")["id"]
    eng = link(edge, desk)
    assert eng.run_once()["ok"]
    # both edit the same version: the owner on the desktop, then (later) Thandi her own task on the edge node
    desk.change(owner_principal(desk.db, ws), ws, [{"type": "update_task", "id": tid, "title": "Grease both bearings"}])
    edge.change(load_principal(edge.db, ws, thandi), ws, [{"type": "update_task", "id": tid, "title": "Grease it"}])
    assert eng.run_once()["ok"] and eng.run_once()["ok"]
    assert desk.db.one("select title from tasks where id=?", (tid,))["title"] == "Grease both bearings"
    assert edge.db.one("select title from tasks where id=?", (tid,))["title"] == "Grease both bearings"
    assert desk.db.one("select count(*) as c from sync_conflicts")["c"] >= 1  # Thandi's version is kept
