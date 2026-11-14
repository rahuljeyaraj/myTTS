"""The running app: reader window, tray icon, global hotkey, settings and single instance.

`python -m mytts` starts it (`--tray` starts it hidden in the tray). A second
launch hands its request to the running copy and exits.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

from .. import __version__, autostart, models
from ..capture import capture_selection
from ..hotkey import GlobalHotkey
from ..player import Player, State
from ..settings import Settings
from . import native
from . import theme as themes
from .icon import app_icon
from .instance import SingleInstance, send
from .reader import ReaderWindow
from .settings_dialog import SettingsDialog
from .tray import Tray

SAVE_DELAY_MS = 600
TRAY_FOCUS_SETTLE_S = 0.15  # after the tray menu gives the focus back to the previous app
PROGRESS_INTERVAL_S = 0.1


class App(QObject):
    """Owns the parts of the app and the flows between them."""

    _captured = Signal(object)  # str | None, from the capture thread
    _download_progress = Signal(object, object)  # bytes done, bytes total
    _download_done = Signal(object)  # None, "cancelled" or an error message

    def __init__(
        self,
        settings: Settings,
        settings_file: Path | None = None,
        *,
        player: Player | None = None,
        use_tray: bool | None = None,
        use_hotkey: bool = True,
        capture: Callable[..., str | None] = capture_selection,
        missing: Callable[[], list] = models.missing,
        ensure: Callable = models.ensure_all,
    ):
        super().__init__()
        self.settings = settings
        self._settings_file = settings_file
        self._capture = capture
        self._missing = missing
        self._ensure = ensure
        self._capturing = False
        self._cancel_download: threading.Event | None = None
        self._quitting = False

        self.player = player or Player(voice=settings.voice, speed=settings.speed)
        self.window = ReaderWindow(self.player, theme=settings.theme, font_size=settings.font_size)
        self.window.setWindowIcon(app_icon())
        if settings.geometry:
            self.window.restoreGeometry(QByteArray.fromBase64(settings.geometry.encode("ascii")))
        if settings.always_on_top:
            self.window.set_always_on_top(True)

        if use_tray is None:
            use_tray = Tray.available()
        self.tray = Tray(self) if use_tray else None
        self.window.hide_on_close = self.tray is not None
        self.hotkey = GlobalHotkey(self) if use_hotkey else None
        self.dialog: SettingsDialog | None = None

        self._save_timer = QTimer(self, singleShot=True, interval=SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_settings)

        w = self.window
        w.preferences_changed.connect(self._preferences_changed)
        w.settings_requested.connect(self.show_settings)
        w.closed_to_tray.connect(self._closed_to_tray)
        w.notice.start_requested.connect(self.start_download)
        w.notice.cancel_requested.connect(self.cancel_download)
        self.player.state_changed.connect(self._update_tray)
        self._captured.connect(self._on_captured, Qt.ConnectionType.QueuedConnection)
        self._download_progress.connect(w.show_download_progress, Qt.ConnectionType.QueuedConnection)
        self._download_done.connect(self._on_download_done, Qt.ConnectionType.QueuedConnection)
        if self.hotkey is not None:
            self.hotkey.activated.connect(self.read_selection)
            self.hotkey.status.connect(self._hotkey_status)
        if self.tray is not None:
            t = self.tray
            t.show_requested.connect(self.show_window)
            t.toggle_requested.connect(self.window.toggle_play)
            t.read_action.triggered.connect(lambda: self.read_selection(from_tray=True))
            t.stop_action.triggered.connect(self.player.stop)
            t.settings_action.triggered.connect(self.show_settings)
            t.quit_action.triggered.connect(self.quit)
            t.apply_theme(themes.THEMES.get(self.window.theme, themes.DARK))
            t.set_hotkey(settings.hotkey, None)

    # ------------------------------------------------------------ lifecycle

    def start(self, show: bool = True, text: str | None = None) -> None:
        if self.hotkey is not None:
            self.hotkey.start(self.settings.hotkey)
        if self.tray is not None:
            self.tray.show()
        todo = self._missing()
        if todo:
            self.window.offer_download(sum(f.size for f in todo))
            show = True  # nothing works until the voices are there
        else:
            self.player.start()
        if show or self.tray is None:
            self.window.show()
            if self.settings.always_on_top:
                self.window.set_always_on_top(True)
        if text:
            QTimer.singleShot(0, lambda: self.window.load_text(text))

    def quit(self) -> None:
        self._quitting = True
        self.window.hide_on_close = False
        QApplication.instance().quit()

    def shutdown(self) -> None:
        """Called once when the event loop ends."""
        self.save_settings()
        if self._cancel_download is not None:
            self._cancel_download.set()
        if self.hotkey is not None:
            self.hotkey.stop()
        if self.tray is not None:
            self.tray.hide()
        self.player.close()

    def handle_message(self, msg: dict) -> None:
        """A request from a second launch."""
        cmd = msg.get("cmd")
        if cmd == "open" and isinstance(msg.get("text"), str):
            self.show_window()
            self.window.load_text(msg["text"])
        elif cmd == "show":
            self.show_window()
        elif cmd == "quit":
            self.quit()

    # ---------------------------------------------------------------- window

    def show_window(self) -> None:
        was_hidden = not self.window.isVisible()
        self.window.bring_to_front()
        if was_hidden and self.settings.always_on_top:
            self.window.set_always_on_top(True)

    def _closed_to_tray(self) -> None:
        self.player.pause()
        self.save_settings()
        if not self.settings.tray_hint_shown and self.tray is not None:
            self.settings.tray_hint_shown = True
            self.tray.notify("mytts is still running",
                             f"Press {self.settings.hotkey} to read selected text, or click the tray icon.")
            self.save_settings()

    def _update_tray(self, state: State | None = None) -> None:
        if self.tray is not None:
            self.tray.update_state(self.player.state, self.window.view.count > 0)

    # ------------------------------------------------------- read selection

    def read_selection(self, from_tray: bool = False) -> None:
        """Copy the selection of the app in front and read it (runs the capture off the GUI thread)."""
        if self._capturing:
            return
        self._capturing = True
        settle = 0.0
        if from_tray and native.enabled():  # the tray menu took the focus; give it back
            target = native.previous_app_window()
            if target and native.bring_to_front(target):
                settle = TRAY_FOCUS_SETTLE_S
        restore = self.settings.restore_clipboard
        threading.Thread(target=self._capture_worker, args=(restore, settle), name="mytts-capture",
                         daemon=True).start()

    def _capture_worker(self, restore: bool, settle: float) -> None:
        if settle:
            time.sleep(settle)
        try:
            text = self._capture(restore=restore)
        except Exception:
            text = None
        self._captured.emit(text)

    def _on_captured(self, text: str | None) -> None:
        self._capturing = False
        self.show_window()
        if text is not None:  # None: nothing was selected, so just show the window
            self.window.load_text(text)
        self._update_tray()

    # ---------------------------------------------------------------- hotkey

    def _hotkey_status(self, hotkey: str, error: str | None) -> None:
        if self.tray is not None:
            self.tray.set_hotkey(hotkey, error)
        if self.dialog is not None:
            self.dialog.set_hotkey_status(hotkey, error)
        if error and (self.dialog is None or not self.dialog.isVisible()):
            if self.tray is not None:
                self.tray.notify("Hotkey not available", f"{error} Choose another one in Settings.")
            else:
                self.window.show_error(error)

    def set_hotkey(self, hotkey: str) -> None:
        self.settings.hotkey = hotkey
        self.save_settings()
        if self.hotkey is not None:
            self.hotkey.set(hotkey)

    def _hotkey_recording(self, recording: bool) -> None:
        """Release the hotkey while the user records a new one, so the keys reach the dialog."""
        if self.hotkey is not None:
            self.hotkey.set(None if recording else self.settings.hotkey)

    # -------------------------------------------------------------- settings

    def show_settings(self) -> None:
        if self.dialog is None:
            d = SettingsDialog(self.settings, autostart.is_enabled(), self.window)
            d.hotkey_changed.connect(self.set_hotkey)
            d.hotkey_recording.connect(self._hotkey_recording)
            d.restore_clipboard_changed.connect(self._set_restore_clipboard)
            d.on_top_changed.connect(self.window.set_always_on_top)
            d.autostart_changed.connect(self._set_autostart)
            self.dialog = d
            if self.hotkey is not None and self.hotkey.hotkey:
                d.set_hotkey_status(self.hotkey.hotkey, self.hotkey.error)
        d = self.dialog
        d.apply_theme(themes.THEMES.get(self.window.theme, themes.DARK))
        d.set_on_top(self.window.always_on_top)
        d.show()
        d.raise_()
        d.activateWindow()
        if native.enabled():
            native.bring_to_front(int(d.winId()))

    def _set_restore_clipboard(self, on: bool) -> None:
        self.settings.restore_clipboard = on
        self.save_settings()

    def _set_autostart(self, on: bool) -> None:
        try:
            autostart.set_enabled(on)
        except OSError as e:
            self.window.show_error(f"Could not change the startup setting: {e}")

    def _preferences_changed(self) -> None:
        w, s = self.window, self.settings
        s.voice, s.speed = self.player.voice, w.speed_value()
        s.theme, s.font_size, s.always_on_top = w.theme, w.font_size, w.always_on_top
        if self.tray is not None:
            self.tray.apply_theme(themes.THEMES.get(w.theme, themes.DARK))
        if self.dialog is not None:
            self.dialog.set_on_top(w.always_on_top)
            if self.dialog.isVisible():
                self.dialog.apply_theme(themes.THEMES.get(w.theme, themes.DARK))
        self._save_timer.start()

    def save_settings(self) -> None:
        self._save_timer.stop()
        self.settings.geometry = bytes(self.window.saveGeometry().toBase64().data()).decode("ascii")
        try:
            self.settings.save(self._settings_file)
        except OSError:
            pass  # read-only profile: keep running with the settings in memory

    # -------------------------------------------------------- model download

    def start_download(self) -> None:
        if self._cancel_download is not None:
            return
        todo = self._missing()
        if not todo:
            self._on_download_done(None)
            return
        total = sum(f.size for f in todo)
        cancel = self._cancel_download = threading.Event()
        self.window.show_download_progress(0, total)
        threading.Thread(target=self._download_worker, args=(cancel, total), name="mytts-download",
                         daemon=True).start()

    def _download_worker(self, cancel: threading.Event, total: int) -> None:
        done_per_file: dict[str, int] = {}
        last = [0.0]

        def progress(f, done, _size):
            done_per_file[f.name] = done
            now = time.monotonic()
            if now - last[0] >= PROGRESS_INTERVAL_S:
                last[0] = now
                self._download_progress.emit(sum(done_per_file.values()), total)

        try:
            self._ensure(progress, cancel)
            result = None
        except models.DownloadCancelled:
            result = "cancelled"
        except Exception as e:
            result = str(e) or e.__class__.__name__
        self._download_done.emit(result)

    def cancel_download(self) -> None:
        if self._cancel_download is not None:
            self._cancel_download.set()

    def _on_download_done(self, result: str | None) -> None:
        self._cancel_download = None
        if self._quitting:
            return
        todo = self._missing()
        if result is None and not todo:
            self.window.model_installed()
            self.player.start()
            return
        error = None if result == "cancelled" else f"Download failed: {result or 'files are missing'}."
        self.window.offer_download(sum(f.size for f in todo), error)


def quit_running() -> int:
    """Ask the running copy to exit (for scripts such as an uninstaller)."""
    from PySide6.QtCore import QCoreApplication

    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    if SingleInstance().acquire():
        print("mytts is not running.")
        return 1
    return 0 if send({"cmd": "quit"}) else 1


def run(text: str | None = None, tray: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("mytts")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")  # renders the stylesheet the same on every Windows version
    app.setFont(themes.ui_font())
    app.setWindowIcon(app_icon())

    instance = SingleInstance()
    if not instance.acquire():
        msg = {"cmd": "open", "text": text} if text else {"cmd": "tray" if tray else "show"}
        if send(msg):
            return 0
        print("mytts is already running but did not respond.", file=sys.stderr)
        return 1

    settings = Settings.load()
    try:
        autostart.refresh()
    except OSError:
        pass
    controller = App(settings)
    app.setQuitOnLastWindowClosed(controller.tray is None)
    instance.message.connect(controller.handle_message)
    app.aboutToQuit.connect(controller.shutdown)
    app.aboutToQuit.connect(instance.release)
    # Windows sign-out: never hold it up by hiding the window instead of closing.
    app.commitDataRequest.connect(lambda _m: setattr(controller.window, "hide_on_close", False))
    controller.start(show=not tray, text=text)
    return app.exec()

