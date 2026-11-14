import threading

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import wait_until
from mytts import autostart, models
from mytts.engine import SAMPLE_RATE, Voice
from mytts.player import Player, State
from mytts.settings import Settings
from mytts.ui.app import App
from mytts.ui.settings_dialog import HotkeyEdit, RECORD_PROMPT

TEXT = "First sentence. Second sentence."


class FakeEngine:
    voices = [
        Voice("af_heart", "Heart", "en-us", "English (US)", "female"),
        Voice("bf_emma", "Emma", "en-gb", "English (UK)", "female"),
    ]

    def synthesize(self, text, voice_id="af_heart", speed=1.0):
        return np.full(2400, 0.1, dtype=np.float32)


class FakeStream:
    def start(self):
        pass

    def abort(self):
        pass

    def close(self):
        pass


class FakeFile:
    def __init__(self, name, size):
        self.name, self.size = name, size


def make_app(tmp_path, settings=None, capture=lambda restore: TEXT, missing=lambda: [], ensure=None, voice="af_heart"):
    settings = settings or Settings()
    player = Player(voice=settings.voice or voice, speed=settings.speed, engine_factory=FakeEngine,
                    stream_factory=lambda cb: (FakeStream(), SAMPLE_RATE))
    app = App(settings, tmp_path / "settings.json", player=player, use_tray=True, use_hotkey=False,
              capture=capture, missing=missing, ensure=ensure or (lambda progress, cancel: None))
    return app


@pytest.fixture
def made(qapp, tmp_path):
    apps = []

    def make(**kw):
        a = make_app(tmp_path, **kw)
        apps.append(a)
        return a

    yield make
    for a in apps:
        a.window.hide_on_close = False
        a.shutdown()
        a.window.close()
        if a.dialog is not None:
            a.dialog.close()


def test_hotkey_reads_the_selection(made):
    seen = []
    app = made(capture=lambda restore: seen.append(restore) or TEXT)
    app.start(show=False)
    assert not app.window.isVisible()
    app.read_selection()
    assert wait_until(lambda: not app._capturing)
    assert seen == [True]  # restore_clipboard is on by default
    assert app.window.isVisible()
    assert app.window.view.count == 2
    assert app.player.state in (State.LOADING, State.PLAYING)


def test_nothing_selected_just_shows_the_window(made):
    app = made(capture=lambda restore: None)
    app.start(show=False)
    app.read_selection()
    assert wait_until(lambda: not app._capturing)
    assert app.window.isVisible() and app.window.view.count == 0


def test_capture_runs_once_at_a_time(made):
    gate = threading.Event()
    calls = []

    def slow(restore):
        calls.append(1)
        gate.wait(2)
        return TEXT

    app = made(capture=slow)
    app.start(show=False)
    app.read_selection()
    app.read_selection()  # ignored while the first capture runs
    gate.set()
    assert wait_until(lambda: not app._capturing)
    assert calls == [1]


def test_close_hides_to_tray_and_pauses(made, tmp_path):
    app = made()
    app.start()
    app.window.load_text(TEXT)
    app.player._core._drain_jobs()
    app.player.play(0)
    assert wait_until(lambda: app.player.state == State.PLAYING)
    app.window.close()
    assert not app.window.isVisible()
    assert app.player.state == State.PAUSED
    assert app.settings.tray_hint_shown
    assert Settings.load(tmp_path / "settings.json").tray_hint_shown


def test_tray_menu_follows_playback(made):
    app = made()
    app.start()
    t = app.tray
    assert t.play_action.text() == "Play" and not t.play_action.isEnabled()
    assert not t.stop_action.isEnabled()
    app.window.load_text(TEXT)
    app.player._core._drain_jobs()
    assert wait_until(lambda: t.play_action.text() == "Pause")
    assert t.stop_action.isEnabled()
    app.player.pause()
    assert wait_until(lambda: t.play_action.text() == "Resume")
    t.stop_action.trigger()
    assert wait_until(lambda: t.play_action.text() == "Play")
    assert t.play_action.isEnabled() and not t.stop_action.isEnabled()


def test_preferences_are_saved(made, tmp_path):
    app = made()
    app.start()
    app.window.cycle_theme()
    app.window.set_font_size(17)
    app.window.set_always_on_top(True)
    assert app._save_timer.isActive()
    app._save_timer.timeout.emit()
    saved = Settings.load(tmp_path / "settings.json")
    assert (saved.theme, saved.font_size, saved.always_on_top) == ("sepia", 17.0, True)
    assert saved.geometry


def test_saved_settings_are_applied(made):
    s = Settings(theme="sepia", font_size=18.0, always_on_top=True, speed=1.5, voice="bf_emma")
    app = made(settings=s)
    app.start()
    w = app.window
    assert (w.theme, w.font_size, w.always_on_top) == ("sepia", 18.0, True)
    assert w.speed_value() == 1.5
    assert wait_until(lambda: w.voice_box.isEnabled())
    assert w.voice_box.currentData() == "bf_emma"


