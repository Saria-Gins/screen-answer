from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screenanswer.ui.icons import _app_pixmap  # noqa: E402

app = QApplication([])
assets = ROOT / "assets"
assets.mkdir(exist_ok=True)
png = assets / "icon.png"
_app_pixmap(256).save(str(png), "PNG")
image = Image.open(png).convert("RGBA")
image.save(
    assets / "icon.ico",
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print(assets / "icon.ico")
