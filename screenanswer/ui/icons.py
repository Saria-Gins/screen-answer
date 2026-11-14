"""Small vector icons drawn with QPainter (no image assets required)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


def _blank(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def glyph_icon(name: str, color: str = "#cbd5e1", size: int = 20) -> QIcon:
    scale = 4
    canvas = size * scale
    pixmap = _blank(canvas)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.4, size * 0.10) * scale / 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    s = canvas

    if name == "settings":
        for i, (y, knob) in enumerate(((0.30, 0.34), (0.50, 0.66), (0.70, 0.44))):
            painter.drawLine(
                QPointF(s * 0.18, s * y), QPointF(s * 0.82, s * y)
            )
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(s * knob, s * y), s * 0.075, s * 0.075)
            painter.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "close":
        painter.drawLine(
            QPointF(s * 0.28, s * 0.28), QPointF(s * 0.72, s * 0.72)
        )
        painter.drawLine(
            QPointF(s * 0.72, s * 0.28), QPointF(s * 0.28, s * 0.72)
        )
    elif name == "minimize":
        painter.drawLine(
            QPointF(s * 0.28, s * 0.58), QPointF(s * 0.72, s * 0.58)
        )
    elif name == "copy":
        painter.drawRoundedRect(
            QRectF(s * 0.32, s * 0.30, s * 0.42, s * 0.44), s * 0.05, s * 0.05
        )
        path = QPainterPath()
        path.moveTo(s * 0.26, s * 0.62)
        path.lineTo(s * 0.22, s * 0.62)
        path.quadTo(s * 0.18, s * 0.62, s * 0.18, s * 0.56)
        path.lineTo(s * 0.18, s * 0.24)
        path.quadTo(s * 0.18, s * 0.18, s * 0.24, s * 0.18)
        path.lineTo(s * 0.58, s * 0.18)
        path.quadTo(s * 0.64, s * 0.18, s * 0.64, s * 0.24)
        path.lineTo(s * 0.64, s * 0.28)
        painter.drawPath(path)
    elif name == "camera":
        painter.drawRoundedRect(
            QRectF(s * 0.14, s * 0.28, s * 0.72, s * 0.50), s * 0.08, s * 0.08
        )
        painter.drawEllipse(QPointF(s * 0.50, s * 0.53), s * 0.14, s * 0.14)
        painter.drawLine(
            QPointF(s * 0.34, s * 0.28), QPointF(s * 0.40, s * 0.19)
        )
        painter.drawLine(
            QPointF(s * 0.60, s * 0.28), QPointF(s * 0.66, s * 0.19)
        )
    elif name == "region":
        for x, y, dx, dy in (
            (0.18, 0.18, 1, 1),
            (0.82, 0.18, -1, 1),
            (0.18, 0.82, 1, -1),
            (0.82, 0.82, -1, -1),
        ):
            painter.drawLine(
                QPointF(s * x, s * y), QPointF(s * (x + 0.18 * dx), s * y)
            )
            painter.drawLine(
                QPointF(s * x, s * y), QPointF(s * x, s * (y + 0.18 * dy))
            )
    elif name == "chevron":
        painter.drawPolyline(
            [
                QPointF(s * 0.36, s * 0.30),
                QPointF(s * 0.58, s * 0.50),
                QPointF(s * 0.36, s * 0.70),
            ]
        )
    elif name == "chevron_down":
        painter.drawPolyline(
            [
                QPointF(s * 0.30, s * 0.38),
                QPointF(s * 0.50, s * 0.58),
                QPointF(s * 0.70, s * 0.38),
            ]
        )
    elif name == "eye":
        path = QPainterPath()
        path.moveTo(s * 0.14, s * 0.50)
        path.cubicTo(
            s * 0.32, s * 0.24, s * 0.68, s * 0.24, s * 0.86, s * 0.50
        )
        path.cubicTo(
            s * 0.68, s * 0.76, s * 0.32, s * 0.76, s * 0.14, s * 0.50
        )
        painter.drawPath(path)
        painter.drawEllipse(QPointF(s * 0.50, s * 0.50), s * 0.09, s * 0.09)
    elif name == "eye_off":
        path = QPainterPath()
        path.moveTo(s * 0.14, s * 0.50)
        path.cubicTo(
            s * 0.32, s * 0.24, s * 0.68, s * 0.24, s * 0.86, s * 0.50
        )
        path.cubicTo(
            s * 0.68, s * 0.76, s * 0.32, s * 0.76, s * 0.14, s * 0.50
        )
        painter.drawPath(path)
        painter.drawEllipse(QPointF(s * 0.50, s * 0.50), s * 0.09, s * 0.09)
        painter.drawLine(
            QPointF(s * 0.18, s * 0.16), QPointF(s * 0.82, s * 0.84)
        )
    elif name == "retry":
        painter.drawArc(
            QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56),
            40 * 16,
            280 * 16,
        )
        painter.drawLine(
            QPointF(s * 0.72, s * 0.16), QPointF(s * 0.72, s * 0.36)
        )
        painter.drawLine(
            QPointF(s * 0.72, s * 0.36), QPointF(s * 0.52, s * 0.36)
        )
    elif name == "pin":
        path = QPainterPath()
        path.moveTo(s * 0.40, s * 0.20)
        path.lineTo(s * 0.60, s * 0.20)
        path.lineTo(s * 0.57, s * 0.44)
        path.lineTo(s * 0.68, s * 0.54)
        path.lineTo(s * 0.32, s * 0.54)
        path.lineTo(s * 0.43, s * 0.44)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(
            QPointF(s * 0.50, s * 0.54), QPointF(s * 0.50, s * 0.82)
        )
    else:
        painter.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.2, s * 0.2)

    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_app_pixmap(size))
    return icon


def _app_pixmap(size: int) -> QPixmap:
    pixmap = _blank(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = float(size)
    gradient = QLinearGradient(0, 0, s, s)
    gradient.setColorAt(0.0, QColor("#102a43"))
    gradient.setColorAt(1.0, QColor("#07111f"))
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor(56, 189, 248, 200), max(1.0, s * 0.035)))
    painter.drawRoundedRect(
        QRectF(s * 0.06, s * 0.06, s * 0.88, s * 0.88),
        s * 0.22,
        s * 0.22,
    )

    # Scan-frame corners.
    pen = QPen(QColor("#38bdf8"), max(1.4, s * 0.065))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    inset = s * 0.26
    arm = s * 0.15
    painter.drawLine(QPointF(inset, inset), QPointF(inset + arm, inset))
    painter.drawLine(QPointF(inset, inset), QPointF(inset, inset + arm))
    painter.drawLine(
        QPointF(s - inset, inset), QPointF(s - inset - arm, inset)
    )
    painter.drawLine(
        QPointF(s - inset, inset), QPointF(s - inset, inset + arm)
    )
    painter.drawLine(
        QPointF(inset, s - inset), QPointF(inset + arm, s - inset)
    )
    painter.drawLine(
        QPointF(inset, s - inset), QPointF(inset, s - inset - arm)
    )
    painter.drawLine(
        QPointF(s - inset, s - inset),
        QPointF(s - inset - arm, s - inset),
    )
    painter.drawLine(
        QPointF(s - inset, s - inset),
        QPointF(s - inset, s - inset - arm),
    )

    # Four-point spark in the middle.
    center = s / 2
    outer = s * 0.16
    inner = s * 0.045
    path = QPainterPath()
    path.moveTo(center, center - outer)
    path.quadTo(center + inner, center - inner, center + outer, center)
    path.quadTo(center + inner, center + inner, center, center + outer)
    path.quadTo(center - inner, center + inner, center - outer, center)
    path.quadTo(center - inner, center - inner, center, center - outer)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#e0f2fe"))
    painter.drawPath(path)

    painter.end()
    return pixmap