def test_unknown_saved_voice_falls_back(made):
    app = made(settings=Settings(voice="xx_gone"))
    app.start()
    assert wait_until(lambda: app.window.voice_box.isEnabled())
    assert app.player.voice == "af_heart"
    assert app.window.voice_box.currentData() == "af_heart"


def test_messages_from_a_second_launch(made, monkeypatch):
    app = made()
    app.start(show=False)
    app.handle_message({"cmd": "show"})
    assert app.window.isVisible()
    app.handle_message({"cmd": "open", "text": TEXT})
    assert app.window.view.count == 2
    app.handle_message({"cmd": "bogus"})
    quits = []
    monkeypatch.setattr("mytts.ui.app.QApplication.quit", lambda *_: quits.append(1))
    app.handle_message({"cmd": "quit"})
    assert quits == [1] and not app.window.hide_on_close


def test_model_download_then_start(made):
    files = [FakeFile("a.onnx", 300), FakeFile("b.bin", 100)]
    present = []

    def missing():
        return [f for f in files if f.name not in present]

    def ensure(progress, cancel):
        for f in files:
            progress(f, f.size // 2, f.size)
            progress(f, f.size, f.size)
            present.append(f.name)

    app = made(missing=missing, ensure=ensure)
    app.start(show=False)
    w = app.window
    assert w.isVisible()  # shown even with --tray: nothing works without the voices
    assert w.notice.isVisible() and w.notice.button.text() == "Download"
    assert w.status.text() == "Voices not installed"
    w.notice.button.click()
    assert wait_until(lambda: not w.notice.isVisible())
    assert wait_until(lambda: app.player.voices)  # the player started once the files were there


def test_model_download_failure_and_cancel(made):
    files = [FakeFile("a.onnx", 300)]
    mode = {"fail": True}

    def ensure(progress, cancel):
        if mode["fail"]:
            raise models.DownloadError("no network")
        progress(files[0], 100, 300)
        assert cancel.wait(2)
        raise models.DownloadCancelled

    app = made(missing=lambda: files, ensure=ensure)
    app.start()
    n = app.window.notice
    n.button.click()
    assert wait_until(lambda: n.button.text() == "Retry")
    assert "no network" in n.label.text()

    mode["fail"] = False
    n.button.click()
    assert wait_until(lambda: n.button.text() == "Cancel")
    n.button.click()
    assert wait_until(lambda: n.button.text() == "Download")
    assert not app.player.voices


def test_settings_dialog(made, monkeypatch, tmp_path):
    autostart_calls = []
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "set_enabled", autostart_calls.append)
    app = made()
    app.start()
    app.show_settings()
    d = app.dialog
    assert d.isVisible()

    d.restore_switch.click()
    assert app.settings.restore_clipboard is False
    d.autostart_switch.click()
    assert autostart_calls == [True]
    d.on_top_switch.click()
    assert app.window.always_on_top
    app.window.set_always_on_top(False)  # the pin button and the switch stay in step
    assert not d.on_top_switch.isChecked()

    d.hotkey_edit.click()
    assert d.hotkey_edit.recording
    QTest.keyClick(d.hotkey_edit, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert not d.hotkey_edit.recording
    assert app.settings.hotkey == "Ctrl+Shift+R"
    assert Settings.load(tmp_path / "settings.json").hotkey == "Ctrl+Shift+R"


def test_hotkey_edit_rejects_and_cancels(qapp):
    e = HotkeyEdit("Ctrl+Alt+Space")
    e.show()
    changes, recording = [], []
    e.changed.connect(changes.append)
    e.recording_changed.connect(recording.append)
    e.click()
    assert e.text() == RECORD_PROMPT
    QTest.keyClick(e, Qt.Key.Key_A, Qt.KeyboardModifier.ShiftModifier)  # Shift alone is not enough
    assert e.recording and "Ctrl, Alt or Win" in e.text()
    QTest.keyClick(e, Qt.Key.Key_Escape)
    assert not e.recording and e.text() == "Ctrl+Alt+Space"
    assert changes == [] and recording == [True, False]
    e.close()


def test_autostart_command_and_registry(monkeypatch):
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows registry")
    import winreg

    cmd = autostart.command()
    assert "pythonw.exe" in cmd.lower() and cmd.endswith("--tray")

    key = r"Software\mytts-tests\Run"
    winreg.CreateKey(winreg.HKEY_CURRENT_USER, key).Close()
    monkeypatch.setattr(autostart, "RUN_KEY", key)
    try:
        assert not autostart.is_enabled()
        autostart.set_enabled(True)
        assert autostart.registered_command() == cmd
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, autostart.VALUE_NAME, 0, winreg.REG_SZ, "old command")
        autostart.refresh()
        assert autostart.registered_command() == cmd
        autostart.set_enabled(False)
        assert not autostart.is_enabled()
        autostart.set_enabled(False)  # already off: no error
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\mytts-tests")
