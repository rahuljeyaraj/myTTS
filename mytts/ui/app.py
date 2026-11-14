"""Start the reader window: `python -m mytts` (or `python -m mytts open TEXT`)."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .. import __version__
from ..player import Player
from . import theme as themes
from .reader import ReaderWindow


def run(text: str | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("mytts")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")  # renders the stylesheet the same on every Windows version
    app.setFont(themes.ui_font())

    player = Player()
    window = ReaderWindow(player)
    app.aboutToQuit.connect(player.close)
    player.start()  # loads the voice model on a worker thread
    window.show()
    if text:
        QTimer.singleShot(0, lambda: window.load_text(text))
    return app.exec()
