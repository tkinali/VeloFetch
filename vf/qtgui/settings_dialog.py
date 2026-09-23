"""
Settings dialog with a scrollable body: language, folder, engine limits,
segmented downloads, tray behavior, API token.
"""

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..i18n import available_languages, set_language, t


class SettingsDialog(QDialog):
    """Modal dialog for editing application settings."""

    def __init__(self, parent, config, on_save=None):
        super().__init__(parent)
        self.config = config
        self.on_save = on_save

        self.setWindowTitle(t("dlg_settings_title"))
        self.resize(600, 640)
        self.setMinimumSize(560, 480)

        self._build_ui()

    def _section(self, layout, key):
        label = QLabel(t(key).upper())
        label.setObjectName("Section")
        layout.addWidget(label)
        layout.addSpacing(2)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        body = QWidget()
        body.setObjectName("SettingsBody")
        body.setStyleSheet("QWidget#SettingsBody { background: transparent; }")
        form_host = QVBoxLayout(body)
        form_host.setContentsMargins(24, 20, 24, 20)
        form_host.setSpacing(10)

        title = QLabel(t("dlg_settings_title"))
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        form_host.addWidget(title)
        form_host.addSpacing(6)

        # ── Language ──
        self._section(form_host, "section_language")
        lang_row = QHBoxLayout()
        self._lang = QComboBox()
        self._lang.setEditable(False)
        choices = [("auto", t("lang_auto"))] + sorted(available_languages().items())
        self._lang_keys = [code for code, _ in choices]
        for code, label in choices:
            self._lang.addItem(label)
        current = self.config.get("language") or "auto"
        self._lang.setCurrentIndex(
            self._lang_keys.index(current) if current in self._lang_keys else 0
        )
        lang_row.addWidget(self._lang, 1)
        hint = QLabel(t("lang_hint"))
        hint.setObjectName("Faint")
        lang_row.addWidget(hint, 2)
        form_host.addLayout(lang_row)

        # ── Folder ──
        self._section(form_host, "section_folder")
        folder_row = QHBoxLayout()
        self._dir = QLineEdit(self.config.download_dir)
        browse = QPushButton(t("btn_browse"))
        browse.clicked.connect(self._on_browse)
        folder_row.addWidget(self._dir, 1)
        folder_row.addWidget(browse)
        form_host.addLayout(folder_row)

        # ── Engine ──
        self._section(form_host, "section_engine")
        engine = QFormLayout()
        engine.setSpacing(8)

        def spin(key, lo, hi):
            box = QSpinBox()
            box.setRange(lo, hi)
            box.setValue(int(self.config.get(key)))
            return box

        self._max_concurrent = spin("max_concurrent", 1, 20)
        self._segments = spin("download_segments", 1, 16)
        self._retries = spin("retry_count", 0, 20)
        self._retry_delay = spin("retry_delay", 0, 120)
        self._timeout = spin("timeout", 5, 300)
        self._speed_limit = spin("speed_limit_kbps", 0, 1000000)

        engine.addRow(QLabel(t("label_max_concurrent")), self._max_concurrent)
        engine.addRow(QLabel(t("label_segments")), self._segments)
        engine.addRow(QLabel(t("label_retry")), self._retries)
        engine.addRow(QLabel(t("label_retry_delay")), self._retry_delay)
        engine.addRow(QLabel(t("label_timeout")), self._timeout)
        engine.addRow(QLabel(t("label_speed_limit")), self._speed_limit)
        form_host.addLayout(engine)

        # ── Segmented ──
        self._section(form_host, "section_segmented")
        self._segmented = QCheckBox(t("seg_toggle"))
        self._segmented.setChecked(bool(self.config.get("segmented")))
        form_host.addWidget(self._segmented)
        seg_hint = QLabel(t("seg_hint"))
        seg_hint.setObjectName("Faint")
        seg_hint.setWordWrap(True)
        form_host.addWidget(seg_hint)

        # ── Behavior ──
        self._section(form_host, "section_behavior")
        self._tray = QCheckBox(t("tray_toggle"))
        self._tray.setChecked(bool(self.config.get("minimize_to_tray", True)))
        form_host.addWidget(self._tray)
        tray_hint = QLabel(t("tray_hint"))
        tray_hint.setObjectName("Faint")
        tray_hint.setWordWrap(True)
        form_host.addWidget(tray_hint)

        self._auto_rename = QCheckBox(t("rename_toggle"))
        self._auto_rename.setChecked(bool(self.config.get("auto_rename", True)))
        form_host.addWidget(self._auto_rename)
        rename_hint = QLabel(t("rename_hint"))
        rename_hint.setObjectName("Faint")
        rename_hint.setWordWrap(True)
        form_host.addWidget(rename_hint)

        # ── API ──
        self._section(form_host, "section_api")
        token_row = QHBoxLayout()
        self._token = QLineEdit(str(self.config.get("api_token") or ""))
        self._token.setReadOnly(True)
        self._token.setEchoMode(QLineEdit.Password)
        token_row.addWidget(self._token, 1)

        self._token_reveal = QPushButton(t("btn_token_show"))
        self._token_reveal.setCheckable(True)
        self._token_reveal.toggled.connect(self._on_toggle_token)
        token_row.addWidget(self._token_reveal)

        copy_token = QPushButton(t("btn_token_copy"))
        copy_token.clicked.connect(self._on_copy_token)
        token_row.addWidget(copy_token)

        regenerate = QPushButton(t("btn_token_regenerate"))
        regenerate.clicked.connect(self._on_regenerate_token)
        token_row.addWidget(regenerate)
        form_host.addLayout(token_row)

        api_hint = QLabel(t("api_token_hint"))
        api_hint.setObjectName("Faint")
        api_hint.setWordWrap(True)
        form_host.addWidget(api_hint)

        form_host.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # ── Buttons pinned to the bottom ──
        buttons = QHBoxLayout()
        buttons.setContentsMargins(22, 10, 22, 16)
        cancel = QPushButton(t("btn_cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        save = QPushButton(t("btn_save"))
        save.setObjectName("Accent")
        save.clicked.connect(self._on_save)
        buttons.addWidget(save)
        outer.addLayout(buttons)

    def _on_toggle_token(self, revealed):
        """Switch the token field between hidden and plain text."""
        self._token.setEchoMode(
            QLineEdit.Normal if revealed else QLineEdit.Password
        )
        self._token_reveal.setText(
            t("btn_token_hide") if revealed else t("btn_token_show")
        )

    def _on_copy_token(self):
        """Copy the current API token to the clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._token.text())

    def _on_regenerate_token(self):
        """Mint a new API token and show it in the field."""
        self._token.setText(self.config.regenerate_api_token())

    def _on_browse(self):
        directory = QFileDialog.getExistingDirectory(
            self, t("dlg_choose_folder"), self._dir.text()
        )
        if directory:
            self._dir.setText(directory)

    def _on_save(self):
        self.config.set("language", self._lang_keys[self._lang.currentIndex()])
        self.config.set("download_dir", self._dir.text().strip())
        for key, box in (
            ("max_concurrent", self._max_concurrent),
            ("download_segments", self._segments),
            ("retry_count", self._retries),
            ("retry_delay", self._retry_delay),
            ("timeout", self._timeout),
            ("speed_limit_kbps", self._speed_limit),
        ):
            self.config.set(key, box.value())
        self.config.set("segmented", self._segmented.isChecked())
        self.config.set("minimize_to_tray", self._tray.isChecked())
        self.config.set("auto_rename", self._auto_rename.isChecked())

        set_language(self._lang_keys[self._lang.currentIndex()])
        if self.on_save:
            self.on_save()
        self.accept()
