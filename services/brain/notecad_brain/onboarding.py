# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""First run (blueprint 3.3): the owner says what they do; the brain proposes their own top branches.
A model builds it from the answer; starter packs are only the fallback, and the owner accepts or edits it."""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .graph import Graph

PACKS: dict[str, dict] = {
    "farm": {"persona": "farmer", "branches": [
        {"title": "Livestock", "kind": "category", "children": [
            {"title": "Cattle", "kind": "group", "aliases": ["cows", "beeste", "koeie"], "children": [{"title": "Health Alerts", "kind": "channel"}]},
            {"title": "Sheep", "kind": "group", "aliases": ["ewes", "rams", "skape", "ooie"], "children": [{"title": "Health Alerts", "kind": "channel"}]}]},
        {"title": "Crops", "kind": "category", "aliases": ["oeste", "lande", "gewasse", "beans", "bone", "maize", "mielies", "wheat", "koring", "soya", "soybeans", "sunflower", "sonneblom"], "children": [{"title": "Fields", "kind": "group"}]},
        {"title": "Vehicles", "kind": "category", "children": [
            {"title": "Tractors", "kind": "group", "aliases": ["tractor", "trekker", "trekkers"], "children": [{"title": "Maintenance", "kind": "channel"}]},
            {"title": "Bakkies", "kind": "group", "aliases": ["bakkie", "pickup"], "children": [{"title": "Maintenance", "kind": "channel"}]}]},
        {"title": "Infrastructure", "kind": "category", "children": [
            {"title": "Water", "kind": "group", "aliases": ["pump", "pomp", "borehole", "boorgat"], "children": [{"title": "Maintenance", "kind": "channel"}]},
            {"title": "Fencing", "kind": "group", "aliases": ["fence", "draad", "heining"]}, {"title": "Buildings", "kind": "group"},
            {"title": "Paddocks", "kind": "group", "aliases": ["camp", "kamp", "paddock"]}]},
        {"title": "Admin", "kind": "category", "children": [
            {"title": "Finance", "kind": "topic"}, {"title": "Staff", "kind": "group"}, {"title": "Compliance", "kind": "topic"}]}]},
    "workshop": {"persona": "workshop", "branches": [
        {"title": "Jobs", "kind": "category", "children": [{"title": "Open Jobs", "kind": "group"}, {"title": "Waiting for Parts", "kind": "channel"}]},
        {"title": "Equipment", "kind": "category", "children": [{"title": "Maintenance", "kind": "channel"}]},
        {"title": "Stock", "kind": "category"}, {"title": "Customers", "kind": "category"},
        {"title": "Admin", "kind": "category", "children": [{"title": "Finance", "kind": "topic"}, {"title": "Staff", "kind": "group"}]}]},
    "office": {"persona": "office", "branches": [
        {"title": "Projects", "kind": "category"}, {"title": "Clients", "kind": "category"},
        {"title": "Team", "kind": "category"}, {"title": "Meetings", "kind": "category"}, {"title": "Admin", "kind": "category"}]},
    "study": {"persona": "student", "branches": [
        {"title": "Courses", "kind": "category"}, {"title": "Assignments", "kind": "category"},
        {"title": "Projects", "kind": "category"}, {"title": "Personal", "kind": "category"}]},
    "household": {"persona": "household", "branches": [
        {"title": "Home", "kind": "category", "children": [{"title": "Maintenance", "kind": "channel"}]},
        {"title": "Family", "kind": "category"}, {"title": "Vehicles", "kind": "category"},
        {"title": "Money", "kind": "category"}, {"title": "Health", "kind": "category"}]},
}
PACK_WORDS = [("farm", r"farm|plaas|boer|cattle|sheep|beeste|skape|crop|hectare|hektaar|\d+\s*ha\b|livestock|vee|bone|mielies|boorgat|borehole|tractor|trekker"),
              ("workshop", r"workshop|werkswinkel|mechanic|garage|repairs|panel|fitter|welding"),
              ("study", r"student|study|studeer|university|universiteit|school|course|exam"),
              ("household", r"household|family|kids|home|huis|gesin"),
              ("office", r"office|kantoor|manager|clients|consult|sales|team|project")]

SPINE_SCHEMA = {"type": "object", "required": ["persona", "branches"], "properties": {
    "persona": {"type": "string"},
    "branches": {"type": "array", "minItems": 2, "maxItems": 8, "items": {
        "type": "object", "required": ["title", "kind", "children"], "properties": {
            "title": {"type": "string"}, "kind": {"type": "string", "enum": ["category"]},
            "children": {"type": "array", "maxItems": 8, "items": {
                "type": "object", "required": ["title", "kind"], "properties": {
                    "title": {"type": "string"},
                    "kind": {"type": "string", "enum": ["group", "asset", "field", "place", "person", "project", "topic", "channel"]},
                    "aliases": {"type": "array", "items": {"type": "string"}}}}}}}}}}

PROMPT = ("You set up a personal NoteCad map from the owner's own description of their work and life. Propose 3-7 "
          "top-level categories and under each the specific things they named (their animals, machines, fields, "
          "places, people, projects). Use their own words and names, in their language. Add a 'Maintenance' or "
          "'Health Alerts' channel under groups of machines or animals. Do not invent things they did not mention "
          "beyond obvious categories. Return JSON.")


def pick_pack(answer: str) -> str:
    a = answer.lower()
    scores = {name: len(re.findall(pat, a)) for name, pat in PACK_WORDS}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] else "office"


GENERIC = {"maintenance", "health alerts", "onderhoud", "gesondheid", "alerts", "general", "algemeen"}
PERSON = re.compile(r"\b([A-Z][a-zA-Z'-]+)\s+(?:is|is ons|is my)\s+(?:my|ons|our|the|die)?\s*"
                    r"(voorman|foreman|manager|bestuurder|worker|werker|mechanic|werktuigkundige|vet|veearts|"
                    r"assistant|assistent|partner|son|seun|daughter|dogter|wife|vrou|husband|man)\b")


NUMBER_ONLY = re.compile(r"[\d\s.,]+\s*(ha|hektaar|hectares?|head|koppe|stuks)?", re.I)


def _owner_words(answer: str, title: str) -> str:
    """Use the owner's own spelling: the model once wrote 'hoelpomp' for 'hoofpomp'."""
    words = re.findall(r"[\wÀ-ÿ'-]+", answer)
    n = len(title.split()) or 1
    best, best_s = title, 0
    for i in range(len(words) - n + 1):
        span = " ".join(words[i:i + n])
        sc = fuzz.ratio(span.lower(), title.lower())
        if sc > best_s:
            best, best_s = span, sc
    return best if best_s >= 72 else title


