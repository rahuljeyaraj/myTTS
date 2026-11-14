"""A system-wide hotkey through Win32 `RegisterHotKey`.

The hotkey is registered on a dedicated thread that runs its own `GetMessageW`
loop, so it fires even while the GUI thread is busy. Other threads talk to it
with `PostThreadMessageW`. `GlobalHotkey` wraps it in a QObject whose signals
arrive on the GUI thread.

Hotkeys are written like Qt shortcuts: "Ctrl+Alt+Space", "Win+Shift+R".
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, Qt, Signal

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MOD_NAMES = ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win"))
_MOD_ALIASES = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "windows": MOD_WIN, "meta": MOD_WIN, "super": MOD_WIN,
}


def _key_table() -> dict[int, str]:
    keys = {0x41 + i: chr(0x41 + i) for i in range(26)}  # A-Z
    keys |= {0x30 + i: str(i) for i in range(10)}  # 0-9
    keys |= {0x70 + i: f"F{i + 1}" for i in range(24)}  # F1-F24
    keys |= {0x60 + i: f"Num{i}" for i in range(10)}
    keys |= {
        0x20: "Space", 0x2D: "Ins", 0x2E: "Del", 0x24: "Home", 0x23: "End",
        0x21: "PgUp", 0x22: "PgDown", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
        0x13: "Pause", 0x91: "ScrollLock",
        0xC0: "`", 0xBD: "-", 0xBB: "=", 0xDB: "[", 0xDD: "]", 0xDC: "\\",
        0xBA: ";", 0xDE: "'", 0xBC: ",", 0xBE: ".", 0xBF: "/",
    }
    return keys


KEY_NAMES = _key_table()  # virtual-key code -> name
_KEY_CODES = {name.lower(): vk for vk, name in KEY_NAMES.items()}
_KEY_CODES |= {"insert": 0x2D, "delete": 0x2E, "pageup": 0x21, "pagedown": 0x22, "pgdn": 0x22}


def parse(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+Space' -> (modifier flags, virtual-key code). Raises ValueError."""
    parts = [p.strip() for p in text.split("+")]
    mods, vk = 0, None
    for i, part in enumerate(parts):
        low = part.lower()
        if i < len(parts) - 1:
            if low not in _MOD_ALIASES:
                raise ValueError(f"unknown modifier {part!r} in {text!r}")
            mods |= _MOD_ALIASES[low]
        else:
            vk = _KEY_CODES.get(low)
            if vk is None:
                raise ValueError(f"unknown key {part!r} in {text!r}")
    if not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        raise ValueError("a hotkey needs Ctrl, Alt or Win")
    return mods, vk


def to_text(mods: int, vk: int) -> str:
    names = [name for flag, name in _MOD_NAMES if mods & flag]
    return "+".join(names + [KEY_NAMES.get(vk, f"0x{vk:02X}")])


def normalize(text: str) -> str:
    """Canonical spelling ('alt+ctrl+space' -> 'Ctrl+Alt+Space'). Raises ValueError."""
    return to_text(*parse(text))


# Qt key codes -> virtual-key codes, for key events that carry no native code
# (synthetic events in tests). Letters and digits share their ASCII codes.
_QT_KEYS = {
    Qt.Key.Key_Space: 0x20, Qt.Key.Key_Insert: 0x2D, Qt.Key.Key_Delete: 0x2E,
    Qt.Key.Key_Home: 0x24, Qt.Key.Key_End: 0x23, Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22, Qt.Key.Key_Left: 0x25, Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27, Qt.Key.Key_Down: 0x28, Qt.Key.Key_Pause: 0x13,
    Qt.Key.Key_ScrollLock: 0x91,
}


def from_key_event(e) -> str | None:
    """The hotkey a QKeyEvent describes, or None if it is incomplete or not allowed."""
    m = e.modifiers()
    mods = 0
    if m & Qt.KeyboardModifier.ControlModifier:
        mods |= MOD_CONTROL
    if m & Qt.KeyboardModifier.AltModifier:
        mods |= MOD_ALT
    if m & Qt.KeyboardModifier.ShiftModifier:
        mods |= MOD_SHIFT
    if m & Qt.KeyboardModifier.MetaModifier:
        mods |= MOD_WIN
    vk = e.nativeVirtualKey()
    if not vk:
        key = e.key()
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            vk = int(key)
        elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
            vk = 0x70 + int(key) - int(Qt.Key.Key_F1)
        else:
            vk = _QT_KEYS.get(key, 0)
    if vk not in KEY_NAMES or not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return None
    return to_text(mods, vk)


