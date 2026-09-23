"""
System tray integration via QSystemTrayIcon (built into Qt).
"""

from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..i18n import t
from .theme import app_icon

TRAY_AVAILABLE = QSystemTrayIcon.isSystemTrayAvailable()


class TrayController:
    """Owns the QSystemTrayIcon and its context menu."""

    def __init__(self, window):
        self._window = window
        self._icon = QSystemTrayIcon(app_icon(), window)
        self._menu = QMenu(window)
        self._build_menu()
        self._icon.setContextMenu(self._menu)
        # Left-click / activation → show the window
        self._icon.activated.connect(self._on_activated)

    def _build_menu(self):
        self._menu.clear()

        show = self._menu.addAction(t("tray_show"))
        show.triggered.connect(self._window.show_and_raise)

        pause = self._menu.addAction(t("btn_pause_all"))
        pause.triggered.connect(self._window._on_pause_all)

        self._menu.addSeparator()

        quit_action = self._menu.addAction(t("tray_quit"))
        quit_action.triggered.connect(self._quit)

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._window.show_and_raise()

    def _quit(self):
        self._window.quit_from_tray()

    # ── Public API ─────────────────────────────────────────────

    def show(self):
        self._icon.show()

    def hide(self):
        self._icon.hide()

    def update_tooltip(self):
        active = len(self._window.engine.get_active_tasks())
        if active:
            self._icon.setToolTip(t("tray_tooltip_active", n=active))
        else:
            self._icon.setToolTip(t("tray_tooltip_idle"))

    def retranslate(self):
        self._build_menu()
        self._icon.setContextMenu(self._menu)
        self.update_tooltip()
