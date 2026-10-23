# Ionity NoteCad - Brain | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
"""Speech to text (blueprint 3.1). Each engine returns the same transcript shape.

  DeepgramSTT   cloud, Nova-3, keyterm prompting from the owner's own words
  WhisperSTT    faster-whisper on the desktop / Edge AI Node; Afrikaans path and offline fallback
  ChainSTT      tries engines in order; drops to the next one on error or low confidence
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

import httpx


@dataclass
class Transcript:
    text: str
    language: str | None = None
    confidence: float | None = None
    engine: str = ""
    words: list[dict] = field(default_factory=list)
    keyterms_used: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"text": self.text, "language": self.language, "confidence": self.confidence, "engine": self.engine,
                "words": self.words[:400], "keyterms_used": self.keyterms_used}


class STT(Protocol):
    name: str

    def transcribe(self, audio: bytes, *, mime: str, lang_hint: str | None, keyterms: list[str]) -> Transcript: ...


class STTError(RuntimeError):
    pass


class DeepgramSTT:
    name = "deepgram:nova-3"

    def __init__(self, api_key: str | None = None, model: str = "nova-3", timeout: float = 60.0, transport=None):
        self.key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        self.model = model
        self._timeout = timeout
        self._transport = transport

    def transcribe(self, audio, *, mime, lang_hint, keyterms):
        if not self.key:
            raise STTError("no Deepgram key")
        params: list[tuple[str, str]] = [("model", self.model), ("smart_format", "true"), ("punctuate", "true")]
        lang = (lang_hint or "").split("-")[0]
        params.append(("language", lang) if lang and lang != "af" else ("detect_language", "true"))
        for k in keyterms[:100]:
            params.append(("keyterm", k))
        with httpx.Client(transport=self._transport, timeout=self._timeout) as c:
            r = c.post("https://api.deepgram.com/v1/listen", params=params, content=audio,
                       headers={"Authorization": f"Token {self.key}", "Content-Type": mime or "audio/ogg"})
        r.raise_for_status()
        ch = r.json()["results"]["channels"][0]
        alt = ch["alternatives"][0]
        return Transcript(text=alt.get("transcript", "").strip(), language=ch.get("detected_language") or lang or None,
                          confidence=alt.get("confidence"), engine=self.name,
                          words=[{"w": w.get("word"), "start": w.get("start"), "end": w.get("end"),
                                  "conf": w.get("confidence")} for w in alt.get("words", [])],
                          keyterms_used=keyterms[:100])


def _cuda_dll_dirs() -> None:
    """Windows: CTranslate2 finds cuBLAS / cuDNN only on the DLL path. When they come from the nvidia-cublas-cu12 and
    nvidia-cudnn-cu12 wheels in this venv, add their bin folders (no system CUDA install needed)."""
    import os
    import sys
    if sys.platform != "win32":
        return
    import importlib.util
    for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_runtime"):
        try:
            spec = importlib.util.find_spec(pkg)
        except (ImportError, ValueError):
            spec = None
        for root in (spec.submodule_search_locations or []) if spec else []:
            b = os.path.join(root, "bin")
            if os.path.isdir(b):
                os.add_dll_directory(b)
                os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")


class WhisperSTT:
    """faster-whisper (CTranslate2). Optional dependency: pip install faster-whisper."""

    name = "faster-whisper"

    def __init__(self, model: str = "large-v3-turbo", device: str = "auto", compute_type: str = "auto",
                 download_root: str | None = None):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root  # keep the model with the project, not in the user profile
        self._model = None

    def _load(self):
        if self._model is None:
            _cuda_dll_dirs()
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type,
                                       download_root=self.download_root)
            self.active_device = getattr(getattr(self._model, "model", None), "device", self.device)
        return self._model

    def warm(self) -> None:
        """Load the model and run one second of silence, so the owner's first note is not the slow one."""
        import numpy as np
        try:
            self._run_array(np.zeros(16000, dtype=np.float32))
        except (RuntimeError, OSError) as ex:
            if self.device != "cpu" and any(w in str(ex).lower() for w in ("cuda", "cublas", "cudnn", "dll")):
                self.device, self.compute_type, self._model = "cpu", "int8", None
                self._run_array(np.zeros(16000, dtype=np.float32))
            else:
                raise

    def _run_array(self, samples):
        segments, _ = self._load().transcribe(samples, language="en", vad_filter=False)
        list(segments)

    def _run(self, audio: bytes, lang: str | None, prompt: str | None):
        import io
        segments, info = self._load().transcribe(io.BytesIO(audio), language=lang, vad_filter=True, initial_prompt=prompt)
        return list(segments), info

    def transcribe(self, audio, *, mime, lang_hint, keyterms):
        lang = (lang_hint or "").split("-")[0] or None
        # a punctuated sentence: a bare comma list makes Whisper drop punctuation, and then events do not split
        prompt = f"Farm notes about {', '.join(keyterms[:60])}. Ask Sipho to check it before Friday." if keyterms else None
        try:
            segs, info = self._run(audio, lang, prompt)
        except (RuntimeError, OSError) as ex:
            # "auto" picks CUDA when a GPU is present, but cuBLAS / cuDNN may not be installed: use the CPU instead
            if self.device == "cpu" or not any(w in str(ex).lower() for w in ("cuda", "cublas", "cudnn", "dll")):
                raise
            self.device, self.compute_type, self._model = "cpu", "int8", None
            segs, info = self._run(audio, lang, prompt)
        text = " ".join(s.text.strip() for s in segs).strip()
        conf = None
        if segs:
            import math
            conf = round(sum(math.exp(s.avg_logprob) for s in segs) / len(segs), 3)
        return Transcript(text=text, language=info.language, confidence=conf, engine=f"{self.name}:{self.model_name}",
                          keyterms_used=keyterms[:60])


class ChainSTT:
    """Deepgram first for English, Whisper first for Afrikaans (blueprint 3.1); fall through on error or
    confidence below the threshold."""

    def __init__(self, engines: list[STT], min_confidence: float = 0.75):
        self.engines = engines
        self.min_confidence = min_confidence
        self.name = "chain:" + ",".join(e.name for e in engines)

    def warm(self) -> None:
        for e in self.engines:
            w = getattr(e, "warm", None)
            if w:
                w()

    def transcribe(self, audio, *, mime, lang_hint, keyterms):
        engines = list(self.engines)
        if (lang_hint or "").startswith("af"):
            engines.sort(key=lambda e: 0 if "whisper" in e.name else 1)
        errors, best = [], None
        for e in engines:
            try:
                t = e.transcribe(audio, mime=mime, lang_hint=lang_hint, keyterms=keyterms)
            except Exception as ex:  # next engine
                errors.append(f"{e.name}: {ex}")
                continue
            if t.text and (t.confidence is None or t.confidence >= self.min_confidence):
                return t
            best = best or t
        if best and best.text:
            return best
        raise STTError("; ".join(errors) or "no transcript")


def make_stt(settings) -> STT | None:
    engines: list[STT] = []
    for name in [n.strip() for n in settings.stt_engines.split(",") if n.strip()]:
        if name == "deepgram" and (settings.deepgram_key or os.environ.get("DEEPGRAM_API_KEY")):
            engines.append(DeepgramSTT(settings.deepgram_key))
        elif name == "whisper":
            import importlib.util
            if importlib.util.find_spec("faster_whisper") is not None:
                engines.append(WhisperSTT(settings.whisper_model, device=settings.whisper_device,
                                          compute_type=settings.whisper_compute, download_root=settings.whisper_dir))
    if not engines:
        return None
    return engines[0] if len(engines) == 1 else ChainSTT(engines)
