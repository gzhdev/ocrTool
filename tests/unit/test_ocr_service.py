"""ocr/service.py：参数映射、惰性加载、单实例复用、结果规范化与错误分类。

以注入的 fake 引擎工厂驱动，不触碰真实 ONNX 模型，也不发起任何网络请求。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from ocrtool.ocr.exceptions import (
    InvalidImageError,
    ModelLoadError,
    ModelMissingError,
    RecognitionError,
)
from ocrtool.ocr.model_manager import ModelInfo
from ocrtool.ocr.service import OCRService, map_thread_count

import os


@dataclass
class FakeOutput:
    txts: Any = None
    boxes: Any = None
    scores: Any = None


@dataclass
class FakeEngine:
    outputs: Any = field(default_factory=list)
    calls: int = 0
    fail_with: Exception | None = None

    def __call__(self, image: np.ndarray) -> FakeOutput:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        if isinstance(self.outputs, list):
            return self.outputs.pop(0) if self.outputs else FakeOutput()
        return self.outputs


def make_model(tmp_path: Path) -> ModelInfo:
    det, rec = tmp_path / "det.onnx", tmp_path / "rec.onnx"
    det.write_bytes(b"det")
    rec.write_bytes(b"rec")
    return ModelInfo(
        model_id="test-model",
        directory=tmp_path,
        det_path=det,
        rec_path=rec,
        name="测试模型",
        recommended=True,
        language_coverage=("ch", "en"),
        raw={},
    )


def image(width: int = 8, height: int = 6) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


class TestMapThreadCount:
    def test_零与负值交给运行时决定(self):
        assert map_thread_count(0, 8) == -1
        assert map_thread_count(-3, 8) == -1

    def test_正值不超过逻辑核心数(self):
        assert map_thread_count(4, 8) == 4
        assert map_thread_count(8, 4) == 4
        assert map_thread_count(2, 1) == 1


class TestEngineParams:
    def test_显式本地路径_关闭方向分类_映射线程数(self, tmp_path):
        captured: list[dict] = []

        def factory(params: dict) -> FakeEngine:
            captured.append(params)
            return FakeEngine()

        service = OCRService(make_model(tmp_path), cpu_threads=2, engine_factory=factory)
        service.recognize(image())

        assert captured, "引擎工厂未被调用"
        params = captured[0]
        assert params["Det.model_path"].endswith("det.onnx")
        assert params["Rec.model_path"].endswith("rec.onnx")
        assert params["Global.use_cls"] is False
        assert params["EngineConfig.onnxruntime.intra_op_num_threads"] == 2
        assert params["EngineConfig.onnxruntime.inter_op_num_threads"] == 2


class TestLazyLoading:
    def test_构造与首次识别之间不加载(self, tmp_path):
        factory_calls: list[int] = []

        def factory(params: dict) -> FakeEngine:
            factory_calls.append(1)
            return FakeEngine()

        service = OCRService(make_model(tmp_path), engine_factory=factory)
        assert service.engine_loaded is False
        assert factory_calls == []

    def test_连续多次识别只加载一次(self, tmp_path):
        engine = FakeEngine(
            outputs=[FakeOutput(txts=("a",), boxes=(((0, 0), (1, 0), (1, 1), (0, 1)),), scores=(0.9,))]
        )
        created: list[FakeEngine] = []

        def factory(params: dict) -> FakeEngine:
            created.append(engine)
            return engine

        service = OCRService(make_model(tmp_path), engine_factory=factory)
        for _ in range(5):
            service.recognize(image())
        assert len(created) == 1, "连续识别必须复用同一引擎实例"
        assert service.engine_loaded is True
        assert engine.calls == 5


class TestConvertOutput:
    def test_空输出的_none_字段被规范化为空结果(self, tmp_path):
        service = OCRService(
            make_model(tmp_path),
            engine_factory=lambda p: FakeEngine(FakeOutput(txts=None, boxes=None, scores=None)),
        )
        result = service.recognize(image(width=32, height=16))
        assert result.text == ""
        assert result.lines == ()
        assert result.line_count == 0
        assert (result.width, result.height) == (32, 16)
        assert result.scale == 1.0

    def test_none_输出对象同样得到空结果(self, tmp_path):
        @dataclass
        class NullEngine:
            def __call__(self, image: np.ndarray) -> None:
                return None

        service = OCRService(make_model(tmp_path), engine_factory=lambda p: NullEngine())
        result = service.recognize(image())
        assert result.text == ""
        assert result.lines == ()

    def test_多行结果合并与坐标转换(self, tmp_path):
        output = FakeOutput(
            txts=("第一行", "line2"),
            boxes=(((0, 0), (10, 0), (10, 4), (0, 4)), ((0, 6), (12, 6), (12, 9), (0, 9))),
            scores=(0.91, 0.85),
        )
        service = OCRService(make_model(tmp_path), engine_factory=lambda p: FakeEngine(output))
        result = service.recognize(image(), scale=0.5)

        assert result.text == "第一行\nline2"
        assert result.line_count == 2
        assert result.lines[0].score == 0.91
        assert result.lines[1].box == ((0.0, 6.0), (12.0, 6.0), (12.0, 9.0), (0.0, 9.0))
        assert result.scale == 0.5

    def test_无效图像输入被拒绝(self, tmp_path):
        service = OCRService(make_model(tmp_path), engine_factory=lambda p: FakeEngine())
        with pytest.raises(InvalidImageError):
            service.recognize(None)  # type: ignore[arg-type]
        with pytest.raises(InvalidImageError):
            service.recognize(np.zeros((0, 0, 3), dtype=np.uint8))


class TestErrorMapping:
    def test_模型文件缺失(self, tmp_path):
        model = make_model(tmp_path)
        service = OCRService(model, engine_factory=lambda p: FakeEngine())
        model.det_path.unlink()
        with pytest.raises(ModelMissingError) as exc_info:
            service.recognize(image())
        assert str(exc_info.value) == "模型文件缺失，请重新获取或恢复程序目录"
        assert "det.onnx" in (exc_info.value.detail or "")

    def test_模型加载失败(self, tmp_path):
        def broken_factory(params: dict) -> FakeEngine:
            raise RuntimeError("onnx parse error")

        service = OCRService(make_model(tmp_path), engine_factory=broken_factory)
        with pytest.raises(ModelLoadError) as exc_info:
            service.recognize(image())
        assert "onnx parse error" in (exc_info.value.detail or "")
        assert "onnx parse error" not in str(exc_info.value)

    def test_识别中的未预期异常(self, tmp_path):
        engine = FakeEngine(fail_with=ValueError("boom"))
        service = OCRService(make_model(tmp_path), engine_factory=lambda p: engine)
        with pytest.raises(RecognitionError):
            service.recognize(image())
        # 失败后服务仍可用（引擎保持已加载，可再次发起识别）
        engine.fail_with = None
        engine.outputs = [FakeOutput(txts=("ok",))]
        assert service.recognize(image()).text == "ok"

    def test_识别失败后引擎不重建(self, tmp_path):
        engine = FakeEngine(fail_with=ValueError("boom"))
        created: list[FakeEngine] = []

        def factory(params: dict) -> FakeEngine:
            created.append(engine)
            return engine

        service = OCRService(make_model(tmp_path), engine_factory=factory)
        with pytest.raises(RecognitionError):
            service.recognize(image())
        with pytest.raises(RecognitionError):
            service.recognize(image())
        assert len(created) == 1


class TestNoNetwork:
    def test_服务层不导入任何联网下载工具(self):
        import ocrtool.ocr.service as service_mod

        source = Path(service_mod.__file__).read_text(encoding="utf-8")
        assert "download" not in source.lower()
        assert "requests" not in source.lower()
        assert "urllib" not in source.lower()
