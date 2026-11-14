"""The reader window: the text being read, with the current sentence highlighted."""

from __future__ import annotations

import time
from bisect import bisect_right
from collections.abc import Sequence

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPalette,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..engine import Voice
from ..player import MAX_SPEED, MIN_SPEED, Player, State
from ..text import Segment, normalize, segment
from . import theme as themes

LINE_HEIGHT = 160  # percent
COLUMN_CHARS = 72  # comfortable line length; wider windows get side margins
PAD_X, PAD_Y = 36, 28
FONT_PT, MIN_FONT_PT, MAX_FONT_PT = 13.0, 9.0, 28.0
SPEED_STEP = 0.05
SPEED_DEBOUNCE_MS = 300
FOLLOW_PAUSE_S = 3.0  # after the user scrolls, don't auto-scroll for this long
EMPTY_HINT = "Paste text with Ctrl+V to hear it read aloud."


class _Utf16Offsets:
    """Python string offsets (code points) to Qt text positions (UTF-16 code units)."""

    def __init__(self, text: str):
        self._wide = [i for i, ch in enumerate(text) if ord(ch) > 0xFFFF]

    def __call__(self, i: int) -> int:
        return i + bisect_right(self._wide, i - 1) if self._wide else i


class TextView(QTextEdit):
    """Read-only text with a highlighted current sentence. Clicking a sentence selects it."""

    segment_clicked = Signal(int)
    zoom_requested = Signal(int)  # +1 or -1

    # Keys the window handles (play/pause, stop, previous/next, paste, zoom).
    _WINDOW_KEYS = {Qt.Key.Key_Space, Qt.Key.Key_Escape, Qt.Key.Key_Left, Qt.Key.Key_Right}

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setUndoRedoEnabled(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setMouseTracking(True)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        self._starts: list[int] = []
        self._ends: list[int] = []
        self._current = -1
        self._hover = -1
        self._press_pos = None
        self._user_scrolled_at = 0.0
        self._current_fmt = QTextCharFormat()
        self._hover_fmt = QTextCharFormat()
        self._hint_color = QColor("#888888")
        self._scroll_anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_anim.setDuration(240)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.verticalScrollBar().actionTriggered.connect(self._note_user_scroll)

    # ------------------------------------------------------------------ content

    @property
    def count(self) -> int:
        return len(self._starts)

    def set_document(self, text: str, segments: Sequence[Segment]) -> None:
        to_qt = _Utf16Offsets(text)
        self._starts = [to_qt(s.start) for s in segments]
        self._ends = [to_qt(s.end) for s in segments]
        self._current = self._hover = -1
        self._scroll_anim.stop()
        self.setPlainText(text)
        self._apply_layout()
        self._refresh()
        self.verticalScrollBar().setValue(0)

    def set_colors(self, t: themes.Theme) -> None:
        self._current_fmt.setBackground(QColor(t.highlight))
        self._hover_fmt.setBackground(QColor(t.hover))
        self._hint_color = QColor(t.muted)
        self._refresh()

    def setFont(self, font) -> None:  # noqa: N802 (Qt naming)
        super().setFont(font)
        self._apply_layout()

    def _apply_layout(self) -> None:
        """Line spacing and margins; setPlainText() resets both."""
        doc = self.document()
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(LINE_HEIGHT, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(fmt)
        self._update_margins()

    def _update_margins(self) -> None:
        column = self.fontMetrics().averageCharWidth() * COLUMN_CHARS
        side = max(PAD_X, (self.viewport().width() - column) // 2)
        root = self.document().rootFrame()
        f = root.frameFormat()
        if (f.leftMargin(), f.rightMargin(), f.topMargin()) != (side, side, PAD_Y):
            f.setLeftMargin(side)
            f.setRightMargin(side)
            f.setTopMargin(PAD_Y)
            f.setBottomMargin(PAD_Y * 2)
            root.setFrameFormat(f)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._update_margins()

    # ------------------------------------------------------------- highlighting

    def set_current(self, index: int) -> None:
        self._current = index if 0 <= index < self.count else -1
        self._refresh()
        if self._current >= 0:
            self._follow(self._current)

    def _selection(self, i: int, fmt: QTextCharFormat) -> QTextEdit.ExtraSelection:
        sel = QTextEdit.ExtraSelection()
        cursor = QTextCursor(self.document())
        cursor.setPosition(self._starts[i])
        cursor.setPosition(self._ends[i], QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = cursor
        sel.format = fmt
        return sel

    def _refresh(self) -> None:
        sels = []
        if self._hover >= 0 and self._hover != self._current:
            sels.append(self._selection(self._hover, self._hover_fmt))
        if self._current >= 0:
            sels.append(self._selection(self._current, self._current_fmt))
        self.setExtraSelections(sels)

    def _follow(self, i: int) -> None:
        """Scroll so the sentence is comfortably in view, unless the user is scrolling."""
        if time.monotonic() - self._user_scrolled_at < FOLLOW_PAUSE_S:
            return
        cursor = QTextCursor(self.document())
        cursor.setPosition(self._starts[i])
        top = self.cursorRect(cursor).top()
        cursor.setPosition(self._ends[i])
        bottom = self.cursorRect(cursor).bottom()
        height = self.viewport().height()
        margin = int(height * 0.12)
        if top >= margin and bottom <= height - margin:
            return
        bar = self.verticalScrollBar()
        target = bar.value() + top - int(height * 0.3)
        target = max(bar.minimum(), min(bar.maximum(), target))
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(bar.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.start()

    def _note_user_scroll(self, _action: int) -> None:
        self._user_scrolled_at = time.monotonic()
        self._scroll_anim.stop()

    # ------------------------------------------------------------------- mouse

    def segment_at(self, pos) -> int:
        """Index of the sentence under a viewport position, or -1."""
        if not self._starts:
            return -1
        doc_pos = QPointF(pos.x() + self.horizontalScrollBar().value(), pos.y() + self.verticalScrollBar().value())
        p = self.document().documentLayout().hitTest(doc_pos, Qt.HitTestAccuracy.ExactHit)
        if p < 0:
            return -1
        i = bisect_right(self._starts, p) - 1
        return i if i >= 0 and p <= self._ends[i] else -1

    def _set_hover(self, i: int) -> None:
        if i != self._hover:
            self._hover = i
            self._refresh()
        shape = Qt.CursorShape.PointingHandCursor if i >= 0 else Qt.CursorShape.ArrowCursor
        if self.viewport().cursor().shape() != shape:
            self.viewport().setCursor(shape)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        super().mouseMoveEvent(e)
        dragging = bool(e.buttons() & Qt.MouseButton.LeftButton)
        self._set_hover(-1 if dragging else self.segment_at(e.position().toPoint()))

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        super().mouseReleaseEvent(e)
        press, self._press_pos = self._press_pos, None
        if e.button() != Qt.MouseButton.LeftButton or press is None:
            return
        pos = e.position().toPoint()
        dragged = (pos - press).manhattanLength() >= QApplication.startDragDistance()
        if not dragged and not self.textCursor().hasSelection():
            i = self.segment_at(pos)
            if i >= 0:
                self.segment_clicked.emit(i)
        self._set_hover(self.segment_at(pos))

    def viewportEvent(self, e) -> bool:  # noqa: N802
        if e.type() == QEvent.Type.Leave:
            self._set_hover(-1)
        return super().viewportEvent(e)

    def wheelEvent(self, e) -> None:  # noqa: N802
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            dy = e.angleDelta().y()
            if dy:
                self.zoom_requested.emit(1 if dy > 0 else -1)
            e.accept()
            return
        self._note_user_scroll(0)
        super().wheelEvent(e)

    # ---------------------------------------------------------------- keyboard

    def keyPressEvent(self, e) -> None:  # noqa: N802
        plain = e.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
        if (plain and e.key() in self._WINDOW_KEYS) or e.matches(QKeySequence.StandardKey.Paste) or _zoom_key(e):
            e.ignore()  # let the window handle it
            return
        super().keyPressEvent(e)

    # ---------------------------------------------------------------- painting

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        if self.document().isEmpty():
            p = QPainter(self.viewport())
            p.setPen(self._hint_color)
            p.setFont(self.font())
            p.drawText(self.viewport().rect().adjusted(PAD_X, 0, -PAD_X, 0),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, EMPTY_HINT)


class _ComboBox(QComboBox):
    """A flat combo box with an icon-font chevron (stylesheets need an image file otherwise)."""

    def __init__(self, glyph_font: QFont, chevron: str):
        super().__init__()
        self._chevron = chevron
        self._chevron_font = QFont(glyph_font)
        self._chevron_font.setPixelSize(10)
        self.chevron_color = QColor("#888888")

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setFont(self._chevron_font)
        p.setPen(self.chevron_color)
        r = self.rect()
        p.drawText(r.adjusted(r.width() - 26, 0, -8, 0), Qt.AlignmentFlag.AlignCenter, self._chevron)


def _zoom_key(e) -> int:
    """+1 / -1 for a zoom-in / zoom-out shortcut, 0 otherwise."""
    if not e.modifiers() & Qt.KeyboardModifier.ControlModifier:
        return 0
    if e.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
        return 1
    if e.key() in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
        return -1
    return 0


class ReaderWindow(QWidget):
    """The text, a transport bar, voice and speed controls."""

    def __init__(self, player: Player, theme: str = "dark", font_size: float = FONT_PT):
        super().__init__()
        self.player = player
        self.setObjectName("reader")
        self.setWindowTitle("mytts")
        self.resize(820, 580)
        self.setMinimumSize(600, 320)

        self._theme = themes.THEMES.get(theme, themes.DARK)
        self._font_size = font_size
        self._error_until = 0.0
        self._glyph_font, self._glyphs = themes.icon_font(16)

        self.view = TextView()
        self.view.segment_clicked.connect(self._on_segment_clicked)
        self.view.zoom_requested.connect(lambda step: self.set_font_size(self._font_size + step))

        bar = QWidget(objectName="bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 10)
        row.setSpacing(2)

        self.prev_btn = self._button("prev", "Previous sentence (Left)", player.prev)
        self.play_btn = self._button("play", "Play (Space)", self.toggle_play)
        self.play_btn.setObjectName("play")
        self.play_btn.setFont(themes.icon_font(20)[0])
        self.stop_btn = self._button("stop", "Stop (Esc)", player.stop)
        self.next_btn = self._button("next", "Next sentence (Right)", player.next)
        for b in (self.prev_btn, self.play_btn, self.stop_btn, self.next_btn):
            row.addWidget(b)
        row.addSpacing(12)

        self.status = QLabel(objectName="status")
        self.status.setMinimumWidth(40)
        row.addWidget(self.status, 1)

        self.voice_box = _ComboBox(self._glyph_font, self._glyphs["chevron"])
        self.voice_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.voice_box.setToolTip("Voice")
        self.voice_box.setMaxVisibleItems(18)
        self.voice_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.voice_box.addItem("Voice")
        self.voice_box.setEnabled(False)
        self.voice_box.currentIndexChanged.connect(self._on_voice_chosen)
        row.addWidget(self.voice_box)
        row.addSpacing(10)

        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed.setRange(round(MIN_SPEED / SPEED_STEP), round(MAX_SPEED / SPEED_STEP))
        self.speed.setPageStep(2)
        self.speed.setFixedWidth(110)
        self.speed.setToolTip("Speed (double-click the value to reset)")
        self.speed_label = QLabel()
        self.speed_label.setFixedWidth(44)
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.speed_label.mouseDoubleClickEvent = lambda _e: self.speed.setValue(round(1 / SPEED_STEP))
        self._speed_timer = QTimer(self, singleShot=True, interval=SPEED_DEBOUNCE_MS)
        self._speed_timer.timeout.connect(lambda: self.player.set_speed(self.speed_value()))
        self.speed.valueChanged.connect(self._on_speed_moved)
        self.speed.setValue(round(player.speed / SPEED_STEP))
        self._on_speed_moved()
        self._speed_timer.stop()
        row.addWidget(self.speed_label)
        row.addSpacing(6)
        row.addWidget(self.speed)
        row.addSpacing(10)

        self.theme_btn = self._button("theme", "Switch theme (dark / sepia)", self.cycle_theme)
        self.pin_btn = self._button("pin", "Keep on top", None)
        self.pin_btn.setCheckable(True)
        self.pin_btn.toggled.connect(self.set_always_on_top)
        row.addWidget(self.theme_btn)
        row.addWidget(self.pin_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view, 1)
        layout.addWidget(bar)

        self._loading_timer = QTimer(self, singleShot=True, interval=300)
        self._loading_timer.timeout.connect(self._update_status)
        self._error_timer = QTimer(self, singleShot=True)
        self._error_timer.timeout.connect(self._update_status)

        player.ready.connect(self._on_voices)
        player.segment_started.connect(self._on_segment)
        player.state_changed.connect(self._on_state)
        player.error.connect(self.show_error)
        if player.voices:
            self._on_voices(player.voices)

        self.set_font_size(font_size)
        self.apply_theme(self._theme.name)
        self._on_state(player.state)
        self.view.setFocus()

    # ------------------------------------------------------------ public API

    def load_text(self, raw: str, play: bool = True) -> bool:
        """Show `raw` (cleaned up) and read it from the start. False if there is nothing to read."""
        text = normalize(raw)
        segments = segment(text)
        if not segments:
            self.show_error("There is no text to read.")
            return False
        self.view.set_document(text, segments)
        self.player.load(text, segments)
        if play:
            self.player.play(0)
        self._update_status()
        return True

    def toggle_play(self) -> None:
        if self.view.count:
            self.player.toggle()

    def speed_value(self) -> float:
        return round(self.speed.value() * SPEED_STEP, 2)

    def set_font_size(self, size: float) -> None:
        self._font_size = max(MIN_FONT_PT, min(MAX_FONT_PT, size))
        self.view.setFont(themes.reading_font(self._font_size))

    def apply_theme(self, name: str) -> None:
        self._theme = themes.THEMES.get(name, themes.DARK)
        t = self._theme
        self.setStyleSheet(themes.stylesheet(t))
        self.view.set_colors(t)
        self.voice_box.chevron_color = QColor(t.muted)
        pal = self.view.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.muted))
        self.view.setPalette(pal)
        themes.style_title_bar(int(self.winId()), t)

    def cycle_theme(self) -> None:
        names = list(themes.THEMES)
        self.apply_theme(names[(names.index(self._theme.name) + 1) % len(names)])

    @property
    def theme(self) -> str:
        return self._theme.name

    @property
    def font_size(self) -> float:
        return self._font_size

    def set_always_on_top(self, on: bool) -> None:
        if not themes.set_topmost(int(self.winId()), on):  # non-Windows fallback
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
            self.show()
        if self.pin_btn.isChecked() != on:
            self.pin_btn.setChecked(on)
        self.pin_btn.setText(self._glyphs["pinned" if on else "pin"])
        self.pin_btn.setToolTip("Stop keeping on top" if on else "Keep on top")

    def show_error(self, message: str) -> None:
        self._error_until = time.monotonic() + 8
        self._show_status(message, error=True)
        self._error_timer.start(8000)

    # --------------------------------------------------------------- internals

    def _button(self, glyph: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setFont(self._glyph_font)
        b.setText(self._glyphs[glyph])
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setAutoRaise(True)
        if slot is not None:
            b.clicked.connect(slot)
        return b

    def _on_voices(self, voices: list[Voice]) -> None:
        box = self.voice_box
        box.blockSignals(True)
        box.clear()
        language = None
        for v in voices:
            if language is not None and v.language != language:
                box.insertSeparator(box.count())
            language = v.language
            box.addItem(v.label, v.id)
        i = box.findData(self.player.voice)
        box.setCurrentIndex(max(0, i))
        box.setEnabled(True)
        box.blockSignals(False)
        self._update_status()

    def _on_voice_chosen(self, index: int) -> None:
        voice_id = self.voice_box.itemData(index)
        if voice_id:
            self.player.set_voice(voice_id)

    def _on_speed_moved(self) -> None:
        self.speed_label.setText(f"{self.speed_value():.2f}×")
        self._speed_timer.start()

    def _on_segment_clicked(self, i: int) -> None:
        self.player.play(i)

    def _on_segment(self, i: int) -> None:
        self.view.set_current(i)
        self._update_status()

    def _on_state(self, state: State) -> None:
        playing = state in (State.PLAYING, State.LOADING)
        self.play_btn.setText(self._glyphs["pause" if playing else "play"])
        self.play_btn.setToolTip("Pause (Space)" if playing else "Play (Space)")
        if state == State.STOPPED:
            self.view.set_current(-1)
        if state == State.LOADING:
            self._loading_timer.start()
        else:
            self._loading_timer.stop()
        self._update_status()

    def _update_status(self) -> None:
        if time.monotonic() < self._error_until:
            return
        state, n = self.player.state, self.view.count
        if self.player.engine_error:
            self._show_status(self.player.engine_error, error=True)
            return
        if not self.player.voices and (state == State.LOADING or not n):
            text = "Loading voices…"
        elif state == State.LOADING and not self._loading_timer.isActive():
            text = "Preparing speech…"
        elif state == State.STOPPED:
            text = f"{n} sentence{'s' if n != 1 else ''}" if n else ""
        else:
            text = f"{self.player.current + 1} / {n}" if n else ""
        self._show_status(text)

    def _show_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setToolTip(text if error else "")
        if self.status.property("error") != error:
            self.status.setProperty("error", error)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        key, mods = e.key(), e.modifiers()
        plain = mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
        if e.matches(QKeySequence.StandardKey.Paste):
            self.load_text(QApplication.clipboard().text())
        elif zoom := _zoom_key(e):
            self.set_font_size(self._font_size + zoom)
        elif mods & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_0:
            self.set_font_size(FONT_PT)
        elif plain and key == Qt.Key.Key_Space:
            self.toggle_play()
        elif plain and key == Qt.Key.Key_Escape:
            self.player.stop()
        elif plain and key == Qt.Key.Key_Left:
            self.player.prev()
        elif plain and key == Qt.Key.Key_Right:
            self.player.next()
        else:
            super().keyPressEvent(e)
