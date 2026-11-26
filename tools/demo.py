"""Record the README demo: select text in a browser, press the hotkey, watch myTTS read it.

    .venv\\Scripts\\python tools\\demo.py --ffmpeg C:\\path\\to\\ffmpeg.exe

Takes over the main monitor for about a minute: keep your hands off the mouse
and keyboard. It opens a Microsoft Edge app window with a sample page (a fresh
profile in a temporary folder, so no tabs, bookmarks or account show), starts a
copy of myTTS with default settings (hotkey Ctrl+Alt+Space; settings in a
temporary folder), drags across two paragraphs, presses the hotkey, then clicks
a later sentence in the reader to jump there and pauses with the hotkey.

The screen area is recorded at 15 fps with the mouse pointer drawn in. The audio
track is exactly what the player produced: the player's output goes to a
recorder that pulls it in real time instead of to the speakers, so nothing is
heard. Writes `docs/demo.gif` (for the README) and `docs/demo.mp4` (with sound),
and keeps the lossless capture in `build/demo/`.

Needs the voice model, Edge, and ffmpeg (`--ffmpeg`, the MYTTS_FFMPEG variable,
or ffmpeg on PATH; `pip install imageio-ffmpeg` in any Python provides one).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np  # noqa: E402
from PySide6.QtCore import QEventLoop, QPoint, QRect, QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from mytts import models  # noqa: E402
from mytts.engine import SAMPLE_RATE  # noqa: E402
from mytts.player import Player  # noqa: E402
from mytts.settings import Settings  # noqa: E402
from mytts.ui import native  # noqa: E402
from mytts.ui import theme as themes  # noqa: E402
from mytts.ui.app import App  # noqa: E402
from mytts.ui.icon import app_icon  # noqa: E402
from screengrab import Grabber  # noqa: E402

OUT = ROOT / "docs"
WORK = ROOT / "build" / "demo"
FPS = 15
REGION = QRect(40, 40, 1280, 720)  # logical pixels on the main monitor; 16:9
EDGE = QRect(28, 28, 700, 664)  # inside REGION
READER = QRect(476, 76, 780, 580)  # inside REGION; the client area (the title bar goes above)
GIF_WIDTH = 1024
EDGE_EXE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
PAGE_TITLE = "Morning on the harbour"

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Short stories</title>
<style>
  html { background: #fbfaf7; }
  body { margin: 0; font: 17px/1.65 "Segoe UI", sans-serif; color: #26231f; }
  header { padding: 16px 40px; border-bottom: 1px solid #e7e2d8; font-size: 12px; font-weight: 600;
           letter-spacing: .08em; text-transform: uppercase; color: #8a7a5c; }
  main { padding: 4px 40px 40px; }
  h1 { font: 600 28px/1.25 Georgia, serif; margin: 26px 0 18px; }
  p { margin: 0 0 16px; }
  .by { color: #8a8378; font-size: 14px; margin: -8px 0 22px; }
</style></head>
<body>
<header>Short stories</header>
<main>
<h1>Morning on the harbour</h1>
<p class="by">A short story &middot; 2 min read</p>
<p id="a">The fog had not yet lifted when the first boats slipped out of the harbour. Gulls followed them in lazy circles, calling to each other over the low hum of the engines. On the quay, an old man unfolded his chair in the same spot he had chosen for forty years.</p>
<p id="b">He did not fish, and he did not read. He simply watched the water change colour as the sun climbed: grey, then silver, then a blue so clear it almost seemed to ring. By nine o'clock the caf&eacute; behind him was full of voices and the smell of fresh bread.</p>
<p>Visitors sometimes asked him what he was waiting for. He would smile and point at the horizon, where the last of the fog was folding itself away like a letter.</p>
</main>
<script>
  // Report where the selection starts and ends through the window title, which the recorder reads.
  function report() {
    const a = document.getElementById("a").firstChild, b = document.getElementById("b").firstChild;
    const r = document.createRange();
    r.setStart(a, 0); r.setEnd(a, 1); const s = r.getClientRects()[0];
    r.setStart(b, b.length - 1); r.setEnd(b, b.length); const e = r.getClientRects()[0];
    document.title = "demo:" + JSON.stringify({sx: s.left, sy: s.top + s.height / 2, ex: e.right,
      ey: e.top + e.height / 2, dpr: devicePixelRatio, w: innerWidth, h: innerHeight});
    clearTimeout(window.t);
    window.t = setTimeout(() => document.title = "%s", 1500);
  }
  addEventListener("load", report);
  addEventListener("resize", report);
</script>
</body></html>
""" % PAGE_TITLE

