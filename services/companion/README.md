<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-->

# IBMM Companion

A small AI model that lives in the app, belongs to one person and learns them over time. The design
decision is in `docs/adr/0007-owner-companion-model.md`.

## Engines

| Where | Model | Runtime |
|---|---|---|
| Android | Gemma 4 E2B (4-bit) | LiteRT-LM |
| iPhone | Gemma 4 E2B (4-bit) | MLX Swift or LiteRT-LM |
| PWA (browser) | `onnx-community/gemma-4-E2B-it-ONNX` | Transformers.js 4 + WebGPU |
| Desktop (Tauri), AEDi Edge AI Node | Gemma 4 E4B or E2B GGUF | llama.cpp (this service) or Ollama |
| Older phones | Qwen3.5 0.8B / 2B | llama.cpp |
| Embeddings everywhere | EmbeddingGemma 300M, 256 dims | same runtime as the model |

## How it learns the owner

1. **Memory**: facts they state (English and Afrikaans), episodic memories with embeddings, their own words
   (fed to speech-to-text as keyterms), their weekly rhythm (nudges).
2. **Behaviour**: reply length, tone, format and proactivity are picked by Thompson sampling and updated from
   thumbs up/down, the owner's edits and plain instructions ("hou dit kort").
3. **Weights**: approved and edited replies become a per-owner LoRA adapter, trained on their own desktop or
   Edge node with `tools/train_lora.py` and loaded with `NC_COMPANION_LORA_PATH`.

## Run on the desktop (WABAKIPI: RTX 4060 Laptop, Smart App Control on)

Smart App Control blocks the unsigned llama.cpp `.exe` builds, so the desktop runs the models in **Ollama**
(signed by Ollama Inc.), installed in `runtime\ollama` with its model store in `runtime\ollama-models`
(user variable `OLLAMA_MODELS`). The downloaded GGUFs are registered once as `notecad-gemma4-e2b` and
`notecad-embeddinggemma`, so nothing is downloaded twice.

```powershell
cd E:\.claude\Ionity\.NoteCad\services\companion
powershell -ExecutionPolicy Bypass -File tools\start_local.ps1          # Ollama + companion API on :8787
powershell -ExecutionPolicy Bypass -File tools\start_local.ps1 -Stop
```

Speed on the RTX 4060: about 100 tokens/s, 0.6-2.4 s per chat turn, 1.1 s per offline route.

Other set-ups: in-process GGUF with `pip install -e ".[local]"` and `NC_COMPANION_MODEL_PATH` /
`NC_COMPANION_EMBED_BACKEND=llama_cpp` / `NC_COMPANION_EMBED_MODEL_PATH`; or `-Engine llamacpp` where unsigned
binaries are allowed. `NC_COMPANION_REASONING_EFFORT` defaults to `none` (Gemma 4 otherwise thinks first and
structured answers come back empty).

## API

| Method and path | What it does |
|---|---|
| `POST /v1/{owner}/chat` `{text}` | Reply, and learn from the message |
| `POST /v1/{owner}/feedback` `{interaction_id, rating?, edited_reply?, comment?}` | Learn from thumbs, edits, comments |
| `POST /v1/{owner}/observe` `{text, node_path?}` | Brain hands over an applied voice note |
| `GET /v1/{owner}/card` | What the companion has learned, for the "About me" screen |
| `GET /v1/{owner}/keyterms` | Owner vocabulary for Deepgram / Whisper |
| `GET /v1/{owner}/nudges` | Weekday habits as hints |
| `POST /v1/{owner}/route-offline` | Brain step 4 without internet, output in the action schema |
| `PUT /v1/{owner}/facts`, `DELETE /v1/{owner}/facts/{key}` | Owner corrects or removes a fact |
| `POST /v1/{owner}/consolidate` | Nightly: merge, decay, re-embed |
| `POST /v1/{owner}/train/export` | SFT + DPO files for the LoRA step |
| `GET /v1/{owner}/export`, `DELETE /v1/{owner}` | POPIA export and wipe |

Set `NC_COMPANION_API_TOKEN` to require `Authorization: Bearer <token>`.

## Tests

```bash
pytest                      # unit + API tests, no downloads
pytest -m live              # real models: set the two GGUF paths, or the openai backends (start_local.ps1 sets them)
python tools/demo_owner.py --model <gemma gguf> --embed <embeddinggemma gguf> --out demo_run.json
```
