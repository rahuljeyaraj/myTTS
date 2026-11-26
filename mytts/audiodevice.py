"""Notice when Windows changes the default speaker.

PortAudio picks its default output device once, when it initializes, and a
stream stays on the device it was opened on. When Bluetooth headphones connect
(or the user picks another speaker), Windows moves its default but our stream
would keep playing on the old one. `DeviceWatcher` polls the default render
endpoint through the MMDevice API and calls back when it changes, so the player
can reopen its stream.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable

POLL_S = 0.5

_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_eRender, _eConsole = 0, 0
_CLSCTX_ALL = 0x17
_COINIT_MULTITHREADED = 0x0


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    g = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


def _method(obj: ctypes.c_void_p, index: int, *argtypes):
    """Vtable entry `index` of a COM object, as a callable taking the object first."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    return proto(vtable[index])


def _release(obj: ctypes.c_void_p) -> None:
    if obj:
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
            ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0][2]
        )(obj)


class DefaultOutput:
    """Reads the endpoint id of the default speaker. Use it on one thread, with COM initialized."""

    def __init__(self):
        self._enum = ctypes.c_void_p()
        ctypes.oledll.ole32.CoCreateInstance(
            ctypes.byref(_guid(_CLSID_MMDeviceEnumerator)),
            None,
            _CLSCTX_ALL,
            ctypes.byref(_guid(_IID_IMMDeviceEnumerator)),
            ctypes.byref(self._enum),
        )

    def id(self) -> str | None:
        """The default output endpoint's id, or None when there is no output device."""
        device = ctypes.c_void_p()
        try:
            # IMMDeviceEnumerator::GetDefaultAudioEndpoint
            _method(self._enum, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                self._enum, _eRender, _eConsole, ctypes.byref(device)
            )
        except OSError:  # E_NOTFOUND: no output device at all
            return None
        try:
            text = ctypes.c_wchar_p()
            _method(device, 5, ctypes.POINTER(ctypes.c_wchar_p))(device, ctypes.byref(text))  # IMMDevice::GetId
            try:
                return text.value
            finally:
                ctypes.windll.ole32.CoTaskMemFree(text)
        finally:
            _release(device)

    def close(self) -> None:
        _release(self._enum)
        self._enum = ctypes.c_void_p()


class DeviceWatcher:
    """Calls `on_change()` from its own thread when the default speaker changes.

    A new default is reported once it has been seen on two polls in a row, so a
    device that Windows switches to and away from at once is ignored. Losing
    every output device is not reported; the device that comes back is.
    """

    def __init__(self, on_change: Callable[[], None], interval: float = POLL_S,
                 probe: Callable[[], Callable[[], str | None]] | None = None):
        self._on_change = on_change
        self._interval = interval
        self._probe = probe
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None and (self._probe is not None or sys.platform == "win32"):
            self._thread = threading.Thread(target=self._run, name="mytts-devices", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        com = self._probe is None
        if com:
            ctypes.windll.ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
        reader = None
        try:
            if com:
                reader = DefaultOutput()
                read = reader.id
            else:
                read = self._probe()
            self._watch(read)
        except Exception:  # no audio service: nothing to watch
            pass
        finally:
            if reader is not None:
                reader.close()
            if com:
                ctypes.windll.ole32.CoUninitialize()

    def _watch(self, read: Callable[[], str | None]) -> None:
        current = read()
        candidate = None
        while not self._stop.wait(self._interval):
            try:
                seen = read()
            except Exception:
                continue
            if seen is None or seen == current:
                candidate = None
            elif seen != candidate:
                candidate = seen
            else:
                current, candidate = seen, None
                self._on_change()
