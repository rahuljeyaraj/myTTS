"""Start with Windows: a value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""

from __future__ import annotations

import sys
from pathlib import Path

from . import paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "mytts"


def _gui_python() -> str:
    """pythonw.exe next to the running interpreter, so no console window opens at login."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.is_file() else exe)


def _installed() -> bool:
    try:
        from importlib.metadata import distribution

        distribution("mytts")
        return True
    except Exception:
        return False


def command() -> str:
    """The command line that starts mytts in the tray."""
    if paths.frozen():
        return f'"{paths.exe_path()}" --tray'
    py = _gui_python()
    if _installed():
        return f'"{py}" -m mytts --tray'
    # Running from a source checkout: the Run key has no working directory, so
    # put the checkout on sys.path explicitly.
    root = str(Path(__file__).resolve().parent.parent)
    code = f"import sys; sys.path.insert(0, {root!r}); from mytts.__main__ import main; sys.exit(main())"
    return f'"{py}" -c "{code}" --tray'


def _open(write: bool = False):
    import winreg

    access = winreg.KEY_READ | (winreg.KEY_SET_VALUE if write else 0)
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def registered_command() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with _open() as key:
            value, _type = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return None


def is_enabled() -> bool:
    return registered_command() is not None


def set_enabled(on: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with _open(write=True) as key:
        if on:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def is_install() -> bool:
    """True for an installed copy: myTTS.exe installed by setup, or mytts installed into a venv.

    A build in dist\\myTTS and a source checkout are not installs.
    """
    return paths.installed_by_setup() if paths.frozen() else _installed()


def refresh() -> None:
    """If enabled, point the entry at this copy, when it is an installed one (it may have moved).

    A dev build or a source checkout leaves the entry alone, so running one on a machine
    with myTTS installed doesn't take over "Start with Windows". Turning the setting on
    from such a copy still points the entry at it.
    """
    if not is_install():
        return
    current = registered_command()
    if current is not None and current != command():
        set_enabled(True)
