"""Read the text selected in another app by sending it Ctrl+C.

`capture_selection()`:

1. waits up to ~1 s for the hotkey's modifier keys to be released, so the app
   doesn't see Ctrl+Alt+C;
2. saves what is on the clipboard (every format it can copy safely, not only text);
3. notes `GetClipboardSequenceNumber()`, sends Ctrl+C with `SendInput` (Ctrl+Insert
   in terminals, where Ctrl+C would interrupt the running program), and polls
   for up to ~600 ms for the number to change;
4. reads the copied text, then puts the saved clipboard back.

If the number never changes, nothing was selected (or the app ignored Ctrl+C)
and the clipboard was not touched.

Windows (UIPI) does not let a normal app send keys to an app running as
administrator, so selections in elevated windows can't be captured.

The polling logic is separate from the Win32 calls (`Win32Clipboard`), so
tests can run it against a fake.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Protocol

MODIFIER_WAIT_S = 1.0
COPY_WAIT_S = 0.6
POLL_S = 0.01

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN, VK_C = 0x10, 0x11, 0x12, 0x5B, 0x5C, 0x43
VK_INSERT = 0x2D
MODIFIER_KEYS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)
KEYEVENTF_EXTENDEDKEY = 0x0001

# In a terminal, Ctrl+C without a selection interrupts the running program.
# These terminals all copy with Ctrl+Insert, which never interrupts.
TERMINAL_CLASSES = {
    "ConsoleWindowClass",  # classic console (conhost)
    "CASCADIA_HOSTING_WINDOW_CLASS",  # Windows Terminal
    "mintty",  # Git Bash, Cygwin, MSYS2
    "PuTTY",
    "VirtualConsoleClass",  # ConEmu, Cmder
}


def copy_key(window_class: str) -> tuple[int, int]:
    """The copy shortcut's key (pressed with Ctrl) and its extra flags for the window in front."""
    if window_class in TERMINAL_CLASSES:
        return VK_INSERT, KEYEVENTF_EXTENDEDKEY  # the navigation-cluster Insert, not numpad 0
    return VK_C, 0


class ClipboardSystem(Protocol):
    def modifiers_down(self) -> list[int]: ...
    def sequence(self) -> int: ...
    def snapshot(self) -> object | None: ...
    def restore(self, saved: object) -> None: ...
    def read_text(self) -> str | None: ...
    def send_copy(self, still_held: list[int]) -> None: ...


def capture_selection(
    restore: bool = True,
    system: ClipboardSystem | None = None,
    modifier_wait: float = MODIFIER_WAIT_S,
    copy_wait: float = COPY_WAIT_S,
) -> str | None:
    """The selected text; "" if something without text was copied; None if nothing was copied."""
    if system is not None:
        return _capture(system, restore, modifier_wait, copy_wait)
    cb = Win32Clipboard()
    try:
        return _capture(cb, restore, modifier_wait, copy_wait)
    finally:
        cb.close()


def _capture(cb: ClipboardSystem, restore: bool, modifier_wait: float, copy_wait: float) -> str | None:
    deadline = time.monotonic() + modifier_wait
    held = cb.modifiers_down()
    while held and time.monotonic() < deadline:
        time.sleep(POLL_S)
        held = cb.modifiers_down()

    saved = cb.snapshot() if restore else None
    before = cb.sequence()
    cb.send_copy(held)

    changed, text = False, None
    deadline = time.monotonic() + copy_wait
    while time.monotonic() < deadline:
        time.sleep(POLL_S)
        if cb.sequence() != before:
            changed = True
            # None while the app still holds the clipboard open, or before it
            # has added a text format: keep polling until the deadline.
            text = cb.read_text()
            if text is not None:
                break
    if not changed:
        return None
    if saved is not None:
        cb.restore(saved)
    return text or ""


# ------------------------------------------------------------------------ Win32

