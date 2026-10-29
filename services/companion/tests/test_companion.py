# Ionity Business Mind Map (IBMM) - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Unit tests: learning behaviour with a scripted model and the hashing embedder (no downloads needed)."""
import json
import random
import time

import numpy as np
import pytest

from notecad_companion.companion import Companion
from notecad_companion.embed import HashEmbedder, cosine
from notecad_companion.learner import DIMS
from notecad_companion.llm import ScriptedLLM, parse_json
from notecad_companion.persona import choose_style, style_confidence
from notecad_companion.store import Store
from notecad_companion.textutil import guess_language, redact
from notecad_companion import trainer

MON_9AM = time.mktime((2026, 10, 19, 9, 0, 0, 0, 0, -1))  # a Monday


def make(llm=None, seed=1):
    return Companion(Store(":memory:"), llm or ScriptedLLM(), HashEmbedder(256), seed=seed,
                     llm_fact_extraction=llm is not None)


# ------------------------------------------------------------------ text helpers
def test_language_guess():
    assert guess_language("Ek het vandag die skape gedip en die pomp lek nie meer nie") == "af"
    assert guess_language("I dipped the sheep today and the pump is fine") == "en"


def test_redaction_masks_id_and_card_but_not_normal_numbers():
    out = redact("My ID is 8001015009087 and card 4111 1111 1111 1111, we planted 3000 ha")
    assert "8001015009087" not in out and "4111" not in out
    assert "[id-number]" in out and "[card-number]" in out and "3000 ha" in out


def test_hash_embedder_similarity():
    e = HashEmbedder(256)
    a = e.embed_doc("the main water pump is leaking")
    b = e.embed_query("is the water pump still leaking?")
    c = e.embed_query("my daughter's birthday party")
    assert cosine(a, b) > cosine(a, c)


def test_parse_json_tolerates_fences():
    assert parse_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert parse_json("sure! {\"facts\": []} done") == {"facts": []}


# ------------------------------------------------------------------ facts
def test_rule_facts_english_and_afrikaans():
    c = make()
    c.chat("Hi, my name is Dennis and I live in Centurion. I'm a farmer.", now=MON_9AM)
    c.chat("Ons het 120 skape en my voorman is Sipho.", now=MON_9AM + 60)
    facts = {f["key"]: f["value"] for f in c.store.all_facts()}
    assert facts["owner.name"] == "Dennis"
    assert facts["owner.location"] == "Centurion"
    assert facts["owner.role"].lower() == "farmer"
    assert facts["owns.skape"] == 120
    assert facts["people.voorman"] == "Sipho"


def test_not_a_role():
    c = make()
    c.chat("I'm a bit tired today", now=MON_9AM)
    assert c.store.get_fact("owner.role") is None


def test_fact_confirmation_and_update_keeps_history():
    c = make()
    c.learner.put_fact("owns.cattle", 80, 0.7, "rule:chat")
    r = c.learner.put_fact("owns.cattle", 80, 0.7, "rule:chat")
    assert r["change"] == "confirmed" and c.store.get_fact("owns.cattle")["confidence"] > 0.9
    r = c.learner.put_fact("owns.cattle", 95, 0.99, "user")
    f = c.store.get_fact("owns.cattle")
    assert r["change"] == "updated" and f["value"] == 95 and f["history"][-1]["value"] == 80


def test_likes_and_dislikes_move_between_lists():
    c = make()
    c.chat("I really like rooibos tea", now=MON_9AM)
    c.chat("I don't like rooibos tea anymore", now=MON_9AM + 60)
    assert "rooibos tea" not in [x.lower() for x in (c.store.get_fact("likes") or {"value": []})["value"]]


