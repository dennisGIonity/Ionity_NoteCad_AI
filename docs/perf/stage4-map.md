<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# Phase 6 Stage 4: the foldable map, measured

28 October 2026, WABAKIPI, installed Microsoft Edge driven by Playwright (`apps\desktop\e2e\perf.spec.ts`,
`e2e\fold.spec.ts`), 1440 × 900. Raw numbers are appended to `data\desktop\perf.jsonl` on every run.

**Display rate.** During the baseline the panel ran at 144 Hz; during Stage 4 it ran at 60 Hz (Windows reports
`CurrentRefreshRate 60`; the laptop switches by power profile). Panning is therefore compared with the frame rate the
same page reaches doing nothing (`display_fps`), and long frames (> 34 ms) are counted.

| 2,000-node synthetic farm (`perf-2000`) | Before (dagre, no fold) | After |
|---|---|---|
| First draw (open the map) | 3,325 ms | **1,367 ms** (main areas: 8 cards) |
| Expand all | n/a (everything was open) | **82 ms** (was 1,116 ms before cards carried their size and handles) |
| Collapse all | n/a | **64 ms** |
| Panning, everything open, fitted | | **54.4 fps on a display idling at 54.2 fps; 0 long frames** |
| Panning after the first draw | 142.6 fps at 144 Hz | 54.4 fps at 60 Hz, 0 long frames |
| Layout of all 2,000 nodes (Node 24) | 401 ms (dagre) | **3 ms** (d3-hierarchy tidy tree) |

| Showcase farm | Before | After |
|---|---|---|
| Capture's change on the map after `action.applied` | 521 ms | **269 ms** (target < 1 s) |

What made the difference, in order of effect:

1. **Cards carry their size and handle positions** (`initialWidth/Height`, `measured`, `handles`). React Flow renders
   every new node once to measure its handles, whatever the viewport; with 2,000 nodes appearing at once that was
   2,000 cards rendered for a frame. It also hid each re-created card while measuring it, which took the keyboard
   focus away.
2. **One React Flow update per change**: a fold re-placed every card and a second effect refreshed their data.
3. **Layout keyed on the tree's shape**: counts, highlights and selection no longer re-lay out (dagre ran on every
   click and every highlight before).
4. **Tile cards when zoomed far out** (< 0.4) and no culling there (every card is on screen anyway; culling only
   re-scanned 2,000 nodes on every pan frame). The overview minimap is hidden above 400 open cards.
5. **No layout worker**: the whole farm lays out in 3 ms on the main thread; posting 2,000 nodes to a worker and back
   would cost more than that.

Bundle (raw / gzip): the HUD loads `index` 286 KB / 90.6 KB (fold logic in the store: +6 KB); the map chunk is
24.2 KB / 9.0 KB plus React Flow 236.8 KB / 77.1 KB, loaded when the map is first opened.
