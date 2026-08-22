"""剪贴板图像读取（spec: image-input）。

薄封装 QClipboard：存在图像返回 QImage，否则返回 None（调用方提示
「剪贴板中没有图像」并保持当前图像不变）。无临时文件，数据全程内存。
"""

from __future__ import annotations

from PySide6.QtGui import QClipboard, QImage


def clipboard_image(clipboard: QClipboard | None = None) -> QImage | None:
    """读取剪贴板图像；无图像数据时返回 None。"""
    if clipboard is None:
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
    image = clipboard.image()
    if image.isNull():
        return None
    return image
