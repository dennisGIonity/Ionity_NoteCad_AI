<!--
  Ionity Business Mind Map (IBMM) - Beta 1 | What it is: proof of concept and scope
  Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
  Classification: CONFIDENTIAL - BETA TESTERS ONLY
  Blueprint: ION-ARC-NOTECAD-2026-001 v1.2
-->

# IBMM Beta 1 - What it is, what the proof of concept shows, and what is in scope

## 1. In one paragraph

**Ionity Business Mind Map (IBMM)** is a voice-first workspace for people who run a business with their hands busy -
the first target is a farm. The owner (or a worker) holds one key and talks: *"Wheel needs changing on tractor John
Deere 9550, number 1."* IBMM writes it down, works out where it belongs, and files it on a live **mind map of the
whole business** as a note, a task, an alert, progress or a job delegated to a named person. The map shows at a glance
what is fine (green), what needs attention (amber) and what is broken (red), all the way up from one tractor to the
whole farm. It runs **on the owner's own PC, offline**, with small AI models that live inside the app and learn how
their owner speaks.

## 2. The problem it solves

People who run farms and field businesses keep the state of the business in their heads, on scraps of paper and in
WhatsApp threads. Typing into a form or a spreadsheet while standing next to a broken pump does not happen, so
problems are forgotten, work is not handed on, and nobody can see the whole picture. IBMM's bet is that **speaking
one sentence** is cheap enough to happen every time, and that software can do the filing.

## 3. How it works

```
 hold Space and talk         speech to text            understand                     file                       see it
 (desktop, phone bubble) ──► Whisper on the PC ──► split into events ──► router chain ──► one transaction ──► live mind map
                              (EN + Afrikaans)      find candidate       Claude (opt.)    note / task /        status colours
                                                    branches             Gemma 4 (local)  alert / progress /   roll up the tree
                                                                         rules (always)   delegation + Undo
                                       not sure? ──► Inbox: the owner picks the branch once, IBMM learns the alias
```

- **The brain** (Python, FastAPI, SQLite) does the work: transcription, splitting a note into events, finding the
  right branch, choosing actions, validating them and applying them in one transaction that can be undone.
- **Three routers in a chain:** Claude (only if a key is set and the owner allows cloud use), **Gemma 4 E2B running on
  the PC's graphics card**, and plain rules that always work. Guards check whatever a model proposes; a model can
  never invent a top-level branch, a number that was not spoken, or a person who does not exist.
- **The companion** is a second small model that belongs to one person, learns their words, reply style and weekly
  rhythm, and answers "what is left to do?" from the live map.
- **The desktop app** (React) has two modes: a glass **recorder pill** and an interactive, **foldable mind map** with a
  drawer for each node (history, voice playback, open work, "record here", ask the companion).
- **The phone app** (Android) records into an outbox first and uploads when it can reach the PC, so nothing is lost
  in a dead zone. A floating capture bubble records from any screen.
- **Sync-ready data:** every change is journalled, so a second PC or an "Edge AI Node" in the farm office can hold a
  copy and stay in step. Roles (owner, manager, employee) decide who sees and changes which branch.

## 4. What this proof of concept sets out to prove

| # | Claim | Evidence so far (on the reference PC: Windows 11, RTX 4060 8 GB) |
|---|---|---|
| H1 | One spoken sentence can be filed in the right place, with the right action, without the user choosing anything | Showcase notes 3/3; 20 golden field notes: **95.2 %** right first time with local Gemma + guards (target 85 %), 81 % with rules alone |
| H2 | It can run entirely on an ordinary owner's PC, offline, without a cloud account | Gemma 4 E2B, EmbeddingGemma and Whisper together fit in 8 GB VRAM; no internet needed after install |
| H3 | It is fast enough to use in the moment | Typed notes about 2-4 s to "filed"; spoken notes about 3-5 s (one longer case about 12 s, being tuned); warm start of the whole stack 17-22 s |
| H4 | One sentence can create structure, not only text | "John Deere 9550 number 1" creates *Vehicles › Tractors › John Deere 9550 #1* if missing and never confuses #1 with #2; "fields south 704 to 708" creates five fields and rolls up planting progress |
| H5 | Mistakes are cheap | Every note is one transaction with an inverse: **Undo** removes exactly what it added. Unsure notes go to the Inbox instead of guessing |
| H6 | It can grow from one person to a team without starting again | Roles and per-branch visibility, invites with per-phone keys, sync between brains with a journal - all built and tested |
| H7 | It can meet South African privacy law (POPIA) by design | 133 actions on personal information audited: 120 compliant in code, 13 waiting on human/legal decisions (Ionity's, not the tester's) |
| H8 | Afrikaans works | Whisper picks English or Afrikaans by itself. Afrikaans word error rate is **34.7 %** on a public test set (English 6.1 %). **Not yet good enough** - Beta 1 needs real farm recordings to decide the next step |

What Beta 1 is for: checking H1, H3, H5 and H8 **with real people, real voices and real PCs** other than the one it
was built on, and finding everything that breaks.

## 5. Scope of Beta 1

