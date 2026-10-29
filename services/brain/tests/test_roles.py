# Ionity Business Mind Map (IBMM) - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""ADR 0014, roles, seats and permission-aware sync. Step 2: migration 7, the permission matrix, the journal's new
columns, and Supabase 0007 generated from them."""
import sqlite3
import sys
from pathlib import Path

import pytest

from farm import make_brain
from notecad_brain import permissions as P
from notecad_brain.db import ADDED_COLUMNS, MIGRATIONS, SCHEMA, Database
from notecad_brain.graph import GraphError
from notecad_brain.sync import TABLES
from test_sync import brain, link

OLD_MEMBERS = [("o", "owner", None), ("e1", "editor", "user-1"), ("e2", "editor", None), ("e3", "editor", ""),
               ("v", "viewer", None)]


def _phase6_db(path: Path) -> None:
    """A database as Phase 6 left it: migrations up to 6, members with the Phase 1 role names."""
    c = sqlite3.connect(path)
    c.executescript(SCHEMA.replace("{BLOB}", "blob"))
    for table, column, typ in ADDED_COLUMNS:
        if column not in {r[1] for r in c.execute(f"pragma table_info({table})")}:
            c.execute(f"alter table {table} add column {column} {typ}")
    c.execute("create table schema_migrations (version integer primary key, name text not null, applied_at text not null)")
    for version, name, statements in MIGRATIONS:
        if version < 7:
            for s in statements:
                c.execute(s)
            c.execute("insert into schema_migrations values (?, ?, '2026-10-28T00:00:00Z')", (version, name))
    c.execute("insert into workspaces(id, name, created_at) values ('w', 'Farm', '2026-10-01T00:00:00Z')")
    for mid, role, user in OLD_MEMBERS:
        c.execute("insert into members(id, workspace_id, user_id, display_name, role, created_at) "
                  "values (?, 'w', ?, ?, ?, '2026-10-01T00:00:00Z')", (mid, user, mid, role))
    c.commit()
    c.close()


def _roles(db: Database) -> dict:
    return {r["id"]: (r["role"], r["level"], r["read_only"]) for r in db.query("select * from members")}


MAPPED = {"o": ("owner", 1, 0), "e1": ("manager", 2, 0), "e2": ("employee", 3, 0), "e3": ("employee", 3, 0),
          "v": ("employee", 3, 1)}


# ---------------------------------------------------------------- migration 7
def test_migration_7_maps_the_phase_1_roles(tmp_path):
    """Owner question 1: an editor with a login is a manager; one added only for delegation an employee."""
    path = tmp_path / "phase6.db"
    _phase6_db(path)
    db = Database(f"sqlite:///{path}")
    assert _roles(db) == MAPPED
    assert {"visibility", "vis_set_by", "eff_level", "rollup_tiers"} <= {r["name"] for r in db.query("pragma table_info(nodes)")}
    tables = {r["name"] for r in db.query("select name from sqlite_master where type='table'")}
    assert {"member_scopes", "seats", "invites", "devices"} <= tables
    assert db.one("select max(version) as v from schema_migrations")["v"] == MIGRATIONS[-1][0]
    db.close()


def test_migration_7_can_run_again(tmp_path):
    """A Supabase hub that already has 0007 runs migration 7 once more when a brain first connects: no error, and
    nothing is mapped twice."""
    url = f"sqlite:///{tmp_path / 'again.db'}"
    _phase6_db(tmp_path / "again.db")
    db = Database(url)
    db.execute("delete from schema_migrations where version=7")
    db.close()
    db = Database(url)
    assert _roles(db) == MAPPED
    db.close()


def test_migration_7_on_postgres_too(farm):
    b, ids = farm
    for s in next(st for v, _, st in MIGRATIONS if v == 7):  # again, as on a Supabase hub
        b.db.run_migration_statement(s)
    assert b.db.one("select level, status from members where id=?", (ids["sipho"],)) == {"level": 2, "status": "active"}
    assert b.db.one("select eff_level, visibility from nodes where id=?", (ids["pump"],)) == {"eff_level": 3,
                                                                                            "visibility": "all"}


def test_members_get_a_level(farm):
    b, ids = farm
    owner = b.db.one("select role, level from members where workspace_id=? and role='owner'", (ids["ws"],))
    assert owner == {"role": "owner", "level": 1}
    thandi = b.graph.add_member(ids["ws"], "Thandi")
    viewer = b.graph.add_member(ids["ws"], "Visitor", role="viewer")
    legacy = b.graph.add_member(ids["ws"], "Johan", role="editor", user_id="user-7")
    got = {m["id"]: (m["role"], m["level"], m["read_only"]) for m in b.graph.members(ids["ws"])}
    assert got[thandi] == ("employee", 3, 0) and got[viewer] == ("employee", 3, 1) and got[legacy] == ("manager", 2, 0)
    with pytest.raises(GraphError):
        b.graph.add_member(ids["ws"], "Root", role="system")


def test_the_last_owner_cannot_be_demoted_or_revoked(farm):
    b, ids = farm
    owner = b.db.one("select id from members where workspace_id=? and level=1", (ids["ws"],))["id"]
    with pytest.raises(Exception, match="last owner"):
        b.db.execute("update members set role='manager', level=2 where id=?", (owner,))
    second = b.graph.add_member(ids["ws"], "Marie", role="owner")
    b.db.execute("update members set status='revoked' where id=?", (owner,))  # another owner is left
    with pytest.raises(Exception, match="last owner"):
        b.db.execute("update members set status='revoked' where id=?", (second,))
    b.db.execute("update members set display_name='Marie B' where id=?", (second,))  # other changes still work


# ---------------------------------------------------------------- the journal
def _act(b, member: str | None, level: int | None) -> None:
    """The member a transaction acts for (step 3 sets this around every write)."""
    if b.db.kind == "sqlite":
        b.db.execute("delete from sync_state where key in ('actor_member', 'actor_level')")
        if member:
            b.db.execute("insert into sync_state(key, value) values ('actor_member', ?), ('actor_level', ?)",
                         (member, str(level)))
    else:
        b.db.execute("select set_config('notecad.member', ?, false), set_config('notecad.level', ?, false)",
                     (member or "", str(level) if level is not None else ""))


def test_the_journal_says_who_where_and_how_visible(farm):
    b, ids = farm
    pump, ws = ids["pump"], ids["ws"]

    def last(tbl: str, pk: str) -> dict:
        return b.db.one("select * from sync_changes where tbl=? and pk=? order by seq desc limit 1", (tbl, pk)) or {}

    before = last("nodes", pump)
    _act(b, "m-1", 2)
    try:
        b.db.execute("update nodes set visibility='owner', vis_set_by=1, eff_level=1 where id=?", (pump,))
        row = last("nodes", pump)
        assert (row["node_id"], row["vis"], row["author_member_id"], row["author_level"]) == (pump, 1, "m-1", 2)
        assert (row["base_ts"], row["base_origin"]) == (before["ts"], before["origin"])  # the version it changed
        b.db.insert("notes", {"id": "n-1", "workspace_id": ws, "node_id": pump, "capture_id": None, "body": "Oil low",
                              "tags": [], "author": "user", "created_at": "2026-10-29T08:00:00Z"})
        note = last("notes", "n-1")
        assert (note["node_id"], note["vis"], note["base_ts"]) == (pump, 1, None)  # a new row has no base
        b.db.execute("delete from notes where id='n-1'")
        gone = last("notes", "n-1")
        assert (gone["op"], gone["node_id"], gone["vis"]) == ("D", pump, 1)  # a delete keeps where it was
        b.applier._link(ws, pump, ids["sipho_node"], "related_to", "user")
        edge = b.db.one("select * from sync_changes where tbl='edges' order by seq desc limit 1")
        assert edge["vis"] == 1  # the stricter of its two ends
    finally:
        _act(b, None, None)
    b.db.execute("update nodes set summary='Main pump' where id=?", (pump,))
    assert last("nodes", pump)["author_member_id"] is None


def test_a_change_from_a_peer_keeps_its_own_base(farm):
    b, ids = farm
    pump = ids["pump"]
    row = {**b.db.one("select * from nodes where id=?", (pump,)), "title": "Main Water Pump (new)"}
    got = b.journal.receive([{"tbl": "nodes", "pk": pump, "op": "U", "row": row, "ws": ids["ws"], "origin": "peer-1",
                              "ts": "2099-01-01T00:00:00.000Z", "origin_seq": 1}], via="peer-1")
    assert got["applied"] == 1
    r = b.db.one("select * from sync_changes where origin='peer-1'")
    assert r["base_ts"] is None and r["node_id"] == pump and r["vis"] == 3


def test_seats_scopes_invites_and_devices_sync():
    desk, edge = brain("desktop"), brain("edge")
    from farm import seed_farm
    ids = seed_farm(desk)
    ws = ids["ws"]
    desk.db.insert("seats", {"id": "s-1", "workspace_id": ws, "role_level": 3, "status": "assigned",
                             "assigned_member_id": ids["sipho"], "purchased_at": "2026-10-29T08:00:00Z"})
    desk.db.insert("member_scopes", {"workspace_id": ws, "member_id": ids["sipho"], "node_id": ids["pump"],
                                     "created_at": "2026-10-29T08:00:00Z"})
    desk.db.insert("devices", {"id": "d-1", "workspace_id": ws, "member_id": ids["sipho"], "name": "Sipho's phone",
                               "token_hash": "ab" * 32, "created_at": "2026-10-29T08:00:00Z"})
    eng = link(desk, edge)
    assert eng.run_once()["ok"]
    assert edge.db.one("select status from seats where id='s-1'") == {"status": "assigned"}
    assert edge.db.one("select node_id from member_scopes where member_id=?", (ids["sipho"],)) == {"node_id": ids["pump"]}
    assert edge.db.one("select token_hash from devices where id='d-1'") == {"token_hash": "ab" * 32}
    desk.db.execute("update devices set revoked_at='2026-10-29T09:00:00Z' where id='d-1'")
    assert eng.run_once()["ok"]
    assert edge.db.one("select revoked_at from devices where id='d-1'") == {"revoked_at": "2026-10-29T09:00:00Z"}


# ---------------------------------------------------------------- the permission matrix
def test_the_matrix_says_what_the_brief_says():
    E, M, O = P.EMPLOYEE, P.MANAGER, P.OWNER
    # employees add and feed data; changes become proposals; a delete is refused
    assert P.decide(E, "append_note") == P.decide(E, "create_task") == P.decide(E, "progress") == P.ALLOW
    assert P.decide(E, "rename_node") == P.decide(E, "move_node") == P.decide(E, "merge_nodes") == P.PROPOSE
    assert P.decide(E, "delete_node") == P.REFUSE and P.decide(E, "set_role") == P.REFUSE
    assert P.decide(E, "create_node") == P.PROPOSE  # the brief's default: ask the owner before changing it
    assert P.decide(E, "complete_task", assigned=True) == P.ALLOW and P.decide(E, "complete_task") == P.PROPOSE
    assert P.decide(E, "edit_entry", own=True) == P.ALLOW and P.decide(E, "edit_entry") == P.PROPOSE
    assert P.decide(E, "undo", own=True) == P.ALLOW and P.decide(E, "undo") == P.REFUSE
    # managers: in their branches; outside them, an employee's rules
    assert P.decide(M, "edit_entry") == P.ALLOW and P.decide(M, "edit_entry", in_scope=False) == P.PROPOSE
    assert P.decide(M, "edit_entry", in_scope=False, own=True) == P.ALLOW
    assert P.decide(M, "approve") == P.ALLOW and P.decide(M, "approve", in_scope=False) == P.REFUSE
    assert P.decide(M, "rename_node") == P.decide(M, "delete_node") == P.PROPOSE
    assert P.decide(M, "set_role") == P.decide(M, "manage_seats") == P.REFUSE
    assert P.decide(M, "invite") == P.ALLOW and P.decide(M, "invite", in_scope=False) == P.REFUSE
    # owners do everything; deleting a node asks once; the brain itself is not a person
    assert all(P.decide(O, a) in (P.ALLOW, P.CONFIRM) for a in P.MATRIX)
    assert P.decide(O, "delete_node") == P.CONFIRM and P.decide(P.SYSTEM, "set_role") == P.ALLOW
    # a read-only member reads, and an unknown level does nothing
    assert P.decide(E, "append_note", read_only=True) == P.REFUSE and P.decide(E, "export", read_only=True) == P.ALLOW
    assert P.decide(7, "append_note") == P.REFUSE
    outcomes = {P.ALLOW, P.CONFIRM, P.PROPOSE, P.REFUSE}
    for lvl in (O, M, E):
        for a in P.MATRIX:
            assert {P.decide(lvl, a, in_scope=s, own=o, assigned=x) for s in (0, 1) for o in (0, 1) for x in (0, 1)} <= outcomes


def test_member_role_names():
    assert P.member_role("owner") == ("owner", 1, 0)
    assert P.member_role("editor", "user-1") == ("manager", 2, 0) and P.member_role("editor") == ("employee", 3, 0)
    assert P.member_role("viewer") == ("employee", 3, 1)
    for bad in ("system", "admin", ""):
        with pytest.raises(ValueError):
            P.member_role(bad)


# ---------------------------------------------------------------- Supabase 0007 (shipped) and 0008
def _gen():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import gen_rls_migration
    return gen_rls_migration


def test_supabase_0007_is_generated_from_the_brain():
    """0007 has shipped (checked by its hash); the row-level security as it is now is 0008, written from the brain."""
    g = _gen()
    assert g.frozen_ok() == [], "a shipped migration was edited: add the next number instead"
    shipped = (g.DIR / "0007_roles_seats_permissions.sql").read_text(encoding="utf-8")
    for t in g.new_tables():
        assert f"create trigger nc_sync_{t} " in shipped
    text = g.render()
    assert g.OUT.read_text(encoding="utf-8") == text, "run tools/gen_rls_migration.py"
    assert "strpos(coalesce(route_member_ids, ''), nc_member(workspace_id))" in text  # no recipients: owners only
    assert set(TABLES) <= set(P.RLS_TABLES), "every synced table needs its row-level security"
    for t, spec in P.RLS_TABLES.items():
        assert f"alter table {t} enable row level security;" in text
        assert f"drop policy if exists {t}_write on {t};" in text  # 0001's policies are replaced
        assert (f"create policy {t}_read on {t} " in text) == bool(spec.read)
    policy = {line.split()[2]: line for line in text.splitlines() if line.startswith("create policy ")}
    # only owners rename, move or delete nodes directly, or touch seats, roles and scopes
    for name in ("nodes_update", "nodes_delete", "seats_insert", "members_update", "member_scopes_insert"):
        assert "when 1 then true else false end" in policy[name] and "when 2" not in policy[name], name
    # an employee writes a note only as themselves, on a node they see
    assert "member_id = nc_member(workspace_id)" in policy["notes_insert"] and "nc_sees_rows(node_id)" in policy["notes_insert"]
    assert not any(n.startswith("devices_") for n in policy)  # the token hashes: no policy, nobody reads them


def test_brain_starts_on_the_backup_shape(tmp_path):
    """A full brain on a Phase 6 database: migration 7, the journal columns and the guards all come up."""
    path = tmp_path / "brain.db"
    _phase6_db(path)
    b = make_brain(f"sqlite:///{path}")
    cols = {r["name"] for r in b.db.query("pragma table_info(sync_changes)")}
    assert {"author_member_id", "author_level", "node_id", "vis", "base_ts", "base_origin"} <= cols
    assert _roles(b.db) == MAPPED
