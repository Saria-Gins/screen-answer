"""The always-on-top answer card anchored to the bottom-right corner."""

from __future__ import annotations

import html

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_DISPLAY_NAME
from ..privacy import PrivacyGuard, hide_from_task_switcher
from ..shortcuts import (
    DEFAULT_CAPTURE_HOTKEY,
    DEFAULT_PANIC_HOTKEY,
    DEFAULT_REGION_HOTKEY,
    DEFAULT_TOGGLE_HOTKEY,
)
from ..theme import (
    ANSWER_DOCUMENT_CSS,
    ANSWER_DOCUMENT_CSS_LIGHT,
    APP_QSS,
    CARD_LIGHT_QSS,
)
from .icons import app_icon, glyph_icon
from .widgets import (
    DragArea,
    IconButton,
    force_topmost,
    set_role,
)


class _ResizeHandle(QWidget):
    """Small corner grip that resizes while keeping the bottom-right fixed."""

    def __init__(self, owner: AnswerCard):
        super().__init__(owner)
        self.owner = owner
        self._hover = False
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("拖动调整窗口大小")
        self.setMouseTracking(True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        light = getattr(self.owner, "_theme", "dark") == "light"
        if self._hover:
            color = QColor("#0284c7" if light else "#7dd3fc")
        else:
            color = QColor("#94a3b8" if light else "#64748b")
        painter.setPen(QPen(color, 1.3))
        painter.drawLine(4, 13, 13, 4)
        painter.drawLine(9, 13, 13, 9)
        painter.end()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.owner._begin_resize(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.owner._drag_resize(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.owner._end_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)


def welcome_markdown(
    capture_key: str = DEFAULT_CAPTURE_HOTKEY,
    region_key: str = DEFAULT_REGION_HOTKEY,
    toggle_key: str = DEFAULT_TOGGLE_HOTKEY,
    panic_key: str = DEFAULT_PANIC_HOTKEY,
) -> str:
    return f"""## 屏幕上的问题，直接问我

截取屏幕后，我会识别其中的文字，并在这里给出答案。

- **{capture_key}** 截取鼠标所在屏幕
- **{region_key}** 框选题目区域
- **{toggle_key}** 显示 / 隐藏卡片
- **{panic_key}** 一键隐身（卡片和托盘一起收起）
- 也可以点击下方 **截图解答**

> 第一次使用，请点左上角的应用图标打开设置，填写 API Key。
>
> 默认使用 Windows 本地 OCR，只把识别出的文字发送给你配置的 AI 接口。
> 隐私模式默认开启：截图和录屏里都看不到这张卡片。
"""


WELCOME_MARKDOWN = welcome_markdown()


class AnswerCard(QWidget):
    capture_full = Signal()
    capture_region = Signal()
    settings_clicked = Signal()
    retry_clicked = Signal()
    hidden_to_tray = Signal()
    geometry_changed = Signal(int, int, int, int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._answer_raw = ""
        self._last_markdown = ""
        self._answer_font_size = 13
        self._hotkey_summary = ""
        self._stream_dirty = False
        self._busy = False
        self._allow_close = False
        self._privacy_mode = False
        self._privacy_switcher = True
        self._theme = "dark"
        self._muted_html_color = "#94a3b8"
        self._resize_origin: QPoint | None = None
        self._resize_geometry = QRect()

        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setWindowIcon(app_icon())
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumSize(340, 280)
        self.setMaximumSize(1400, 1000)
        self.resize(620, 420)
        self.setStyleSheet(APP_QSS)

        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(80)
        self._stream_timer.timeout.connect(self._render_stream)
        # Re-applies Windows display protection and covers every window this
        # process opens later (settings dialog, region picker, menus).
        self.privacy_guard = PrivacyGuard(self)
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        self._card = QFrame()
        self._card.setObjectName("card")
        outer.addWidget(self._card)

        self._shadow = QGraphicsDropShadowEffect(self._card)
        self._shadow.setBlurRadius(30)
        self._shadow.setOffset(0, 8)
        self._shadow.setColor(QColor(0, 0, 0, 165))
        self._card.setGraphicsEffect(self._shadow)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(14, 7, 14, 7)
        layout.setSpacing(5)

        # Header ---------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(1)
        # The app logo doubles as the settings button, away from the
        # minimize/close controls on the right.
        self.settings_btn = QToolButton(self)
        self.settings_btn.setIcon(app_icon())
        self.settings_btn.setIconSize(QSize(24, 24))
        self.settings_btn.setFixedSize(24, 24)
        self.settings_btn.setAutoRaise(True)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setStyleSheet(
            "QToolButton{background:transparent;border:none;padding:0;}"
            "QToolButton:hover{background:rgba(148,163,184,0.13);"
            "border-radius:6px;}"
        )
        self.settings_btn.clicked.connect(self.settings_clicked)
        header.addWidget(self.settings_btn)

        drag = DragArea(self)
        drag.released.connect(self._on_drag_finished)
        drag_layout = QHBoxLayout(drag)
        drag_layout.setContentsMargins(7, 0, 0, 0)
        drag_layout.setSpacing(7)

        title = QLabel(APP_DISPLAY_NAME)
        title.setObjectName("appTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        drag_layout.addWidget(title)
        drag_layout.addStretch(1)
        header.addWidget(drag, 1)

        self.hide_btn = IconButton("minimize", "收起到托盘", "#94a3b8", 15, self)
        self.hide_btn.clicked.connect(self.hide_to_tray)
        self.close_btn = IconButton("close", "收起到托盘", "#94a3b8", 15, self)
        self.close_btn.clicked.connect(self.hide_to_tray)
        for button in (self.hide_btn, self.close_btn):
            button.setFixedSize(22, 22)
            button.setIconSize(QSize(14, 14))
            header.addWidget(button)
        layout.addLayout(header)

        layout.addWidget(self._divider())

        # Status ---------------------------------------------------------
        status_row = QHBoxLayout()
        status_row.setSpacing(7)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(7, 7)
        self.status_dot.setStyleSheet(
            "background:#64748b;border-radius:3px;"
        )
        self.status_label = QLabel("准备就绪")
        self.status_label.setObjectName("status")
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("hint")
        self.retry_btn = QToolButton()
        self.retry_btn.setObjectName("retryButton")
        self.retry_btn.setIcon(glyph_icon("retry", "#7dd3fc", 15))
        self.retry_btn.setText("重试")
        self.retry_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.hide()
        self.retry_btn.clicked.connect(self.retry_clicked)
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        status_row.addWidget(self.meta_label)
        status_row.addWidget(self.retry_btn)
        layout.addLayout(status_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        layout.addWidget(self.progress)

        # Answer ---------------------------------------------------------
        self.answer = QTextBrowser()
        self.answer.setObjectName("answer")
        self.answer.setOpenExternalLinks(True)
        self.answer.setFrameShape(QFrame.Shape.NoFrame)
        self.answer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        answer_font = QFont("Microsoft YaHei UI")
        answer_font.setPixelSize(13)
        self.answer.setFont(answer_font)
        self.answer.document().setDefaultFont(answer_font)
        self.answer.document().setDefaultStyleSheet(ANSWER_DOCUMENT_CSS)
        self._set_markdown(WELCOME_MARKDOWN)
        layout.addWidget(self.answer, 1)

        # OCR transcript -------------------------------------------------
        self.ocr_panel = QFrame()
        self.ocr_panel.setObjectName("ocrPanel")
        ocr_layout = QVBoxLayout(self.ocr_panel)
        ocr_layout.setContentsMargins(4, 3, 4, 4)
        ocr_layout.setSpacing(2)
        self.ocr_toggle = QToolButton()
        self.ocr_toggle.setObjectName("ocrToggle")
        self.ocr_toggle.setCheckable(True)
        self.ocr_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.ocr_toggle.setIcon(glyph_icon("chevron", "#64748b", 13))
        self.ocr_toggle.setText("识别到的文字")
        self.ocr_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ocr_toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.ocr_toggle.setStyleSheet("text-align:left;")
        self.ocr_toggle.toggled.connect(self._toggle_ocr)
        self.ocr_text = QPlainTextEdit()
        self.ocr_text.setObjectName("ocrText")
        self.ocr_text.setReadOnly(True)
        self.ocr_text.setMaximumHeight(88)
        self.ocr_text.hide()
        ocr_layout.addWidget(self.ocr_toggle)
        ocr_layout.addWidget(self.ocr_text)
        self.ocr_panel.hide()
        layout.addWidget(self.ocr_panel)

        # Actions --------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(7)
        self.capture_btn = QPushButton("  截图解答")
        self.capture_btn.setIcon(glyph_icon("camera", "#04121f", 16))
        self.capture_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.capture_btn.setFixedHeight(28)
        set_role(self.capture_btn, "primary")
        self.capture_btn.clicked.connect(self.capture_full)
        self.region_btn = QPushButton("  框选")
        self.region_btn.setIcon(glyph_icon("region", "#cbd5e1", 13))
        self.region_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.region_btn.setFixedHeight(28)
        self.region_btn.clicked.connect(self.capture_region)
        self.copy_btn = IconButton("copy", "复制答案", "#cbd5e1", 14, self)
        self.copy_btn.setFixedSize(28, 28)
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self.copy_answer)
        actions.addWidget(self.capture_btn, 3)
        actions.addWidget(self.region_btn, 2)
        actions.addWidget(self.copy_btn)
        actions.addSpacing(4)
        layout.addLayout(actions)

        self.resize_handle = _ResizeHandle(self)
        self.resize_handle.raise_()
        self._position_resize_handle()

    def _divider(self) -> QFrame:
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        return divider

    # --------------------------------------------------------------- state
    def _set_markdown(self, markdown: str) -> None:
        self._last_markdown = markdown
        self.answer.setMarkdown(markdown)

    def apply_answer_font_size(self, size: int) -> None:
        size = max(6, min(48, int(size)))
        self._answer_font_size = size
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(size)
        self.answer.setFont(font)
        self.answer.document().setDefaultFont(font)
        self._set_markdown(self._last_markdown or WELCOME_MARKDOWN)

    def _apply_privacy_affinity(self) -> None:
        """(Re)apply capture protection and task-switcher hiding for the card."""
        self.privacy_guard.attach(self)
        hide_from_task_switcher(self, self._privacy_switcher)
        self.privacy_guard.refresh()

    @property
    def privacy_active(self) -> bool:
        """True when Windows confirmed the card is hidden from captures."""
        return self.privacy_guard.active

    def apply_privacy_mode(
        self, enabled: bool, hide_from_switcher: bool | None = None
    ) -> None:
        self._privacy_mode = bool(enabled)
        if hide_from_switcher is not None:
            self._privacy_switcher = bool(hide_from_switcher)
        self.privacy_guard.set_enabled(
            self._privacy_mode, apply_now=self.isVisible()
        )
        if self.isVisible():
            self._apply_privacy_affinity()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_privacy_affinity)

    def set_status(self, text: str, kind: str = "normal") -> None:
        self.status_label.setText(text)
        object_name = {
            "busy": "statusBusy",
            "error": "statusError",
            "normal": "status",
        }.get(kind, "status")
        self.status_label.setObjectName(object_name)
        style = self.status_label.style()
        style.unpolish(self.status_label)
        style.polish(self.status_label)
        color = {
            "busy": "#38bdf8",
            "error": "#fb7185",
            "normal": "#64748b",
        }.get(kind, "#64748b")
        self.status_dot.setStyleSheet(
            f"background:{color};border-radius:3px;"
        )

    def set_meta(self, text: str) -> None:
        self.meta_label.setText(text)

    def set_busy(self, busy: bool, message: str = "正在处理…") -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        self.capture_btn.setEnabled(not busy)
        self.region_btn.setEnabled(not busy)
        self.settings_btn.setEnabled(not busy)
        if busy:
            self.retry_btn.hide()
            self.set_status(message, "busy")
            self.set_meta("")
        elif self.status_label.objectName() == "statusBusy":
            self.set_status("准备就绪", "normal")

    @property
    def busy(self) -> bool:
        return self._busy

    def set_hotkeys(
        self,
        capture_label: str,
        region_label: str,
        failed: list[str] | None = None,
        toggle_label: str = "",
        panic_label: str = "",
    ) -> None:
        parts = []
        if capture_label:
            parts.append(f"{capture_label} 截图")
        if region_label:
            parts.append(f"{region_label} 框选")
        if toggle_label:
            parts.append(f"{toggle_label} 显示/隐藏")
        if panic_label:
            parts.append(f"{panic_label} 一键隐身")
        self._hotkey_summary = "  ·  ".join(parts)
        if failed:
            self._hotkey_summary += "  ·  部分快捷键冲突"
        self.capture_btn.setToolTip(
            f"{capture_label} 截取鼠标所在屏幕" if capture_label else "截取屏幕"
        )
        self.region_btn.setToolTip(
            f"{region_label} 框选题目区域" if region_label else "框选题目区域"
        )
        settings_tip = "设置"
        if self._hotkey_summary:
            settings_tip += f"  ·  {self._hotkey_summary}"
        if failed:
            settings_tip = "设置（部分快捷键冲突）"
        self.settings_btn.setToolTip(settings_tip)
        tips = []
        if toggle_label:
            tips.append(f"{toggle_label} 恢复")
        if panic_label:
            tips.append(f"{panic_label} 一键隐身")
        self.hide_btn.setToolTip(
            f"隐藏到后台（{' / '.join(tips)}）" if tips else "隐藏到后台"
        )
        self.close_btn.setToolTip(self.hide_btn.toolTip())
        if not self._answer_raw and not self._busy:
            self._set_markdown(
                welcome_markdown(
                    capture_label or "未注册",
                    region_label or "未注册",
                    toggle_label or "未注册",
                    panic_label or "未注册",
                )
            )

    def reset_for_new_capture(self) -> None:
        self._answer_raw = ""
        self._stream_timer.stop()
        self.retry_btn.hide()
        self.copy_btn.setEnabled(False)
        self.set_meta("")
        self.ocr_panel.hide()
        self.ocr_toggle.setChecked(False)
        self.ocr_text.clear()
        self._set_markdown(
            "### 正在读取屏幕…\n\n"
            f"<span style='color:{self._muted_html_color}'>"
            "请稍候，几秒内就会在这里显示答案。</span>"
        )

    def set_ocr_text(self, text: str, meta: str = "") -> None:
        if not text.strip():
            self.ocr_panel.hide()
            return
        self.ocr_text.setPlainText(text)
        self.ocr_toggle.setText(f"识别到的文字  ·  {len(text)} 字")
        self.ocr_panel.show()
        if meta:
            self.set_meta(meta)

    def begin_answer(self) -> None:
        self._answer_raw = ""
        self._stream_dirty = False
        self._set_markdown("_正在组织答案…_")
        self.copy_btn.setEnabled(False)
        self.retry_btn.hide()
        self._stream_timer.start()

    def append_answer(self, chunk: str) -> None:
        if not chunk:
            return
        self._answer_raw += chunk
        self._stream_dirty = True

    def _render_stream(self) -> None:
        if not self._stream_dirty:
            return
        self._stream_dirty = False
        scroll = self.answer.verticalScrollBar()
        at_top = scroll.value() <= 4
        self._set_markdown(self._answer_raw)
        if at_top:
            scroll.setValue(0)

    def finish_answer(self, text: str, meta_text: str = "") -> None:
        self._stream_timer.stop()
        self._answer_raw = text or self._answer_raw
        self._set_markdown(self._answer_raw)
        self.answer.verticalScrollBar().setValue(0)
        self.copy_btn.setEnabled(bool(self._answer_raw.strip()))
        if meta_text:
            self.set_meta(meta_text)
        self.set_busy(False)
        self.set_status("解答完成", "normal")
        self.retry_btn.hide()

    def show_error(self, message: str, hint: str = "") -> None:
        self._stream_timer.stop()
        self._busy = False
        self.progress.hide()
        self.settings_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
        self.region_btn.setEnabled(True)
        self.copy_btn.setEnabled(False)
        self.retry_btn.show()
        self.set_status("没能完成", "error")
        safe_message = html.escape(message).replace("\n", "<br>")
        safe_hint = html.escape(hint).replace("\n", "<br>") if hint else ""
        body = f"### 这次没有完成\n\n{safe_message}"
        if safe_hint:
            body += (
                f"\n\n<span style='color:{self._muted_html_color}'>"
                f"{safe_hint}</span>"
            )
        self._set_markdown(body)
        self.answer.verticalScrollBar().setValue(0)

    def copy_answer(self) -> None:
        text = self._answer_raw.strip()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.copy_btn.setToolTip("已复制")
        self.set_meta("已复制到剪贴板")
        QTimer.singleShot(
            1800, lambda: self.copy_btn.setToolTip("复制答案")
        )

    def _toggle_ocr(self, checked: bool) -> None:
        self.ocr_text.setVisible(checked)
        self.ocr_toggle.setIcon(
            glyph_icon("chevron_down" if checked else "chevron", "#64748b", 13)
        )

    # ------------------------------------------------------------ geometry
    def apply_opacity(self, value: float) -> None:
        self.setWindowOpacity(max(0.10, min(1.0, float(value))))

    def apply_theme(self, theme: str) -> None:
        theme = "light" if theme == "light" else "dark"
        self._theme = theme
        self.setStyleSheet(
            APP_QSS + (CARD_LIGHT_QSS if theme == "light" else "")
        )
        self.answer.document().setDefaultStyleSheet(
            ANSWER_DOCUMENT_CSS_LIGHT
            if theme == "light"
            else ANSWER_DOCUMENT_CSS
        )
        if theme == "light":
            self.capture_btn.setIcon(
                glyph_icon("camera", "#ffffff", 16)
            )
            self.region_btn.setIcon(
                glyph_icon("region", "#334155", 13)
            )
            self.copy_btn.setIcon(glyph_icon("copy", "#334155", 14))
            self.hide_btn.setIcon(glyph_icon("minimize", "#475569", 15))
            self.close_btn.setIcon(glyph_icon("close", "#475569", 15))
            self.retry_btn.setIcon(glyph_icon("retry", "#0369a1", 15))
            chevron_color = "#64748b"
            self._muted_html_color = "#64748b"
            self._shadow.setColor(QColor(15, 23, 42, 55))
        else:
            self.capture_btn.setIcon(
                glyph_icon("camera", "#04121f", 16)
            )
            self.region_btn.setIcon(glyph_icon("region", "#cbd5e1", 13))
            self.copy_btn.setIcon(glyph_icon("copy", "#cbd5e1", 14))
            self.hide_btn.setIcon(glyph_icon("minimize", "#94a3b8", 15))
            self.close_btn.setIcon(glyph_icon("close", "#94a3b8", 15))
            self.retry_btn.setIcon(glyph_icon("retry", "#7dd3fc", 15))
            chevron_color = "#64748b"
            self._muted_html_color = "#94a3b8"
            self._shadow.setColor(QColor(0, 0, 0, 165))
        self.ocr_toggle.setIcon(
            glyph_icon(
                "chevron_down" if self.ocr_toggle.isChecked() else "chevron",
                chevron_color,
                13,
            )
        )
        self.resize_handle.update()
        self._set_markdown(self._last_markdown or WELCOME_MARKDOWN)

    def apply_size(self, width: int, height: int) -> None:
        """Resize from settings while keeping the card near the screen corner."""
        width = max(self.minimumWidth(), min(self.maximumWidth(), int(width)))
        height = max(self.minimumHeight(), min(self.maximumHeight(), int(height)))
        old = self.geometry()
        screen = QGuiApplication.screenAt(old.center())
        near_right = False
        near_bottom = False
        if screen is not None:
            available = screen.availableGeometry()
            near_right = abs(old.right() - available.right()) <= 42
            near_bottom = abs(old.bottom() - available.bottom()) <= 42
        self.resize(width, height)
        x = old.right() - self.width() + 1 if near_right else old.x()
        y = old.bottom() - self.height() + 1 if near_bottom else old.y()
        self.move(QPoint(x, y))
        self._position_resize_handle()

    def place_default(self, width: int = 620, height: int = 420) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = max(self.minimumWidth(), min(width, available.width()))
        height = max(self.minimumHeight(), min(height, available.height()))
        self.resize(width, height)
        x = available.right() - self.width() - 18
        y = available.bottom() - self.height() - 18
        self.move(max(available.left(), x), max(available.top(), y))
        self._position_resize_handle()

    def restore_position(self, x: int, y: int, width: int, height: int) -> None:
        width = max(self.minimumWidth(), min(width, self.maximumWidth()))
        height = max(self.minimumHeight(), min(height, self.maximumHeight()))
        self.resize(width, height)
        if x == -1 and y == -1:
            self.place_default(width, height)
            return
        # A negative position is legitimate: the card may deliberately be
        # dragged partly or fully beyond the screen edge.
        self.move(QPoint(x, y))
        self._position_resize_handle()

    def _position_resize_handle(self) -> None:
        if not hasattr(self, "resize_handle"):
            return
        # The 12 px outer margin contains a transparent shadow area; keep the
        # grip just inside the card's rounded corner.
        self.resize_handle.move(self.width() - 30, self.height() - 30)
        self.resize_handle.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_resize_handle()

    def _begin_resize(self, global_pos: QPoint) -> None:
        self._resize_origin = global_pos
        self._resize_geometry = self.geometry()

    def _drag_resize(self, global_pos: QPoint) -> None:
        if self._resize_origin is None:
            return
        delta = global_pos - self._resize_origin
        base = self._resize_geometry
        width = max(
            self.minimumWidth(),
            min(self.maximumWidth(), base.width() + delta.x()),
        )
        height = max(
            self.minimumHeight(),
            min(self.maximumHeight(), base.height() + delta.y()),
        )
        right = base.right()
        bottom = base.bottom()
        self.setGeometry(right - width + 1, bottom - height + 1, width, height)

    def _end_resize(self) -> None:
        self._resize_origin = None
        self.geometry_changed.emit(
            self.x(), self.y(), self.width(), self.height()
        )

    def _on_drag_finished(self) -> None:
        # Do not snap back to a screen; the card is allowed to be moved
        # partly or fully off-screen.
        self.geometry_changed.emit(
            self.x(), self.y(), self.width(), self.height()
        )

    def ensure_visible(self) -> bool:
        """If the card is (almost) entirely off-screen, bring it back."""
        for screen in QGuiApplication.screens():
            visible = screen.availableGeometry().intersected(self.frameGeometry())
            if visible.width() >= 120 and visible.height() >= 60:
                return False
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return False
        available = screen.availableGeometry()
        width = min(self.width(), available.width())
        height = min(self.height(), available.height())
        self.resize(width, height)
        self.move(
            max(available.left(), available.right() - width - 18),
            max(available.top(), available.bottom() - height - 18),
        )
        return True

    def reveal(self, activate: bool = True, ensure_visible: bool = False) -> None:
        if ensure_visible:
            self.ensure_visible()
        if not self.isVisible():
            self.show()
        self.raise_()
        force_topmost(self)
        if activate:
            self.activateWindow()

    def hide_to_tray(self) -> None:
        """Hide the card; the controller decides whether the tray follows."""
        self.hide()
        self.hidden_to_tray.emit()

    def hide_now(self) -> None:
        """Hide without notifying the controller (used for stealth hiding)."""
        self.hide()

    def allow_close(self) -> None:
        self._allow_close = True

    def closeEvent(self, event) -> None:
        if self._allow_close:
            event.accept()
            return
        self.hide_to_tray()
        event.ignore()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_to_tray()
            event.accept()
            return
        super().keyPressEvent(event)

