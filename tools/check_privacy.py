"""Probe Windows display protection for the current session.

Run from the repository root:

    .\\.venv\\Scripts\\python.exe tools\\check_privacy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget

from screenanswer import privacy

def main() -> int:
    app = QApplication(sys.argv)
    print("system      :", privacy.windows_version_text())
    print("support     :", privacy.support_mode(), "->", privacy.resolve_mode("auto"))
    print("labels      :", privacy.MODE_LABELS.get(privacy.support_mode()))

    window = QWidget()
    window.setWindowFlags(
        Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
    )
    window.setWindowTitle("ScreenAnswer privacy probe")
    window.resize(260, 120)
    window.show()
    app.processEvents()

    guard = privacy.PrivacyGuard()
    guard.attach(window)
    guard.set_enabled(True)
    app.processEvents()
    print("affinity    :", privacy.affinity_of(window))
    print("guard active:", guard.active, "|", guard.last_error or "ok")

    privacy.hide_from_task_switcher(window, True)
    print("switcher    : hidden from Alt+Tab / Win+Tab / peek")

    guard.set_enabled(False)
    app.processEvents()
    print("released    :", privacy.affinity_of(window))

    QTimer.singleShot(300, app.quit)
    app.exec()
    return 0 if privacy.support_mode() != privacy.MODE_UNSUPPORTED else 1


if __name__ == "__main__":
    raise SystemExit(main())
