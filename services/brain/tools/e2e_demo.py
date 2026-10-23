import json, sys, time, httpx
WS = sys.argv[1] if len(sys.argv) > 1 else "demo-farm-4"
B, C = "http://127.0.0.1:8788", "http://127.0.0.1:8787"
c = httpx.Client(timeout=180)
ws = c.post(f"{B}/v1/workspaces", json={"name": "Demo Farm", "owner_name": "Dennis", "workspace_id": WS})
t = time.time()
ob = c.post(f"{B}/v1/workspaces/{WS}/onboard", json={"answer": "Ek boer met 120 Dohne Merino skape en 300 beeste naby Bronkhorstspruit. "
            "Ons het 3000 hektaar bone, twee John Deere trekkers en 'n hoofpomp by die boorgat. Sipho is my voorman."}).json()
print("ONBOARD", ob["proposal"].get("source"), "created", ob["created"], round(time.time() - t, 1), "s")
def walk(n, d=0):
    if d and n["kind"] != "channel":
        print("  " * d + n["title"], f"({n['kind']})")
    for ch in n.get("children", []):
        walk(ch, d + 1)
walk(c.get(f"{B}/v1/workspaces/{WS}/tree").json())
sipho = next((n for n in [] ), None)
c.post(f"{B}/v1/workspaces/{WS}/members", json={"display_name": "Sipho"})
for note in ["Die hoofpomp lek baie erg. Vra Sipho om dit môre reg te maak.",
             "One of the ewes is limping in the south camp",
             "Finished planting the last two hundred hectares of beans"]:
    t = time.time()
    out = c.post(f"{B}/v1/workspaces/{WS}/captures", json={"text": note}).json()
    print("CAPTURE", out["state"], round(time.time() - t, 1), "s |", note)
    for e in out["events"]:
        print("   ", e["state"], e.get("router"), "notes", e.get("notes"), "tasks", e.get("tasks"), "alerts", e.get("alerts"),
              "delegated", [d["to"] for d in e.get("delegated", [])], e.get("reason", ""))
d = c.get(f"{B}/v1/workspaces/{WS}/digest").json()
for tk in d["tasks"]:
    print("TASK", tk["priority"], tk["title"], "|", tk["path"], "|", tk["assignee_name"] or tk["assignee_hint"] or "owner", "|", tk["due_at"])
for a in d["alerts"]:
    print("ALERT", a["severity"], a["title"], "|", a["path"])
for i in d["inbox"]:
    print("INBOX", i["question"])
t = time.time()
r = c.post(f"{C}/v1/{WS}/chat", json={"text": "What do I still need to do this week? Keep it short."}).json()
print("COMPANION", round(time.time() - t, 1), "s:", r["reply"])
