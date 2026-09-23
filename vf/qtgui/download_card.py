"""
A download card: rounded surface, animated progress bar, per-state actions.
"""

from PySide6.QtCore import QEasingCurve, QPoint, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)

from ..i18n import t
from ..utils.helpers import format_eta, format_size, format_speed
from .icons import icon
from .theme import STATUS_COLORS, C


class StatusBadge(QToolButton):
    """Colored ring with a status icon (theme icon or painted fallback)."""

    ICONS = {
        "pending": "waiting",
        "downloading": "download",
        "paused": "pause",
        "completed": "complete",
        "failed": "error",
        "cancelled": "cancelled",
        "retrying": "refresh",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setIconSize(QSize(18, 18))
        self._status = "pending"

    def set_status(self, status):
        self._status = status
        color = STATUS_COLORS.get(status, C["accent"])
        self.setIcon(icon(self.ICONS.get(status, "download"), color))
        self.setStyleSheet(
            f"QToolButton {{"
            f"background: transparent; border: 1.5px solid {color};"
            f"border-radius: 20px;"
            f"}}"
            f"QToolButton:hover {{ background: rgba(255,255,255,0.04); }}"
        )


class DownloadCard(QFrame):
    """Card representing a single download."""

    # The user asked for this card to go away. A card must never take itself
    # out of the engine and delete itself: its owner keeps a reference to it
    # (MainWindow._cards) and would be left with a dead C++ object.
    removed = Signal(object)

    def __init__(self, task, engine, parent=None):
        super().__init__(parent)
        self.task = task
        self.engine = engine

        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._build_ui()

        # Smoothly animated progress value (needs _bar from _build_ui)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._bar.setValue)

        # Right-click context menu
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self.update_task(task)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        # Left: status badge
        self._badge = StatusBadge()
        root.addWidget(self._badge, 0, Qt.AlignTop)

        # Middle: name / progress / stats
        mid = QVBoxLayout()
        mid.setSpacing(4)

        name_row = QHBoxLayout()
        self._name = QLabel(self.task.filename)
        self._name.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {C['fg']};"
        )
        self._name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # One context menu per card: route the label's menu event to the card
        self._name.setContextMenuPolicy(Qt.PreventContextMenu)
        name_row.addWidget(self._name, 1)

        self._percent = QLabel("")
        self._percent.setStyleSheet(
            f"color: {C['fg']}; font-size: 13px; font-weight: 700;"
        )
        name_row.addWidget(self._percent, 0, Qt.AlignRight)
        mid.addLayout(name_row)

        self._bar = QProgressBar()
        self._bar.setFixedHeight(8)
        self._bar.setRange(0, 1000)
        mid.addWidget(self._bar)

        stats = QHBoxLayout()
        self._size = QLabel("")
        self._size.setObjectName("Faint")
        stats.addWidget(self._size)
        stats.addSpacing(10)
        self._speed = QLabel("")
        self._speed.setObjectName("Speed")
        stats.addWidget(self._speed)
        stats.addSpacing(10)
        self._eta = QLabel("")
        self._eta.setObjectName("Faint")
        stats.addWidget(self._eta)
        stats.addStretch(1)
        self._status = QLabel("")
        self._status.setObjectName("Faint")
        stats.addWidget(self._status, 0, Qt.AlignRight)
        mid.addLayout(stats)

        root.addLayout(mid, 1)

        # Right: action buttons
        self._btns = QHBoxLayout()
        self._btns.setSpacing(2)
        root.addLayout(self._btns)

        self._buttons = {}
        for name, icon_name, tip_key, handler in (
            ("resume", "play", "status_pending", self._on_resume),
            ("pause", "pause", "btn_pause_all", self._on_pause),
            ("cancel", "stop", "status_cancelled", self._on_cancel),
            ("folder", "folder", "ctx_open_folder", self._on_open_folder),
            ("retry", "refresh", "ctx_retry", self._on_resume),
            ("remove", "remove", "ctx_remove", self._on_remove),
        ):
            btn = QPushButton()
            btn.setObjectName("Icon")
            btn.setFixedSize(30, 30)
            btn.setIconSize(QSize(16, 16))
            btn.setIcon(icon(icon_name, C["fg_dim"]))
            btn.setToolTip(t(tip_key))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(handler)
            self._buttons[name] = btn
            self._btns.addWidget(btn)

    # ── Refresh ────────────────────────────────────────────────

    def update_task(self, task):
        self.task = task
        status = task.status

        # Name + percent
        name = task.filename
        metrics = self._name.fontMetrics()
        if metrics.horizontalAdvance(name) > 460:
            name = metrics.elidedText(name, Qt.ElideMiddle, 460)
        self._name.setText(name)
        self._percent.setText(f"{task.progress:.1f}%" if task.total_size > 0 else "")

        # Badge + progress color / mode
        self._badge.set_status(status)
        color = STATUS_COLORS.get(status, C["accent"])
        self._bar.setStyleSheet(
            f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
        )
        self._bar.setTextVisible(False)
        if status == "completed":
            self._set_bar(1000)
        elif task.total_size > 0:
            self._set_bar(int(task.progress * 10))
        else:
            # Unknown size: animated indeterminate mode
            self._bar.setRange(0, 0)

        # Stats line
        downloaded = format_size(task.downloaded_size)
        total = format_size(task.total_size) if task.total_size > 0 else "?"
        self._size.setText(f"{downloaded} / {total}")

        if status == "downloading":
            self._speed.setText(format_speed(task.current_speed))
            self._eta.setText(format_eta(task))
            self._status.setText("")
        elif status == "completed":
            self._speed.setText(t("status_completed"))
            self._eta.setText("")
        else:
            self._speed.setText("")
            self._eta.setText("")

        # Checksum verdict (only after a verified download)
        if status == "completed" and self.task.checksum is not None:
            if self.task.checksum_ok is True:
                self._speed.setText(t("checksum_ok"))
                self._speed.setStyleSheet(f"color: {C['green']}; font-size: 12px; font-weight: 600;")
            elif self.task.checksum_ok is False:
                self._speed.setText(t("checksum_bad"))
                self._speed.setStyleSheet(f"color: {C['red']}; font-size: 12px; font-weight: 700;")

        # Status text
        if status == "failed":
            text = task.error_message or t("status_failed_prefix")
            self._status.setStyleSheet(f"color: {C['red']}; font-size: 12px;")
        elif status == "retrying":
            text = task.error_message or t("status_retrying")
            self._status.setStyleSheet(f"color: {C['fg_faint']}; font-size: 12px;")
        else:
            text = {
                "pending": t("status_pending"),
                "paused": t("status_paused"),
                "cancelled": t("status_cancelled"),
            }.get(status, "")
            self._status.setStyleSheet(f"color: {C['fg_faint']}; font-size: 12px;")
        self._status.setText(text)

        # Buttons by state
        shown = {
            "downloading": ("pause", "cancel", "remove"),
            "retrying": ("pause", "cancel", "remove"),
            "paused": ("resume", "cancel", "remove"),
            "completed": ("folder", "remove"),
            "failed": ("retry", "remove"),
            "cancelled": ("retry", "remove"),
            "pending": ("resume", "remove"),
        }.get(status, ("resume", "remove"))
        for name, btn in self._buttons.items():
            btn.setVisible(name in shown)

    def _set_bar(self, value):
        self._bar.setRange(0, 1000)
        current = self._bar.value()
        if abs(value - current) > 250:  # big jumps snap instantly
            self._bar.setValue(value)
        else:
            self._anim.stop()
            self._anim.setStartValue(current)
            self._anim.setEndValue(value)
            self._anim.start()

    # ── Actions ────────────────────────────────────────────────

    def _on_pause(self):
        self.engine.pause_download(self.task)

    def _on_resume(self):
        if self.task.status in ("failed", "cancelled"):
            self.engine.retry_download(self.task)
        else:
            self.engine.resume_download(self.task)

    def _on_cancel(self):
        self.engine.cancel_download(self.task)

    def _on_open_folder(self):
        from ..utils.helpers import open_file_manager
        open_file_manager(self.task.save_path)

    def _on_open_file(self):
        import os

        from ..utils.helpers import open_file
        if os.path.exists(self.task.save_path):
            open_file(self.task.save_path)

    def _on_copy_url(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.task.url)

    def _on_copy_name(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.task.filename)

    def _build_context_menu(self):
        import os
        menu = QMenu(self)
        menu.setCursor(Qt.PointingHandCursor)

        copy_name = menu.addAction(t("ctx_copy_name"))
        copy_name.triggered.connect(self._on_copy_name)

        copy_url = menu.addAction(t("ctx_copy_url"))
        copy_url.triggered.connect(self._on_copy_url)

        if self.task.status == "completed" and os.path.exists(self.task.save_path):
            open_file = menu.addAction(t("ctx_open_file"))
            open_file.triggered.connect(self._on_open_file)

        open_folder = menu.addAction(t("ctx_open_folder"))
        open_folder.triggered.connect(self._on_open_folder)

        if self.task.status in ("failed", "cancelled", "paused"):
            menu.addSeparator()
            retry = menu.addAction(t("ctx_retry"))
            retry.triggered.connect(self._on_resume)

        menu.addSeparator()
        remove = menu.addAction(t("ctx_remove"))
        remove.triggered.connect(self._on_remove)
        return menu

    def _show_context_menu(self, pos: QPoint):
        self._build_context_menu().exec(self.mapToGlobal(pos))

    def _on_remove(self):
        # The owner archives/removes the task and tears the widget down.
        self.removed.emit(self.task)
