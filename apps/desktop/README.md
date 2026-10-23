<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-->

# NoteCad desktop

The transparent voice recorder and the live mind map, on the brain (:8788) and the companion (:8787).
React 19 + TypeScript + Vite + Tailwind 4 + React Flow 12 (Dagre tree or radial layout); ready for a Tauri v2
transparent window (`src-tauri/`). Decisions: `docs/adr/0010-desktop-recorder-and-mind-map.md`.

## Use it

The brain serves the built app: open **http://127.0.0.1:8788/** (it redirects to `/app/`) once
`services\start_notecad.ps1` is running.

| Do | How |
|---|---|
| Talk | Hold **Space** (or click the mic). Release to send. **Esc** cancels |
| Type instead | Keyboard button in the pill |
| Map | **M** or the map button; the pill docks at the bottom |
| Note for one node | Click a node, then **Record note for this node** (or hold Space while it is selected) |
| Ask the companion | Ask bar at the bottom of the node drawer |
| Undo | **Undo** on the toast, or **Undo this note** in a node's History |
| Place a held note | Tap a branch pill on the toast; the brain learns your words for next time |

## Develop

```powershell
cd E:\.claude\Ionity\.NoteCad\apps\desktop
npm.cmd ci --include=dev   # WABAKIPI sets NODE_ENV=production, which skips the build tools
npm.cmd run dev        # http://127.0.0.1:5173 (talks to the brain on :8788)
npm.cmd run build      # dist\ - the brain serves it at /app/
```

`?ws=<workspace>`, `?brain=`, `?companion=`, `?token=` and `?view=map` in the URL override the defaults;
`VITE_BRAIN_URL`, `VITE_COMPANION_URL`, `VITE_API_TOKEN`, `VITE_WORKSPACE` do the same at build time.
`services\brain\tools\seed_farm_showcase.py --reset-clean` builds the showcase farm (fields South 704-708, John Deere tractors, borehole pumps); add `--interactive` to send the three showcase notes.

## Tauri v2 shell

`src-tauri/` is a transparent, frameless, always-on-top window that starts as the pill and grows into the map;
**Ctrl+Shift+Space** anywhere in Windows is hold-to-talk. It compiles (`cargo check`); building the installer
needs Rust (rustup) and the MSVC build tools on WABAKIPI, then `npm.cmd run tauri build`.

| File | What |
|---|---|
| `src/lib/store.ts` | Map, live events (SSE with Last-Event-ID), captures in flight, highlights |
| `src/lib/recorder.ts` | Microphone: MediaRecorder (Opus) for the brain, AnalyserNode for the waveform |
| `src/lib/layout.ts` | Mind map payload to React Flow, Dagre tree or radial |
| `src/components/RecorderHUD.tsx` | The pill: mic, 60 fps waveform, status ticker, type box, map toggle |
| `src/components/ActionToast.tsx` | What changed, Undo, branch pills for held notes |
| `src/components/MindMap.tsx`, `nodes/Cards.tsx` | Map, category / asset / field / task / member cards, live focus |
| `src/components/Inspector.tsx` | Node drawer: tasks, notes, action log, context mic, companion ask |
| `src/components/SyncIndicator.tsx` | Local store health and changes waiting to sync |
