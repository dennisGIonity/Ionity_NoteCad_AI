# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Phase 6: regressions found in the full pass (ADR 0013). One test per bug."""
from datetime import datetime, timezone

from notecad_brain.routers import RouteContext, RulesRouter


def _ctx(event: str, candidates: list[dict], **kw) -> RouteContext:
    return RouteContext(capture_id="c1", event_index=0, event=event, transcript=event,
                        captured_at=datetime(2026, 10, 28, 8, tzinfo=timezone.utc), lang="en",
                        candidates=candidates, spine=[], **kw)


def _cand(nid, path, kind, score, aliases=(), parent=None):
    return {"node_id": nid, "path": path, "title": path.split(" > ")[-1], "kind": kind, "score": score,
            "aliases": list(aliases), "parent_id": parent}


def test_rules_prefer_the_named_child_over_its_one_word_parent():
    """Showcase note 3 with EmbeddingGemma scores: "Water" (alias water) out-scored its child "North Borehole Pump"
    by 0.02 and the task landed on the category. The child is named in the note, so it wins."""
    cands = [
        _cand("pump", "Water > North Borehole Pump", "asset", 0.918,
              ["noord boorgat", "noord pomp", "north borehole", "north borehole pump"], "water"),
        _cand("water", "Water", "category", 0.885, ["boorgate", "boreholes", "water"]),
        _cand("sipho", "Admin > Staff > Sipho", "person", 0.885, ["foreman", "sipho dlamini", "voorman"], "staff"),
        _cand("north", "Fields > North Block", "group", 0.818, ["noord", "north"], "fields"),
    ]
    out = RulesRouter().route(_ctx("Ask Sipho to check the water pump on the North borehole", cands,
                                   people=[{"name": "Sipho Dlamini"}]))
    task = next(a for a in out["actions"] if a["type"] == "create_task")
    assert task["node_id"] == "pump" and task["assignee_hint"] == "Sipho"


def test_rules_keep_the_parent_when_no_child_is_named():
    cands = [_cand("water", "Water", "category", 0.9, ["water"]),
             _cand("pump", "Water > North Borehole Pump", "asset", 0.86, ["north borehole"], "water")]
    out = RulesRouter().route(_ctx("Water pressure is low today", cands))
    assert {a["node_id"] for a in out["actions"]} == {"water"}