CF_TEXT, CF_BITMAP, CF_METAFILEPICT, CF_OEMTEXT = 1, 2, 3, 7
CF_PALETTE, CF_UNICODETEXT, CF_ENHMETAFILE = 9, 13, 14
CF_OWNERDISPLAY, CF_DSPBITMAP, CF_DSPMETAFILEPICT, CF_DSPENHMETAFILE = 0x80, 0x82, 0x83, 0x8E
# Formats whose data is a GDI or other non-memory handle; copying them as bytes is unsafe.
_HANDLE_FORMATS = {CF_BITMAP, CF_METAFILEPICT, CF_PALETTE, CF_ENHMETAFILE,
                   CF_OWNERDISPLAY, CF_DSPBITMAP, CF_DSPMETAFILEPICT, CF_DSPENHMETAFILE}
# OLE's own bookkeeping; it points into the process that copied, so it can't be replayed.
_SKIP_NAMES = {"DataObject", "Ole Private Data", "OlePrivateData"}
_HISTORY_OPT_OUT = ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")
SNAPSHOT_LIMIT = 64 << 20  # bytes; larger formats are not saved

GMEM_MOVEABLE = 0x0002
INPUT_KEYBOARD, KEYEVENTF_KEYUP = 1, 0x0002
HWND_MESSAGE = wintypes.HWND(-3)
_INJECTED_TAG = 0x6D797474  # "mytt" in dwExtraInfo, to recognize our own key events


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _InputUnion)]


