<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# Phase 6 Stage 2: efficiency, measured

28 October 2026, WABAKIPI. Every change below was measured before and after with the tools in
`services\brain\tools` (`profile_capture.py`, `profile_retrieval.py`, `perf_probe.py`) and kept only because it won.
Raw numbers: `docs\perf\stage2-*.json`. Baseline: `docs\perf\baseline-phase6.md`.

## Capture path

`profile_capture.py` (in-process brain, real Gemma 4 E2B and EmbeddingGemma through Ollama, fresh showcase farm)
showed Gemma routing at **94 %** of capture time: 2.34 s per event, and note 2 is five events.

| Change | Before | After |
|---|---|---|
| Gemma sees `n1`, `n2` … instead of 36-character node ids; one line of compact JSON | 2.34 s per call, ~165 output tokens | **1.74 s** per call |
| Rules answer alone for a plain field-work report they are sure of (`rules_are_sure`, `NC_BRAIN_RULES_FAST_PATH`) | note 2: 12.1 s | **0.10 s** |
| Golden notes, Gemma + rules (accuracy check) | 90.5 % (19/21) | **95.2 % (20/21)** |
| Golden notes, rules only | 81.0 % | 81.0 % |

Showcase, typed, in process (p50 of 2 runs): **3.0 / 12.1 / 2.4 s → 2.8 / 0.10 / 1.8 s**, still 3/3.

Not changed, with reasons:
- **Ollama `format` / structured output**: already used (`response_format: json_schema`, strict), so there are no
  retry guards to remove.
- **Claude prompt caching**: there is no Claude key on WABAKIPI, so it cannot be measured; left for when a key exists
  (ADR 0013, open).
- **Batching a note's events into one call**: the fast path removes the case that needed it (ranges).

## Retrieval and the mind map (2,000-node synthetic farm)

`profile_retrieval.py` on a copy of `brain.db`, workspace `perf-2000`:

| | Before | After |
|---|---|---|
| Retrieval per event | 297 ms | **76 ms** |
| Mind-map build (in process) | 634 ms | **83 ms** |
| SQL statements for the three showcase notes | 1,907 | **593** |
| Brain test suite | 13.5 s | 9.6 s |

What changed: every node's path was built with one query per ancestor (about 10,000 queries per event) and is now
built in memory once (`Graph.paths`); the vectors are kept as one matrix per workspace, rebuilt only when a node's
text changes, and scored with one matrix-vector product; the mind map looked up channels by scanning every node for
every node (O(n²)); roll-ups wrote unchanged rows; six hot queries were full table scans (migration 6 adds the
indexes); SQLite now runs `synchronous=NORMAL` under WAL.

**sqlite-vec** was not adopted: at farm scale (2,000 nodes × 768 dims) the numpy matrix product takes well under
1 ms, so a native extension (another binary for Smart App Control to judge) would buy nothing.

## Start-up

A timeline of a cold start (outside monitor, 250 ms polling) showed Ollama ready at 12.9 s and the table green 8 s
after Whisper was ready. Windows takes about 2 s to refuse an HTTP connection to a loopback port nothing listens on,
and the scripts paid that in every wait loop and every health round.

| | Before | After |
|---|---|---|
| Cold start (Ollama not running) | 28 s (baseline, script clock) | **17.5 s** |
| Warm start (Ollama running, models unloaded) | 22 s | **17.5 s** (target < 20 s) |
| Hot start (models loaded) | | 17.2 s |

Changes: 200 ms TCP probe before any HTTP wait; the companion and brain start side by side; model warm-ups run in the
background; `/api/tags` instead of `ollama list`; the UI rebuilds only when a source is newer than the build.
`OLLAMA_KEEP_ALIVE=-1` keeps the models loaded between notes (the OpenAI-style API cannot pass `keep_alive`, so
every note had reset Ollama's 5-minute timer).

## Speech to text

Whisper large-v3-turbo is 0.4 s of a spoken note (RTF 0.068), so it is not where the time goes.

| compute type | VRAM | RTF (beam 5, VAD) |
|---|---|---|
| float16 (kept) | 1,543 MiB | 0.068 |
| int8_float16 | 1,342 MiB | 0.061 |

Beam 1, int8 and batched inference changed transcripts only in punctuation on the five English samples. There is no
Afrikaans recording on this PC to prove accuracy holds there, and the saving is 200 MiB and about 30 ms a note, so the
engine stays at float16, beam 5, VAD on (ADR 0013).

## VRAM and RAM

Steady state with everything loaded: 6,388 / 8,188 MiB (baseline 6,814; the Windows desktop's own use varies by
about 0.5 GB). NoteCad's share: Gemma 1.6 GB, EmbeddingGemma 0.4 GB, Whisper 1.5 GB, about 3.5 GB in all; more than
1.5 GB left over.

## Desktop and phone

| | Before | After |
|---|---|---|
| Desktop JavaScript loaded with the recorder HUD | 560.7 KB raw / 183.5 KB gzip | **281.5 KB / 89.2 KB** (map and QR load on first use) |
| Phone: idle polling | outbox read with every recording every 5 s, forever | in-memory check; poll only while something waits and the stream is down |
| Phone: level meter and upload progress | whole screen re-rendered every frame / chunk | per-field selectors, about 15 updates a second |

The map's rendering (selectors, layout in a worker, no full relayout on live updates, fold) is reworked in Stage 4;
its numbers are in `docs\perf\stage4-map.md`.

## Targets

| Target (PLAN-0001 / brief) | Result |
|---|---|
| Typed notes p95 < 4 s with local Gemma | 2.8 s worst of the showcase (was 12.6 s) |
| Warm start < 20 s | 17.5 s |
| A capture's change on the map < 1 s after `applied` | 521 ms at baseline; see Stage 4 |
| 2,000-node map pans at 60 fps | 142.6 fps at baseline; see Stage 4 |
| Whisper + Gemma + EmbeddingGemma fit in 8 GB with headroom | about 3.5 GB, >1.5 GB free |
