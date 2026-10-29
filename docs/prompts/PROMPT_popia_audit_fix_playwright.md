<!--
Ionity Global (Pty) Ltd | AEDI | Author: Dennis Grobler (Wabakipi)
Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-->

# Build prompt: POPIA action audit, fix every failure, full Playwright run

Paste everything below the line into a Claude Code session opened at `E:\.claude\Ionity\.NoteCad`.

---

You are working in the NoteCad repo. Read `CLAUDE.md` first, then `docs/BUILD_STATUS.md` (the POPIA and roles
sections), `docs/adr/0012`-`0014`, `docs/compliance/Ionity_NoteCad_POPIA_Assessment_v1.0.pdf` (the 29 October 2026
review: twelve findings, five built, seven open) and `services/brain/notecad_brain/{permissions,retention,privacy,
serve,tls,sync,api,apply,delegate,pipeline}.py`. Follow every rule in `CLAUDE.md`: licence headers, vault-only
secrets, nothing on C:, back up `data\` to `data\archive\popia2-<time>\` before anything touches a database,
forward-only migrations in step with Supabase (`gen_rls_migration.py --check`), a guard plus a regression test for
every fix, Git identity from config, never force-push.

This is a technical compliance check, not legal advice. Where a finding needs a human or legal decision
(Information Officer, operator agreements, a lawful basis), write it down for me; don't decide it.

The work has three parts, in this order. Don't move on until each part's exit check passes.

## Part 1: check every action against POPIA

### 1a. Inventory every action

Build `docs/compliance/popia-action-register.md` (a table, generated where possible by
`tools/popia_inventory.py` from the FastAPI routes, the voice admin commands, the worker jobs, the sync paths and
the phone/desktop UI actions, so it can't drift; add `--check` to CI). One row per action:

| Column | Meaning |
|---|---|
| Action | e.g. capture audio, transcribe, route to Claude, delegate "Ask Sipho", join with invite, revoke seat, sync push/pull, export, delete workspace, retention purge, audio playback, companion LoRA training, log write, archive |
| Surface | endpoint / voice / worker / phone / desktop / CI |
| Personal info touched | voice, names, contact, location (fields, boreholes), device ids, tokens, IP, work performance, anything that could be special personal info (s26: health, religion, biometrics, etc.) or about children (s34) |
| Data subjects | owner, manager, employee, third parties named in a note |
| Where it goes | SQLite, Supabase, edge node, phone storage, logs, archive, Anthropic API, Deepgram, Google Drive |
| Who can read it | by role and visibility (cite `permissions.py`) |
| Retention | which period in `retention.py` covers it, or "none" |
| POPIA sections | the conditions it touches (below) |
| Status | compliant / gap / needs human decision, with the evidence: file:line and the test that proves it |

### 1b. Test each action against the eight conditions and the extra rules

- **Accountability (s8):** an Information Officer named in the privacy notice; who does what is written down.
- **Processing limitation (s9-12):** minimality (does each action collect only what it needs: e.g. is the raw
  recording kept when the transcript is enough?), a lawful basis per purpose (s11: consent, contract, legitimate
  interest), the right to object, collection from the data subject. Employees' voices and their work records count.
- **Purpose specification (s13-14):** a stated purpose per action; retention periods cover *every* copy: SQLite,
  Supabase, the edge node, phone copies, `sync_changes`, `view_changes`, `data\archive`, logs, audio files, LoRA
  adapters and companion memory, CI artifacts, Google Drive copies.
- **Further processing (s15):** training the per-owner LoRA or companion memory on employees' captures is a new
  purpose; check it's covered or gated.
- **Information quality (s16):** people can correct a wrong transcript or mis-filed note about themselves.
- **Openness (s17-18):** the privacy notice says everything s18 needs, including cloud processors and transfers;
  every member sees it before their first capture (check the phone *and* desktop, and that a capture is blocked or
  flagged until it is read).
- **Security safeguards (s19-22):** tokens hashed, no tokens or invite codes in URLs or logs, TLS pinning on the
  LAN, Keystore for the phone token (open), BitLocker or equivalent check on WABAKIPI (open), security headers
  (open), rate limits on `/v1/join` and invite codes, revoked devices wiped, the loopback trust note (open), and a
  breach-notification runbook (s22): what is logged so a breach can be found and reported to the Regulator and the
  people affected.
- **Operators (s20-21):** Anthropic, Deepgram, Supabase, Google: written down as operators, and nothing goes to them
  without the gate in the next bullet.
- **Cross-border transfer (s72):** Claude routing, Deepgram and a non-SA Supabase region send personal info out of
  South Africa. Build or verify the **cloud-transfer gate** (open): off by default, an owner turns it on per
  workspace after the notice says so, it is logged, and restricted branches (e.g. Financials) never leave the PC.
  Test that with the gate off no request leaves for those hosts (mock the network).
- **Data subject participation (s23-25):** **per-person export and erasure** (open): a member, or a person named
  in notes who isn't a member, can get a copy of everything about them and have it erased or de-identified, across
  every copy listed above, including the next sync to phones and the hub. Respect what must be kept (audit records),
  and say so.
- **Special personal info (s26-33) and children (s34-35):** voice is not treated as biometric unless used to
  identify someone; check the speaker/companion code doesn't do that. Flag notes that would hold health or
  disciplinary details about workers and how they're protected (restricted visibility at least).
- **Direct marketing (s69) and automated decisions (s71):** check that no action messages people outside the
  business, and that routing/delegation is never a decision with legal effect on a worker without a person in the
  loop.
- **Monitoring of employees:** capturing employees' recordings and task progress is workplace monitoring; check
  the notice says so and employees can see their own activity (`.../audit` for employees).

### 1c. Fix

Fix every gap you can fix in code, smallest change first, each with a regression test in `tests/test_popia*.py`
(brain), Vitest (desktop/phone) or Android unit tests. Include the seven open findings from the assessment. Things
that need a human (Information Officer registration with the Regulator, operator agreements, the lawful basis
wording, a legal review) go into `docs/compliance/popia-human-actions.md` with what I have to do and why.

**Exit check, Part 1:** every row in the register is "compliant" or "needs human decision" with evidence;
`popia_inventory.py --check` passes; new tests pass.

## Part 2: fix every failing task

Run the complete matrix on WABAKIPI and collect every failure first, then fix them; don't stop at the first:

```powershell
cd services\brain
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check .; .venv\Scripts\pyright.exe
.venv\Scripts\python.exe tools\gen_sync_migration.py --check
.venv\Scripts\python.exe tools\gen_rls_migration.py --check
cd ..\companion; ..\brain\.venv\Scripts\ruff.exe check .; .venv\Scripts\python.exe -m pytest -q
cd ..\..\apps\desktop; npm.cmd ci --include=dev; npm.cmd run build; npm.cmd run lint; npm.cmd test
cd ..\mobile; npm.cmd ci --include=dev; npm.cmd run build; npm.cmd run lint; npm.cmd test
```

Then push and read the latest GitHub Actions run (Postgres 17, Supabase 0001-0009 twice, Android unit tests, APK,
`cargo check`, Tauri installers) from its notices and annotations; fix anything failing there too. Also go through
every "Open" item in `docs/BUILD_STATUS.md` and the field test (`tools\field_test.py --routers local,rules --embed
openai`, the 20 golden notes; `--showcase`): fix what can be fixed here, and list what can't with the reason (needs a
real phone, a Mac, a signing key, an API key).

Rules: fix the cause, not the test. Never skip, delete, loosen or mark xfail a test to make it pass unless you show
me why the test itself is wrong. A flaky test gets its flake found (timing, port, order) and fixed. When the model
routes something wrong, add a guard and a regression test.

**Exit check, Part 2:** every command above exits 0 on WABAKIPI, the CI run is green, and the field test is at
least as good as the last numbers in `docs/BUILD_STATUS.md`.

## Part 3: the full Playwright run

```powershell
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Showcase -NoOpen
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Status     # all green before testing
cd services\brain; .venv\Scripts\python.exe tools\seed_farm_showcase.py --reset-clean --id roles-showcase
cd ..\..\apps\desktop
npm.cmd run test:e2e                                                          # every spec
$env:NC_E2E_WS='roles-showcase'; npx.cmd playwright test e2e/roles.spec.ts
$env:NC_SHOTS=1; npx.cmd playwright test e2e/fold.spec.ts
```

Also run the stack with `-Lan` and check the pinned HTTPS path (phone dev server on :5174 paired through
`?pair=...`), and add e2e specs for what Part 1 built: the privacy notice gating the first capture for a new
member, per-person export and erasure (the erased person disappears from map, search, digest, export and an
employee's next pull), the cloud-transfer gate (off: no request to Anthropic/Deepgram), and no token or invite code
in any URL the browser loads (check the network log) or in `api.log`.

Run the whole suite three times in a row; all three must pass (that's how flakes show up). Playwright uses the
installed Edge (`channel: 'msedge'`). Compare frame rates with the same run's idle rate.

**Exit check, Part 3:** three green full runs; the HTML report and any screenshots in `docs\media`.

## When you finish

- Update `docs/BUILD_STATUS.md` (new section, newest first: built, verified with counts, still open), `CLAUDE.md`
  for any new command or endpoint, and the POPIA assessment as v1.1 in the official Ionity template
  (`docs/compliance/Ionity_NoteCad_POPIA_Assessment_v1.1.docx` + PDF), also to Google Drive.
- Commit in small, named steps.
- Give me: the register summary (how many actions, how many compliant / fixed / need me), the test counts before
  and after, what failed and what fixed it, and my human-action list.

Ask me before: turning any cloud transfer on, deleting or erasing any real workspace data (use `roles-showcase` and
test workspaces), changing a retention period on a real workspace, or choosing wording that commits Ionity to a
legal position.
