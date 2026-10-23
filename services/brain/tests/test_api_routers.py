# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""API flow, speech-to-text chain, Claude / local routers (mocked transports) and the companion hand-off."""
import asyncio
import threading
import json

import httpx
from fastapi.testclient import TestClient

from farm import make_brain, seed_farm
from notecad_brain.api import create_app
from notecad_brain.events import Broker
from notecad_brain.pipeline import CompanionLink
from notecad_brain.routers import ClaudeRouter, LocalRouter, RouteContext, RouterChain, RulesRouter
from notecad_brain.stt import ChainSTT, DeepgramSTT, STTError, Transcript


def test_api_end_to_end(tmp_path):
    b = make_brain(f"sqlite:///{tmp_path/'brain.db'}", audio_dir=str(tmp_path / "audio"))
    c = TestClient(create_app(b))
    assert c.get("/health").json()["provenance"]["policy"] == "986 AED"
    ws = c.post("/v1/workspaces", json={"name": "Highveld Farm", "owner_name": "Dennis"}).json()
    w = ws["id"]
    ob = c.post(f"/v1/workspaces/{w}/onboard", json={"answer": "Ek boer met skape, beeste en bone naby Bronkhorstspruit"}).json()
    assert ob["created"] > 5
    tree = c.get(f"/v1/workspaces/{w}/tree").json()
    water = next(x for x in tree["children"] if x["title"] == "Infrastructure")["children"][0]
    pump = c.post(f"/v1/workspaces/{w}/nodes", json={"parent_id": water["id"], "title": "Main Water Pump", "kind": "asset",
                                                    "aliases": ["die groot pomp"]}).json()["id"]
    sipho = c.post(f"/v1/workspaces/{w}/members", json={"display_name": "Sipho"}).json()["id"]
    out = c.post(f"/v1/workspaces/{w}/captures", json={"text": "Die groot pomp lek baie erg. Vra Sipho om dit môre reg te maak."}).json()
    assert out["state"] == "applied", out
    node = c.get(f"/v1/nodes/{pump}").json()
    assert node["status"] == "critical" and node["open_alerts"] == 1 and node["notes"]
    tasks = c.get(f"/v1/workspaces/{w}/tasks").json()
    assert any(t["assignee_member"] == sipho for t in tasks)
    assert c.get(f"/v1/workspaces/{w}/notifications", params={"member": sipho}).json()
    assert c.get(f"/v1/workspaces/{w}/digest").json()["alerts"]
    assert "Main Water Pump" in c.get(f"/v1/workspaces/{w}/keyterms").json()["keyterms"]
    # undo through the API
    assert c.post(f"/v1/captures/{out['capture_id']}/undo").json()["reverted"] > 0
    assert c.get(f"/v1/nodes/{pump}").json()["status"] == "ok"
    # queued capture + worker
    q = c.post(f"/v1/workspaces/{w}/captures", json={"text": "Die skape is gedip", "wait": False}).json()
    assert q["state"] == "queued" and b.run_jobs() == 1
    assert c.get(f"/v1/captures/{q['capture_id']}").json()["state"] == "applied"
    # rename, move, alias
    p = c.patch(f"/v1/nodes/{pump}", json={"title": "Hoofpomp", "add_aliases": ["boorgat pomp"]}).json()
    assert p["title"] == "Hoofpomp" and "boorgat pomp" in p["aliases"]
    assert c.get("/v1/nodes/nope").status_code == 404


def test_api_audio_capture_with_stt(tmp_path):
    class FakeSTT:
        name = "fake"

        def transcribe(self, audio, *, mime, lang_hint, keyterms):
            assert audio == b"OggS..." and "Main Water Pump" in keyterms
            return Transcript(text="the main water pump is leaking badly", language="en", confidence=0.93, engine="fake")
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}", audio_dir=str(tmp_path / "audio"), stt=FakeSTT())
    ids = seed_farm(b)
    c = TestClient(create_app(b))
    r = c.post(f"/v1/workspaces/{ids['ws']}/captures/audio", content=b"OggS...", headers={"content-type": "audio/ogg"}).json()
    assert r["state"] == "queued" and b.run_jobs() == 1
    s = c.get(f"/v1/captures/{r['capture_id']}").json()
    assert s["state"] == "applied" and s["text"] == "the main water pump is leaking badly"
    assert (tmp_path / "audio" / ids["ws"]).exists()


