# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Writes docs/compliance/popia-action-register.md: every action NoteCad takes on personal information, read from the
code so the register cannot drift: the brain's and the companion's routes (OpenAPI), the spoken admin commands
(admin.py), the background threads, the synced tables (sync.TABLES), and the app actions listed below (each pointing
at the file that does it). Every action is matched to one rule of RULES (what it touches, where it goes, who reads it,
how long it is kept, the POPIA sections, and the status with its evidence: a file and the test that proves it).

    .venv\\Scripts\\python.exe tools\\popia_inventory.py           # write the register
    .venv\\Scripts\\python.exe tools\\popia_inventory.py --check   # exit 1 when an action has no rule, a cited test or
                                                                    file is missing, or the register is out of date (CI)

Technical compliance check, not legal advice: "needs human decision" rows are in docs/compliance/popia-human-actions.md.
"""
from __future__ import annotations

import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve()
BRAIN = HERE.parents[1]
REPO = HERE.parents[3]
sys.path[:0] = [str(BRAIN), str(REPO / "services" / "companion")]
OUT = REPO / "docs" / "compliance" / "popia-action-register.md"

OK, HUMAN = "compliant", "needs human decision"
P_VIEW = "by role and branch (permissions.View; restricted branches only owners or managers)"


@dataclass(frozen=True)
class Rule:
    match: str            # a regex on "<surface> <action>"
    what: str             # personal information touched
    who: str              # data subjects
    where: str            # where it goes
    reads: str            # who can read it
    keep: str             # retention
    popia: str            # sections
    status: str
    evidence: str         # "file or test; file or test"


R = Rule
RULES: list[Rule] = [
    # ---------------------------------------------------------------- the brain's routes
    R(r"^endpoint GET /health$|^companion GET /health$", "none", "-", "-", "anyone on this PC", "-", "-", OK,
      "test_health_reports_speech_model_state"),
    R(r"^endpoint (GET|POST) /v1/workspaces$|^endpoint GET /v1/workspaces/\{ws\}$",
      "business name, owner's name", "owner", "SQLite (Supabase / edge node when sync is set)", "members of the business",
      "until the workspace is deleted", "s9-11, s19", OK, "test_node_history_sync_status_and_workspace_list"),
    R(r"^endpoint POST /v1/workspaces/\{ws\}/onboard$", "the owner's description of the business", "owner",
      "the local model (Ollama on this PC); SQLite", "owners", "until deleted", "s10, s13", OK,
      "test_onboarding_keeps_owner_spelling_and_places_crops"),
    R(r"^endpoint (GET|POST) /v1/workspaces/\{ws\}/(me|members)$|^endpoint PATCH /v1/members/\{member_id\}$",
      "names, roles, contact, scopes", "owner, managers, employees", "SQLite; synced", P_VIEW,
      "until erased or the workspace is deleted", "s8, s11, s19", OK,
      "test_api_answers_as_the_device_member; test_role_changes_need_a_seat_that_holds_them"),
    R(r"^endpoint GET /v1/workspaces/\{ws\}/audit$", "who did what and when (work records)", "all members",
      "SQLite (action_log)", "owners all; managers their branches; employees their own", "log_days",
      "s18 (monitoring), s23", OK, "test_manager_approves_and_the_log_names_writer_and_approver"),
    R(r"^endpoint GET /v1/workspaces/\{ws\}/export$", "everything in the workspace", "everyone in it", "the owner's file",
      "owners (as their view)", "the owner's copy", "s23, s19", OK, "test_export_then_delete_workspace_leaves_others"),
    R(r"^endpoint DELETE /v1/workspaces/\{ws\}$", "everything in the workspace", "everyone in it",
      "deleted; tombstones without data in the journal; companion forgets", "owners, with ?confirm", "-", "s14, s24",
      OK, "test_a_deleted_workspace_leaves_only_tombstones_in_the_journal; test_delete_workspace_api_needs_confirmation"),
    R(r"^endpoint (GET|POST|PATCH|DELETE) /v1/(workspaces/\{ws\}/(tree|nodes)|nodes/\{node_id\}(/history)?)$",
      "node titles and aliases (people are nodes), notes", "people named", "SQLite; synced; device copies", P_VIEW,
      "until deleted; person erasure", "s9-11, s16, s19", OK,
      "test_an_employee_sees_nothing_restricted; test_employee_delete_is_refused_and_logged"),
    R(r"^endpoint POST /v1/nodes/\{node_id\}/visibility$", "-", "-", "SQLite; synced", "owners; managers in branch",
      "-", "s19", OK, "test_managers_restrict_in_their_branches_but_never_to_owner_only"),
    R(r"^endpoint POST /v1/workspaces/\{ws\}/(captures|captures/audio|capture)$",
      "voice recording, what was said, names in it", "the speaker; people named",
      "audio file + SQLite on this PC; the notice must be read first", "the speaker and who sees the branch",
      "audio_days, transcript_days", "s9-12, s18, s26", OK,
      "test_a_member_records_nothing_before_reading_the_notice; test_capture_endpoint_multipart_audio_json_and_errors"),
    R(r"^endpoint (OPTIONS|HEAD|PATCH|DELETE|POST) /v1/workspaces/\{ws\}/uploads(/\{uid\})?$",
      "voice recording (resumable upload from a phone)", "the speaker", "upload parts on this PC, then as a capture",
      "the uploading device", "parts deleted when done or expired; then audio_days", "s18, s19", OK,
      "test_upload_survives_a_dropped_connection_and_becomes_one_anchored_capture; test_a_member_records_nothing_before_reading_the_notice"),
    R(r"^endpoint GET /v1/captures/\{cid\}(/audio)?$", "the recording and its text", "the speaker",
      "the asking app (ticket in the URL, never the token)", P_VIEW, "audio_days", "s19, s23", OK,
      "test_history_plays_the_voice_note; test_phones_get_live_events_and_recordings_with_a_ticket"),
    R(r"^endpoint POST /v1/captures/\{cid\}/undo$", "-", "-", "SQLite", "the author, or who manages them", "-", "s16",
      OK, "test_undo_is_your_own_unless_you_manage_it"),
    R(r"^endpoint (GET|POST) /v1/(workspaces/\{ws\}/inbox|inbox/\{item_id\}/(resolve|dismiss))$",
      "held notes and proposals (text naming people)", "people named", "SQLite; synced",
      "the routed members (owners for sensitive notes)", "transcript_days for the notes", "s16, s26, s71", OK,
      "test_a_note_with_a_workers_health_is_held_for_the_owners; test_employee_rename_becomes_a_proposal_for_an_owner"),
    R(r"^endpoint (GET|PATCH|POST) /v1/(workspaces/\{ws\}/(tasks|alerts|notifications)|tasks/\{task_id\}|alerts/\{alert_id\}/resolve)$",
      "tasks given to people, progress, alerts (work performance)", "employees", "SQLite; synced; phones", P_VIEW,
      "until done and deleted; person erasure", "s11, s18 (monitoring), s71", OK,
      "test_employees_assign_tasks_only_to_themselves; test_restricted_critical_alerts_reach_only_those_who_see_them"),
    R(r"^endpoint GET /v1/workspaces/\{ws\}/(digest|mindmap|keyterms|sync)$", "the map as the caller may see it",
      "people named", "the asking app", P_VIEW, "-", "s19", OK,
      "test_an_employee_sees_nothing_restricted; test_digest_lists_open_work"),
    R(r"^endpoint POST /v1/workspaces/\{ws\}/ask$", "a member's question", "the member",
      "the companion on this PC (the member's own store)", "the member", "transcript_days", "s15", OK,
      "test_the_companion_reads_as_the_member"),
    R(r"^endpoint POST /v1/workspaces/\{ws\}/maintenance$", "-", "-", "SQLite", "owners", "-", "-", OK,
      "test_the_matrix_says_what_the_brief_says"),
    R(r"^endpoint (GET|POST) /v1/sync/(status|push|pull|ack|now)$", "every synced row", "everyone",
      "an edge node or Supabase (operator; TLS; the region is a human decision)",
      "other brains with the sync token; checked against the author's role", "the journal is compacted on purge",
      "s19-21, s72", HUMAN, "test_a_stale_worker_cannot_push_what_a_demoted_member_did; popia-human-actions.md#operators"),
    R(r"^endpoint GET /v1/workspaces/\{ws\}/events/stream$", "live events (note text, names)", "people named",
      "the open apps (ticket, never the token)", "filtered per viewer (events.for_view)", "-", "s19", OK,
      "test_live_events_carry_only_what_the_viewer_sees; test_phones_get_live_events_and_recordings_with_a_ticket"),
    R(r"^endpoint POST /v1/tickets$", "a stand-in for the caller's credential", "the caller", "the caller", "-",
      "10 minutes", "s19", OK, "test_a_ticket_stands_for_a_credential_for_ten_minutes_only"),
    R(r"^endpoint (GET|PUT|POST) /v1/workspaces/\{ws\}/(privacy|privacy/ack)$",
      "owner's contact, Information Officer, when each member read it", "owner, members", "SQLite; synced",
      "every member", "until the workspace is deleted", "s8, s17-18, s55", HUMAN,
      "test_the_owner_sets_the_notice_and_every_member_reads_it; popia-human-actions.md#notice"),
    R(r"^endpoint POST /v1/workspaces/\{ws\}/retention/run$", "-", "-", "deletes what is past its period", "owners",
      "the periods themselves", "s14", OK, "test_old_recordings_transcripts_and_log_go_new_ones_stay"),
    R(r"^endpoint (GET|POST) /v1/workspaces/\{ws\}/subjects/\{sid\}/(export|erase)$",
      "everything about one person", "a member or a person named", "the person's own copy / erased everywhere",
      "owners; a member for themselves", "-", "s23-25", OK,
      "test_a_member_gets_a_copy_of_everything_about_them; test_erasing_a_person_removes_them_everywhere_but_the_audit_record"),
    R(r"^endpoint (GET|POST) /v1/(workspaces/\{ws\}/(seats|invites|devices)|seats/\{seat_id\}/remove|invites/\{invite_id\}/revoke|devices/\{device_id\}/revoke|members/\{member_id\}/revoke)$",
      "names, roles, device names, last seen", "members", "SQLite; synced", "owners; managers for their employees",
      "until erased or the workspace is deleted", "s19", OK,
      "test_revoking_stops_the_device_and_frees_the_seat; test_managers_invite_employees_into_their_own_branches"),
    R(r"^endpoint (GET|POST) /v1/join(/preview)?$", "the invite's name and role; a new device token",
      "the person joining", "the phone (token shown once, stored hashed)", "no token needed: 10 tries a minute",
      "invite expires; one use", "s19", OK,
      "test_join_over_http_and_the_door_is_throttled; test_an_invite_code_never_travels_in_a_url"),
    R(r"^endpoint (GET|POST) /v1/device/(snapshot|pull|wiped)$", "what the member may see", "people named",
      "the member's phone (its copy)", "that member", "wiped on revoke", "s19, s14", OK,
      "test_a_snapshot_holds_only_what_the_member_may_see; test_pull_sends_what_changed_and_tombstones_what_was_restricted"),
    R(r"^endpoint GET /v1/pairing$", "the shared token in a QR (this PC's screen only)", "owner",
      "the phone that scans it", "this PC only", "-", "s19", OK, "test_pairing_only_on_this_pc"),
    # ---------------------------------------------------------------- the companion
    R(r"^companion POST /v1/\{owner_id\}/(chat|feedback|observe)$",
      "what a member says and the notes they file; learned facts", "owner or the member (own store)",
      "the companion's SQLite on this PC; the local model", "that person", "transcript_days (forget before); erasure",
      "s13-15", OK, "companion:test_a_member_has_their_own_memory; companion:test_forget_reaches_the_companion_memory"),
    R(r"^companion (PUT|DELETE|GET|POST) /v1/\{owner_id\}(/facts(/\{key\})?|/card|/keyterms|/nudges|/consolidate|/route-offline|/export|/forget)?$",
      "facts and memories about the owner", "owner or member", "the companion's SQLite", "that person",
      "transcript_days; wiped with the workspace", "s14-16, s23-24", OK,
      "companion:test_full_flow; companion:test_forget_reaches_the_companion_memory"),
    R(r"^companion POST /v1/\{owner_id\}/train/export$", "the owner's own conversations as training examples",
      "owner", "data/companion/training (LoRA, on this PC)", "the owner", "deleted with the store",
      "s15", HUMAN, "companion:test_full_flow; popia-human-actions.md#lora"),
    # ---------------------------------------------------------------- spoken admin commands
    R(r"^voice ", "names of members and branches", "members", "SQLite", "owners (managers within their branches)",
      "log_days", "s19", OK, "test_an_owner_restricts_at_once_and_loosens_with_a_confirm; test_a_role_change_by_voice_is_confirmed_first"),
    # ---------------------------------------------------------------- background threads
    R(r"^worker worker$", "recordings to text, notes to the map", "speakers; people named",
      "Whisper and Gemma on this PC; Claude / Deepgram only behind the owner's gate",
      "the workspace as the speaker sees it", "audio_days, transcript_days", "s9-12, s72, s26, s71", OK,
      "test_no_note_leaves_this_pc_while_the_gate_is_off; test_recordings_stay_on_this_pc_while_the_gate_is_off; test_a_note_with_a_workers_health_is_held_for_the_owners"),
    R(r"^worker stt-warm$", "none (loads the speech model)", "-", "-", "-", "-", "-", OK,
      "test_health_reports_speech_model_state"),
    R(r"^worker retention$", "-", "-", "deletes what is past its period, on every brain (hubs too)", "-",
      "the owner's periods; NC_BRAIN_ARCHIVE_DAYS", "s14", OK,
      "test_old_recordings_transcripts_and_log_go_new_ones_stay; test_old_archives_go_when_the_pc_sets_a_period"),
    R(r"^worker sync$", "every synced row", "everyone", "the edge node or Supabase", "other brains",
      "journal compacted on purge", "s19-21, s72", HUMAN,
      "test_the_journal_keeps_only_the_newest_change_of_each_row; popia-human-actions.md#operators"),
    # ---------------------------------------------------------------- synced tables
    R(r"^sync ", "the table's rows", "people in them", "edge node / Supabase; phones (device copy)",
      "each receiver checks the author's role", "as the source", "s19-21", OK,
      "test_seats_scopes_invites_and_devices_sync; test_a_stale_worker_cannot_push_what_a_demoted_member_did"),
    # ---------------------------------------------------------------- files, logs, copies
    R(r"^files log$", "IP addresses, paths, refusals (no token, ticket or invite code)", "anyone calling",
      "data/<brain>/logs/api.log", "whoever runs the PC", "weekly, 4 weeks", "s19, s22", OK,
      "test_the_log_never_holds_a_token_a_ticket_or_an_invite_code; test_answers_carry_security_headers_and_refusals_are_logged"),
    R(r"^files archive$", "removed workspaces and backups of data/", "everyone in them", "data/archive on this PC",
      "whoever runs the PC", "NC_BRAIN_ARCHIVE_DAYS (unset: kept)", "s14, s19", HUMAN,
      "test_old_archives_go_when_the_pc_sets_a_period; popia-human-actions.md#archive"),
    R(r"^files disk$", "everything in data/", "everyone", "the PC's disk", "whoever can sign in to the PC", "-",
      "s19", HUMAN, "services/start_notecad.ps1; popia-human-actions.md#disk"),
    R(r"^files ci$", "none (made-up farms in tests)", "-", "GitHub Actions (public repo)", "anyone", "90 days",
      "-", OK, ".github/workflows/ci.yml"),
    R(r"^files drive$", "Ionity's own documents (no NoteCad data)", "Ionity staff named as authors", "Google Drive",
      "Ionity", "Ionity's policy", "s20-21", HUMAN, "popia-human-actions.md#operators"),
    # ---------------------------------------------------------------- the apps
    R(r"^desktop (record|type)$", "voice, what was said", "the owner", "the brain on this PC", "-", "audio_days",
      "s9-12", OK, "apps/desktop/src/lib/recorder.ts; test_capture_is_idempotent"),
    R(r"^desktop (notice|people|erase)$", "notice, members, erasure", "members, people named", "the brain", "owners",
      "-", "s18, s23-24", OK, "apps/desktop/src/components/PrivacyNotice.tsx; desktop:privacy.test.ts"),
    R(r"^phone (record|bubble)$", "voice", "the member", "the phone's outbox, then the brain (pinned HTTPS)",
      "the member", "deleted after upload; audio_days", "s18, s19", OK,
      "apps/mobile/src/lib/outbox.ts; android:TlsPinTest"),
    R(r"^phone (copy|pair|token|notice|mycopy)$", "the member's copy, token, pin", "the member", "phone storage",
      "the member", "wiped on revoke", "s19, s23", OK,
      "android:TokenVaultTest; android:OutboxStoreTest; mobile:pairing.test.ts"),
]

APP_ACTIONS = {  # app actions: the file that does each (must exist)
    "desktop record": "apps/desktop/src/lib/recorder.ts", "desktop type": "apps/desktop/src/components/RecorderHUD.tsx",
    "desktop notice": "apps/desktop/src/components/PrivacyNotice.tsx",
    "desktop people": "apps/desktop/src/components/PeoplePanel.tsx",
    "desktop erase": "apps/desktop/src/components/Inspector.tsx",
    "phone record": "apps/mobile/src/lib/phone.ts", "phone bubble": "apps/mobile/android/app/src/main/java/today/ionity/notecad/BubbleService.java",
    "phone copy": "apps/mobile/src/lib/devicecopy.ts", "phone pair": "apps/mobile/src/lib/pairing.ts",
    "phone token": "apps/mobile/android/app/src/main/java/today/ionity/notecad/TokenVault.java",
    "phone notice": "apps/mobile/src/components/PrivacySheet.tsx", "phone mycopy": "apps/mobile/src/components/Home.tsx",
    "files log": "services/brain/notecad_brain/serve.py", "files archive": "services/brain/notecad_brain/retention.py",
    "files disk": "services/start_notecad.ps1", "files ci": ".github/workflows/ci.yml",
    "files drive": "CLAUDE.md",
}


def actions() -> list[str]:
    from notecad_brain import admin
    from notecad_brain.api import create_app
    from notecad_brain.config import Settings
    from notecad_brain.pipeline import Brain
    from notecad_brain.routers import RouterChain, RulesRouter
    from notecad_brain.sync import TABLES
    from notecad_companion.api import create_app as companion_app
    from notecad_companion.config import Settings as CSettings
    from notecad_companion.embed import HashEmbedder

    s = Settings()
    s.db_url, s.worker, s.stt_engines, s.ui_dir = "sqlite:///:memory:", False, "", ""
    tmp = tempfile.mkdtemp()
    s.audio_dir = str(Path(tmp) / "audio")
    out = []
    for path, ops in create_app(Brain(s, routers=RouterChain([RulesRouter()]), embedder=HashEmbedder(64))).openapi()["paths"].items():
        out += [f"endpoint {m.upper()} {path}" for m in ops]
    cs = CSettings()
    cs.data_dir = tmp
    for path, ops in companion_app(cs).openapi()["paths"].items():
        out += [f"companion {m.upper()} {path}" for m in ops]
    out += [f"voice {name.lower()}" for name in ("VIS", "ROLE", "WHO") if hasattr(admin, name)]
    src = (BRAIN / "notecad_brain" / "api.py").read_text(encoding="utf-8") + \
        (BRAIN / "notecad_brain" / "sync.py").read_text(encoding="utf-8")
    out += [f"worker {n}" for n in sorted(set(re.findall(r'name="notecad-([\w-]+)"', src)))]
    out += [f"sync {t}" for t in TABLES]
    out += list(APP_ACTIONS)
    return out


def tests_known() -> set[str]:
    names = set()
    for f in (BRAIN / "tests").glob("*.py"):
        names |= set(re.findall(r"^def (test_\w+)", f.read_text(encoding="utf-8"), re.M))
    for f in (REPO / "services" / "companion" / "tests").glob("*.py"):
        names |= {f"companion:{n}" for n in re.findall(r"^def (test_\w+)", f.read_text(encoding="utf-8"), re.M)}
    for f in (REPO / "apps" / "mobile" / "android" / "app" / "src" / "test").rglob("*.java"):
        names.add(f"android:{f.stem}")
    for app in ("desktop", "mobile"):
        for f in (REPO / "apps" / app / "src").rglob("*.test.ts*"):
            names.add(f"{app}:{f.name}")
    return names


def evidence_ok(ev: str, known: set[str]) -> list[str]:
    bad = []
    for part in [x.strip() for x in ev.split(";")]:
        if part.startswith(("test_", "companion:", "android:", "desktop:", "mobile:")):
            if part not in known:
                bad.append(part)
        elif part.startswith("popia-human-actions.md"):
            anchor = part.split("#")[1] if "#" in part else ""
            doc = (OUT.parent / "popia-human-actions.md")
            if not doc.exists() or f'<a id="{anchor}">' not in doc.read_text(encoding="utf-8"):
                bad.append(part)
        elif not (REPO / part).exists():
            bad.append(part)
    return bad


def render(rows: list[tuple[str, Rule]]) -> str:
    n_ok = sum(r.status == OK for _, r in rows)
    lines = [
        "<!--",
        "  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI",
        "  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>",
        "  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved",
        "  Web: https://www.ionity.today | Ref: https://www.ionity.co.za",
        "  Generated by services/brain/tools/popia_inventory.py: do not edit by hand.",
        "-->",
        "",
        "# POPIA action register",
        "",
        "Every action NoteCad takes on personal information, read from the code (routes, spoken commands, background "
        "threads, synced tables, app actions). Technical compliance check, not legal advice. Rows that need a person "
        "to decide point at [popia-human-actions.md](popia-human-actions.md).",
        "",
        f"**{len(rows)} actions: {n_ok} compliant, {len(rows) - n_ok} need a human decision.**",
        "",
        "| Action | Surface | Personal info touched | Data subjects | Where it goes | Who can read it | Retention | POPIA | Status | Evidence |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, r in rows:
        surface, action = key.split(" ", 1)
        ev = "<br>".join(x.strip() for x in r.evidence.split(";"))
        lines.append(f"| `{action}` | {surface} | {r.what} | {r.who} | {r.where} | {r.reads} | {r.keep} | {r.popia} "
                     f"| {r.status} | {ev} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    acts = actions()
    rows, unmatched = [], []
    for a in acts:
        rule = next((r for r in RULES if re.search(r.match, a)), None)
        if rule is None:
            unmatched.append(a)
        else:
            rows.append((a, rule))
    known = tests_known()
    missing = sorted({b for _, r in rows for b in evidence_ok(r.evidence, known)})
    missing += [f for f in APP_ACTIONS.values() if not (REPO / f).exists()]
    text = render(rows)
    if unmatched or missing:
        print("actions without a rule:", *unmatched, sep="\n  ") if unmatched else None
        print("evidence not found:", *missing, sep="\n  ") if missing else None
        raise SystemExit(1)
    if "--check" in sys.argv:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8").replace("\r\n", "\n") == text
        print(f"up to date: {len(rows)} actions" if ok else f"{OUT.name} is out of date: run this tool")
        raise SystemExit(0 if ok else 1)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(rows)} actions)")


if __name__ == "__main__":
    main()
