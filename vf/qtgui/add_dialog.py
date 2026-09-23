"""
Add-download dialog. QLineEdit/QTextEdit come with native
Cut/Copy/Paste/Select-All context menus on right-click — no extra code.
Layout: label-above-field rows so every field shares the same full width.
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..core.config import Config
from ..i18n import t
from .icons import icon
from .theme import C


def _icon_button(icon_name, tooltip, on_click):
    """Compact square icon button used next to input fields."""
    btn = QPushButton()
    btn.setObjectName("Icon")
    btn.setFixedSize(36, 36)
    btn.setIconSize(QSize(18, 18))
    btn.setIcon(icon(icon_name, C["fg_dim"]))
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    btn.clicked.connect(on_click)
    return btn


class AddDownloadDialog(QDialog):
    """Modal dialog for adding a new download URL."""

    def __init__(self, parent, engine):
        super().__init__(parent)
        self.engine = engine
        self.result_task = None
        self.config = Config()

        self.setWindowTitle(t("dlg_add_title"))
        self.setFixedWidth(560)

        self._build_ui()

    def _field_label(self, text):
        label = QLabel(text)
        label.setObjectName("Dim")
        return label

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(6)

        title = QLabel(t("dlg_add_heading"))
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        layout.addWidget(title)
        layout.addSpacing(8)

        # ── URL (full width + compact paste button) ──
        layout.addWidget(self._field_label(t("label_url")))
        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        self._url = QLineEdit()
        self._url.setPlaceholderText("https://…")
        url_row.addWidget(self._url, 1)
        url_row.addWidget(_icon_button("paste", t("btn_paste"), self._on_paste))
        layout.addLayout(url_row)
        layout.addSpacing(6)

        # ── Save location (full width + compact browse button) ──
        layout.addWidget(self._field_label(t("label_save")))
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self._path = QLineEdit(self.config.download_dir)
        path_row.addWidget(self._path, 1)
        path_row.addWidget(_icon_button("folder", t("btn_browse"), self._on_browse))
        layout.addLayout(path_row)
        layout.addSpacing(6)

        # ── Filename (full width) ──
        layout.addWidget(self._field_label(t("label_name")))
        self._name = QLineEdit()
        layout.addWidget(self._name)
        layout.addSpacing(6)

        # ── SHA-256 checksum (full width, optional) ──
        layout.addWidget(self._field_label(t("label_checksum")))
        self._checksum = QLineEdit()
        self._checksum.setPlaceholderText("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        layout.addWidget(self._checksum)
        layout.addSpacing(6)

        # ── Cookies (full width, taller area) ──
        cookie_head = QHBoxLayout()
        cookie_head.addWidget(self._field_label(t("label_cookie")))
        cookie_head.addStretch(1)
        load_btn = QPushButton(t("btn_load_cookie_file"))
        load_btn.setCursor(Qt.PointingHandCursor)
        load_btn.clicked.connect(self._on_load_cookie_file)
        cookie_head.addWidget(load_btn)
        layout.addLayout(cookie_head)

        self._cookies = QTextEdit()
        self._cookies.setFixedHeight(110)
        self._cookies.setAcceptRichText(False)
        layout.addWidget(self._cookies)

        hint = QLabel(t("cookie_hint"))
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        import shutil
        self._ytdlp = QCheckBox(t("ytdlp_toggle"))
        self._ytdlp.setChecked(False)
        self._ytdlp.setEnabled(shutil.which("yt-dlp") is not None)
        layout.addWidget(self._ytdlp)

        layout.addSpacing(8)

        # ── Buttons: one right-aligned group, no stray gap ──
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("btn_cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        add = QPushButton(t("btn_add"))
        add.setObjectName("Accent")
        add.clicked.connect(self._on_add)
        buttons.addWidget(add)
        layout.addLayout(buttons)

        self._url.setFocus()

    # ── Handlers ───────────────────────────────────────────────

    def _on_browse(self):
        directory = QFileDialog.getExistingDirectory(
            self, t("dlg_choose_folder"), self._path.text() or self.config.download_dir
        )
        if directory:
            self._path.setText(directory)

    def _on_load_cookie_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("btn_load_cookie_file"),
            self.config.download_dir,
            "Cookie files (*.txt *.cookie);;All files (*)",
        )
        if path:
            self._cookies.setPlainText(path)

    def _on_paste(self):
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        text = (clipboard.text() or "").strip()
        if text.startswith(("http://", "https://")):
            self._url.setText(text)

    def _on_add(self):
        url = self._url.text().strip()
        if not url:
            QMessageBox.warning(self, t("dlg_add_title"), t("warn_no_url"))
            return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, t("dlg_add_title"), t("warn_bad_url"))
            return
        save_dir = self._path.text().strip()
        if not save_dir:
            QMessageBox.warning(self, t("dlg_add_title"), t("warn_no_dir"))
            return

        filename = self._name.text().strip() or None
        cookies_raw = self._cookies.toPlainText().strip() or None
        checksum = self._checksum.text().strip() or None
        try:
            self.result_task = self.engine.add_download(
                url, filename, save_dir, cookies_raw=cookies_raw,
                checksum=checksum, use_yt_dlp=self._ytdlp.isChecked(),
            )
        except Exception as e:
            QMessageBox.critical(
                self, t("error_add_title"), t("error_add", err=str(e))
            )
            return
        self.accept()
