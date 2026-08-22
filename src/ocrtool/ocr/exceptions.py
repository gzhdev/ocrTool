"""识别过程错误分类（spec: ocr-engine）。

message（异常消息）是用户可读的中文说明；技术细节（路径、原始异常、
调用栈）只随 detail 与日志流转，绝不进入界面文本。
"""

from __future__ import annotations


class OcrError(Exception):
    """本项目识别错误基类。"""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ModelMissingError(OcrError):
    """模型文件缺失（缺失路径仅记入日志）。"""


class ModelLoadError(OcrError):
    """模型文件存在但无法加载（技术细节仅记入日志）。"""


class RecognitionError(OcrError):
    """识别执行中的未预期异常（完整调用栈仅记入日志）。"""


class InvalidImageError(OcrError):
    """图像无效或无法解码。"""
