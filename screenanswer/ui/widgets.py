"""Shared small widgets and Windows visual helpers."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QToolButton, QWidget

from .icons import glyph_icon


class DragArea(QWidget):
    """Invisible title-bar area that moves its top-level window."""

    released = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._offset: QPoint | None = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = (
                event.globalPosition().toPoint() - self.window().pos()
            )
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(
                event.globalPosition().toPoint() - self._offset
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._offset is not None:
            self._offset = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.released.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class IconButton(QToolButton):
    def __init__(
        self,
        icon_name: str,
        tooltip: str,
        color: str = "#94a3b8",
        size: int = 18,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setIcon(glyph_icon(icon_name, color, size))
        self.setIconSize(QSize(size, size))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(30, 30)
        self.setAutoRaise(True)


def set_role(widget: QWidget, role: str) -> None:
    widget.setProperty("role", role)
    repolish(widget)


def set_state(widget: QWidget, name: str, value: object) -> None:
    widget.setProperty(name, value)
    repolish(widget)


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def force_topmost(widget: QWidget) -> None:
    """Raise a top-level window above other windows without activating it."""
    try:
        hwnd = int(widget.winId())
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        HWND_TOPMOST = wintypes.HWND(-1)
        flags = 0x0001 | 0x0002 | 0x0010 | 0x0040  # NOSIZE|NOMOVE|NOACTIVATE|SHOW
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
    except Exception:
        pass


def set_capture_protection(widget: QWidget, enabled: bool) -> bool:
    """Exclude a top-level window from screen capture where Windows allows it.

    Thin wrapper kept for older call sites; the actual logic (mode detection,
    read-back verification and the watchdog that re-applies it) lives in
    :mod:`screenanswer.privacy`.
    """
    from ..privacy import protect_widget, release_widget

    result = protect_widget(widget) if enabled else release_widget(widget)
    return result.active if enabled else bool(result.applied)


def hide_from_task_switcher(widget: QWidget, enabled: bool = True) -> bool:
    """Keep a window out of Alt+Tab / Win+Tab previews (see ``privacy``)."""
    from ..privacy import hide_from_task_switcher as _hide

    return _hide(widget, enabled)


def enable_dark_title_bar(widget: QWidget, dark: bool = True) -> None:
    """Ask DWM for a dark or light native caption on Windows 10/11."""
    try:
        hwnd = int(widget.winId())
        value = wintypes.BOOL(bool(dark))
        dwmapi = ctypes.windll.dwmapi
        for attribute in (20, 19):
            result = dwmapi.DwmSetWindowAttribute(
                hwnd,
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:
                break
        # Rounded corners are native on Windows 11.
        corner = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)
        )
    except Exception:
        pass
