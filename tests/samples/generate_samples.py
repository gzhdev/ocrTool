"""生成 tests/samples/ 下的测试样本图（mvp-image-ocr 任务 0.2）。

可重复执行：样本内容确定性生成，覆盖六类输入——中文、英文、中英混合、
小字号、无文字、超大尺寸（最长边超过默认上限 6000px，用于触发缩放路径）。

用法：uv run python tests/samples/generate_samples.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SAMPLES_DIR = Path(__file__).resolve().parent
MAX_EDGE = 6000


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_image(lines: list[str], size: int = 48, margin: int = 40) -> Image.Image:
    width = max(len(line) for line in lines) * size + margin * 2
    height = margin * 2 + size * len(lines) * 2
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = _font(size)
    for index, line in enumerate(lines):
        draw.text((margin, margin + index * size * 2), line, fill="black", font=font)
    return img


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    _text_image(["全中文样本第一行", "第二行包含标点，测试。"]).save(
        SAMPLES_DIR / "chinese.png"
    )
    _text_image(["The quick brown fox", "jumps over the lazy dog."]).save(
        SAMPLES_DIR / "english.png"
    )
    _text_image(["OCRTool MVP Sample 2026", "中英文混合识别测试行"]).save(
        SAMPLES_DIR / "mixed.png"
    )
    _text_image(["Small text at fourteen pixels", "小字号十四像素文本行"], size=14).save(
        SAMPLES_DIR / "small_text.png"
    )

    # 无文字：灰度渐变，确保存在非平凡图像内容但不含可检出文本
    gradient = Image.new("RGB", (400, 300))
    for x in range(400):
        shade = int(x / 399 * 255)
        for y in range(300):
            gradient.putpixel((x, y), (shade, shade, shade))
    gradient.save(SAMPLES_DIR / "no_text.png")

    # 超大尺寸：最长边超过默认上限，载入时必须触发等比缩放路径
    big = _text_image(["Oversized sample line"], size=48)
    big.resize((MAX_EDGE + 400, int(big.height * (MAX_EDGE + 400) / big.width))).save(
        SAMPLES_DIR / "oversized.png"
    )

    # 验证：全部样本可被图像库正常解码
    for path in sorted(SAMPLES_DIR.glob("*.png")):
        with Image.open(path) as img:
            img.load()
            print(f"OK {path.name} {img.width}x{img.height}")


if __name__ == "__main__":
    main()
