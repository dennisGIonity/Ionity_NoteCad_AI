"""Live tests with the real models. Run:  pytest -m live
Needs NC_COMPANION_MODEL_PATH (Gemma 4 E2B GGUF) and NC_COMPANION_EMBED_MODEL_PATH (EmbeddingGemma GGUF)."""
import json
import os
import time

import pytest

pytestmark = pytest.mark.live
MODEL = os.environ.get("NC_COMPANION_MODEL_PATH")
EMBED = os.environ.get("NC_COMPANION_EMBED_MODEL_PATH")
need = pytest.mark.skipif(not (MODEL and EMBED), reason="real GGUF models not configured")


@pytest.fixture(scope="module")
def models():
    from notecad_companion.embed import LlamaEmbedder
    from notecad_companion.llm import LlamaCppLLM
    return LlamaCppLLM(MODEL, n_ctx=4096), LlamaEmbedder(EMBED, 256)


@need
def test_embeddinggemma_ranks_related_memory_first(models):
    from notecad_companion.embed import cosine
    _, emb = models
    q = emb.embed_query("is die hoofpomp nog stukkend?")  # Afrikaans query, English memory
    pump = emb.embed_doc("The main water pump is leaking at the flange.")
    party = emb.embed_doc("Mia's birthday party is on Saturday.")
    assert cosine(q, pump) > cosine(q, party)


@need
def test_companion_recalls_and_obeys_style(models):
    from notecad_companion.companion import Companion
    from notecad_companion.store import Store
    llm, emb = models
    c = Companion(Store(":memory:"), llm, emb, seed=3, max_reply_tokens=120)
    now = time.time()
    c.chat("My name is Sam. Remember that the vet, Dr Botha, comes on Thursday at 10.", now=now)
    c.chat("Keep it short please.", now=now + 60)
    out = c.chat("Who is coming on Thursday and at what time?", now=now + 120)
    assert "botha" in out["reply"].lower() and "10" in out["reply"]
    assert out["style"]["length"] == "short" or len(out["reply"].split()) < 60
    assert c.store.get_fact("owner.name")["value"] == "Sam"


@need
def test_offline_router_picks_the_owners_pump(models):
    from notecad_companion.companion import Companion
    from notecad_companion.store import Store
    llm, emb = models
    c = Companion(Store(":memory:"), llm, emb)
    out = c.route_offline("die groot pomp lek baie erg", [
        {"node_id": "n-pump", "path": "Infrastructure > Water > Main Water Pump", "kind": "asset",
         "aliases": ["die groot pomp"]},
        {"node_id": "n-beans", "path": "Operations > Crops > Beans", "kind": "field"}], "cap-live")
    first = out["actions"][0]
    assert first["type"] == "append_note" and first["node_id"] == "n-pump", json.dumps(out)
    assert any(a["type"] == "set_status" for a in out["actions"])
