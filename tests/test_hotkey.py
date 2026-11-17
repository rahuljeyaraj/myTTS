import sys
import threading
import time

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from mytts import hotkey as hk

CTRL, ALT, SHIFT, WIN = (hk.MOD_CONTROL, hk.MOD_ALT, hk.MOD_SHIFT, hk.MOD_WIN)
M = Qt.KeyboardModifier


def test_parse_default():
    assert hk.parse("Ctrl+Alt+Space") == (CTRL | ALT, 0x20)


def test_parse_is_lenient_and_normalize_is_canonical():
    assert hk.normalize("alt + control + space") == "Ctrl+Alt+Space"
    assert hk.normalize("Shift+Win+r") == "Shift+Win+R"
    assert hk.normalize("Ctrl+PageDown") == "Ctrl+PgDown"
    assert hk.normalize("meta+f13") == "Win+F13"


@pytest.mark.parametrize("bad", ["Space", "Shift+A", "Ctrl+Foo", "Hyper+A", "Ctrl+", "", "Ctrl+Alt"])
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        hk.parse(bad)


def test_every_key_round_trips():
    for vk, name in hk.KEY_NAMES.items():
        text = hk.to_text(CTRL | SHIFT, vk)
        assert text == f"Ctrl+Shift+{name}"
        assert hk.parse(text) == (CTRL | SHIFT, vk)


def key(k, mods=M.NoModifier, native_vk=0):
    return QKeyEvent(QEvent.Type.KeyPress, k, mods, 0, native_vk, 0)


def test_from_key_event_qt_keys():
    assert hk.from_key_event(key(Qt.Key.Key_R, M.ControlModifier | M.AltModifier)) == "Ctrl+Alt+R"
    assert hk.from_key_event(key(Qt.Key.Key_F5, M.MetaModifier)) == "Win+F5"
    assert hk.from_key_event(key(Qt.Key.Key_Space, M.ControlModifier)) == "Ctrl+Space"
    assert hk.from_key_event(key(Qt.Key.Key_A, M.ShiftModifier)) is None  # Shift alone is not enough
    assert hk.from_key_event(key(Qt.Key.Key_Escape, M.ControlModifier)) is None  # not an allowed key


def test_from_key_event_prefers_native_virtual_key():
    # Shift+1 reports Qt.Key_Exclam; the virtual key is still '1'.
    e = key(Qt.Key.Key_Exclam, M.ControlModifier | M.ShiftModifier, native_vk=0x31)
    assert hk.from_key_event(e) == "Ctrl+Shift+1"


def test_modifier_text():
    # A modifier's own flag comes from the event type, whatever the platform reports.
    for mods in (M.ControlModifier, M.ControlModifier | M.AltModifier):
        assert hk.modifier_text(key(Qt.Key.Key_Alt, mods)) == "Ctrl+Alt+"
        release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Alt, mods)
        assert hk.modifier_text(release) == "Ctrl+"
    assert hk.modifier_text(key(Qt.Key.Key_A)) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey is Windows-only")
def test_register_conflict_and_release():
    combo = "Ctrl+Alt+Shift+F23"  # unlikely to be taken
    results = {1: [], 2: []}
    events = {1: threading.Event(), 2: threading.Event()}

    def sink(n):
        def on_status(name, hotkey, error):
            assert name == "read"
            results[n].append((hotkey, error))
            events[n].set()
        return on_status

    first = hk.HotkeyThread(lambda: None, sink(1))
    second = hk.HotkeyThread(lambda: None, sink(2))
    first.start()
    second.start()
    try:
        first.set("read", combo)
        assert events[1].wait(2) and results[1][-1] == (combo, None)
        second.set("read", combo)
        assert events[2].wait(2)
        assert "already used" in results[2][-1][1]

        first.suspend(True)  # as while recording a new hotkey
        # The release happens on first's thread and reports nothing, so retry until it has.
        deadline = time.monotonic() + 2
        while True:
            events[2].clear()
            second.set("read", combo)
            assert events[2].wait(2)
            if results[2][-1] == (combo, None) or time.monotonic() > deadline:
                break
            time.sleep(0.02)
        assert results[2][-1] == (combo, None)
    finally:
        first.stop()
        second.stop()


def test_invalid_hotkey_reports_error():
    t = hk.HotkeyThread(lambda name: None, lambda n, k, e: None)
    ok, error = t._register(None, "Shift+A")
    assert not ok and "Ctrl, Alt or Win" in error


@pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey is Windows-only")
def test_several_hotkeys_on_one_thread():
    results = []
    got = threading.Condition()

    def on_status(name, hotkey, error):
        with got:
            results.append((name, hotkey, error))
            got.notify_all()

    def wait_for(entry):
        with got:
            assert got.wait_for(lambda: entry in results, timeout=2), results

    t = hk.HotkeyThread(lambda name: None, on_status, {"read": "Read selection"})
    t.start()
    try:
        t.set("read", "Ctrl+Alt+Shift+F21")
        t.set("next", "Ctrl+Alt+Shift+F22")
        wait_for(("read", "Ctrl+Alt+Shift+F21", None))
        wait_for(("next", "Ctrl+Alt+Shift+F22", None))
        t.set("next", "Ctrl+Alt+Shift+F21")  # the same keys as another action
        wait_for(("next", "Ctrl+Alt+Shift+F21", "Ctrl+Alt+Shift+F21 is already used for Read selection."))
    finally:
        t.stop()
