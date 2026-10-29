# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""The worked example from the blueprint: a Highveld farm with sheep, cattle, 3,000 ha beans, tractors and water."""
from notecad_brain.config import Settings
from notecad_brain.pipeline import Brain
from notecad_brain.routers import RouterChain, RulesRouter


MADE: list[Brain] = []  # closed after each test by conftest (no leaked SQLite connections)


def make_brain(db_url: str = "sqlite:///:memory:", routers=None, **kw) -> Brain:
    s = Settings()
    s.db_url, s.worker, s.audio_dir = db_url, False, kw.pop("audio_dir", "./data/test-audio")
    s.stt_engines = ""  # hermetic: no real Deepgram / Whisper even where they are installed; tests pass a fake
    from notecad_companion.embed import HashEmbedder
    b = Brain(s, routers=routers or RouterChain([RulesRouter()]), embedder=kw.pop("embedder", HashEmbedder(256)),
              stt=kw.pop("stt", None), **kw)
    MADE.append(b)
    return b


def seed_farm(brain: Brain) -> dict:
    g = brain.graph
    ws = g.create_workspace("Highveld Farm", persona="farmer", owner_name="Dennis")
    w, root = ws["id"], ws["root_id"]
    ids = {"ws": w, "root": root}
    ops = g.add_node(w, root, "Operations", "category")
    infra = g.add_node(w, root, "Infrastructure", "category")
    admin = g.add_node(w, root, "Admin", "category")
    livestock = g.add_node(w, ops, "Livestock", "category")
    ids["sheep"] = g.add_node(w, livestock, "Sheep", "group", aliases=["ewes", "ewe", "skape", "ooie", "rams"])
    ids["sheep_health"] = g.add_node(w, ids["sheep"], "Health Alerts", "channel")
    ids["cattle"] = g.add_node(w, livestock, "Cattle", "group", aliases=["cows", "beeste"])
    crops = g.add_node(w, ops, "Crops", "category")
    ids["beans"] = g.add_node(w, crops, "Beans", "field", aliases=["bone", "bean fields"],
                              attributes={"area_ha": 3000, "planted_ha": 2800, "phase": "planting"})
    ids["planting_log"] = g.add_node(w, ids["beans"], "Planting Log", "channel")
    vehicles = g.add_node(w, ops, "Vehicles", "category")
    ids["tractors"] = g.add_node(w, vehicles, "Tractors", "group", aliases=["tractor", "john deere", "trekker"])
    ids["tractor_maint"] = g.add_node(w, ids["tractors"], "Maintenance", "channel")
    water = g.add_node(w, infra, "Water", "group")
    ids["water"] = water
    ids["pump"] = g.add_node(w, water, "Main Water Pump", "asset",
                             aliases=["main pump", "die groot pomp", "hoofpomp", "borehole pump"])
    ids["pivot"] = g.add_node(w, water, "Centre Pivot 2", "asset", aliases=["pivot 2"])
    paddocks = g.add_node(w, infra, "Paddocks", "group")
    ids["south_paddock"] = g.add_node(w, paddocks, "South Paddock", "place", aliases=["south camp"])
    ids["north_fence"] = g.add_node(w, infra, "Fencing", "group", aliases=["fence", "north fence", "draad"])
    staff = g.add_node(w, admin, "Staff", "group")
    ids["sipho_node"] = g.add_node(w, staff, "Sipho", "person", aliases=["sipho dlamini"])
    ids["sipho"] = g.add_member(w, "Sipho Dlamini", role="manager", person_node_id=ids["sipho_node"])
    ids["livestock"], ids["ops"], ids["infra"] = livestock, ops, infra
    return ids
