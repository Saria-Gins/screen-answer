"""Parsing and validation for user-configurable global shortcuts."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

DEFAULT_CAPTURE_HOTKEY = "Ctrl+Alt+Q"
DEFAULT_REGION_HOTKEY = "Ctrl+Alt+S"
DEFAULT_TOGGLE_HOTKEY = "Ctrl+Alt+H"
DEFAULT_PANIC_HOTKEY = "Ctrl+Alt+Shift+X"

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIER_KEYS = {
    Qt.Key.Key_Control,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Shift,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
}

_SPECIAL_VK = {
    Qt.Key.Key_Space: 0x20,
    Qt.Key.Key_Tab: 0x09,
    Qt.Key.Key_Backspace: 0x08,
    Qt.Key.Key_Return: 0x0D,
    Qt.Key.Key_Enter: 0x0D,
    Qt.Key.Key_Escape: 0x1B,
    Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Delete: 0x2E,
    Qt.Key.Key_Home: 0x24,
    Qt.Key.Key_End: 0x23,
    Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_Left: 0x25,
    Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27,
    Qt.Key.Key_Down: 0x28,
    Qt.Key.Key_Pause: 0x13,
    Qt.Key.Key_Print: 0x2C,
    Qt.Key.Key_CapsLock: 0x14,
    Qt.Key.Key_NumLock: 0x90,
    Qt.Key.Key_ScrollLock: 0x91,
}


@dataclass(frozen=True)
class HotkeySpec:
    modifiers: int
    vk: int
    stored: str
    display: str


def _win_modifiers(modifiers) -> int:
    result = 0
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        result |= MOD_CONTROL
    if modifiers & Qt.KeyboardModifier.AltModifier:
        result |= MOD_ALT
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        result |= MOD_SHIFT
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        result |= MOD_WIN
    return result


def _virtual_key(key: Qt.Key) -> int | None:
    value = int(key)
    if int(Qt.Key.Key_A) <= value <= int(Qt.Key.Key_Z):
        return value
    if int(Qt.Key.Key_0) <= value <= int(Qt.Key.Key_9):
        return value
    if int(Qt.Key.Key_F1) <= value <= int(Qt.Key.Key_F24):
        return 0x70 + (value - int(Qt.Key.Key_F1))
    return _SPECIAL_VK.get(key)


def parse_hotkey(text: str) -> HotkeySpec | None:
    text = (text or "").strip()
    if not text:
        return None
    sequence = QKeySequence(text)
    if sequence.count() != 1:
        return None
    combination = sequence[0]
    key = combination.key()
    modifiers = combination.keyboardModifiers()
    if key in _MODIFIER_KEYS or int(key) == 0:
        return None
    vk = _virtual_key(key)
    if vk is None:
        return None
    win_mods = _win_modifiers(modifiers)
    if not win_mods:
        return None
    stored = sequence.toString(QKeySequence.SequenceFormat.PortableText)
    display = sequence.toString(QKeySequence.SequenceFormat.NativeText) or stored
    return HotkeySpec(
        modifiers=win_mods | MOD_NOREPEAT,
        vk=vk,
        stored=stored,
        display=display,
    )


def validate_hotkey(text: str) -> str:
    """Return a user-facing error, or an empty string when valid."""
    if not (text or "").strip():
        return "快捷键不能为空"
    sequence = QKeySequence(text.strip())
    if sequence.isEmpty():
        return "没有识别到有效的按键"
    if sequence.count() != 1:
        return "只支持单个组合键，请不要输入连续多组按键"
    combination = sequence[0]
    if combination.key() in _MODIFIER_KEYS or int(combination.key()) == 0:
        return "还需要按下一个非修饰键，例如字母、数字或 F1-F12"
    modifiers = combination.keyboardModifiers()
    modifier_count = sum(
        bool(modifiers & flag)
        for flag in (
            Qt.KeyboardModifier.ControlModifier,
            Qt.KeyboardModifier.AltModifier,
            Qt.KeyboardModifier.ShiftModifier,
            Qt.KeyboardModifier.MetaModifier,
        )
    )
    if modifier_count < 2:
        return (
            "请至少使用两个修饰键，例如 Ctrl+Alt+Q；"
            "单修饰键很容易被其他软件占用"
        )
    if _virtual_key(combination.key()) is None:
        return "这个按键暂不支持，请使用字母、数字、F1-F24 或方向键等"
    return ""


def normalize_hotkey(text: str) -> str:
    spec = parse_hotkey(text)
    return spec.stored if spec is not None else ""


def display_hotkey(text: str) -> str:
    spec = parse_hotkey(text)
    return spec.display if spec is not None else ""
