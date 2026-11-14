"""Visual theme for the answer card and settings window."""

from __future__ import annotations

BG = "#070d18"
CARD_TOP = "#111d31"
CARD_BOTTOM = "#0a1220"
TEXT = "#e8effa"
MUTED = "#94a3b8"
SUBTLE = "#64748b"
ACCENT = "#38bdf8"
ACCENT_STRONG = "#22d3ee"
BORDER = "rgba(148, 163, 184, 0.16)"
ERROR = "#fb7185"
SUCCESS = "#34d399"

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", sans-serif'

APP_QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    color: {TEXT};
    outline: none;
}}
QWidget {{
    background: transparent;
}}
QFrame#card {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {CARD_TOP}, stop:0.55 #0d1728, stop:1 {CARD_BOTTOM});
    border: 1px solid {BORDER};
    border-radius: 18px;
}}
QLabel {{
    background: transparent;
    font-size: 13px;
}}
QLabel#appTitle {{
    font-size: 13px;
    font-weight: 700;
    color: #f8fbff;
    letter-spacing: 0.2px;
}}
QLabel#subtitle {{
    font-size: 11px;
    color: {MUTED};
}}
QLabel#sectionTitle {{
    font-size: 12px;
    font-weight: 700;
    color: #cbd5e1;
    letter-spacing: 0.4px;
}}
QLabel#hint {{
    font-size: 11px;
    color: {SUBTLE};
    line-height: 1.5;
}}
QLabel#status {{
    font-size: 12px;
    color: {MUTED};
}}
QLabel#statusBusy {{
    font-size: 12px;
    color: {ACCENT};
}}
QLabel#statusError {{
    font-size: 12px;
    color: {ERROR};
}}
QLabel#footer {{
    font-size: 10px;
    color: #52627a;
}}
QLabel#pill {{
    background: rgba(56, 189, 248, 0.10);
    border: 1px solid rgba(56, 189, 248, 0.22);
    border-radius: 8px;
    padding: 2px 7px;
    color: #7dd3fc;
    font-size: 10px;
}}
QLabel#keyHint {{
    color: {SUBTLE};
    font-size: 10px;
}}
QFrame#divider {{
    background: {BORDER};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}