### 5.1 In scope - please test

| Area | What |
|---|---|
| Install | Clean install on your Windows PC with the set-up script; start, stop, status; CPU-only and NVIDIA PCs |
| Capture | Voice notes (hold Space), typed notes (`/`), English and Afrikaans, mixed sentences, several events in one note |
| Filing | Right branch, right action (note, task, alert, progress, delegation), new assets and ranges created sensibly |
| Inbox | Notes IBMM is unsure about; choosing a branch; IBMM remembering your word for it next time |
| Undo | The toast's Undo, right after a note |
| Mind map | Main areas view, folding and unfolding, keyboard navigation, zoom, radial / tree layout, search ("Go to a node"), light and dark mode |
| Node drawer | History, playing back the voice note, open tasks and alerts, **Record note for this node**, asking the companion |
| Companion | "What is left to do?", questions about one node, whether it adapts to how you talk |
| Roles | (roles demo farm) Owner, manager and employee views; restricted branches (e.g. Financials); invites; spoken admin commands |
| Privacy | The privacy notice on first use; export and erasure of one person |
| Phones (if you have Android) | Pairing by QR, recording in the app and with the bubble, recording with no Wi-Fi and seeing it arrive later |
| Speed and stability | How long notes take, whether anything hangs, crashes or gets slower over a session |

### 5.2 Out of scope for Beta 1 - please do not spend time on

| Area | Why |
|---|---|
| iPhone app | Needs a Mac to build and sign; planned for a later beta |
| The Tauri desktop window (`-Ui desktop`) | Unsigned; Windows Smart App Control blocks it. The browser app is the same app |
| Cloud: Supabase, Claude, Deepgram | Off by default and waiting on operator agreements (POPIA). Only test if Dennis asks |
| Sync between two separate PCs | Works on one PC with the Edge AI Node; multi-PC farms are a later phase |
| Billing and seat payments | Seats are a local ledger only; no payment provider |
| Push notifications to phones | Not built yet |
| Security / penetration testing | Welcome later, by arrangement - not part of this beta |
| Real business data | Please use the demo farms or made-up data only |

### 5.3 Known limitations (no need to report these)

- Afrikaans accuracy is noticeably lower than English (see H8). **Do** send examples of what it got wrong - that is useful.
- The very first start downloads the speech model (about 1.6 GB) and takes several minutes.
- On a PC without an NVIDIA card voice notes are much slower; typed notes are fine.
- The Android APK is a debug build (not from the Play Store); Android shows a warning when you install it.
- The status table shows `WARN` for disk encryption on PCs without BitLocker / Device Encryption.
- "Sync now" does nothing useful unless you started with `-EdgeNode`.
- Employees cannot create new top-level branches or child nodes by design; their notes about new things go to the
  owner's Inbox as proposals.

## 6. Privacy in this beta

- Everything stays on the test PC: database, recordings, transcripts and models are files under `<IBMM>\data` and
  `<IBMM>\models`.
- No cloud service is called unless a key is added **and** the owner ticks the cloud transfer in the privacy notice.
- Each business has a privacy notice that the owner accepts and each member reads before their first note.
- Owners can export everything about one person, or erase that person (POPIA sections 23 and 24).
- Logs blank out tokens, tickets and invite codes.

The POPIA assessment (technical, not legal advice) is in `source\IBMM\docs\compliance\`.

## 7. What happens after Beta 1

| Next | Depends on |
|---|---|
| Choose between the current speech model and a more accurate (slower) one for Afrikaans | Tester recordings and reports |
| Signed Windows app and Play Store build | Code-signing certificate and release key |
| iPhone app | Build and sign on a Mac |
| Cloud sync for multi-site farms (Supabase, South African region) | Operator agreements and lawful-basis wording (POPIA) |
| Reminders, routines and push notifications | Beta 1 feedback on tasks and alerts |

## 8. Words used in IBMM

| Word | Meaning |
|---|---|
| **Workspace** | One business and its map (e.g. the "showcase" demo farm) |
| **Main areas** | The top-level categories: Vehicles, Fields, Livestock, Irrigation, Infrastructure, Staff, Admin |
| **Node / branch** | Anything on the map: a category, a group (Tractors), an asset (John Deere 9550 #1), a field, a person |
| **Capture** | One note, spoken or typed, from recording to "filed" |
| **Router** | The part that decides what a note means: Claude, Gemma (local) or rules |
| **Inbox** | Notes IBMM was not sure about, and employees' proposals waiting for an owner |
| **Status colours** | Green fine, amber needs attention or work due, red broken or critical; a dot on a parent means something below it needs attention |
| **Roll-up** | Status and progress of children carried up to their parents, up to the whole farm |
| **Companion** | The personal assistant model that learns its owner |
| **Edge AI Node** | A second brain (e.g. in the farm office) that keeps a synced copy |
| **Brain** | The local service that does the filing; everything else talks to it |

---
Policy 986 AED | License AED 900 | (c) 2018-2026 Antwerp Designs | Ionity Global (Pty) Ltd - All rights reserved.