def test_audio_without_stt_fails_clearly(tmp_path):
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}", audio_dir=str(tmp_path / "audio"))
    ids = seed_farm(b)
    r = b.register_capture(ids["ws"], audio=b"x", mime="audio/ogg")
    b.run_jobs()
    s = b.capture_summary(r["capture_id"])
    assert s["state"] == "failed" and "speech-to-text" in s["error"]


def test_token_required(tmp_path):
    b = make_brain()
    b.settings.api_token = "s3cret"
    c = TestClient(create_app(b))
    assert c.post("/v1/workspaces", json={"name": "x"}).status_code == 401
    assert c.post("/v1/workspaces", json={"name": "x"}, headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_stt_chain_falls_back_and_prefers_whisper_for_afrikaans():
    calls = []

    class E:
        def __init__(self, name, text, conf, fail=False):
            self.name, self.text, self.conf, self.fail = name, text, conf, fail

        def transcribe(self, audio, *, mime, lang_hint, keyterms):
            calls.append(self.name)
            if self.fail:
                raise RuntimeError("offline")
            return Transcript(text=self.text, confidence=self.conf, engine=self.name)
    chain = ChainSTT([E("deepgram", "low", 0.5), E("faster-whisper", "good", 0.9)])
    assert chain.transcribe(b"", mime="audio/ogg", lang_hint="en", keyterms=[]).text == "good"
    calls.clear()
    chain.transcribe(b"", mime="audio/ogg", lang_hint="af-ZA", keyterms=[])
    assert calls[0] == "faster-whisper"
    try:
        ChainSTT([E("a", "", 0, True)]).transcribe(b"", mime="", lang_hint=None, keyterms=[])
        assert False
    except STTError:
        pass


def test_deepgram_request_carries_keyterms():
    seen = {}

    def handler(req: httpx.Request):
        seen["params"] = req.url.params.get_list("keyterm")
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"results": {"channels": [{"alternatives": [
            {"transcript": "main pump leaking", "confidence": 0.95, "words": [{"word": "main", "start": 0, "end": 0.3,
                                                                              "confidence": 0.99}]}]}]}})
    t = DeepgramSTT("k", transport=httpx.MockTransport(handler)).transcribe(b"a", mime="audio/ogg", lang_hint="en-ZA",
                                                                             keyterms=["Main Water Pump", "Dohne Merino"])
    assert t.text == "main pump leaking" and seen["params"] == ["Main Water Pump", "Dohne Merino"]
    assert seen["auth"] == "Token k"


def _ctx(b, ids, event):
    from datetime import datetime, timezone
    return RouteContext(capture_id="c1", event_index=0, event=event, transcript=event,
                        captured_at=datetime(2026, 10, 19, 6, tzinfo=timezone.utc), lang="en",
                        candidates=b.retriever.candidates(ids["ws"], event),
                        spine=[{"node_id": n["id"], "path": b.graph.path_titles(n["id"]), "kind": n["kind"]}
                               for n in b.graph.spine(ids["ws"])])


def test_claude_router_forced_tool_call():
    b = make_brain()
    ids = seed_farm(b)
    sent = {}

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        sent.update(body)
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "apply_capture_actions", "input": {
            "capture_id": "x", "event_index": 9, "summary": "Pump leak",
            "actions": [{"type": "append_note", "node_id": ids["pump"], "text": "Main water pump is leaking badly.",
                         "confidence": 0.95, "evidence": "leaking badly"}]}}]})
    r = ClaudeRouter("claude-sonnet-5-5", api_key="k", transport=httpx.MockTransport(handler))
    out = r.route(_ctx(b, ids, "the main water pump is leaking badly"))
    assert out["capture_id"] == "c1" and out["event_index"] == 0  # ids come from us, not the model
    assert sent["tool_choice"] == {"type": "tool", "name": "apply_capture_actions"}
    assert "<candidates>" in sent["messages"][0]["content"] and "data from a voice note" in sent["system"]


