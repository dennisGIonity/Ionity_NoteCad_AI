# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""ADR 0014, step 4: seats, invites, joining with a one-time code, per-device tokens, role changes, revoking (and a
revoked phone handing in what it recorded before), and a member's device copy: snapshot, pull, tombstones, reset."""
import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from notecad_brain.api import create_app
from notecad_brain.graph import GraphError
from notecad_brain.permissions import load_principal
from test_roles_access import SECRET, as_, leaks, seed_roles


@pytest.fixture
def people(farm):
    b, ids = farm
    ids = seed_roles(b, ids)
    return b, ids, as_(b, ids, "owner")


def _join(b, ids, owner, name="Zanele", role="employee", **kw):
    if not b.db.one("select 1 from seats where workspace_id=? and status='available' and role_level>=?",
                    (ids["ws"], 3 if role == "employee" else 2)):
        b.people.add_seats(owner, ids["ws"], role, 1)
    inv = b.people.invite(owner, ids["ws"], name=name, role=role, base_urls=["http://192.168.1.20:8788"], **kw)
    return inv, b.people.join(inv["code"], f"{name}'s phone", "android")


# ---------------------------------------------------------------- seats and invites
def test_owners_buy_seats_managers_see_the_free_employee_ones(people):
    b, ids, owner = people
    ws = ids["ws"]
    b.people.add_seats(owner, ws, "employee", 2)
    b.people.add_seats(owner, ws, "manager", 1)
    with pytest.raises(PermissionError):
        b.people.add_seats(as_(b, ids, "sipho"), ws, "employee", 1)
    with pytest.raises(GraphError):
        b.people.add_seats(owner, ws, "owner", 1)  # owners need no seat
    assert len(b.people.seats(owner, ws)) == 3
    assert [s["role_level"] for s in b.people.seats(as_(b, ids, "sipho"), ws)] == [3, 3]
    assert b.people.seats(as_(b, ids, "thandi"), ws) == []


def test_an_invite_is_a_one_time_code_and_joining_makes_the_member(people):
    b, ids, owner = people
    ws = ids["ws"]
    b.people.add_seats(owner, ws, "employee", 1)
    inv = b.people.invite(owner, ws, name="Zanele", role="employee", scope_node_ids=[ids["water"]],
                          base_urls=["http://192.168.1.20:8788"])
    link = urlparse(inv["links"][0])
    assert link.scheme == "notecad" and parse_qs(link.query) == {"u": ["http://192.168.1.20:8788"], "c": [inv["code"]],
                                                                 "w": [ws]}
    stored = b.db.one("select * from invites where id=?", (inv["invite"]["id"],))
    assert stored["code_hash"] == hashlib.sha256(inv["code"].encode()).hexdigest() and inv["code"] not in json.dumps(stored)
    pv = b.people.preview(inv["code"])
    assert (pv["workspace"], pv["role"], pv["name"]) == ("Highveld Farm", "employee", "Zanele")
    assert pv["scope"] == ["Infrastructure > Water"]
    got = b.people.join(inv["code"], "Zanele's phone", "android")
    assert got["token"].startswith("nct_") and got["role"] == "employee"
    m = load_principal(b.db, ws, got["member_id"])
    assert m.level == 3 and m.active and len(m.scopes) == 1
    assert b.db.one("select status, assigned_member_id from seats where id=?", (got["seat_id"],)) == {
        "status": "assigned", "assigned_member_id": got["member_id"]}
    dev = b.db.one("select * from devices where id=?", (got["device_id"],))
    assert dev["token_hash"] == hashlib.sha256(got["token"].encode()).hexdigest()  # the token itself is kept nowhere
    with pytest.raises(KeyError):  # once only
        b.people.join(inv["code"], "another phone")


def test_joining_wakes_the_member_already_on_the_map(people):
    """Thandi was added for delegation (no seat, no login): her invite, through her person node, makes her a user."""
    b, ids, owner = people
    _, got = _join(b, ids, owner, name="Thandi Nkosi", person_node_id=ids["thandi_node"])
    assert got["member_id"] == ids["thandi"]
    assert b.db.one("select count(*) as c from members where person_node_id=?", (ids["thandi_node"],))["c"] == 1


def test_managers_invite_employees_into_their_own_branches(people):
    b, ids, owner = people
    ws = ids["ws"]
    b.people.add_seats(owner, ws, "employee", 2)
    marie = as_(b, ids, "marie")  # bound to Infrastructure
    assert b.people.invite(marie, ws, name="Pieter", scope_node_ids=[ids["water"]])["code"]
    with pytest.raises(PermissionError):
        b.people.invite(marie, ws, name="Pieter", scope_node_ids=[ids["sheep"]])  # outside her branch
    with pytest.raises(PermissionError):
        b.people.invite(marie, ws, name="Pieter")  # unbound: they would see more than she manages
    with pytest.raises(PermissionError):
        b.people.invite(marie, ws, name="Pieter", role="manager", scope_node_ids=[ids["water"]])
    with pytest.raises(PermissionError):
        b.people.invite(as_(b, ids, "thandi"), ws, name="Pieter")


