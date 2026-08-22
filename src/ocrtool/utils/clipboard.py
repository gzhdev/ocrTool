"""剪贴板读写（spec: image-input / main-window）。

薄封装 QClipboard：读取存在图像返回 QImage，否则返回 None（调用方提示
「剪贴板中没有图像」并保持当前图像不变）。自动复制仅在识别成功且检出
文本时写入（design D5：空结果/失败写入空串等于清空用户剪贴板）。
无临时文件，数据全程内存。
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


def set_clipboard_text(text: str, clipboard: QClipboard | None = None) -> None:
    """把文本写入系统剪贴板（自动复制路径）。"""
    if clipboard is None:
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
    clipboard.setText(text)
