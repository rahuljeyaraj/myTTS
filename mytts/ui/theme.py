"""Colors, fonts and the Qt stylesheet for the reader window."""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase


@dataclass(frozen=True)
class Theme:
    name: str
    dark: bool
    bg: str
    text: str
    muted: str
    highlight: str  # the sentence being read
    hover: str  # the sentence under the mouse
    accent: str
    border: str
    control: str  # hover/pressed background of buttons
    selection: str
    scroll: str


DARK = Theme(
    name="dark",
    dark=True,
    bg="#1c1b19",
    text="#d8d4cc",
    muted="#8c867b",
    highlight="#3a3326",
    hover="#26241f",
    accent="#d9a55b",
    border="#2c2a26",
    control="#2c2a26",
    selection="#4d4231",
    scroll="#3b3833",
)

SEPIA = Theme(
    name="sepia",
    dark=False,
    bg="#f5efe3",
    text="#3b362f",
    muted="#8a7f6e",
    highlight="#e8d9b5",
    hover="#efe6d3",
    accent="#a8701f",
    border="#e4d9c4",
    control="#ebe1cd",
    selection="#dccb9f",
    scroll="#d8ccb4",
)

THEMES = {t.name: t for t in (DARK, SEPIA)}


# Media-control glyphs: Segoe Fluent Icons (Windows 11) and Segoe MDL2 Assets
# (Windows 10) share these code points. Plain symbols are the last resort.
_ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
_GLYPHS = {
    "prev": "",
    "play": "",
    "pause": "",
    "stop": "",
    "next": "",
    "pin": "",
    "pinned": "",
    "theme": "",
    "chevron": "",
}
_FALLBACK = {
    "prev": "⏮", "play": "▶", "pause": "⏸", "stop": "■", "next": "⏭",
    "pin": "📌", "pinned": "📌", "theme": "◐", "chevron": "▾",
}

_TEXT_FONTS = ("Segoe UI Variable Text", "Segoe UI")
_UI_FONTS = ("Segoe UI Variable Small", "Segoe UI")


def _first_available(families: tuple[str, ...]) -> str | None:
    have = set(QFontDatabase.families())
    return next((f for f in families if f in have), None)


def icon_font(pixel_size: int = 16) -> tuple[QFont, dict[str, str]]:
    """The icon font and glyph table to use on this system."""
    family = _first_available(_ICON_FONTS)
    font = QFont(family) if family else QFont()
    font.setPixelSize(pixel_size)
    return font, (_GLYPHS if family else _FALLBACK)


def reading_font(point_size: float) -> QFont:
    font = QFont()
    family = _first_available(_TEXT_FONTS)
    if family:
        font.setFamily(family)
    font.setPointSizeF(point_size)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def ui_font() -> QFont:
    font = QFont()
    family = _first_available(_UI_FONTS)
    if family:
        font.setFamily(family)
    font.setPointSizeF(9.5)
    return font


def stylesheet(t: Theme) -> str:
    return f"""
QWidget#reader {{ background: {t.bg}; }}
QTextEdit {{
    background: {t.bg}; color: {t.text}; border: none;
    selection-background-color: {t.selection}; selection-color: {t.text};
}}
QWidget#bar {{ background: {t.bg}; border-top: 1px solid {t.border}; }}
QLabel {{ color: {t.muted}; background: transparent; }}
QLabel#status[error="true"] {{ color: {t.accent}; }}

QToolButton {{
    color: {t.text}; background: transparent; border: none; border-radius: 6px;
    min-width: 32px; min-height: 32px; padding: 0;
}}
QToolButton:hover {{ background: {t.control}; }}
QToolButton:pressed {{ background: {t.border}; }}
QToolButton:disabled {{ color: {t.border}; }}
QToolButton#play {{ color: {t.accent}; min-width: 38px; }}
QToolButton:checked {{ color: {t.accent}; }}

QComboBox {{
    color: {t.text}; background: transparent; border: 1px solid {t.border};
    border-radius: 6px; padding: 4px 8px; min-height: 22px;
}}
QComboBox:hover {{ background: {t.control}; }}
QComboBox:disabled {{ color: {t.muted}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ border: none; width: 0; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{
    background: {t.bg}; color: {t.text}; border: 1px solid {t.border};
    selection-background-color: {t.highlight}; selection-color: {t.text}; outline: 0; padding: 4px;
}}

QSlider {{ background: transparent; min-height: 24px; }}
QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ height: 4px; background: {t.muted}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {t.accent}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 2px 4px 0; }}
QScrollBar::handle:vertical {{ background: {t.scroll}; border-radius: 4px; min-height: 36px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QToolTip {{ color: {t.text}; background: {t.bg}; border: 1px solid {t.border}; padding: 4px 6px; }}
"""


def _colorref(hex_color: str) -> int:
    c = QColor(hex_color)
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def style_title_bar(hwnd: int, t: Theme) -> None:
    """Make the native title bar match the theme (dark mode on Windows 10, colors on 11)."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        dwm = ctypes.windll.dwmapi
    except OSError:
        return

    def set_attr(attr: int, value: int) -> None:
        v = ctypes.c_int(value)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))

    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 34, 35, 36
    set_attr(DWMWA_USE_IMMERSIVE_DARK_MODE, int(t.dark))
    # The calls below need Windows 11; earlier versions ignore them.
    set_attr(DWMWA_CAPTION_COLOR, _colorref(t.bg))
    set_attr(DWMWA_TEXT_COLOR, _colorref(t.text))
    set_attr(DWMWA_BORDER_COLOR, _colorref(t.border))


def set_topmost(hwnd: int, on: bool) -> bool:
    """Keep a window above others without recreating it (Qt's flag change hides the window)."""
    if sys.platform != "win32" or not hwnd:
        return False
    HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.c_uint]
    return bool(
        user32.SetWindowPos(
            ctypes.c_void_p(hwnd),
            ctypes.c_void_p(HWND_TOPMOST if on else HWND_NOTOPMOST),
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    )
