# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""The NoteCad showcase: a clean farm workspace and three notes that exercise the whole stack.

  1  "Wheel needs changing on tractor model John Deere 9550 - number 1"   -> task on John Deere 9550 #1
  2  "Today I planted field south 704 to 708"                             -> five fields filled to 100 %
  3  "Ask Sipho to check the water pump on the North borehole"            -> task on North Borehole Pump for Sipho

Against the running brain (start it with services\\start_notecad.ps1 first):

  python tools/seed_farm_showcase.py                     build the showcase workspace if it is not there
  python tools/seed_farm_showcase.py --reset-clean       archive and remove it, then build it fresh
  python tools/seed_farm_showcase.py --interactive       ... then send the three notes one at a time (Enter)
  python tools/seed_farm_showcase.py --auto --pause 4    ... send all three, pausing so you can watch the map
  python tools/seed_farm_showcase.py --audio DIR         ... speak them: DIR\\showcase_1.wav .. showcase_3.wav
  python tools/seed_farm_showcase.py --check             only check the three results on the current map
  python tools/seed_farm_showcase.py --list              list workspaces, marking stale test ones
  python tools/seed_farm_showcase.py --remove-stale      dry run: which test workspaces would go
  python tools/seed_farm_showcase.py --remove-stale --yes   archive each to data\\archive\\, then remove it

Removal is permanent; every workspace is written to data\\archive\\<id>-<time>.json first.
The same farm and checks run in process with: python tools/field_test.py --showcase
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]  # the NoteCad folder
SHOWCASE_ID = "showcase"
STALE = re.compile(r"^demo-farm|^t_|^test", re.I)
STALE_NAMES = re.compile(r"demo farm$", re.I)

F = lambda n, ha, planted=0: (f"Field {n}", "field", [f"field {n.split()[-1]}", n.lower(), f"land {n.split()[-1]}"],  # noqa: E731
                              {"area_ha": ha, "planted_ha": planted, "phase": "planting"}, [])
FARM = [
    ("Vehicles", "category", ["voertuie"], {}, [
        ("Tractors", "group", ["tractor", "trekker", "trekkers"], {}, [
            ("Maintenance", "channel", [], {}, []),
            ("John Deere 9550 #1", "asset", ["john deere 9550 number 1", "john deere one", "first john deere", "jd 1"], {"hours": 6120}, []),
            ("John Deere 9550 #2", "asset", ["john deere 9550 number 2", "john deere two", "second john deere", "jd 2"], {"hours": 4310}, []),
            ("Case IH Magnum 340", "asset", ["case", "magnum", "rooi trekker"], {"hours": 2890}, [])]),
        ("Bakkies", "group", ["bakkie", "pickup"], {}, [
            ("Maintenance", "channel", [], {}, []),
            ("Toyota Hilux", "asset", ["hilux"], {}, [])]),
    ]),
    ("Fields", "category", ["lande", "crops", "oeste"], {}, [
        ("South Block", "group", ["south", "suid"], {}, [F(f"South {n}", ha) for n, ha in
                                                         ((704, 40), (705, 52), (706, 38), (707, 61), (708, 45))]),
        ("North Block", "group", ["north", "noord"], {}, [F("North 101", 80, 80), F("North 102", 75, 30)]),
    ]),
    ("Water", "category", ["water", "boreholes", "boorgate"], {}, [
        ("North Borehole Pump", "asset", ["north borehole", "north borehole pump", "noord boorgat", "noord pomp"], {}, []),
        ("South Borehole Pump", "asset", ["south borehole", "south borehole pump", "suid boorgat", "suid pomp"], {}, []),
        ("Centre Pivot 2", "asset", ["pivot 2", "spilpunt 2"], {}, []),
    ]),
    ("Livestock", "category", ["vee"], {}, [
        ("Cattle", "group", ["cows", "beeste", "koeie", "calf", "kalf"], {}, [("Health Alerts", "channel", [], {}, [])]),
        ("Sheep", "group", ["ewes", "skape", "ooie"], {}, [("Health Alerts", "channel", [], {}, [])]),
    ]),
    ("Infrastructure", "category", [], {}, [("Fencing", "group", ["fence", "draad", "heining"], {}, [])]),
    ("Admin", "category", [], {}, [("Staff", "group", ["team", "personeel"], {}, [
        ("Sipho", "person", ["sipho dlamini", "voorman", "foreman"], {}, []),
        ("Thandi", "person", ["thandi nkosi"], {}, []),
        ("Thabo", "person", ["thabo mokoena", "mechanic", "werktuigkundige"], {}, [])])]),
    # ADR 0014: a branch only owners see
    ("Financials", "category", ["finances", "finansies", "geld"], {}, [
        ("Bank Loan", "topic", ["absa loan", "lening", "bank"], {}, []),
        ("Payroll", "topic", ["wages", "salaries", "lone"], {}, [])]),
]
# (name, person node, role): Sipho and Thandi are employees, Thabo a person tasks are delegated to (no login)
MEMBERS = [("Sipho Dlamini", "Sipho", "employee"), ("Thandi Nkosi", "Thandi", "employee"),
           ("Thabo Mokoena", "Thabo", "employee")]
