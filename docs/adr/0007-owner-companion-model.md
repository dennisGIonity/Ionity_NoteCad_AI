<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# ADR 0007: The NoteCad Companion, a small model that lives in the app and learns its owner

Status: accepted, 2026-10-21. Author: Dennis Grobler. Blueprint ION-ARC-NOTECAD-2026-001, sections 2.3, 3.3, 7.3.

## Decision

| Part | Choice | Why |
|---|---|---|
| Owner model, phones | **Gemma 4 E2B** (instruction-tuned, ~2.3 B effective parameters, 4-bit) | Apache 2.0 since April 2026; built for phones; text, image and audio input; 128 K context; 140+ languages, which covers Afrikaans; function calling and JSON output |
| Owner model, desktop and AEDi Edge AI Node | **Gemma 4 E4B** (4.5 B effective) | Same family and chat format as the phone, so one prompt and one LoRA recipe serve both |
| Low-end fallback | **Qwen3.5 0.8B / 2B** (Apache 2.0) | Under 2 GB at 4-bit for older phones |
| On-device embeddings | **EmbeddingGemma 300M**, truncated to 256 dims (Matryoshka) | Built for on-device search, 100+ languages, about 330 MB at Q8 |
| Runtimes | Android: **LiteRT-LM** (Google's runtime for Gemma, Apache 2.0). iOS: **MLX Swift** or LiteRT-LM. PWA: **Transformers.js v4 + WebGPU** (`onnx-community/gemma-4-E2B-it-ONNX`). Desktop (Tauri) and Edge node: **llama.cpp** (GGUF) or **Ollama** | Each is the fastest published option for Gemma on its platform; llama.cpp also loads LoRA adapters at run time |
| Backend | `services/companion`: Python + FastAPI, one SQLite file per owner, talks to llama.cpp in-process or to any OpenAI-compatible server | The same code runs on the desktop, on the Edge node and in tests |
| Cloud fallback | Claude Haiku through the existing brain key, only when the owner allows cloud help | Keeps quality up for hard questions without making the cloud a requirement |

## What "learns its owner" means here

The companion learns in three layers. Each one works without the next.

1. **Memory.** Facts the owner states (name, role, place, people, things they own, likes and dislikes), in
   English and Afrikaans, from rules plus small-model extraction that is checked before it is kept. Episodic
   memories with embeddings, scored by similarity, recency and importance. The owner's own words, which also
   feed the speech-to-text keyterm list. A weekly rhythm, which turns into nudges ("you usually deal with
   dipping on Mondays").
2. **Behaviour.** Reply length, tone, format and how proactive it is are four dimensions with a Beta posterior
   per option. Each reply's style is chosen by Thompson sampling. Thumbs up or down, the owner's edits
   (shorter or longer, lists or sentences) and plain instructions ("hou dit kort", "use bullet points")
   update the posteriors. Old evidence fades (decay 0.985) so the companion follows the owner as they change.
   A stated language preference beats the language of the message.
3. **Weights.** Approved replies and the owner's edits are exported as SFT and DPO data. Once there are 20 or
   more, `tools/train_lora.py` trains a small LoRA adapter for Gemma on the owner's own desktop or Edge
   node. The adapter is loaded at run time (`NC_COMPANION_LORA_PATH`); the base model never changes and the
   adapter never leaves the owner's hardware.

A 2026 paper on LoRA-generating hypernetworks for on-device personalisation (arXiv 2609.24979) is a
possible later replacement for step 3; it is not needed for the pilot.

## Privacy (POPIA)

- One SQLite file per owner on their device or Edge node. Owners never share a store, a memory or an adapter.
- South African ID numbers and payment card numbers (Luhn-checked) are masked before anything is stored or
  sent to a model, and facts that contain them are dropped.
- Remembered notes are passed to the model as information, never as instructions.
- `GET /v1/{owner}/export` returns everything; `DELETE /v1/{owner}` wipes it.

## Connection to the brain

- `POST /v1/{owner}/observe`: the brain sends each applied note so the companion also learns from voice notes.
- `GET /v1/{owner}/keyterms`: the owner's vocabulary for Deepgram keyterms and the Whisper prompt.
- `POST /v1/{owner}/route-offline`: brain step 4 without internet. The small model picks a node from the
  candidate list only (the JSON schema is compiled to a grammar, so it cannot invent an id) and the result is
  mapped to `packages/schema/actions.schema.json`. Below 0.6 confidence it becomes `ask_user`.

## Rejected

- Training a model from scratch per owner: far too much data and compute for one person's notes.
- Full fine-tuning on the phone: battery and heat; LoRA on the desktop or Edge node gives the same benefit.
- Cloud-only personal model: breaks the offline and sovereign modes in blueprint 2.3.