def test_no_free_seat_no_invite_and_an_expired_code_does_nothing(people):
    b, ids, owner = people
    with pytest.raises(GraphError, match="no free employee seat"):
        b.people.invite(owner, ids["ws"], name="Zanele")
    b.people.add_seats(owner, ids["ws"], "employee", 1)
    inv = b.people.invite(owner, ids["ws"], name="Zanele")
    b.db.execute("update invites set expires_at='2020-01-01T00:00:00Z' where id=?", (inv["invite"]["id"],))
    with pytest.raises(KeyError):
        b.people.join(inv["code"], "phone")


# ---------------------------------------------------------------- roles and revoking
def test_role_changes_need_a_seat_that_holds_them(people):
    b, ids, owner = people
    ws = ids["ws"]
    _, got = _join(b, ids, owner)
    with pytest.raises(GraphError, match="no free manager seat"):
        b.people.set_role(owner, ws, got["member_id"], role="manager")
    b.people.add_seats(owner, ws, "manager", 1)
    m = b.people.set_role(owner, ws, got["member_id"], role="manager")
    assert m["level"] == 2 and m["seat_id"] != got["seat_id"]
    assert b.db.one("select status from seats where id=?", (got["seat_id"],))["status"] == "available"
    with pytest.raises(PermissionError):
        b.people.set_role(as_(b, ids, "sipho"), ws, got["member_id"], role="employee")
    with pytest.raises(GraphError, match="last owner"):
        b.people.set_role(owner, ws, ids["owner"], role="manager")


def test_revoking_stops_the_device_and_frees_the_seat(people):
    b, ids, owner = people
    ws = ids["ws"]
    _, got = _join(b, ids, owner)
    c = TestClient(create_app(b))
    h = {"Authorization": f"Bearer {got['token']}"}
    assert c.get(f"/v1/workspaces/{ws}/me", headers=h).json()["member_id"] == got["member_id"]
    b.people.revoke_member(owner, ws, got["member_id"])
    r = c.get(f"/v1/workspaces/{ws}/mindmap", headers=h)
    assert r.status_code == 410 and r.json()["detail"]["wipe"] is True
    assert b.db.one("select status from seats where id=?", (got["seat_id"],))["status"] == "available"
    assert c.post("/v1/device/wiped", headers=h).json() == {"wiped": True}
    assert b.db.one("select wipe_acked_at from devices where id=?", (got["device_id"],))["wipe_acked_at"]


def test_a_revoked_phone_hands_in_what_it_recorded_before_for_an_owner(people):
    """Owner question 2: recordings made before the revoke are taken once, held for an owner, never applied."""
    b, ids, owner = people
    ws = ids["ws"]
    _, got = _join(b, ids, owner)
    before = "2026-10-29T07:00:00Z"
    b.people.revoke_member(owner, ws, got["member_id"])
    revoked = b.db.one("select revoked_at from devices where id=?", (got["device_id"],))["revoked_at"]
    assert revoked > before
    c = TestClient(create_app(b))
    h = {"Authorization": f"Bearer {got['token']}"}
    r = c.post(f"/v1/workspaces/{ws}/capture", headers=h,
               json={"text": "The pump oil is low", "recorded_at": before, "wait": True})
    assert r.status_code == 200, r.text
    cid = r.json()["capture_id"]
    assert not b.db.one("select 1 from notes where capture_id=?", (cid,))  # nothing applied
    item = b.db.one("select * from inbox where capture_id=? and state='open'", (cid,))
    assert item and set(json.loads(item["route_member_ids"])) == {ids["owner"]}
    late = c.post(f"/v1/workspaces/{ws}/capture", headers=h, json={"text": "After", "recorded_at": "2099-01-01T00:00:00Z"})
    assert late.status_code == 410


def test_join_over_http_and_the_door_is_throttled(people):
    b, ids, owner = people
    b.people.add_seats(owner, ids["ws"], "employee", 1)
    inv = b.people.invite(owner, ids["ws"], name="Zanele")
    c = TestClient(create_app(b))
    assert c.get("/v1/join", params={"c": inv["code"]}).json()["role"] == "employee"
    got = c.post("/v1/join", json={"code": inv["code"], "device_name": "Zanele's phone"}).json()
    assert got["token"].startswith("nct_")
    assert c.post("/v1/join", json={"code": inv["code"]}).status_code == 404
    codes = [c.post("/v1/join", json={"code": "wrong-code-123"}).status_code for _ in range(10)]
    assert 429 in codes


# ---------------------------------------------------------------- the device copy
def _sync(b, p, cursor=None):
    return b.devices.pull(p, cursor) if cursor else b.devices.snapshot(p)


def test_a_snapshot_holds_only_what_the_member_may_see(people):
    b, ids, owner = people
    snap = b.devices.snapshot(as_(b, ids, "thandi"))
    assert snap["reset"] and not leaks(snap["tables"])
    assert all("audio_path" not in c for c in snap["tables"]["captures"])
    assert all("token_hash" not in d for d in snap["tables"]["devices"])
    lerato = b.devices.snapshot(as_(b, ids, "lerato"))
    nodes = {n["id"]: n for n in lerato["tables"]["nodes"]}
    assert ids["pump"] in nodes and ids["sheep"] not in nodes and nodes[ids["infra"]].get("stub")


