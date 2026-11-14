"""System-wide, user-configurable hotkeys through RegisterHotKey."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QApplication

from .shortcuts import (
    display_hotkey,
    normalize_hotkey,
    parse_hotkey,
    validate_hotkey,
)

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312

HOTKEY_CAPTURE_ID = 0x5341
HOTKEY_REGION_ID = 0x5342
HOTKEY_TOGGLE_ID = 0x5343
HOTKEY_PANIC_ID = 0x5344
_PROBE_ID = 0x6F01


class _NativeFilter(QAbstractNativeEventFilter):
    def __init__(self, owner: GlobalHotkeys):
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):
        try:
            name = bytes(event_type)
            if name in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    return self.owner._handle_hotkey(int(msg.wParam))
        except Exception:
            logger.debug("Native hotkey filter error", exc_info=True)
        return False, 0


def _user32():
    return ctypes.WinDLL("user32", use_last_error=True)


def probe_hotkey(text: str) -> bool:
    """Check whether Windows will allow a shortcut without keeping it bound."""
    spec = parse_hotkey(text)
    if spec is None:
        return False
    user32 = _user32()
    user32.RegisterHotKey.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    temporary_id = _PROBE_ID + (id(text) & 0x0F)
    if user32.RegisterHotKey(None, temporary_id, spec.modifiers, spec.vk):
        user32.UnregisterHotKey(None, temporary_id)
        return True
    return False


class GlobalHotkeys(QObject):
    capture_full = Signal()
    capture_region = Signal()
    toggle_requested = Signal()
    panic_requested = Signal()

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self.user32 = _user32()
        self.user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self.user32.RegisterHotKey.restype = wintypes.BOOL
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.UnregisterHotKey.restype = wintypes.BOOL
        self.registered: set[int] = set()
        self.failures: list[str] = []
        self.notes: list[str] = []
        self.capture_label = ""
        self.region_label = ""
        self.toggle_label = ""
        self.panic_label = ""
        self.capture_stored = ""
        self.region_stored = ""
        self.toggle_stored = ""
        self.panic_stored = ""
        self._filter = _NativeFilter(self)
        app.installNativeEventFilter(self._filter)

    def _unregister_keys(self) -> None:
        for hotkey_id in list(self.registered):
            try:
                self.user32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                pass
        self.registered.clear()

    def suspend(self) -> None:
        """Temporarily release shortcuts while the settings dialog is open."""
        self._unregister_keys()
        self.capture_label = ""
        self.region_label = ""
        self.toggle_label = ""
        self.panic_label = ""

    def _register_binding(
        self,
        hotkey_id: int,
        text: str,
        action: str,
        fallbacks: tuple[str, ...],
        label_attr: str,
        stored_attr: str,
    ) -> None:
        primary = normalize_hotkey(text)
        candidates = (primary, *fallbacks)
        seen: set[str] = set()
        primary_error = ""
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            error = validate_hotkey(candidate)
            if error:
                if candidate == primary:
                    primary_error = f"{action}：{error}"
                continue
            spec = parse_hotkey(candidate)
            if spec is None:
                continue
            if self.user32.RegisterHotKey(
                None, hotkey_id, spec.modifiers, spec.vk
            ):
                self.registered.add(hotkey_id)
                setattr(self, label_attr, spec.display)
                setattr(self, stored_attr, spec.stored)
                if candidate != primary:
                    old_display = display_hotkey(primary) or text
                    self.notes.append(
                        f"{action}快捷键 {old_display} 被占用，"
                        f"已改用 {spec.display}"
                    )
                return
            code = ctypes.get_last_error()
            logger.warning(
                "RegisterHotKey %s failed (error %s)", spec.stored, code
            )
        self.failures.append(
            primary_error
            or f"{action}快捷键未注册：所有候选组合都被占用"
        )
        setattr(self, label_attr, "")
        setattr(self, stored_attr, "")

    def register(
        self,
        capture_text: str,
        region_text: str,
        toggle_text: str,
        panic_text: str = "",
    ) -> list[str]:
        """Bind the configured shortcuts, replacing any previous bindings."""
        self._unregister_keys()
        self.failures = []
        self.notes = []
        self.capture_label = ""
        self.region_label = ""
        self.toggle_label = ""
        self.panic_label = ""
        self.capture_stored = ""
        self.region_stored = ""
        self.toggle_stored = ""
        self.panic_stored = ""

        self._register_binding(
            HOTKEY_CAPTURE_ID,
            capture_text,
            "截图",
            ("Ctrl+Alt+Shift+Q", "Ctrl+Alt+F9", "Ctrl+Shift+F9"),
            "capture_label",
            "capture_stored",
        )
        self._register_binding(
            HOTKEY_REGION_ID,
            region_text,
            "框选",
            ("Ctrl+Alt+Shift+R", "Ctrl+Alt+F10", "Ctrl+Shift+F10"),
            "region_label",
            "region_stored",
        )
        self._register_binding(
            HOTKEY_TOGGLE_ID,
            toggle_text,
            "显示/隐藏",
            ("Ctrl+Alt+Shift+H", "Ctrl+Alt+F8", "Ctrl+Shift+H"),
            "toggle_label",
            "toggle_stored",
        )
        self._register_binding(
            HOTKEY_PANIC_ID,
            panic_text,
            "一键隐身",
            ("Ctrl+Alt+Shift+X", "Ctrl+Alt+F7", "Ctrl+Shift+F7"),
            "panic_label",
            "panic_stored",
        )
        return self.failures

    @property
    def used_fallback(self) -> bool:
        return bool(self.notes)

    def _handle_hotkey(self, hotkey_id: int) -> tuple[bool, int]:
        if hotkey_id == HOTKEY_CAPTURE_ID:
            self.capture_full.emit()
            return True, 0
        if hotkey_id == HOTKEY_REGION_ID:
            self.capture_region.emit()
            return True, 0
        if hotkey_id == HOTKEY_TOGGLE_ID:
            self.toggle_requested.emit()
            return True, 0
        if hotkey_id == HOTKEY_PANIC_ID:
            self.panic_requested.emit()
            return True, 0
        return False, 0

    def unregister(self) -> None:
        self._unregister_keys()
        try:
            self.app.removeNativeEventFilter(self._filter)
        except Exception:
            pass
