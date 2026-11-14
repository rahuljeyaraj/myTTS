import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from mytts.engine import SAMPLE_RATE, Voice
from mytts.player import Player, State
from mytts.text import normalize, segment
from mytts.ui.reader import ReaderWindow, TextView, _Utf16Offsets

TEXT = "Books 📚 are quiet. They wait for you 🙂. Then they speak."


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


def make_player():
    return Player(engine_factory=FakeEngine, stream_factory=lambda cb: (FakeStream(), SAMPLE_RATE))


def selected(view, i):
    c = QTextCursor(view.document())
    c.setPosition(view._starts[i])
    c.setPosition(view._ends[i], QTextCursor.MoveMode.KeepAnchor)
    return c.selectedText()


def center_of(view, i):
    c = QTextCursor(view.document())
    c.setPosition(view._starts[i] + 2)
    return view.cursorRect(c).center()


@pytest.fixture
def view(qapp):
    v = TextView()
    v.resize(600, 400)
    v.show()
    text = normalize(TEXT)
    v.set_document(text, segment(text))
    qapp.processEvents()
    yield v
    v.close()


def test_utf16_offsets_count_astral_characters_twice():
    to_qt = _Utf16Offsets("a📚b🙂c")
    assert [to_qt(i) for i in range(6)] == [0, 1, 3, 4, 6, 7]
    assert _Utf16Offsets("plain")(3) == 3


def test_segments_map_to_the_right_text_after_emoji(view):
    assert [selected(view, i) for i in range(view.count)] == [
        "Books 📚 are quiet.",
        "They wait for you 🙂.",
        "Then they speak.",
    ]


def test_hit_testing_finds_sentences_and_ignores_empty_space(view):
    for i in range(view.count):
        assert view.segment_at(center_of(view, i)) == i
    assert view.segment_at(QPoint(590, 390)) == -1


def test_click_jumps_but_drag_does_not(view):
    clicked = []
    view.segment_clicked.connect(clicked.append)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(view, 1))
    assert clicked == [1]

    start, end = center_of(view, 0), center_of(view, 1)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    assert clicked == [1]


def test_current_sentence_highlight(view):
    view.set_current(2)
    assert len(view.extraSelections()) == 1
    view.set_current(-1)
    assert view.extraSelections() == []


@pytest.fixture
def window(qapp):
    player = make_player()
    w = ReaderWindow(player)
    w.show()
    yield w, player, qapp
    w.close()
    player.close()


def wait_ready(w, player, qapp):
    player.start()
    for _ in range(300):
        qapp.processEvents()
        if w.voice_box.isEnabled():
            return
        QTest.qWait(10)
    raise AssertionError("voices never arrived")


def test_window_loads_text_and_keyboard_controls_playback(window):
    w, player, qapp = window
    wait_ready(w, player, qapp)
    assert w.load_text(TEXT)
    assert player.count == 3 and w.view.count == 3
    qapp.processEvents()
    assert player.state in (State.LOADING, State.PLAYING)
    assert "1 / 3" in w.status.text()

    QTest.keyClick(w.view, Qt.Key.Key_Space)
    assert player.state == State.PAUSED
    QTest.keyClick(w.view, Qt.Key.Key_Right)
    QTest.keyClick(w.view, Qt.Key.Key_Right)
    assert player.current == 2
    QTest.keyClick(w.view, Qt.Key.Key_Left)
    assert player.current == 1
    qapp.processEvents()
    assert "2 / 3" in w.status.text()
    QTest.keyClick(w.view, Qt.Key.Key_Escape)
    assert player.state == State.STOPPED
    qapp.processEvents()
    assert w.view.extraSelections() == []


def test_nothing_to_read_is_reported(window):
    w, player, _ = window
    assert not w.load_text("  \n ... \n")
    assert player.count == 0
    assert w.status.property("error") is True


def test_voices_fill_the_combo_with_language_separators(window):
    w, player, qapp = window
    wait_ready(w, player, qapp)
    labels = [w.voice_box.itemText(i) for i in range(w.voice_box.count())]
    assert labels == ["Heart · English (US), female", "", "Emma · English (UK), female"]
    w.voice_box.setCurrentIndex(2)
    assert player.voice == "bf_emma"


def test_speed_slider_is_debounced(window):
    w, player, _ = window
    w.speed.setValue(30)
    assert w.speed_label.text() == "1.50×"
    assert player.speed == 1.0
    QTest.qWait(400)
    assert player.speed == 1.5


def test_theme_and_font_size(window):
    w, _, _ = window
    w.cycle_theme()
    assert w.theme == "sepia"
    w.cycle_theme()
    assert w.theme == "dark"
    w.set_font_size(100)
    assert w.view.font().pointSizeF() == 28
