"""Where mytts keeps its files on disk."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "mytts"


def frozen() -> bool:
    """True in the self-contained build (myTTS.exe), False when run by a Python interpreter."""
    return bool(getattr(sys, "frozen", False))


def exe_path() -> Path:
    """myTTS.exe in the self-contained build."""
    return Path(sys.executable).resolve()


def installed_by_setup() -> bool:
    """True for myTTS.exe installed by the setup program, which puts its uninstaller next to it.

    A build in dist\\myTTS (or a copy of it elsewhere) has no uninstaller.
    """
    return frozen() and any(exe_path().parent.glob("unins*.exe"))


def _local_appdata() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) if base else Path.home() / "AppData" / "Local"


def data_dir() -> Path:
    """Per-user, non-roaming data (voice models are large; keep them out of roaming)."""
    return _local_appdata() / APP_NAME


def models_dir() -> Path:
    override = os.environ.get("MYTTS_MODELS_DIR")
    return Path(override) if override else data_dir() / "models"


def logs_dir() -> Path:
    return data_dir() / "logs"


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    return (Path(base) if base else Path.home() / "AppData" / "Roaming") / APP_NAME


def licenses_dir() -> Path | None:
    """The `licenses` folder next to myTTS.exe, if this build has one."""
    if not frozen():
        return None
    d = exe_path().parent / "licenses"
    return d if d.is_dir() else None


def download_command() -> str:
    """How to download the voice model from a terminal, for messages."""
    return "myTTS.exe download" if frozen() else "python -m mytts download"