QFrame#ocrPanel {{
    background: rgba(2, 6, 23, 0.28);
    border: 1px solid rgba(148, 163, 184, 0.10);
    border-radius: 11px;
}}
QTextBrowser#answer {{
    background: transparent;
    border: none;
    padding: 2px 4px 2px 0px;
    selection-background-color: rgba(56, 189, 248, 0.35);
}}
QPlainTextEdit#ocrText {{
    background: transparent;
    border: none;
    padding: 2px 6px;
    color: #9fb0c5;
    font-size: 12px;
    selection-background-color: rgba(56, 189, 248, 0.35);
}}
QPushButton {{
    background: rgba(148, 163, 184, 0.08);
    border: 1px solid rgba(148, 163, 184, 0.14);
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 11px;
    color: #d7e2f0;
}}
QPushButton:hover {{
    background: rgba(148, 163, 184, 0.15);
    border-color: rgba(148, 163, 184, 0.26);
}}
QPushButton:pressed {{
    background: rgba(148, 163, 184, 0.22);
}}
QPushButton:disabled {{
    color: #58677b;
    background: rgba(148, 163, 184, 0.04);
    border-color: rgba(148, 163, 184, 0.07);
}}
QPushButton[role="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0ea5e9, stop:1 #22d3ee);
    border: 1px solid rgba(125, 211, 252, 0.50);
    color: #04121f;
    font-weight: 700;
    font-size: 11px;
    padding: 5px 12px;
}}
QPushButton[role="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #38bdf8, stop:1 #67e8f9);
}}
QPushButton[role="primary"]:pressed {{
    background: #0284c7;
}}
QPushButton[role="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {MUTED};
    padding: 6px 8px;
}}
QPushButton[role="ghost"]:hover {{
    color: {TEXT};
    background: rgba(148, 163, 184, 0.10);
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px;
}}
QToolButton:hover {{
    background: rgba(148, 163, 184, 0.13);
    border-color: rgba(148, 163, 184, 0.10);
}}
QToolButton:pressed {{
    background: rgba(148, 163, 184, 0.20);
}}
QToolButton#ocrToggle {{
    color: {MUTED};
    font-size: 11px;
    text-align: left;
    padding: 4px 6px;
}}
QToolButton#ocrToggle:hover {{
    color: {TEXT};
}}
QToolButton#retryButton {{
    color: {ACCENT};
    font-size: 11px;
    padding: 2px 4px;
}}
QToolButton#retryButton:hover {{
    color: #e0f2fe;
}}
QProgressBar {{
    border: none;
    background: rgba(148, 163, 184, 0.09);
    border-radius: 2px;
    max-height: 3px;
    min-height: 3px;
}}
QProgressBar::chunk {{
    border-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0ea5e9, stop:1 #22d3ee);
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(148, 163, 184, 0.28);
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(148, 163, 184, 0.45);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    background: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    height: 8px;
    background: transparent;
}}
QScrollBar::handle:horizontal {{
    background: rgba(148, 163, 184, 0.28);
    border-radius: 4px;
    min-width: 28px;
}}
"""

SETTINGS_QSS = f"""
QDialog {{
    background: #0b1322;
}}
QWidget {{
    font-family: {FONT_FAMILY};
    color: {TEXT};
    font-size: 12px;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QLabel#dialogTitle {{
    font-size: 19px;
    font-weight: 700;
    color: #f8fbff;
}}
QLabel#dialogSubtitle {{
    font-size: 11px;
    color: {MUTED};
}}
QLabel#sectionTitle {{
    font-size: 12px;
    font-weight: 700;
    color: #cbd5e1;
    letter-spacing: 0.4px;
}}
QLabel#hint {{
    font-size: 11px;
    color: {SUBTLE};
}}
QLabel#fieldLabel {{
    color: #cbd5e1;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#linkButton {{
    background: transparent;
    border: none;
    color: #7dd3fc;
    font-size: 11px;
    padding: 2px 4px;
}}
QPushButton#linkButton:hover {{
    color: #e0f2fe;
}}
QLabel#errorHint {{
    font-size: 11px;
    color: {ERROR};
}}
QLabel#successHint {{
    font-size: 11px;
    color: {SUCCESS};
}}
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QKeySequenceEdit {{
    background: rgba(2, 6, 23, 0.55);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: rgba(56, 189, 248, 0.35);
    font-size: 12px;
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus,
QKeySequenceEdit:focus {{
    border-color: rgba(56, 189, 248, 0.65);
    background: rgba(2, 6, 23, 0.78);
}}
QKeySequenceEdit {{
    padding: 0;
    border: none;
    background: transparent;
}}
QKeySequenceEdit QLineEdit {{
    background: rgba(2, 6, 23, 0.55);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 8px;
    padding: 7px 9px;
}}
QKeySequenceEdit QLineEdit:focus {{
    border-color: rgba(56, 189, 248, 0.65);
    background: rgba(2, 6, 23, 0.78);
}}
QSpinBox {{
    padding-right: 22px;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: rgba(148, 163, 184, 0.18);
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: #0ea5e9;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
    background: #38bdf8;
}}
QSlider::handle:horizontal:hover {{
    background: #7dd3fc;
}}
QLineEdit:disabled {{
    color: #64748b;
}}
QComboBox {{
    padding-right: 24px;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: #111c2e;
    border: 1px solid rgba(148, 163, 184, 0.22);
    border-radius: 8px;
    selection-background-color: rgba(56, 189, 248, 0.22);
    padding: 4px;
    outline: none;
}}
QCheckBox {{
    spacing: 8px;
    color: #cbd5e1;
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid rgba(148, 163, 184, 0.35);
    background: rgba(2, 6, 23, 0.55);
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: none;
}}
QPushButton {{
    background: rgba(148, 163, 184, 0.09);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 12px;
}}
QPushButton:hover {{
    background: rgba(148, 163, 184, 0.16);
}}
QPushButton[role="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0ea5e9, stop:1 #22d3ee);
    border: 1px solid rgba(125, 211, 252, 0.50);
    color: #04121f;
    font-weight: 700;
}}
QPushButton[role="primary"]:hover {{
    background: #38bdf8;
}}
QPushButton:disabled {{
    color: #58677b;
}}
QFrame#section {{
    background: rgba(15, 23, 42, 0.45);
    border: 1px solid rgba(148, 163, 184, 0.10);
    border-radius: 12px;
}}
QToolButton#eyeButton {{
    border: none;
    background: transparent;
    padding: 2px 6px;
    color: {MUTED};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(148, 163, 184, 0.28);
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
"""

ANSWER_DOCUMENT_CSS = f"""
body {{
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}}
p {{ margin: 0 0 8px 0; }}
h1, h2, h3, h4 {{ color: #f8fbff; margin: 9px 0 5px 0; }}
strong {{ color: #f8fbff; }}
a {{ color: {ACCENT}; }}
code {{
    background: rgba(2, 6, 23, 0.7);
    color: #bae6fd;
    font-family: "Cascadia Code", Consolas, monospace;
}}
pre {{
    background: rgba(2, 6, 23, 0.72);
    border: 1px solid rgba(148, 163, 184, 0.14);
    padding: 8px;
}}
blockquote {{
    color: {MUTED};
    border-left: 2px solid rgba(56, 189, 248, 0.45);
    margin-left: 2px;
    padding-left: 8px;
}}
li {{ margin-bottom: 3px; }}
table {{ border-collapse: collapse; }}
th, td {{
    border: 1px solid rgba(148, 163, 184, 0.22);
    padding: 4px 7px;
}}
th {{ background: rgba(148, 163, 184, 0.10); }}
"""

CARD_LIGHT_QSS = """
QFrame#card {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #ffffff, stop:0.6 #ffffff, stop:1 #f5f8fc);
    border: 1px solid #d8e2ef;
    border-radius: 18px;
}
QLabel {
    color: #1f2937;
}
QLabel#appTitle {
    color: #0b1220;
}
QLabel#subtitle {
    color: #64748b;
}
QLabel#hint {
    color: #64748b;
}
QLabel#status {
    color: #475569;
}
QLabel#statusBusy {
    color: #0369a1;
}
QLabel#statusError {
    color: #dc2626;
}
QLabel#footer {
    color: #94a3b8;
}
QLabel#pill {
    background: #eff6ff;
    border-color: #bfdbfe;
    color: #0369a1;
}
QFrame#divider {
    background: #e2e8f0;
}
QFrame#ocrPanel {
    background: #f8fafc;
    border-color: #e2e8f0;
}
QTextBrowser#answer {
    color: #111827;
}
QPlainTextEdit#ocrText {
    color: #475569;
}
QPushButton {
    background: #f1f5f9;
    border-color: #d8e2ef;
    color: #0f172a;
}
QPushButton:hover {
    background: #e2e8f0;
    border-color: #cbd5e1;
}
QPushButton:pressed {
    background: #cbd5e1;
}
QPushButton:disabled {
    color: #94a3b8;
    background: #f8fafc;
    border-color: #e8edf4;
}
QPushButton[role="primary"] {
    background: #0f172a;
    border-color: #0f172a;
    color: #ffffff;
}
QPushButton[role="primary"]:hover {
    background: #1e293b;
}
QPushButton[role="primary"]:pressed {
    background: #334155;
}
QPushButton[role="ghost"] {
    color: #64748b;
}
QPushButton[role="ghost"]:hover {
    color: #0f172a;
    background: #eef2f7;
}
QToolButton:hover {
    background: #eef2f7;
    border-color: #e2e8f0;
}
QToolButton:pressed {
    background: #e2e8f0;
}
QToolButton#ocrToggle {
    color: #475569;
}
QToolButton#ocrToggle:hover {
    color: #0f172a;
}
QToolButton#retryButton {
    color: #0369a1;
}
QToolButton#retryButton:hover {
    color: #0c4a6e;
}
QProgressBar {
    background: #e2e8f0;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1;
}
"""

SETTINGS_LIGHT_QSS = """
QDialog {
    background: #f5f7fb;
}
QWidget {
    color: #1f2937;
}
QLabel {
    color: #1f2937;
}
QLabel#dialogTitle {
    color: #0b1220;
}
QLabel#dialogSubtitle {
    color: #64748b;
}
QLabel#sectionTitle {
    color: #334155;
}
QLabel#hint {
    color: #64748b;
}
QLabel#fieldLabel {
    color: #475569;
}
QPushButton#linkButton {
    background: transparent;
    border: none;
    color: #0369a1;
    font-size: 11px;
    padding: 2px 4px;
}
QPushButton#linkButton:hover {
    color: #0c4a6e;
}
QLabel#errorHint {
    color: #dc2626;
}
QLabel#successHint {
    color: #047857;
}
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QKeySequenceEdit {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    color: #111827;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus,
QKeySequenceEdit:focus {
    border-color: #0284c7;
    background: #ffffff;
}
QKeySequenceEdit {
    background: transparent;
    border: none;
}
QKeySequenceEdit QLineEdit {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    color: #111827;
}
QKeySequenceEdit QLineEdit:focus {
    border-color: #0284c7;
    background: #ffffff;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    color: #111827;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
}
QCheckBox {
    color: #334155;
}
QCheckBox::indicator {
    background: #ffffff;
    border: 1px solid #94a3b8;
}
QCheckBox::indicator:checked {
    background: #0284c7;
    border-color: #0284c7;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d8e2ef;
    color: #0f172a;
}
QPushButton:hover {
    background: #eef2f7;
}
QPushButton[role="primary"] {
    background: #0f172a;
    border-color: #0f172a;
    color: #ffffff;
}
QPushButton[role="primary"]:hover {
    background: #1e293b;
}
QPushButton:disabled {
    color: #94a3b8;
}
QFrame#section {
    background: #ffffff;
    border: 1px solid #e2e8f0;
}
QFrame#footerBar {
    border-top: 1px solid #e2e8f0;
}
QToolButton#eyeButton {
    color: #64748b;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
"""

ANSWER_DOCUMENT_CSS_LIGHT = """
body {
    color: #111827;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}
p { margin: 0 0 8px 0; }
h1, h2, h3, h4 { color: #0b1220; margin: 9px 0 5px 0; }
strong { color: #0b1220; }
a { color: #0369a1; }
code {
    background: #eef2f7;
    color: #0f172a;
    font-family: "Cascadia Code", Consolas, monospace;
}
pre {
    background: #f8fafc;
    border: 1px solid #dbe4ef;
    padding: 8px;
}
blockquote {
    color: #475569;
    border-left: 2px solid #7dd3fc;
    margin-left: 2px;
    padding-left: 8px;
}
li { margin-bottom: 3px; }
table { border-collapse: collapse; }
th, td {
    border: 1px solid #cbd5e1;
    padding: 4px 7px;
}
th { background: #f1f5f9; }
"""
