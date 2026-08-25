"""生成多尺寸托盘图标（一次性资源脚本，产物入库）。

以 256px 基准绘制（蓝底圆角方块 + 白色「文」字，呼应 OCR 文字识别），
缩放出 16/24/32/48 尺寸。托盘在高 DPI 下按显示器缩放自动取用最接近
尺寸，避免单张 16px 位图被拉伸模糊（任务 2.1）。

用法：uv run python scripts/gen_tray_icon.py
产物：resources/icons/tray-{16,24,32,48,256}.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "resources" / "icons"
SIZES = (16, 24, 32, 48, 256)
BASE = 256
BG_COLOR = (37, 99, 235, 255)  # 蓝 #2563EB
FG_COLOR = (255, 255, 255, 255)
CORNER_RATIO = 0.22
FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_base() -> Image.Image:
    """绘制 256px 基准图。"""
    img = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(BASE * CORNER_RATIO)
    draw.rounded_rectangle((0, 0, BASE - 1, BASE - 1), radius=radius, fill=BG_COLOR)
    font = _load_font(int(BASE * 0.62))
    bbox = draw.textbbox((0, 0), "文", font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((BASE - text_w) / 2 - bbox[0], (BASE - text_h) / 2 - bbox[1]),
        "文",
        fill=FG_COLOR,
        font=font,
    )
    return img


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = draw_base()
    for size in SIZES:
        icon = base if size == BASE else base.resize(
            (size, size), Image.LANCZOS
        )
        target = OUTPUT_DIR / f"tray-{size}.png"
        icon.save(target)
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
