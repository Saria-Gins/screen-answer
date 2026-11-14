"""ScreenAnswer application entry point."""

from __future__ import annotations

import ctypes
import getpass
import hashlib
import json
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from screenanswer.ai import AIWorker, image_to_data_url
from screenanswer.capture import (
    clear_captures,
    grab,
    grab_fullscreen,
    monitor_at_cursor,
    persist_capture,
)
from screenanswer.config import (
    APP_DIR,
    APP_DISPLAY_NAME,
    APP_NAME,
    Settings,
    load_settings,
    save_settings,
)
from screenanswer.hotkey import GlobalHotkeys
from screenanswer.knowledge import KnowledgeBase
from screenanswer.ocr import OcrResult, OcrWorker
from screenanswer.shortcuts import normalize_hotkey
from screenanswer.theme import APP_QSS
from screenanswer.ui.card import AnswerCard
from screenanswer.ui.icons import app_icon
from screenanswer.ui.region import RegionSelector
from screenanswer.ui.settings import SettingsDialog

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        APP_DIR / "app.log",
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-8s %(name)s: %(message)s"
        )
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def hook(exc_type, exc_value, traceback):
        logger.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, traceback),
        )
        sys.__excepthook__(exc_type, exc_value, traceback)

    sys.excepthook = hook


def set_windows_app_id() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ScreenAnswer.Desktop"
        )
    except Exception:
        pass


SINGLE_INSTANCE_NAME = (
    "ScreenAnswer-"
    + hashlib.sha1(getpass.getuser().encode("utf-8")).hexdigest()[:10]
)


def _notify_existing_instance(show: bool = True) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_NAME)
    if not socket.waitForConnected(250):
        return False
    socket.write(b"show" if show else b"ping")
    socket.flush()
    socket.waitForBytesWritten(400)
    socket.disconnectFromServer()
    return True


def _tray_menu_style(theme: str) -> str:
    if theme == "light":
        return (
            "QMenu{background:#ffffff;color:#111827;border:1px solid "
            "#d8e2ef;border-radius:8px;padding:5px;}"
            "QMenu::item{padding:7px 26px 7px 12px;border-radius:5px;}"
            "QMenu::item:selected{background:#e0f2fe;}"
            "QMenu::separator{height:1px;background:#e2e8f0;"
            "margin:5px 8px;}"
        )
    return (
        "QMenu{background:#0d1728;color:#e8effa;border:1px solid "
        "rgba(148,163,184,0.22);border-radius:8px;padding:5px;}"
        "QMenu::item{padding:7px 26px 7px 12px;border-radius:5px;}"
        "QMenu::item:selected{background:rgba(56,189,248,0.16);}"
        "QMenu::separator{height:1px;background:rgba(148,163,184,0.14);"
        "margin:5px 8px;}"
    )


