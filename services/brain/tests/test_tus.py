# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Phase 5: resumable phone uploads (tus 1.0.0), LAN token rules and phone pairing."""
import base64
import time

from fastapi.testclient import TestClient

from farm import make_brain, seed_farm
from notecad_brain.api import create_app
from notecad_brain.common import uuid7
from notecad_brain.stt import Transcript

V = {"Tus-Resumable": "1.0.0"}
AUDIO = b"OggS" + bytes(range(256)) * 40  # 10 KB pretend recording


def meta(**kw) -> str:
    return ",".join(f"{k} {base64.b64encode(str(v).encode()).decode()}" for k, v in kw.items())


class FakeSTT:
    name = "fake"

    def transcribe(self, audio, *, mime, lang_hint, keyterms):
        assert audio == AUDIO and mime == "audio/ogg"
        return Transcript(text="needs new tyres before the season", language="en", confidence=0.9, engine="fake")


def setup(tmp_path, **settings):
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}", audio_dir=str(tmp_path / "audio"), stt=FakeSTT())
    for k, v in settings.items():
        setattr(b.settings, k, v)
    ids = seed_farm(b)
    return b, ids, TestClient(create_app(b))


def test_options_advertises_tus(tmp_path):
    _, ids, c = setup(tmp_path)
    r = c.options(f"/api/v1/workspaces/{ids['ws']}/uploads")
    assert r.status_code == 204 and r.headers["tus-version"] == "1.0.0"
    assert "creation" in r.headers["tus-extension"] and int(r.headers["tus-max-size"]) == 25 * 1024 * 1024


def test_upload_survives_a_dropped_connection_and_becomes_one_anchored_capture(tmp_path):
    b, ids, c = setup(tmp_path)
    cid = uuid7()
    base = f"/api/v1/workspaces/{ids['ws']}/uploads"
    r = c.post(base, headers={**V, "Upload-Length": str(len(AUDIO)),
                              "Upload-Metadata": meta(capture_id=cid, filetype="audio/ogg", filename="n.ogg",
                                                      context_node_id=ids["tractors"], source="android-bubble")})
    assert r.status_code == 201 and r.headers["location"].startswith("http")
    url = r.headers["location"].split("testserver")[1]
    oct_ = {**V, "Content-Type": "application/offset+octet-stream"}
    # the first 4 KB arrive, then the signal drops
    r = c.patch(url, headers={**oct_, "Upload-Offset": "0"}, content=AUDIO[:4096])
    assert r.status_code == 204 and r.headers["upload-offset"] == "4096" and "notecad-capture-id" not in r.headers
    # back in signal: ask where to continue
    h = c.head(url, headers=V)
    assert h.status_code == 200 and h.headers["upload-offset"] == "4096" and h.headers["upload-length"] == str(len(AUDIO))
    assert "capture_id" in h.headers["upload-metadata"] and h.headers["cache-control"] == "no-store"
    # a stale client that thinks it is at 0 is told the real offset
    r = c.patch(url, headers={**oct_, "Upload-Offset": "0"}, content=AUDIO)
    assert r.status_code == 409 and r.headers["upload-offset"] == "4096"
    r = c.patch(url, headers={**oct_, "Upload-Offset": "4096"}, content=AUDIO[4096:])
    assert r.status_code == 204 and r.headers["upload-offset"] == str(len(AUDIO))
    assert r.headers["notecad-capture-id"] == cid
    cap = b.db.one("select * from captures where id=?", (cid,))
    assert cap["state"] == "queued" and cap["source"] == "android-bubble" and cap["anchor_node_id"] == ids["tractors"]
    assert b.run_jobs() == 1
    assert b.capture_summary(cid)["state"] == "applied"
    assert b.db.one("select node_id from notes where capture_id=?", (cid,))["node_id"] == ids["tractors"]
    # the phone did not hear the answer and sends the whole recording again: still one capture
    r = c.post(base, headers={**oct_, "Upload-Length": str(len(AUDIO)), "Upload-Metadata": meta(capture_id=cid, filetype="audio/ogg")},
               content=AUDIO)
    assert r.status_code == 201 and r.headers["notecad-capture-id"] == cid
    assert b.db.one("select count(*) as c from captures where id=?", (cid,))["c"] == 1
    assert not list((tmp_path / "uploads").glob("*.part"))  # parts are cleaned once the capture has the audio


