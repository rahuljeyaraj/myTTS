"""Offline neural voices (Kokoro-82M via ONNX Runtime)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import models

SAMPLE_RATE = 24_000
DEFAULT_VOICE = "af_heart"

# Kokoro voice ids look like "af_heart": language letter + gender letter + "_" + name.
# Japanese (j) and Mandarin (z) need the separate misaki G2P package, so they are not offered.
_LANGUAGES = {
    "a": ("en-us", "English (US)"),
    "b": ("en-gb", "English (UK)"),
    "e": ("es", "Spanish"),
    "f": ("fr-fr", "French"),
    "h": ("hi", "Hindi"),
    "i": ("it", "Italian"),
    "p": ("pt-br", "Portuguese (BR)"),
}
_GENDERS = {"f": "female", "m": "male"}
# Highest-rated voices on the Kokoro voice card are listed first within their language.
_FEATURED = ("af_heart", "af_bella", "af_nicole", "bf_emma", "af_aoede", "af_kore", "af_sarah",
             "am_michael", "am_fenrir", "am_puck", "bm_george", "bm_fable")


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    lang: str  # espeak language code passed to Kokoro
    language: str  # human-readable language
    gender: str

    @property
    def label(self) -> str:
        return f"{self.name} · {self.language}, {self.gender}"


def parse_voice(voice_id: str) -> Voice | None:
    if len(voice_id) < 4 or voice_id[2] != "_":
        return None
    lang = _LANGUAGES.get(voice_id[0])
    gender = _GENDERS.get(voice_id[1])
    if not lang or not gender:
        return None
    return Voice(voice_id, voice_id[3:].replace("_", " ").title(), lang[0], lang[1], gender)


def _sort_key(v: Voice) -> tuple:
    featured = _FEATURED.index(v.id) if v.id in _FEATURED else len(_FEATURED)
    return (list(_LANGUAGES).index(v.id[0]), featured, v.gender, v.name)


class Engine:
    """Loads the Kokoro model once and turns text into 24 kHz mono float32 audio."""

    def __init__(self, model_path: Path | None = None, voices_path: Path | None = None):
        model_path = Path(model_path or models.MODEL.path)
        voices_path = Path(voices_path or models.VOICES.path)
        absent = [p.name for p in (model_path, voices_path) if not p.is_file()]
        if absent:
            raise FileNotFoundError(
                f"Voice model not found ({', '.join(absent)}). Run: python -m mytts download"
            )
        from kokoro_onnx import Kokoro  # heavy import (onnxruntime), keep it lazy

        self._kokoro = Kokoro(str(model_path), str(voices_path))
        self._lock = threading.Lock()
        parsed = (parse_voice(v) for v in self._kokoro.get_voices())
        self.voices: list[Voice] = sorted((v for v in parsed if v), key=_sort_key)
        self._by_id = {v.id: v for v in self.voices}

    def voice(self, voice_id: str) -> Voice:
        return self._by_id.get(voice_id) or self._by_id.get(DEFAULT_VOICE) or self.voices[0]

    def synthesize(self, text: str, voice_id: str = DEFAULT_VOICE, speed: float = 1.0) -> np.ndarray:
        if not any(ch.isalnum() for ch in text):
            return np.zeros(0, dtype=np.float32)
        voice = self.voice(voice_id)
        speed = min(2.0, max(0.5, float(speed)))
        with self._lock:
            samples, sample_rate = self._kokoro.create(text, voice=voice.id, speed=speed, lang=voice.lang)
        if sample_rate != SAMPLE_RATE:
            raise RuntimeError(f"Unexpected sample rate {sample_rate}")
        return np.asarray(samples, dtype=np.float32).reshape(-1)
