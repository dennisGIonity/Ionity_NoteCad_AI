# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""ADR 0014, decisions 7 and 28: spoken admin commands, from a fixed grammar (never a model). Restricting applies at
once; loosening and role changes come back as a confirm; an employee gets a polite refusal, and it is logged."""
import json

import pytest

from notecad_brain import admin
from test_roles_access import as_, seed_roles


@pytest.fixture
def roles(farm):
    b, ids = farm
    return b, seed_roles(b, ids)


def say(b, ids, who: str, text: str) -> dict:
    r = b.register_capture(ids["ws"], text=text, enqueue=False, principal=as_(b, ids, who))
    return b.process(r["capture_id"])["events"][0]


def test_the_grammar_in_english_and_afrikaans():
    assert admin.parse("Make Johan a manager") == admin.Command("role", "Johan", "manager")
    assert admin.parse("Maak Johan 'n bestuurder.") == admin.Command("role", "Johan", "manager")
    assert admin.parse("Restrict Financials to owner only") == admin.Command("visibility", "Financials", "owner")
    assert admin.parse("make payroll managers only") == admin.Command("visibility", "payroll", "manager")
    assert admin.parse("Beperk Finansies tot eienaars") == admin.Command("visibility", "Finansies", "owner")
    assert admin.parse("Make Financials visible to everyone") == admin.Command("visibility", "Financials", "all")
    assert admin.parse("Who can see Financials?") == admin.Command("who", "Financials", None)
    assert admin.parse("Wie kan Finansies sien?") == admin.Command("who", "Finansies", None)
    for note in ("Make sure the pump is fixed", "The manager checked the fence", "Ask Sipho to see the pump"):
        assert admin.parse(note) is None


def test_an_owner_restricts_at_once_and_loosens_with_a_confirm(roles):
    b, ids = roles
    out = say(b, ids, "owner", "Restrict Payroll to owner only")
    assert out["state"] == "applied" and "owners only" in out["answer"]
    assert b.graph.node(ids["payroll"])["eff_level"] == 1
    out = say(b, ids, "owner", "Make Financials visible to everyone")
    assert out["state"] == "needs_review" and b.graph.node(ids["financials"])["eff_level"] == 1
    b.resolve_inbox(out["proposal"], decision="approve", principal=as_(b, ids, "owner"))
    assert b.graph.node(ids["financials"])["eff_level"] == 3


def test_a_role_change_by_voice_is_confirmed_first(roles):
    b, ids = roles
    b.people.add_seats(as_(b, ids, "owner"), ids["ws"], "manager", 1)
    out = say(b, ids, "owner", "Make Thandi a manager")
    assert out["state"] == "needs_review" and "Thandi Nkosi" in out["answer"]
    assert b.db.one("select level from members where id=?", (ids["thandi"],))["level"] == 3  # not yet
    b.resolve_inbox(out["proposal"], decision="approve", principal=as_(b, ids, "owner"))
    assert b.db.one("select level from members where id=?", (ids["thandi"],))["level"] == 2


def test_who_can_see_names_the_people(roles):
    b, ids = roles
    out = say(b, ids, "owner", "Who can see Payroll?")
    assert "managers and owners" in out["answer"] and "Sipho Dlamini" in out["answer"] and "Thandi" not in out["answer"]


@pytest.mark.parametrize("text", ["Make Sipho an owner", "Who can see Financials?", "Restrict the Main Water Pump to owners"])
def test_an_employee_is_refused_politely_and_it_is_logged(roles, text):
    b, ids = roles
    out = say(b, ids, "thandi", text)
    assert out["answer"].startswith("Only")
    log = b.db.one("select action from action_log where member_id=? and action like ?", (ids["thandi"], "%refused%"))
    assert json.loads(log["action"])["type"] == "refused"
    assert b.db.one("select level from members where id=?", (ids["sipho"],))["level"] == 2
    assert b.graph.node(ids["pump"])["eff_level"] == 3
