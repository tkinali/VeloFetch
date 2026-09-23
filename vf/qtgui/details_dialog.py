"""
Download details dialog: start/finish times, duration, average speed, etc.
"""

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..i18n import t
from ..utils.helpers import format_size, format_speed, format_time
from .icons import icon
from .theme import C


def _fmt_dt(iso):
    if not iso:
        return t("detail_unknown")
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso


def _duration(record):
    started = record.get("created_at")
    finished = record.get("completed_at")
    if not started or not finished:
        return None
    try:
        delta = (
            datetime.fromisoformat(finished) - datetime.fromisoformat(started)
        ).total_seconds()
        return delta if delta > 0 else None
    except ValueError:
        return None


class DetailsDialog(QDialog):
    """Read-only detail sheet for a finished (or any) download record."""

    WIDTH = 520

    def __init__(self, parent, record):
        super().__init__(parent)
        self.record = record
        self.setWindowTitle(t("detail_title"))
        self.setFixedWidth(self.WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(8)

        title = QLabel(record.get("filename", ""))
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignTop)
        form.setSpacing(6)

        def value(text, wrap=False, selectable=True):
            label = QLabel(text)
            label.setObjectName("Dim")
            label.setWordWrap(wrap)
            if selectable:
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return label

        status_map = {
            "completed": t("status_completed"),
            "failed": t("status_failed_prefix"),
            "cancelled": t("status_cancelled"),
            "paused": t("status_paused"),
        }
        status = status_map.get(record.get("status"), record.get("status", ""))

        size = format_size(record.get("total_size") or 0)
        duration = _duration(record)
        if duration:
            duration_text = format_time(duration)
            avg = record.get("total_size") or 0
            speed_text = format_speed(avg / duration)
        else:
            duration_text = t("detail_unknown")
            speed_text = t("detail_unknown")

        form.addRow(self._dim(t("detail_status")), value(status))
        form.addRow(self._dim(t("detail_size")), value(size))
        form.addRow(self._dim(t("detail_started")), value(_fmt_dt(record.get("created_at"))))
        form.addRow(self._dim(t("detail_finished")), value(_fmt_dt(record.get("completed_at"))))
        form.addRow(self._dim(t("detail_duration")), value(duration_text))
        form.addRow(self._dim(t("detail_avg_speed")), value(speed_text))
        form.addRow(self._dim(t("detail_url")), value(record.get("url", ""), wrap=True))
        layout.addLayout(form)

        # Location row with an inline open-folder button
        loc_row = QHBoxLayout()
        loc_row.addWidget(self._dim(t("detail_location")))
        loc_row.addSpacing(10)
        path = record.get("save_path", "") or ""
        path_label = value(path, wrap=True)
        loc_row.addWidget(path_label, 1)

        save_path = record.get("save_path") or ""
        if os.path.exists(save_path):
            folder_btn = QPushButton()
            folder_btn.setObjectName("Icon")
            folder_btn.setFixedSize(32, 32)
            folder_btn.setIcon(icon("folder", C["teal"]))
            folder_btn.setToolTip(t("ctx_open_folder"))
            folder_btn.setCursor(Qt.PointingHandCursor)
            folder_btn.clicked.connect(
                lambda: open_folder(save_path)
            )
            loc_row.addWidget(folder_btn)
        layout.addLayout(loc_row)

        # Close button
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton(t("btn_cancel"))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    @staticmethod
    def _dim(text):
        label = QLabel(text)
        label.setObjectName("Dim")
        return label


def open_folder(path):
    from ..utils.helpers import open_file_manager
    open_file_manager(path)