class Controller(QObject):
    def __init__(
        self,
        app: QApplication,
        settings: Settings,
        background: bool = False,
    ):
        super().__init__()
        self.app = app
        self.settings = settings
        self._background = background
        self._busy = False
        self._card_was_visible = True
        self._tray_hint_shown = False
        self._quitting = False
        self._last_image_path: Path | None = None
        self._last_image = None
        self._last_ocr_text = ""
        self._last_ocr_meta = ""
        self._last_knowledge_context = ""
        self._ocr_worker: OcrWorker | None = None
        self._ai_worker: AIWorker | None = None
        self._region_selector: RegionSelector | None = None
        self._settings_dialog: SettingsDialog | None = None
        self._settings_saved = False
        self._card_hidden = False
        self._capture_started = 0.0
        self.knowledge = KnowledgeBase()
        self.knowledge.load()

        self._build_card()
        self._build_tray()
        self._build_hotkeys()
        self._build_single_instance_server()

        self.card.geometry_changed.connect(self._save_geometry)
        self.card.apply_opacity(self.settings.opacity)
        self._apply_theme(self.settings.theme)
        self.card.apply_answer_font_size(self.settings.answer_font_size)
        self.card.apply_privacy_mode(
            self.settings.privacy_mode,
            self.settings.privacy_hide_from_switcher,
        )
        if self._background:
            # Started at login: keep the tray icon, no card until asked.
            self.card.hide_now()
        else:
            self.card.show()
            self.card.raise_()

        if not settings.api_key and not self._uses_local_endpoint():
            self.card.set_status("尚未配置 API Key", "normal")
            self.card.set_meta("点击右上角设置")
        elif settings.model:
            self.card.set_meta(settings.model)

        # Persist migrations (weak hotkeys, old font units) and any automatic
        # fallback choice so the next launch starts from the same state.
        try:
            save_settings(self.settings)
        except Exception:
            logger.exception("Could not persist migrated settings")

    # --------------------------------------------------------------- setup
    def _build_card(self) -> None:
        self.card = AnswerCard()
        self.card.capture_full.connect(lambda: self.request_capture(False))
        self.card.capture_region.connect(lambda: self.request_capture(True))
        self.card.settings_clicked.connect(self.open_settings)
        self.card.retry_clicked.connect(self.retry)
        self.card.hidden_to_tray.connect(self._on_card_hidden)
        if not (
            self.settings.window_x == -1 and self.settings.window_y == -1
        ):
            self.card.restore_position(
                self.settings.window_x,
                self.settings.window_y,
                self.settings.window_width,
                self.settings.window_height,
            )
        else:
            self.card.place_default(
                self.settings.window_width, self.settings.window_height
            )

    def _apply_theme(self, theme: str) -> None:
        self.card.apply_theme(theme)
        menu = getattr(self, "_tray_menu", None)
        if menu is not None:
            menu.setStyleSheet(_tray_menu_style(theme))

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(f"{APP_DISPLAY_NAME} · 屏幕内容 AI 助手")
        menu = QMenu()
        menu.setStyleSheet(_tray_menu_style(self.settings.theme))
        show_action = QAction("显示解答卡片", menu)
        show_action.triggered.connect(self._show_card)
        hide_action = QAction("隐藏（连托盘图标一起）", menu)
        hide_action.triggered.connect(self.panic_hide)
        reset_position_action = QAction("重置卡片位置", menu)
        reset_position_action.triggered.connect(self.reset_card_position)
        capture_action = QAction("截图解答", menu)
        capture_action.triggered.connect(lambda: self.request_capture(False))
        region_action = QAction("框选解答", menu)
        region_action.triggered.connect(lambda: self.request_capture(True))
        settings_action = QAction("设置…", menu)
        settings_action.triggered.connect(self.open_settings)
        rehotkey_action = QAction("重新注册快捷键", menu)
        rehotkey_action.triggered.connect(
            lambda _checked=False: self.reload_hotkeys(notify=True)
        )
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(show_action)
        menu.addAction(hide_action)
        menu.addAction(reset_position_action)
        menu.addSeparator()
        menu.addAction(capture_action)
        menu.addAction(region_action)
        menu.addSeparator()
        menu.addAction(settings_action)
        menu.addAction(rehotkey_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _build_hotkeys(self) -> None:
        self.hotkeys = GlobalHotkeys(self.app)
        self.hotkeys.capture_full.connect(lambda: self.request_capture(False))
        self.hotkeys.capture_region.connect(lambda: self.request_capture(True))
        self.hotkeys.toggle_requested.connect(self.toggle_card_visibility)
        self.hotkeys.panic_requested.connect(self.panic_hide)
        self.reload_hotkeys(notify=True)

    def reload_hotkeys(self, notify: bool = True) -> None:
        failures = self.hotkeys.register(
            self.settings.hotkey_capture,
            self.settings.hotkey_region,
            self.settings.hotkey_toggle,
            self.settings.hotkey_panic,
        )
        changed = False
        for attr, stored in (
            ("hotkey_capture", self.hotkeys.capture_stored),
            ("hotkey_region", self.hotkeys.region_stored),
            ("hotkey_toggle", self.hotkeys.toggle_stored),
            ("hotkey_panic", self.hotkeys.panic_stored),
        ):
            if stored and stored != normalize_hotkey(
                getattr(self.settings, attr)
            ):
                setattr(self.settings, attr, stored)
                changed = True
        if changed:
            try:
                save_settings(self.settings)
            except Exception:
                logger.exception("Could not save fallback hotkeys")
        self.card.set_hotkeys(
            self.hotkeys.capture_label,
            self.hotkeys.region_label,
            failures,
            self.hotkeys.toggle_label,
            self.hotkeys.panic_label,
        )
        if failures:
            logger.warning("Hotkey registration failed: %s", failures)
        if notify and self.tray.isVisible():
            if self.hotkeys.notes:
                self.tray.showMessage(
                    "快捷键已自动调整",
                    "；".join(self.hotkeys.notes),
                    QSystemTrayIcon.MessageIcon.Warning,
                    6000,
                )
            elif failures:
                self.tray.showMessage(
                    "快捷键未生效",
                    "；".join(failures),
                    QSystemTrayIcon.MessageIcon.Warning,
                    6000,
                )

    def _build_single_instance_server(self) -> None:
        self.server = QLocalServer(self)
        QLocalServer.removeServer(SINGLE_INSTANCE_NAME)
        if not self.server.listen(SINGLE_INSTANCE_NAME):
            logger.warning("Could not start single-instance server")
        self.server.newConnection.connect(self._on_new_instance)

    def _on_new_instance(self) -> None:
        socket = self.server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(
            lambda: self._handle_instance_message(socket)
        )
        socket.disconnected.connect(socket.deleteLater)
        if socket.bytesAvailable():
            self._handle_instance_message(socket)

    def _handle_instance_message(self, socket: QLocalSocket) -> None:
        data = bytes(socket.readAll())
        if data == b"show":
            self._show_card()
        socket.disconnectFromServer()

    # ------------------------------------------------------------- actions
    def _show_card(self) -> None:
        """Bring the card (and its tray icon) back into view."""
        self._card_hidden = False
        self._sync_tray()
        self.card.reveal(activate=True, ensure_visible=True)

    def toggle_card_visibility(self) -> None:
        """Hotkey: hide the card into the background, or bring it back."""
        if self._quitting:
            return
        self._set_card_hidden(self.card.isVisible())

    def panic_hide(self) -> None:
        """Hotkey: hide everything this process shows, in one step."""
        if self._quitting:
            return
        selector = self._region_selector
        if selector is not None:
            self._region_selector = None
            selector.close()
            selector.deleteLater()
        dialog = self._settings_dialog
        if dialog is not None and dialog.isVisible():
            # reject() restores the live opacity preview and the shortcuts.
            dialog.reject()
        self._set_card_hidden(True)

    def _set_card_hidden(self, hidden: bool) -> None:
        """Single entry point for showing/hiding the card."""
        if self._quitting:
            return
        if hidden:
            self.card.hide_now()
            self._card_hidden = True
            self._sync_tray()
            self._show_hidden_hint()
            return
        self._card_hidden = False
        self._sync_tray()
        self.card.reveal(activate=False, ensure_visible=True)

    def _tray_should_show(self) -> bool:
        if self._quitting:
            return False
        return not (self._card_hidden and self.settings.privacy_hide_tray)

    def _sync_tray(self) -> None:
        """Keep the tray icon in step with the stealth state."""
        try:
            want = self._tray_should_show()
            if want and not self.tray.isVisible():
                self.tray.show()
            elif not want and self.tray.isVisible():
                self.tray.hide()
        except Exception:
            logger.debug("Could not update the tray icon", exc_info=True)

    def reset_card_position(self) -> None:
        self.card.place_default(
            self.settings.window_width, self.settings.window_height
        )
        if self._settings_dialog is None or not self._settings_dialog.isVisible():
            self.card.reveal(activate=True)
        self._save_geometry(
            self.card.x(),
            self.card.y(),
            self.card.width(),
            self.card.height(),
        )
        self.card.set_status("位置已重置", "normal")
        if self._settings_dialog is not None:
            self._settings_dialog.set_size_values(
                self.card.width(), self.card.height()
            )

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.card.isVisible():
                self._set_card_hidden(True)
            else:
                self._show_card()

    def _on_card_hidden(self) -> None:
        self._card_hidden = True
        self._sync_tray()
        self._show_hidden_hint()

    def _show_hidden_hint(self) -> None:
        if self._tray_hint_shown or not self.tray.isVisible():
            return
        self._tray_hint_shown = True
        key = (
            self.hotkeys.toggle_label
            or self.hotkeys.capture_label
            or "卡片上的截图按钮"
        )
        self.tray.showMessage(
            APP_DISPLAY_NAME,
            f"已收起到托盘。按 {key} 恢复卡片。",
            QSystemTrayIcon.MessageIcon.Information,
            2600,
        )

    def _uses_local_endpoint(self) -> bool:
        base = self.settings.api_base.lower()
        return any(
            marker in base
            for marker in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")
        )

    def request_capture(self, region: bool) -> None:
        if self._quitting:
            return
        if self._region_selector is not None:
            return
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        if self._busy:
            self.card.reveal(activate=False, ensure_visible=True)
            self.card.set_status("正在处理，请稍候", "busy")
            return
        if not self.settings.endpoint or not self.settings.model:
            self.card.reveal(ensure_visible=True)
            self.card.set_status("请先配置 API 地址和模型", "error")
            self.open_settings()
            return
        if not self.settings.api_key and not self._uses_local_endpoint():
            self.card.reveal(ensure_visible=True)
            self.card.set_status("请先填写 API Key", "error")
            self.open_settings()
            return

        self._card_was_visible = self.card.isVisible()
        self._capture_started = time.perf_counter()
        self.card.hide_now()
        QApplication.processEvents()
        QTimer.singleShot(170, lambda: self._capture_after_hide(region))

    def _capture_after_hide(self, region: bool) -> None:
        try:
            if region:
                self._start_region_capture()
            else:
                result = grab_fullscreen(self.settings.capture_scope)
                path = persist_capture(result.image)
                self._begin_pipeline(result.image, path, "全屏")
        except Exception as exc:
            logger.exception("Screen capture failed")
            self.card.reveal(activate=False, ensure_visible=True)
            self.card.show_error(
                f"截取屏幕失败：{exc}",
                "请确认没有其他程序正在独占屏幕，或尝试框选模式。",
            )
            self._busy = False

    def _start_region_capture(self) -> None:
        monitor = monitor_at_cursor()
        if monitor is None:
            raise RuntimeError("找不到鼠标所在的显示器")
        from PySide6.QtGui import QCursor

        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("没有可用的显示器")
        image = grab(monitor.rect)
        selector = RegionSelector(screen, image)
        selector.selected.connect(self._on_region_selected)
        selector.cancelled.connect(self._on_region_cancelled)
        self._region_selector = selector
        # The picker shows a frozen screenshot: keep it out of other captures
        # and out of task-switch previews like the card.
        self.card.privacy_guard.attach(selector)
        selector.start()

    def _on_region_selected(self, rect, image) -> None:
        selector = self._region_selector
        self._region_selector = None
        if selector is not None:
            selector.deleteLater()
        try:
            path = persist_capture(image)
        except Exception as exc:
            logger.exception("Could not persist region capture")
            self.card.reveal(activate=False, ensure_visible=True)
            self.card.show_error(f"保存截图失败：{exc}")
            return
        self._begin_pipeline(image, path, "框选")

    def _on_region_cancelled(self) -> None:
        selector = self._region_selector
        self._region_selector = None
        if selector is not None:
            selector.deleteLater()
        if self._card_was_visible:
            self.card.reveal(activate=False)
            self.card.set_status("已取消框选", "normal")

    # ------------------------------------------------------------ pipeline
    def _begin_pipeline(self, image, path: Path, source: str) -> None:
        self._busy = True
        self._last_image = image
        self._last_image_path = path
        self._last_ocr_text = ""
        self._last_ocr_meta = ""
        self._last_knowledge_context = ""
        self._card_hidden = False
        self._sync_tray()
        self.card.reveal(activate=False, ensure_visible=True)
        self.card.reset_for_new_capture()
        self.card.set_busy(True, "正在识别屏幕并检索知识库…")
        self.card.set_meta(f"{source} · {image.width}×{image.height}")

        if self._ocr_worker is not None:
            self._stop_worker(self._ocr_worker, 400)
        worker = OcrWorker(path, self.settings.ocr_language, self)
        worker.done.connect(self._on_ocr_done)
        worker.finished.connect(self._on_ocr_thread_finished)
        self._ocr_worker = worker
        worker.start()

    def _on_ocr_done(self, result: OcrResult) -> None:
        if self._quitting:
            return
        text = result.text.strip()
        if result.error or not text:
            if self.settings.mode == "vision":
                logger.warning(
                    "OCR unavailable for knowledge lookup: %s",
                    result.error or "empty text",
                )
                self._start_vision_ai("", "")
                return
            if result.error:
                hint = (
                    "可以在设置中改用视觉模型，或安装 Windows 中文 OCR 语言包。"
                    if result.engine_missing
                    else "请尝试框选更清晰的区域，或改用视觉模型。"
                )
                self._fail(result.error, hint)
            else:
                self._fail(
                    "没有识别到文字。",
                    "试试框选题目区域，放大页面，或在设置中切换到视觉模型。",
                )
            return

        self._last_ocr_text = text
        meta = (
            f"{result.language} · {result.line_count} 行 · "
            f"{result.duration:.2f}s"
        )
        self._last_ocr_meta = meta
        self.card.set_ocr_text(text, meta)
        context = self.knowledge.build_context(text)
        self._last_knowledge_context = context
        if context:
            meta += " · 命中本地知识库"
            self.card.set_meta(meta)
        self.card.set_status(
            "正在结合本地知识库解答…" if context else "正在解答…", "busy"
        )
        if self.settings.mode == "vision":
            self._start_vision_ai(text, context)
        else:
            self._start_ai(text, "", context)

    def _start_vision_ai(self, text: str, context: str) -> None:
        if self._last_image_path is None or not self._last_image_path.exists():
            self._fail(
                "找不到刚才的截图文件。",
                "请重新截图，或改用本地 OCR 模式。",
            )
            return
        try:
            data_url = image_to_data_url(self._last_image_path)
        except Exception as exc:
            self._fail(f"处理截图失败：{exc}", "请重试或改用本地 OCR。")
            return
        self.card.set_status(
            "正在结合本地知识库解答…" if context else "正在解答…", "busy"
        )
        self._start_ai(text, data_url, context)

    @staticmethod
    def _stop_worker(worker, timeout: int = 1500) -> None:
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()
        if worker.wait(timeout):
            return
        logger.warning("Terminating a background worker that did not stop")
        worker.terminate()
        worker.wait(800)

    def _start_ai(
        self, text: str, image_data_url: str, knowledge_context: str = ""
    ) -> None:
        if self._ai_worker is not None:
            self._stop_worker(self._ai_worker, 400)
            self._ai_worker = None
        self.card.begin_answer()
        worker = AIWorker(
            settings=self.settings,
            text=text,
            image_data_url=image_data_url,
            parent=self,
            knowledge_context=knowledge_context,
        )
        worker.chunk.connect(self.card.append_answer)
        worker.done.connect(self._on_ai_done)
        worker.failed.connect(self._on_ai_failed)
        worker.finished.connect(self._on_ai_thread_finished)
        self._ai_worker = worker
        worker.start()

    def _on_ai_done(self, text: str, meta) -> None:
        if self._quitting:
            return
        elapsed = getattr(meta, "elapsed", 0.0)
        model = getattr(meta, "model", self.settings.model) or self.settings.model
        meta_text = f"{model} · {elapsed:.1f}s" if elapsed else model
        self.card.finish_answer(text, meta_text)
        self.card.set_meta(meta_text)
        self._busy = False

    def _on_ai_failed(self, message: str) -> None:
        if self._quitting:
            return
        hint = "请检查 API 地址、密钥和模型名是否正确。"
        lowered = message.lower()
        if "401" in message or "unauthorized" in lowered or "invalid" in lowered:
            hint = "密钥可能无效或已过期。请到设置中重新填写 API Key。"
        elif "404" in message or "model" in lowered:
            hint = "请确认模型名称和 API 地址是否匹配该服务商。"
        elif "余额" in message or "quota" in lowered or "429" in message:
            hint = "接口额度不足或请求过于频繁，请稍后再试。"
        self._fail(message, hint)

    def _on_ai_thread_finished(self) -> None:
        worker = self._ai_worker
        self._ai_worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_ocr_thread_finished(self) -> None:
        worker = self._ocr_worker
        self._ocr_worker = None
        if worker is not None:
            worker.deleteLater()

    def _fail(self, message: str, hint: str = "") -> None:
        self._busy = False
        self.card.show_error(message, hint)

    def retry(self) -> None:
        if self._busy:
            return
        if self.settings.mode == "vision":
            if self._last_image_path is None or not self._last_image_path.exists():
                self.request_capture(False)
                return
            try:
                data = image_to_data_url(self._last_image_path)
            except Exception as exc:
                self.card.show_error(f"无法读取上次的截图：{exc}")
                return
            self._busy = True
            self.card.set_busy(True, "正在重试…")
            self._start_ai(
                self._last_ocr_text,
                data,
                self._last_knowledge_context,
            )
            return
        if not self._last_ocr_text.strip():
            self.request_capture(False)
            return
        self._busy = True
        self.card.set_busy(True, "正在重试…")
        self._start_ai(
            self._last_ocr_text, "", self._last_knowledge_context
        )

    # ------------------------------------------------------------ settings
    def open_settings(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(
            self.settings,
            self.card,
            knowledge_summary=self.knowledge.stats.summary,
        )
        dialog.saved.connect(self._on_settings_saved)
        dialog.finished.connect(self._on_settings_closed)
        dialog.opacity_preview.connect(self.card.apply_opacity)
        dialog.reset_position_requested.connect(self.reset_card_position)
        self._settings_dialog = dialog
        self._settings_saved = False
        # Release the current shortcuts so the key editor can capture them.
        self.hotkeys.suspend()
        self.card.privacy_guard.attach(dialog)
        dialog.show()
        self.card.privacy_guard.refresh()
        dialog.raise_()
        dialog.activateWindow()

    def _on_settings_saved(self, settings: Settings) -> None:
        self._settings_saved = True
        self.settings = settings
        self.card.apply_opacity(settings.opacity)
        self.card.apply_size(settings.window_width, settings.window_height)
        self._apply_theme(settings.theme)
        self.card.apply_answer_font_size(settings.answer_font_size)
        self.card.apply_privacy_mode(
            settings.privacy_mode, settings.privacy_hide_from_switcher
        )
        self._sync_tray()
        self.reload_hotkeys(notify=True)
        if self.hotkeys.failures:
            self.card.set_status("快捷键未生效", "error")
        elif self.hotkeys.notes:
            self.card.set_status("快捷键已自动调整", "normal")
        else:
            self.card.set_status("设置已保存", "normal")
        self.card.set_meta(settings.model)
        if self.card.isVisible():
            self.card.reveal(activate=False, ensure_visible=True)

    def _on_settings_closed(self, _result: int) -> None:
        dialog = self._settings_dialog
        self._settings_dialog = None
        if dialog is not None:
            dialog.deleteLater()
        if self._quitting:
            self._settings_saved = False
            return
        if not self._settings_saved:
            # Cancel: restore the live opacity preview and the old shortcuts.
            self.card.apply_opacity(self.settings.opacity)
            self.reload_hotkeys(notify=False)
        self._settings_saved = False

    def _save_geometry(self, x: int, y: int, width: int, height: int) -> None:
        self.settings.window_x = x
        self.settings.window_y = y
        self.settings.window_width = width
        self.settings.window_height = height
        try:
            save_settings(self.settings)
        except Exception:
            logger.exception("Could not save window geometry")

    # ---------------------------------------------------------------- quit
    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._busy = False
        try:
            self.hotkeys.unregister()
        except Exception:
            pass
        for worker in (self._ocr_worker, self._ai_worker):
            if worker is not None:
                self._stop_worker(worker, 1500)
        if self._region_selector is not None:
            self._region_selector.close()
        if self._settings_dialog is not None:
            self._settings_dialog.close()
        self.tray.hide()
        self.server.close()
        clear_captures()
        self.card.allow_close()
        self.card.close()
        self.app.quit()


def _install_styles(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(APP_QSS)


def _ocr_test_cli(argv: list[str]) -> int | None:
    """Hidden diagnostic used to verify OCR inside a packaged build."""
    if "--ocr-test" not in argv:
        return None
    index = argv.index("--ocr-test")
    if index + 1 >= len(argv):
        return 2
    source = Path(argv[index + 1]).resolve()
    from screenanswer.ocr import recognize_image

    result = recognize_image(source)
    output = (
        Path(argv[index + 2]).resolve()
        if index + 2 < len(argv)
        else source.with_suffix(source.suffix + ".ocr.json")
    )
    output.write_text(
        json.dumps(
            {
                "text": result.text,
                "language": result.language,
                "lines": result.line_count,
                "duration": result.duration,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0 if not result.error else 1


def _knowledge_cli(argv: list[str]) -> int | None:
    """Hidden diagnostic: dump knowledge-base status (and an optional query)."""
    if "--knowledge" not in argv:
        return None
    index = argv.index("--knowledge")
    query = ""
    if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
        query = argv[index + 1]
    kb = KnowledgeBase()
    started = time.perf_counter()
    stats = kb.load()
    duration = time.perf_counter() - started
    lines = ["=== 知识库状态 ==="]
    lines.append("目录：" + ("；".join(str(d) for d in kb.directories) or "（未找到）"))
    lines.append(stats.summary)
    lines.append(
        f"文件 {stats.files} 个 · 条目 {stats.entries} 条 · "
        f"{stats.chars} 字符 · 解析耗时 {duration:.1f}s"
    )
    kinds = {"question": 0, "passage": 0}
    for entry in kb.entries:
        kinds[entry.kind] = kinds.get(entry.kind, 0) + 1
    lines.append(f"题库条目 {kinds.get('question', 0)} · 资料片段 {kinds.get('passage', 0)}")
    for name in stats.skipped:
        lines.append(f"跳过：{name}")
    for name in stats.errors:
        lines.append(f"失败：{name}")
    if query:
        lines.append("")
        lines.append(f"=== 检索「{query}」 ===")
        for match in kb.search(query):
            head = match.text.replace("\n", " ")[:220]
            lines.append(f"[{match.kind}｜{match.source}｜第{match.number or '-'}题] {head}")
    report = "\n".join(lines)
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        (APP_DIR / "knowledge-report.txt").write_text(report, encoding="utf-8")
    except Exception:
        logger.exception("Could not write the knowledge report")
    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        print(report)
    except Exception:
        pass
    return 0 if stats.files else 1


def main() -> int:
    setup_logging()
    set_windows_app_id()
    cli_result = _ocr_test_cli(sys.argv)
    if cli_result is not None:
        return cli_result
    knowledge_result = _knowledge_cli(sys.argv)
    if knowledge_result is not None:
        return knowledge_result
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName("ScreenAnswer")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    _install_styles(app)

    background = "--background" in sys.argv[1:]
    if _notify_existing_instance(show=not background):
        return 0

    settings = load_settings()
    controller = Controller(app, settings, background=background)
    app._controller = controller  # keep Python ownership for the app lifetime
    app.aboutToQuit.connect(controller.hotkeys.unregister)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
