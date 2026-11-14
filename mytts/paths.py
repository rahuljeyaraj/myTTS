"""Where mytts keeps its files on disk."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "mytts"


def _local_appdata() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) if base else Path.home() / "AppData" / "Local"


def data_dir() -> Path:
    """Per-user, non-roaming data (voice models are large; keep them out of roaming)."""
    return _local_appdata() / APP_NAME


def models_dir() -> Path:
    override = os.environ.get("MYTTS_MODELS_DIR")
    return Path(override) if override else data_dir() / "models"


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    return (Path(base) if base else Path.home() / "AppData" / "Roaming") / APP_NAME