def test_llm_fact_extraction_is_validated():
    def fn(msgs, schema):
        if schema and "facts" in json.dumps(schema):
            return json.dumps({"facts": [
                {"key": "work.farm.crop", "value": "beans", "confidence": 0.95},
                {"key": "BAD KEY", "value": "x", "confidence": 0.9},
                {"key": "owner.id_number", "value": "8001015009087", "confidence": 0.9}]})
        return "ok"
    c = make(ScriptedLLM(fn))
    c.chat("We mostly grow beans on the home farm these days", now=MON_9AM)
    keys = {f["key"]: f for f in c.store.all_facts()}
    assert keys["work.farm.crop"]["value"] == "beans"
    assert keys["work.farm.crop"]["confidence"] <= 0.8  # model-extracted facts are capped
    assert "owner.id_number" not in keys and "bad key" not in keys


# ------------------------------------------------------------------ memory
def test_explicit_remember_is_recalled_later():
    c = make()
    c.chat("Remember that the vet is coming on Thursday at 10", now=MON_9AM)
    for i in range(5):
        c.chat(f"Random chatter number {i} about the weather and rain", now=MON_9AM + 100 + i)
    out = c.chat("When is the vet coming?", now=MON_9AM + 3600)
    assert any("vet" in m["text"] for m in out["memories_used"])
    system = c.llm.calls[-1][0][0]["content"]
    assert "vet is coming on Thursday" in system


def test_memory_dedupe_and_redaction():
    c = make()
    c.remember("Main pump leaks at the flange", importance=0.4)
    c.remember("Main pump leaks at the flange", importance=0.9)
    mems = c.store.memories()
    assert len(mems) == 1 and mems[0]["importance"] == 0.9
    c.remember("my card is 4111 1111 1111 1111")
    assert all("4111" not in m["text"] for m in c.store.memories())


def test_observe_notes_feed_memory_vocab_and_keyterms():
    c = make()
    c.observe("Dipped the Dohne Merino ewes in the south paddock", node_path="Livestock > Sheep", ts=MON_9AM)
    c.observe("Dohne Merino rams moved to the south paddock", ts=MON_9AM + 600)
    kt = c.keyterms()
    assert "dohne" in kt and "merino" in kt and "paddock" in kt
    assert c.store.memories()[0]["text"].startswith("[Livestock > Sheep]")


# ------------------------------------------------------------------ behaviour learning
def test_explicit_style_instruction_wins_immediately():
    c = make()
    c.chat("Please keep it short and use bullet points", now=MON_9AM)
    st = choose_style(c.store, greedy=True)
    assert st["length"] == "short" and st["format"] == "bullets"


def test_language_preference_overrides_message_language():
    c = make()
    c.chat("Antwoord asseblief in Afrikaans", now=MON_9AM)
    out = c.chat("How many sheep do I have?", now=MON_9AM + 60)
    assert out["language"] == "af"
    assert "Reply in Afrikaans." in c.llm.calls[-1][0][0]["content"]


def test_thompson_sampling_converges_on_owner_preference():
    """Simulated owner who likes short, casual, prose answers. After ~60 rated replies the companion should
    pick that style nearly every time."""
    c = make(seed=7)
    rng = random.Random(3)
    liked = {"length": "short", "tone": "casual", "format": "prose"}
    for i in range(60):
        out = c.chat(f"question {i} about the farm", now=MON_9AM + i * 60)
        st = out["style"]
        hits = sum(st[d] == o for d, o in liked.items())
        rating = 1 if hits >= 2 and rng.random() < 0.9 else -1
        c.feedback(out["interaction_id"], rating=rating)
    picks = [choose_style(c.store, random.Random(s)) for s in range(200)]
    for dim, opt in liked.items():
        share = sum(p[dim] == opt for p in picks) / len(picks)
        assert share > 0.6, (dim, share, style_confidence(c.store)[dim])