MANAGER = ("Marie Venter", "North Block")  # a manager bound to one section (ADR 0014, decision 3)
RESTRICTED = {"Financials": "owner"}
SEATS = {"manager": 1, "employee": 3}  # free seats to invite into (the local ledger: added by hand)
NOTES = [
    "Wheel needs changing on tractor model John Deere 9550 - number 1",
    "Today I planted field south 704 to 708",
    "Ask Sipho to check the water pump on the North borehole",
]
FIELDS = [f"Field South {n}" for n in range(704, 709)]


# ==================================================================== what each note must do on the map
def _by_title(mm: dict) -> dict[str, dict]:
    return {n["title"]: n for n in mm["nodes"] if n["type"] in ("entity", "category", "root")}


def _tasks_on(mm: dict, node_id: str) -> list[dict]:
    return [n for n in mm["nodes"] if n["type"] == "task" and n["parent_id"] == node_id]


def check(i: int, mm: dict, before: dict | None = None) -> tuple[bool, str]:
    """i is 1, 2 or 3. Checks the mind map payload (GET /mindmap), the same thing the desktop draws."""
    t = _by_title(mm)
    if i == 1:
        jd1, jd2 = t.get("John Deere 9550 #1"), t.get("John Deere 9550 #2")
        if not jd1:
            return False, "John Deere 9550 #1 is not on the map"
        wheel = [x for x in _tasks_on(mm, jd1["id"]) if "wheel" in x["title"].lower()]
        notes = [x for x in jd1.get("recent_notes") or [] if "wheel" in x["body"].lower()]
        wrong = jd2 and any("wheel" in x["title"].lower() for x in _tasks_on(mm, jd2["id"]))
        if wrong:
            return False, "the wheel job went to John Deere 9550 #2"
        if wheel:
            return True, f"task \"{wheel[0]['title']}\" on John Deere 9550 #1"
        return False, "a note on John Deere 9550 #1 but no task" if notes else "nothing about the wheel on John Deere 9550 #1"
    if i == 2:
        pct = {f: (t.get(f) or {}).get("progress_pct") for f in FIELDS}
        full = [f for f, p in pct.items() if p is not None and p >= 100]
        stray = [x["title"] for f in FIELDS if t.get(f) for x in _tasks_on(mm, t[f]["id"]) if "plant" in x["title"].lower()]
        block = (t.get("South Block") or {}).get("progress_pct")
        if len(full) == 5 and not stray:
            return True, f"fields 704-708 planted 100 %, South Block {block:g} %"
        return False, f"{len(full)} of 5 fields full ({pct}); stray tasks: {stray}"
    if i == 3:
        pump = t.get("North Borehole Pump")
        if not pump:
            return False, "North Borehole Pump is not on the map"
        mine = [x for x in _tasks_on(mm, pump["id"]) if (x.get("assignee") or "").lower().startswith("sipho")]
        if mine:
            return True, f"task \"{mine[0]['title']}\" on North Borehole Pump for {mine[0]['assignee']}"
        south = t.get("South Borehole Pump")
        if south and _tasks_on(mm, south["id"]):
            return False, "the job went to South Borehole Pump"
        return False, "no task for Sipho on North Borehole Pump"
    raise ValueError(i)


