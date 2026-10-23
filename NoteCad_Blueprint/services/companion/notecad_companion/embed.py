"""Embeddings. EmbeddingGemma 300M (GGUF via llama.cpp) on device; a hashing embedder when no model is present."""
from __future__ import annotations

import hashlib
import math
from typing import Protocol

import numpy as np

from .textutil import bigrams, content_terms, tokens


class Embedder(Protocol):
    name: str
    dims: int

    def embed_query(self, text: str) -> np.ndarray: ...
    def embed_doc(self, text: str) -> np.ndarray: ...


def _normalise(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return (v / n).astype(np.float32) if n > 0 else v.astype(np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None or a.shape != b.shape:
        return 0.0
    return float(np.dot(a, b))  # vectors are stored normalised


class HashEmbedder:
    """Feature hashing over words, bigrams and character trigrams. No model, deterministic, tiny.

    Used on very low-end phones, in tests, and as a fallback while EmbeddingGemma downloads.
    """

    name = "hash-v1"

    def __init__(self, dims: int = 256):
        self.dims = dims

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dims, dtype=np.float32)
        terms = content_terms(text) or tokens(text)
        feats: list[tuple[str, float]] = [(t, 1.0) for t in terms]
        feats += [(b, 0.7) for b in bigrams(terms)]
        for t in terms:
            padded = f"#{t}#"
            feats += [(padded[i : i + 3], 0.3) for i in range(len(padded) - 2)]
        for f, w in feats:
            h = hashlib.blake2b(f.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dims
            sign = 1.0 if h[4] & 1 else -1.0
            v[idx] += sign * w
        return _normalise(v)

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)

    def embed_doc(self, text: str) -> np.ndarray:
        return self._vec(text)


class LlamaEmbedder:
    """EmbeddingGemma through llama.cpp. Uses the model's task prompts and Matryoshka truncation."""

    name = "embeddinggemma-300m"

    def __init__(self, model_path: str, dims: int = 256, n_threads: int | None = None):
        from llama_cpp import Llama  # imported lazily so the package works without llama.cpp

        self._llm = Llama(
            model_path=model_path, embedding=True, n_ctx=2048, n_threads=n_threads, verbose=False
        )
        self.dims = dims  # EmbeddingGemma is 768-d; MRL lets us keep 512/256/128

    def _embed(self, text: str) -> np.ndarray:
        out = self._llm.create_embedding(text)["data"][0]["embedding"]
        arr = np.asarray(out, dtype=np.float32)
        if arr.ndim == 2:  # some builds return per-token vectors; mean-pool them
            arr = arr.mean(axis=0)
        return _normalise(arr[: self.dims])

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed(f"task: search result | query: {text}")

    def embed_doc(self, text: str) -> np.ndarray:
        return self._embed(f"title: none | text: {text}")


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes | None) -> np.ndarray | None:
    return None if b is None else np.frombuffer(b, dtype=np.float32)


def make_embedder(settings) -> Embedder:
    if settings.embed_backend == "llama_cpp" and settings.embed_model_path:
        return LlamaEmbedder(settings.embed_model_path, settings.embed_dims, settings.n_threads)
    return HashEmbedder(settings.embed_dims)


def recency_weight(age_hours: float, half_life_hours: float = 72.0) -> float:
    return math.exp(-math.log(2) * max(age_hours, 0.0) / half_life_hours)
