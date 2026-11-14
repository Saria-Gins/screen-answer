"""Screen capture and logical/native coordinate mapping for Windows."""

from __future__ import annotations

import ctypes
import logging
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import mss
from PIL import Image
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QCursor, QGuiApplication, QScreen

from .config import CAPTURE_DIR

logger = logging.getLogger(__name__)


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MonitorInfoEx(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _Rect),
        ("rcWork", _Rect),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


@dataclass(frozen=True)
class NativeMonitor:
    left: int
    top: int
    right: int
    bottom: int
    device: str

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def rect(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class CaptureResult:
    image: Image.Image
    rect: dict[str, int]
    path: Path
    taken_at: float


def _normalise_device_name(name: str) -> str:
    return name.lower().replace("\\", "").replace(".", "").strip()


def native_monitors() -> list[NativeMonitor]:
    """Return physical monitor rectangles (the source of truth for mss)."""
    user32 = ctypes.windll.user32
    monitors: list[NativeMonitor] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HANDLE,
        wintypes.HDC,
        ctypes.POINTER(_Rect),
        wintypes.LPARAM,
    )

    def callback(hmonitor, _hdc, _rect, _data):
        info = _MonitorInfoEx()
        info.cbSize = ctypes.sizeof(_MonitorInfoEx)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            monitors.append(
                NativeMonitor(
                    r.left, r.top, r.right, r.bottom, info.szDevice
                )
            )
        return True

    user32.EnumDisplayMonitors.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(_Rect),
        callback_type,
        wintypes.LPARAM,
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    callback = callback_type(callback)
    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        logger.warning("EnumDisplayMonitors failed")
    return monitors


def virtual_desktop_rect() -> dict[str, int]:
    monitors = native_monitors()
    if not monitors:
        with mss.mss() as sct:
            return dict(sct.monitors[0])
    left = min(m.left for m in monitors)
    top = min(m.top for m in monitors)
    right = max(m.right for m in monitors)
    bottom = max(m.bottom for m in monitors)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def monitor_at_cursor() -> NativeMonitor | None:
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    for monitor in native_monitors():
        if (
            monitor.left <= point.x < monitor.right
            and monitor.top <= point.y < monitor.bottom
        ):
            return monitor
    monitors = native_monitors()
    return monitors[0] if monitors else None


def _native_for_screen(screen: QScreen) -> NativeMonitor | None:
    wanted = _normalise_device_name(screen.name())
    for monitor in native_monitors():
        if _normalise_device_name(monitor.device) == wanted:
            return monitor
    # Some Qt/Windows combinations report a display name rather than a device.
    # Fall back to matching physical geometry after accounting for DPI.
    dpr = screen.devicePixelRatio() or 1.0
    geometry = screen.geometry()
    expected = (
        geometry.x() * dpr,
        geometry.y() * dpr,
        geometry.width() * dpr,
        geometry.height() * dpr,
    )
    for monitor in native_monitors():
        if all(
            abs(a - b) <= 3
            for a, b in zip(
                expected,
                (
                    monitor.left,
                    monitor.top,
                    monitor.width,
                    monitor.height,
                ),
            )
        ):
            return monitor
    return None


def _screen_at(point: QPoint) -> QScreen | None:
    screen = QGuiApplication.screenAt(point)
    if screen is not None:
        return screen
    for candidate in QGuiApplication.screens():
        if candidate.geometry().contains(point):
            return candidate
    return QGuiApplication.primaryScreen()


def qt_rect_to_native(rect: QRect) -> dict[str, int] | None:
    """Convert a Qt logical global rectangle to physical screen pixels."""
    if rect.width() <= 0 or rect.height() <= 0:
        return None
    top_left_screen = _screen_at(rect.topLeft())
    bottom_right_screen = _screen_at(rect.bottomRight())
    if top_left_screen is None or bottom_right_screen is None:
        return None
    tl_monitor = _native_for_screen(top_left_screen)
    br_monitor = _native_for_screen(bottom_right_screen)
    if tl_monitor is None:
        return None

    tl_geometry = top_left_screen.geometry()
    dpr = top_left_screen.devicePixelRatio() or 1.0
    rel_x = rect.left() - tl_geometry.left()
    rel_y = rect.top() - tl_geometry.top()
    native_left = tl_monitor.left + round(rel_x * dpr)
    native_top = tl_monitor.top + round(rel_y * dpr)

    if top_left_screen is bottom_right_screen or br_monitor is None:
        native_width = max(1, round(rect.width() * dpr))
        native_height = max(1, round(rect.height() * dpr))
    else:
        br_geometry = bottom_right_screen.geometry()
        br_dpr = bottom_right_screen.devicePixelRatio() or 1.0
        br_x = br_monitor.left + round(
            (rect.right() - br_geometry.left()) * br_dpr
        )
        br_y = br_monitor.top + round(
            (rect.bottom() - br_geometry.top()) * br_dpr
        )
        native_width = max(1, br_x - native_left + 1)
        native_height = max(1, br_y - native_top + 1)

    desktop = virtual_desktop_rect()
    if native_left < desktop["left"] or native_top < desktop["top"]:
        return None
    native_width = min(native_width, desktop["left"] + desktop["width"] - native_left)
    native_height = min(
        native_height, desktop["top"] + desktop["height"] - native_top
    )
    if native_width < 2 or native_height < 2:
        return None
    return {
        "left": native_left,
        "top": native_top,
        "width": native_width,
        "height": native_height,
    }


def grab(rect: dict[str, int]) -> Image.Image:
    with mss.mss() as sct:
        shot = sct.grab(rect)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def grab_fullscreen(scope: str = "cursor") -> CaptureResult:
    if scope == "all":
        rect = virtual_desktop_rect()
    else:
        monitor = monitor_at_cursor()
        rect = (
            monitor.rect
            if monitor
            else virtual_desktop_rect()
        )
    image = grab(rect)
    return CaptureResult(image=image, rect=rect, path=Path(), taken_at=time.time())


def persist_capture(image: Image.Image) -> Path:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = CAPTURE_DIR / f"capture-{int(time.time())}-{uuid.uuid4().hex[:8]}.png"
    image.save(path, "PNG")
    _cleanup_old_captures(keep=path)
    return path


def _cleanup_old_captures(keep: Path) -> None:
    try:
        cutoff = time.time() - 24 * 60 * 60
        for path in CAPTURE_DIR.glob("capture-*.png"):
            if path != keep and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not prune old captures", exc_info=True)


def clear_captures() -> None:
    """Remove cached screenshots when the application exits."""
    try:
        for path in CAPTURE_DIR.glob("capture-*.png"):
            path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not clear captures", exc_info=True)


def capture_to_png(rect: dict[str, int]) -> CaptureResult:
    image = grab(rect)
    path = persist_capture(image)
    return CaptureResult(
        image=image, rect=rect, path=path, taken_at=time.time()
    )


def current_screen_geometry() -> QRect:
    screen = QGuiApplication.screenAt(QCursor.pos())
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)
