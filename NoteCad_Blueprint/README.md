# NoteCad - Voice-First AI Workspace

| Path | What it is |
|---|---|
| `NoteCad_Master_Blueprint.md` / `.docx` / `.pdf` | Master blueprint NOTECAD-BP-001 v1.1: front end, floating capture widget, AI routing, database, end-to-end lifecycle, four-phase plan |
| `docs/adr/0007-owner-companion-model.md` | Decision record for the on-device companion model that learns its owner |
| `services/companion/` | Companion backend (Python, FastAPI): memory, style learning, LoRA export, offline router. `pytest` runs the tests |
| `docs/test-results/companion-2026-10-21/` | Test run with Gemma 4 E2B + EmbeddingGemma and the LoRA check |

Models are not included; run `services/companion/tools/get_models.ps1` to download them.
