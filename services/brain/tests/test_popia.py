# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""The POPIA review's five high-priority fixes (docs/compliance): retention periods (s14), nothing left behind in the
sync journal after a delete, no token in a URL or a log (s19), HTTPS with a pinned certificate on the farm network
(s19), and the privacy notice (s18). Runs on SQLite, and on Postgres where the `farm` fixture does (CI)."""
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notecad_brain import retention
from notecad_brain.api import Tickets, create_app
from notecad_brain.common import now_iso
from notecad_brain.permissions import owner_principal
from notecad_brain.serve import redact
from test_people import _join
from test_roles_access import as_, seed_roles

DAY = 86400


# ---------------------------------------------------------------- fix 3: tickets instead of tokens in URLs and logs
def test_a_ticket_stands_for_a_credential_for_ten_minutes_only():
    t = Tickets()
    now = 1_800_000_000.0
    tk = t.issue("ab" * 32, True, now=now)
    assert tk.startswith("nck_") and "ab" * 32 in tk
    assert t.check(tk, now=now + 599) == ("ab" * 32, True)
    assert t.check(tk, now=now + Tickets.TTL + 1) is None              # expired
    assert t.check(tk.replace("ab", "ac", 1), now=now) is None          # changed
    assert Tickets().check(tk, now=now) is None                         # another process (a restart) ended it
    assert t.check("nct_not_a_ticket", now=now) is None


def test_the_log_never_holds_a_token_a_ticket_or_an_invite_code():
    line = ('127.0.0.1:5 - "GET /api/v1/workspaces/w/events/stream?last_event_id=3&token=nct_secret HTTP/1.1" 200 '
            '"GET /x?ticket=nck_1.dabc.sig&format=json" Authorization: Bearer shared-secret '
            'notecad://join?u=https%3A%2F%2F10.0.0.5%3A9788&c=INVITECODE&w=farm')
    out = redact(line)
    for secret in ("nct_secret", "nck_1.dabc.sig", "shared-secret", "INVITECODE"):
        assert secret not in out
    assert "last_event_id=3" in out and "format=json" in out and "w=farm" in out


def test_phones_get_live_events_and_recordings_with_a_ticket(farm):
    b, ids = farm
    ids = seed_roles(b, ids)
    owner = as_(b, ids, "owner")
    _, got = _join(b, ids, owner)
    b.settings.api_token = "shared-secret"
    c = TestClient(create_app(b))
    dev = {"Authorization": f"Bearer {got['token']}"}
    tk = c.post("/api/v1/tickets", headers=dev).json()
    assert tk["ticket"].startswith("nck_") and tk["expires_in"] == 600
    ws = ids["ws"]
    assert c.get(f"/api/v1/workspaces/{ws}/me", params={"ticket": tk["ticket"]}).json()["member_id"] == got["member_id"]
    assert c.get(f"/api/v1/workspaces/{ws}/me", params={"ticket": tk["ticket"] + "x"}).status_code == 401
    # a ticket is for reading: a change still needs the header
    assert c.post(f"/api/v1/workspaces/{ws}/capture", params={"ticket": tk["ticket"]},
                  data={"text": "pump"}).status_code in (401, 403)
    # the shared token's ticket acts as the first owner, like the token itself
    st = c.post("/api/v1/tickets", headers={"Authorization": "Bearer shared-secret"}).json()["ticket"]
    assert c.get(f"/api/v1/workspaces/{ws}/me", params={"ticket": st}).json()["role"] == "owner"
    # a revoked phone's ticket stops working with the phone
    b.people.revoke_member(owner, ws, got["member_id"])
    assert c.get(f"/api/v1/workspaces/{ws}/me", params={"ticket": tk["ticket"]}).status_code == 410


# ---------------------------------------------------------------- fix 4: HTTPS on the LAN with a pinned certificate
def test_the_lan_certificate_is_made_once_and_pinned(tmp_path):
    import ssl

    from notecad_brain.tls import ensure_cert, fingerprint, pinned_context
    cert, key = ensure_cert(tmp_path / "tls")
    fp = fingerprint(cert)
    assert len(fp) == 64 and key.read_text().startswith("-----BEGIN PRIVATE KEY")
    assert ensure_cert(tmp_path / "tls") == (cert, key) and fingerprint(cert) == fp  # never replaced on its own
    ctx = pinned_context(cert)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and not ctx.check_hostname


def test_invites_carry_the_certificate_pin_on_https_only(people_farm):
    b, ids, owner = people_farm
    b.people.add_seats(owner, ids["ws"], "employee", 1)
    inv = b.people.invite(owner, ids["ws"], name="Zanele", role="employee", pin="a" * 64,
                          base_urls=["https://192.168.1.20:9788", "http://127.0.0.1:8788"])
    https, plain = inv["links"]
    assert "f=" + "a" * 64 in https and "f=" not in plain


# ---------------------------------------------------------------- fix 1: retention periods
def test_periods_are_whole_days_or_kept():
    assert retention.clean({"audio_days": 90, "transcript_days": None}) == {
        "audio_days": 90, "transcript_days": None, "log_days": None}
    for bad in ({"audio_days": 0}, {"audio_days": 1.5}, {"audio_days": "90"}, {"audio_days": True},
                {"forever": 1}, {"log_days": 99999}):
        with pytest.raises(ValueError):
            retention.clean(bad)


def _old_capture(b, ws, tmp_path, days_ago: float, text="Check the borehole pump") -> str:
    r = b.register_capture(ws, text=text, enqueue=False, recorded_at=now_iso(time.time() - days_ago * DAY))
    audio = Path(b.settings.audio_dir) / ws / f"{r['capture_id']}.ogg"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"OggS")
    b.db.update("captures", {"id": r["capture_id"]}, {"audio_path": str(audio), "transcript": json.dumps({"x": text})})
    return r["capture_id"]


def test_nothing_is_deleted_until_an_owner_sets_the_periods(farm, tmp_path):
    b, ids = farm
    b.settings.audio_dir = str(tmp_path / "audio")
    cid = _old_capture(b, ids["ws"], tmp_path, 400)
    assert retention.purge_all(b) == {}
    cap = b.db.one("select audio_path, text from captures where id=?", (cid,))
    assert cap["audio_path"] and cap["text"] and Path(cap["audio_path"]).exists()


def test_old_recordings_transcripts_and_log_go_new_ones_stay(farm, tmp_path):
    b, ids = farm
    ws = ids["ws"]
    b.settings.audio_dir = str(tmp_path / "audio")
    old, mid, new = (_old_capture(b, ws, tmp_path, d) for d in (400, 100, 1))
    b.db.insert("capture_events", {"capture_id": old, "idx": 0, "text": "Check the borehole pump"})
    b.applier.apply(ws, None, None, [{"type": "append_note", "node_id": ids["pump"], "text": "Oil is low",
                                      "confidence": 1, "evidence": "x"}], "user:test")
    b.db.execute("update action_log set created_at=? where workspace_id=?", (now_iso(time.time() - 400 * DAY), ws))
    logged = b.db.one("select count(*) as c from action_log where workspace_id=?", (ws,))["c"]
    b.db.update("workspaces", {"id": ws}, {"retention": json.dumps({"audio_days": 90, "transcript_days": 365,
                                                                       "log_days": 365})})
    got = retention.purge(b, ws)
    assert got["audio"] == 2 and got["transcripts"] == 1 and got["log"] >= logged > 0
    caps = {r["id"]: r for r in b.db.query("select id, audio_path, text, transcript from captures where workspace_id=?",
                                            (ws,))}
    assert caps[old]["audio_path"] is None and caps[mid]["audio_path"] is None and caps[new]["audio_path"]
    assert not (Path(b.settings.audio_dir) / ws / f"{old}.ogg").exists()
    assert (Path(b.settings.audio_dir) / ws / f"{new}.ogg").exists()
    assert caps[old]["text"] is None and caps[old]["transcript"] is None and caps[mid]["text"]
    assert b.db.one("select text from capture_events where capture_id=?", (old,))["text"] == ""
    # the map the owner keeps is a business record: its nodes are untouched
    assert b.graph.node(ids["pump"]) is not None
    assert retention.purge(b, ws)["audio"] == 0  # once only


def test_the_journal_keeps_only_the_newest_change_of_each_row(farm):
    b, ids = farm
    ws = ids["ws"]
    for name in ("Pump A", "Pump B", "Pump C"):
        b.db.update("nodes", {"id": ids["pump"]}, {"title": name})
    rows = b.db.query("select row from sync_changes where tbl='nodes' and pk=? order by seq", (ids["pump"],))
    assert len(rows) >= 3 and any("Pump A" in (r["row"] or "") for r in rows)
    retention.compact_journal(b.db, ws)
    rows = b.db.query("select row from sync_changes where tbl='nodes' and pk=?", (ids["pump"],))
    assert len(rows) == 1 and "Pump C" in rows[0]["row"]
    dups = b.db.one("select count(*) as c from (select tbl, pk from sync_changes where ws=? group by tbl, pk "
                    "having count(*) > 1) x", (ws,))["c"]
    assert dups == 0


def test_old_archives_go_when_the_pc_sets_a_period(tmp_path):
    arch = tmp_path / "archive"
    (arch / "old-backup").mkdir(parents=True)
    (arch / "old-backup" / "brain.db").write_bytes(b"x")
    (arch / "farm-20260101.json").write_text("{}")
    (arch / "farm-today.json").write_text("{}")
    month_ago = time.time() - 40 * DAY
    for p in (arch / "old-backup", arch / "farm-20260101.json"):
        os.utime(p, (month_ago, month_ago))
    assert retention.purge_archives(arch, 0) == 0
    assert retention.purge_archives(arch, 30) == 2
    assert [p.name for p in arch.iterdir()] == ["farm-today.json"]


# ---------------------------------------------------------------- fix 2: a deleted workspace leaves no copy behind
def test_a_deleted_workspace_leaves_only_tombstones_in_the_journal(farm):
    b, ids = farm
    ws = ids["ws"]
    b.register_capture(ws, text="Sipho must fix the North borehole pump", enqueue=False)
    assert b.db.one("select count(*) as c from sync_changes where ws=? and op<>'D'", (ws,))["c"] > 0
    got = b.delete_workspace(ws)
    assert got["counts"]["journal"] > 0
    left = b.db.query("select op, row from sync_changes where ws=?", (ws,))
    assert left and all(r["op"] == "D" and r["row"] is None for r in left)  # peers still delete it, with no data
    assert "borehole" not in json.dumps(b.db.query("select row from sync_changes"))  # (a tombstone's key may name an alias)
    assert b.db.one("select count(*) as c from view_changes where ws=?", (ws,))["c"] == 0


# ---------------------------------------------------------------- fix 5: the privacy notice
def test_the_owner_sets_the_notice_and_every_member_reads_it(people_farm):
    b, ids, owner = people_farm
    ws = ids["ws"]
    c = TestClient(create_app(b))
    n = c.get(f"/api/v1/workspaces/{ws}/privacy").json()  # this PC: the first owner
    assert n["is_owner"] and n["accepted_at"] is None and n["contact"] is None
    assert n["retention_text"] == "recordings until deleted, transcripts until deleted, activity log until deleted"
    assert n["cloud"] == {"claude": False, "deepgram": False, "allowed": False, "sync": None,
                          "available": {"claude": False, "deepgram": False}}  # the gate is off by default
    assert c.put(f"/api/v1/workspaces/{ws}/privacy", json={"retention": {"audio_days": 90}}).status_code == 400
    assert c.put(f"/api/v1/workspaces/{ws}/privacy", json={"contact": "x", "retention": {"audio_days": 0}}).status_code == 400
    n = c.put(f"/api/v1/workspaces/{ws}/privacy", json={"contact": "Dennis, 082 000 0000",
                                                         "retention": retention.RECOMMENDED}).json()
    assert n["accepted_at"] and n["my_ack_at"] and n["retention"] == retention.RECOMMENDED
    assert "recordings 90 days" in n["retention_text"]
    # an employee joins: reads the notice once, cannot change it
    _, got = _join(b, ids, owner)
    dev = {"Authorization": f"Bearer {got['token']}"}
    n = c.get(f"/api/v1/workspaces/{ws}/privacy", headers=dev).json()
    assert not n["is_owner"] and n["my_ack_at"] is None and n["contact"] == "Dennis, 082 000 0000"
    assert c.put(f"/api/v1/workspaces/{ws}/privacy", headers=dev, json={"contact": "me"}).status_code == 403
    assert c.post(f"/api/v1/workspaces/{ws}/retention/run", headers=dev).status_code == 403
    assert c.post(f"/api/v1/workspaces/{ws}/privacy/ack", headers=dev).json()["my_ack_at"]
    assert b.db.one("select privacy_ack_at from members where id=?", (got["member_id"],))["privacy_ack_at"]
    assert c.post(f"/api/v1/workspaces/{ws}/retention/run").status_code == 200


@pytest.fixture
def people_farm(farm):
    b, ids = farm
    ids = seed_roles(b, ids)
    return b, ids, as_(b, ids, "owner")


def test_owner_principal_is_used_for_this_pc(people_farm):  # the notice's "is_owner" for the desktop app
    b, ids, _ = people_farm
    assert owner_principal(b.db, ids["ws"]).level == 1
