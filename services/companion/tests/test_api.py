# Ionity Business Mind Map (IBMM) - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
from fastapi.testclient import TestClient

from notecad_companion.api import create_app
from notecad_companion.config import Settings
from notecad_companion.embed import HashEmbedder
from notecad_companion.llm import ScriptedLLM


def client(tmp_path, token=None):
    s = Settings()
    s.data_dir, s.api_token, s.llm_fact_extraction = tmp_path, token, False
    return TestClient(create_app(s, ScriptedLLM(lambda m, sc: "Sure."), HashEmbedder()))


def test_full_flow(tmp_path):
    c = client(tmp_path)
    assert c.get("/health").json()["provenance"]["policy"] == "986 AED"
    r = c.post("/v1/dennis/chat", json={"text": "My name is Dennis. Keep it short please."}).json()
    assert r["reply"] == "Sure." and r["learned"]["facts"][0]["key"] == "owner.name"
    assert c.post("/v1/dennis/feedback", json={"interaction_id": r["interaction_id"], "rating": 1}).status_code == 200
    c.post("/v1/dennis/observe", json={"text": "Borehole 2 pressure low", "node_path": "Water"})
    card = c.get("/v1/dennis/card").json()
    assert card["facts"]["owner.name"]["value"] == "Dennis" and card["memories"] >= 1
    assert "borehole" in c.get("/v1/dennis/keyterms").json()["keyterms"]
    assert c.put("/v1/dennis/facts", json={"key": "owner.location", "value": "Centurion"}).status_code == 200
    assert c.delete("/v1/dennis/facts/owner.location").status_code == 200
    assert c.post("/v1/dennis/train/export").json()["sft_examples"] == 1
    assert c.get("/v1/dennis/export").json()["data"]["facts"]
    assert c.delete("/v1/dennis").status_code == 200
    assert c.get("/v1/dennis/card").json()["facts"] == {}


def test_owners_are_isolated(tmp_path):
    c = client(tmp_path)
    c.post("/v1/alice/chat", json={"text": "My name is Alice"})
    c.post("/v1/bob/chat", json={"text": "My name is Bob"})
    assert c.get("/v1/alice/card").json()["facts"]["owner.name"]["value"] == "Alice"
    assert c.get("/v1/bob/card").json()["facts"]["owner.name"]["value"] == "Bob"
    assert c.get("/v1/../etc/card").status_code in (400, 404)


def test_token_required_when_set(tmp_path):
    c = client(tmp_path, token="s3cret")
    assert c.post("/v1/x/chat", json={"text": "hi"}).status_code == 401
    assert c.post("/v1/x/chat", json={"text": "hi"}, headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_a_member_has_their_own_memory(tmp_path):
    """ADR 0014: the brain asks for a member other than the owner (as_member); they get a store of their own."""
    c = client(tmp_path)
    c.post("/v1/farm/chat", json={"text": "My name is Dennis"})
    c.post("/v1/farm/chat", json={"text": "My name is Thandi", "as_member": "m-thandi"})
    assert c.get("/v1/farm/card").json()["facts"]["owner.name"]["value"] == "Dennis"
    assert (tmp_path / "farm~m-thandi.sqlite").exists()
    assert c.post("/v1/farm/chat", json={"text": "hi", "as_member": "../x"}).status_code == 422


def test_brain_digest_asks_as_the_member():
    import httpx

    from notecad_companion.api import brain_digest
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        return httpx.Response(200, json={"tasks": [], "alerts": [], "map": {"lines": []}})
    brain_digest("http://brain", "farm", transport=httpx.MockTransport(handler), as_member="m-thandi")()
    assert seen == [{"as_member": "m-thandi"}]


def test_forget_reaches_the_companion_memory(tmp_path):
    """POPIA: the brain's retention period and per-person erasure also clear what the companion learned."""
    import time
    c = client(tmp_path)
    c.post("/v1/farm/observe", json={"text": "Thabo was off sick on Monday", "node_path": "Staff"})
    c.post("/v1/farm/observe", json={"text": "Borehole 2 pressure low", "node_path": "Water"})
    c.post("/v1/farm/chat", json={"text": "Is Thabo back?"})
    c.post("/v1/farm/observe", json={"text": "Thandi fixed the gate", "as_member": "m-thandi"})
    got = c.post("/v1/farm/forget", json={"terms": ["Thabo"]}).json()
    assert got["memories"] >= 1 and got["interactions"] == 1  # the note, and the chat about him
    data = c.get("/v1/farm/export").json()["data"]
    assert "thabo" not in str(data).lower() and "Borehole" in str(data["memories"])
    assert c.post("/v1/farm/forget", json={"before": time.time() + 1}).json()["memories"] >= 1
    assert c.get("/v1/farm/export").json()["data"]["memories"] == []
    # a member's own store is reached with as_member
    assert c.post("/v1/farm/forget", json={"terms": ["gate"], "as_member": "m-thandi"}).json()["memories"] == 1