def test_pull_sends_what_changed_and_tombstones_what_was_restricted(people):
    b, ids, owner = people
    ws = ids["ws"]
    thandi = as_(b, ids, "thandi")
    seen = b.register_capture(ws, text="Pump hours 1200", enqueue=False, principal=owner)  # touches the pump only
    b.applier.apply(ws, seen["capture_id"], 0, [{"type": "append_note", "node_id": ids["pump"], "text": "Pump hours 1200",
                                                 "confidence": 1, "evidence": "x"}], "user:test", principal=owner)
    b.graph.capture_level(seen["capture_id"])
    cur = b.devices.snapshot(thandi)["cursor"]
    r = b.register_capture(ws, text="The pivot is running", enqueue=False, principal=thandi)
    b.applier.apply(ws, r["capture_id"], 0, [{"type": "append_note", "node_id": ids["pump"], "text": "Pump oil topped up",
                                              "confidence": 1, "evidence": "x"}], "user:test", principal=thandi)
    b.graph.capture_level(r["capture_id"])
    got = b.devices.pull(thandi, cur)
    assert any(c["tbl"] == "notes" and c["row"]["body"] == "Pump oil topped up" for c in got["changes"])
    assert not leaks(got)
    # the owner makes Water managers-only: Thandi's device drops it, and her capture that touched it
    b.change(owner, ws, [{"type": "set_visibility", "node_id": ids["water"], "visibility": "manager"}])
    got2 = b.devices.pull(thandi, got["cursor"])
    assert {"op": "H", "tbl": "nodes", "pk": ids["water"]} in got2["tombstones"]
    assert {"op": "D", "tbl": "captures", "pk": seen["capture_id"]} in got2["changes"]  # the owner's pump note: gone
    assert {"op": "D", "tbl": "captures", "pk": r["capture_id"]} not in got2["changes"]  # what she said stays hers
    assert not any(c.get("row", {}).get("node_id") == ids["pump"] for c in got2["changes"] if c["op"] == "U")
    # and when it opens again she starts over from a snapshot
    b.change(owner, ws, [{"type": "set_visibility", "node_id": ids["water"], "visibility": "all"}])
    assert b.devices.pull(thandi, got2["cursor"])["reset"] is True


def test_a_role_change_or_another_brain_means_a_new_snapshot(people):
    b, ids, owner = people
    _, got = _join(b, ids, owner)
    p = load_principal(b.db, ids["ws"], got["member_id"])
    cur = b.devices.snapshot(p)["cursor"]
    assert b.devices.pull(p, cur)["reset"] is False
    b.people.add_seats(owner, ids["ws"], "manager", 1)
    b.people.set_role(owner, ids["ws"], got["member_id"], role="manager")
    assert b.devices.pull(load_principal(b.db, ids["ws"], got["member_id"]), cur)["reset"] is True
    assert b.devices.pull(p, "another-brain|x|1|1|y")["reset"] is True


def test_device_routes_need_a_device_token(people):
    b, ids, owner = people
    _, got = _join(b, ids, owner)
    c = TestClient(create_app(b))
    assert c.get("/v1/device/snapshot").status_code == 403  # this PC is not a member's device
    h = {"Authorization": f"Bearer {got['token']}"}
    snap = c.get("/v1/device/snapshot", headers=h).json()
    assert snap["reset"] and not any(s in json.dumps(snap) for s in SECRET)
    pulled = c.get("/v1/device/pull", headers=h, params={"cursor": snap["cursor"]}).json()
    assert pulled["reset"] is False


# ---------------------------------------------------------------- the showcase farm (step 6)
def test_the_showcase_farm_has_its_people_and_a_restricted_branch():
    """One owner, Marie managing the North Block, Sipho and Thandi as employees, Financials for owners only."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from farm import make_brain
    from notecad_brain.permissions import View
    from seed_farm_showcase import LocalBrain, build
    b = make_brain()
    build(LocalBrain(b), "showcase")
    m = {r["display_name"]: r for r in b.graph.members("showcase")}
    assert (m["Dennis"]["level"], m["Marie Venter"]["level"], m["Sipho Dlamini"]["level"], m["Thandi Nkosi"]["level"]) == (1, 2, 3, 3)
    marie = load_principal(b.db, "showcase", m["Marie Venter"]["id"])
    assert len(marie.scopes) == 1
    fin = next(n for n in b.graph.nodes("showcase") if n["title"] == "Financials")
    assert fin["eff_level"] == 1
    for who in ("Sipho Dlamini", "Marie Venter"):
        v = View(b.db, load_principal(b.db, "showcase", m[who]["id"]), "showcase")
        assert "Financials" not in json.dumps(b.mindmap("showcase", view=v)["nodes"])
    assert len([s for s in b.db.query("select * from seats where workspace_id='showcase' and status='available'")]) == 4
