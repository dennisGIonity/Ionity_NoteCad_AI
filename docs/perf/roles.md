<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# Roles and restricted branches, measured (ADR 0014, decision 31)

29 October 2026, WABAKIPI, in process (`services\brain\tools\perf_roles.py`, raw numbers in `roles.json`). The
2,000-node synthetic farm of `seed_synthetic_farm.py` (283 open tasks, 63 alerts), built in memory, with Admin >
Finance restricted to owners. Median of 15 runs after one warm-up; times include building the viewer's View.

| Viewer | Builds the View | Mind map | Retrieval | Digest | Map nodes seen |
|---|---|---|---|---|---|
| Owner | 0 ms (sees everything) | 70.0 ms | 71.9 ms | 142.3 ms | 2,287 |
| Employee | 3.6 ms | 79.0 ms | 62.4 ms | 136.8 ms | 2,217 |
| Employee bound to Irrigation | 6.1 ms | 38.4 ms | 42.8 ms | 39.0 ms | 331 |

| Change | Time |
|---|---|
| Restrict Finance to owners (its subtree's levels recomputed) | 3.5 ms |
| Restrict Fields (349 nodes) to managers | 14.8 ms |

## Against the targets

| Target (ADR 0014) | Result |
|---|---|
| An employee's mind map within 15 % of the owner's | **+12.9 %** (9 ms, 3.6 of it the View) |
| Retrieval within 10 % | within the run-to-run noise (the employee's run was faster here) |
| A 500-node visibility change under 50 ms | 349 nodes in 14.8 ms |
| Device pull filtering, snapshot | not yet built (step 4) |

The first build of the employee's map was +16 %: it copied every node to recompute the roll-ups. Only the ancestors of
a hidden node (and a scoped employee's path stubs) can roll up differently, so only those are copied and recomputed
now (`mindmap.as_seen`).

## The live stack, as the owner (`perf_probe.py --only routes`, `probe-roles.json`)

29 October 2026, after the restart that ran migrations 7 and 8 on `data\brain\brain.db`. p50 of 30 requests, against
Phase 6's `probe-final.json`:

| Route | Phase 6 | With roles |
|---|---|---|
| Mind map, showcase | 6.8 ms | 7.5 ms |
| Mind map, 2,000 nodes | 243.6 ms | 251.8 ms |
| Digest | 5.2 ms | 5.1 ms |
| Workspace sync status | 21.1 ms | 27.4 ms (now also works out the caller's own counts) |
| Tasks, Inbox, node, history | 2.3-2.7 ms | 2.7-3.3 ms |

The live showcase notes with Gemma on the GPU, as the owner on the role-aware farm (`roles-showcase`): 3/3 filed in
4.1 s, 1.7 s and 2.2 s.
