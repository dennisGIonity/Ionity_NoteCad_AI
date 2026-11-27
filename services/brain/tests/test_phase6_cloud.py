# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Phase 6 cloud gap-fill: what running from a clone (Linux, CI, no models) needed. One test per change."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from farm import make_brain, seed_farm
from notecad_brain.api import create_app
from notecad_brain.config import Settings
from notecad_brain.stt import FixtureSTT, local_only, make_stt


def _settings(stt: str) -> SimpleNamespace:
    return SimpleNamespace(stt_engines=stt, deepgram_key=None, whisper_model="tiny", whisper_device="cpu",
                           whisper_compute="int8", whisper_dir=None, stt_languages="en,af")


def test_the_fixture_engine_runs_only_when_asked_for(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    assert "fixture" not in Settings().stt_engines.split(",")  # never part of the default chain
    assert make_stt(_settings("none")) is None
    assert isinstance(make_stt(_settings("fixture")), FixtureSTT)


def test_the_fixture_engine_stays_on_this_pc_and_reads_its_text(monkeypatch):
    monkeypatch.setenv("NC_BRAIN_STT_FIXTURE_TEXT", "Tractor 2 has a flat tyre")
    f = FixtureSTT()
    assert local_only(f) is f  # the cloud transfer gate keeps it
    t = f.transcribe(b"RIFF....", mime="audio/wav", lang_hint=None, keyterms=[])
    assert t.text == "Tractor 2 has a flat tyre" and t.engine == "fixture"


def test_a_voice_note_through_the_fixture_engine_keeps_its_recording(tmp_path):
    # the e2e "hold Space to talk" flow on a clone: the capture is applied and the recording can be played back
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}", audio_dir=str(tmp_path / "audio"),
                   stt=FixtureSTT("the main water pump is leaking badly"))
    ids = seed_farm(b)
    c = TestClient(create_app(b))
    r = c.post(f"/v1/workspaces/{ids['ws']}/captures/audio", content=b"OggS" + b"\0" * 2000,
               headers={"content-type": "audio/ogg"}).json()
    assert b.run_jobs() == 1
    s = c.get(f"/v1/captures/{r['capture_id']}").json()
    assert s["state"] == "applied" and s["text"] == "the main water pump is leaking badly"
    audio = c.get(f"/v1/captures/{r['capture_id']}/audio")
    assert audio.status_code == 200 and len(audio.content) > 1000