def test_edit_teaches_length_and_format():
    c = make(ScriptedLLM(lambda m, s: "Here is a long answer. " * 20))
    out = c.chat("what's on today?", now=MON_9AM)
    before = style_confidence(c.store)["length"]["short"]
    r = c.feedback(out["interaction_id"], edited_reply="- dip sheep\n- fix pump")
    after = style_confidence(c.store)["length"]["short"]
    sig = {x["signal"] for x in r["changes"]}
    assert "edited_shorter" in sig and "edited_format" in sig
    assert after > before or out["style"]["length"] == "short"


def test_feedback_comment_is_learned():
    c = make()
    out = c.chat("hello", now=MON_9AM)
    c.feedback(out["interaction_id"], rating=-1, comment="too long, hou dit kort")
    assert choose_style(c.store, greedy=True)["length"] == "short"


def test_bad_feedback_values():
    c = make()
    out = c.chat("hello", now=MON_9AM)
    with pytest.raises(ValueError):
        c.feedback(out["interaction_id"], rating=5)
    with pytest.raises(KeyError):
        c.feedback("nope", rating=1)


# ------------------------------------------------------------------ rhythm
def test_weekday_habits_become_nudges():
    c = make()
    week = 7 * 86400
    for w in range(4):
        c.chat("Time to check the dipping tank and the borehole", now=MON_9AM + w * week)
    nudges = c.nudges(now=MON_9AM + 4 * week)
    assert any("dipping" in n or "borehole" in n for n in nudges)
    assert c.nudges(now=MON_9AM + 4 * week + 86400) == []  # Tuesday: nothing yet
    assert any("Mon" in h for h in c.card()["habits"])


# ------------------------------------------------------------------ consolidation + training data
def test_consolidation_merges_and_decays():
    c = make()
    old = MON_9AM - 90 * 86400
    c.store.add_memory("pump leak fixed with new seal", "episode", 0.06, c.embedder.embed_doc("pump leak fixed with new seal"),
                       c.embedder.name, "chat", old)
    c.store.add_memory("pump leak fixed with a new seal", "episode", 0.5, c.embedder.embed_doc("pump leak fixed with a new seal"),
                       c.embedder.name, "chat", MON_9AM)
    c.store.add_memory("call the bank about the loan", "explicit", 1.0, c.embedder.embed_doc("call the bank about the loan"),
                       c.embedder.name, "chat", old)
    stats = c.consolidate(now=MON_9AM + 86400)
    assert stats["merged"] == 1
    texts = [m["text"] for m in c.store.memories()]
    assert "call the bank about the loan" in texts  # explicit memories never decay away


def test_reembed_after_embedder_upgrade():
    c = make()
    c.remember("tractor service due in November", importance=0.6)
    c.embedder = HashEmbedder(128)
    c.embedder.name = "hash-v2"
    assert c.consolidate()["reembedded"] == 1


def test_training_export(tmp_path):
    c = make(ScriptedLLM(lambda m, s: "A long reply that the owner did not like at all."))
    a = c.chat("what do I do about the pump?", now=MON_9AM)
    b = c.chat("and the sheep?", now=MON_9AM + 60)
    c.feedback(a["interaction_id"], edited_reply="Call Sipho to fix the pump.")
    c.feedback(b["interaction_id"], rating=1)
    info = trainer.export(c.store, tmp_path)
    assert info["sft_examples"] == 2 and info["dpo_pairs"] == 1 and not info["ready_for_lora"]
    rows = [json.loads(l) for l in open(tmp_path / "dpo.jsonl", encoding="utf-8")]
    assert rows[0]["chosen"][0]["content"] == "Call Sipho to fix the pump."


# ------------------------------------------------------------------ offline router
def test_route_offline_maps_to_action_schema():
    def fn(msgs, schema):
        return json.dumps({"node_id": "n-pump", "kind": "problem", "severity": "critical",
                           "text": "Main water pump is leaking badly.", "task_title": "Repair main pump leak",
                           "confidence": 0.9})
    c = make(ScriptedLLM(fn))
    cands = [{"node_id": "n-pump", "path": "Infrastructure > Water > Main Water Pump", "kind": "asset"},
             {"node_id": "n-beans", "path": "Operations > Crops > Beans", "kind": "field"}]
    out = c.route_offline("the main water pump is leaking badly", cands, "cap-1")
    types = [a["type"] for a in out["actions"]]
    assert types == ["append_note", "set_status", "create_alert", "create_task"]
    assert out["actions"][1]["status"] == "critical" and out["actions"][3]["priority"] == "urgent"
    schema = c.llm.calls[-1][1]
    assert schema["properties"]["node_id"]["enum"] == ["n-pump", "n-beans", "none"]


