"""图像输入管线（spec: image-input）。

四种输入（文件选择 / 拖放 / 剪贴板 / 屏幕捕获）共用同一条转换路径：
文件途径经双重校验（扩展名 + 可解码），内存途径（剪贴板 / 捕获）由
程序自身生成 QImage，格式校验不适用。全程 QImage / ndarray 内存流转，
不落任何临时文件（design D8）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage

from ocrtool.ocr.exceptions import InvalidImageError

logger = logging.getLogger("ocrtool.image")

SUPPORTED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp"})
DEFAULT_MAX_EDGE = 6000


def validate_and_load(path: Path | str) -> QImage:
    """双重校验（spec: image-input）：扩展名白名单 + 实际可解码。

    扩展名与内容不符时以可解码性为准；损坏文件抛 InvalidImageError，
    技术细节记入日志。返回的 QImage 为原始尺寸。
    """
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise InvalidImageError(
            f"不支持的图像格式：{path.suffix or '<无扩展名>'}（"
            "支持 PNG / JPG / JPEG / BMP / WEBP）"
        )

    image = QImage(str(path))
    if image.isNull():
        logger.error("图像无法解码：%s", path)
        raise InvalidImageError(f"图像无法读取：{path.name}")
    return image


def validate_dropped_urls(urls: list[QUrl]) -> Path | None:
    """拖放入口的预处理：仅接受单张受支持图像，其余一律返回 None。

    返回 None 时调用方保持当前图像不变并给出提示（spec: image-input）。
    """
    local_files = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
    if len(local_files) != 1:
        return None
    file_path = local_files[0]
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    return file_path


def qimage_to_bgr(image: QImage) -> np.ndarray:
    """QImage → BGR ndarray；按 bytesPerLine 切除行尾对齐填充。

    必须复制为自有内存（np.array 默认 copy）：constBits() 的视图指向
    QImage 底层缓冲，converted 局部对象销毁后视图即悬垂，下游 cv2.resize
    会访问已释放内存（实测 access violation）。
    """
    converted = image.convertToFormat(QImage.Format.Format_BGR888)
    height, width = converted.height(), converted.width()
    raw = np.frombuffer(converted.constBits(), dtype=np.uint8, count=converted.sizeInBytes())
    rows = raw.reshape(height, converted.bytesPerLine())
    return np.array(rows[:, : width * 3].reshape(height, width, 3))


def scale_to_limit(
    image: np.ndarray, max_edge: int = DEFAULT_MAX_EDGE
) -> tuple[np.ndarray, float]:
    """超大图等比缩放至上限内（design D7/D8）；返回 (识别副本, scale)。

    scale 为识别副本相对原图的缩放比例（≤1.0），随 OcrResult 返回，
    供后续版本把位置框换算回原始坐标系。
    """
    height, width = image.shape[:2]
    longest = max(width, height)
    if longest <= max_edge:
        return image, 1.0

    factor = max_edge / longest
    new_width = max(1, round(width * factor))
    new_height = max(1, round(height * factor))
    import cv2

    scaled = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
    return scaled, factor


def load_for_recognition(
    path: Path | str, max_edge: int = DEFAULT_MAX_EDGE
) -> tuple[QImage, np.ndarray, float]:
    """「原图预览 + 缩放识别副本」的组合入口（design D7）。

    返回 (原始 QImage 供预览, BGR ndarray 供识别, 缩放比例)。
    """
    original = validate_and_load(path)
    bgr = qimage_to_bgr(original)
    scaled, scale = scale_to_limit(bgr, max_edge)
    return original, scaled, scale
