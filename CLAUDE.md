<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# Ionity NoteCad

Voice-first AI workspace (blueprint ION-ARC-NOTECAD-2026-001). The owner talks; the brain files each note on the
owner's own mind map as notes, tasks, alerts and progress, and delegates work by name. Everything runs on the
desktop WABAKIPI (Windows 11, RTX 4060), offline unless a Claude or Deepgram key is set.

## Start, stop, check

```powershell
cd E:\.claude\Ionity\.NoteCad
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1             # everything, then a green health table
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Showcase   # ... and the showcase farm on the map
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Status     # health table only
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Stop
```

Phones and a second worker: `-Lan` (phones on the farm network; phone token in the vault, then **Pair a phone** in
the app's status chip; once, as admin: `services\allow_phones_firewall.ps1`) and `-EdgeNode` (an Edge AI Node sync hub on :8789, `data\edge-node`, synced with the brain).
Other switches: `-Ui dev` (Vite on :5173, hot reload), `-Ui desktop` (Tauri window, once built), `-Ui none`,
`-Rebuild` (rebuild `apps\desktop\dist` after UI changes), `-NoOpen`. The app opens at **http://127.0.0.1:8788/**.

## Architecture

| Part | Where | Port | What it does |
|---|---|---|---|
| Ollama | `runtime\ollama`, models in `models\` | 11434 | Gemma 4 E2B (`notecad-gemma4-e2b`: router + companion) and EmbeddingGemma (`notecad-embeddinggemma`: retrieval). Signed, so it runs under Smart App Control; unsigned llama.cpp is blocked |
| Companion | `services\companion` | 8787 | Learns the owner (memory, reply style, per-owner LoRA); answers from the brain's digest and map lines; `context_node_id` for "this one" |
| Brain | `services\brain` | 8788 | Capture → Whisper (GPU) → split → candidates → router chain (Claude → Gemma → rules) → validate → apply (one transaction, inverses for Undo) or Inbox. SQLite at `data\brain\brain.db`. Serves the UI at `/app/` |
| Desktop app | `apps\desktop` | 8788/app, 5173 dev | React 19 + Vite + Tailwind 4 + React Flow: recorder pill (hold Space), live status from SSE, toast with Undo and branch pills, mind map, node drawer, sync chip. `src-tauri` is the transparent always-on-top window (Ctrl+Shift+Space) |
| Edge AI Node | `services\brain` (`-Name edge-node -HubOnly`) | 8789 | Another brain used as sync hub; on a farm-office PC it can run the full stack |
| Phone app | `apps\mobile` | 5174 dev | Capacitor 8 (Android APK; iOS needs a Mac). Outbox in IndexedDB / native files, tus uploads, Android capture bubble, iOS Action Button intent |
| Supabase | `supabase\migrations` | | Same schema + RLS for the cloud (0001 core, 0002 capture anchor, 0003 sync readiness, 0004 sync journal) |

Key brain endpoints (all also under `/api/v1`): `POST /v1/workspaces/{ws}/capture` (multipart audio or text,
`context_node_id`), `GET .../mindmap`, `GET .../events/stream` (SSE with `Last-Event-ID`), `GET .../digest`,
`GET /v1/nodes/{id}/history`, `POST /v1/captures/{id}/undo`, `POST /v1/inbox/{id}/resolve`, `GET .../sync`,
`GET .../export`, `DELETE /v1/workspaces/{ws}?confirm={ws}`, `POST .../uploads` (tus 1.0.0 for phones),
`GET /v1/pairing` (this PC only), `GET /v1/sync/status`, `POST /v1/sync/push`, `GET /v1/sync/pull`, `POST /v1/sync/now`.

Sync (ADR 0012): triggers write every change to `sync_changes`; last writer wins per row; `action_log.synced_at`
is set once a peer has the row. Target in the vault: `NC_BRAIN_SYNC_TARGET=http://<edge-node>:8789` or
`postgresql://...` (Supabase), `NC_BRAIN_SYNC_TOKEN` for a remote node. Off this PC every request needs
`NC_BRAIN_API_TOKEN`; this PC (loopback) does not. Diagram: `docs\notecad_data_flow.html`
(artifact "NoteCad Capture Flow"). Decisions: `docs\adr\0007`-`0012`.

## Showcase and tests

```powershell
cd services\brain
.venv\Scripts\python.exe tools\seed_farm_showcase.py --reset-clean --interactive   # fresh farm, then the 3 notes one by one
.venv\Scripts\python.exe tools\seed_farm_showcase.py --reset-clean --audio ..\..\data\samples\showcase   # spoken
.venv\Scripts\python.exe tools\seed_farm_showcase.py --list | --remove-stale [--yes]   # test workspaces; archived first
.venv\Scripts\python.exe tools\field_test.py --showcase --routers local,rules --embed openai
.venv\Scripts\python.exe tools\field_test.py --routers local,rules --embed openai        # 20 golden field notes
.venv\Scripts\python.exe -m pytest -q                       # brain; NC_BRAIN_LIVE_URL=http://127.0.0.1:11434 ... -m live
cd ..\companion; .venv\Scripts\python.exe -m pytest -q
cd ..\..\apps\desktop; npm.cmd ci --include=dev; npm.cmd run build
cd ..\mobile; npm.cmd ci --include=dev; npm.cmd run build   # Android APK: see apps\mobile\README.md
```

The three showcase notes: "Wheel needs changing on tractor model John Deere 9550 - number 1", "Today I planted
field south 704 to 708", "Ask Sipho to check the water pump on the North borehole". Removed workspaces are written
to `data\archive\<id>-<time>.json` first.

## Rules for work in this folder

- Licence header on every source file: `Ionity Global (Pty) Ltd | AEDI`, author Dennis Grobler (Wabakipi),
  `Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved`.
- Secrets only in `E:\.claude\_vault\notecad.env` (`ANTHROPIC_API_KEY`, `NC_BRAIN_DEEPGRAM_KEY`); `start_brain.ps1`
  reads it. Never put keys in this folder.
- Nothing operational on C:. Models, Whisper weights (`models\whisper`), data and logs stay under this folder.
- Never commit `models\`, `data\`, `runtime\`, `.venv\`, `node_modules\`, `.env*` or anything from the vault.
- Documents use the official Ionity template; deliverables also go to Google Drive.
- Git identity comes from config, never `-c` flags; never force-push.
- When the model gets something wrong in the field, add a guard and a regression test (see `tests\test_phase*.py`).

## Windows gotchas on WABAKIPI

- Scripts: `powershell -ExecutionPolicy Bypass -File ...` (script execution is off). Use `npm.cmd`, not `npm`.
- `NODE_ENV=production` is set machine-wide: `npm.cmd ci --include=dev` or the UI build tools are skipped.
- The venv `python.exe` is a launcher with a child process: stop services by command line, not by PID.
- Windows PowerShell 5.1 hands back a JSON array from `Invoke-RestMethod` as one object: pipe through
  `ForEach-Object { $_ }` before counting.
- faster-whisper needs PyAV below 16 (`av>=14,<16`). CUDA comes from the `nvidia-cublas-cu12` / `nvidia-cudnn-cu12`
  wheels in the brain venv (the brain adds their DLL folders); without them Whisper falls back to the CPU.
- Python 3.14 lives at `C:\Python314` (base interpreter only); the venvs are under `services\*\.venv`.
- `start_notecad.ps1` runs the edge node and the brain in one PowerShell session: `start_brain.ps1` must reset
  every per-instance env var (`NC_BRAIN_WORKER`, `NC_BRAIN_STT`, `NC_BRAIN_SYNC_TARGET`) or the hub's settings leak.
- Leave the DGMic account alone.
