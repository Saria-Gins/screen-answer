from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from screenanswer.ai import build_user_content
from screenanswer.config import (
    DEFAULT_SYSTEM_PROMPT,
    Settings,
    load_identity,
    protect_secret,
    unprotect_secret,
)
from screenanswer.knowledge import KnowledgeBase, _query_trigrams  # noqa: F401
from screenanswer.ocr import _tidy_text as tidy_ocr_text
from screenanswer.privacy import (
    MODE_EXCLUDE,
    MODE_MONITOR,
    MODE_UNSUPPORTED,
    PROTECTIVE_MODES,
    apply_affinity,
    resolve_mode,
    support_mode,
    windows_build,
)
from screenanswer.shortcuts import (
    DEFAULT_PANIC_HOTKEY,
    parse_hotkey,
    validate_hotkey,
)

DOCX_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}</w:body>
</w:document>"""


def _make_docx(path: Path, paragraphs: list[str]) -> None:
    """Write a minimal .docx that the stdlib parser understands."""
    body = "".join(
        "<w:p><w:r><w:t>{}</w:t></w:r></w:p>".format(
            line.replace("&", "&amp;").replace("<", "&lt;")
        )
        for line in paragraphs
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", DOCX_XML.format(body=body))


def test_endpoint() -> None:
    assert (
        Settings(api_base="https://api.deepseek.com/v1").endpoint
        == "https://api.deepseek.com/v1/chat/completions"
    )
    assert (
        Settings(api_base="https://x.test/v1/").endpoint
        == "https://x.test/v1/chat/completions"
    )
    assert (
        Settings(
            api_base="http://localhost:1234/v1/chat/completions"
        ).endpoint
        == "http://localhost:1234/v1/chat/completions"
    )


def test_settings_roundtrip() -> None:
    settings = Settings.from_dict(
        {
            "api_base": "http://127.0.0.1:1234/v1",
            "api_key": "secret",
            "mode": "vision",
            "capture_scope": "all",
            "system_prompt": "",
            "unknown": "ignored",
        }
    )
    assert settings.mode == "vision"
    assert settings.capture_scope == "all"
    assert settings.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert settings.api_key == "secret"


def test_secret_protection() -> None:
    encrypted = protect_secret("sk-test-123")
    assert encrypted.startswith(("dpapi:", "b64:"))
    assert "sk-test-123" not in encrypted
    assert unprotect_secret(encrypted) == "sk-test-123"
    assert unprotect_secret("") == ""


def test_identity_defaults() -> None:
    identity = load_identity()
    assert identity["display_name"]


def test_ocr_tidy() -> None:
    raw = "第 1 题 求 下 列 方 程 的 解\n已知 3x + 5 = 20 ， 求 x 的 值。\n\n\n"
    text = tidy_ocr_text(raw)
    assert "第1题求下列方程的解" in text
    assert "20，求" in text
    assert text.count("\n\n") == 0


def test_vision_content() -> None:
    settings = Settings(mode="vision")
    content = build_user_content(
        settings, "text", "data:image/jpeg;base64,AAAA", False
    )
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg")


def test_knowledge_base(tmp_path: Path) -> None:
    _make_docx(
        tmp_path / "题库.docx",
        [
            "第1题",
            "下列哪一项是水的化学式？",
            "A．H2O",
            "B．CO2",
            "【参考答案】A",
            "【解析】水由两个氢原子和一个氧原子组成。",
            "第2题",
            "中国的首都是哪座城市？",
            "A．北京",
            "B．上海",
            "【参考答案】A",
        ],
    )
    (tmp_path / "资料.md").write_text(
        "# 速记\n\n"
        "数据结构的栈和队列区别在于：栈是后进先出，队列是先进先出。\n"
        "栈只允许在表尾插入和删除元素，队列则在表尾插入、表头删除。\n"
        "实际使用时，递归调用依赖栈，而任务排队、打印队列依赖队列。\n",
        encoding="utf-8",
    )
    kb = KnowledgeBase(directory=tmp_path)
    stats = kb.load()
    assert stats.files == 2
    assert stats.entries >= 3
    assert kb.search("水的化学式是什么")
    context = kb.build_context("下列哪一项是水的化学式？")
    assert "本地题库" in context
    # 无关的屏幕文字不应该拿到任何资料
    assert kb.build_context("今天天气不错，适合出去散步。") == ""
    # 长资料片段靠三字短语也能命中
    assert kb.search("说说栈和队列的区别")


def test_hotkeys_and_appearance_limits() -> None:
    assert validate_hotkey("Ctrl+Alt+Q") == ""
    assert validate_hotkey("A") != ""
    assert validate_hotkey("Shift+Q") != ""
    assert validate_hotkey("Ctrl+Alt") != ""
    assert parse_hotkey("Ctrl+Shift+F9") is not None
    settings = Settings.from_dict(
        {
            "opacity": 0.1,
            "window_width": 100,
            "window_height": 9999,
            "answer_font_size": 99,
            "privacy_mode": "yes",
            "hotkey_capture": "",
        }
    )
    assert settings.opacity == 0.10
    assert settings.window_width == 340
    assert settings.window_height == 1000
    assert settings.answer_font_size == 48
    assert settings.privacy_mode is True
    assert settings.privacy_hide_tray is True
    assert settings.privacy_hide_from_switcher is True
    assert settings.hotkey_capture == "Ctrl+Alt+Q"
    assert settings.hotkey_region == "Ctrl+Alt+S"
    assert settings.hotkey_toggle == "Ctrl+Alt+H"
    assert settings.hotkey_panic == DEFAULT_PANIC_HOTKEY
    assert settings.theme == "dark"
    weak = Settings.from_dict({"hotkey_capture": "Shift+Q"})
    assert weak.hotkey_capture == "Ctrl+Alt+Q"
    light = Settings.from_dict({"theme": "light"})
    assert light.theme == "light"
    assert Settings.from_dict({"theme": "invalid"}).theme == "dark"


def test_privacy_helpers() -> None:
    assert support_mode() in {MODE_EXCLUDE, MODE_MONITOR, MODE_UNSUPPORTED}
    assert windows_build() >= 0
    if support_mode() == MODE_UNSUPPORTED:
        assert resolve_mode("auto") == MODE_UNSUPPORTED
    else:
        assert resolve_mode("auto") in PROTECTIVE_MODES
        if windows_build() < 19041:
            assert resolve_mode(MODE_EXCLUDE) == MODE_MONITOR
        else:
            assert resolve_mode(MODE_EXCLUDE) == MODE_EXCLUDE
        assert resolve_mode(MODE_MONITOR) == MODE_MONITOR
    result = apply_affinity(0, MODE_EXCLUDE)
    assert result.active is False
    assert validate_hotkey(DEFAULT_PANIC_HOTKEY) == ""
    assert parse_hotkey(DEFAULT_PANIC_HOTKEY) is not None


if __name__ == "__main__":
    import tempfile

    test_endpoint()
    test_settings_roundtrip()
    test_secret_protection()
    test_identity_defaults()
    test_ocr_tidy()
    test_vision_content()
    with tempfile.TemporaryDirectory() as folder:
        test_knowledge_base(Path(folder))
    test_hotkeys_and_appearance_limits()
    test_privacy_helpers()
    print("all core tests passed")
