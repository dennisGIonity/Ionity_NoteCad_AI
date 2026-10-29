# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Spoken admin commands (ADR 0014, decisions 7 and 28), recognised by a fixed grammar in English and Afrikaans and
never by a model, so a mishearing or a note with instructions in it cannot grant anything:

  "Make Johan a manager"                   "Maak Johan 'n bestuurder"         -> set_role (always a one-tap confirm)
  "Restrict Financials to owner only"      "Beperk Finansies tot eienaars"    -> set_visibility (tighter: at once)
  "Make Financials visible to everyone"    "Maak Finansies sigbaar vir almal" -> set_visibility (looser: a confirm)
  "Who can see Financials?"                "Wie kan Finansies sien?"           -> an answer
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ROLE_WORDS = {"owner": "owner", "manager": "manager", "employee": "employee", "worker": "employee",
              "eienaar": "owner", "bestuurder": "manager", "werker": "employee", "werknemer": "employee"}
LEVEL_WORDS = {"owner": "owner", "owners": "owner", "eienaar": "owner", "eienaars": "owner",
               "manager": "manager", "managers": "manager", "bestuurder": "manager", "bestuurders": "manager",
               "everyone": "all", "all": "all", "everybody": "all", "almal": "all", "iedereen": "all"}

_END = r"[\s.!?]*$"
VIS = [re.compile(p, re.I) for p in (
    r"^(?:please\s+)?(?:restrict|limit)\s+(?P<what>.+?)\s+to\s+(?:the\s+)?(?P<lvl>owners?|managers?)(?:\s+only)?" + _END,
    r"^(?:please\s+)?make\s+(?P<what>.+?)\s+(?P<lvl>owners?|managers?)\s+only" + _END,
    r"^(?:please\s+)?make\s+(?P<what>.+?)\s+visible\s+to\s+(?P<lvl>everyone|everybody|all|managers?|owners?)" + _END,
    r"^beperk\s+(?P<what>.+?)\s+tot\s+(?:die\s+)?(?P<lvl>eienaars?|bestuurders?)(?:\s+alleen)?" + _END,
    r"^maak\s+(?P<what>.+?)\s+sigbaar\s+(?:vir|aan)\s+(?P<lvl>almal|iedereen|bestuurders?|eienaars?)" + _END,
)]
ROLE = [re.compile(p, re.I) for p in (
    r"^(?:please\s+)?(?:make|set)\s+(?P<who>.+?)\s+(?:an?|the)\s+(?P<role>owner|manager|employee|worker)" + _END,
    r"^maak\s+(?P<who>.+?)\s+(?:'n|n|die)\s+(?P<role>eienaar|bestuurder|werker|werknemer)" + _END,
)]
WHO = [re.compile(p, re.I) for p in (
    r"^who\s+(?:can|may|is\s+allowed\s+to)\s+see\s+(?:the\s+)?(?P<what>.+?)" + _END,
    r"^wie\s+(?:kan|mag)\s+(?:die\s+)?(?P<what>.+?)\s+sien" + _END,
)]


@dataclass(frozen=True)
class Command:
    kind: str           # role | visibility | who
    target: str         # a person's name, or a branch as spoken
    value: str | None   # the role, or the visibility (all | manager | owner)


def parse(event: str) -> Command | None:
    s = event.strip()
    for rx in VIS:
        m = rx.match(s)
        if m:
            return Command("visibility", m["what"].strip(" ,"), LEVEL_WORDS[m["lvl"].lower()])
    for rx in ROLE:
        m = rx.match(s)
        if m:
            return Command("role", m["who"].strip(" ,"), ROLE_WORDS[m["role"].lower()])
    for rx in WHO:
        m = rx.match(s)
        if m:
            return Command("who", m["what"].strip(" ,"), None)
    return None
