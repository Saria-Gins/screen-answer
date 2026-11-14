from __future__ import annotations

import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from screenanswer.hotkey import (
    HOTKEY_CAPTURE_ID,
    HOTKEY_REGION_ID,
    HOTKEY_TOGGLE_ID,
    WM_HOTKEY,
    GlobalHotkeys,
)

app = QApplication(sys.argv)
hotkeys = GlobalHotkeys(app)
failures = hotkeys.register(
    "Ctrl+Alt+Q", "Ctrl+Alt+S", "Ctrl+Alt+H"
)
print("failures:", failures)
print(
    "labels:",
    hotkeys.capture_label,
    hotkeys.region_label,
    hotkeys.toggle_label,
)
fired: list[str] = []
hotkeys.capture_full.connect(lambda: fired.append("full"))
hotkeys.capture_region.connect(lambda: fired.append("region"))
hotkeys.toggle_requested.connect(lambda: fired.append("toggle"))


def post(hotkey_id: int) -> None:
    thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
    ctypes.windll.user32.PostThreadMessageW(
        thread_id, WM_HOTKEY, hotkey_id, 0
    )


def finish() -> None:
    print("fired:", fired)
    hotkeys.unregister()
    app.quit()


QTimer.singleShot(250, lambda: post(HOTKEY_CAPTURE_ID))
QTimer.singleShot(500, lambda: post(HOTKEY_REGION_ID))
QTimer.singleShot(750, lambda: post(HOTKEY_TOGGLE_ID))
QTimer.singleShot(1200, finish)
raise SystemExit(app.exec())
