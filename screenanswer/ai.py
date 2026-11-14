"""OpenAI-compatible chat client with streaming support."""

from __future__ import annotations

import base64
import io
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps
from PySide6.QtCore import QThread, Signal

from .config import DEFAULT_SYSTEM_PROMPT, Settings

logger = logging.getLogger(__name__)


@dataclass
class AiMeta:
    elapsed: float = 0.0
    model: str = ""
    usage: dict | None = None
    finish_reason: str = ""


def image_to_data_url(path: Path, max_side: int = 1800) -> str:
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
        if max(width, height) > max_side:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=86, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def build_user_content(
    settings: Settings,
    text: str,
    image_data_url: str,
    test: bool,
    knowledge_context: str = "",
) -> str | list[dict[str, Any]]:
    if test:
        return "这是一次连接测试。请只回复：连接成功"
    reference = ""
    if knowledge_context:
        reference = (
            "【本地知识库参考】\n"
            f"{knowledge_context}\n\n"
            "请只在资料与屏幕题目明确匹配时采用；"
            "如果资料不匹配，忽略资料并以屏幕内容为准。\n\n"
        )
    instruction = (
        f"{reference}"
        "以下是从屏幕截图中识别出的文字，可能存在 OCR 错字或断行。"
        "请解答屏幕上的问题；如果这不是题目，请概括重点。\n\n"
        f"--- 屏幕文字开始 ---\n{text}\n--- 屏幕文字结束 ---"
    )
    if image_data_url:
        image_text = (
            f"{reference}"
            "这是用户当前的屏幕截图。请识别并解答其中的题目或内容。"
            "如果图片不够清晰，请说明。"
        )
        return [
            {"type": "text", "text": image_text},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    return instruction


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or error.get("code")
            if detail:
                return str(detail)
        if isinstance(payload.get("message"), str):
            return payload["message"]
    except Exception:
        pass
    text = response.text.strip()
    if text:
        return text[:500]
    return f"HTTP {response.status_code}"


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.Timeout):
        return "请求超时。请检查网络或接口地址，稍后重试。"
    if isinstance(exc, requests.exceptions.SSLError):
        return "HTTPS 证书校验失败。请检查代理或接口地址。"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "无法连接到 AI 接口。请检查网络、代理和 API 地址。"
    return f"请求失败：{exc}"


class AIWorker(QThread):
    chunk = Signal(str)
    done = Signal(str, object)
    failed = Signal(str)

    def __init__(
        self,
        settings: Settings,
        text: str = "",
        image_data_url: str = "",
        test: bool = False,
        parent=None,
        knowledge_context: str = "",
    ):
        super().__init__(parent)
        self.settings = settings
        self.text = text
        self.image_data_url = image_data_url
        self.test = test
        self.knowledge_context = knowledge_context
        self._cancelled = False
        self._response: requests.Response | None = None

    def cancel(self) -> None:
        self._cancelled = True
        response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def _payload(self) -> dict[str, Any]:
        system_prompt = (
            self.settings.system_prompt.strip() or DEFAULT_SYSTEM_PROMPT
        )
        return {
            "model": self.settings.model.strip(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": build_user_content(
                        self.settings,
                        self.text,
                        self.image_data_url,
                        self.test,
                        self.knowledge_context,
                    ),
                },
            ],
            "stream": not self.test,
            "temperature": 0.2,
            "max_tokens": 4096,
        }

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "User-Agent": "ScreenAnswer/1.8",
        }
        if self.settings.api_key.strip():
            headers["Authorization"] = f"Bearer {self.settings.api_key.strip()}"
        return headers

    def _emit_text(self, text: str, partial: str, meta: AiMeta) -> str:
        if not text:
            return partial
        try:
            self.chunk.emit(text)
        except RuntimeError:
            logger.debug("AI chunk emitted after the UI was closed")
        return partial + text

    def run(self) -> None:
        started = time.perf_counter()
        if not self.settings.endpoint:
            self.failed.emit("API 地址为空，请先在设置中填写。")
            return
        if not self.settings.model.strip():
            self.failed.emit("模型名称为空，请先在设置中填写。")
            return
        payload = self._payload()
        timeout = (10, 60) if self.test else (15, 180)
        partial = ""
        meta = AiMeta(model=self.settings.model)
        try:
            with requests.post(
                self.settings.endpoint,
                headers=self._headers(),
                json=payload,
                stream=not self.test,
                timeout=timeout,
            ) as response:
                self._response = response
                if self._cancelled:
                    return
                if response.status_code != 200:
                    self.failed.emit(
                        f"接口返回错误 {response.status_code}："
                        f"{_error_message(response)}"
                    )
                    return
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/event-stream" not in content_type:
                    data = response.json()
                    if data.get("error"):
                        message = data["error"]
                        if isinstance(message, dict):
                            message = message.get("message", str(message))
                        self.failed.emit(f"接口返回错误：{message}")
                        return
                    choices = data.get("choices") or []
                    content = ""
                    if choices:
                        content = (choices[0].get("message") or {}).get(
                            "content", ""
                        ) or ""
                    if isinstance(content, list):
                        content = "".join(
                            part.get("text", "")
                            for part in content
                            if isinstance(part, dict)
                        )
                    if not content:
                        self.failed.emit("模型没有返回内容，请查看接口配置。")
                        return
                    partial = self._emit_text(content, "", meta)
                    meta.usage = data.get("usage")
                    if choices:
                        meta.finish_reason = (
                            choices[0].get("finish_reason") or ""
                        )
                    meta.elapsed = time.perf_counter() - started
                    self.done.emit(partial, meta)
                    return

                model_returned = ""
                for raw_line in response.iter_lines(chunk_size=1024):
                    if self._cancelled:
                        break
                    if not raw_line:
                        continue
                    try:
                        line = (
                            raw_line.decode("utf-8", errors="replace")
                            if isinstance(raw_line, bytes)
                            else raw_line
                        )
                    except Exception:
                        continue
                    line = line.strip()
                    if not line or line.startswith(":") or not line.startswith("data:"):
                        continue
                    data_text = line[5:].strip()
                    if data_text == "[DONE]":
                        break
                    try:
                        event = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue
                    if event.get("error"):
                        error = event["error"]
                        if isinstance(error, dict):
                            error = error.get("message", str(error))
                        self.failed.emit(f"接口返回错误：{error}")
                        return
                    model_returned = event.get("model") or model_returned
                    if event.get("usage"):
                        meta.usage = event["usage"]
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    if choice.get("finish_reason"):
                        meta.finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or choice.get("message") or {}
                    content = delta.get("content")
                    if isinstance(content, list):
                        content = "".join(
                            part.get("text", "")
                            for part in content
                            if isinstance(part, dict)
                        )
                    if isinstance(content, str) and content:
                        partial = self._emit_text(content, partial, meta)

                if self._cancelled:
                    return
                if not partial.strip():
                    self.failed.emit(
                        "模型没有返回文本内容。请确认该模型支持当前模式"
                        "（OCR 文本 / 图片输入）。"
                    )
                    return
                meta.model = model_returned or meta.model
                meta.elapsed = time.perf_counter() - started
                self.done.emit(partial, meta)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("AI request failed")
            self.failed.emit(_friendly_error(exc))
        finally:
            self._response = None


class ConnectionTestWorker(AIWorker):
    """Small non-streaming request used by the settings dialog."""


def make_connection_test(settings: Settings) -> ConnectionTestWorker:
    return ConnectionTestWorker(settings=settings, test=True)