def test_route_offline_low_confidence_asks_user():
    c = make(ScriptedLLM(lambda m, s: json.dumps({"node_id": "n-pump", "kind": "note", "severity": "none",
                                                  "text": "x", "task_title": "", "confidence": 0.3})))
    out = c.route_offline("something vague", [{"node_id": "n-pump", "path": "P"}], "cap-2")
    assert out["actions"][0]["type"] == "ask_user"


def test_no_model_mode_still_learns():
    c = Companion(Store(":memory:"), None, HashEmbedder(), llm_fact_extraction=False)
    out = c.chat("My name is Dennis. Remember that the gate code changed", now=MON_9AM)
    assert out["model"] == "none" and "Dennis" in out["reply"]
    assert c.store.get_fact("owner.name")["value"] == "Dennis"


def test_all_dims_have_prompt_text():
    from notecad_companion.persona import STYLE_TEXT
    for d, opts in DIMS.items():
        for o in opts:
            assert (d, o) in STYLE_TEXT


def test_several_owned_things_and_near_location():
    c = make()
    c.chat("I'm a farmer near Bronkhorstspruit and we have 120 sheep and 300 cattle.", now=MON_9AM)
    f = {x["key"]: x["value"] for x in c.store.all_facts()}
    assert f["owns.sheep"] == 120 and f["owns.cattle"] == 300
    assert f["owner.location"] == "near Bronkhorstspruit"


def test_model_key_names_are_normalised():
    from notecad_companion.learner import normalise_key
    assert normalise_key("owner_name") == "owner.name"
    assert normalise_key("number_of_cattle") == "owns.cattle"
    assert normalise_key("Occupation") == "owner.role"
    assert normalise_key("work.farm.crop") == "work.farm.crop"


# ------------------------------------------------------------------ regressions found in the live Gemma 4 E2B run
def test_model_guess_cannot_overwrite_a_count_or_a_stated_fact():
    def fn(msgs, schema):
        if schema:
            return json.dumps({"facts": [{"key": "owns.cattle", "value": "rams", "confidence": 0.8},
                                         {"key": "owner.location", "value": "the north camp", "confidence": 0.8}]})
        return "ok"
    c = make(ScriptedLLM(fn))
    c.learner.put_fact("owns.cattle", 300, 0.75, "rule:chat")
    c.learner.put_fact("owner.location", "near Bronkhorstspruit", 0.75, "rule:chat")
    c.chat("Moved the rams into the north camp this morning, all fine", now=MON_9AM)
    assert c.store.get_fact("owns.cattle")["value"] == 300
    assert c.store.get_fact("owner.location")["value"] == "near Bronkhorstspruit"
    c.chat("The rams are in the north camp again today, all fine", now=MON_9AM + 60)  # same guess twice
    assert c.store.get_fact("owner.location")["value"] == "the north camp"  # repeated guesses can win


def test_notes_do_not_run_model_fact_extraction():
    llm = ScriptedLLM(lambda m, s: json.dumps({"facts": [{"key": "routine.dipping", "value": "day again",
                                                          "confidence": 0.9}]}))
    c = make(llm)
    c.observe("Dipping day again, the rams in the north camp.", ts=MON_9AM)
    assert c.store.get_fact("routine.dipping") is None and llm.calls == []


