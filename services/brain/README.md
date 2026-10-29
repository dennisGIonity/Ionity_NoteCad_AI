<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-->

# IBMM brain

Voice note in, the owner's map updated: notes, tasks, alerts, new branches, links, and tasks delegated to the
right person. The flow is drawn in `docs/notecad_data_flow.html`; the decisions are in `docs/adr/0008-brain-backend.md`.

```
capture -> speech to text -> clean up -> split into events -> per event:
  candidates -> router chain (Claude -> Gemma 4 local -> rules) -> validate -> apply | Inbox
  apply = one transaction: note, task (+ delegation), alert (+ status roll-up), branch, link, numbers
        + action_log with inverses (Undo) + live events + companion learns from the note
```

| Module | Job |
|---|---|
| `db.py` | One schema for SQLite (desktop, Edge AI Node, tests) and Postgres / Supabase |
| `graph.py` | Tree + cross-links, move with cycle check, status roll-up, channel mirroring, decay |
| `stt.py` | Deepgram Nova-3 with keyterms, faster-whisper, fallback chain (Afrikaans goes to Whisper first) |
| `text.py` | Clean-up, number words, event splitting, due-date words, problem words (English and Afrikaans) |
| `retrieve.py` | Candidates: owner's words vs titles and aliases, EmbeddingGemma, channel children, 1-hop links |
| `routers.py` | Claude (forced tool call), local Gemma (schema-constrained), rules; guards on top of the model |
| `validate.py` | `packages/schema/actions.schema.json`, known ids only, no new top-level branch, numeric caps, confidence |
| `apply.py` | One transaction per event, inverses for Undo, provenance in `action_log` |
| `delegate.py` | Assignee names to members and person nodes, notifications |
| `onboarding.py` | First-run branches from the owner's own answer (model), starter packs as fallback |
| `pipeline.py` | The whole flow, Inbox decisions with alias learning, Undo, tasks, alerts, digest |
| `api.py` | FastAPI with a background worker and server-sent events |

## Run on WABAKIPI

```powershell
cd E:\.claude\Ionity\.NoteCad\services
powershell -ExecutionPolicy Bypass -File start_notecad.ps1        # Ollama models, companion :8787, brain :8788
powershell -ExecutionPolicy Bypass -File start_notecad.ps1 -Stop
```

Speech to text on the desktop: `pip install faster-whisper` in the brain venv; the model (large-v3-turbo) is kept in
`models\whisper` (`NC_BRAIN_WHISPER_DIR`), runs on the GPU when CUDA libraries are present and on the CPU otherwise.

Keys never go in this folder. Put `ANTHROPIC_API_KEY=...` and `NC_BRAIN_DEEPGRAM_KEY=...` in
`E:\.claude\_vault\notecad.env`; `tools\start_brain.ps1` reads it. Without keys the brain routes with Gemma
and rules, and audio needs faster-whisper (`pip install faster-whisper`) or a Deepgram key.

## API (http://127.0.0.1:8788/docs)

| Method and path | What it does |
|---|---|
| `POST /v1/workspaces` | New workspace (root + owner) |
| `POST /v1/workspaces/{ws}/onboard` `{answer}` | Owner's own top branches |
| `POST /v1/workspaces/{ws}/members` | Add a person who can receive tasks |
| `GET /v1/workspaces/{ws}/tree` · `POST /v1/workspaces/{ws}/nodes` · `GET/PATCH/DELETE /v1/nodes/{id}` | The map |
| `POST /v1/workspaces/{ws}/captures` `{text, wait}` | Typed or transcribed note |
| `POST /v1/workspaces/{ws}/captures/audio` (body = audio) | Voice note; worker transcribes and routes |
| `GET /v1/captures/{id}` · `POST /v1/captures/{id}/undo` | Progress, Undo |
| `GET /v1/workspaces/{ws}/inbox` · `POST /v1/inbox/{id}/resolve` `{node_id}` | Owner decides; alias learned |
| `GET /v1/workspaces/{ws}/tasks` · `PATCH /v1/tasks/{id}` | Open work, done, reassign |
| `GET /v1/workspaces/{ws}/alerts` · `POST /v1/alerts/{id}/resolve` | Alerts |
| `GET /v1/workspaces/{ws}/notifications?member=` | What to push to whom |
| `GET /v1/workspaces/{ws}/digest` | Open tasks + alerts (the companion reads this) |
| `GET /v1/workspaces/{ws}/events/stream` | Live updates (server-sent events, `Last-Event-ID` replay, `?types=`, `?token=`) |
| `GET /v1/workspaces/{ws}/mindmap` | The whole map, UI-ready: categories, entities, task leaves, People, edges (Phase 2) |
| `POST /v1/workspaces/{ws}/capture` | Multipart audio (WAV / WebM / Opus) or text, plus `context_node_id` (Phase 2) |
| `GET /v1/workspaces/{ws}/digest?focus=` | Also the map's lines (needs work, progress) and the open node |
| `GET /v1/workspaces` · `GET /v1/nodes/{id}/history` · `GET /v1/workspaces/{ws}/sync` | Workspace list, action log per node, local store health and pending sync (Phase 3) |
| `GET /` → `/app/` | The desktop app (`apps/desktop`, built with `npm.cmd run build`) |

Every route is also served under `/api/v1/...`. Live event names: `capture.queued`, `stt.transcribing`,
`stt.completed`, `router.resolving`, `action.applied`, `inbox.created`, `capture.completed`, `capture.failed`,
`action.undone`, `node.updated`, `task.updated`, `alert.updated`, `inbox.resolved`. Decisions: `docs/adr/0009`.

## Tests

```bash
pytest                                   # 54 tests on SQLite
NC_BRAIN_TEST_PG_URL=postgresql://... pytest      # the same tests on Postgres as well (79)
NC_BRAIN_LIVE_URL=http://127.0.0.1:11434 pytest -m live    # Gemma 4 router + EmbeddingGemma
python tools/field_test.py --routers local,rules --embed openai   # 20 golden field notes, Phase 1 exit check
```
