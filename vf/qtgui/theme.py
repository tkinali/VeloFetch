"""
Dark theme for the Qt UI: Fusion style + a global QSS stylesheet.
"""

import os

# Same palette as the previous design, slightly deepened for Qt
C = {
    "bg_window": "#0f0f13",
    "bg_header": "#15151b",
    "bg_card": "#1a1a22",
    "bg_card_hover": "#21212b",
    "bg_input": "#22222c",
    "border": "#2b2b36",
    "border_subtle": "#232330",
    "fg": "#e8e8f2",
    "fg_dim": "#a9a9bd",
    "fg_faint": "#6d6d82",
    "accent": "#7aa2f7",
    "accent_hover": "#8ab0fa",
    "green": "#9ece6a",
    "yellow": "#e0af68",
    "red": "#f7768e",
    "teal": "#7dcfff",
    "track": "#26262f",
}

STATUS_COLORS = {
    "downloading": C["accent"],
    "pending": C["fg_faint"],
    "retrying": C["yellow"],
    "paused": C["yellow"],
    "failed": C["red"],
    "cancelled": C["fg_faint"],
    "completed": C["green"],
}

QSS = f"""
* {{
    font-family: "Inter", "Cantarell", "Segoe UI", "Noto Sans", "DejaVu Sans", "Noto Color Emoji";
    outline: none;
}}

QMainWindow, QDialog {{
    background: {C["bg_window"]};
}}

/* ── Header / status bars ── */
#HeaderBar, #StatusBar {{
    background: {C["bg_header"]};
    border: none;
}}
#HeaderBar {{ border-bottom: 1px solid {C["border_subtle"]}; }}
#StatusBar {{ border-top: 1px solid {C["border_subtle"]}; }}

QLabel {{
    color: {C["fg"]};
    background: transparent;
}}
QLabel#Brand {{
    font-size: 17px;
    font-weight: 700;
    color: {C["fg"]};
}}
QLabel#Dim {{ color: {C["fg_dim"]}; font-size: 12px; }}
QLabel#Faint {{ color: {C["fg_faint"]}; font-size: 12px; }}
QLabel#Speed {{ color: {C["teal"]}; font-size: 12px; font-weight: 600; }}
QLabel#Section {{
    color: {C["accent"]}; font-size: 11px; font-weight: 700;
    letter-spacing: 1px;
}}

/* ── Buttons ── */
QPushButton {{
    background: {C["bg_input"]};
    color: {C["fg"]};
    border: 1px solid {C["border_subtle"]};
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {C["border"]};
    border-color: {C["border"]};
}}
QPushButton:pressed {{ background: {C["bg_card_hover"]}; }}

QPushButton#Accent {{
    background: {C["accent"]};
    color: #10121a;
    border: none;
    padding: 8px 18px;
}}
QPushButton#Accent:hover {{ background: {C["accent_hover"]}; }}
QPushButton#Accent:pressed {{ background: {C["accent"]}; }}

QPushButton#Icon {{
    background: transparent;
    border: none;
    border-radius: 14px;
    padding: 4px;
    font-size: 15px;
    color: {C["fg_dim"]};
}}
QPushButton#Icon:hover {{
    background: {C["bg_input"]};
    color: {C["fg"]};
}}
QPushButton#Icon:checked {{
    background: {C["bg_input"]};
    border: 1px solid {C["border"]};
}}

/* ── Filter chips ── */
QPushButton#Chip {{
    background: {C["bg_input"]};
    color: {C["fg_dim"]};
    border: none;
    border-radius: 13px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 700;
}}
QPushButton#Chip:hover {{ color: {C["fg"]}; }}
QPushButton#Chip:checked {{
    background: {C["accent"]};
    color: #10121a;
}}

/* ── Cards ── */
QFrame#Card {{
    background: {C["bg_card"]};
    border: 1px solid {C["border_subtle"]};
    border-radius: 12px;
}}
QFrame#Card:hover {{
    background: {C["bg_card_hover"]};
    border-color: {C["border"]};
}}

/* ── Inputs ── */
QLineEdit, QTextEdit, QSpinBox, QComboBox {{
    background: {C["bg_input"]};
    color: {C["fg"]};
    border: 1px solid {C["border"]};
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 13px;
    selection-background-color: {C["accent"]};
    selection-color: #10121a;
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {C["accent"]};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent; border: none; width: 18px;
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {C["bg_input"]};
    color: {C["fg"]};
    border: 1px solid {C["border"]};
    selection-background-color: {C["border"]};
    selection-color: {C["fg"]};
}}
QComboBox::down-arrow {{
    image: url(__ARROW_DOWN__);
    width: 12px;
    height: 8px;
    margin-right: 8px;
}}
QCheckBox {{
    color: {C["fg_dim"]};
    font-size: 13px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 5px;
    border: 1px solid {C["border"]};
    background: {C["bg_input"]};
}}
QCheckBox::indicator:checked {{
    background: {C["accent"]};
    border-color: {C["accent"]};
    image: none;
}}
QCheckBox:hover {{ color: {C["fg"]}; }}

/* ── Progress bar ── */
QProgressBar {{
    background: {C["track"]};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {C["accent"]};
    border-radius: 4px;
}}

/* ── Context menus ── */
QMenu {{
    background: {C["bg_input"]};
    color: {C["fg"]};
    border: 1px solid {C["border"]};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 24px;
    border-radius: 6px;
    font-size: 13px;
}}
QMenu::item:selected {{
    background: {C["border"]};
    color: {C["fg"]};
}}
QMenu::separator {{
    height: 1px;
    background: {C["border_subtle"]};
    margin: 5px 8px;
}}

/* ── Scroll area ── */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {C["border"]};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {C["fg_faint"]}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""

# -- Bundled assets --

#: Package that ships the icon files, and the sub-directory inside it.
ASSET_PACKAGE = "vf"
ASSET_DIR = "assets"

#: Last-resort absolute locations, used when the package data is missing
#: (e.g. icons installed system-wide or by install.sh into the icon theme).
APP_ICON_PATHS = [
    "/usr/local/share/velofetch/icons/icon-128.png",
    "/usr/share/velofetch/icons/icon-128.png",
    os.path.expanduser("~/.local/share/icons/hicolor/128x128/apps/velofetch.png"),
]


def asset_path(name):
    """Return an absolute path to a bundled asset, or None when missing.

    Assets live inside the package (``vf/assets``) so a wheel ships them as
    package data. ``importlib.resources`` is tried first, which resolves them
    under ``site-packages`` for a real install; a plain source checkout falls
    back to a path relative to this module.
    """
    try:
        from importlib.resources import files as resource_files

        candidate = resource_files(ASSET_PACKAGE) / ASSET_DIR / name
        if candidate.is_file():
            resolved = str(candidate)
            if os.path.exists(resolved):
                return resolved
    except (ImportError, TypeError, OSError):
        pass

    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for root in (package_root, os.path.dirname(package_root)):
        path = os.path.join(root, ASSET_DIR, name)
        if os.path.exists(path):
            return path
    return None


def _ensure_arrow_assets():
    """Draw the combobox arrow as a real PNG (border tricks render as a
    square in QSS). Cached under ~/.cache/velofetch."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF

    cache_dir = os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "velofetch"
    )
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "arrow-down.png")
    if not os.path.exists(path):
        img = QImage(12, 8, QImage.Format_RGBA8888)
        img.fill(QColor(0, 0, 0, 0))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(C["fg_dim"]))
        painter.drawPolygon(QPolygonF([
            QPointF(1, 1.5), QPointF(11, 1.5), QPointF(6, 7),
        ]))
        painter.end()
        img.save(path)
    return path


def apply_theme(app):
    """Apply Fusion + dark QSS to the application."""
    app.setStyle("Fusion")
    app.setStyleSheet(QSS.replace("__ARROW_DOWN__", _ensure_arrow_assets()))


def app_icon():
    """Return a QIcon with all bundled sizes (crisp taskbar/tray/desktop)."""
    from PySide6.QtGui import QIcon
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        path = asset_path(f"icon-{size}.png")
        if path:
            icon.addFile(path)
    if icon.isNull():  # fallback: single file or theme lookup
        for path in APP_ICON_PATHS:
            if os.path.exists(path):
                return QIcon(path)
    return icon


def brand_pixmap(size=30):
    """Return the app logo as a pixmap for in-window display, or None."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    for name in ("logo.png", "icon-128.png"):
        path = asset_path(name)
        if not path:
            continue
        pm = QPixmap(path)
        if not pm.isNull():
            return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return None
