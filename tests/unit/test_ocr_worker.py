"""ocr/worker.py：信号可连接、token 与结果随信号投递（任务 2.1，design D5）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import pytest

from ocrtool.ocr.exceptions import RecognitionError
from ocrtool.ocr.result import OcrResult
from ocrtool.ocr.worker import OcrWorker


def make_result(text: str = "行") -> OcrResult:
    return OcrResult(
        text=text, lines=(), elapsed_ms=1.0, width=8, height=6, scale=1.0
    )


class FakeService:
    def __init__(self, *, loaded: bool = False, result=None, error=None):
        self.engine_loaded = loaded
        self.model_name = "fake-model"
        self._result = result if result is not None else make_result("默认")
        self._error = error
        self.preloaded = 0

    def preload(self) -> None:
        self.preloaded += 1
        self.engine_loaded = True

    def recognize(self, image, *, scale: float = 1.0) -> OcrResult:
        if self._error is not None:
            raise self._error
        return self._result


@dataclass
class Recorder:
    loaded: list[int] = field(default_factory=list)
    finished: list[tuple[int, object]] = field(default_factory=list)
    failed: list[tuple[int, object]] = field(default_factory=list)


def make_worker(service, token: int = 1) -> tuple[OcrWorker, Recorder]:
    worker = OcrWorker(service, np.zeros((4, 4, 3), dtype=np.uint8), token, 1.0)
    recorder = Recorder()
    # Signal(int, object) 必须能连接普通 Python 槽——连接失败即类型注册问题
    worker.signals.loaded.connect(recorder.loaded.append)
    worker.signals.finished.connect(lambda t, r: recorder.finished.append((t, r)))
    worker.signals.failed.connect(lambda t, e: recorder.failed.append((t, e)))
    return worker, recorder


class TestWorkerSignals:
    def test_信号连接不出现类型注册失败(self, qapp):
        worker, recorder = make_worker(FakeService())
        worker.run()
        assert recorder.finished, "object 类型结果应可经信号投递"

    def test_结果携带请求序号(self, qapp):
        worker, recorder = make_worker(FakeService(), token=7)
        worker.run()
        assert recorder.finished[0][0] == 7
        assert isinstance(recorder.finished[0][1], OcrResult)

    def test_未加载时先发_loaded_再识别(self, qapp):
        service = FakeService(loaded=False)
        worker, recorder = make_worker(service)
        worker.run()
        assert recorder.loaded == [1]
        assert service.preloaded == 1
        assert recorder.finished

    def test_已加载时不发_loaded(self, qapp):
        service = FakeService(loaded=True)
        worker, recorder = make_worker(service)
        worker.run()
        assert recorder.loaded == []
        assert service.preloaded == 0
        assert recorder.finished

    def test_错误经_failed_投递且携带序号(self, qapp):
        service = FakeService(error=RecognitionError("出错了"))
        worker, recorder = make_worker(service, token=3)
        worker.run()
        assert recorder.finished == []
        assert recorder.failed[0][0] == 3
        assert isinstance(recorder.failed[0][1], RecognitionError)

    def test_非项目异常被兜底为识别失败(self, qapp):
        service = FakeService(error=ValueError("raw boom"))
        worker, recorder = make_worker(service)
        worker.run()
        assert recorder.failed
        error = recorder.failed[0][1]
        assert isinstance(error, RecognitionError)
        assert "boom" in (error.detail or "")
