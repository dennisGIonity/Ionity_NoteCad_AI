# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""The POPIA action audit (docs/compliance/popia-action-register.md): the seven findings the first review left open,
and the gaps the audit found. One test per guard. Runs on SQLite, and on Postgres where `farm` does (CI)."""
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from farm import make_brain, seed_farm
from notecad_brain import subjects, text
from notecad_brain.api import create_app
from notecad_brain.routers import ClaudeRouter, RouterChain, RulesRouter
from notecad_brain.stt import ChainSTT, DeepgramSTT, local_only
from test_people import _join
from test_roles_access import as_, seed_roles


@pytest.fixture
def people_farm(farm):
    b, ids = farm
    ids = seed_roles(b, ids)
    return b, ids, as_(b, ids, "owner")


class Companion:
    """Stands in for CompanionLink: records what the brain asks the companion to forget or hand over."""

    def __init__(self):
        self.calls: list[tuple] = []

    def forget(self, owner, terms, members, before=None, wipe=None):
        self.calls.append(("forget", owner, tuple(terms or ()), tuple(members), before, wipe))
        return {"memories": 1}

    def export(self, owner, member):
        return {"memories": [f"what {member} told the companion"]}

    def observe(self, *a, **k):
        pass

    def keyterms(self, *a, **k):
        return []


# ---------------------------------------------------------------- s23-24: one person's copy and erasure
def test_a_member_gets_a_copy_of_everything_about_them(people_farm):
    b, ids, owner = people_farm
    b.companion = Companion()
    ws = ids["ws"]
    thandi = as_(b, ids, "thandi")
    b.register_capture(ws, text="Thandi fixed the gate at the north camp", enqueue=False, principal=owner)
    got = subjects.export(b, thandi, ws, ids["thandi"])  # the person themselves
    assert "Thandi Nkosi" in got["names"] and got["member"]["id"] == ids["thandi"]
    assert any("Thandi fixed the gate" in (c.get("text") or "") for c in got["naming_them"]["captures"])
    assert got["companion"] == {"memories": [f"what {ids['thandi']} told the companion"]}
    with pytest.raises(PermissionError):  # another employee may not
        subjects.export(b, as_(b, ids, "lerato"), ws, ids["thandi"])
    assert subjects.export(b, owner, ws, ids["thandi"])["member"]["display_name"] == "Thandi Nkosi"  # an owner may


def test_erasing_a_person_removes_them_everywhere_but_the_audit_record(people_farm, tmp_path):
    b, ids, owner = people_farm
    b.companion = Companion()
    b.settings.audio_dir = str(tmp_path / "audio")
    ws = ids["ws"]
    thandi = as_(b, ids, "thandi")
    b.db.update("members", {"id": ids["thandi"]}, {"privacy_ack_at": "2026-10-29T10:00:00Z"})
    r = b.register_capture(ws, text="Thandi says the borehole pump is leaking", enqueue=False, principal=owner)
    b.process(r["capture_id"])
    rec = b.register_capture(ws, audio=b"OggS-thandi", mime="audio/ogg", enqueue=False, principal=thandi)
    rec_path = b.db.one("select audio_path from captures where id=?", (rec["capture_id"],))["audio_path"]
    logged = b.db.one("select count(*) as c from action_log where workspace_id=?", (ws,))["c"]
    with pytest.raises(PermissionError):
        subjects.erase(b, as_(b, ids, "marie"), ws, ids["thandi"])  # a manager may not
    out = subjects.erase(b, owner, ws, ids["thandi"])
    assert out["counts"]["texts"] >= 1 and out["counts"]["recordings"] == 1 and "action log" in out["kept"][0]
    every = json.dumps([b.db.query(f"select * from {t} where workspace_id=?", (ws,))
                        for t in ("notes", "tasks", "alerts", "captures", "inbox", "members", "nodes")])
    assert "Thandi" not in every and "[removed]" in every
    assert not __import__("pathlib").Path(rec_path).exists()
    assert "Thandi" not in json.dumps(b.mindmap(ws)) and "Thandi" not in json.dumps(b.digest(ws))
    assert "thandi" not in " ".join(b.keyterms(ws)).lower()
    assert "Thandi" not in json.dumps(b.export_workspace(ws), default=str)
    assert "Thandi" not in json.dumps(b.db.query("select row from sync_changes where ws=?", (ws,)))  # no old copy
    # an employee's next pull carries the change; the audit record stays
    lerato = as_(b, ids, "lerato")
    assert "Thandi" not in json.dumps(b.devices.snapshot(lerato))
    assert b.db.one("select count(*) as c from action_log where workspace_id=?", (ws,))["c"] >= logged
    assert b.db.one("select status from members where id=?", (ids["thandi"],))["status"] == "revoked"
    assert ("forget", ws) == b.companion.calls[-1][:2] and b.companion.calls[-1][5] == ids["thandi"]


def test_a_person_without_a_login_can_be_erased_too(people_farm):
    b, ids, owner = people_farm
    b.companion = Companion()
    ws = ids["ws"]
    thabo = b.graph.add_node(ws, b.graph.node(ids["sipho_node"])["parent_id"], "Thabo", "person",
                             aliases=["thabo mokoena"])
    b.applier.apply(ws, None, None, [{"type": "append_note", "node_id": ids["pump"],
                                      "text": "Thabo Mokoena serviced the pump", "confidence": 1, "evidence": "x"}],
                    "user:test", principal=owner)
    with pytest.raises(KeyError):
        subjects.erase(b, owner, ws, ids["pump"])  # not a person
    subjects.erase(b, owner, ws, thabo)
    assert b.graph.node(thabo)["title"] == "Removed person" and b.graph.aliases(thabo) == []
    assert "Thabo" not in json.dumps(b.db.query("select body from notes where workspace_id=?", (ws,)))


def test_the_api_asks_for_confirmation_and_an_owner(people_farm):
    b, ids, owner = people_farm
    b.companion = Companion()
    c = TestClient(create_app(b))
    ws, sid = ids["ws"], ids["lerato"]
    assert c.post(f"/api/v1/workspaces/{ws}/subjects/{sid}/erase").status_code == 400
    assert c.get(f"/api/v1/workspaces/{ws}/subjects/{sid}/export").status_code == 200
    assert c.post(f"/api/v1/workspaces/{ws}/subjects/{sid}/erase", params={"confirm": sid}).json()["erased"] == sid
    owner_id = ids["owner"]
    assert c.post(f"/api/v1/workspaces/{ws}/subjects/{owner_id}/erase",
                  params={"confirm": owner_id}).status_code == 403  # the last owner stays


# ---------------------------------------------------------------- s72: the cloud transfer gate
def _claude(sent: list):
    def handler(req: httpx.Request):
        sent.append(str(req.url))
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "apply_capture_actions",
                                                      "input": {"capture_id": "x", "event_index": 0, "summary": "",
                                                                "actions": []}}]})
    return ClaudeRouter("claude-sonnet-5-5", api_key="k", transport=httpx.MockTransport(handler))


def test_no_note_leaves_this_pc_while_the_gate_is_off(people_farm):
    b, ids, owner = people_farm
    sent: list[str] = []
    b.routers = RouterChain([_claude(sent), RulesRouter()])
    ws = ids["ws"]
    r = b.register_capture(ws, text="The main water pump is leaking", enqueue=False, principal=owner)
    assert b.process(r["capture_id"])["state"] in ("applied", "needs_review") and sent == []  # off by default
    b.db.update("workspaces", {"id": ws}, {"privacy": json.dumps({"cloud_ok": True})})
    r = b.register_capture(ws, text="The main water pump is leaking again", enqueue=False, principal=owner)
    b.process(r["capture_id"])
    assert sent and sent[0].startswith("https://api.anthropic.com")  # on: it goes
    sent.clear()
    r = b.register_capture(ws, text="The Absa bank loan repayment is due", enqueue=False, principal=owner)
    b.process(r["capture_id"])
    assert sent == []  # a note about Financials (owners only) never leaves, gate on or not


def test_recordings_stay_on_this_pc_while_the_gate_is_off():
    class Whisper:
        name = "whisper"

    dg = DeepgramSTT("k")
    assert local_only(dg) is None
    chain = ChainSTT([dg, Whisper()])
    assert local_only(chain).name == "whisper"
    w = Whisper()
    assert local_only(w) is w


def test_the_gate_is_an_owner_setting_and_is_logged(people_farm, caplog):
    b, ids, owner = people_farm
    c = TestClient(create_app(b))
    ws = ids["ws"]
    with caplog.at_level(logging.INFO, logger="notecad.security"):
        n = c.put(f"/api/v1/workspaces/{ws}/privacy", json={"contact": "Dennis", "cloud": True}).json()
    assert n["cloud"]["allowed"] and "cloud transfer gate on" in caplog.text
    _, got = _join(b, ids, owner)
    dev = {"Authorization": f"Bearer {got['token']}"}
    assert c.put(f"/api/v1/workspaces/{ws}/privacy", headers=dev, json={"contact": "x", "cloud": False}).status_code == 403


# ---------------------------------------------------------------- s18: the notice before the first note
def test_a_member_records_nothing_before_reading_the_notice(people_farm):
    b, ids, owner = people_farm
    c = TestClient(create_app(b))
    ws = ids["ws"]
    _, got = _join(b, ids, owner)
    dev = {"Authorization": f"Bearer {got['token']}"}
    r = c.post(f"/api/v1/workspaces/{ws}/captures", headers=dev, json={"text": "The pump is leaking"})
    assert r.status_code == 403 and "privacy_unread" in r.json()["detail"]
    r = c.post(f"/api/v1/workspaces/{ws}/uploads", headers={**dev, "Tus-Resumable": "1.0.0", "Upload-Length": "4"})
    assert r.status_code == 403
    c.post(f"/api/v1/workspaces/{ws}/privacy/ack", headers=dev)
    assert c.post(f"/api/v1/workspaces/{ws}/captures", headers=dev, json={"text": "The pump is leaking"}).status_code == 200
    # the owner, who sets the notice, is not held up by it
    assert c.post(f"/api/v1/workspaces/{ws}/captures", json={"text": "The pump is leaking"}).status_code == 200


# ---------------------------------------------------------------- s19 / s22: hardening and the security log
def test_answers_carry_security_headers_and_refusals_are_logged(people_farm, caplog):
    b, ids, _ = people_farm
    b.settings.api_token = "shared-secret"
    c = TestClient(create_app(b))
    r = c.get(f"/api/v1/workspaces/{ids['ws']}/digest")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
    with caplog.at_level(logging.WARNING, logger="notecad.security"):
        assert c.get(f"/api/v1/workspaces/{ids['ws']}/digest", headers={"Authorization": "Bearer nct_wrong"}).status_code == 401
    assert "refused 401 GET" in caplog.text and "nct_wrong" not in caplog.text


def test_an_invite_code_never_travels_in_a_url(people_farm):
    b, ids, owner = people_farm
    b.people.add_seats(owner, ids["ws"], "employee", 1)
    inv = b.people.invite(owner, ids["ws"], name="Zanele", role="employee", base_urls=["http://127.0.0.1:8788"])
    c = TestClient(create_app(b))
    assert c.post("/api/v1/join/preview", json={"code": inv["code"]}).json()["role"] == "employee"
    assert c.post("/api/v1/join/preview", json={"code": "wrongcode1"}).status_code == 404


# ---------------------------------------------------------------- s26-33: health and disciplinary details
def test_a_note_with_a_workers_health_is_held_for_the_owners():
    assert text.sensitive_about("Thabo was injured and went to hospital", ["Thabo"]) == ("Thabo", "health")
    assert text.sensitive_about("Sipho got a final warning for being drunk", ["Sipho"]) == ("Sipho", "disciplinary")
    assert text.sensitive_about("Sipho says the ewes are sick", ["Sipho"]) is None  # about animals
    assert text.sensitive_about("Ask Sipho to check the water pump", ["Sipho"]) is None
    b = make_brain()
    ids = seed_farm(b)
    r = b.register_capture(ids["ws"], text="Sipho was injured and went to hospital", enqueue=False)
    out = b.process(r["capture_id"])
    assert out["state"] == "needs_review"
    item = b.db.one("select * from inbox where capture_id=?", (r["capture_id"],))
    assert "health" in item["question"] and item["approver_level"] == 1
    r = b.register_capture(ids["ws"], text="Ask Sipho to check the water pump", enqueue=False)
    assert b.process(r["capture_id"])["state"] == "applied"  # field work goes straight on