def _all_nodes(branches: list[dict]):
    for b in branches:
        yield b
        yield from _all_nodes(b.get("children") or [])


def _names(n: dict) -> list[tuple[str, float]]:
    return [(n["title"], 2.0)] + [(a, 1.0) for a in n.get("aliases") or []]


def propose(answer: str, llm=None) -> dict:
    """Structure from the starter pack that fits the owner's words; the specific things they named (their animals,
    machines, fields, people) placed into it from the model's reading, or from rules when no model is available."""
    import copy
    from .retrieve import _fuzzy
    pack = pick_pack(answer)
    spine = copy.deepcopy(PACKS[pack])
    spine["source"] = f"starter-pack:{pack}"
    added: list[str] = []
    staff = next((n for n in _all_nodes(spine["branches"]) if n["title"] in ("Staff", "Team", "Family")), None)
    for m in PERSON.finditer(answer):  # "Sipho is my voorman"
        if staff is not None:
            staff.setdefault("children", []).append({"title": m.group(1), "kind": "person", "aliases": [m.group(2).lower()]})
            added.append(m.group(1))
    if llm is not None:
        try:
            from notecad_companion.llm import parse_json
            data = parse_json(llm.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": answer}],
                                       max_tokens=900, temperature=0.2, schema=SPINE_SCHEMA))
        except Exception:
            data = None
        if isinstance(data, dict):
            spine["source"] += f"+{getattr(llm, 'name', 'model')}"
            spine["persona"] = data.get("persona") or spine.get("persona")
            pack_nodes = [n for n in _all_nodes(spine["branches"]) if n.get("kind") != "channel"]
            for cat in data.get("branches") or []:
                for item in cat.get("children") or []:
                    title = _owner_words(answer, (item.get("title") or "").strip())
                    if not title or title.lower() in GENERIC or title in added or NUMBER_ONLY.fullmatch(title):
                        continue
                    aliases = [a for a in item.get("aliases") or [] if a.lower() not in GENERIC]
                    # already in the pack under another name? then the owner's word becomes an alias
                    same, same_s = None, 0
                    for n in pack_nodes:
                        for nm, _ in _names(n):
                            sc = fuzz.token_set_ratio(title.lower(), nm.lower())
                            if sc >= 90 and len(title.split()) <= len(nm.split()) + 1 and sc > same_s:
                                same, same_s = n, sc
                    if same is not None:
                        if title.lower() not in [a.lower() for a in same.setdefault("aliases", [])] + [same["title"].lower()]:
                            same["aliases"].append(title.lower())
                        continue
                    # otherwise it goes under the pack node its category or its own words fit best
                    home = max(pack_nodes, key=lambda n: max(_fuzzy(f"{cat.get('title', '')} {title}", _names(n)),
                                                              _fuzzy(title, _names(n))))
                    if max(_fuzzy(f"{cat.get('title', '')} {title}", _names(home)), _fuzzy(title, _names(home))) < 0.4:
                        # nothing in the pack fits: the owner's own category becomes a branch (they approve it first)
                        ctitle = (cat.get("title") or "Other").strip()[:80]
                        home = next((b for b in spine["branches"] if b["title"].lower() == ctitle.lower()), None)
                        if home is None:
                            home = {"title": ctitle, "kind": "category", "children": []}
                            spine["branches"].append(home)
                            pack_nodes.append(home)
                    kind = item.get("kind") if item.get("kind") in ("asset", "field", "place", "person", "project") else "asset"
                    if home["title"] in ("Staff", "Team", "Family"):
                        kind = "person"
                    home.setdefault("children", []).append({"title": title[:80], "kind": kind, "aliases": aliases})
                    added.append(title)
    spine["added_from_answer"] = added
    return spine


def apply_spine(graph: Graph, ws: str, spine: dict) -> int:
    root = graph.root(ws)
    count = 0

    def add(parent: str, items: list[dict]) -> None:
        nonlocal count
        existing = {c["title"].lower(): c["id"] for c in graph.children(parent)}
        for it in items:
            title = (it.get("title") or "").strip()
            if not title:
                continue
            nid = existing.get(title.lower())
            if nid is None:
                nid = graph.add_node(ws, parent, title, it.get("kind") or "topic", aliases=it.get("aliases"))
                count += 1
            add(nid, it.get("children") or [])

    with graph.db.tx():
        add(root["id"], spine.get("branches") or [])
        if spine.get("persona"):
            graph.db.update("workspaces", {"id": ws}, {"persona": spine["persona"]})
    return count
