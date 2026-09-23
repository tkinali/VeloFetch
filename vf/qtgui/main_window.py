"""
Main window: header bar, filter chips, download cards, status bar.
"""

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.config import Config
from ..core.database import Database
from ..core.downloader import DownloadEngine
from ..core.server import VeloFetchServer
from ..i18n import get_language, set_language, t
from ..utils.helpers import format_speed
from .bridge import EngineBridge
from .download_card import DownloadCard
from .history_card import HistoryCard
from .icons import icon
from .theme import C, app_icon

# Statuses of a task whose worker thread has nothing left to stop.
FINISHED_STATES = ("completed", "failed", "cancelled")

FILTERS = [
    ("all", "filter_all"),
    ("downloading", "filter_downloading"),
    ("paused", "filter_paused"),
    ("completed", "filter_completed"),
    ("failed", "filter_failed"),
]


class MainWindow(QMainWindow):
    """Main application window managing the download list and controls."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VeloFetch")
        self.resize(1000, 680)
        self.setMinimumSize(840, 520)
        self.setWindowIcon(app_icon())

        # Core
        self.config = Config()
        set_language(self.config.get("language") or "auto")
        self._built_language = get_language()
        self.db = Database(self.config.db_file)

        self._bridge = EngineBridge()
        self.engine = DownloadEngine(
            config=self.config, db=self.db,
            on_update=self._bridge.engine_on_update,
        )
        self._bridge.task_updated.connect(self._on_task_update)

        self.server = VeloFetchServer(
            self.engine, port=9876,
            on_show=self._bridge.server_on_show,
        )
        self._server_started = self.server.start()
        self._bridge.show_requested.connect(self.show_and_raise)

        # State
        self._cards = {}          # task_id -> DownloadCard
        self._history_cards = []  # HistoryCard list
        self._update_pending = True
        self._active_filter = "all"
        self._tray = None         # created lazily by tray integration

        self._build_ui()

        # Periodic refresh (engine callbacks only set a flag)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_ui)
        self._timer.start(300)

    # ── UI construction ────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_filter_bar())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_download_area())    # page 0
        self._stack.addWidget(self._build_history_page())     # page 1
        layout.addWidget(self._stack, 1)

        layout.addWidget(self._build_status_bar())

    def _build_header(self):
        header = QFrame()
        header.setObjectName("HeaderBar")
        header.setFixedHeight(62)

        row = QHBoxLayout(header)
        row.setContentsMargins(20, 10, 20, 10)
        row.setSpacing(10)

        # Logo: the app artwork, falling back to a painted "V" badge
        from .theme import brand_pixmap
        logo_pm = brand_pixmap(30)
        if logo_pm is not None:
            logo = QLabel()
            logo.setPixmap(logo_pm)
        else:
            logo = QLabel("V")
            logo.setAlignment(Qt.AlignCenter)
            logo.setStyleSheet(
                f"background: {C['accent']}; color: #10121a;"
                f"border-radius: 15px; font-weight: 800; font-size: 15px;"
            )
        logo.setFixedSize(30, 30)
        row.addWidget(logo)

        brand = QLabel("VeloFetch")
        brand.setObjectName("Brand")
        row.addWidget(brand)
        row.addStretch(1)

        self._history_btn = QPushButton()
        self._history_btn.setObjectName("Icon")
        self._history_btn.setFixedSize(34, 34)
        self._history_btn.setIconSize(QSize(18, 18))
        self._history_btn.setIcon(icon("history", C["fg_dim"]))
        self._history_btn.setToolTip(t("history_title"))
        self._history_btn.setCheckable(True)
        self._history_btn.setCursor(Qt.PointingHandCursor)
        self._history_btn.clicked.connect(self._toggle_history)
        row.addWidget(self._history_btn)

        self._settings_btn = QPushButton()
        self._settings_btn.setObjectName("Icon")
        self._settings_btn.setFixedSize(34, 34)
        self._settings_btn.setIconSize(QSize(18, 18))
        self._settings_btn.setIcon(icon("settings", C["fg_dim"]))
        self._settings_btn.setToolTip(t("dlg_settings_title"))
        self._settings_btn.setCursor(Qt.PointingHandCursor)
        self._settings_btn.clicked.connect(self._on_settings)
        row.addWidget(self._settings_btn)

        self._pause_all_btn = QPushButton(t("btn_pause_all"))
        self._pause_all_btn.clicked.connect(self._on_pause_all)
        row.addWidget(self._pause_all_btn)

        self._resume_all_btn = QPushButton(t("btn_resume_all"))
        self._resume_all_btn.clicked.connect(self._on_resume_all)
        row.addWidget(self._resume_all_btn)

        self._add_btn = QPushButton(t("btn_new_download"))
        self._add_btn.setObjectName("Accent")
        self._add_btn.clicked.connect(self._on_add_download)
        row.addWidget(self._add_btn)

        return header

    def _build_filter_bar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 12, 20, 4)
        row.setSpacing(8)

        self._chips = {}
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        for key, label_key in FILTERS:
            chip = QPushButton(t(label_key))
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setChecked(key == "all")
            chip.setCursor(Qt.PointingHandCursor)
            self._chip_group.addButton(chip)
            chip.clicked.connect(lambda _=False, k=key: self._on_filter(k))
            row.addWidget(chip)
            self._chips[key] = chip

        row.addStretch(1)

        # Search box
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("search_placeholder"))
        self._search.setFixedWidth(180)
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        row.addWidget(self._search)

        folder = os.path.basename(self.config.download_dir) or self.config.download_dir
        self._folder_label = QLabel(f"▾ {folder}")
        self._folder_label.setObjectName("Faint")
        row.addWidget(self._folder_label)

        self._clear_btn = QPushButton(t("btn_clear_finished"))
        self._clear_btn.clicked.connect(self._on_clear_finished)
        row.addWidget(self._clear_btn)

        return bar

    def _build_download_area(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self._list_host = QWidget()
        self._list_host.setObjectName("ListHost")
        self._list_host.setStyleSheet("QWidget#ListHost { background: transparent; }")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(20, 8, 22, 12)
        self._list_layout.setSpacing(10)

        self._empty_label = QLabel(
            f"\n\n{t('empty_title')}\n\n{t('empty_hint')}"
        )
        self._empty_label.setObjectName("Faint")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._list_layout.addWidget(self._empty_label)
        self._list_layout.addStretch(1)

        scroll.setWidget(self._list_host)
        return scroll

    def _build_history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(20, 0, 22, 8)
        self._history_title = QLabel(t("history_title"))
        self._history_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        head.addWidget(self._history_title)
        head.addStretch(1)
        self._history_clear_btn = QPushButton(t("history_clear"))
        self._history_clear_btn.clicked.connect(self._on_clear_history)
        head.addWidget(self._history_clear_btn)
        layout.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self._history_host = QWidget()
        self._history_host.setObjectName("HistoryHost")
        self._history_host.setStyleSheet("QWidget#HistoryHost { background: transparent; }")
        self._history_layout = QVBoxLayout(self._history_host)
        self._history_layout.setContentsMargins(20, 8, 22, 12)
        self._history_layout.setSpacing(10)

        self._history_empty = QLabel(f"\n\n{t('history_empty')}")
        self._history_empty.setObjectName("Faint")
        self._history_empty.setAlignment(Qt.AlignCenter)
        self._history_layout.addWidget(self._history_empty)
        self._history_layout.addStretch(1)

        scroll.setWidget(self._history_host)
        layout.addWidget(scroll, 1)
        return page

    def _toggle_history(self):
        opening = self._stack.currentIndex() == 0
        self._stack.setCurrentIndex(1 if opening else 0)
        self._history_btn.setChecked(opening)
        if opening:
            self._refresh_history()

    def _refresh_history(self):
        # Drop old cards (the empty label and stretch stay in place)
        for card in self._history_cards:
            card.setParent(None)
            card.deleteLater()
        self._history_cards = []

        records = self.engine.get_history()
        self._history_empty.setVisible(not records)
        for rec in records:
            card = HistoryCard(rec, self._redownload, self._delete_history_record)
            # insert before the trailing stretch
            self._history_layout.insertWidget(self._history_layout.count() - 1, card)
            self._history_cards.append(card)

    def _redownload(self, rec):
        from PySide6.QtWidgets import QMessageBox

        try:
            task = self.engine.add_download(rec["url"])
        except Exception as e:
            QMessageBox.critical(self, t("error_add_title"), t("error_add", err=str(e)))
            return
        self._stack.setCurrentIndex(0)
        self._history_btn.setChecked(False)
        self._add_card(task)
        self.engine.start_download(task)

    def _drop_task(self, task):
        """Remove a task from the engine without freezing the GUI thread.

        ``remove_download()`` joins the worker thread for up to three seconds.
        A finished download has nothing left to stop — its worker only still
        owes the desktop notification, which alone may take seconds — so the
        thread handle is dropped first and the thread retires on its own.
        """
        if task.status in FINISHED_STATES:
            self.engine._threads.pop(task.id, None)
        self.engine.remove_download(task)

    def _forget_task(self, record_id):
        """Drop the main-list task/card of a record that is leaving history.

        A completed download stays in the main list until it is archived, so
        deleting its history row must take the live task with it — otherwise
        the card lingers over a record that no longer exists.
        """
        for task in self.engine.get_all_tasks():
            if task.id == record_id:
                # Engine first: _remove_card() recomputes the status bar and
                # the chip counts, which must not still see this task.
                self._drop_task(task)
                self._remove_card(task.id)
                break

    def _delete_history_record(self, rec):
        self._forget_task(rec["id"])
        self.db.delete_history_entry(rec["id"])
        self._refresh_history()

    def _on_clear_history(self):
        for rec in self.engine.get_history():
            self._forget_task(rec["id"])
        self.db.clear_history()
        self._refresh_history()

    def _build_status_bar(self):
        status = QFrame()
        status.setObjectName("StatusBar")
        status.setFixedHeight(36)

        row = QHBoxLayout(status)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(10)

        self._speed_dot = QLabel("●")
        self._speed_dot.setStyleSheet(f"color: {C['fg_faint']}; font-size: 9px;")
        self._speed_dot.setFixedWidth(12)
        row.addWidget(self._speed_dot)

        self._speed_label = QLabel("0 B/s")
        self._speed_label.setObjectName("Speed")
        row.addWidget(self._speed_label)

        self._count_label = QLabel("")
        self._count_label.setObjectName("Faint")
        row.addWidget(self._count_label)

        row.addStretch(1)

        version = QLabel(f"v{__version__}")
        version.setObjectName("Faint")
        row.addWidget(version)

        server_text = t("ext_connected") if self._server_started else t("ext_off")
        server_color = C["green"] if self._server_started else C["yellow"]
        server = QLabel(f"● {server_text}")
        server.setStyleSheet(f"color: {server_color}; font-size: 12px;")
        row.addWidget(server)

        return status

    # ── Cards ──────────────────────────────────────────────────

    def _add_card(self, task):
        existing = self._cards.get(task.id)
        if existing is not None:
            # Never build a second card for the same task: the old one would
            # stay in the layout with nothing referencing it.
            existing.update_task(task)
            self._apply_filter()
            self._update_status_bar()
            return

        card = DownloadCard(task, self.engine)
        # The card never removes itself: the window owns every card it built.
        card.removed.connect(self._on_card_removed)
        self._cards[task.id] = card
        # The list always owns the card. A parentless widget that is shown
        # later (by the filter) would be turned into a top-level window.
        self._list_layout.insertWidget(self._list_layout.count() - 1, card)
        self._apply_filter()
        self._update_status_bar()

    def _remove_card(self, task_id):
        card = self._cards.pop(task_id, None)
        if card is not None:
            self._list_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._apply_filter()
        self._update_status_bar()

    def _on_card_removed(self, task):
        """A card's own remove action. Completed downloads stay in history."""
        if task.status == "completed":
            self.engine.archive_download(task)
        else:
            self._drop_task(task)
        self._remove_card(task.id)

    def _apply_filter(self):
        matches = 0
        for card in self._cards.values():
            visible = self._task_matches_filter(card.task)
            card.setVisible(visible)
            matches += visible
        self._update_empty_label(matches)

    def _update_empty_label(self, matches):
        """The empty state follows the VISIBLE cards, not len(self._cards):
        a filter or a search that matches nothing must say so instead of
        leaving a blank pane behind."""
        if self._cards:
            self._empty_label.setText(
                f"\n\n{t('empty_filtered_title')}\n\n{t('empty_filtered_hint')}"
            )
        else:
            self._empty_label.setText(f"\n\n{t('empty_title')}\n\n{t('empty_hint')}")
        self._empty_label.setVisible(matches == 0)

    def _task_matches_filter(self, task):
        if self._active_filter == "all":
            matched = True
        elif self._active_filter == "downloading":
            matched = task.status in ("downloading", "pending", "retrying")
        elif self._active_filter == "failed":
            matched = task.status in ("failed", "cancelled")
        else:
            matched = task.status == self._active_filter

        if not matched:
            return False
        query = self._search.text().strip().lower()
        if query:
            return query in task.filename.lower()
        return True

    # ── Slots ──────────────────────────────────────────────────

    def _on_task_update(self, _task):
        self._update_pending = True

    def _on_filter(self, key):
        self._active_filter = key
        self._apply_filter()

    def _on_add_download(self):
        from .add_dialog import AddDownloadDialog
        dlg = AddDownloadDialog(self, self.engine)
        if dlg.exec() and dlg.result_task is not None:
            self._add_card(dlg.result_task)
            self.engine.start_download(dlg.result_task)

    def _on_settings(self):
        from .settings_dialog import SettingsDialog
        SettingsDialog(self, self.config, on_save=self._on_settings_saved).exec()

    def _on_settings_saved(self):
        self.engine.apply_concurrency_limit()
        folder = os.path.basename(self.config.download_dir) or self.config.download_dir
        self._folder_label.setText(f"▾ {folder}")
        if get_language() != self._built_language:
            self._built_language = get_language()
            self._retranslate()

    def _retranslate(self):
        """Rebuild all texts after a language change."""
        self._pause_all_btn.setText(t("btn_pause_all"))
        self._resume_all_btn.setText(t("btn_resume_all"))
        self._add_btn.setText(t("btn_new_download"))
        self._clear_btn.setText(t("btn_clear_finished"))
        for (key, label_key), chip in zip(FILTERS, self._chips.values()):
            chip.setText(t(label_key))
        self._apply_filter()   # re-renders the empty state in the new language
        self._search.setPlaceholderText(t("search_placeholder"))
        self._history_btn.setToolTip(t("history_title"))
        self._settings_btn.setToolTip(t("dlg_settings_title"))
        self._history_title.setText(t("history_title"))
        self._history_clear_btn.setText(t("history_clear"))
        self._history_empty.setText(f"\n\n{t('history_empty')}")
        if self._stack.currentIndex() == 1:
            self._refresh_history()
        for card in self._cards.values():
            card.update_task(card.task)
        if self._tray is not None:
            self._tray.retranslate()
        self._update_status_bar()

    def _on_pause_all(self):
        for task in self.engine.get_active_tasks():
            self.engine.pause_download(task)

    def _on_resume_all(self):
        for task in self.engine.get_all_tasks():
            if task.status in ("paused", "pending"):
                self.engine.resume_download(task)

    def _on_clear_finished(self):
        """Completed downloads are archived to history; failures are deleted."""
        for task in list(self.engine.get_all_tasks()):
            # Engine first, card second: _remove_card() recomputes the counts.
            if task.status == "completed":
                self.engine.archive_download(task)
                self._remove_card(task.id)
            elif task.status in ("failed", "cancelled"):
                self._drop_task(task)
                self._remove_card(task.id)
        self.db.clear_finished()

    # ── Periodic refresh ───────────────────────────────────────

    def _refresh_ui(self):
        if not self._update_pending and not self.engine.get_active_tasks():
            return
        self._update_pending = False

        for task in self.engine.get_all_tasks():
            if task.id in self._cards:
                self._cards[task.id].update_task(task)
            else:
                self._add_card(task)

        current_ids = {task.id for task in self.engine.get_all_tasks()}
        for task_id in list(self._cards.keys()):
            if task_id not in current_ids:
                self._remove_card(task_id)

        self._update_status_bar()

    def _update_status_bar(self):
        all_tasks = self.engine.get_all_tasks()
        active = [task for task in all_tasks if task.status == "downloading"]

        self._speed_label.setText(format_speed(self.engine.get_total_speed()))
        self._count_label.setText(t("status_counts", active=len(active), total=len(all_tasks)))
        self._speed_dot.setStyleSheet(
            f"color: {C['green'] if active else C['fg_faint']}; font-size: 9px;"
        )

        counts = {key: 0 for key, _ in FILTERS}
        for task in all_tasks:
            if task.status in ("downloading", "pending", "retrying"):
                counts["downloading"] += 1
            elif task.status == "paused":
                counts["paused"] += 1
            elif task.status == "completed":
                counts["completed"] += 1
            elif task.status in ("failed", "cancelled"):
                counts["failed"] += 1
        counts["all"] = len(all_tasks)
        for key, chip in self._chips.items():
            chip.setText(f"{t(dict(FILTERS)[key])}  {counts.get(key, 0)}")

        if self._tray is not None:
            self._tray.update_tooltip()

    # ── Window lifecycle ───────────────────────────────────────

    def show_and_raise(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        """Close: hide to tray if enabled, otherwise pause downloads and quit."""
        from .tray import TRAY_AVAILABLE, TrayController
        if TRAY_AVAILABLE and self.config.get("minimize_to_tray", True):
            event.ignore()
            self.hide()
            if self._tray is None:
                self._tray = TrayController(self)
            self._tray.show()
            self._tray.update_tooltip()
            return

        if self._confirm_quit():
            self._shutdown()
            event.accept()
        else:
            event.ignore()

    def quit_from_tray(self):
        if self._confirm_quit():
            self._shutdown()
            from PySide6.QtWidgets import QApplication
            QApplication.quit()

    def _confirm_quit(self):
        from PySide6.QtWidgets import QMessageBox
        if not self.engine.get_active_tasks():
            return True
        box = QMessageBox(self)
        box.setWindowTitle(t("exit_title"))
        box.setText(t("exit_confirm"))
        yes = box.addButton(t("tray_quit"), QMessageBox.YesRole)
        box.addButton(t("btn_cancel"), QMessageBox.NoRole)
        box.exec()
        return box.clickedButton() is yes

    def _shutdown(self):
        """Stop everything. Active downloads are paused and saved."""
        self.engine.shutdown()
        self.server.stop()
        if self._tray is not None:
            self._tray.hide()