def test_explicit_memories_stay_in_view():
    c = make()
    c.chat("Remember that the vet comes on Thursday at 10", now=MON_9AM)
    out = c.chat("What do I still need to do this week?", now=MON_9AM + 86400)
    assert any("vet" in m["text"] for m in out["memories_used"])


def test_steps_and_long_explanations():
    c = make()
    c.chat("I don't like long explanations. Just give me the steps.", now=MON_9AM)
    st = choose_style(c.store, greedy=True)
    assert st["length"] == "short" and st["format"] == "bullets"


def test_vet_is_filed_as_vet_not_manager():
    llm = ScriptedLLM(lambda m, s: json.dumps({"facts": [{"key": "people.manager", "value": "Dr Botha", "confidence": 0.8}]})
                      if s else "ok")
    c = make(llm)
    c.chat("Remember that the vet, Dr Botha, comes on Thursday at 10 for the ewes.", now=MON_9AM)
    assert c.store.get_fact("people.vet")["value"] == "Dr Botha"
    assert c.store.get_fact("people.manager") is None
    assert c.keyterms()[0] in ("Dr Botha",)


def test_keyterms_strip_place_prefix_and_fillers():
    c = make()
    c.chat("I'm a farmer near Bronkhorstspruit", now=MON_9AM)
    c.observe("Dipping again this morning, pressure low", ts=MON_9AM)
    kt = c.keyterms()
    assert "Bronkhorstspruit" in kt and "near Bronkhorstspruit" not in kt
    assert "again" not in kt and "morning" not in kt and "dipping" in kt


def test_openai_compatible_embedder_uses_task_prompts_and_truncates():
    import httpx
    from notecad_companion.embed import OpenAICompatEmbedder
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body["input"])
        vec = [float(len(body["input"]) % 7 + i % 3) for i in range(768)]
        return httpx.Response(200, json={"data": [{"embedding": vec}]})

    e = OpenAICompatEmbedder("http://local", dims=256, transport=httpx.MockTransport(handler))
    q = e.embed_query("is die pomp reg?")
    d = e.embed_doc("pump fixed")
    assert q.shape == (256,) and abs(float(np.linalg.norm(d)) - 1.0) < 1e-5
    assert seen[0].startswith("task: search result | query:") and seen[1].startswith("title: none | text:")
    assert e.name == "embeddinggemma-300m"


def test_openai_llm_turns_thinking_off_and_sends_schema():
    import httpx
    from notecad_companion.llm import OpenAICompatLLM
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"node_id\": \"n-pump\"}"}}]})

    llm = OpenAICompatLLM("http://local", "m", transport=httpx.MockTransport(handler))
    out = llm.chat([{"role": "user", "content": "x"}], schema={"type": "object"})
    assert out == "{\"node_id\": \"n-pump\"}"
    assert bodies[0]["reasoning_effort"] == "none"
    assert bodies[0]["response_format"]["type"] == "json_schema"


def test_open_work_from_the_brain_reaches_the_prompt():
    import httpx
    from notecad_companion.api import brain_digest

    def handler(req):
        assert req.url.path == "/v1/workspaces/ws1/digest"
        return httpx.Response(200, json={"alerts": [{"severity": "critical", "title": "Main water pump leaking",
                                                      "path": "Infrastructure > Water > Main Water Pump"}],
                                         "tasks": [{"priority": "high", "title": "Fix the north fence", "path": "Fencing",
                                                    "assignee_name": "Sipho Dlamini", "due_at": "2026-10-20T15:00:00+00:00"}]})
    fetch = brain_digest("http://brain", "ws1", transport=httpx.MockTransport(handler))
    c = Companion(Store(":memory:"), ScriptedLLM(), HashEmbedder(256), open_work=fetch, llm_fact_extraction=False)
    c.chat("What do I still need to do this week?", now=MON_9AM)
    system = c.llm.calls[-1][0][0]["content"]
    assert "ALERT (critical) Main water pump leaking" in system
    assert "TASK (high) Fix the north fence - Fencing - Sipho Dlamini, due 2026-10-20 15:00 UTC" in system