def test_local_router_maps_flat_answer_to_actions():
    from notecad_companion.llm import ScriptedLLM
    b = make_brain()
    ids = seed_farm(b)

    def fn(msgs, schema):
        assert ids["pump"] in schema["properties"]["node_id"]["enum"]
        return json.dumps({"node_id": ids["pump"], "kind": "problem", "severity": "critical",
                           "note": "Main water pump is leaking badly.", "task_title": "Repair main pump leak",
                           "assignee": "Sipho", "place_node_id": "none", "new_item_title": "", "confidence": 0.9})
    out = LocalRouter(ScriptedLLM(fn)).route(_ctx(b, ids, "the main water pump is leaking badly, Sipho must fix it"))
    types = [a["type"] for a in out["actions"]]
    assert types == ["append_note", "set_status", "create_alert", "create_task"]
    assert out["actions"][3]["assignee_hint"] == "Sipho" and out["actions"][3]["priority"] == "urgent"


def test_router_chain_falls_through():
    class Broken:
        name = "claude"

        def route(self, ctx):
            raise httpx.ConnectError("offline")
    b = make_brain(routers=RouterChain([Broken(), RulesRouter()]))
    ids = seed_farm(b)
    r = b.register_capture(ids["ws"], text="the main water pump is leaking badly", enqueue=False)
    b.process(r["capture_id"])
    log = json.loads(b.db.one("select provenance from action_log limit 1")["provenance"])
    assert log["router"] == "rules" and "offline" in log["fallbacks"][0]
    assert b.capture_summary(r["capture_id"])["router"] == "rules"


def test_companion_receives_applied_notes():
    got = []

    def handler(req: httpx.Request):
        if req.method == "POST":
            got.append(json.loads(req.content))
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"keyterms": ["Dohne Merino"]})
    link = CompanionLink("http://companion", transport=httpx.MockTransport(handler))
    b = make_brain(companion=link)
    ids = seed_farm(b)
    r = b.register_capture(ids["ws"], text="the main water pump is leaking badly", enqueue=False)
    b.process(r["capture_id"])
    assert got and got[0]["node_path"] == "Infrastructure > Water > Main Water Pump"
    assert "Dohne Merino" in b.keyterms(ids["ws"])


def test_broker_delivers_to_subscribers():
    async def run():
        br = Broker()
        q = br.subscribe("w1")
        other = br.subscribe("w2")
        br.publish("w1", "node", {"node_id": "n", "status": "critical"})
        await asyncio.sleep(0)
        msg = await asyncio.wait_for(q.get(), 1)
        assert msg["status"] == "critical" and other.empty()
        assert Broker.sse(msg).startswith(f"id: {msg['id']}\nevent: node\ndata: ")
        assert br.since("w1", 0) == [msg] and br.since("w1", msg["id"]) == []
    asyncio.run(run())


