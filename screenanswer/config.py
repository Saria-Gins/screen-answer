"""Configuration, secret protection and Windows startup helpers."""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import sys
from ctypes import wintypes
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .shortcuts import (
    DEFAULT_CAPTURE_HOTKEY,
    DEFAULT_PANIC_HOTKEY,
    DEFAULT_REGION_HOTKEY,
    DEFAULT_TOGGLE_HOTKEY,
    normalize_hotkey,
    validate_hotkey,
)

logger = logging.getLogger(__name__)

APP_NAME = "ScreenAnswer"
DEFAULT_DISPLAY_NAME = "识屏解答"


def _identity_candidates() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("SCREENANSWER_IDENTITY", "").strip()
    if override:
        candidates.append(Path(override))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).with_name("identity.json"))
    candidates.append(Path(__file__).resolve().parent.parent / "identity.json")
    return candidates


def load_identity() -> dict:
    """Optional neutral identity, used by builds that must not look like 识屏解答.

    A build can ship an ``identity.json`` next to the executable::

        {"display_name": "TextInputHost", "product_name": "Text Input Host"}

    Only cosmetic strings change; settings still live in ``%APPDATA%\\ScreenAnswer``
    so existing configuration keeps working.
    """
    for path in _identity_candidates():
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Could not read identity file %s", path, exc_info=True)
            continue
        if isinstance(data, dict) and str(data.get("display_name", "")).strip():
            return {
                "display_name": str(data["display_name"]).strip(),
                "product_name": str(data.get("product_name", "")).strip(),
            }
    return {"display_name": DEFAULT_DISPLAY_NAME, "product_name": ""}


IDENTITY = load_identity()
APP_DISPLAY_NAME = IDENTITY["display_name"] or DEFAULT_DISPLAY_NAME
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
CONFIG_PATH = APP_DIR / "settings.json"
CAPTURE_DIR = Path(os.environ.get("TEMP", APP_DIR)) / "ScreenAnswer"
RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "ScreenAnswer"

DEFAULT_SYSTEM_PROMPT = """你是一位可靠的屏幕内容解答助手。用户会截取屏幕，你要读懂其中的题目、文档或界面，并给出准确、直接的答案。

要求：
1. 先判断屏幕上的核心问题或内容；文字可能来自 OCR，请容忍错别字、空格和断行。
2. 优先给出最终答案或结论；需要推导时，给出简洁、可核对的步骤。
3. 如果屏幕内容不是题目，就概括重点，并说明你能如何帮助。
4. 使用简体中文，除非题目明确要求其他语言。
5. 数学公式用清晰的文本或 Markdown 表示；不要输出无关的客套话。
6. 如果信息不足，指出缺少什么，不要编造。"""

DEFAULT_SETTINGS = {
    "api_base": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "mode": "ocr",
    "ocr_language": "",
    "capture_scope": "cursor",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "launch_at_startup": False,
    "window_x": -1,
    "window_y": -1,
    "window_width": 620,
    "window_height": 420,
    "opacity": 1.0,
    "answer_font_size": 13,
    "privacy_mode": True,
    "privacy_hide_tray": True,
    "privacy_hide_from_switcher": True,
    "hotkey_capture": DEFAULT_CAPTURE_HOTKEY,
    "hotkey_region": DEFAULT_REGION_HOTKEY,
    "hotkey_toggle": DEFAULT_TOGGLE_HOTKEY,
    "hotkey_panic": DEFAULT_PANIC_HOTKEY,
    "theme": "dark",
    "config_version": 2,
    "onboarding_done": False,
}


