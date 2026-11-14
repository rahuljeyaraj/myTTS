"""The app icon, drawn with QPainter: sound-wave bars on an amber tile."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

TILE = "#d9a55b"  # the dark theme's accent
INK = "#1c1b19"  # the dark theme's background
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def paint(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)

    inset = max(0.5, size * 0.03)
    tile = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    p.setBrush(QColor(TILE))
    p.drawRoundedRect(tile, size * 0.22, size * 0.22)

    # Few, thick bars at small sizes so the tray icon stays legible.
    heights = (0.34, 0.62, 0.46) if size < 32 else (0.28, 0.52, 0.70, 0.44, 0.30)
    n = len(heights)
    area = tile.width() * (0.62 if size < 32 else 0.64)
    bar = area / (2 * n - 1)
    x = tile.center().x() - area / 2
    p.setBrush(QColor(INK))
    for h in heights:
        bh = tile.height() * h
        p.drawRoundedRect(QRectF(x, tile.center().y() - bh / 2, bar, bh), bar / 2, bar / 2)
        x += 2 * bar
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for s in SIZES:
        icon.addPixmap(paint(s))
    return icon
