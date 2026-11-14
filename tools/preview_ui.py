from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtGui import QFont, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screenanswer.config import Settings  # noqa: E402
from screenanswer.theme import APP_QSS  # noqa: E402
from screenanswer.ui.card import AnswerCard  # noqa: E402
from screenanswer.ui.icons import app_icon  # noqa: E402
from screenanswer.ui.settings import SettingsDialog  # noqa: E402

SAMPLE = """### 最终答案：x = 5

由 **3x + 5 = 20**：

1. 两边同时减去 5：`3x = 15`
2. 两边同时除以 3：`x = 5`

所以正确选项是 **B. 5**。

> 验算：3 × 5 + 5 = 20，成立。
"""


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(APP_QSS)
    app.setWindowIcon(app_icon())

    card = AnswerCard()
    card.place_default(480, 650)
    card.set_ocr_text(
        "第 1 题 求下列方程的解\n已知 3x + 5 = 20，求 x 的值。\n"
        "B. 5 C. 7 D. 15\n请给出答案，并写出简要步骤。",
        "zh-Hans-CN · 4 行 · 0.10s",
    )
    card.finish_answer(SAMPLE, "deepseek-chat · 1.8s")
    card.show()
    card.raise_()

    dialog = SettingsDialog(Settings(api_key="sk-demo-not-real"))
    dialog.saved.connect(lambda _settings: None)
    dialog.show()
    dialog.move(80, 40)

    def capture() -> None:
        out = ROOT / "tools" / "preview"
        out.mkdir(exist_ok=True)
        card.grab().save(str(out / "card.png"))
        dialog.grab().save(str(out / "settings.png"))
        print("saved")
        app.quit()

    QTimer.singleShot(1200, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