def test_protocol_errors(tmp_path):
    b, ids, c = setup(tmp_path)
    base = f"/api/v1/workspaces/{ids['ws']}/uploads"
    assert c.post(base, headers={"Upload-Length": "10"}).status_code == 412
    assert c.post(base, headers=V).status_code == 400
    assert c.post(base, headers={**V, "Upload-Length": str(26 * 1024 * 1024)}).status_code == 413
    assert c.post(base, headers={**V, "Upload-Length": "10", "Upload-Metadata": meta(context_node_id="nope")}).status_code == 400
    assert c.post(base, headers={**V, "Upload-Length": "10", "Upload-Metadata": "capture_id !!!"}).status_code == 400
    assert c.post("/api/v1/workspaces/nope/uploads", headers={**V, "Upload-Length": "10"}).status_code == 404
    url = c.post(base, headers={**V, "Upload-Length": "10"}).headers["location"].split("testserver")[1]
    assert c.patch(url, headers={**V, "Upload-Offset": "0", "Content-Type": "audio/ogg"}, content=b"x").status_code == 415
    assert c.patch(url, headers={**V, "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"},
                   content=b"x" * 11).status_code == 413
    assert c.head(f"{base}/0123abcd", headers=V).status_code == 404
    assert c.delete(url, headers=V).status_code == 204 and c.head(url, headers=V).status_code == 404
    # an upload left unfinished past its expiry is gone
    url = c.post(base, headers={**V, "Upload-Length": "10"}).headers["location"].split("testserver")[1]
    uid = url.rsplit("/", 1)[1]
    info = b.uploads.info(uid)
    info["expires"] = time.time() - 1
    b.uploads.save(info)
    assert c.head(url, headers=V).status_code == 410


def test_creation_with_upload_and_method_override(tmp_path):
    b, ids, c = setup(tmp_path)
    base = f"/api/v1/workspaces/{ids['ws']}/uploads"
    one = c.post(base, headers={**V, "Upload-Length": str(len(AUDIO)), "Content-Type": "application/offset+octet-stream",
                                "Upload-Metadata": meta(filetype="audio/ogg")}, content=AUDIO)
    assert one.status_code == 201 and one.headers["upload-offset"] == str(len(AUDIO)) and one.headers["notecad-capture-id"]
    url = c.post(base, headers={**V, "Upload-Length": str(len(AUDIO)), "Upload-Metadata": meta(filetype="audio/ogg")}).headers["location"].split("testserver")[1]
    r = c.post(url, headers={**V, "X-HTTP-Method-Override": "PATCH", "Upload-Offset": "0",
                             "Content-Type": "application/offset+octet-stream"}, content=AUDIO)
    assert r.status_code == 204 and r.headers["notecad-capture-id"]
    assert b.db.one("select count(*) as c from captures where workspace_id=?", (ids["ws"],))["c"] == 2


def test_phones_need_the_token_this_pc_does_not(tmp_path):
    b, ids, phone = setup(tmp_path, api_token="farm-secret")
    base = f"/api/v1/workspaces/{ids['ws']}/uploads"
    assert phone.post(base, headers={**V, "Upload-Length": "10"}).status_code == 401
    assert phone.post(base, headers={**V, "Upload-Length": "10", "Authorization": "Bearer farm-secret"}).status_code == 201
    assert phone.get(f"/api/v1/workspaces/{ids['ws']}/mindmap").status_code == 401
    desk = TestClient(create_app(b), client=("127.0.0.1", 50000))
    assert desk.get(f"/api/v1/workspaces/{ids['ws']}/mindmap").status_code == 200
    b.settings.trust_loopback = False
    assert TestClient(create_app(b), client=("127.0.0.1", 50001)).get(f"/api/v1/workspaces/{ids['ws']}/mindmap").status_code == 401


def test_pairing_only_on_this_pc(tmp_path):
    b, ids, phone = setup(tmp_path, api_token="farm-secret", bind_host="0.0.0.0")
    assert phone.get("/api/v1/pairing").status_code in (401, 403)
    desk = TestClient(create_app(b), client=("127.0.0.1", 50000))
    p = desk.get(f"/api/v1/pairing?ws={ids['ws']}").json()
    assert p["lan"] and p["token_set"] and p["workspace"] == ids["ws"]
    assert all(l.startswith("notecad://pair?u=http") and "t=farm-secret" in l for l in p["links"])
    b.settings.bind_host = "127.0.0.1"
    p = desk.get("/api/v1/pairing").json()
    assert not p["ready"] and "-Lan" in p["hint"]


def test_stray_bytes_after_a_crash_do_not_corrupt_the_resumed_audio(tmp_path):
    """Phase 6: the chunk was written but the brain died before saving the offset. The part file is longer than
    the recorded offset; the resumed PATCH must overwrite, not append after, the stray bytes."""
    b, ids, c = setup(tmp_path)
    cid = uuid7()
    base = f"/api/v1/workspaces/{ids['ws']}/uploads"
    url = c.post(base, headers={**V, "Upload-Length": str(len(AUDIO)),
                                "Upload-Metadata": meta(capture_id=cid, filetype="audio/ogg")}).headers["location"].split("testserver")[1]
    oct_ = {**V, "Content-Type": "application/offset+octet-stream"}
    assert c.patch(url, headers={**oct_, "Upload-Offset": "0"}, content=AUDIO[:4096]).status_code == 204
    part = next((tmp_path / "uploads").glob("*.part"))
    with part.open("ab") as f:
        f.write(b"\x00" * 1000)  # written, offset never saved
    assert c.head(url, headers=V).headers["upload-offset"] == "4096"
    assert c.patch(url, headers={**oct_, "Upload-Offset": "4096"}, content=AUDIO[4096:]).status_code == 204
    b.run_jobs()  # FakeSTT asserts the bytes are exactly the recording; a corrupt file fails the capture
    assert b.capture_summary(cid)["state"] in ("applied", "needs_review")
