"""Full-screen region picker with a frozen screenshot background."""

from __future__ import annotations

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QScreen,
)
from PySide6.QtWidgets import QWidget


class RegionSelector(QWidget):
    selected = Signal(object, object)  # QRect (global logical), PIL.Image
    cancelled = Signal()

    def __init__(
        self,
        screen: QScreen,
        image: Image.Image,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._screen = screen
        self._image = image.convert("RGB")
        qt_image = QImage(ImageQt(self._image)).convertToFormat(
            QImage.Format.Format_RGB888
        )
        self._background = qt_image.copy()
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._dragging = False
        self._hover = QPoint(-1, -1)
        self._done = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setWindowTitle("框选要解答的区域")

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard()

    def _selection(self) -> QRect:
        if self._origin is None or self._current is None:
            return QRect()
        return QRect(self._origin, self._current).normalized()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bounds = self.rect()
        painter.drawImage(bounds, self._background)
        painter.fillRect(bounds, QColor(3, 8, 18, 158))

        selection = self._selection()
        if not selection.isEmpty():
            source = self._source_rect(selection)
            painter.drawImage(selection, self._background, source)
            self._draw_selection(painter, selection)
        else:
            self._draw_crosshair(painter)

        self._draw_instructions(painter)
        painter.end()

    def _source_rect(self, selection: QRect) -> QRect:
        sx = self._background.width() / max(1, self.width())
        sy = self._background.height() / max(1, self.height())
        return QRect(
            round(selection.x() * sx),
            round(selection.y() * sy),
            max(1, round(selection.width() * sx)),
            max(1, round(selection.height() * sy)),
        )

    def _draw_crosshair(self, painter: QPainter) -> None:
        if not self.rect().contains(self._hover):
            return
        pen = QPen(QColor(56, 189, 248, 90), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(0, self._hover.y(), self.width(), self._hover.y())
        painter.drawLine(self._hover.x(), 0, self._hover.x(), self.height())

    def _draw_selection(self, painter: QPainter, selection: QRect) -> None:
        pen = QPen(QColor("#38bdf8"), 1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(selection.adjusted(0, 0, -1, -1))

        # Corner brackets.
        painter.setPen(QPen(QColor("#7dd3fc"), 3))
        arm = min(22, selection.width() // 3, selection.height() // 3)
        left, top, right, bottom = (
            selection.left(),
            selection.top(),
            selection.right(),
            selection.bottom(),
        )
        painter.drawLine(left, top, left + arm, top)
        painter.drawLine(left, top, left, top + arm)
        painter.drawLine(right, top, right - arm, top)
        painter.drawLine(right, top, right, top + arm)
        painter.drawLine(left, bottom, left + arm, bottom)
        painter.drawLine(left, bottom, left, bottom - arm)
        painter.drawLine(right, bottom, right - arm, bottom)
        painter.drawLine(right, bottom, right, bottom - arm)

        label = f"{selection.width()} × {selection.height()}"
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(label) + 18
        text_height = metrics.height() + 8
        label_x = min(
            max(8, selection.left()),
            max(8, self.width() - text_width - 8),
        )
        label_y = selection.top() - text_height - 8
        if label_y < 8:
            label_y = min(
                self.height() - text_height - 8, selection.bottom() + 8
            )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 15, 28, 225))
        painter.drawRoundedRect(
            QRectF(label_x, label_y, text_width, text_height), 6, 6
        )
        painter.setPen(QColor("#bae6fd"))
        painter.drawText(
            QRectF(label_x, label_y, text_width, text_height),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )

    def _draw_instructions(self, painter: QPainter) -> None:
        text = "拖动鼠标框选题目区域    ·    Esc 取消"
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 34
        height = metrics.height() + 18
        x = (self.width() - width) / 2
        y = 30
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(7, 13, 24, 225))
        painter.drawRoundedRect(QRectF(x, y, width, height), 12, 12)
        painter.setPen(QPen(QColor(148, 163, 184, 60), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(x, y, width, height), 12, 12)
        painter.setPen(QColor("#dbeafe"))
        painter.drawText(
            QRectF(x, y, width, height),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._hover = event.position().toPoint()
        if self._dragging:
            self._current = event.position().toPoint()
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._current = event.position().toPoint()
            selection = self._selection()
            if selection.width() >= 10 and selection.height() >= 10:
                self._finish(selection)
            else:
                self._origin = None
                self._current = None
                self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            selection = self._selection()
            if selection.width() >= 10 and selection.height() >= 10:
                self._finish(selection)
                return
        super().keyPressEvent(event)

    def _finish(self, selection: QRect) -> None:
        if self._done:
            return
        self._done = True
        sx = self._image.width / max(1, self.width())
        sy = self._image.height / max(1, self.height())
        crop_box = (
            max(0, round(selection.x() * sx)),
            max(0, round(selection.y() * sy)),
            min(self._image.width, round(selection.right() * sx) + 1),
            min(self._image.height, round(selection.bottom() * sy) + 1),
        )
        cropped = self._image.crop(crop_box)
        global_rect = QRect(
            self.mapToGlobal(selection.topLeft()),
            selection.size(),
        )
        self.releaseKeyboard()
        self.hide()
        self.selected.emit(global_rect, cropped)
        self.close()

    def _cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self.releaseKeyboard()
        self.hide()
        self.cancelled.emit()
        self.close()

    def closeEvent(self, event) -> None:
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        super().closeEvent(event)