# ==================================================================== two ways to reach the brain
class HttpBrain:
    def __init__(self, base: str, token: str | None = None):
        import httpx
        self.base = base.rstrip("/") + "/api/v1"
        self.c = httpx.Client(timeout=240, headers={"Authorization": f"Bearer {token}"} if token else {})

    def _ok(self, r):
        if r.status_code >= 400:
            raise RuntimeError(f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}")
        return r.json()

    def workspaces(self): return self._ok(self.c.get(f"{self.base}/workspaces"))
    def exists(self, ws): return self.c.get(f"{self.base}/workspaces/{ws}").status_code == 200
    def create(self, ws, name): return self._ok(self.c.post(f"{self.base}/workspaces", json={"name": name, "owner_name": "Dennis", "workspace_id": ws, "persona": "farmer"}))
    def add_node(self, ws, parent, title, kind, aliases): return self._ok(self.c.post(f"{self.base}/workspaces/{ws}/nodes", json={"parent_id": parent, "title": title, "kind": kind, "aliases": aliases}))["id"]
    def set_attrs(self, nid, attrs): self._ok(self.c.patch(f"{self.base}/nodes/{nid}", json={"attributes": attrs}))
    def add_member(self, ws, name, person, role="employee"):
        return self._ok(self.c.post(f"{self.base}/workspaces/{ws}/members",
                                    json={"display_name": name, "person_node_id": person, "role": role}))["id"]
    def set_scope(self, member, nodes): self._ok(self.c.patch(f"{self.base}/members/{member}", json={"scope_node_ids": nodes}))
    def restrict(self, nid, vis): self._ok(self.c.post(f"{self.base}/nodes/{nid}/visibility", json={"visibility": vis}))
    def add_seats(self, ws, role, n): self._ok(self.c.post(f"{self.base}/workspaces/{ws}/seats", json={"role": role, "count": n}))
    def mindmap(self, ws): return self._ok(self.c.get(f"{self.base}/workspaces/{ws}/mindmap"))
    def export(self, ws): return self._ok(self.c.get(f"{self.base}/workspaces/{ws}/export"))
    def delete(self, ws): return self._ok(self.c.delete(f"{self.base}/workspaces/{ws}", params={"confirm": ws}))

    def capture(self, ws, text=None, wav: Path | None = None):
        if wav:
            r = self.c.post(f"{self.base}/workspaces/{ws}/capture", data={"wait": "true", "source": "showcase"},
                            files={"file": (wav.name, wav.read_bytes(), "audio/wav")})
        else:
            r = self.c.post(f"{self.base}/workspaces/{ws}/capture", json={"text": text, "wait": True, "source": "showcase"})
        return self._ok(r)


