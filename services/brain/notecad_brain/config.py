# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Settings from environment variables prefixed NC_BRAIN_."""
from __future__ import annotations

import os
from typing import overload
from pathlib import Path
from dataclasses import dataclass, field


@overload
def _env(name: str, default: str) -> str: ...
@overload
def _env(name: str, default: None = None) -> str | None: ...
def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"NC_BRAIN_{name}", default)


@dataclass
class Settings:
    db_url: str = field(default_factory=lambda: _env("DB_URL", "sqlite:///./data/brain.db"))
    audio_dir: str = field(default_factory=lambda: _env("AUDIO_DIR", "./data/audio"))
    # router order: claude (cloud), local (Gemma via Ollama / llama-server), rules (no model)
    routers: str = field(default_factory=lambda: _env("ROUTERS", "claude,local,rules"))
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-sonnet-5-5"))
    local_base_url: str = field(default_factory=lambda: _env("LOCAL_BASE_URL", "http://127.0.0.1:11434"))
    local_model: str = field(default_factory=lambda: _env("LOCAL_MODEL", "notecad-gemma4-e2b"))
    # embeddings for retrieval: openai (Ollama / llama-server), hash (no model), none
    embed_backend: str = field(default_factory=lambda: _env("EMBED_BACKEND", "hash"))
    embed_base_url: str = field(default_factory=lambda: _env("EMBED_BASE_URL", "http://127.0.0.1:11434"))
    embed_model: str = field(default_factory=lambda: _env("EMBED_MODEL", "notecad-embeddinggemma"))
    stt_engines: str = field(default_factory=lambda: _env("STT", "deepgram,whisper"))
    deepgram_key: str | None = field(default_factory=lambda: _env("DEEPGRAM_KEY"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "large-v3-turbo"))
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "auto"))  # auto | cuda | cpu
    whisper_compute: str = field(default_factory=lambda: _env("WHISPER_COMPUTE", "auto"))  # auto | float16 | int8
    whisper_dir: str = field(default_factory=lambda: _env(
        "WHISPER_DIR", str(Path(__file__).resolve().parents[3] / "models" / "whisper")))
    companion_url: str | None = field(default_factory=lambda: _env("COMPANION_URL"))
    timezone: str = field(default_factory=lambda: _env("TIMEZONE", "Africa/Johannesburg"))
    worker: bool = field(default_factory=lambda: _env("WORKER", "1") == "1")  # background worker thread in the API
    api_token: str | None = field(default_factory=lambda: _env("API_TOKEN"))
    # browsers allowed to call the API: the Vite dev server and the Tauri desktop shell
    cors_origins: str = field(default_factory=lambda: _env(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,"
                   "http://127.0.0.1:8788,http://localhost:8788,tauri://localhost,http://tauri.localhost,"
                   "http://localhost,https://localhost,capacitor://localhost"))
    # the built desktop app (apps/desktop/dist), served at /app/; empty to turn off
    ui_dir: str | None = field(default_factory=lambda: _env("UI_DIR"))
    # multi-worker sync (Phase 5): an Edge AI Node or desktop brain (http://host:8788) or Postgres / Supabase
    worker_id: str | None = field(default_factory=lambda: _env("WORKER_ID"))
    sync_target: str | None = field(default_factory=lambda: _env("SYNC_TARGET"))
    sync_token: str | None = field(default_factory=lambda: _env("SYNC_TOKEN"))
    sync_interval: float = field(default_factory=lambda: float(_env("SYNC_INTERVAL", "15")))
    sync_workspaces: str | None = field(default_factory=lambda: _env("SYNC_WORKSPACES"))  # comma list; empty = all
    upload_dir: str | None = field(default_factory=lambda: _env("UPLOAD_DIR"))  # tus parts; default next to audio
    bind_host: str = field(default_factory=lambda: _env("BIND", "127.0.0.1"))  # 0.0.0.0 when phones on the LAN connect
    trust_loopback: bool = field(default_factory=lambda: _env("TRUST_LOOPBACK", "1") == "1")  # this PC needs no token
    max_audio_mb: int = field(default_factory=lambda: int(_env("MAX_AUDIO_MB", "25")))
