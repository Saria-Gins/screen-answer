"""Window privacy: keep ScreenAnswer out of screenshots, recordings and switchers.

Windows offers two display-affinity modes for a top-level window:

``WDA_EXCLUDEFROMCAPTURE`` (Windows 10 2004+ / Windows 11)
    The window simply does not exist for capture APIs: Graphics Capture,
    BitBlt, DWM thumbnails used by 截图工具、微信/QQ 截图、OBS、录屏软件 and the
    Windows game bar all render the desktop *without* this window.

``WDA_MONITOR`` (Windows 7+)
    The window stays visible on screen but is replaced by a black rectangle in
    captures. Older builds only understand this mode.

Affinity is bound to an HWND, is dropped when a window handle is recreated
(window flags changes, DPI changes, some shell events) and every capture tool
behaves slightly differently.  This module therefore

* verifies each application by reading the setting back,
* re-applies it from a watchdog timer, and
* keeps the card out of Alt+Tab / Win+Tab / Aero Peek previews as well.

Everything here degrades silently: a failure never breaks the UI.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

# SetWindowDisplayAffinity modes ------------------------------------------------
WDA_NONE = 0x00
WDA_MONITOR = 0x01
WDA_EXCLUDEFROMCAPTURE = 0x11

MODE_OFF = "off"
MODE_EXCLUDE = "exclude"
MODE_MONITOR = "monitor"
MODE_UNSUPPORTED = "unsupported"

#: Modes that actually protect a window.
PROTECTIVE_MODES = (MODE_EXCLUDE, MODE_MONITOR)

_MODE_VALUES = {
    MODE_EXCLUDE: WDA_EXCLUDEFROMCAPTURE,
    MODE_MONITOR: WDA_MONITOR,
}
_VALUE_MODES = {
    WDA_NONE: MODE_OFF,
    WDA_MONITOR: MODE_MONITOR,
    WDA_EXCLUDEFROMCAPTURE: MODE_EXCLUDE,
}

MODE_LABELS = {
    MODE_EXCLUDE: "完全排除（截图/录屏里看不到）",
    MODE_MONITOR: "黑色遮挡（被截图时显示为黑块）",
    MODE_UNSUPPORTED: "不可用",
}

# Extended window styles / DWM attributes ---------------------------------------
GWLP_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
DWMWA_DISALLOW_PEEK = 11
DWMWA_EXCLUDED_FROM_PEEK = 12

WINDOWS_10_2004_BUILD = 19041

_user32 = None
_dwmapi = None


# --------------------------------------------------------------------------- API
def _win_user32():
    global _user32
    if _user32 is not None:
        return _user32
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.GetWindowDisplayAffinity.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
    for name in ("GetWindowLongPtrW", "SetWindowLongPtrW"):
        function = getattr(user32, name, None)
        if function is None:
            continue
        function.argtypes = (
            [wintypes.HWND, ctypes.c_int]
            if name.startswith("Get")
            else [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        )
        function.restype = ctypes.c_ssize_t
    _user32 = user32
    return user32


def _win_dwmapi():
    global _dwmapi
    if _dwmapi is not None:
        return _dwmapi
    try:
        _dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:  # pragma: no cover - non-Windows
        _dwmapi = None
    return _dwmapi


def is_supported_platform() -> bool:
    return sys.platform.startswith("win")


def windows_build() -> int:
    """Best-effort NT build number, 0 when unknown."""
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def windows_version_text() -> str:
    build = windows_build()
    if not build:
        return "未知系统"
    if build >= 22000:
        return f"Windows 11 (build {build})"
    if build >= WINDOWS_10_2004_BUILD:
        return f"Windows 10 / 11 (build {build})"
    return f"Windows (build {build})"


def support_mode() -> str:
    """Strongest affinity mode this Windows build can provide."""
    if not is_supported_platform():
        return MODE_UNSUPPORTED
    return MODE_EXCLUDE if windows_build() >= WINDOWS_10_2004_BUILD else MODE_MONITOR


def resolve_mode(preferred: str = "auto") -> str:
    """Map a user preference onto what the OS can actually do."""
    supported = support_mode()
    if supported == MODE_UNSUPPORTED:
        return MODE_UNSUPPORTED
    if preferred in PROTECTIVE_MODES:
        # WDA_EXCLUDEFROMCAPTURE is refused by pre-2004 builds; fall back.
        if preferred == MODE_EXCLUDE and supported == MODE_MONITOR:
            return MODE_MONITOR
        return preferred
    return supported


def widget_hwnd(widget: QWidget) -> int:
    try:
        return int(widget.winId() or 0)
    except Exception:
        return 0


# ------------------------------------------------------------------ affinity
@dataclass(frozen=True)
class Affinity:
    """Result of one display-affinity application."""

    mode: str = MODE_OFF
    value: int = WDA_NONE
    applied: bool = False
    verified: bool = False
    error: str = ""

    @property
    def active(self) -> bool:
        return self.applied and self.mode in PROTECTIVE_MODES

    @property
    def label(self) -> str:
        return MODE_LABELS.get(self.mode, self.mode)


def read_affinity(hwnd: int) -> int | None:
    """Current affinity value of an HWND, or None when it cannot be read."""
    if not hwnd or not is_supported_platform():
        return None
    try:
        value = wintypes.DWORD(0)
        if _win_user32().GetWindowDisplayAffinity(
            wintypes.HWND(hwnd), ctypes.byref(value)
        ):
            return int(value.value)
    except Exception:
        logger.debug("GetWindowDisplayAffinity failed", exc_info=True)
    return None


def apply_affinity(hwnd: int, mode: str) -> Affinity:
    """Set display affinity for an HWND and verify it took effect."""
    if mode not in _MODE_VALUES and mode != MODE_OFF:
        mode = support_mode()
    value = _MODE_VALUES.get(mode, WDA_NONE)
    if not hwnd or not is_supported_platform():
        return Affinity(mode=MODE_UNSUPPORTED, value=value, error="仅支持 Windows")
    user32 = _win_user32()
    try:
        applied = bool(
            user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), value)
        )
    except Exception as exc:  # pragma: no cover - unusual shells
        return Affinity(mode=mode, value=value, error=str(exc))
    if not applied:
        error = ctypes.WinError(ctypes.get_last_error())
        return Affinity(
            mode=mode,
            value=value,
            verified=False,
            error=getattr(error, "strerror", str(error)),
        )
    actual = read_affinity(hwnd)
    if mode == MODE_OFF:
        return Affinity(mode=MODE_OFF, value=value, applied=True, verified=True)
    return Affinity(
        mode=mode,
        value=value,
        applied=True,
        verified=actual == value,
        error="" if actual == value else "系统未确认显示保护",
    )


def protect_widget(widget: QWidget, mode: str = "auto") -> Affinity:
    """One-shot protection for a single window."""
    resolved = resolve_mode(mode)
    hwnd = widget_hwnd(widget)
    if resolved == MODE_UNSUPPORTED:
        return Affinity(mode=MODE_UNSUPPORTED)
    return apply_affinity(hwnd, resolved)


def release_widget(widget: QWidget) -> Affinity:
    return apply_affinity(widget_hwnd(widget), MODE_OFF)


def affinity_of(widget: QWidget) -> str:
    value = read_affinity(widget_hwnd(widget))
    if value is None:
        return MODE_UNSUPPORTED
    return _VALUE_MODES.get(value, MODE_OFF)


# ------------------------------------------------------- window switcher hiding
def hide_from_task_switcher(widget: QWidget, enabled: bool = True) -> bool:
    """Keep a window out of Alt+Tab / Win+Tab / Aero Peek previews.

    Qt tool windows already use ``WS_EX_TOOLWINDOW``, which most shells skip;
    clearing ``WS_EX_APPWINDOW`` and denying DWM peek closes the remaining
    paths (任务视图缩略图、Win+Tab、鼠标悬停预览).
    """
    hwnd = widget_hwnd(widget)
    if not hwnd or not is_supported_platform():
        return False
    try:
        user32 = _win_user32()
        get_style = getattr(user32, "GetWindowLongPtrW", None)
        set_style = getattr(user32, "SetWindowLongPtrW", None)
        if get_style is None or set_style is None:  # pragma: no cover - 32-bit
            get_style = user32.GetWindowLongW
            set_style = user32.SetWindowLongW
        style = int(get_style(wintypes.HWND(hwnd), GWLP_EXSTYLE) or 0)
        wanted = style | WS_EX_TOOLWINDOW if enabled else style
        wanted &= ~WS_EX_APPWINDOW
        if wanted != style:
            set_style(wintypes.HWND(hwnd), GWLP_EXSTYLE, wanted)
    except Exception:
        logger.debug("Could not adjust extended window style", exc_info=True)
        return False
    dwmapi = _win_dwmapi()
    if dwmapi is None:
        return enabled
    for attribute, flag in (
        (DWMWA_DISALLOW_PEEK, enabled),
        (DWMWA_EXCLUDED_FROM_PEEK, enabled),
    ):
        try:
            value = wintypes.BOOL(bool(flag))
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_int(attribute),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        except Exception:
            logger.debug("DwmSetWindowAttribute(%s) failed", attribute)
    return enabled


# ------------------------------------------------------------------- the guard
class PrivacyGuard(QObject):
    """Keeps every ScreenAnswer window protected while privacy mode is on.

    The guard re-applies affinity on a short timer because window handles and
    DWM state can be reset by the shell, and it covers windows created later
    (settings dialog, region picker, context menus) without extra wiring.
    """

    state_changed = Signal(bool)  # emitted when the applied state changes

    def __init__(
        self,
        parent: QObject | None = None,
        interval_ms: int = 2500,
    ):
        super().__init__(parent)
        self._enabled = False
        self._mode_pref = "auto"
        self._extra: list[QWidget] = []
        self._last_active: bool | None = None
        self._last_error = ""
        self._timer = QTimer(self)
        self._timer.setInterval(max(500, int(interval_ms)))
        self._timer.timeout.connect(self.refresh)

    # ----------------------------------------------------------------- state
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def mode(self) -> str:
        return resolve_mode(self._mode_pref)

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def active(self) -> bool:
        """True when at least one window is confirmed protected."""
        return bool(self._last_active)

    def attach(self, widget: QWidget) -> None:
        """Protect a specific window (also covered by the top-level scan)."""
        if widget not in self._extra:
            self._extra.append(widget)
        if self._enabled:
            self._protect(widget)

    def detach(self, widget: QWidget) -> None:
        if widget in self._extra:
            self._extra.remove(widget)

    def set_enabled(self, enabled: bool, apply_now: bool = True) -> None:
        enabled = bool(enabled)
        if enabled == self._enabled:
            if apply_now:
                self.refresh()
            return
        self._enabled = enabled
        if enabled:
            self._timer.start()
            if apply_now:
                self.refresh()
        else:
            self._timer.stop()
            self.release_all()

    def set_mode(self, preferred: str) -> None:
        self._mode_pref = preferred
        if self._enabled:
            self.refresh()

    def refresh(self) -> bool:
        """Apply (or drop) protection on every candidate window."""
        targets = self._targets()
        if not targets:
            return False
        if not self._enabled:
            for widget in targets:
                apply_affinity(widget_hwnd(widget), MODE_OFF)
            return True
        active = False
        error = ""
        for widget in targets:
            result = self._protect(widget)
            active = active or result.active
            if result.error and not error:
                error = result.error
        self._last_error = error
        if self._last_active != active:
            self._last_active = active
            self.state_changed.emit(active)
        return active

    def release_all(self) -> None:
        self._last_active = False
        self._last_error = ""
        for widget in self._targets():
            apply_affinity(widget_hwnd(widget), MODE_OFF)
        self.state_changed.emit(False)

    # --------------------------------------------------------------- private
    def _protect(self, widget: QWidget) -> Affinity:
        mode = self.mode
        hwnd = widget_hwnd(widget)
        if not hwnd:
            return Affinity(mode=mode, error="窗口尚未创建")
        if affinity_of(widget) == mode:
            return Affinity(
                mode=mode,
                value=_MODE_VALUES.get(mode, WDA_NONE),
                applied=True,
                verified=True,
            )
        return apply_affinity(hwnd, mode)

    def _targets(self) -> list[QWidget]:
        targets: list[QWidget] = []
        seen: set[int] = set()

        def add(widget: QWidget | None) -> None:
            if widget is None:
                return
            key = id(widget)
            if key in seen:
                return
            try:
                # 已被 deleteLater() 回收的 C++ 对象会在这里抛 RuntimeError。
                if not widget.isVisible():
                    return
                if widget.testAttribute(
                    Qt.WidgetAttribute.WA_DontShowOnScreen
                ):
                    return
            except RuntimeError:
                return
            seen.add(key)
            targets.append(widget)

        for widget in list(self._extra):
            add(widget)
        self._extra = [widget for widget in self._extra if _alive(widget)]
        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                add(widget)
        return targets


def _alive(widget: QWidget) -> bool:
    """True when the underlying C++ object still exists."""
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False