@dataclass
class Settings:
    api_base: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"
    mode: str = "ocr"  # "ocr" or "vision"
    ocr_language: str = ""  # empty means automatic
    capture_scope: str = "cursor"  # "cursor" or "all"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    launch_at_startup: bool = False
    window_x: int = -1
    window_y: int = -1
    window_width: int = 620
    window_height: int = 420
    opacity: float = 1.0
    answer_font_size: int = 13  # pixels
    privacy_mode: bool = True
    privacy_hide_tray: bool = True
    privacy_hide_from_switcher: bool = True
    hotkey_capture: str = DEFAULT_CAPTURE_HOTKEY
    hotkey_region: str = DEFAULT_REGION_HOTKEY
    hotkey_toggle: str = DEFAULT_TOGGLE_HOTKEY
    hotkey_panic: str = DEFAULT_PANIC_HOTKEY
    theme: str = "dark"
    config_version: int = 2
    onboarding_done: bool = False

    @property
    def endpoint(self) -> str:
        base = self.api_base.strip().rstrip("/")
        if not base:
            return ""
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        known = {f.name for f in fields(cls)}
        values = {key: value for key, value in data.items() if key in known}
        # Tolerate older or hand-edited configuration files.
        if not isinstance(values.get("system_prompt"), str) or not values["system_prompt"].strip():
            values["system_prompt"] = DEFAULT_SYSTEM_PROMPT
        if values.get("mode") not in {"ocr", "vision"}:
            values["mode"] = "ocr"
        if values.get("capture_scope") not in {"cursor", "all"}:
            values["capture_scope"] = "cursor"
        try:
            values["opacity"] = max(
                0.10, min(1.0, float(values.get("opacity", 1.0)))
            )
        except (TypeError, ValueError):
            values["opacity"] = 1.0
        # Version 1 stored answer font size in points; version 2 uses pixels.
        legacy_font_units = not data.get("config_version")
        try:
            font_size = int(values.get("answer_font_size", 13))
            if legacy_font_units and "answer_font_size" in values:
                font_size = round(font_size * 96 / 72)
            values["answer_font_size"] = max(6, min(48, font_size))
        except (TypeError, ValueError):
            values["answer_font_size"] = 13
        if not isinstance(values.get("privacy_mode"), bool):
            values["privacy_mode"] = True
        for key in ("privacy_hide_tray", "privacy_hide_from_switcher"):
            if not isinstance(values.get(key), bool):
                values[key] = True
        values["config_version"] = 2
        try:
            values["window_width"] = max(
                340, min(1400, int(values.get("window_width", 620)))
            )
            values["window_height"] = max(
                280, min(1000, int(values.get("window_height", 420)))
            )
        except (TypeError, ValueError):
            values["window_width"] = 620
            values["window_height"] = 420
        if values.get("theme") not in {"dark", "light"}:
            values["theme"] = "dark"
        for key, default in (
            ("hotkey_capture", DEFAULT_CAPTURE_HOTKEY),
            ("hotkey_region", DEFAULT_REGION_HOTKEY),
            ("hotkey_toggle", DEFAULT_TOGGLE_HOTKEY),
            ("hotkey_panic", DEFAULT_PANIC_HOTKEY),
        ):
            value = values.get(key)
            normalized = (
                normalize_hotkey(value) if isinstance(value, str) else ""
            )
            if not normalized or validate_hotkey(normalized):
                normalized = ""
            values[key] = normalized or default
        return cls(**values)


# ---------------------------------------------------------------------------
# Windows DPAPI: the API key is encrypted for the current Windows account.
# ---------------------------------------------------------------------------

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    return blob, buffer


def _dpapi_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    input_blob, _keep_input = _blob_from_bytes(data)
    output_blob = _DataBlob()
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "ScreenAnswer API key",
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    input_blob, _keep_input = _blob_from_bytes(data)
    output_blob = _DataBlob()
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def protect_secret(secret: str) -> str:
    if not secret:
        return ""
    try:
        encrypted = _dpapi_protect(secret.encode("utf-8"))
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    except Exception:  # pragma: no cover - only on unusual Windows setups
        logger.exception("DPAPI encryption failed; using local obfuscation")
        return "b64:" + base64.b64encode(secret.encode("utf-8")).decode("ascii")


def unprotect_secret(value: str) -> str:
    if not value:
        return ""
    try:
        if value.startswith("dpapi:"):
            raw = base64.b64decode(value[6:])
            return _dpapi_unprotect(raw).decode("utf-8")
        if value.startswith("b64:"):
            return base64.b64decode(value[4:]).decode("utf-8")
        # Older plaintext configs are migrated on the next save.
        return value
    except Exception:
        logger.exception("Could not decode the stored API key")
        return ""


def load_settings() -> Settings:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        return Settings()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Could not read settings; using defaults")
        return Settings()
    raw["api_key"] = unprotect_secret(str(raw.pop("api_key_enc", "") or ""))
    return Settings.from_dict(raw)


def save_settings(settings: Settings) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    data = asdict(settings)
    data.pop("api_key", None)
    data["api_key_enc"] = protect_secret(settings.api_key)
    temp_path = CONFIG_PATH.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temp_path, CONFIG_PATH)


def format_startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --background'
    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.exists():
        executable = pythonw
    script = Path(sys.argv[0]).resolve()
    return f'"{executable}" "{script}" --background'


def apply_startup(enabled: bool) -> None:
    """Enable or disable launch-at-login for the current user."""
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key, RUN_VALUE_NAME, 0, winreg.REG_SZ, format_startup_command()
            )
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass


def startup_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, RUN_VALUE_NAME)
        return True
    except OSError:
        return False

