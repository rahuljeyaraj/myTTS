"""Kokoro voice-model files: registry, presence check and verified download.

The model is downloaded once (~350 MB). After that everything runs offline.
"""

from __future__ import annotations

import hashlib
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import models_dir

_BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str

    @property
    def url(self) -> str:
        return f"{_BASE_URL}/{self.name}"

    @property
    def path(self) -> Path:
        return models_dir() / self.name


MODEL = ModelFile(
    "kokoro-v1.0.onnx",
    325_505_369,
    "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
)
VOICES = ModelFile(
    "voices-v1.0.bin",
    28_214_398,
    "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
)
REQUIRED = (MODEL, VOICES)

# progress(file, bytes_done, bytes_total)
Progress = Callable[[ModelFile, int, int], None]


class DownloadCancelled(Exception):
    pass


class DownloadError(Exception):
    pass


def is_present(f: ModelFile) -> bool:
    p = f.path
    return p.is_file() and p.stat().st_size == f.size


def missing() -> list[ModelFile]:
    return [f for f in REQUIRED if not is_present(f)]


def _hash_file(path: Path, h: "hashlib._Hash") -> None:
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)


def verify(f: ModelFile) -> bool:
    if not is_present(f):
        return False
    h = hashlib.sha256()
    _hash_file(f.path, h)
    return h.hexdigest() == f.sha256


def download(
    f: ModelFile,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download one file to the models dir, resuming a partial `.part` file if present.

    The file is only moved into place after its size and SHA-256 match.
    """
    dest = f.path
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    h = hashlib.sha256()
    have = part.stat().st_size if part.exists() else 0
    if have > f.size:
        part.unlink()
        have = 0
    if have:
        _hash_file(part, h)

    if have < f.size:
        req = urllib.request.Request(f.url, headers={"User-Agent": "mytts"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            resp = urllib.request.urlopen(req, timeout=30)
        except urllib.error.URLError as e:
            raise DownloadError(f"Could not download {f.name}: {e}") from e
        with resp:
            if have and resp.status != 206:  # server ignored the range: start over
                h, have = hashlib.sha256(), 0
            with open(part, "ab" if have else "wb") as out:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    h.update(chunk)
                    have += len(chunk)
                    if progress:
                        progress(f, have, f.size)

    if have != f.size or h.hexdigest() != f.sha256:
        part.unlink(missing_ok=True)
        raise DownloadError(f"{f.name}: size or checksum mismatch, please retry the download")
    os.replace(part, dest)
    return dest


def ensure_all(progress: Progress | None = None, cancel: threading.Event | None = None) -> None:
    for f in missing():
        download(f, progress, cancel)
