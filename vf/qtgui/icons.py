"""
Icon provider: prefers freedesktop theme icons (native look on GNOME/KDE),
falls back to self-drawn vector icons so glyphs never depend on emoji fonts.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

# freedesktop icon-theme names (spec: https://specifications.freedesktop.org/icon-naming-spec)
THEME_NAMES = {
    "play": ["media-playback-start"],
    "pause": ["media-playback-pause"],
    "stop": ["process-stop", "window-close"],
    "folder": ["folder-open"],
    "refresh": ["view-refresh"],
    "remove": ["list-delete", "edit-delete", "list-remove"],
    "paste": ["edit-paste"],
    "settings": ["preferences-system", "settings-configure"],
    "download": ["emblem-download", "go-down"],
    "waiting": ["content-loading"],
    "complete": ["object-select", "checkbox-checked"],
    "error": ["dialog-error"],
    "cancelled": ["process-stop"],
    "clear": ["edit-clear-all", "edit-clear"],
    "history": ["document-open-recent", "view-history"],
}

SIZE = 32
_cache = {}


def icon(name, color="#a9a9bd"):
    """Return a QIcon for a logical name; themed icon if available,
    otherwise a painted vector icon in the given color."""
    key = (name, color)
    if key in _cache:
        return _cache[key]

    for theme_name in THEME_NAMES.get(name, [name]):
        themed = QIcon.fromTheme(theme_name)
        if not themed.isNull():
            _cache[key] = themed
            return themed

    painted = _paint(name, color)
    _cache[key] = painted
    return painted


def _paint(name, color):
    """Draw the fallback icon with QPainter (no font dependency)."""
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor(color))
    pen.setWidthF(2.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    if name == "play":
        path = QPainterPath(QPointF(11, 9))
        path.lineTo(23, 16)
        path.lineTo(11, 23)
        path.closeSubpath()
        p.setBrush(QColor(color))
        p.drawPath(path)

    elif name == "pause":
        p.setBrush(QColor(color))
        p.drawRect(QRectF(10, 9, 4, 14))
        p.drawRect(QRectF(18, 9, 4, 14))

    elif name in ("stop", "cancelled"):
        p.drawLine(QPointF(10, 10), QPointF(22, 22))
        p.drawLine(QPointF(22, 10), QPointF(10, 22))

    elif name == "folder":
        p.drawRoundedRect(QRectF(5, 9, 22, 15), 2, 2)
        p.drawLine(QPointF(5, 9), QPointF(11, 9))
        p.drawLine(QPointF(11, 9), QPointF(13, 12))
        p.drawLine(QPointF(13, 12), QPointF(27, 12))

    elif name == "refresh":
        p.drawArc(QRectF(8, 8, 16, 16), 30 * 16, 280 * 16)
        # arrowhead at the arc's start
        arrow = QPainterPath(QPointF(24.5, 9.5))
        arrow.lineTo(QPointF(19.5, 8.5))
        arrow.lineTo(QPointF(23.5, 14.0))
        arrow.closeSubpath()
        p.setBrush(QColor(color))
        p.drawPath(arrow)

    elif name == "remove":
        p.drawRoundedRect(QRectF(9, 7, 14, 18), 2, 2)
        p.drawLine(QPointF(12, 12), QPointF(20, 20))
        p.drawLine(QPointF(20, 12), QPointF(12, 20))

    elif name == "paste":
        p.drawRoundedRect(QRectF(7, 7, 18, 18), 2, 2)
        p.drawRoundedRect(QRectF(12, 5, 8, 5), 1, 1)
        p.drawLine(QPointF(11, 15), QPointF(21, 15))
        p.drawLine(QPointF(11, 19), QPointF(18, 19))

    elif name == "settings":
        p.drawEllipse(QRectF(11, 11, 10, 10))
        for angle_deg in (0, 45, 90, 135):
            p.save()
            p.translate(16, 16)
            p.rotate(angle_deg)
            p.drawLine(QPointF(0, -13.5), QPointF(0, -9.5))
            p.restore()

    elif name == "download":
        p.drawLine(QPointF(16, 6), QPointF(16, 20))
        p.drawLine(QPointF(10, 14), QPointF(16, 21))
        p.drawLine(QPointF(22, 14), QPointF(16, 21))
        p.drawLine(QPointF(8, 25), QPointF(24, 25))

    elif name == "waiting":
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(6, 14, 5, 5))
        p.drawEllipse(QRectF(13.5, 14, 5, 5))
        p.drawEllipse(QRectF(21, 14, 5, 5))

    elif name == "complete":
        p.drawLine(QPointF(8, 17), QPointF(14, 23))
        p.drawLine(QPointF(14, 23), QPointF(24, 9))

    elif name == "error":
        p.drawEllipse(QRectF(7, 7, 18, 18))
        p.drawLine(QPointF(16, 11), QPointF(16, 18))
        p.drawPoint(QPointF(16, 22))

    elif name == "history":
        p.drawEllipse(QRectF(8, 8, 16, 16))
        p.drawLine(QPointF(16, 12), QPointF(16, 16))
        p.drawLine(QPointF(16, 16), QPointF(20, 18))

    else:  # unknown name → dot
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(11, 11, 10, 10))

    p.end()
    return QIcon(pixmap)
