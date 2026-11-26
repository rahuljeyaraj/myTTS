"""Copy a rectangle of the screen, in physical pixels, with GDI.

Qt's `QScreen.grabWindow` takes logical coordinates and converts them per screen,
which can be off by a row or two at 125 % scaling with several monitors. The
tools need exact pixels, so they use BitBlt from the desktop instead. The
calling process must be DPI aware (Qt 6 makes it per-monitor aware).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtGui import QImage

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000  # include layered (translucent) windows
DIB_RGB_COLORS = 0

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
DI_NORMAL = 3
CURSOR_SHOWING = 1


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hCursor", wintypes.HICON),
                ("ptScreenPos", wintypes.POINT)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]


user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class Grabber:
    """Grabs the same rectangle repeatedly, reusing the GDI objects (fast enough for 15 fps video)."""

    def __init__(self, left: int, top: int, width: int, height: int):
        self.left, self.top, self.width, self.height = left, top, width, height
        self._screen = user32.GetDC(None)
        self._dc = gdi32.CreateCompatibleDC(self._screen)
        self._bmp = gdi32.CreateCompatibleBitmap(self._screen, width, height)
        self._old = gdi32.SelectObject(self._dc, self._bmp)
        self._info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0)
        self._buf = ctypes.create_string_buffer(width * height * 4)

    def raw(self, cursor: bool = False) -> bytes:
        """The pixels as top-down BGRX rows. With `cursor`, the mouse pointer is drawn in."""
        gdi32.BitBlt(self._dc, 0, 0, self.width, self.height, self._screen, self.left, self.top,
                     SRCCOPY | CAPTUREBLT)
        if cursor:
            self._draw_cursor()
        gdi32.GetDIBits(self._dc, self._bmp, 0, self.height, self._buf, ctypes.byref(self._info), DIB_RGB_COLORS)
        return self._buf.raw

    def _draw_cursor(self) -> None:
        ci = CURSORINFO(ctypes.sizeof(CURSORINFO))
        if not user32.GetCursorInfo(ctypes.byref(ci)) or not ci.flags & CURSOR_SHOWING or not ci.hCursor:
            return
        ii = ICONINFO()
        if not user32.GetIconInfo(ci.hCursor, ctypes.byref(ii)):
            return
        try:
            x = ci.ptScreenPos.x - self.left - ii.xHotspot
            y = ci.ptScreenPos.y - self.top - ii.yHotspot
            user32.DrawIconEx(self._dc, x, y, ci.hCursor, 0, 0, 0, None, DI_NORMAL)
        finally:
            for bmp in (ii.hbmMask, ii.hbmColor):
                if bmp:
                    gdi32.DeleteObject(bmp)

    def image(self) -> QImage:
        return QImage(self.raw(), self.width, self.height, self.width * 4, QImage.Format.Format_RGB32).copy()

    def close(self) -> None:
        if self._dc:
            gdi32.SelectObject(self._dc, self._old)
            gdi32.DeleteObject(self._bmp)
            gdi32.DeleteDC(self._dc)
            user32.ReleaseDC(None, self._screen)
            self._dc = None

    def __enter__(self) -> Grabber:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def grab(left: int, top: int, width: int, height: int) -> QImage:
    with Grabber(left, top, width, height) as g:
        return g.image()
