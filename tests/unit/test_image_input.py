"""utils/image.py：格式白名单、双重校验与等比缩放（任务 3.1 / 3.2）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QUrl

from ocrtool.ocr.exceptions import InvalidImageError
from ocrtool.utils.image import (
    DEFAULT_MAX_EDGE,
    SUPPORTED_EXTENSIONS,
    qimage_to_bgr,
    scale_to_limit,
    validate_and_load,
    validate_dropped_urls,
)


def make_png(path: Path, size: tuple[int, int] = (10, 8), color=(255, 0, 0)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


class TestFormatWhitelist:
    @pytest.mark.parametrize("ext", sorted(SUPPORTED_EXTENSIONS))
    def test_受支持格式全部通过双重校验(self, tmp_path, ext, qapp):
        source = make_png(tmp_path / "source.png")
        target = source.with_suffix(ext)
        if ext != ".png":
            source.replace(target)
        image = validate_and_load(target)
        assert not image.isNull()

    @pytest.mark.parametrize("ext", [".gif", ".tiff", ".pdf", ".svg", ".txt"])
    def test_不受支持格式被拒绝(self, tmp_path, ext):
        source = make_png(tmp_path / "source.png")
        target = source.with_suffix(ext)
        if ext != ".png":
            source.replace(target)
        with pytest.raises(InvalidImageError, match="不支持的图像格式"):
            validate_and_load(target)

    def test_扩展名合法但内容损坏(self, tmp_path):
        broken = tmp_path / "broken.png"
        broken.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png-payload")
        with pytest.raises(InvalidImageError, match="图像无法读取"):
            validate_and_load(broken)

    @pytest.mark.parametrize("real_ext", sorted(SUPPORTED_EXTENSIONS))
    def test_扩展名与内容不符时以可解码性为准(self, tmp_path, real_ext, qapp):
        """真实为受支持格式、扩展名被改写为另一受支持格式 → 正常载入。"""
        source = make_png(tmp_path / "source.png")
        renamed = source.with_suffix(real_ext)
        if real_ext != ".png":
            source.replace(renamed)
        image = validate_and_load(renamed)
        assert image.width() == 10 and image.height() == 8


class TestScaleToLimit:
    def test_未超限图像不缩放且比例为_1(self):
        image = np.zeros((400, 300, 3), dtype=np.uint8)
        scaled, scale = scale_to_limit(image, DEFAULT_MAX_EDGE)
        assert scale == 1.0
        assert scaled is image

    def test_超限图被等比缩放至上限内(self):
        width, height = 6400, 800
        image = np.zeros((height, width, 3), dtype=np.uint8)
        scaled, scale = scale_to_limit(image, 6000)
        new_height, new_width = scaled.shape[:2]
        assert max(new_width, new_height) <= 6000
        assert scale == pytest.approx(6000 / 6400, rel=1e-3)
        # 等比：宽高比保持
        assert new_width / new_height == pytest.approx(width / height, rel=0.01)
        assert scale < 1.0

    def test_纵向超限同样处理(self):
        image = np.zeros((9000, 500, 3), dtype=np.uint8)
        scaled, scale = scale_to_limit(image, 6000)
        new_height, new_width = scaled.shape[:2]
        assert new_height <= 6000
        assert scale == pytest.approx(6000 / 9000, rel=1e-3)

    def test_上限可配置(self):
        image = np.zeros((100, 4000, 3), dtype=np.uint8)
        scaled, scale = scale_to_limit(image, 2000)
        assert scaled.shape[1] <= 2000
        assert scale == pytest.approx(0.5, rel=1e-3)


class TestQImageToBgr:
    def test_转换得到正确形状与颜色(self, tmp_path, qapp):
        from PySide6.QtGui import QImage

        make_png(tmp_path / "red.png", size=(10, 8), color=(255, 0, 0))
        image = QImage(str(tmp_path / "red.png"))
        bgr = qimage_to_bgr(image)
        assert bgr.shape == (8, 10, 3)
        # 纯红 RGB → BGR 通道翻转
        assert tuple(bgr[0, 0]) == (0, 0, 255)

    def test_奇数宽度行对齐正确(self, tmp_path, qapp):
        """BGR888 行按 4 字节对齐时 bytesPerLine > width*3，切片不得错位。"""
        from PySide6.QtGui import QImage

        width, height = 13, 5
        img = Image.new("RGB", (width, height), (0, 255, 0))
        for y in range(height):
            img.putpixel((width - 1, y), (255, 0, 0))
        img.save(tmp_path / "odd.png")
        bgr = qimage_to_bgr(QImage(str(tmp_path / "odd.png")))
        assert bgr.shape == (height, width, 3)
        # 最后一列应是红色（BGR: 0,0,255），倒数第二列是绿色（BGR: 0,255,0）
        assert tuple(bgr[2, width - 1]) == (0, 0, 255)
        assert tuple(bgr[2, width - 2]) == (0, 255, 0)


class TestDroppedUrls:
    def test_单张受支持图像通过(self, tmp_path):
        path = make_png(tmp_path / "ok.png")
        url = QUrl.fromLocalFile(str(path))
        assert validate_dropped_urls([url]) == path

    def test_多个文件被拒绝(self, tmp_path):
        urls = [
            QUrl.fromLocalFile(str(make_png(tmp_path / "a.png"))),
            QUrl.fromLocalFile(str(make_png(tmp_path / "b.png"))),
        ]
        assert validate_dropped_urls(urls) is None

    def test_非图像文件被拒绝(self, tmp_path):
        text = tmp_path / "note.txt"
        text.write_text("hi", encoding="utf-8")
        assert validate_dropped_urls([QUrl.fromLocalFile(str(text))]) is None

    def test_空列表被拒绝(self):
        assert validate_dropped_urls([]) is None
