<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# Breach runbook (POPIA s22)

A security compromise: someone who should not have got NoteCad data may have got it (a lost or stolen phone or PC, a
leaked token, an unknown device in People & seats, a copy of `data\` where it should not be). Technical runbook, not
legal advice; who decides and who tells whom is in [popia-human-actions.md](popia-human-actions.md#breach).

## 1. Stop it (minutes)

| What happened | Do this |
|---|---|
| A phone is lost or a member leaves | People & seats: **Remove** the member or the device. Its token stops at once (410) and the phone wipes its copy on its next contact |
| The shared token leaked | Delete `NC_BRAIN_API_TOKEN` from `E:\.claude\_vault\notecad.env`, restart (`-Lan` writes a new one), pair the phones again |
| The PC or `data\` was copied | Revoke every device; change the vault secrets; rotate the TLS certificate (delete `data\brain\tls`, restart with `-Lan`, pair the phones again) |
| A cloud processor reported a breach | Turn the cloud transfer off in the privacy notice (each workspace) |

## 2. Find out what and who (hours)

- `data\brain\logs\api.log` (and the four weekly files before it): `notecad.security` lines record every refused
  request (401, 403, 410, 429 with method, path and address), every person export and erasure, workspace deletions,
  the cloud transfer gate and each transfer. No token, ticket or invite code is ever written.
- `GET /api/v1/workspaces/<ws>/devices`: each device, when it was last seen, when it was removed and when it wiped.
- `GET /api/v1/workspaces/<ws>/audit`: who did what and when.
- People affected: the members of the workspace (People & seats) and the people named in it
  (`GET .../subjects/<id>/export` shows what is held about each one).

## 3. Tell (as soon as reasonably possible)

- The Information Regulator, with its breach form (inforegulator.org.za): what happened, when, what information, how
  many people, what was done.
- Each person affected, in writing (email, SMS or the app), unless the Regulator or SAPS says to wait: what happened,
  what it means for them, what they can do, who to contact.
- When Ionity is the farm's operator (it runs their edge node or Supabase): tell the farm owner first; they are the
  responsible party.

## 4. Afterwards

Write down what happened and what changed, in `docs\compliance\` (no personal information in the write-up).
