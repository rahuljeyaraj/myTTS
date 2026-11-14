"""Win32 window helpers: bring a window to the front, find the app the user was in."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

_SHELL_CLASSES = {
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland",
    "Progman", "WorkerW", "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
}
GW_HWNDNEXT = 2
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
SW_RESTORE = 9
DWMWA_CLOAKED = 14


def _user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    H = wintypes.HWND
    u.GetForegroundWindow.restype = H
    u.SetForegroundWindow.argtypes = [H]
    u.BringWindowToTop.argtypes = [H]
    u.IsIconic.argtypes = [H]
    u.IsWindowVisible.argtypes = [H]
    u.ShowWindow.argtypes = [H, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    u.GetTopWindow.argtypes = [H]
    u.GetTopWindow.restype = H
    u.GetWindow.argtypes = [H, wintypes.UINT]
    u.GetWindow.restype = H
    u.GetWindowLongW.argtypes = [H, ctypes.c_int]
    u.GetWindowLongW.restype = wintypes.LONG
    u.GetClassNameW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowTextLengthW.argtypes = [H]
    return u


def enabled() -> bool:
    """True when Qt draws real Windows windows (not under the offscreen test platform)."""
    if sys.platform != "win32":
        return False
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.platformName() == "windows"


def foreground_window() -> int:
    if sys.platform != "win32":
        return 0
    return _user32().GetForegroundWindow() or 0


def bring_to_front(hwnd: int) -> bool:
    """Activate `hwnd` even when Windows' foreground lock would only flash its taskbar button.

    Attaching to the input queue of the current foreground thread is the usual
    way around the lock; it is only used if the plain call did not work.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    u = _user32()
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, SW_RESTORE)
    if u.SetForegroundWindow(hwnd) and u.GetForegroundWindow() == hwnd:
        return True
    fg = u.GetForegroundWindow()
    fg_thread = u.GetWindowThreadProcessId(fg, None) if fg else 0
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and u.AttachThreadInput(me, fg_thread, True))
    try:
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        if attached:
            u.AttachThreadInput(me, fg_thread, False)
    return u.GetForegroundWindow() == hwnd


def previous_app_window() -> int:
    """The window Alt+Tab would switch to: the topmost visible app window of another process.

    Used by the tray menu, which takes the focus away from the app whose
    selection the user wants read.
    """
    if sys.platform != "win32":
        return 0
    u = _user32()
    dwm = ctypes.windll.dwmapi
    me = os.getpid()
    buf = ctypes.create_unicode_buffer(256)
    hwnd = u.GetTopWindow(None)
    while hwnd:
        if _is_app_window(u, dwm, hwnd, me, buf):
            return hwnd
        hwnd = u.GetWindow(hwnd, GW_HWNDNEXT)
    return 0


def _is_app_window(u, dwm, hwnd, my_pid: int, buf) -> bool:
    if not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd) or not u.GetWindowTextLengthW(hwnd):
        return False
    if u.GetWindowLongW(hwnd, GWL_EXSTYLE) & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
        return False
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == my_pid:
        return False
    u.GetClassNameW(hwnd, buf, len(buf))
    if buf.value in _SHELL_CLASSES:
        return False
    cloaked = wintypes.DWORD()
    dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return not cloaked.value  # cloaked: on another virtual desktop, or a suspended UWP app
