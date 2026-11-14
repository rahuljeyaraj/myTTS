import struct

from PySide6.QtGui import QImage, QImageReader

from mytts.ui.icon import SIZES, ico_bytes, render, save_ico

ARGB32 = QImage.Format.Format_ARGB32


def directory(data: bytes) -> list[tuple]:
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind) == (0, 1)  # 1 = icon
    return [struct.unpack_from("<BBBBHHII", data, 6 + 16 * i) for i in range(count)]


def test_ico_layout():
    data = ico_bytes()
    entries = directory(data)
    assert [w or 256 for w, *_ in entries] == list(SIZES)
    offset = 6 + 16 * len(entries)
    for w, h, colors, _reserved, planes, bpp, size, start in entries:
        assert (w, colors, planes, bpp) == (h, 0, 1, 32)
        assert start == offset  # images follow the directory back to back
        offset += size
        blob = data[start : start + size]
        if w == 0:  # 256 px: PNG
            assert blob.startswith(b"\x89PNG\r\n\x1a\n")
        else:  # BMP: header with double height (pixels + mask), then BGRA rows, then the 1-bit mask
            assert struct.unpack_from("<IiiHH", blob) == (40, w, 2 * w, 1, 32)
            assert size == 40 + 4 * w * w + ((w + 31) // 32) * 4 * w
    assert offset == len(data)


def test_bmp_mask_marks_transparent_pixels():
    data = ico_bytes((16,))
    (_w, _h, _c, _r, _p, _b, size, start), = directory(data)
    mask = data[start + 40 + 4 * 16 * 16 : start + size]
    img = render(16).convertToFormat(ARGB32)
    for y in range(16):
        row = mask[(15 - y) * 4 : (15 - y) * 4 + 4]  # rows are stored bottom-up, 4 bytes each
        for x in range(16):
            transparent = bool(row[x // 8] & (0x80 >> (x % 8)))
            assert transparent == (img.pixel(x, y) >> 24 == 0)


def test_saved_icon_reads_back_unchanged(qapp, tmp_path):
    path = tmp_path / "sub" / "mytts.ico"
    save_ico(path)
    assert [p.name for p in path.parent.iterdir()] == ["mytts.ico"]  # no temporary file left
    reader = QImageReader(str(path), b"ico")
    assert reader.imageCount() == len(SIZES)
    for i in range(reader.imageCount()):
        assert reader.jumpToImage(i)
        img = reader.read().convertToFormat(ARGB32)
        assert img == render(img.width()).convertToFormat(ARGB32)
