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
    assert c.get("/health").json()["provenance"]["pipeline"].startswith("notecad-companion")
    r = c.post("/v1/sam/chat", json={"text": "My name is Sam. Keep it short please."}).json()
    assert r["reply"] == "Sure." and r["learned"]["facts"][0]["key"] == "owner.name"
    assert c.post("/v1/sam/feedback", json={"interaction_id": r["interaction_id"], "rating": 1}).status_code == 200
    c.post("/v1/sam/observe", json={"text": "Borehole 2 pressure low", "node_path": "Water"})
    card = c.get("/v1/sam/card").json()
    assert card["facts"]["owner.name"]["value"] == "Sam" and card["memories"] >= 1
    assert "borehole" in c.get("/v1/sam/keyterms").json()["keyterms"]
    assert c.put("/v1/sam/facts", json={"key": "owner.location", "value": "Centurion"}).status_code == 200
    assert c.delete("/v1/sam/facts/owner.location").status_code == 200
    assert c.post("/v1/sam/train/export").json()["sft_examples"] == 1
    assert c.get("/v1/sam/export").json()["data"]["facts"]
    assert c.delete("/v1/sam").status_code == 200
    assert c.get("/v1/sam/card").json()["facts"] == {}


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
