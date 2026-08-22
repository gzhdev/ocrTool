"""ocr/exceptions.py：错误分类可被独立捕获（任务 1.3）。"""

import pytest

from ocrtool.ocr.exceptions import (
    InvalidImageError,
    ModelLoadError,
    ModelMissingError,
    OcrError,
    RecognitionError,
)

ALL_KINDS = pytest.mark.parametrize(
    "exc_type",
    [ModelMissingError, ModelLoadError, RecognitionError, InvalidImageError],
)


class TestErrorClasses:
    @ALL_KINDS
    def test_各类错误可被独立捕获(self, exc_type):
        with pytest.raises(exc_type):
            raise exc_type("用户可读消息", detail="技术细节：路径 X")

    @ALL_KINDS
    def test_各类错误同时属于基类(self, exc_type):
        assert issubclass(exc_type, OcrError)

    @ALL_KINDS
    def test_消息可读_细节与消息分离(self, exc_type):
        error = exc_type("界面显示这句话", detail="/models/x/det.onnx 缺失")
        assert str(error) == "界面显示这句话"
        assert error.message == "界面显示这句话"
        assert error.detail == "/models/x/det.onnx 缺失"
