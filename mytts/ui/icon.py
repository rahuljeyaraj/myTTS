"""The app icon, drawn with QPainter: sound-wave bars on an amber tile.

`save_ico()` writes it as a Windows .ico file for the Start menu shortcut. The
drawing uses QImage only, so it also works without a QGuiApplication.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

TILE = "#d9a55b"  # the dark theme's accent
INK = "#1c1b19"  # the dark theme's background
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
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
    return img


def paint(size: int) -> QPixmap:
    return QPixmap.fromImage(render(size))


def app_icon() -> QIcon:
    icon = QIcon()
    for s in SIZES:
        icon.addPixmap(paint(s))
    return icon


def _png(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data.data())


def _dib(img: QImage) -> bytes:
    """A 32-bit BMP icon image: header, BGRA rows bottom-up, then the 1-bit AND mask."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)  # straight alpha; bytes are B, G, R, A
    w, h = img.width(), img.height()
    bits = bytes(img.constBits())
    stride = img.bytesPerLine()
    rows = [bits[y * stride : y * stride + 4 * w] for y in range(h)]
    mask_stride = ((w + 31) // 32) * 4
    mask = bytearray()
    for row in reversed(rows):
        line = bytearray(mask_stride)
        for x in range(w):
            if row[4 * x + 3] == 0:  # fully transparent pixel
                line[x // 8] |= 0x80 >> (x % 8)
        mask += line
    pixels = b"".join(reversed(rows))
    header = struct.pack("<IiiHHIIiiII", 40, w, 2 * h, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + pixels + bytes(mask)


def ico_bytes(sizes: tuple[int, ...] = SIZES) -> bytes:
    """The icon as .ico data. 256 px is stored as PNG, smaller sizes as BMP, as Windows expects."""
    images = [(s, _png(render(s)) if s >= 256 else _dib(render(s))) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, data in images:
        dim = 0 if s >= 256 else s  # 0 means 256 in the directory entry
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + b"".join(data for _s, data in images)


def save_ico(path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(ico_bytes())
    tmp.replace(path)
