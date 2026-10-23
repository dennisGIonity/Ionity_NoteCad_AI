"""Settings, read from environment variables prefixed NC_COMPANION_."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"NC_COMPANION_{name}", default)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")))
    # llm backend: "llama_cpp" (in-process GGUF), "openai" (Ollama / llama-server / LM Studio),
    # "claude" (cloud fallback), "none" (memory + learning only)
    llm_backend: str = field(default_factory=lambda: _env("LLM_BACKEND", "llama_cpp"))
    model_path: str | None = field(default_factory=lambda: _env("MODEL_PATH"))
    lora_path: str | None = field(default_factory=lambda: _env("LORA_PATH"))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "http://127.0.0.1:11434"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gemma4:e2b"))
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-haiku-5-5"))
    # embeddings: "llama_cpp" (EmbeddingGemma GGUF) or "hash" (no model, offline fallback)
    embed_backend: str = field(default_factory=lambda: _env("EMBED_BACKEND", "hash"))
    embed_model_path: str | None = field(default_factory=lambda: _env("EMBED_MODEL_PATH"))
    embed_dims: int = field(default_factory=lambda: int(_env("EMBED_DIMS", "256")))
    n_ctx: int = field(default_factory=lambda: int(_env("N_CTX", "4096")))
    n_threads: int = field(default_factory=lambda: int(_env("N_THREADS", str(os.cpu_count() or 4))))
    max_reply_tokens: int = field(default_factory=lambda: int(_env("MAX_REPLY_TOKENS", "320")))
    history_turns: int = field(default_factory=lambda: int(_env("HISTORY_TURNS", "6")))
    memory_top_k: int = field(default_factory=lambda: int(_env("MEMORY_TOP_K", "5")))
    llm_fact_extraction: bool = field(default_factory=lambda: _env("LLM_FACTS", "1") == "1")
    api_token: str | None = field(default_factory=lambda: _env("API_TOKEN"))