def _dlls():
    u = ctypes.WinDLL("user32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    H, P, U, B = wintypes.HANDLE, ctypes.c_void_p, wintypes.UINT, wintypes.BOOL
    sigs = {
        (u, "OpenClipboard"): ([wintypes.HWND], B),
        (u, "CloseClipboard"): ([], B),
        (u, "EmptyClipboard"): ([], B),
        (u, "EnumClipboardFormats"): ([U], U),
        (u, "GetClipboardData"): ([U], H),
        (u, "SetClipboardData"): ([U, H], H),
        (u, "IsClipboardFormatAvailable"): ([U], B),
        (u, "GetClipboardSequenceNumber"): ([], wintypes.DWORD),
        (u, "GetClipboardFormatNameW"): ([U, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        (u, "RegisterClipboardFormatW"): ([wintypes.LPCWSTR], U),
        (u, "GetAsyncKeyState"): ([ctypes.c_int], wintypes.SHORT),
        (u, "SendInput"): ([U, ctypes.POINTER(INPUT), ctypes.c_int], U),
        (u, "MapVirtualKeyW"): ([U, U], U),
        (u, "CreateWindowExW"): ([wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, P], wintypes.HWND),
        (u, "DestroyWindow"): ([wintypes.HWND], B),
        (u, "GetForegroundWindow"): ([], wintypes.HWND),
        (u, "GetClassNameW"): ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        (k, "GlobalAlloc"): ([U, ctypes.c_size_t], H),
        (k, "GlobalLock"): ([H], P),
        (k, "GlobalUnlock"): ([H], B),
        (k, "GlobalSize"): ([H], ctypes.c_size_t),
        (k, "GlobalFree"): ([H], H),
    }
    for (dll, name), (args, res) in sigs.items():
        fn = getattr(dll, name)
        fn.argtypes, fn.restype = args, res
    return u, k


class Win32Clipboard:
    """The real clipboard and keyboard. Create and use it on one thread."""

    def __init__(self):
        self.user32, self.kernel32 = _dlls()
        self._hwnd = None

    # The clipboard owner should be a window: with a NULL owner, SetClipboardData
    # is documented to fail. A message-only window is invisible and cheap.
    def _owner(self):
        if self._hwnd is None:
            self._hwnd = self.user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0,
                                                     HWND_MESSAGE, None, None, None)
        return self._hwnd

    def close(self) -> None:
        if self._hwnd:
            self.user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _open(self, tries: int = 25) -> bool:
        """Open the clipboard, retrying while another app has it open (up to ~250 ms)."""
        owner = self._owner()
        for _ in range(tries):
            if self.user32.OpenClipboard(owner):
                return True
            time.sleep(POLL_S)
        return False

    # ----------------------------------------------------------- ClipboardSystem

    def modifiers_down(self) -> list[int]:
        return [vk for vk in MODIFIER_KEYS if self.user32.GetAsyncKeyState(vk) & 0x8000]

    def sequence(self) -> int:
        return self.user32.GetClipboardSequenceNumber()

    def snapshot(self) -> list[tuple[int, bytes]] | None:
        """Every memory-backed format on the clipboard, or None if it couldn't be opened."""
        u, k = self.user32, self.kernel32
        if not self._open():
            return None
        try:
            formats, f = [], u.EnumClipboardFormats(0)
            while f:
                formats.append(f)
                f = u.EnumClipboardFormats(f)
            has_unicode = CF_UNICODETEXT in formats
            saved, total = [], 0
            for f in formats:
                if f in _HANDLE_FORMATS or 0x200 <= f <= 0x3FF:  # private and GDI-object ranges
                    continue
                if has_unicode and f in (CF_TEXT, CF_OEMTEXT):  # Windows derives these again
                    continue
                if f >= 0xC000 and self._format_name(f) in _SKIP_NAMES:
                    continue
                h = u.GetClipboardData(f)
                size = k.GlobalSize(h) if h else 0
                if not size or total + size > SNAPSHOT_LIMIT:
                    continue
                p = k.GlobalLock(h)
                if not p:
                    continue
                try:
                    saved.append((f, ctypes.string_at(p, size)))
                    total += size
                finally:
                    k.GlobalUnlock(h)
            return saved
        finally:
            u.CloseClipboard()

    def restore(self, saved: list[tuple[int, bytes]]) -> None:
        u, k = self.user32, self.kernel32
        if not self._open(tries=50):
            return
        try:
            u.EmptyClipboard()
            data = list(saved)
            # Keep the restore out of Win+V history: the original entry is already there.
            have = {f for f, _ in data}
            for name in _HISTORY_OPT_OUT:
                f = u.RegisterClipboardFormatW(name)
                if f and f not in have:
                    data.append((f, (0).to_bytes(4, "little")))
            for f, blob in data:
                h = k.GlobalAlloc(GMEM_MOVEABLE, max(1, len(blob)))
                if not h:
                    continue
                p = k.GlobalLock(h)
                if p:
                    ctypes.memmove(p, blob, len(blob))
                    k.GlobalUnlock(h)
                if not u.SetClipboardData(f, h):
                    k.GlobalFree(h)  # ownership only passes to Windows on success
        finally:
            u.CloseClipboard()

    def read_text(self) -> str | None:
        u, k = self.user32, self.kernel32
        if not u.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        if not self._open(tries=5):
            return None
        try:
            h = u.GetClipboardData(CF_UNICODETEXT)
            p = k.GlobalLock(h) if h else None
            if not p:
                return None
            try:
                return ctypes.wstring_at(p)
            finally:
                k.GlobalUnlock(h)
        finally:
            u.CloseClipboard()

    def send_copy(self, still_held: list[int]) -> None:
        """Ctrl+C (Ctrl+Insert in terminals). Modifiers the user still holds (other than Ctrl)
        are released while Ctrl is down, so the app sees a plain copy shortcut and a lone Alt
        or Win release can't open a menu."""
        key, ext = copy_key(self._foreground_class())
        keys = [(VK_CONTROL, 0)]
        keys += [(vk, KEYEVENTF_KEYUP) for vk in still_held if vk != VK_CONTROL]
        keys += [(key, ext), (key, ext | KEYEVENTF_KEYUP), (VK_CONTROL, KEYEVENTF_KEYUP)]
        inputs = (INPUT * len(keys))()
        for item, (vk, flags) in zip(inputs, keys):
            item.type = INPUT_KEYBOARD
            item.u.ki = KEYBDINPUT(vk, self.user32.MapVirtualKeyW(vk, 0), flags, 0, _INJECTED_TAG)
        self.user32.SendInput(len(keys), inputs, ctypes.sizeof(INPUT))

    def _foreground_class(self) -> str:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buf, len(buf))
        return buf.value

    # --------------------------------------------------------------- internals

    def _format_name(self, f: int) -> str:
        buf = ctypes.create_unicode_buffer(128)
        n = self.user32.GetClipboardFormatNameW(f, buf, len(buf))
        return buf.value[:n]