_OWN_FLAG = {
    Qt.Key.Key_Control: Qt.KeyboardModifier.ControlModifier,
    Qt.Key.Key_Alt: Qt.KeyboardModifier.AltModifier,
    Qt.Key.Key_Shift: Qt.KeyboardModifier.ShiftModifier,
    Qt.Key.Key_Meta: Qt.KeyboardModifier.MetaModifier,
}


def modifier_text(e) -> str:
    """'Ctrl+Alt+' while only modifiers are held (for a live preview)."""
    m = e.modifiers()
    # Platforms disagree on whether a modifier key's own event includes its
    # flag, so set it from the event type: pressed means down, released up.
    own = _OWN_FLAG.get(e.key())
    if own is not None:
        m = m | own if e.type() == QEvent.Type.KeyPress else m & ~own
    names = [
        name
        for flag, name in (
            (Qt.KeyboardModifier.ControlModifier, "Ctrl"),
            (Qt.KeyboardModifier.AltModifier, "Alt"),
            (Qt.KeyboardModifier.ShiftModifier, "Shift"),
            (Qt.KeyboardModifier.MetaModifier, "Win"),
        )
        if m & flag
    ]
    return "+".join(names) + "+" if names else ""


# ------------------------------------------------------------------ Win32 thread

WM_QUIT, WM_HOTKEY, WM_APP = 0x0012, 0x0312, 0x8000
_WM_UPDATE = WM_APP + 1
_HOTKEY_ID = 1
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# on_status(hotkey, error): error is None once the hotkey is registered.
StatusSink = Callable[[str, "str | None"], None]


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    return user32


class HotkeyThread:
    """Owns the registration. `on_hotkey` and `on_status` run on the hotkey thread."""

    def __init__(self, on_hotkey: Callable[[], None], on_status: StatusSink):
        self._on_hotkey = on_hotkey
        self._on_status = on_status
        self._lock = threading.Lock()
        self._wanted: str | None = None
        self._tid = 0
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def start(self) -> None:
        if self._thread is None and self.available:
            self._thread = threading.Thread(target=self._run, name="mytts-hotkey", daemon=True)
            self._thread.start()
            self._ready.wait(2)

    def set(self, hotkey: str | None) -> None:
        """Register `hotkey` instead of the current one; None unregisters (e.g. while recording)."""
        with self._lock:
            self._wanted = hotkey
        if self._thread is None:
            if hotkey is not None and not self.available:
                self._on_status(hotkey, "Global hotkeys need Windows.")
            return
        self._post(_WM_UPDATE)

    def stop(self) -> None:
        if self._thread is not None:
            self._post(WM_QUIT)
            self._thread.join(timeout=2)
            self._thread = None

    def _post(self, msg: int) -> None:
        _user32().PostThreadMessageW(self._tid, msg, 0, 0)

    def _run(self) -> None:
        user32 = _user32()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # creates this thread's queue
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._ready.set()
        registered = False
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                try:
                    self._on_hotkey()
                except Exception:  # never let a callback kill the loop
                    pass
            elif msg.message == _WM_UPDATE:
                if registered:
                    user32.UnregisterHotKey(None, _HOTKEY_ID)
                    registered = False
                with self._lock:
                    wanted = self._wanted
                if wanted is not None:
                    registered, error = self._register(user32, wanted)
                    self._on_status(wanted, error)
        if registered:
            user32.UnregisterHotKey(None, _HOTKEY_ID)

    @staticmethod
    def _register(user32, hotkey: str) -> tuple[bool, str | None]:
        try:
            mods, vk = parse(hotkey)
        except ValueError as e:
            return False, str(e)
        if user32.RegisterHotKey(None, _HOTKEY_ID, mods | MOD_NOREPEAT, vk):
            return True, None
        code = ctypes.get_last_error()
        if code == ERROR_HOTKEY_ALREADY_REGISTERED:
            return False, f"{hotkey} is already used by another app."
        return False, f"Could not register {hotkey} (error {code})."


class GlobalHotkey(QObject):
    """Qt face of `HotkeyThread`; its signals are delivered on the GUI thread."""

    activated = Signal()
    status = Signal(str, object)  # hotkey, error message or None

    _fired = Signal()
    _status = Signal(str, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._fired.connect(self.activated, Qt.ConnectionType.QueuedConnection)
        self._status.connect(self._on_status, Qt.ConnectionType.QueuedConnection)
        self._thread = HotkeyThread(self._fired.emit, self._status.emit)
        self.hotkey: str | None = None
        self.error: str | None = None

    def start(self, hotkey: str) -> None:
        self._thread.start()
        self.set(hotkey)

    def set(self, hotkey: str | None) -> None:
        self._thread.set(hotkey)

    def stop(self) -> None:
        self._thread.stop()

    def _on_status(self, hotkey: str, error: object) -> None:
        self.hotkey, self.error = hotkey, error
        self.status.emit(hotkey, error)
