"""The notification-area icon and its menu."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..player import State
from . import theme as themes
from .icon import app_icon


class Tray(QObject):
    """Show, Read selection, Pause/Resume, Stop, Settings and Quit.

    Left click shows the reader; middle click plays or pauses.
    """

    show_requested = Signal()
    toggle_requested = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.icon = QSystemTrayIcon(app_icon(), self)
        self.menu = QMenu()
        self.show_action = self._add("Show reader")
        self.read_action = self._add("Read selection")
        self.menu.addSeparator()
        self.play_action = self._add("Play")
        self.stop_action = self._add("Stop")
        self.menu.addSeparator()
        self.settings_action = self._add("Settings…")
        self.quit_action = self._add("Quit")
        self.show_action.triggered.connect(self.show_requested)
        self.play_action.triggered.connect(self.toggle_requested)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        self._hotkey = ""
        self._hotkey_error: str | None = None
        self.update_state(State.STOPPED, False)

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def _add(self, text: str) -> QAction:
        action = QAction(text, self.menu)
        self.menu.addAction(action)
        return action

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def apply_theme(self, t: themes.Theme) -> None:
        self.menu.setStyleSheet(themes.menu_stylesheet(t))

    def update_state(self, state: State, has_text: bool) -> None:
        playing = state in (State.PLAYING, State.LOADING)
        self.play_action.setText("Pause" if playing else "Resume" if state == State.PAUSED else "Play")
        self.play_action.setEnabled(has_text)
        self.stop_action.setEnabled(state != State.STOPPED)

    def set_hotkey(self, hotkey: str, error: str | None) -> None:
        self._hotkey, self._hotkey_error = hotkey, error
        # QMenu shows the text after a tab in the shortcut column.
        self.read_action.setText(f"Read selection\t{hotkey}" if not error else "Read selection")
        self.icon.setToolTip(f"mytts · {hotkey} reads the selection" if not error else f"mytts · {error}")

    def notify(self, title: str, message: str) -> None:
        if self.icon.isVisible() and QSystemTrayIcon.supportsMessages():
            self.icon.showMessage(title, message, app_icon(), 6000)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_requested.emit()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.toggle_requested.emit()
