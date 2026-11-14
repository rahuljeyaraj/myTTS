"""The settings window: hotkey, clipboard, keep on top, start with Windows."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import hotkey as hk
from ..settings import Settings
from . import theme as themes

_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta, Qt.Key.Key_AltGr}
RECORD_PROMPT = "Press a shortcut…"


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


class Switch(QAbstractButton):
    """An on/off toggle, painted in the theme's colors."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._pos = 0.0  # knob position, 0 = off, 1 = on
        self._anim = QVariantAnimation(self, duration=120)
        self._anim.valueChanged.connect(self._move)
        self.toggled.connect(self._animate)
        self._on, self._off, self._knob_on, self._knob_off = (QColor(c) for c in ("#d9a55b", "#3b3833", "#1c1b19", "#8c867b"))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(40, 22)

    def set_theme(self, t: themes.Theme) -> None:
        self._on, self._off, self._knob_on, self._knob_off = (QColor(c) for c in (t.accent, t.scroll, t.bg, t.muted))
        self.update()

    def setChecked(self, on: bool) -> None:  # noqa: N802 - jump without animating
        super().setChecked(on)
        self._anim.stop()
        self._move(1.0 if on else 0.0)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _move(self, value) -> None:
        self._pos = float(value)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        h = r.height()
        track = QColor(self._off)
        on = self._on
        track.setRedF(track.redF() + (on.redF() - track.redF()) * self._pos)
        track.setGreenF(track.greenF() + (on.greenF() - track.greenF()) * self._pos)
        track.setBlueF(track.blueF() + (on.blueF() - track.blueF()) * self._pos)
        p.setBrush(track)
        p.drawRoundedRect(r, h / 2, h / 2)
        d = h - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._pos
        p.setBrush(self._knob_on if self._pos > 0.5 else self._knob_off)
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        if self.hasFocus():
            p.setPen(self._on)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, h / 2, h / 2)


class HotkeyEdit(QPushButton):
    """Shows the hotkey; click it and press a new one (Esc cancels)."""

    changed = Signal(str)
    recording_changed = Signal(bool)

    def __init__(self, hotkey: str, parent: QWidget | None = None):
        super().__init__(hotkey, parent)
        self.setObjectName("hotkey")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click, then press the keys you want to use")
        self._hotkey = hotkey
        self._hint = False
        self.recording = False
        self.clicked.connect(self.start)

    @property
    def hotkey(self) -> str:
        return self._hotkey

    def set_hotkey(self, hotkey: str) -> None:
        self._hotkey = hotkey
        if not self.recording:
            self.setText(hotkey)

    def start(self) -> None:
        if self.recording:
            return
        self.recording = True
        self.setProperty("recording", True)
        _repolish(self)
        self.setText(RECORD_PROMPT)
        self.setFocus()
        self.grabKeyboard()
        self.recording_changed.emit(True)

    def stop(self, new: str | None = None) -> None:
        if not self.recording:
            return
        self.releaseKeyboard()
        self.recording = False
        self.setProperty("recording", False)
        _repolish(self)
        if new:
            self._hotkey = new
        self.setText(self._hotkey)
        if new:  # before recording_changed, so the app re-registers the new hotkey only
            self.changed.emit(new)
        self.recording_changed.emit(False)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if not self.recording:
            super().keyPressEvent(e)
            return
        self._hint = False
        if e.key() == Qt.Key.Key_Escape and not e.modifiers():
            self.stop()
        elif e.key() in _MODIFIER_KEYS:
            self.setText(hk.modifier_text(e) + "…")
        elif combo := hk.from_key_event(e):
            self.stop(combo)
        else:
            self._hint = True  # stays until the next key press
            self.setText("Use Ctrl, Alt or Win with a key")

    def keyReleaseEvent(self, e) -> None:  # noqa: N802
        if not self.recording:
            super().keyReleaseEvent(e)
        elif e.key() in _MODIFIER_KEYS and not self._hint:
            held = hk.modifier_text(e)
            self.setText(held + "…" if held else RECORD_PROMPT)

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self.stop()
        super().focusOutEvent(e)


class SettingsDialog(QDialog):
    hotkey_changed = Signal(str)
    hotkey_recording = Signal(bool)
    restore_clipboard_changed = Signal(bool)
    on_top_changed = Signal(bool)
    autostart_changed = Signal(bool)

    def __init__(self, settings: Settings, autostart: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("settings")
        self.setWindowTitle("mytts settings")
        self.setMinimumWidth(500)

        self.hotkey_edit = HotkeyEdit(settings.hotkey)
        self.hotkey_edit.changed.connect(self.hotkey_changed)
        self.hotkey_edit.recording_changed.connect(self.hotkey_recording)
        self.hotkey_status = QLabel(objectName="hint")
        self.hotkey_status.setWordWrap(True)

        self.restore_switch = Switch()
        self.restore_switch.setChecked(settings.restore_clipboard)
        self.restore_switch.toggled.connect(self.restore_clipboard_changed)
        self.on_top_switch = Switch()
        self.on_top_switch.setChecked(settings.always_on_top)
        self.on_top_switch.toggled.connect(self.on_top_changed)
        self.autostart_switch = Switch()
        self.autostart_switch.setChecked(autostart)
        self.autostart_switch.toggled.connect(self.autostart_changed)

        close = QPushButton("Close", objectName="primary")
        close.clicked.connect(self.close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(16)
        hotkey_block = QVBoxLayout()
        hotkey_block.setSpacing(8)
        hotkey_block.addLayout(self._row("Read selection", "Select text in any app, then press this.",
                                         self.hotkey_edit))
        hotkey_block.addWidget(self.hotkey_status)
        self.hotkey_status.hide()
        layout.addLayout(hotkey_block)
        layout.addLayout(self._row("Restore the clipboard",
                                   "Put back what was on the clipboard after copying the selection.",
                                   self.restore_switch))
        layout.addLayout(self._row("Keep the reader on top", "Same as the pin button.", self.on_top_switch))
        layout.addLayout(self._row("Start with Windows", "Start in the tray when you sign in.",
                                   self.autostart_switch))
        layout.addSpacing(4)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    @staticmethod
    def _row(title: str, hint: str, control: QWidget) -> QHBoxLayout:
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(QLabel(title, objectName="heading"))
        h = QLabel(hint, objectName="hint")
        h.setWordWrap(True)
        text.addWidget(h)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addLayout(text, 1)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def set_hotkey_status(self, hotkey: str, error: str | None) -> None:
        self.hotkey_edit.set_hotkey(hotkey)
        self.hotkey_status.setText(error or "")
        self.hotkey_status.setProperty("error", bool(error))
        _repolish(self.hotkey_status)
        self.hotkey_status.setVisible(bool(error))

    def set_on_top(self, on: bool) -> None:
        if self.on_top_switch.isChecked() != on:
            self.on_top_switch.blockSignals(True)
            self.on_top_switch.setChecked(on)
            self.on_top_switch.blockSignals(False)

    def apply_theme(self, t: themes.Theme) -> None:
        self.setStyleSheet(themes.stylesheet(t))
        for s in (self.restore_switch, self.on_top_switch, self.autostart_switch):
            s.set_theme(t)
        themes.style_title_bar(int(self.winId()), t)

    def closeEvent(self, e) -> None:  # noqa: N802
        self.hotkey_edit.stop()
        super().closeEvent(e)
