<!--
  Ionity Business Mind Map (IBMM) - Beta 1 | Deployment and installation
  Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
  Classification: CONFIDENTIAL - BETA TESTERS ONLY
-->

# IBMM Beta 1 - Deployment and installation

This guide takes a clean Windows PC to a running IBMM in about an hour, most of it downloads. It covers the desktop
(the main thing to test), phones (optional) and what to do when something goes wrong.

## 1. What you are installing

IBMM is four local programs that talk to each other on your PC. Nothing needs the internet once it is installed.

| Part | Port | What it does |
|---|---|---|
| **Ollama** | 11434 | Runs the two local AI models on your graphics card: Gemma 4 E2B (understands notes, chats) and EmbeddingGemma (finds the right branch) |
| **Companion** | 8787 | The small assistant that learns its owner and answers questions about open work |
| **Brain** | 8788 | Turns speech into text (Whisper), files each note on the map, keeps the database (`data\brain\brain.db`), serves the app |
| **Desktop app** | in your browser | http://127.0.0.1:8788/ - the recorder and the mind map |

Optional: phones on the same Wi-Fi (HTTPS on port 9788) and an "Edge AI Node" sync hub (port 8789).

## 2. Requirements

| | Minimum | Recommended (what IBMM is built and measured on) |
|---|---|---|
| Windows | Windows 10 22H2 or 11, 64-bit | Windows 11 |
| CPU / RAM | 4 cores, 16 GB | 8 cores, 16-32 GB |
| Graphics | none (CPU only: works, but voice notes take several times longer) | NVIDIA RTX with **8 GB VRAM** or more (built on an RTX 4060 8 GB), current driver |
| Free disk | 15 GB | 25 GB on a fast SSD |
| Microphone | any | a headset mic, for clean recordings |
| Browser | Microsoft Edge or Chrome, current | Edge (the automated tests use it) |
| Rights | a normal user account | admin only once, if you test phones (firewall rule) |

Software to install first (all free, all signed, so Windows Smart App Control allows them):

| Software | Version | Where | Notes |
|---|---|---|---|
| Python | **3.13 or 3.14** (3.11 is the floor) | https://www.python.org/downloads/windows/ | Tick **"Add python.exe to PATH"**. The `py` launcher is fine too |
| Node.js | **24 LTS** (22 also builds) | https://nodejs.org/ | Only needed to build the app once |
| Ollama | current Windows release | https://ollama.com/download/windows | Leave it running in the tray after install |
| Git | optional | https://git-scm.com/ | Only if you prefer to clone instead of using `source\IBMM` |

Check them in a new PowerShell window:

```powershell
python --version      # Python 3.13.x or 3.14.x
node --version        # v24.x
ollama --version      # any
nvidia-smi            # (GPU only) shows your card and driver
```

## 3. Install (once)

### 3.1 Copy the source

Copy `source\IBMM` from this package to a folder of your own. Use a short path **without spaces**, on a drive
with room, for example `D:\IBMM`. Everything IBMM creates - models, database, recordings, logs - stays inside that
folder. In the rest of this guide that folder is called `<IBMM>`.

> **Tip if you will test phones:** the phone-pairing token is written to a fixed place, `E:\.claude\_vault\notecad.env`.
> If your PC has no E: drive, map one before step 3.2 with `subst E: C:\IBMM-E` (make the folder first). You can skip
> this if you are only testing the desktop.

### 3.2 Run the set-up script

Open PowerShell **in the package folder** (where this file is) and run:

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup_ibmm.ps1 -Root D:\IBMM
```

Add `-CpuOnly` if the PC has no NVIDIA card. The script:

1. checks Python, Node, Ollama and (if present) your NVIDIA card;
2. creates two Python environments, `services\companion\.venv` and `services\brain\.venv`, and installs IBMM into them
   (with Whisper and its GPU libraries unless `-CpuOnly`);
3. downloads the two Gemma models (about 3.4 GB) into `<IBMM>\models`;
4. installs the app's packages and builds the desktop app (`apps\desktop\dist`);
5. prints the start command.

It is safe to run again: finished steps are skipped. `-SkipModels` and `-SkipUi` skip steps 3 and 4.

The **speech model** (Whisper large-v3-turbo, about 1.6 GB) downloads by itself into `<IBMM>\models\whisper` the
first time the brain starts. That first start therefore takes a few minutes; later starts take about 20 seconds.

<details>
<summary>Manual install (what the script does, if you prefer to do it by hand)</summary>

```powershell
cd D:\IBMM
# companion
python -m venv services\companion\.venv
services\companion\.venv\Scripts\python.exe -m pip install -U pip
services\companion\.venv\Scripts\python.exe -m pip install -e services\companion
# brain (it uses the companion package too); use [whisper] instead of [whisper-gpu] without an NVIDIA card
python -m venv services\brain\.venv
services\brain\.venv\Scripts\python.exe -m pip install -U pip
services\brain\.venv\Scripts\python.exe -m pip install -e services\companion -e "services\brain[whisper-gpu]"
# models (3.4 GB)
powershell -ExecutionPolicy Bypass -File services\companion\tools\get_models.ps1 -Dest D:\IBMM\models
# desktop app
cd apps\desktop
npm.cmd ci --include=dev
npm.cmd run build
```
</details>

## 4. Start, check, stop

All commands run from `<IBMM>` in PowerShell.

```powershell
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Showcase   # first time: start + load the demo farm
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1             # every other time
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Status     # health table only
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Stop       # stop everything
```

The start script brings up Ollama, the companion and the brain, then prints a health table and opens
**http://127.0.0.1:8788/**. A healthy start has these rows at `OK`:

| Row | Healthy detail |
|---|---|
| Ollama `:11434` | `loaded: notecad-gemma4-e2b (... GB GPU), notecad-embeddinggemma ...` |
| Companion `:8787` | `model notecad-gemma4-e2b, embeddings ...` |
| Brain `:8788` | `sqlite ..., routers local,rules` (`claude,local,rules` if a Claude key is set) |
| Speech to text | `whisper on cuda` (or `on cpu`). `WAIT ... loading` for the first minute is normal |
| Desktop UI `:8788/app` | `http://127.0.0.1:8788/` |

