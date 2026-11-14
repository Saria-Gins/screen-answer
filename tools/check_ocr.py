from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from screenanswer.ocr import available_languages, recognize_image  # noqa: E402


def make_sample() -> Path:
    image = Image.new("RGB", (1280, 720), "#f7f4ec")
    draw = ImageDraw.Draw(image)
    fonts = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    font_path = next((p for p in fonts if Path(p).exists()), None)
    title_font = ImageFont.truetype(font_path, 54) if font_path else None
    body_font = ImageFont.truetype(font_path, 34) if font_path else None
    draw.text((90, 70), "第 1 题  求下列方程的解", fill="#20242c", font=title_font)
    draw.text((90, 190), "已知 3x + 5 = 20，求 x 的值。", fill="#20242c", font=body_font)
    draw.text((90, 280), "A. 3      B. 5      C. 7      D. 15", fill="#20242c", font=body_font)
    draw.text((90, 390), "请给出答案，并写出简要步骤。", fill="#4a5568", font=body_font)
    path = ROOT / "tools" / "ocr-sample.png"
    image.save(path)
    return path


if __name__ == "__main__":
    print("Languages:", [(x.tag, x.display_name) for x in available_languages()])
    sample = make_sample()
    print("Sample:", sample)
    result = recognize_image(sample)
    print("Error:", result.error)
    print("Language:", result.language, "Lines:", result.line_count)
    print("---TEXT---")
    print(result.text)