class LocalBrain:
    """The same calls on a Brain object in this process (field_test.py --showcase, tests)."""

    def __init__(self, brain):
        self.b = brain

    def workspaces(self): return self.b.db.query("select id, name from workspaces")
    def exists(self, ws): return self.b.graph.workspace(ws) is not None
    def create(self, ws, name): return self.b.graph.create_workspace(name, persona="farmer", owner_name="Dennis", workspace_id=ws)
    def add_node(self, ws, parent, title, kind, aliases): return self.b.graph.add_node(ws, parent, title, kind, aliases=aliases)
    def set_attrs(self, nid, attrs): self.b.set_attributes(nid, attrs)
    def add_member(self, ws, name, person, role="employee"): return self.b.graph.add_member(ws, name, role=role, person_node_id=person)

    def set_scope(self, member, nodes):
        m = self.b.db.one("select workspace_id from members where id=?", (member,))
        self.b.people._set_scopes(m["workspace_id"], member, nodes)

    def restrict(self, nid, vis): self.b.graph.set_visibility(nid, vis, 1)

    def add_seats(self, ws, role, n):
        from notecad_brain.permissions import owner_principal
        self.b.people.add_seats(owner_principal(self.b.db, ws), ws, role, n)
    def mindmap(self, ws): return self.b.mindmap(ws)
    def export(self, ws): return self.b.export_workspace(ws)
    def delete(self, ws): return self.b.delete_workspace(ws)

    def capture(self, ws, text=None, wav=None):
        r = self.b.register_capture(ws, text=text, audio=wav.read_bytes() if wav else None,
                                    mime="audio/wav" if wav else None, enqueue=False, source="showcase")
        return self.b.process(r["capture_id"])


def build(api, ws: str = SHOWCASE_ID, name: str = "Wabakipi Farm") -> int:
    root = api.create(ws, name)["root_id"]
    people: dict[str, str] = {}
    count = 0

    titles: dict[str, str] = {}

    def add(parent, items):
        nonlocal count
        for title, kind, aliases, attrs, kids in items:
            nid = api.add_node(ws, parent, title, kind, aliases)
            count += 1
            titles.setdefault(title, nid)
            if attrs:
                api.set_attrs(nid, attrs)
            if kind == "person":
                people[title] = nid
            add(nid, kids)
    add(root, FARM)
    for full, short, role in MEMBERS:
        api.add_member(ws, full, people[short], role)
    manager = api.add_member(ws, MANAGER[0], None, "manager")
    api.set_scope(manager, [titles[MANAGER[1]]])
    for title, vis in RESTRICTED.items():
        api.restrict(titles[title], vis)
    for role, n in SEATS.items():
        api.add_seats(ws, role, n)
    return count


