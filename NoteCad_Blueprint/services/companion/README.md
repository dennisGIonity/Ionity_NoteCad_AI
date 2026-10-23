# NoteCad Companion

A small AI model that lives in the app, belongs to one person and learns them over time. The design
decision is in `docs/adr/0007-owner-companion-model.md`.

## Engines

| Where | Model | Runtime |
|---|---|---|
| Android | Gemma 4 E2B (4-bit) | LiteRT-LM |
| iPhone | Gemma 4 E2B (4-bit) | MLX Swift or LiteRT-LM |
| PWA (browser) | `onnx-community/gemma-4-E2B-it-ONNX` | Transformers.js 4 + WebGPU |
| Desktop (Tauri), Edge AI Node | Gemma 4 E4B or E2B GGUF | llama.cpp (this service) or Ollama |
| Older phones | Qwen3.5 0.8B / 2B | llama.cpp |
| Embeddings everywhere | EmbeddingGemma 300M, 256 dims | same runtime as the model |

## How it learns the owner

1. **Memory**: facts they state (English and Afrikaans), episodic memories with embeddings, their own words
   (fed to speech-to-text as keyterms), their weekly rhythm (nudges).
2. **Behaviour**: reply length, tone, format and proactivity are picked by Thompson sampling and updated from
   thumbs up/down, the owner's edits and plain instructions ("hou dit kort").
3. **Weights**: approved and edited replies become a per-owner LoRA adapter, trained on their own desktop or
   Edge node with `tools/train_lora.py` and loaded with `NC_COMPANION_LORA_PATH`.

## Run

```bash
pip install -e ".[local,dev]"
# models (about 3.4 GB together)
#   unsloth/gemma-4-E2B-it-GGUF          gemma-4-E2B-it-Q4_K_M.gguf
#   ggml-org/embeddinggemma-300M-GGUF    embeddinggemma-300M-Q8_0.gguf
set NC_COMPANION_MODEL_PATH=C:\notecad\models\gemma-4-E2B-it-Q4_K_M.gguf
set NC_COMPANION_EMBED_BACKEND=llama_cpp
set NC_COMPANION_EMBED_MODEL_PATH=C:\notecad\models\embeddinggemma-300M-Q8_0.gguf
set NC_COMPANION_DATA_DIR=C:\notecad\data\companion
uvicorn notecad_companion.api:app --host 127.0.0.1 --port 8787
```

Use Ollama instead of the in-process model: `NC_COMPANION_LLM_BACKEND=openai`,
`NC_COMPANION_OPENAI_BASE_URL=http://127.0.0.1:11434`, `NC_COMPANION_OPENAI_MODEL=gemma4:e2b`.

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
pytest -m live              # real Gemma 4 E2B + EmbeddingGemma (set the two model paths)
python tools/demo_owner.py --model <gemma gguf> --embed <embeddinggemma gguf> --out demo_run.json
```
