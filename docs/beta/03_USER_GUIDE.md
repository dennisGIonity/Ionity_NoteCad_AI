<!--
  Ionity Business Mind Map (IBMM) - Beta 1 | User guide and beta test script
  Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
  Classification: CONFIDENTIAL - BETA TESTERS ONLY
-->

# IBMM Beta 1 - User guide

This guide assumes IBMM is installed and running (see `01_DEPLOYMENT_AND_INSTALLATION.md`) and you have opened
**http://127.0.0.1:8788/** with the demo farm loaded (`start_notecad.ps1 -Showcase`).

## 1. The screen

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Workspace ▾ [Main areas] [−1] [+1] [Expand all] [Collapse all]  Level 2 [Find]│  ← map toolbar
│                                                                               │
│                     Vehicles ──── Tractors ──── John Deere 9550 #1 (amber)    │
│          Farm ──┬── Fields ──── South Block ─── +5 · 3 tasks                  │  ← the mind map
│                 ├── Water                                                     │
│                 └── Admin                                    ┌──────────────┐ │
│                                                              │ node drawer  │ │  ← opens when you
│                                                              │ history, ▶   │ │     click a node
│                ╭──────────────────────────────╮              └──────────────┘ │
│                │  ● Hold Space   ∿∿∿∿∿   ⌨   │    Inbox (1)     [status chip] │  ← recorder pill,
│                ╰──────────────────────────────╯                               │     Inbox, status
└───────────────────────────────────────────────────────────────────────────────┘
```

The app follows your Windows light or dark theme. Press **M** to switch between the map and the recorder-only view.

## 2. Record a note

| Do this | How |
|---|---|
| **Voice note** | Press and **hold Space**, talk, let go. Or press and hold the pill with the mouse. The waveform shows the mic is hearing you |
| **Cancel** a recording | Press **Esc** while recording |
| **Typed note** | Press **/** (or the keyboard icon "Type instead"), type, press Enter |
| **Note about one thing** | Click the node on the map, then use **Record note for this node** in its drawer (or hold Space while it is selected). IBMM files the note there first |

The first time, the browser asks for the microphone: choose **Allow**. If you are a member who has not read the
business's privacy notice yet, IBMM shows it first - read it and close it, then record.

**Talk the way you would to a foreman.** Examples that work on the demo farm:

- *"Wheel needs changing on tractor model John Deere 9550 - number 1"* → a task on *Vehicles › Tractors › John Deere 9550 #1*, which turns amber
- *"Today I planted field south 704 to 708"* → five fields created under *Fields › South Block*, planting progress 100 % on each and rolled up
- *"Ask Sipho to check the water pump on the North borehole"* → a task on the pump, delegated to Sipho
- *"The south borehole pump is leaking badly"* → a problem on *Water › South Borehole Pump*; it turns red or amber and *Water* shows a dot
- *"Die Hilux se battery is pap"* → Afrikaans works the same way (a note on *Vehicles › Bakkies › Toyota Hilux*)
- Several things in one breath: *"Fixed the fence at the north gate and centre pivot 2 is making a noise"* → two events, filed separately

The demo farm has: *Vehicles* (tractors John Deere 9550 #1 and #2, Case IH Magnum 340; bakkie Toyota Hilux), *Fields*
(South Block 704-708, North Block 101-102), *Water* (North and South Borehole Pumps, Centre Pivot 2), *Livestock* (cattle,
sheep), *Infrastructure* (fencing), *Admin › Staff* (Sipho, Thandi, Thabo) and *Financials* (owners only).

### 2.1 What happens next

The pill shows each step live: **Received → Transcribing… → filing… → Filed** (or **Where should this go?**). A toast then tells you what was
done, for example *"Filed 2: Tractors › John Deere 9550 #1 - task"*, with:

- **Undo** - removes everything that note added (use it straight away if IBMM got it wrong, then say it again more clearly);
- **branch pills** - click one to jump to that place on the map, which unfolds just enough to show it.

If IBMM is not sure where a note belongs it does **not** guess: the note goes to the **Inbox**.

## 3. The Inbox

The Inbox button shows how many items are waiting. Open it to see:

- **Notes to place** - pick the right branch from the 2-3 suggestions (or leave it in the Inbox). IBMM remembers the
  words you used, so next time *"the big pump"* goes straight to *Main Water Pump*.
- **Proposals** - things employees asked for that need an owner: **Approve** or **Reject**.
- **Confirmations** - spoken admin commands waiting for one tap (see 6.2).

## 4. The mind map

### 4.1 Reading it

| You see | It means |
|---|---|
| Green | Fine |
| Amber | Needs attention or has work due |
| Red | Broken, alert, critical |
| A coloured **dot** on a parent | Something further down needs attention, even if that branch is folded |
| A progress bar / ring | Progress of the work below (e.g. fields planted) |
| **+14 · 2 alerts · 3 tasks** badge | A folded branch: 14 hidden nodes, with that much open work inside |
| A lock | A restricted branch (only managers or owners see it) |
| A brief pulse | A note just changed something inside that branch |

### 4.2 Folding and moving around

The map opens on **Main areas** (the farm and its top-level categories, such as Vehicles, Fields, Water, Livestock). Open it up only as far as you need.

| Toolbar | Does |
|---|---|
| **Main areas** | Back to the farm and its categories only |
| **+1 / −1** (Expand / Collapse one level) | One level deeper or shallower everywhere; the stepper shows *Level N* |
| **Expand all / Collapse all** | The whole tree / just the root |
| **Fit to screen**, **Zoom in/out** | View |
| **Radial / Tree layout** | Two ways of drawing the same map |
| **Find on the map** / **Go to a node** | Search by name; opens just the path to it |

| On a node | Does |
|---|---|
| Click the **chevron** | Open that node's next level |
| **Shift+click** the chevron | Open everything below it |
| **Right-click** | *Expand all below*, *Collapse all below*, *Focus this branch* |
| **Click** the node | Open its drawer |

Keyboard (click the map first): **↑ ↓** move, **→** open / go to first child, **←** close / go to parent,
**Shift+→ / Shift+←** open / close everything below, **Home / End**, **Enter** opens the drawer. Space stays
"hold to record" and **/** stays "type a note".

IBMM remembers how you left the map folded (per workspace and layout, on this PC only).

### 4.3 The node drawer

Click a node to open its drawer:

- **Header** - name, path, status, progress, identity (make, model, unit number).
- **Record note for this node** - a note recorded here goes to this node first.
- **Open work** - tasks (tick to finish, see who it is for) and alerts.
- **History** - every note that touched this node, newest first, with the time and **▶ Play the voice note**.
- **Ask the companion** - ask about this node: *"What still needs doing here?"*, *"When was this last serviced?"*
- **Who can see this branch** (owners and managers) - Everyone / Managers / Owners only.

## 5. The companion

The companion is your own assistant. Ask it things like *"What is left to do today?"*, *"What is wrong with the
irrigation?"* or *"Hou dit kort"* (keep it short) - it adapts its reply length and tone to you over time and learns
your words for things, which also helps speech recognition. It answers from the live map, so it only knows what has
been recorded.

## 6. People, roles and phones

Use the roles demo farm for this section (`seed_farm_showcase.py --reset-clean --id roles-showcase`, then pick
**roles-showcase** in the Workspace menu).

### 6.1 Roles

| Role | Can |
|---|---|
| **Owner** | Everything: all branches, people and seats, privacy settings, export, erase |
| **Manager** | Run the work: record, assign, see manager-level branches; not owner-only branches |
| **Employee** | Record notes and do their tasks on branches they can see; cannot create new branches (their requests become Inbox proposals) |

Restricted branches (for example **Financials**, owners only) are invisible to people below that level - not on the
map, not in search, not in the companion's answers.

### 6.2 Spoken admin commands (owners)

These use a fixed set of phrases, never the AI, so a misheard note can never grant access:

| English | Afrikaans | Result |
|---|---|---|
| "Make Thandi a manager" | "Maak Thandi 'n bestuurder" | Role change, after one tap to confirm |
| "Restrict Financials to owners only" | "Beperk Finansies tot eienaars" | Tighter visibility, at once |
| "Make Financials visible to everyone" | "Maak Finansies sigbaar vir almal" | Looser visibility, after a confirm |
| "Who can see Financials?" | "Wie kan Finansies sien?" | An answer |

### 6.3 People & seats

Owners open **People & seats** from the status chip (bottom right) to see members, their roles and devices, to **Invite someone**
(a QR or a link that gives that person's phone its own key and role), change a role, revoke a device (the phone is
told to wipe its copy), reopen the privacy notice, and - for POPIA - make **a copy of everything about one person** or **erase this person**.

### 6.4 The status chip and phones

The chip at the bottom right shows the local store and sync: changes waiting to send, last sync, notes in flight.
From it: **People & seats** (owners), **Pair a phone** (a QR for the Android app, when the brain was started with `-Lan`) and **Sync now** (when an
Edge AI Node is running).

On the phone: pick where a note should go with **Record onto** (main areas first, then one branch at a time, or
search), tap the big record button, or switch on the **Capture bubble** to record from any screen (tap to start, tap
to save, drag to move, long-press to close). Notes are kept on the phone and sent when it can reach the PC - you can
record with no signal.

## 7. Beta test script and how to report

### 7.1 Test script (about 60-90 minutes)

Tick each line and note anything odd. Times are rough; tell us yours.

| # | Do | Expect |
|---|---|---|
| 1 | Install with `setup_ibmm.ps1`, start with `-Showcase` | Health table green (Disk `WARN` is fine); app opens |
| 2 | Record the three example notes from section 2 by voice | Each filed in the right place within about 5 s (GPU) |
| 3 | Type the same three notes with `/` on a fresh farm (`--reset-clean`) | Same result, a bit faster |
| 4 | Record a note, then **Undo** | Everything it added disappears |
| 5 | Record something vague (*"sort out the thing by the old shed"*) | It goes to the Inbox; resolve it; say it again - now it files directly |
| 6 | Record 10 notes of your own about the farm, in your own words | Write down which were wrong and what you said |
| 7 | (Afrikaans speakers) Record 10 notes in Afrikaans, a few mixed with English | Note what the transcript said vs what you said |
| 8 | Map: Main areas → +1 → Expand all → Collapse all → reload the page | Fold state comes back after reload |
| 9 | Fold *Fields*, record a planting note for a field | *Fields* pulses and its badge updates without unfolding; the toast's branch pill reveals the field |
| 10 | Keyboard only: walk the map, open a drawer with Enter | Works without the mouse |
| 11 | Open a node with history; play a voice note | Audio plays |
| 12 | Ask the companion three questions | Sensible answers from the map |
| 13 | Roles farm: invite a second "person" in another browser profile as an employee | They never see *Financials*; their new-branch request lands in the owner's Inbox |
| 14 | Spoken admin commands from 6.2 | Confirmations work; employee view changes |
| 15 | (Android) Pair, record in the app, then with Wi-Fi off, then back on | The offline note arrives once, not twice |
| 16 | Leave it running for a working day; use it now and then | No slow-down, no crash; tell us start-up time the next morning |
| 17 | `start_notecad.ps1 -Stop`, then start again | Everything is still there |

### 7.2 Reporting a bug

Send each problem as its own email to **dennis.g@ionity.digital** with the subject `IBMM Beta 1 - <short title>`:

```
What I did:        (steps, and the exact words I said or typed)
What I expected:
What happened:     (screenshot if you can; the toast text; the transcript)
How often:         always / sometimes / once
When:              date and time (so the log lines can be found)
PC:                Windows version, CPU, RAM, graphics card (or CPU only)
Severity:          blocker / wrong result / annoying / cosmetic / idea
```

Attach the logs: from the package folder run

```powershell
powershell -ExecutionPolicy Bypass -File tools\collect_logs.ps1 -Root D:\IBMM
```

It writes `IBMM_logs_<PC>_<time>.zip` to your Desktop with the health table and the log files only - **no database,
no recordings, no keys**. Look inside before you send it if you like.

Wrong filing is the most valuable report: say exactly what you said, where it went, and where it should have gone.

### 7.3 At the end of the beta

Please send a short summary: what you liked, what got in the way, the three things you would fix first, and whether
you would use it every day. Then follow the uninstall steps in the deployment guide, or keep it for Beta 2.

---
Policy 986 AED | License AED 900 | (c) 2018-2026 Antwerp Designs | Ionity Global (Pty) Ltd - All rights reserved.