def archive(api, ws: str) -> Path:
    d = ROOT / "data" / "archive"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{ws}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    p.write_text(json.dumps(api.export(ws), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return p


def run_note(api, ws: str, i: int, *, wav: Path | None = None, out=print) -> tuple[bool, str, float]:
    t0 = time.perf_counter()
    res = api.capture(ws, text=None if wav else NOTES[i - 1], wav=wav)
    secs = time.perf_counter() - t0
    heard = res.get("text") or NOTES[i - 1]
    events = res.get("events") or []
    states = ", ".join(f"{e.get('state')}" + (f"/{e.get('router')}" if e.get("router") else "") for e in events)
    ok, detail = check(i, api.mindmap(ws))
    out(f"     heard   \"{heard}\"" if wav else f"     events  {len(events)}: {states}")
    return ok, detail, secs


# ==================================================================== console
class C:
    on = sys.stdout.isatty()
    G, R, Y, D, B, X = ("\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m") if on else ("",) * 6


def stale_of(rows: list[dict], keep: str) -> list[dict]:
    return [w for w in rows if w["id"] != keep and (STALE.search(w["id"]) or STALE_NAMES.search(w.get("name") or ""))]


def main() -> int:
    if os.name == "nt":
        os.system("")  # turn on ANSI colours in the Windows console
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brain", default=os.environ.get("NC_BRAIN_URL", "http://127.0.0.1:8788"))
    ap.add_argument("--token", default=os.environ.get("NC_BRAIN_API_TOKEN"))
    ap.add_argument("--id", default=SHOWCASE_ID)
    ap.add_argument("--name", default="Wabakipi Farm")
    ap.add_argument("--reset-clean", action="store_true", help="archive and remove the showcase workspace, then build it fresh")
    ap.add_argument("--remove-stale", action="store_true", help="test workspaces (demo-farm*, '... Demo Farm'): dry run unless --yes")
    ap.add_argument("--yes", action="store_true", help="really remove (each is archived first)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--interactive", action="store_true", help="send the three notes one at a time")
    ap.add_argument("--auto", action="store_true", help="send all three notes")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between notes with --auto")
    ap.add_argument("--audio", type=Path, help="folder with showcase_1.wav .. showcase_3.wav to send as voice")
    ap.add_argument("--check", action="store_true", help="only check the three results")
    a = ap.parse_args()

    api = HttpBrain(a.brain, a.token)
    try:
        rows = api.workspaces()
    except Exception as ex:
        print(f"{C.R}brain not reachable at {a.brain}{C.X} ({type(ex).__name__}). Start it: services\\start_notecad.ps1")
        return 2

    if a.list:
        for w in rows:
            tag = f"{C.Y}stale{C.X}" if w in stale_of(rows, a.id) else (f"{C.G}showcase{C.X}" if w["id"] == a.id else "")
            print(f"  {w['id']:<40} {w['name']:<24} {w.get('nodes', ''):>4} nodes  {tag}")
        return 0

    if a.remove_stale:
        st = stale_of(rows, a.id)
        if not st:
            print("no stale test workspaces")
        for w in st:
            if a.yes:
                p = archive(api, w["id"])
                api.delete(w["id"])
                print(f"  {C.G}removed{C.X} {w['id']} ({w['name']})  archive: {p}")
            else:
                print(f"  would remove {w['id']} ({w['name']}, {w.get('nodes')} nodes)")
        if st and not a.yes:
            print(f"{C.D}dry run: add --yes to archive and remove these{C.X}")

    if a.reset_clean and api.exists(a.id):
        p = archive(api, a.id)
        api.delete(a.id)
        print(f"{C.G}removed{C.X} old '{a.id}' workspace  (archive: {p})")

    if not api.exists(a.id):
        n = build(api, a.id, a.name)
        print(f"{C.G}built{C.X} '{a.id}' ({a.name}): {n} nodes, members {', '.join(f for f, *_ in MEMBERS)}")
    elif not (a.check or a.remove_stale or a.list):
        print(f"'{a.id}' already exists (use --reset-clean for a fresh one)")

    print(f"open {C.B}{a.brain.rstrip('/')}/app/?ws={a.id}&view=map{C.X}")
    if not (a.interactive or a.auto or a.audio or a.check):
        return 0

    results = []
    for i, note in enumerate(NOTES, 1):
        wav = a.audio / f"showcase_{i}.wav" if a.audio and (a.audio / f"showcase_{i}.wav").exists() else None
        print(f"\n{C.B}{i}/3{C.X}  \"{note}\"" + (f"  {C.D}(voice: {wav.name}){C.X}" if wav else ""))
        if a.check:
            ok, detail = check(i, api.mindmap(a.id))
            secs = 0.0
        else:
            if a.interactive:
                ans = input(f"     {C.D}Enter to send, s to skip, or say it into the app and press c to check:{C.X} ").strip().lower()
                if ans == "s":
                    results.append(None)
                    continue
                if ans == "c":
                    ok, detail = check(i, api.mindmap(a.id))
                    print(f"     {(C.G + 'PASS') if ok else (C.R + 'FAIL')}{C.X}  {detail}")
                    results.append(ok)
                    continue
            ok, detail, secs = run_note(api, a.id, i, wav=wav)
        print(f"     {(C.G + 'PASS') if ok else (C.R + 'FAIL')}{C.X}  {detail}" + (f"  {C.D}{secs:.1f} s{C.X}" if secs else ""))
        results.append(ok)
        if a.auto and a.pause and i < len(NOTES):
            time.sleep(a.pause)
    done = [r for r in results if r is not None]
    print(f"\n{C.B}showcase: {sum(done)}/{len(done)} passed{C.X}")
    return 0 if done and all(done) else 1


if __name__ == "__main__":
    raise SystemExit(main())
