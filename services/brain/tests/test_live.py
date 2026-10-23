# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Live: the brain with the local Gemma router and EmbeddingGemma retrieval (Ollama).   pytest -m live
Needs NC_BRAIN_LIVE_URL (e.g. http://127.0.0.1:11434) with notecad-gemma4-e2b and notecad-embeddinggemma."""
import os

import pytest

from farm import make_brain, seed_farm

pytestmark = pytest.mark.live
URL = os.environ.get("NC_BRAIN_LIVE_URL")
need = pytest.mark.skipif(not URL, reason="NC_BRAIN_LIVE_URL not set")


@pytest.fixture(scope="module")
def live():
    from notecad_companion.embed import OpenAICompatEmbedder
    from notecad_companion.llm import OpenAICompatLLM
    from notecad_brain.routers import LocalRouter, RouterChain, RulesRouter
    llm = OpenAICompatLLM(URL, os.environ.get("NC_BRAIN_LOCAL_MODEL", "notecad-gemma4-e2b"), timeout=120)
    emb = OpenAICompatEmbedder(URL, os.environ.get("NC_BRAIN_EMBED_MODEL", "notecad-embeddinggemma"))
    b = make_brain(routers=RouterChain([LocalRouter(llm), RulesRouter()]), embedder=emb)
    return b, seed_farm(b)


@need
def test_gemma_files_the_blueprint_note(live):
    b, ids = live
    r = b.register_capture(ids["ws"], text="Just finished planting the last two hundred hectares of beans, but the main "
                                           "water pump is leaking badly.", enqueue=False)
    out = b.process(r["capture_id"])
    assert all(e["router"].startswith("local") for e in out["events"]), out
    pump = b.graph.node(ids["pump"])
    assert pump["status"] in ("warning", "critical") and pump["open_alerts"] == 1


@need
def test_gemma_afrikaans_and_delegation(live):
    b, ids = live
    r = b.register_capture(ids["ws"], text="Vra Sipho om die trekker se olie te verander voor Vrydag", enqueue=False)
    b.process(r["capture_id"])
    t = [t for t in b.tasks(ids["ws"]) if t["capture_id"] == r["capture_id"]]
    assert t and t[0]["assignee_member"] == ids["sipho"], t
    assert t[0]["due_at"] is not None


@need
def test_gemma_knows_a_calf_is_cattle(live):
    b, ids = live
    r = b.register_capture(ids["ws"], text="A calf was born last night, healthy and strong", enqueue=False)
    b.process(r["capture_id"])
    note = b.db.one("select node_id from notes where capture_id=?", (r["capture_id"],))
    ok = {ids["cattle"]} | {c["id"] for c in b.graph.children(ids["cattle"])}  # Cattle, or a new calf node under it
    assert note and note["node_id"] in ok, b.graph.path_titles(note["node_id"]) if note else None


@need
def test_gemma_anchor_and_map_questions(live):
    """Phase 2 live: an unnamed note recorded on the Tractors node lands there, and the companion (same Gemma)
    answers 'which tractors need work?' and 'how much is planted?' from the map lines."""
    from notecad_companion.companion import Companion
    from notecad_companion.embed import HashEmbedder
    from notecad_companion.llm import OpenAICompatLLM
    from notecad_companion.store import Store
    b, ids = live
    r = b.register_capture(ids["ws"], text="The hydraulic hose is leaking, it needs replacing before Friday.",
                           enqueue=False, context_node_id=ids["tractors"])
    b.process(r["capture_id"])
    a = b.db.one("select node_id from alerts where capture_id=?", (r["capture_id"],))
    assert a and a["node_id"] in (ids["tractors"], ids["tractor_maint"]), a

    def work(focus=None):
        d = b.digest(ids["ws"], focus=focus)
        return d["map"]["lines"]
    llm = OpenAICompatLLM(URL, os.environ.get("NC_BRAIN_LOCAL_MODEL", "notecad-gemma4-e2b"), timeout=120)
    comp = Companion(Store(":memory:"), llm, HashEmbedder(256), open_work=work, llm_fact_extraction=False)
    reply = comp.chat("Which tractors need work?")["reply"].lower()
    assert "tractor" in reply and ("hydraulic" in reply or "hose" in reply or "leak" in reply), reply
    reply = comp.chat("How much of the beans is planted?")["reply"].lower().replace(",", "").replace(" ", "")
    assert "2800" in reply or "93" in reply, reply
