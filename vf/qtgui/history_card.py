"""
History card: a download-list-style card for an archived/completed record.
"""

import os

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ..i18n import t
from ..utils.helpers import format_size, format_speed, format_time
from .details_dialog import DetailsDialog, _duration, _fmt_dt
from .icons import icon
from .theme import C


class HistoryCard(QFrame):
    """Card for one completed download in the history page."""

    def __init__(self, record, on_redownload, on_remove, parent=None):
        super().__init__(parent)
        self.record = record
        self._on_redownload = on_redownload
        self._on_remove = on_remove

        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        self._build_ui()
        self._fill()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        # Badge: completed
        from .download_card import StatusBadge
        self._badge = StatusBadge()
        self._badge.set_status("completed")
        root.addWidget(self._badge, 0, Qt.AlignTop)

        # Middle: name + meta
        mid = QVBoxLayout()
        mid.setSpacing(4)

        self._name = QLabel("")
        self._name.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {C['fg']};")
        self._name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # One context menu per card: route the label's menu event to the card
        self._name.setContextMenuPolicy(Qt.PreventContextMenu)
        mid.addWidget(self._name)

        meta = QHBoxLayout()
        self._size = QLabel("")
        self._size.setObjectName("Faint")
        meta.addWidget(self._size)
        meta.addSpacing(10)
        self._date = QLabel("")
        self._date.setObjectName("Faint")
        meta.addWidget(self._date)
        meta.addSpacing(10)
        self._duration = QLabel("")
        self._duration.setObjectName("Faint")
        meta.addWidget(self._duration)
        meta.addStretch(1)
        self._speed = QLabel("")
        self._speed.setObjectName("Speed")
        meta.addWidget(self._speed)
        mid.addLayout(meta)

        root.addLayout(mid, 1)

        # Right: actions
        btns = QHBoxLayout()
        btns.setSpacing(2)

        self._folder_btn = self._icon_button("folder", t("ctx_open_folder"),
                                             C["teal"], self._open_folder)
        btns.addWidget(self._folder_btn)

        again = self._icon_button("refresh", t("redownload"),
                                  C["green"], self._redownload)
        btns.addWidget(again)

        remove = self._icon_button("remove", t("ctx_remove"),
                                   C["fg_dim"], self._remove)
        btns.addWidget(remove)

        root.addLayout(btns)

    def _icon_button(self, icon_name, tooltip, color, handler):
        btn = QPushButton()
        btn.setObjectName("Icon")
        btn.setFixedSize(30, 30)
        btn.setIconSize(QSize(16, 16))
        btn.setIcon(icon(icon_name, color))
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(handler)
        return btn

    def _fill(self):
        rec = self.record
        self._name.setText(rec.get("filename", ""))

        self._size.setText(format_size(rec.get("total_size") or 0))
        self._date.setText(_fmt_dt(rec.get("completed_at") or rec.get("created_at")))

        duration = _duration(rec)
        if duration:
            self._duration.setText(format_time(duration))
            avg = (rec.get("total_size") or 0) / duration
            self._speed.setText(format_speed(avg))
        else:
            self._duration.setText("")
            self._speed.setText("")

        # Folder button only when the file still exists
        self._file_exists = bool(rec.get("save_path")) and os.path.exists(rec["save_path"])
        self._folder_btn.setVisible(self._file_exists)

    # ── Actions ────────────────────────────────────────────────

    def _redownload(self):
        self._on_redownload(self.record)

    def _remove(self):
        self._on_remove(self.record)

    def _open_folder(self):
        from .details_dialog import open_folder
        open_folder(self.record["save_path"])

    def _copy_name(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.record.get("filename", ""))

    def _show_details(self):
        DetailsDialog(self.window(), self.record).exec()

    def _build_menu(self):
        menu = QMenu(self)

        details = menu.addAction(t("btn_details"))
        details.triggered.connect(self._show_details)

        copy_name = menu.addAction(t("ctx_copy_name"))
        copy_name.triggered.connect(self._copy_name)

        if self._file_exists:
            folder = menu.addAction(t("ctx_open_folder"))
            folder.triggered.connect(self._open_folder)

        menu.addSeparator()
        redownload = menu.addAction(t("redownload"))
        redownload.triggered.connect(self._redownload)

        remove = menu.addAction(t("ctx_remove"))
        remove.triggered.connect(self._remove)
        return menu

    def _show_menu(self, pos: QPoint):
        self._build_menu().exec(self.mapToGlobal(pos))

    def mouseDoubleClickEvent(self, _event):
        self._show_details()
