"""User settings, saved as JSON in %APPDATA%\\mytts\\settings.json.

Loading never fails: a missing or damaged file, an unknown key or a value of the
wrong type falls back to the default for that field.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .engine import DEFAULT_VOICE
from .paths import config_dir

DEFAULT_HOTKEY = "Ctrl+Alt+Space"
DEFAULT_NEXT_HOTKEY = "Ctrl+Alt+Right"
DEFAULT_PREV_HOTKEY = "Ctrl+Alt+Left"

# Global hotkeys: action name -> (Settings field, label shown to the user).
HOTKEYS = {
    "read": ("hotkey", "Read selection"),
    "next": ("next_hotkey", "Next sentence"),
    "prev": ("prev_hotkey", "Previous sentence"),
}


def settings_path() -> Path:
    return config_dir() / "settings.json"


@dataclass
class Settings:
    voice: str = DEFAULT_VOICE
    speed: float = 1.0
    theme: str = "dark"
    font_size: float = 13.0
    hotkey: str = DEFAULT_HOTKEY  # read selection; pressed while reading, it pauses
    next_hotkey: str = DEFAULT_NEXT_HOTKEY
    prev_hotkey: str = DEFAULT_PREV_HOTKEY
    always_on_top: bool = False
    restore_clipboard: bool = True
    geometry: str = ""  # base64 of QWidget.saveGeometry()
    tray_hint_shown: bool = False  # "still running in the tray" is shown once

    # "Start with Windows" is not stored here: the registry Run key is the
    # source of truth (see autostart.py), so the two can never disagree.

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or settings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        s = cls()
        if not isinstance(data, dict):
            return s
        for f in fields(cls):
            if f.name not in data:
                continue
            value, default = data[f.name], getattr(s, f.name)
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, float):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                value = float(value) if ok else value
            else:
                ok = isinstance(value, type(default))
            if ok:
                setattr(s, f.name, value)
        return s

    def hotkeys(self) -> dict[str, str]:
        return {name: getattr(self, field) for name, (field, _label) in HOTKEYS.items()}

    def save(self, path: Path | None = None) -> None:
        """Write atomically, so a crash mid-write cannot leave a half-written file."""
        path = path or settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
