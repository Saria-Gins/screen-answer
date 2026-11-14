"""Offline OCR through the OCR engine built into Windows 10/11."""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 14_000
_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"


@dataclass
class OcrResult:
    text: str = ""
    language: str = ""
    line_count: int = 0
    duration: float = 0.0
    error: str = ""
    engine_missing: bool = False


@dataclass(frozen=True)
class OcrLanguage:
    tag: str
    display_name: str


def _import_api():
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import (
        BitmapAlphaMode,
        BitmapDecoder,
        BitmapPixelFormat,
    )
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage import FileAccessMode, StorageFile

    return {
        "Language": Language,
        "BitmapAlphaMode": BitmapAlphaMode,
        "BitmapDecoder": BitmapDecoder,
        "BitmapPixelFormat": BitmapPixelFormat,
        "OcrEngine": OcrEngine,
        "FileAccessMode": FileAccessMode,
        "StorageFile": StorageFile,
    }


def available_languages() -> list[OcrLanguage]:
    try:
        api = _import_api()
        engine_cls = api["OcrEngine"]
        result = []
        for language in engine_cls.available_recognizer_languages:
            tag = str(language.language_tag)
            try:
                display = str(language.display_name)
            except Exception:
                display = tag
            result.append(OcrLanguage(tag=tag, display_name=display or tag))
        return result
    except Exception:
        logger.exception("Windows OCR is unavailable")
        return []


def _prepare_image(path: Path) -> tuple[Path, bool]:
    """Upscale small crops, keep large ones within the engine limit."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode in {"RGBA", "LA"}:
            background = Image.new("RGB", image.size, "white")
            alpha = image.getchannel("A") if "A" in image.getbands() else None
            background.paste(image.convert("RGB"), mask=alpha)
            image = background
        else:
            image = image.convert("RGB")

        width, height = image.size
        scale = 1.0
        if width < 1200 and height < 1600:
            scale = min(2.5, max(1.0, 1400 / max(width, 1)))
        max_dimension = 8000
        if max(width, height) * scale > max_dimension:
            scale = max_dimension / max(width, height)
        if abs(scale - 1.0) < 0.05:
            return path, False
        resized = image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.LANCZOS,
        )

    temp = Path(tempfile.gettempdir()) / f"screenanswer-ocr-{time.time_ns()}.png"
    resized.save(temp, "PNG")
    return temp, True


def _tidy_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Windows OCR inserts spaces between Chinese glyphs; remove only those
    # spaces, leaving spaces inside Latin words and numbers alone.
    text = re.sub(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])", "", text)
    text = re.sub(rf"(?<=[{_CJK}])[ \t]+(?=\d)", "", text)
    text = re.sub(rf"(?<=\d)[ \t]+(?=[{_CJK}])", "", text)
    text = re.sub(r"[ \t]+(?=[，。！？；：、）】》”’])", "", text)
    text = re.sub(r"(?<=[（【《“‘])[ \t]+", "", text)
    text = re.sub(rf"(?<=[，。！？；：、])[ \t]+(?=[{_CJK}\d])", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS].rstrip() + "\n\n[内容过长，已截断]"
    return text


async def _recognize_async(path: Path, language_tag: str) -> OcrResult:
    api = _import_api()
    started = time.perf_counter()
    engine_cls = api["OcrEngine"]
    engine = None
    used_language = ""

    if language_tag:
        language = api["Language"](language_tag)
        engine = engine_cls.try_create_from_language(language)
        used_language = language_tag
    if engine is None:
        engine = engine_cls.try_create_from_user_profile_languages()
        if engine is not None:
            try:
                used_language = str(engine.recognizer_language.language_tag)
            except Exception:
                used_language = "auto"
    if engine is None:
        for language in engine_cls.available_recognizer_languages:
            candidate = engine_cls.try_create_from_language(language)
            if candidate is not None:
                engine = candidate
                used_language = str(language.language_tag)
                break
    if engine is None:
        return OcrResult(
            error="Windows 没有可用的 OCR 语言包。请在系统设置中安装中文语言包。",
            engine_missing=True,
        )

    prepared, temporary = _prepare_image(path)
    stream = None
    try:
        storage_file = await api["StorageFile"].get_file_from_path_async(
            str(prepared)
        )
        stream = await storage_file.open_async(api["FileAccessMode"].READ)
        decoder = await api["BitmapDecoder"].create_async(stream)
        bitmap = await decoder.get_software_bitmap_async(
            api["BitmapPixelFormat"].BGRA8,
            api["BitmapAlphaMode"].PREMULTIPLIED,
        )
        result = await engine.recognize_async(bitmap)
        lines = [
            line.text.strip()
            for line in result.lines
            if line.text and line.text.strip()
        ]
        text = _tidy_text("\n".join(lines))
        return OcrResult(
            text=text,
            language=used_language or "auto",
            line_count=len(lines),
            duration=time.perf_counter() - started,
        )
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if temporary:
            prepared.unlink(missing_ok=True)


def recognize_image(path: Path, language_tag: str = "") -> OcrResult:
    try:
        return asyncio.run(_recognize_async(Path(path).resolve(), language_tag))
    except Exception as exc:
        logger.exception("OCR failed")
        return OcrResult(error=f"屏幕文字识别失败：{exc}", duration=0.0)


class OcrWorker(QThread):
    done = Signal(object)

    def __init__(self, path: Path, language_tag: str = "", parent=None):
        super().__init__(parent)
        self.path = path
        self.language_tag = language_tag
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        result = recognize_image(self.path, self.language_tag)
        if not self._cancelled:
            self.done.emit(result)
