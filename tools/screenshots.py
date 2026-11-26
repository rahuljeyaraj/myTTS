"""Regenerate the README screenshots in docs/.

    .venv\\Scripts\\python tools\\screenshots.py

Opens the reader on the real desktop with sample text, reading the fourth
sentence, and captures the window with its title bar in both themes, then the
settings window. Audio goes to a silent stream, so nothing is heard. Needs the
voice model. Settings are kept in a temporary folder, not in %APPDATA%.
"""

from __future__ import annotations

import ctypes
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import numpy as np  # noqa: E402

from mytts import models  # noqa: E402
from mytts.engine import SAMPLE_RATE  # noqa: E402
from mytts.player import Player, State  # noqa: E402
from mytts.settings import Settings  # noqa: E402
from mytts.ui import native  # noqa: E402
from mytts.ui import theme as themes  # noqa: E402
from mytts.ui.app import App  # noqa: E402
from mytts.ui.icon import app_icon  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from screengrab import grab  # noqa: E402

OUT = ROOT / "docs"
SAMPLE = """Morning on the harbour

The fog had not yet lifted when the first boats slipped out of the harbour. Gulls followed them in lazy circles, calling to each other over the low hum of the engines. On the quay, an old man unfolded his chair in the same spot he had chosen for forty years.

He did not fish, and he did not read. He simply watched the water change colour as the sun climbed: grey, then silver, then a blue so clear it almost seemed to ring. By nine o'clock the café behind him was full of voices and the smell of fresh bread.

Visitors sometimes asked him what he was waiting for. He would smile and point at the horizon, where the last of the fog was folding itself away like a letter. “That,” he said. “Every morning, that.”
"""
READING = 3  # index of the highlighted sentence

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1


class SilentStream:
    """Stands in for the PortAudio stream. Audio is only pulled by `pump()`, so the
    player stays on its sentence for as long as the screenshots take."""

    streams: list[SilentStream] = []

    def __init__(self, callback):
        self.callback = callback
        SilentStream.streams.append(self)

    @staticmethod
    def factory(callback):
        return SilentStream(callback), SAMPLE_RATE

    def pump(self, frames: int = 320) -> None:
        try:
            self.callback(np.zeros((frames, 1), np.float32), frames, None, None)
        except Exception:  # CallbackStop: the player is idle
            pass

    def start(self) -> None: ...
    def abort(self) -> None: ...
    def close(self) -> None: ...


def wait(ms: int) -> None:
    # Not QTest.qWait: it keeps the GIL while it sleeps, which starves the synthesis thread.
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(predicate, timeout_ms: int = 20_000) -> None:
    for _ in range(timeout_ms // 20):
        if predicate():
            return
        wait(20)
    raise TimeoutError("the reader did not get ready in time")


class Backdrop(QWidget):
    """A plain screen-sized window behind the one being captured, in its background
    colour, so no other window can show at its edges (at 125 % scaling a window's
    frame can be a pixel or two larger than what Qt paints)."""

    def __init__(self, screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.color = QColor(themes.DARK.bg)
        self.setGeometry(screen.geometry())

    def set_color(self, color: str) -> None:
        self.color = QColor(color)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        QPainter(self).fillRect(self.rect(), self.color)


def snap(n: float) -> int:
    """Round to a multiple of 4 logical pixels, which is a whole number of device
    pixels at 100, 125, 150 and 200 % scaling."""
    return 4 * round(n / 4)


def capture(widget: QWidget, name: str) -> None:
    """Screen-grab the window, title bar included, without the drop shadow."""
    hwnd = wintypes.HWND(int(widget.winId()))
    dwm = ctypes.windll.dwmapi
    corner = ctypes.c_int(DWMWCP_DONOTROUND)  # square corners: no desktop showing through
    dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), ctypes.sizeof(corner))
    themes.set_topmost(int(widget.winId()), True)
    native.bring_to_front(int(widget.winId()))  # an active title bar
    wait(600)  # let DWM redraw the frame

    r = wintypes.RECT()  # physical pixels, without the invisible resize border
    dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r))
    shot = grab(r.left, r.top, r.right - r.left, r.bottom - r.top)
    OUT.mkdir(exist_ok=True)
    shot.save(str(OUT / name))
    themes.set_topmost(int(widget.winId()), False)
    print(f"{OUT / name}: {shot.width()}x{shot.height()}")


def main() -> int:
    if models.missing():
        print("The voice model is missing: run `python -m mytts download` first.")
        return 1
    native.set_app_id()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("mytts")
    app.setStyle("Fusion")
    app.setFont(themes.ui_font())
    app.setWindowIcon(app_icon())

    with tempfile.TemporaryDirectory() as tmp:
        player = Player(stream_factory=SilentStream.factory)
        controller = App(Settings(), Path(tmp) / "settings.json", player=player, use_tray=False, use_hotkey=False)
        window = controller.window
        controller.start(show=True)
        backdrop = Backdrop(window.screen())
        backdrop.show()
        themes.set_topmost(int(backdrop.winId()), True)  # above every other app; capture() raises the window above it
        window.setGeometry(QRect(160, 60, 780, 720))
        wait_until(lambda: bool(player.voices))
        window.load_text(SAMPLE, play=False)
        player.play(READING)

        def started() -> bool:  # one audio block once the sentence is ready turns "loading" into "playing"
            SilentStream.streams[-1].pump()
            return player.state == State.PLAYING

        wait_until(started)
        wait(400)  # past the status label's loading delay

        capture(window, "reader-dark.png")
        window.apply_theme("sepia")
        backdrop.set_color(themes.THEMES["sepia"].bg)
        capture(window, "reader-sepia.png")
        backdrop.set_color(themes.DARK.bg)
        window.apply_theme("dark")

        controller.show_settings()
        dialog = controller.dialog
        c = window.geometry().center() - dialog.rect().center()
        dialog.move(QPoint(snap(c.x()), snap(c.y())))
        capture(dialog, "settings.png")

        controller.shutdown()
        backdrop.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