user32 = ctypes.windll.user32

# ------------------------------------------------------------------ input


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x1, 0x2, 0x4
MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x8000, 0x4000
KEYEVENTF_KEYUP = 0x2
VK_CONTROL, VK_MENU, VK_SPACE = 0x11, 0x12, 0x20


def send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def mouse(flags: int, x: int = 0, y: int = 0) -> INPUT:
    i = INPUT(type=0)
    if flags & MOUSEEVENTF_MOVE:  # absolute, over the whole virtual desktop, in physical pixels
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        x = round((x - vx) * 65535 / (vw - 1))
        y = round((y - vy) * 65535 / (vh - 1))
        flags |= MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    i.u.mi = MOUSEINPUT(x, y, 0, flags, 0, 0)
    return i


def key(vk: int, up: bool = False) -> INPUT:
    i = INPUT(type=1)
    i.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    return i


def cursor_pos() -> tuple[int, int]:
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def glide(x: int, y: int, ms: int, button: bool = False) -> None:
    """Move the pointer smoothly (ease in and out) to physical (x, y)."""
    x0, y0 = cursor_pos()
    steps = max(1, ms // 12)
    for k in range(1, steps + 1):
        t = k / steps
        e = t * t * (3 - 2 * t)
        send(mouse(MOUSEEVENTF_MOVE, round(x0 + (x - x0) * e), round(y0 + (y - y0) * e)))
        wait(12)


def wait(ms: int) -> None:
    # Not QTest.qWait: it keeps the GIL while it sleeps, which starves the synthesis thread.
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(predicate, timeout_ms: int, what: str) -> None:
    for _ in range(timeout_ms // 20):
        if predicate():
            return
        wait(20)
    raise TimeoutError(f"timed out waiting for {what}")

# ------------------------------------------------------------------ windows


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_window(pid_hint, predicate) -> int:
    found = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and predicate(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else 0


def child_rect(hwnd: int, cls: str) -> wintypes.RECT | None:
    found = []

    def cb(child, _):
        if class_name(child) == cls and user32.IsWindowVisible(child):
            found.append(child)
        return True

    user32.EnumChildWindows(hwnd, EnumWindowsProc(cb), 0)
    if not found:
        return None
    r = wintypes.RECT()
    user32.GetWindowRect(found[0], ctypes.byref(r))
    return r


SWP_NOZORDER, SWP_NOACTIVATE = 0x4, 0x10

# ------------------------------------------------------------------ audio


class Tape:
    """Pulls audio from the player's callback in real time, like a sound card would, and
    keeps it at the position matching the wall clock, so it lines up with the video."""

    def __init__(self, seconds: int = 180):
        self.samples = np.zeros(SAMPLE_RATE * seconds, np.float32)
        self.streams: list[TapeStream] = []
        self.t0: float | None = None
        self.pos = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="demo-tape", daemon=True)

    def start(self, t0: float) -> None:
        self.t0 = t0
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        block = np.zeros((480, 1), np.float32)
        while not self._stop.is_set():
            target = min(int((time.perf_counter() - self.t0) * SAMPLE_RATE), len(self.samples))
            while self.pos < target:
                n = min(480, target - self.pos)
                out = block[:n]
                mixed = np.zeros(n, np.float32)
                for s in list(self.streams):
                    if s.active:
                        out[:] = 0
                        s.pull(out)
                        mixed += out[:, 0]
                self.samples[self.pos:self.pos + n] = mixed
                self.pos += n
            time.sleep(0.005)

    def factory(self, callback):
        s = TapeStream(callback)
        self.streams.append(s)
        return s, SAMPLE_RATE


class TapeStream:
    def __init__(self, callback):
        self.callback = callback
        self.active = False

    def pull(self, out: np.ndarray) -> None:
        try:
            self.callback(out, len(out), None, None)
        except BaseException:  # CallbackStop: the player went idle; the block is still valid
            self.active = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    abort = close = stop

# ------------------------------------------------------------------ video


class Recorder:
    """Grabs the region on a timer and pipes the frames to ffmpeg (lossless), duplicating
    a frame whenever a tick came late, so the video keeps wall-clock time."""

    def __init__(self, ffmpeg: str, rect: tuple[int, int, int, int], out: Path):
        self.grabber = Grabber(*rect)
        w, h = rect[2], rect[3]
        self.proc = subprocess.Popen(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr0",
             "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-c:v", "libx264rgb", "-crf", "0",
             "-preset", "ultrafast", str(out)],
            stdin=subprocess.PIPE)
        self.frames: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
        self.writer = threading.Thread(target=self._write, name="demo-writer", daemon=True)
        self.timer = QTimer(interval=1000 // FPS / 2)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.count = 0
        self.t0 = 0.0
        self._last: bytes | None = None

    def start(self) -> float:
        self.writer.start()
        self.t0 = time.perf_counter()
        self._tick()
        self.timer.start()
        return self.t0

    def _tick(self) -> None:
        due = int((time.perf_counter() - self.t0) * FPS) + 1
        if due <= self.count:
            return
        frame = self.grabber.raw(cursor=True)
        while self.count < due - 1 and self._last is not None:  # a late tick: repeat the previous frame
            self.frames.put(self._last)
            self.count += 1
        self.frames.put(frame)
        self._last = frame
        self.count += 1

    def _write(self) -> None:
        while (frame := self.frames.get()) is not None:
            self.proc.stdin.write(frame)

    def stop(self) -> float:
        self.timer.stop()
        seconds = self.count / FPS
        self.frames.put(None)
        self.writer.join()
        self.proc.stdin.close()
        self.proc.wait()
        self.grabber.close()
        return seconds

# ------------------------------------------------------------------ overlays


class Backdrop(QWidget):
    """A calm background behind the recorded windows, so no other app shows."""

    def __init__(self, rect: QRect):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setGeometry(rect)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor("#4a4f58"))
        g.setColorAt(1, QColor("#2b2e34"))
        p.fillRect(self.rect(), g)


class Keys(QWidget):
    """Shows the keys being pressed, as key caps, at the bottom of the recorded area."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.keys: list[str] = []
        self.font_ = QFont("Segoe UI", 15, QFont.Weight.DemiBold)

    def show_keys(self, keys: list[str], center: QPoint) -> None:
        self.keys = keys
        widths = [max(56, 22 + 11 * len(k)) for k in keys]
        w = sum(widths) + 34 * (len(keys) - 1) + 40
        h = 76
        self.setGeometry(center.x() - w // 2, center.y() - h // 2, w, h)
        self.widths = widths
        self.show()
        themes.set_topmost(int(self.winId()), True)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 22, 215))
        p.drawRoundedRect(QRectF(self.rect()), 14, 14)
        p.setFont(self.font_)
        x = 20
        for i, (k, w) in enumerate(zip(self.keys, self.widths)):
            cap = QRectF(x, 16, w, 44)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#d9a55b"))
            p.drawRoundedRect(cap.adjusted(0, 3, 0, 3), 8, 8)
            p.setBrush(QColor("#f2d3a2"))
            p.drawRoundedRect(cap, 8, 8)
            p.setPen(QPen(QColor("#1c1b19")))
            p.drawText(cap, Qt.AlignmentFlag.AlignCenter, k)
            x += w
            if i < len(self.keys) - 1:
                p.setPen(QPen(QColor("#e8e4dc")))
                p.drawText(QRectF(x, 16, 34, 44), Qt.AlignmentFlag.AlignCenter, "+")
                x += 34

# ------------------------------------------------------------------ main


def find_ffmpeg(arg: str | None) -> str:
    exe = arg or os.environ.get("MYTTS_FFMPEG") or shutil.which("ffmpeg")
    if not exe or not Path(exe).exists():
        sys.exit("ffmpeg not found: pass --ffmpeg, set MYTTS_FFMPEG, or put ffmpeg on PATH.")
    return exe


def encode(ffmpeg: str, video: Path, audio: Path, seconds: float) -> None:
    gif, mp4 = OUT / "demo.gif", OUT / "demo.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(audio),
                    "-t", f"{seconds:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-preset", "slow", "-tune", "stillimage", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(mp4)], check=True)
    palette = (f"fps=12,scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];"
               "[a]palettegen=stats_mode=diff:max_colors=192[p];"
               "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vf", palette,
                    "-loop", "0", str(gif)], check=True)
    for f in (gif, mp4):
        print(f"{f}: {f.stat().st_size / 1e6:.1f} MB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ffmpeg", help="path to ffmpeg.exe")
    ap.add_argument("--encode-only", action="store_true", help="re-encode the last capture in build/demo")
    args = ap.parse_args()
    ffmpeg = find_ffmpeg(args.ffmpeg)
    WORK.mkdir(parents=True, exist_ok=True)
    video, audio, meta = WORK / "capture.mkv", WORK / "audio.wav", WORK / "capture.json"
    if args.encode_only:
        encode(ffmpeg, video, audio, json.loads(meta.read_text())["seconds"])
        return 0
    if models.missing():
        sys.exit("The voice model is missing: run `python -m mytts download` first.")
    if not EDGE_EXE.exists():
        sys.exit(f"Microsoft Edge not found at {EDGE_EXE}")

    native.set_app_id()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("mytts")
    app.setStyle("Fusion")
    app.setFont(themes.ui_font())
    app.setWindowIcon(app_icon())
    screen = app.primaryScreen()
    dpr = screen.devicePixelRatio()
    if screen.geometry().topLeft() != QPoint(0, 0):
        sys.exit("The main monitor must be at the top left of the desktop.")

    def phys(x: float, y: float) -> tuple[int, int]:
        return round(x * dpr), round(y * dpr)

    region = REGION
    rx, ry = phys(region.x(), region.y())
    rw, rh = phys(region.width(), region.height())
    rw, rh = rw // 2 * 2, rh // 2 * 2  # even sizes for H.264

    tmp = Path(tempfile.mkdtemp(prefix="mytts-demo-"))
    edge = None
    controller = None
    hwnd = 0
    try:
        backdrop = Backdrop(region)
        backdrop.show()
        native.bring_to_front(int(backdrop.winId()))
        wait(300)

        # The browser: an app window (no tabs or address bar) with a throwaway profile.
        page = tmp / "story.html"
        page.write_text(PAGE, encoding="utf-8")
        edge = subprocess.Popen([str(EDGE_EXE), f"--user-data-dir={tmp / 'edge'}", "--no-first-run",
                                 "--no-default-browser-check", "--disable-sync", "--disable-extensions",
                                 "--disable-features=msEdgeSidebar,EdgeShoppingAssistant",
                                 f"--app={page.as_uri()}"])
        hwnd = 0

        def edge_window() -> bool:
            nonlocal hwnd
            hwnd = find_window(None, lambda h: class_name(h) == "Chrome_WidgetWin_1"
                               and (window_text(h).startswith("demo:") or window_text(h).startswith(PAGE_TITLE)))
            return bool(hwnd)

        wait_until(edge_window, 20_000, "the Edge window")
        ex, ey = phys(region.x() + EDGE.x(), region.y() + EDGE.y())
        ew, eh = phys(EDGE.width(), EDGE.height())
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, None, ex, ey, ew, eh, SWP_NOZORDER | SWP_NOACTIVATE)

        info: dict = {}

        def layout_reported() -> bool:
            t = window_text(hwnd)
            if t.startswith("demo:"):
                d = json.loads(t[5:])
                vp = child_rect(hwnd, "Chrome_RenderWidgetHostHWND")
                if vp and abs(d["w"] * d["dpr"] - (vp.right - vp.left)) <= 2:
                    info.update(d, vx=vp.left, vy=vp.top)
                    return True
            return False

        wait_until(layout_reported, 10_000, "the page layout")
        wait_until(lambda: window_text(hwnd) == PAGE_TITLE, 5_000, "the page title")
        sel_start = (round(info["vx"] + (info["sx"] + 1) * info["dpr"]), round(info["vy"] + info["sy"] * info["dpr"]))
        sel_end = (round(info["vx"] + (info["ex"] + 2) * info["dpr"]), round(info["vy"] + info["ey"] * info["dpr"]))

        # myTTS, as a fresh install would run it, with the audio going to the tape.
        tape = Tape()
        player = Player(stream_factory=tape.factory)
        settings = Settings(font_size=14.0)
        controller = App(settings, tmp / "settings.json", player=player, use_tray=True, use_hotkey=True)
        errors: list[str] = []
        controller.hotkey.status.connect(lambda name, hk, err: err and errors.append(f"{hk}: {err}"))
        window = controller.window
        window.setGeometry(READER.translated(region.topLeft()))
        controller.start(show=False)
        wait_until(lambda: bool(player.voices), 20_000, "the voices")
        wait(500)
        if errors:
            sys.exit("The hotkey could not be registered: " + "; ".join(errors))
        current = [-1]
        player.segment_started.connect(lambda i: current.__setitem__(0, i))

        keys = Keys()
        key_center = QPoint(region.x() + EDGE.x() + 230, region.bottom() - 70)  # under the page, clear of the reader
        user32.SetForegroundWindow(hwnd)
        send(mouse(MOUSEEVENTF_MOVE, *phys(region.x() + 1040, region.y() + 620)))
        wait(400)

        rec = Recorder(ffmpeg, (rx, ry, rw, rh), video)
        t0 = rec.start()
        tape.start(t0)

        wait(900)
        glide(sel_start[0] - 6, sel_start[1], 700)
        glide(*sel_start, 120)
        send(mouse(MOUSEEVENTF_LEFTDOWN))
        wait(120)
        glide(*sel_end, 1500)
        wait(100)
        send(mouse(MOUSEEVENTF_LEFTUP))
        wait(700)

        keys.show_keys(["Ctrl", "Alt", "Space"], key_center)
        wait(450)
        send(key(VK_CONTROL), key(VK_MENU))
        wait(60)
        send(key(VK_SPACE))
        wait(90)
        send(key(VK_SPACE, up=True), key(VK_MENU, up=True), key(VK_CONTROL, up=True))
        wait(1300)
        keys.hide()

        wait_until(lambda: current[0] >= 0, 15_000, "speech to start")
        glide(*phys(region.x() + 330, region.y() + 640), 800)  # out of the way, over the page
        wait_until(lambda: current[0] >= 1, 30_000, "the second sentence")
        wait(2600)

        # Click a later sentence in the reader: reading jumps there.
        view = window.view
        c = QTextCursor(view.document())
        c.setPosition(view._starts[4] + 12)
        g = view.viewport().mapToGlobal(view.cursorRect(c).center())
        glide(*phys(g.x(), g.y()), 900)
        wait(250)
        send(mouse(MOUSEEVENTF_LEFTDOWN))
        wait(70)
        send(mouse(MOUSEEVENTF_LEFTUP))
        wait(300)
        glide(*phys(g.x() + 60, g.y() + 150), 600)
        wait_until(lambda: current[0] >= 5, 30_000, "the sentence after the jump")

        # Pause with the same hotkey.
        keys.show_keys(["Ctrl", "Alt", "Space"], key_center)
        send(key(VK_CONTROL), key(VK_MENU), key(VK_SPACE))
        wait(60)
        send(key(VK_SPACE, up=True), key(VK_MENU, up=True), key(VK_CONTROL, up=True))
        wait(1300)
        keys.hide()
        wait(900)

        seconds = rec.stop()
        tape.stop()
        n = int(seconds * SAMPLE_RATE)
        pcm = (np.clip(tape.samples[:n], -1, 1) * 32767).astype("<i2")
        with wave.open(str(audio), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        meta.write_text(json.dumps({"seconds": seconds, "fps": FPS, "size": [rw, rh]}))
        print(f"captured {seconds:.1f} s, {rec.count} frames; peak audio {np.abs(tape.samples[:n]).max():.2f}")
    finally:
        if controller is not None:
            controller.shutdown()
        if hwnd:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        if edge is not None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(edge.pid)], capture_output=True)
        app.processEvents()
        time.sleep(1)
        shutil.rmtree(tmp, ignore_errors=True)

    encode(ffmpeg, video, audio, seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
