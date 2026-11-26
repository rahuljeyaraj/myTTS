"""Draw docs/social-preview.png (1280x640, for GitHub) and docs/icon.png (the README's icon).

    .venv\\Scripts\\python tools\\social_preview.py

The image is uploaded by hand in the repository's Settings > General > Social
preview; GitHub has no API for it. It uses the app icon and the reader's dark
theme colours.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

from mytts import DISPLAY_NAME  # noqa: E402
from mytts.ui import theme as themes  # noqa: E402
from mytts.ui.icon import render  # noqa: E402

W, H = 1280, 640
OUT = ROOT / "docs" / "social-preview.png"
ICON = ROOT / "docs" / "icon.png"


def main() -> int:
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 (fonts need it)
    t = themes.DARK
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(t.bg))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # GitHub crops the edges in some places: keep everything inside a 40 px margin.
    p.drawImage(QRectF(96, 112, 168, 168), render(512))

    p.setPen(QColor(t.text))
    p.setFont(QFont("Segoe UI Semibold", 76))
    p.drawText(QRectF(300, 104, 900, 120), Qt.AlignmentFlag.AlignVCenter, DISPLAY_NAME)
    p.setPen(QColor(t.muted))
    p.setFont(QFont("Segoe UI", 27))
    p.drawText(QRectF(304, 214, 900, 60), Qt.AlignmentFlag.AlignVCenter,
               "Offline read-aloud for Windows")

    # A few lines of text with one sentence highlighted, as in the reader window.
    body = QFont("Segoe UI", 25)
    p.setFont(body)
    lines = [
        ("Select text in any app and press a hotkey. ", False),
        ("A natural voice reads it, and the sentence being", True),
        ("read is highlighted.", True),
        (" Nothing leaves your computer.", False),
    ]
    fm = p.fontMetrics()
    x0, y, lh = 100, 360, 58
    x = x0
    for text, hl in lines:
        w = fm.horizontalAdvance(text)
        if x + w > W - 100:
            x, y = x0, y + lh
        if hl:
            p.fillRect(QRectF(x - 4, y - fm.ascent() - 8, w + 8, fm.height() + 16), QColor(t.highlight))
        p.setPen(QColor(t.text))
        p.drawText(int(x), int(y), text)
        x += w
        if text.endswith("being"):
            x, y = x0, y + lh

    p.setPen(QColor(t.accent))
    p.setFont(QFont("Segoe UI Semibold", 21))
    p.drawText(QRectF(100, H - 112, W - 200, 50), Qt.AlignmentFlag.AlignVCenter,
               "41 voices  ·  free and open source  ·  no account, no cloud")
    p.end()
    OUT.parent.mkdir(exist_ok=True)
    img.save(str(OUT))
    render(192).save(str(ICON))  # shown at 96 px: sharp on high-DPI screens
    for f in (OUT, ICON):
        print(f"{f}: {f.stat().st_size / 1e3:.0f} kB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