`INFO` rows (Sync, Phones, This PC, Workspaces) are information only. A yellow `WARN` on **Disk** (not encrypted) is
expected on most test PCs and does not stop testing.

Useful switches: `-NoOpen` (do not open a browser), `-Rebuild` (rebuild the app), `-Ui none` (services only),
`-Lan` (phones, section 6), `-EdgeNode` (sync hub, section 6.4).

**Always open the app as `http://127.0.0.1:8788/` or `http://localhost:8788/`.** Other addresses (the PC's name or IP)
are treated as "from the network" and need a token.

### 4.1 Reset the demo farm

```powershell
cd <IBMM>\services\brain
.venv\Scripts\python.exe tools\seed_farm_showcase.py --reset-clean                       # fresh demo farm (old one archived first)
.venv\Scripts\python.exe tools\seed_farm_showcase.py --reset-clean --id roles-showcase   # demo farm with owner, manager and employees
.venv\Scripts\python.exe tools\seed_synthetic_farm.py                                    # a 2,000-node farm, for speed testing
```

Removed workspaces are saved to `<IBMM>\data\archive\` first, so nothing is lost by a reset.

## 5. Optional settings

IBMM works with no keys and no settings. The settings below are for specific tests only - ask Dennis before you use
them. They go in `E:\.claude\_vault\notecad.env` (one `NAME=value` per line), which `start_brain.ps1` reads at start.
Never put keys anywhere inside `<IBMM>`.

| Setting | Effect |
|---|---|
| `ANTHROPIC_API_KEY=...` | Adds Claude as the first router (better on unusual notes). **Nothing is sent** until the owner ticks the cloud transfer in the privacy notice |
| `NC_BRAIN_DEEPGRAM_KEY=...` | Adds Deepgram cloud speech-to-text (same cloud-transfer rule) |
| `NC_BRAIN_WHISPER_MODEL=small` | A smaller speech model: much faster on CPU-only PCs, less accurate (default `large-v3-turbo`; `large-v3` is more accurate for Afrikaans and twice as slow) |
| `NC_BRAIN_STT_LANGUAGES=en,af` | Languages Whisper may choose from (default English and Afrikaans) |
| `NC_BRAIN_TRUST_LOOPBACK=0` | On a PC several people sign in to: this PC is no longer trusted without a token |

For a one-off test you can also set a value in the same PowerShell window before starting, for example
`$env:NC_BRAIN_WHISPER_MODEL="small"`.

## 6. Phones (optional)

### 6.1 Allow phones through the firewall (once, as admin)

```powershell
powershell -ExecutionPolicy Bypass -File services\allow_phones_firewall.ps1           # Private networks, local subnet only
powershell -ExecutionPolicy Bypass -File services\allow_phones_firewall.ps1 -Check    # look
powershell -ExecutionPolicy Bypass -File services\allow_phones_firewall.ps1 -Remove   # undo after testing
```

Your Wi-Fi must be set to **Private** in Windows (Settings > Network > your network > Private).

### 6.2 Start with phones allowed

```powershell
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Lan
```

Phones talk to the brain over HTTPS on port **9788** with the brain's own certificate; the phone pins that certificate
during pairing, so no other server can pretend to be your brain.

### 6.3 Install and pair the Android app

1. Install the APK from `binaries\` (see `binaries\README.md`). Allow "Install unknown apps" for your file manager
   when Android asks. The APK is a **debug build, not signed for the Play Store** - that is expected for Beta 1.
2. On the desktop, click the **status chip** (bottom right of the map) > **Pair a phone**. A QR code appears.
3. Scan it with the phone's camera. IBMM opens with the brain's address, the workspace and the phone's own key.
4. For the capture bubble: switch on **Capture bubble** and allow the microphone, notifications and "Display over
   other apps".

Owners can also invite people from **People & seats > Invite someone**; the invite QR gives that person's phone its
own key and role.

iPhone: not part of Beta 1 (it needs a Mac with Xcode 16+ to build and sign).

No phone? You can try the phone app in a desktop browser:

```powershell
cd <IBMM>\apps\mobile
npm.cmd ci --include=dev
npm.cmd run dev      # then open http://localhost:5174/?pair=notecad%3A%2F%2Fpair%3Fu%3Dhttp%3A%2F%2F127.0.0.1%3A8788%26w%3Dshowcase
```

### 6.4 Edge AI Node (sync between two brains)

`start_notecad.ps1 -EdgeNode` also starts a second brain on port 8789 (`data\edge-node`) and keeps the desktop brain
in sync with it. Use it to test **Sync now** in the status chip and offline/online behaviour. Two-PC sync is out of
scope for Beta 1.

## 7. Where things are kept

| What | Where |
|---|---|
| Database | `<IBMM>\data\brain\brain.db` (SQLite) |
| Voice recordings | `<IBMM>\data\brain\audio\` |
| Logs | `<IBMM>\data\brain\logs\`, `<IBMM>\data\companion\logs\`, `<IBMM>\data\desktop\logs\` |
| Backups of removed or reset workspaces | `<IBMM>\data\archive\` |
| AI models | `<IBMM>\models\` (Gemma, EmbeddingGemma), `<IBMM>\models\whisper\` |
| Keys and phone token | `E:\.claude\_vault\notecad.env` (never inside `<IBMM>`) |

`api.log` has tokens, tickets and invite codes blanked out; it rotates weekly and keeps four weeks.

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `...cannot be loaded because running scripts is disabled` | Always start scripts with `powershell -ExecutionPolicy Bypass -File ...` as shown |
| Health table: **Ollama FAIL - not answering** | Start Ollama from the Start menu (tray icon), then run the start script again |
| **Ollama FAIL - missing notecad-gemma4-e2b** | The models are not in `<IBMM>\models`. Run `setup_ibmm.ps1` again (without `-SkipModels`) |
| **Speech to text OFF - no engine** | Whisper is not installed in the brain environment. Run `setup_ibmm.ps1` again, or `services\brain\.venv\Scripts\python.exe -m pip install -e "services\brain[whisper-gpu]"` |
| Speech to text says **cpu** on a PC with an NVIDIA card | Update the NVIDIA driver; re-run set-up without `-CpuOnly` so the CUDA libraries are installed |
| First voice note takes minutes | The speech model is downloading or loading (first start only). Watch `data\brain\logs\api.err.log` |
| Voice notes very slow on a CPU-only PC | Expected. Use `NC_BRAIN_WHISPER_MODEL=small` (section 5) or type notes with `/` |
| Browser asks for microphone permission every time / no waveform | Allow the microphone for `127.0.0.1` in the browser's site settings; use `127.0.0.1`, not the PC name |
| App shows **401 / unauthorised** | You opened it by IP or PC name. Use `http://127.0.0.1:8788/` |
| `npm` errors during set-up, or **Desktop UI FAIL - not built** | Run `cd apps\desktop; npm.cmd ci --include=dev; npm.cmd run build`. If `NODE_ENV=production` is set on the PC, `--include=dev` is required |
| Port already in use (8787 / 8788 / 11434) | Run `start_notecad.ps1 -Stop`, then start again. Find the program with `netstat -ano | findstr :8788` |
| Phone cannot connect | Firewall rule (6.1), Wi-Fi set to Private, PC and phone on the same network, brain started with `-Lan`. Phones paired before `-Lan` HTTPS must pair again |
| Windows blocks `notecad-desktop.exe` | The optional Tauri window is unsigned and Smart App Control blocks it. Use the browser (the default) |
| Anything else | Run `tools\collect_logs.ps1 -Root <IBMM>` from the package and send the zip with your report |

## 9. Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Stop
powershell -ExecutionPolicy Bypass -File services\allow_phones_firewall.ps1 -Remove     # if you added it (admin)
ollama rm notecad-gemma4-e2b; ollama rm notecad-embeddinggemma
```

Then delete `<IBMM>`, `E:\.claude\_vault\notecad.env` (if you made it) and, if you mapped one, the `subst E:` drive
(`subst E: /D`). Uninstall Ollama, Python and Node from Windows Settings if you no longer need them. Uninstall the
Android app from the phone.

---
Policy 986 AED | License AED 900 | (c) 2018-2026 Antwerp Designs | Ionity Global (Pty) Ltd - All rights reserved.
