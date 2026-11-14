"""Settings dialog for the AI endpoint, OCR and answer style."""

from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..ai import AIWorker
from ..config import (
    APP_DISPLAY_NAME,
    DEFAULT_SYSTEM_PROMPT,
    Settings,
    apply_startup,
    save_settings,
)
from ..hotkey import probe_hotkey
from ..ocr import available_languages
from ..privacy import (
    MODE_EXCLUDE,
    MODE_LABELS,
    MODE_MONITOR,
    is_supported_platform,
    support_mode,
    windows_version_text,
)
from ..shortcuts import (
    DEFAULT_CAPTURE_HOTKEY,
    DEFAULT_PANIC_HOTKEY,
    DEFAULT_REGION_HOTKEY,
    DEFAULT_TOGGLE_HOTKEY,
    normalize_hotkey,
    validate_hotkey,
)
from ..theme import SETTINGS_LIGHT_QSS, SETTINGS_QSS
from .icons import app_icon, glyph_icon
from .widgets import enable_dark_title_bar, set_role

logger = logging.getLogger(__name__)

# Keep a strong reference to detached connection-test threads so closing the
# dialog cannot destroy a QThread while it is still waiting on the network.
_DETACHED_TESTS: set[AIWorker] = set()


class SettingsDialog(QDialog):
    saved = Signal(object)
    opacity_preview = Signal(float)
    reset_position_requested = Signal()

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        knowledge_summary: str = "",
    ):
        super().__init__(parent)
        self.settings = settings
        self._test_worker: AIWorker | None = None
        self._ocr_languages = available_languages()
        self._original_opacity = settings.opacity
        self._knowledge_summary = knowledge_summary

        self.setWindowTitle(f"{APP_DISPLAY_NAME} · 设置")
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.setStyleSheet(
            SETTINGS_QSS
            + (SETTINGS_LIGHT_QSS if settings.theme == "light" else "")
        )
        self.setMinimumWidth(620)
        self.resize(660, 760)
        self._build_ui()
        self._load_values()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(24, 18, 24, 12)
        header.setSpacing(11)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(38, 38))
        icon.setFixedSize(38, 38)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("设置")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("连接 AI 模型，调整识别、外观与快捷键")
        subtitle.setObjectName("dialogSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addWidget(icon)
        header.addLayout(titles)
        header.addStretch(1)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        content = QWidget()
        content.setObjectName("settingsContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 4, 24, 18)
        content_layout.setSpacing(13)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self._build_ai_section(content_layout)
        self._build_ocr_section(content_layout)
        self._build_appearance_section(content_layout)
        self._build_privacy_section(content_layout)
        self._build_hotkey_section(content_layout)
        self._build_prompt_section(content_layout)
        self._build_knowledge_section(content_layout)
        self._build_other_section(content_layout)
        content_layout.addStretch(1)

        footer = QFrame()
        footer.setObjectName("footerBar")
        footer.setStyleSheet(
            "QFrame#footerBar{border-top:1px solid rgba(148,163,184,0.12);}"
        )
        footer_outer = QVBoxLayout(footer)
        footer_outer.setContentsMargins(24, 8, 24, 12)
        footer_outer.setSpacing(4)
        self.dialog_status = QLabel("")
        self.dialog_status.setObjectName("errorHint")
        self.dialog_status.setWordWrap(True)
        self.dialog_status.hide()
        footer_outer.addWidget(self.dialog_status)
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(8)
        note = QLabel("截图只发送到你填写的接口")
        note.setObjectName("hint")
        footer_layout.addWidget(note)
        footer_layout.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("保存")
        set_role(self.save_btn, "primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        footer_layout.addWidget(cancel)
        footer_layout.addWidget(self.save_btn)
        footer_outer.addLayout(footer_layout)
        layout.addWidget(footer)

    def _new_section(self, title: str, description: str = ""):
        frame = QFrame()
        frame.setObjectName("section")
        box = QVBoxLayout(frame)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(7)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        box.addWidget(label)
        if description:
            hint = QLabel(description)
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            box.addWidget(hint)
        return frame, box

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _build_ai_section(self, parent_layout: QVBoxLayout) -> None:
        frame, box = self._new_section(
            "AI 接口",
            "使用 OpenAI 兼容的 Chat Completions 接口。API Key 只加密保存在本机。",
        )
        box.addWidget(self._field_label("API 地址"))
        self.api_base_edit = QLineEdit()
        self.api_base_edit.setPlaceholderText("https://api.deepseek.com/v1")
        self.api_base_edit.setClearButtonEnabled(True)
        box.addWidget(self.api_base_edit)
        api_hint = QLabel(
            "DeepSeek：https://api.deepseek.com/v1　·　"
            "OpenAI：https://api.openai.com/v1"
        )
        api_hint.setObjectName("hint")
        api_hint.setWordWrap(True)
        api_hint.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        box.addWidget(api_hint)

        model_mode = QHBoxLayout()
        model_mode.setSpacing(10)
        model_box = QVBoxLayout()
        model_box.setSpacing(4)
        model_box.addWidget(self._field_label("模型"))
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("deepseek-chat")
        model_box.addWidget(self.model_edit)
        mode_box = QVBoxLayout()
        mode_box.setSpacing(4)
        mode_box.addWidget(self._field_label("识别方式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("本地 OCR + 文本模型", "ocr")
        self.mode_combo.addItem("视觉模型（直接发图）", "vision")
        self.mode_combo.currentIndexChanged.connect(self._update_mode_hint)
        mode_box.addWidget(self.mode_combo)
        model_mode.addLayout(model_box, 3)
        model_mode.addLayout(mode_box, 2)
        box.addLayout(model_mode)

        self.mode_hint = QLabel("")
        self.mode_hint.setObjectName("hint")
        self.mode_hint.setWordWrap(True)
        box.addWidget(self.mode_hint)

        box.addWidget(self._field_label("API Key"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-…（本地模型可留空）")
        self.key_edit.setClearButtonEnabled(True)
        self._key_visible = False
        self._eye_action = self.key_edit.addAction(
            glyph_icon("eye", "#64748b", 17),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self._eye_action.setToolTip("显示密钥")
        self._eye_action.triggered.connect(self._toggle_key_visibility)
        box.addWidget(self.key_edit)

        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test_connection)
        self.test_result = QLabel("")
        self.test_result.setObjectName("hint")
        self.test_result.setWordWrap(True)
        self.test_result.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        box.addLayout(test_row)
        parent_layout.addWidget(frame)

    def _build_ocr_section(self, parent_layout: QVBoxLayout) -> None:
        frame, box = self._new_section(
            "识别与截图", "本地 OCR 由 Windows 提供，图片不会离开本机。"
        )
        row = QHBoxLayout()
        row.setSpacing(10)
        lang_box = QVBoxLayout()
        lang_box.setSpacing(4)
        lang_box.addWidget(self._field_label("OCR 语言"))
        self.ocr_lang_combo = QComboBox()
        self.ocr_lang_combo.addItem("自动（跟随系统）", "")
        for language in self._ocr_languages:
            label = language.display_name
            if language.tag not in label:
                label = f"{language.display_name}  ({language.tag})"
            self.ocr_lang_combo.addItem(label, language.tag)
        if not self._ocr_languages:
            self.ocr_lang_combo.addItem("Windows OCR 不可用", "")
            self.ocr_lang_combo.setEnabled(False)
        lang_box.addWidget(self.ocr_lang_combo)
        row.addLayout(lang_box, 1)

        scope_box = QVBoxLayout()
        scope_box.setSpacing(4)
        scope_box.addWidget(self._field_label("全屏截图范围"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("鼠标所在屏幕", "cursor")
        self.scope_combo.addItem("所有屏幕", "all")
        scope_box.addWidget(self.scope_combo)
        row.addLayout(scope_box, 1)
        box.addLayout(row)

        if self._ocr_languages:
            tags = "、".join(x.tag for x in self._ocr_languages[:4])
            hint = QLabel(f"已安装：{tags}。框选模式始终只截取所选区域。")
        else:
            hint = QLabel(
                "没有检测到 Windows OCR 语言包。可在系统设置 → 时间和语言 → "
                "语言中添加中文的“光学字符识别”功能，或改用视觉模型。"
            )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        box.addWidget(hint)
        parent_layout.addWidget(frame)

    def _build_knowledge_section(self, parent_layout: QVBoxLayout) -> None:
        frame, box = self._new_section(
            "本地知识库",
            "从程序旁的 know 文件夹检索相关题目；命中片段会随问题发送给 AI。",
        )
        summary = QLabel(self._knowledge_summary or "知识库未加载")
        summary.setObjectName("successHint" if self._knowledge_summary else "hint")
        summary.setWordWrap(True)
        box.addWidget(summary)
        note = QLabel(
            "支持 .docx / .pdf / .txt / .md；放在程序旁的 know 文件夹里即可，"
            "新增或替换文件后重启生效（扫描件 PDF 无文本层，会自动跳过）。"
            "检索与解析都在本机完成。"
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        box.addWidget(note)
        parent_layout.addWidget(frame)

    def _build_appearance_section(self, parent_layout: QVBoxLayout) -> None:
        frame, box = self._new_section(
            "外观与窗口",
            "透明度会自动保存；拖动卡片右下角小三角调整大小，"
            "卡片也可以移到屏幕边缘之外。",
        )
        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(10)
        opacity_row.addWidget(self._field_label("卡片透明度"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setSingleStep(1)
        self.opacity_slider.setPageStep(5)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.opacity_value = QLabel("100%")
        self.opacity_value.setObjectName("hint")
        self.opacity_value.setFixedWidth(38)
        self.opacity_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_value)
        box.addLayout(opacity_row)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(10)
        theme_row.addWidget(self._field_label("主题"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色（白底黑字）", "light")
        theme_row.addWidget(self.theme_combo)
        theme_hint = QLabel("保存后卡片和设置窗口切换主题")
        theme_hint.setObjectName("hint")
        theme_row.addWidget(theme_hint, 1)
        box.addLayout(theme_row)

        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        size_row.addWidget(self._field_label("窗口大小"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(340, 1400)
        self.width_spin.setSingleStep(10)
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(620)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(280, 1000)
        self.height_spin.setSingleStep(10)
        self.height_spin.setSuffix(" px")
        self.height_spin.setValue(420)
        size_row.addWidget(self.width_spin)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height_spin)
        size_row.addSpacing(12)
        size_row.addWidget(self._field_label("答案字号"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 48)
        self.font_size_spin.setSingleStep(1)
        self.font_size_spin.setSuffix(" px")
        self.font_size_spin.setValue(13)
        self.font_size_spin.setToolTip(
            "答案文字像素大小，最小 6 px；修改后自动重新排版"
        )
        size_row.addWidget(self.font_size_spin)
        size_row.addStretch(1)
        box.addLayout(size_row)

        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        reset_size = QPushButton("恢复默认大小")
        reset_size.setObjectName("linkButton")
        reset_size.clicked.connect(self._reset_size)
        reset_row.addWidget(reset_size)
        reset_position = QPushButton("重置位置")
        reset_position.setObjectName("linkButton")
        reset_position.clicked.connect(self.reset_position_requested.emit)
        reset_row.addWidget(reset_position)
        box.addLayout(reset_row)
        parent_layout.addWidget(frame)

    def _build_privacy_section(self, parent_layout: QVBoxLayout) -> None:
        frame, box = self._new_section(
            "隐私与隐藏",
            "让卡片和设置窗口在截图、录屏、任务切换里都“不出现”。",
        )
        self.privacy_check = QCheckBox(
            "隐私模式：从截图和录屏中隐藏所有窗口"
        )
        self.privacy_check.toggled.connect(self._update_privacy_state)
        box.addWidget(self.privacy_check)

        self.privacy_hide_tray_check = QCheckBox(
            "隐身时一并隐藏托盘图标（卡片与托盘都不留痕迹）"
        )
        box.addWidget(self.privacy_hide_tray_check)

        self.privacy_switcher_check = QCheckBox(
            "从 Alt+Tab、Win+Tab 和任务栏预览中隐藏卡片"
        )
        box.addWidget(self.privacy_switcher_check)

        capability = support_mode() if is_supported_platform() else None
        version = windows_version_text()
        if capability == MODE_EXCLUDE:
            support_text = (
                f"当前系统：{version}　·　{MODE_LABELS[MODE_EXCLUDE]}"
                "。截图工具、微信/QQ 截图、录屏软件都拍不到卡片；"
                "窗口每次显示后都会自动重新应用保护。"
            )
            object_name = "successHint"
        elif capability == MODE_MONITOR:
            support_text = (
                f"当前系统：{version}　·　{MODE_LABELS[MODE_MONITOR]}"
                "。升级到 Windows 10 2004（build 19041）或更高版本可完全隐藏。"
            )
            object_name = "hint"
        else:
            support_text = "当前系统不支持 Windows 显示保护，隐私模式不会生效。"
            object_name = "hint"
        self.privacy_status = QLabel(support_text)
        self.privacy_status.setObjectName(object_name)
        self.privacy_status.setWordWrap(True)
        box.addWidget(self.privacy_status)

        check_row = QHBoxLayout()
        check_row.setSpacing(8)
        self.privacy_test_btn = QPushButton("检测当前保护状态")
        self.privacy_test_btn.clicked.connect(self._check_privacy)
        check_row.addWidget(self.privacy_test_btn)
        self.privacy_test_result = QLabel("")
        self.privacy_test_result.setObjectName("hint")
        self.privacy_test_result.setWordWrap(True)
        check_row.addWidget(self.privacy_test_result, 1)
        box.addLayout(check_row)

        note = QLabel(
            "说明：托盘图标被隐藏后，用“一键隐身/显示隐藏”快捷键恢复卡片，"
            "或重新运行 ScreenAnswer 也会把界面唤回来。任务管理器里的进程"
            "名称始终可见。"
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        box.addWidget(note)
        parent_layout.addWidget(frame)

    def _build_hotkey_section(self, parent_layout: QVBoxLayout) -> None:
        frame, box = self._new_section(
            "快捷键",
            "点击输入框后直接按下新的组合键。至少使用两个修饰键，"
            "例如 Ctrl+Alt+Q；单修饰键容易被其他软件占用。",
        )
        row = QHBoxLayout()
        row.setSpacing(10)
        capture_box = QVBoxLayout()
        capture_box.setSpacing(4)
        capture_box.addWidget(self._field_label("截图解答"))
        self.capture_key_edit = QKeySequenceEdit()
        self.capture_key_edit.setMaximumSequenceLength(1)
        self.capture_key_edit.setToolTip("例如 Ctrl+Alt+Q")
        capture_box.addWidget(self.capture_key_edit)
        row.addLayout(capture_box, 1)

        region_box = QVBoxLayout()
        region_box.setSpacing(4)
        region_box.addWidget(self._field_label("框选解答"))
        self.region_key_edit = QKeySequenceEdit()
        self.region_key_edit.setMaximumSequenceLength(1)
        self.region_key_edit.setToolTip("例如 Ctrl+Alt+S")
        region_box.addWidget(self.region_key_edit)
        row.addLayout(region_box, 1)
        box.addLayout(row)

        box.addWidget(self._field_label("显示 / 隐藏卡片"))
        self.toggle_key_edit = QKeySequenceEdit()
        self.toggle_key_edit.setMaximumSequenceLength(1)
        self.toggle_key_edit.setToolTip("例如 Ctrl+Alt+H")
        box.addWidget(self.toggle_key_edit)

        box.addWidget(self._field_label("一键隐身（卡片 + 托盘一起收起）"))
        self.panic_key_edit = QKeySequenceEdit()
        self.panic_key_edit.setMaximumSequenceLength(1)
        self.panic_key_edit.setToolTip("例如 Ctrl+Alt+Shift+X")
        box.addWidget(self.panic_key_edit)

        hint_row = QHBoxLayout()
        hint = QLabel(
            "如果按键被其他程序占用，保存时会提示你换一个组合。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        hint_row.addWidget(hint, 1)
        reset_hotkeys = QPushButton("恢复默认")
        reset_hotkeys.setObjectName("linkButton")
        reset_hotkeys.clicked.connect(self._reset_hotkeys)
        hint_row.addWidget(reset_hotkeys)
        box.addLayout(hint_row)
        parent_layout.addWidget(frame)

    def _build_prompt_section(self, parent_layout: QVBoxLayout) -> None:
        frame, box = self._new_section(
            "回答风格", "这段提示词会作为 system 消息发送给模型。"
        )
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText("留空则使用默认提示词")
        self.prompt_edit.setMinimumHeight(105)
        self.prompt_edit.setMaximumHeight(150)
        box.addWidget(self.prompt_edit)
        row = QHBoxLayout()
        row.addStretch(1)
        reset_btn = QPushButton("恢复默认")
        reset_btn.setObjectName("linkButton")
        reset_btn.clicked.connect(
            lambda: self.prompt_edit.setPlainText(DEFAULT_SYSTEM_PROMPT)
        )
        row.addWidget(reset_btn)
        box.addLayout(row)
        parent_layout.addWidget(frame)

    def _build_other_section(self, parent_layout: QVBoxLayout) -> None:
        frame, box = self._new_section("其他")
        self.startup_check = QCheckBox("开机时自动启动（登录后静默运行）")
        box.addWidget(self.startup_check)
        hint = QLabel(
            "开机启动后只显示托盘图标；按快捷键或双击托盘图标即可使用。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        box.addWidget(hint)
        parent_layout.addWidget(frame)

    # ------------------------------------------------------------ values
    def _load_values(self) -> None:
        settings = self.settings
        self.api_base_edit.setText(settings.api_base)
        self.model_edit.setText(settings.model)
        self.key_edit.setText(settings.api_key)
        index = self.mode_combo.findData(settings.mode)
        self.mode_combo.setCurrentIndex(max(0, index))
        index = self.ocr_lang_combo.findData(settings.ocr_language)
        self.ocr_lang_combo.setCurrentIndex(max(0, index))
        index = self.scope_combo.findData(settings.capture_scope)
        self.scope_combo.setCurrentIndex(max(0, index))
        self.prompt_edit.setPlainText(settings.system_prompt)
        self.startup_check.setChecked(settings.launch_at_startup)
        self.opacity_slider.setValue(
            max(10, min(100, round(settings.opacity * 100)))
        )
        self.opacity_value.setText(f"{self.opacity_slider.value()}%")
        self.width_spin.setValue(
            max(340, min(1400, settings.window_width))
        )
        self.height_spin.setValue(
            max(280, min(1000, settings.window_height))
        )
        self.font_size_spin.setValue(
            max(6, min(48, settings.answer_font_size))
        )
        theme_index = self.theme_combo.findData(settings.theme)
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        self.privacy_check.setChecked(settings.privacy_mode)
        self.privacy_hide_tray_check.setChecked(settings.privacy_hide_tray)
        self.privacy_switcher_check.setChecked(
            settings.privacy_hide_from_switcher
        )
        self._update_privacy_state()
        self.capture_key_edit.setKeySequence(
            QKeySequence(settings.hotkey_capture)
        )
        self.region_key_edit.setKeySequence(
            QKeySequence(settings.hotkey_region)
        )
        self.toggle_key_edit.setKeySequence(
            QKeySequence(settings.hotkey_toggle)
        )
        self.panic_key_edit.setKeySequence(
            QKeySequence(settings.hotkey_panic)
        )
        self._update_mode_hint()
        if not settings.api_key:
            self.key_edit.setFocus()
        else:
            self.api_base_edit.setFocus()

    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_value.setText(f"{value}%")
        self.opacity_preview.emit(value / 100.0)

    def _update_privacy_state(self) -> None:
        """Grey out the stealth sub-options when privacy mode is off."""
        enabled = self.privacy_check.isChecked()
        self.privacy_hide_tray_check.setEnabled(True)
        self.privacy_switcher_check.setEnabled(enabled)

    def _check_privacy(self) -> None:
        """Read the real display-affinity state back from Windows."""
        if not self.privacy_check.isChecked():
            self._set_privacy_result(
                "隐私模式未开启，卡片仍会出现在截图里。", ok=False
            )
            return
        guard = getattr(self.parent(), "privacy_guard", None)
        if guard is None:
            self._set_privacy_result("无法读取卡片窗口，请保存后重试。", ok=False)
            return
        guard.set_enabled(True, apply_now=True)
        active = guard.active
        mode = guard.mode
        if active:
            self._set_privacy_result(
                f"已生效：{MODE_LABELS.get(mode, mode)}。"
                "现在用截图工具或录屏软件检查一下，卡片不应出现。",
                ok=True,
            )
        else:
            self._set_privacy_result(
                "未生效"
                + (f"（{guard.last_error}）" if guard.last_error else "")
                + "。请确认卡片已经显示，然后重新检测。",
                ok=False,
            )

    def _set_privacy_result(self, text: str, ok: bool) -> None:
        self.privacy_test_result.setObjectName(
            "successHint" if ok else "errorHint"
        )
        self.privacy_test_result.setText(text)
        self.privacy_test_result.style().unpolish(self.privacy_test_result)
        self.privacy_test_result.style().polish(self.privacy_test_result)

    def _reset_size(self) -> None:
        self.width_spin.setValue(620)
        self.height_spin.setValue(420)

    def set_size_values(self, width: int, height: int) -> None:
        self.width_spin.setValue(max(340, min(1400, width)))
        self.height_spin.setValue(max(280, min(1000, height)))

    def _reset_hotkeys(self) -> None:
        self.capture_key_edit.setKeySequence(
            QKeySequence(DEFAULT_CAPTURE_HOTKEY)
        )
        self.region_key_edit.setKeySequence(
            QKeySequence(DEFAULT_REGION_HOTKEY)
        )
        self.toggle_key_edit.setKeySequence(
            QKeySequence(DEFAULT_TOGGLE_HOTKEY)
        )
        self.panic_key_edit.setKeySequence(
            QKeySequence(DEFAULT_PANIC_HOTKEY)
        )

    def _hotkey_text(self, edit: QKeySequenceEdit) -> str:
        return edit.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText
        )

    def _collect(self) -> Settings:
        return replace(
            self.settings,
            api_base=self.api_base_edit.text().strip(),
            api_key=self.key_edit.text().strip(),
            model=self.model_edit.text().strip(),
            mode=str(self.mode_combo.currentData()),
            ocr_language=str(self.ocr_lang_combo.currentData() or ""),
            capture_scope=str(self.scope_combo.currentData()),
            system_prompt=self.prompt_edit.toPlainText().strip()
            or DEFAULT_SYSTEM_PROMPT,
            launch_at_startup=self.startup_check.isChecked(),
            opacity=self.opacity_slider.value() / 100.0,
            window_width=self.width_spin.value(),
            window_height=self.height_spin.value(),
            answer_font_size=self.font_size_spin.value(),
            privacy_mode=self.privacy_check.isChecked(),
            privacy_hide_tray=self.privacy_hide_tray_check.isChecked(),
            privacy_hide_from_switcher=self.privacy_switcher_check.isChecked(),
            theme=str(self.theme_combo.currentData()),
            hotkey_capture=normalize_hotkey(
                self._hotkey_text(self.capture_key_edit)
            ),
            hotkey_region=normalize_hotkey(
                self._hotkey_text(self.region_key_edit)
            ),
            hotkey_toggle=normalize_hotkey(
                self._hotkey_text(self.toggle_key_edit)
            ),
            hotkey_panic=normalize_hotkey(
                self._hotkey_text(self.panic_key_edit)
            ),
        )

    def _validate_hotkeys(self) -> tuple[str, str, str, str] | None:
        capture_raw = self._hotkey_text(self.capture_key_edit)
        region_raw = self._hotkey_text(self.region_key_edit)
        toggle_raw = self._hotkey_text(self.toggle_key_edit)
        panic_raw = self._hotkey_text(self.panic_key_edit)
        raw_values = (
            ("截图解答", capture_raw),
            ("框选解答", region_raw),
            ("显示/隐藏", toggle_raw),
            ("一键隐身", panic_raw),
        )
        for label, text in raw_values:
            error = validate_hotkey(text)
            if error:
                self._show_dialog_error(f"{label}快捷键：{error}")
                return None
        capture = normalize_hotkey(capture_raw)
        region = normalize_hotkey(region_raw)
        toggle = normalize_hotkey(toggle_raw)
        panic = normalize_hotkey(panic_raw)
        if len({capture, region, toggle, panic}) < 4:
            self._show_dialog_error("四个功能不能使用同一个快捷键。")
            return None
        for label, text in (
            ("截图解答", capture),
            ("框选解答", region),
            ("显示/隐藏", toggle),
            ("一键隐身", panic),
        ):
            if not probe_hotkey(text):
                self._show_dialog_error(
                    f"{label}快捷键 {text} 已被其他程序占用，请换一个组合。"
                )
                return None
        self._clear_dialog_error()
        return capture, region, toggle, panic

    def _show_dialog_error(self, message: str) -> None:
        self.dialog_status.setObjectName("errorHint")
        self.dialog_status.setText(message)
        self.dialog_status.show()
        self.dialog_status.style().unpolish(self.dialog_status)
        self.dialog_status.style().polish(self.dialog_status)

    def _clear_dialog_error(self) -> None:
        self.dialog_status.clear()
        self.dialog_status.hide()

    def _update_mode_hint(self) -> None:
        mode = self.mode_combo.currentData()
        if mode == "vision":
            self.mode_hint.setText(
                "截图会直接作为图片发送给模型。请使用支持图片输入的模型，"
                "例如 GPT-4o、Qwen-VL、Gemini 等。"
            )
        else:
            self.mode_hint.setText(
                "先用 Windows 本地 OCR 提取文字，再发给文本模型。"
                "速度快、费用低，适合 DeepSeek 等文本模型。"
            )

    def _toggle_key_visibility(self) -> None:
        self._key_visible = not self._key_visible
        self.key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal
            if self._key_visible
            else QLineEdit.EchoMode.Password
        )
        self._eye_action.setIcon(
            glyph_icon("eye_off" if self._key_visible else "eye", "#64748b", 17)
        )
        self._eye_action.setToolTip(
            "隐藏密钥" if self._key_visible else "显示密钥"
        )

    # ------------------------------------------------------------- test
    def _test_connection(self) -> None:
        if self._test_worker is not None:
            return
        settings = self._collect()
        if not settings.endpoint:
            self.test_result.setObjectName("errorHint")
            self.test_result.setText("请先填写 API 地址")
            self._repolish_result()
            return
        if not settings.model:
            self.test_result.setObjectName("errorHint")
            self.test_result.setText("请先填写模型名称")
            self._repolish_result()
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中…")
        self.test_result.setObjectName("hint")
        self.test_result.setText("正在连接接口…")
        self._repolish_result()
        worker = AIWorker(settings=settings, test=True)
        worker.done.connect(self._test_ok)
        worker.failed.connect(self._test_failed)
        worker.finished.connect(self._test_finished)
        self._test_worker = worker
        worker.start()

    def _repolish_result(self) -> None:
        self.test_result.style().unpolish(self.test_result)
        self.test_result.style().polish(self.test_result)

    def _test_ok(self, text: str, _meta) -> None:
        self.test_result.setObjectName("successHint")
        self.test_result.setText(f"连接成功：{text.strip()[:60]}")
        self._repolish_result()

    def _test_failed(self, message: str) -> None:
        self.test_result.setObjectName("errorHint")
        self.test_result.setText(message)
        self._repolish_result()

    def _test_finished(self) -> None:
        self.test_btn.setEnabled(True)
        self.test_btn.setText("测试连接")
        if self._test_worker is not None:
            self._test_worker.deleteLater()
            self._test_worker = None

    # ------------------------------------------------------------- save
    def _save(self) -> None:
        hotkeys = self._validate_hotkeys()
        if hotkeys is None:
            return
        settings = replace(
            self._collect(),
            hotkey_capture=hotkeys[0],
            hotkey_region=hotkeys[1],
            hotkey_toggle=hotkeys[2],
            hotkey_panic=hotkeys[3],
        )
        if not settings.endpoint:
            self.test_result.setObjectName("errorHint")
            self.test_result.setText("API 地址不能为空")
            self._repolish_result()
            return
        if not (
            settings.endpoint.startswith("https://")
            or settings.endpoint.startswith("http://")
        ):
            self.test_result.setObjectName("errorHint")
            self.test_result.setText("API 地址必须以 http:// 或 https:// 开头")
            self._repolish_result()
            return
        if not settings.model:
            self.test_result.setObjectName("errorHint")
            self.test_result.setText("模型名称不能为空")
            self._repolish_result()
            return
        try:
            save_settings(settings)
        except Exception as exc:
            logger.exception("Could not save settings")
            self.test_result.setObjectName("errorHint")
            self.test_result.setText(f"保存失败：{exc}")
            self._repolish_result()
            return
        try:
            apply_startup(settings.launch_at_startup)
        except Exception:
            logger.exception("Could not update startup setting")
        self._clear_dialog_error()
        self.saved.emit(settings)
        self.accept()

    # ------------------------------------------------------------ modal
    def showEvent(self, event) -> None:
        super().showEvent(event)
        enable_dark_title_bar(self, dark=self.settings.theme != "light")
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                min(660, available.width() - 40),
                min(760, available.height() - 60),
            )
            self.move(
                available.center().x() - self.width() // 2,
                available.center().y() - self.height() // 2,
            )

    def reject(self) -> None:
        self.opacity_preview.emit(self._original_opacity)
        self._stop_test()
        super().reject()

    def accept(self) -> None:
        self._stop_test()
        super().accept()

    def _stop_test(self) -> None:
        if self._test_worker is None:
            return
        worker = self._test_worker
        self._test_worker = None
        worker.cancel()
        if worker.wait(800):
            worker.deleteLater()
            return
        # A network read can outlive the dialog. Detach every signal and keep
        # the thread referenced until it finishes on its own.
        for signal, slot in (
            (worker.done, self._test_ok),
            (worker.failed, self._test_failed),
            (worker.finished, self._test_finished),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        _DETACHED_TESTS.add(worker)

        def cleanup() -> None:
            _DETACHED_TESTS.discard(worker)
            worker.deleteLater()

        worker.finished.connect(cleanup)

