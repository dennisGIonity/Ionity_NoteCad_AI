# Ionity NoteCad - Companion | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""LLM back ends behind one small interface.

  LlamaCppLLM     Gemma 4 E2B / E4B (or any GGUF) in-process, with an optional per-owner LoRA adapter.
  OpenAICompatLLM Ollama, llama-server, LM Studio, the AEDi Edge AI Node - anything with /v1/chat/completions.
  ClaudeLLM       cloud fallback through the Anthropic Messages API.
  ScriptedLLM     deterministic stand-in for tests.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Protocol

import httpx

Message = dict  # {"role": "system"|"user"|"assistant", "content": str}


class LLM(Protocol):
    name: str

    def chat(self, messages: list[Message], *, max_tokens: int = 256, temperature: float = 0.7,
             schema: dict | None = None) -> str: ...


def parse_json(text: str) -> dict | list | None:
    """Pull the first JSON object/array out of a model reply (tolerates code fences and chatter)."""
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def strip_thinking(text: str) -> str:
    """Remove reasoning blocks some small models emit before the answer."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"<\|channel\|>analysis.*?<\|channel\|>final<\|message\|>", "", text, flags=re.S)
    return text.strip()


class LlamaCppLLM:
    def __init__(self, model_path: str, *, lora_path: str | None = None, n_ctx: int = 4096,
                 n_threads: int | None = None, chat_format: str | None = None):
        from llama_cpp import Llama  # pyright: ignore[reportMissingImports]  (optional extra [local])

        kwargs = dict(model_path=model_path, n_ctx=n_ctx, n_threads=n_threads, verbose=False)
        if lora_path:
            kwargs["lora_path"] = lora_path
        if chat_format:
            kwargs["chat_format"] = chat_format
        self._llm = Llama(**kwargs)
        self.name = "llama_cpp:" + os.path.basename(model_path) + (f"+lora:{os.path.basename(lora_path)}" if lora_path else "")

    def chat(self, messages, *, max_tokens=256, temperature=0.7, schema=None) -> str:
        kwargs: dict = dict(messages=messages, max_tokens=max_tokens, temperature=temperature)
        if schema is not None:
            # llama.cpp compiles the JSON schema to a grammar, so the reply is always valid JSON
            kwargs["response_format"] = {"type": "json_object", "schema": schema}
        out = self._llm.create_chat_completion(**kwargs)
        return strip_thinking(out["choices"][0]["message"]["content"] or "")


class OpenAICompatLLM:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 120.0,
                 reasoning_effort: str | None = "none", transport=None):
        # Gemma 4 thinks before answering when served by Ollama; on a 2B companion that only burns the token
        # budget (structured replies came back empty), so thinking is off unless asked for.
        self.reasoning_effort = reasoning_effort
        self._transport = transport
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"openai:{model}"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout

    def chat(self, messages, *, max_tokens=256, temperature=0.7, schema=None) -> str:
        body: dict = {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                      "temperature": temperature, "stream": False}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "out", "schema": schema, "strict": True}}
        with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
            r = client.post(f"{self.base_url}/v1/chat/completions", json=body, headers=self._headers)
        r.raise_for_status()
        return strip_thinking(r.json()["choices"][0]["message"]["content"] or "")


class ClaudeLLM:
    """Cloud fallback. Used only when the owner allows cloud help; the key stays on the server."""

    def __init__(self, model: str = "claude-haiku-5-5", api_key: str | None = None, timeout: float = 60.0):
        self.model = model
        self.name = f"claude:{model}"
        self._key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._timeout = timeout

    def chat(self, messages, *, max_tokens=256, temperature=0.7, schema=None) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [m for m in messages if m["role"] != "system"]
        body: dict = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature,
                      "system": system, "messages": convo}
        if schema is not None:
            body["tools"] = [{"name": "answer", "description": "Return the answer.", "input_schema": schema}]
            body["tool_choice"] = {"type": "tool", "name": "answer"}
        r = httpx.post("https://api.anthropic.com/v1/messages", json=body, timeout=self._timeout,
                       headers={"x-api-key": self._key or "", "anthropic-version": "2023-06-01"})
        r.raise_for_status()
        blocks = r.json()["content"]
        if schema is not None:
            for b in blocks:
                if b.get("type") == "tool_use":
                    return json.dumps(b["input"])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


class ScriptedLLM:
    """Test double: replies with a function of the messages (and schema)."""

    def __init__(self, fn: Callable[[list[Message], dict | None], str] | None = None):
        self.name = "scripted"
        self.calls: list[tuple[list[Message], dict | None]] = []
        self._fn = fn or (lambda msgs, schema: "{}" if schema else "Noted.")

    def chat(self, messages, *, max_tokens=256, temperature=0.7, schema=None) -> str:
        self.calls.append((messages, schema))
        return self._fn(messages, schema)


def make_llm(settings) -> LLM | None:
    b = settings.llm_backend
    if b == "llama_cpp" and settings.model_path:
        return LlamaCppLLM(settings.model_path, lora_path=settings.lora_path, n_ctx=settings.n_ctx,
                           n_threads=settings.n_threads)
    if b == "openai":
        return OpenAICompatLLM(settings.openai_base_url, settings.openai_model,
                               reasoning_effort=settings.reasoning_effort or None)
    if b == "claude":
        return ClaudeLLM(settings.claude_model)
    return None