def test_brain_down_does_not_break_chat():
    def boom():
        raise RuntimeError("brain offline")
    c = Companion(Store(":memory:"), ScriptedLLM(), HashEmbedder(256), open_work=boom, llm_fact_extraction=False)
    assert c.chat("hello", now=MON_9AM)["reply"] == "Noted."


def test_map_lines_and_focus_from_the_brain_reach_the_prompt():
    import httpx
    from notecad_companion.api import brain_digest
    asked = []

    def handler(req):
        asked.append(req.url.params.get("focus"))
        return httpx.Response(200, json={
            "alerts": [], "tasks": [],
            "map": {"lines": ["NEEDS WORK Operations > Vehicles > Tractors: warning, alert: hydraulic hose leaking",
                              "PROGRESS Operations > Crops > South Block: 2800 of 3000 ha planted (93.3%)"]},
            "focus": {"path": "Operations > Crops > South Block", "display_status": "info",
                      "progress": {"pct": 93.3, "done": 2800, "total": 3000, "unit": "ha", "verb": "planted"},
                      "tasks": ["Finish the last 200 ha"], "alerts": [], "children": [],
                      "recent_notes": [{"body": "Planted 400 ha today."}]}})
    fetch = brain_digest("http://brain", "ws1", transport=httpx.MockTransport(handler))
    c = Companion(Store(":memory:"), ScriptedLLM(), HashEmbedder(256), open_work=fetch, llm_fact_extraction=False)
    c.chat("How much of the South block is planted?", now=MON_9AM, context_node_id="n-south")
    system = c.llm.calls[-1][0][0]["content"]
    assert asked == ["n-south"]
    assert "PROGRESS Operations > Crops > South Block: 2800 of 3000 ha planted (93.3%)" in system
    assert "NEEDS WORK Operations > Vehicles > Tractors" in system
    assert ("OPEN ON SCREEN NOW ('this', 'hier' means it): Operations > Crops > South Block - status info; "
            "2800 of 3000 ha planted (93.3%); open tasks: Finish the last 200 ha; latest notes: Planted 400 ha today.") in system
    c.chat("And what about the tractors?", now=MON_9AM)  # no node open: no focus asked for
    assert asked[-1] is None


# ------------------------------------------------------------------ Phase 6 regressions (ADR 0013)
def test_route_offline_survives_a_list_or_a_word_for_confidence():
    for reply in ('[{"node_id": "n-pump"}]', '{"node_id": "n-pump", "kind": "note", "confidence": "high"}'):
        c = make(ScriptedLLM(lambda m, s, r=reply: r))
        out = c.route_offline("pump", [{"node_id": "n-pump", "path": "P"}], "cap-3")
        assert out["actions"][0]["type"] == "ask_user"


def test_brain_digest_sends_the_token_and_reports_a_refusal():
    import httpx
    from notecad_companion.api import brain_digest
    seen = []

    def handler(req):
        seen.append(req.headers.get("authorization"))
        return httpx.Response(401, json={"detail": "missing or wrong token"})
    fetch = brain_digest("http://brain", "ws1", transport=httpx.MockTransport(handler), token="s3cret")
    with pytest.raises(httpx.HTTPStatusError):
        fetch()
    assert seen == ["Bearer s3cret"]


def test_owners_are_not_queued_behind_each_other_on_ollama(tmp_path):
    import contextlib
    from notecad_companion.api import Registry
    from notecad_companion.config import Settings
    s = Settings()
    s.data_dir = str(tmp_path)
    reg = Registry(s, ScriptedLLM(), HashEmbedder(64))  # not an in-process llama.cpp model
    assert isinstance(reg.model_lock, contextlib.nullcontext)
    a, b = reg.get("owner-a"), reg.get("owner-b")
    with reg.using(a):
        assert b.lock.acquire(blocking=False)  # owner B is free while A is busy
        b.lock.release()
