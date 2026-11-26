"""The self-contained build: frozen paths, autostart, logging, console output, --self-test, About."""

import logging
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

from mytts import DISPLAY_NAME, __version__, autostart, logs, paths
from mytts import __main__ as cli

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    """Pretend to be myTTS.exe in tmp_path."""
    exe = tmp_path / "myTTS.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    return exe


def test_frozen_paths_and_autostart(frozen, tmp_path):
    assert paths.frozen()
    assert autostart.command() == f'"{frozen.resolve()}" --tray'
    assert paths.download_command() == "myTTS.exe download"
    assert paths.licenses_dir() is None
    (tmp_path / "licenses").mkdir()
    assert paths.licenses_dir() == tmp_path / "licenses"
    assert not paths.installed_by_setup() and not autostart.is_install()  # a dev build
    (tmp_path / "unins000.exe").write_bytes(b"")
    assert paths.installed_by_setup() and autostart.is_install()


def test_source_paths():
    assert not paths.frozen()
    assert "-m mytts" in paths.download_command()
    assert paths.licenses_dir() is None
    assert "myTTS.exe" not in autostart.command()


@pytest.fixture
def logged(tmp_path, monkeypatch):
    dialogs = []
    monkeypatch.setattr(logs, "_dialog", dialogs.append)
    path = logs.setup(tmp_path)
    yield path, dialogs
    logs.shutdown()


def _read(path: Path) -> str:
    for h in logging.getLogger().handlers:
        h.flush()
    return path.read_text(encoding="utf-8")


def test_log_file_and_unhandled_exception(logged, capsys):
    path, dialogs = logged
    logging.getLogger("mytts.test").info("hello log")
    try:
        raise ValueError("boom")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    text = _read(path)
    assert "hello log" in text
    assert "Unhandled exception" in text and "ValueError: boom" in text
    assert len(dialogs) == 1 and "boom" in dialogs[0] and str(logs.log_file()) in dialogs[0]
    assert "ValueError: boom" in capsys.readouterr().err  # still printed when there is a console
    assert path.with_name(logs.CRASH_NAME).exists()


def test_thread_exception_is_logged_without_dialog(logged):
    path, dialogs = logged

    def fail():
        raise RuntimeError("worker failed")

    t = threading.Thread(target=fail, name="worker")
    t.start()
    t.join()
    text = _read(path)
    assert "Unhandled exception in thread worker" in text and "RuntimeError: worker failed" in text
    assert dialogs == []


def test_setup_twice_adds_one_handler(logged, tmp_path):
    before = len(logging.getLogger().handlers)
    logs.setup(tmp_path)
    assert len(logging.getLogger().handlers) == before
    assert logging.getLogger("phonemizer").level == logging.ERROR


def test_shutdown_restores_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "_dialog", lambda _t: None)
    logs.setup(tmp_path)
    logs.shutdown()
    assert sys.excepthook is sys.__excepthook__
    assert threading.excepthook is threading.__excepthook__


def test_error_dialog_skipped_offscreen(qapp):
    logs._dialog("not shown under the offscreen platform")  # would block if it were modal


@pytest.mark.parametrize("argv", [[], ["--tray"], ["open", "text"], ["--version"]])
def test_console_streams_never_leave_none(monkeypatch, argv):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    cli._console_streams(argv)
    assert sys.stdout is not None and sys.stderr is not None
    print("nowhere")  # must not raise


def test_console_streams_keep_real_streams(capsys):
    out, err = sys.stdout, sys.stderr
    cli._console_streams(["--version"])
    assert (sys.stdout, sys.stderr) == (out, err)


class _FakeEngine:
    voices = ["a", "b"]

    def __init__(self, audio):
        self._audio = audio

    def synthesize(self, _text):
        return self._audio


@pytest.mark.parametrize("ok", [True, False])
def test_self_test(qapp, monkeypatch, capsys, ok):
    import mytts.engine

    t = np.arange(24_000, dtype=np.float32) / 24_000
    audio = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32) if ok else np.zeros(24_000, np.float32)
    monkeypatch.setattr(mytts.engine, "Engine", lambda: _FakeEngine(audio))
    assert cli._cmd_self_test(None) == (0 if ok else 1)
    out = capsys.readouterr()
    assert f"{DISPLAY_NAME} {__version__}" in out.out
    assert ("Self-test passed" in out.out) == ok
    assert ("FAILED" in out.err) == (not ok)


def test_about_section(qapp):
    from mytts.settings import Settings
    from mytts.ui import theme
    from mytts.ui.settings_dialog import SettingsDialog

    d = SettingsDialog(Settings(), False)
    try:
        assert d.windowTitle() == f"{DISPLAY_NAME} settings"
        assert d.about_title.text() == f"{DISPLAY_NAME} {__version__}"
        d.apply_theme(theme.SEPIA)
        html = d.about_links.text()
        for needle in ("Project page", "MIT license", "Third-party licenses", "Log files",
                       "https://github.com/rahuljeyaraj/myTTS", theme.SEPIA.accent):
            assert needle in html
        assert d.about_links.openExternalLinks()
    finally:
        d.deleteLater()


def test_spec_and_launcher_exist():
    spec = (ROOT / "packaging" / "mytts.spec").read_text(encoding="utf-8")
    assert "console=False" in spec and "launcher.py" in spec
    compile(spec, "mytts.spec", "exec")
    assert "from mytts.__main__ import main" in (ROOT / "packaging" / "launcher.py").read_text(encoding="utf-8")
