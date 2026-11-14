"""Audio helpers."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def silence(seconds: float, sample_rate: int) -> np.ndarray:
    return np.zeros(int(seconds * sample_rate), dtype=np.float32)


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
