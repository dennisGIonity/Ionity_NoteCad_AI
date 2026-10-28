# Ionity NoteCad - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Settings, read from environment variables prefixed NC_COMPANION_."""
from __future__ import annotations

import os
from typing import overload
from dataclasses import dataclass, field
from pathlib import Path


@overload
def _env(name: str, default: str) -> str: ...
@overload
def _env(name: str, default: None = None) -> str | None: ...
def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"NC_COMPANION_{name}", default)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")))
    # browsers allowed to call the API: the NoteCad desktop (Vite dev server, Tauri shell)
    cors_origins: str = field(default_factory=lambda: _env(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,"
                        "http://127.0.0.1:8788,http://localhost:8788,tauri://localhost,http://tauri.localhost"))
    # llm backend: "llama_cpp" (in-process GGUF), "openai" (Ollama / llama-server / LM Studio),
    # "claude" (cloud fallback), "none" (memory + learning only)
    llm_backend: str = field(default_factory=lambda: _env("LLM_BACKEND", "llama_cpp"))
    model_path: str | None = field(default_factory=lambda: _env("MODEL_PATH"))
    lora_path: str | None = field(default_factory=lambda: _env("LORA_PATH"))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "http://127.0.0.1:11434"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gemma4:e2b"))
    reasoning_effort: str = field(default_factory=lambda: _env("REASONING_EFFORT", "none"))  # "" to leave default
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-haiku-5-5"))
    # embeddings: "llama_cpp" (EmbeddingGemma GGUF in-process), "openai" (llama-server --embedding / Ollama)
    # or "hash" (no model, offline fallback)
    embed_backend: str = field(default_factory=lambda: _env("EMBED_BACKEND", "hash"))
    embed_model_path: str | None = field(default_factory=lambda: _env("EMBED_MODEL_PATH"))
    embed_base_url: str = field(default_factory=lambda: _env("EMBED_BASE_URL", "http://127.0.0.1:8081"))
    embed_model: str = field(default_factory=lambda: _env("EMBED_MODEL", "embeddinggemma"))
    embed_dims: int = field(default_factory=lambda: int(_env("EMBED_DIMS", "256")))
    n_ctx: int = field(default_factory=lambda: int(_env("N_CTX", "4096")))
    n_threads: int = field(default_factory=lambda: int(_env("N_THREADS", str(os.cpu_count() or 4))))
    max_reply_tokens: int = field(default_factory=lambda: int(_env("MAX_REPLY_TOKENS", "320")))
    history_turns: int = field(default_factory=lambda: int(_env("HISTORY_TURNS", "6")))
    memory_top_k: int = field(default_factory=lambda: int(_env("MEMORY_TOP_K", "5")))
    llm_fact_extraction: bool = field(default_factory=lambda: _env("LLM_FACTS", "1") == "1")
    brain_url: str | None = field(default_factory=lambda: _env("BRAIN_URL"))
    # a brain off this PC needs its API token (the brain's NC_BRAIN_API_TOKEN)
    brain_token: str | None = field(default_factory=lambda: _env("BRAIN_TOKEN") or os.environ.get("NC_BRAIN_API_TOKEN"))  # e.g. http://127.0.0.1:8788
    api_token: str | None = field(default_factory=lambda: _env("API_TOKEN"))