def test_local_router_guards_pronoun_and_invented_assignee():
    """Found on the desktop with Gemma 4: 'dit' filed on Sheep, and the owner's own name put on a task."""
    from notecad_companion.llm import ScriptedLLM
    b0 = make_brain()
    ids = seed_farm(b0)

    def fn(msgs, schema):
        user = msgs[-1]["content"]
        if "EVENT: Die groot pomp" in user:
            return json.dumps({"node_id": ids["pump"], "kind": "problem", "severity": "critical", "note": "Pump leaks badly.",
                               "task_title": "Fix pump", "assignee": "Dennis", "place_node_id": "none",
                               "new_item_title": "", "confidence": 0.9})
        return json.dumps({"node_id": ids["sheep"], "kind": "todo", "severity": "none", "note": "Sipho to fix it tomorrow.",
                           "task_title": "Fix it", "assignee": "Sipho", "place_node_id": "none", "new_item_title": "",
                           "confidence": 0.9})
    b = make_brain(routers=RouterChain([LocalRouter(ScriptedLLM(fn)), RulesRouter()]))
    ids = seed_farm(b)
    r = b.register_capture(ids["ws"], text="Die groot pomp lek baie erg. Vra Sipho om dit môre reg te maak.", enqueue=False)
    b.process(r["capture_id"])
    tasks = {t["title"]: t for t in b.tasks(ids["ws"])}
    assert tasks["Fix pump"]["assignee_hint"] is None and tasks["Fix pump"]["assignee_member"] is None
    sipho_task = next(t for t in tasks.values() if t["assignee_member"] == ids["sipho"])
    assert sipho_task["node_id"] == ids["pump"]
    assert sipho_task["title"].startswith("Vra Sipho om dit")  # model wording about sheep was dropped


def test_local_router_drops_task_title_that_owner_never_said():
    """Gemma 4 once turned 'Vra Sipho om dit môre reg te maak' into the task 'Make rain'."""
    from notecad_companion.llm import ScriptedLLM
    b = make_brain()
    ids = seed_farm(b)
    llm = ScriptedLLM(lambda m, s: json.dumps({"node_id": ids["pump"], "kind": "todo", "severity": "none",
                                                "note": "Sipho to repair it tomorrow.", "task_title": "Make rain",
                                                "assignee": "Sipho", "place_node_id": "none", "new_item_title": "",
                                                "confidence": 0.9}))
    out = LocalRouter(llm).route(_ctx(b, ids, "Vra Sipho om die hoofpomp môre reg te maak"))
    task = next(a for a in out["actions"] if a["type"] == "create_task")
    assert task["title"] != "Make rain" and "hoofpomp" in task["title"]


def test_onboarding_keeps_owner_spelling_and_places_crops():
    from notecad_companion.llm import ScriptedLLM
    from notecad_brain.onboarding import propose
    model = {"persona": "boer", "branches": [
        {"title": "Masjiene", "kind": "category", "children": [{"title": "hoelpomp", "kind": "asset"}]},
        {"title": "Grond", "kind": "category", "children": [{"title": "3000 hektaar", "kind": "asset"},
                                                            {"title": "bone", "kind": "field"}]}]}
    sp = propose("Ons het 3000 hektaar bone en 'n hoofpomp by die boorgat.", ScriptedLLM(lambda m, s: json.dumps(model)))
    flat = {}

    def walk(ns, parent=None):
        for n in ns:
            flat[n["title"]] = parent
            walk(n.get("children") or [], n["title"])
    walk(sp["branches"])
    assert "hoofpomp" in flat and flat["hoofpomp"] == "Water"
    assert "3000 hektaar" not in flat
    assert "bone" not in flat or flat["bone"] in ("Crops", "Fields")


def test_whisper_falls_back_to_cpu_when_cuda_libraries_are_missing(monkeypatch):
    from notecad_brain.stt import WhisperSTT
    w = WhisperSTT("tiny", device="auto")
    calls = []

    class Seg:
        text, avg_logprob = " field south 704", -0.1

    class Info:
        language = "en"

    def run(audio, lang, prompt):
        calls.append(w.device)
        if w.device != "cpu":
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return [Seg()], Info()
    monkeypatch.setattr(w, "_run", run)
    t = w.transcribe(b"x", mime="audio/webm", lang_hint=None, keyterms=[])
    assert calls == ["auto", "cpu"] and w.compute_type == "int8" and t.text == "field south 704"


def test_stt_is_warmed_at_startup(tmp_path):
    warmed = threading.Event()

    class SlowSTT:
        name = "fake"

        def warm(self):
            warmed.set()
    b = make_brain(f"sqlite:///{tmp_path/'b.db'}", stt=SlowSTT())
    b.settings.worker = True
    with TestClient(create_app(b)):
        assert warmed.wait(5)
