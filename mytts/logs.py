"""The log file and crash reports.

myTTS.exe is a windowed program with no console, so whatever would have been
printed goes to %LOCALAPPDATA%\\mytts\\logs\\mytts.log instead. An unhandled
exception is written there and shown in a short error dialog.
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import sys
import threading
import traceback
from pathlib import Path

from . import DISPLAY_NAME, __version__, paths

LOG_NAME = "mytts.log"
CRASH_NAME = "crash.log"  # native crashes (faulthandler), which logging can't catch
MAX_BYTES = 1_000_000
BACKUPS = 2
FORMAT = "%(asctime)s %(process)d %(threadName)s %(levelname)s %(name)s: %(message)s"

log = logging.getLogger("mytts")
_handler: logging.Handler | None = None
_crash_file = None
_showing = False


def log_file(directory: Path | None = None) -> Path:
    return (directory or paths.logs_dir()) / LOG_NAME


def setup(directory: Path | None = None, level: int = logging.INFO) -> Path:
    """Log to a rotating file and report unhandled exceptions. Safe to call more than once."""
    global _handler, _crash_file
    path = log_file(directory)
    root = logging.getLogger()
    if _handler is None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8", delay=True)
            _handler.setFormatter(logging.Formatter(FORMAT))
            root.addHandler(_handler)
            _crash_file = open(path.with_name(CRASH_NAME), "a", encoding="utf-8")
            faulthandler.enable(_crash_file)
        except OSError:
            pass  # a read-only profile: keep running without a log
    root.setLevel(level)
    # phonemizer warns "words count mismatch" for nearly every sentence; it is harmless.
    logging.getLogger("phonemizer").setLevel(logging.ERROR)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    return path


def shutdown() -> None:
    """Undo `setup` (for tests)."""
    global _handler, _crash_file
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler.close()
        _handler = None
    if _crash_file is not None:
        faulthandler.disable()
        _crash_file.close()
        _crash_file = None
    sys.excepthook = sys.__excepthook__
    threading.excepthook = threading.__excepthook__


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
    if sys.stderr is not None:
        traceback.print_exception(exc_type, exc, tb)
    show_error(exc)


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread else "?"
    log.critical("Unhandled exception in thread %s", name,
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    if sys.stderr is not None:
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)


def error_text(exc: BaseException) -> str:
    detail = str(exc) or exc.__class__.__name__
    return (f"Something went wrong: {detail}\n\n"
            f"Details are in {log_file()}")


def show_error(exc: BaseException) -> None:
    """A short error dialog, on the GUI thread only and one at a time."""
    global _showing
    if _showing or threading.current_thread() is not threading.main_thread():
        return
    _showing = True
    try:
        _dialog(error_text(exc))
    except Exception:
        log.exception("Could not show the error dialog")
    finally:
        _showing = False


def _dialog(text: str) -> None:
    app = None
    if "PySide6.QtWidgets" in sys.modules:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
    if app is not None:
        if app.platformName() != "windows":  # offscreen (tests): a modal dialog would block
            return
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(None, DISPLAY_NAME, text)
    elif sys.platform == "win32" and (paths.frozen() or sys.stderr is None):
        import ctypes

        MB_ICONERROR, MB_SETFOREGROUND = 0x10, 0x10000
        ctypes.windll.user32.MessageBoxW(None, text, DISPLAY_NAME, MB_ICONERROR | MB_SETFOREGROUND)
