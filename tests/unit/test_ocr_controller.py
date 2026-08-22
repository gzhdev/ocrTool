"""controllers/ocr_controller.py：序号作废、重入拒绝、状态序列（任务 2.2–2.6）。"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QRunnable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/qt_helpers
from qt_helpers import process_events_until

from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.ocr.exceptions import RecognitionError
from ocrtool.ocr.result import OcrResult
from ocrtool.ocr.states import OcrState as S


def image() -> np.ndarray:
    return np.zeros((4, 4, 3), dtype=np.uint8)


def make_result(lines: int = 1) -> OcrResult:
    from ocrtool.ocr.result import OcrLine

    line = OcrLine(text="行", score=0.9, box=((0, 0), (1, 0), (1, 1), (0, 1)))
    return OcrResult(
        text="行" * lines if lines else "",
        lines=(line,) * lines if lines else (),
        elapsed_ms=1.0,
        width=8,
        height=6,
    )


class FakeService:
    def __init__(self, result: OcrResult | None = None, error: Exception | None = None,
                 delay: float = 0.0) -> None:
        self.model_name = "fake-model"
        self.engine_loaded = False
        self._result = result if result is not None else make_result()
        self._error = error
        self._delay = delay
        self.recognize_calls = 0
        self.load_calls = 0

    def preload(self) -> None:
        time.sleep(self._delay)
        self.load_calls += 1
        self.engine_loaded = True

    def recognize(self, img, *, scale: float = 1.0) -> OcrResult:
        time.sleep(self._delay)
        self.recognize_calls += 1
        if self._error is not None:
            raise self._error
        return self._result


@dataclass
class Observer:
    states: list[S] = field(default_factory=list)
    results: list[OcrResult] = field(default_factory=list)
    errors: list[Exception] = field(default_factory=list)
    busy_flips: list[bool] = field(default_factory=list)


def make_controller(service, qapp) -> tuple[OcrController, Observer]:
    controller = OcrController(service)
    observer = Observer()
    controller.stateChanged.connect(observer.states.append)
    controller.resultReady.connect(observer.results.append)
    controller.errorOccurred.connect(observer.errors.append)
    controller.busyChanged.connect(observer.busy_flips.append)
    return controller, observer


class TestThreadPoolCapacity:
    def test_线程池容量为_1(self, qapp):
        controller, _ = make_controller(FakeService(), qapp)
        assert controller.pool.maxThreadCount() == 1

    def test_并发提交两个任务不重叠执行(self, qapp):
        controller, _ = make_controller(FakeService(), qapp)
        tracker = {"active": 0, "max_active": 0, "done": 0}
        lock = threading.Lock()

        class CountingTask(QRunnable):
            def run(self) -> None:
                with lock:
                    tracker["active"] += 1
                    tracker["max_active"] = max(tracker["max_active"], tracker["active"])
                time.sleep(0.05)
                with lock:
                    tracker["active"] -= 1
                    tracker["done"] += 1

        pool = controller.pool
        pool.start(CountingTask())
        pool.start(CountingTask())
        process_events_until(qapp, lambda: tracker["done"] == 2)
        assert tracker["max_active"] == 1, "容量 1 的线程池不允许任务重叠执行"


class TestReentryGuard:
    def test_识别进行中再次请求被拒绝(self, qapp):
        service = FakeService(delay=0.05)
        controller, _ = make_controller(service, qapp)
        assert controller.start_recognition(image()) is True
        assert controller.busy is True
        assert controller.start_recognition(image()) is False

        process_events_until(qapp, lambda: not controller.busy)
        assert service.recognize_calls == 1, "重入请求不得产生第二个任务"
        # 结束后恢复可用
        assert controller.start_recognition(image()) is True

    def test_busy_信号驱动触发入口启停(self, qapp):
        controller, observer = make_controller(FakeService(delay=0.03), qapp)
        controller.start_recognition(image())
        process_events_until(qapp, lambda: not controller.busy)
        assert observer.busy_flips == [True, False]


class TestTokenInvalidation:
    def test_过期回调被丢弃且无副作用(self, qapp):
        service = FakeService(delay=0.01)
        controller, observer = make_controller(service, qapp)
        controller.start_recognition(image())  # token=1

        # 模拟乱序：token=1 的迟到回调在 token=2 期间到达
        controller._token = 2
        stale_result = make_result()
        controller._on_finished(1, stale_result)

        assert observer.results == [], "过期结果不得转发"
        assert controller.busy is True, "过期回调不得解除禁用"
        assert controller.state is not S.IDLE, "过期回调不得改写状态"

        # token=2 的合法回调正常生效（须先经 loaded 推进到识别中态）
        controller._on_loaded(2)
        controller._on_finished(2, stale_result)
        assert observer.results == [stale_result]
        assert controller.busy is False

    def test_过期失败回调同样被丢弃(self, qapp):
        controller, observer = make_controller(FakeService(delay=0.01), qapp)
        controller.start_recognition(image())  # token=1
        controller._token = 2
        controller._on_failed(1, RecognitionError("迟到"))
        assert observer.errors == []
        assert controller.busy is True

    def test_过期_loaded_回调被丢弃(self, qapp):
        controller, observer = make_controller(FakeService(delay=0.01), qapp)
        controller.start_recognition(image())  # token=1，进入 LOADING
        controller._token = 2
        controller._on_loaded(1)
        assert controller.state is S.LOADING, "过期 loaded 不得推进状态"


class TestStateSequences:
    def test_首次识别_加载_识别_成功_空闲(self, qapp):
        controller, observer = make_controller(FakeService(delay=0.01), qapp)
        controller.start_recognition(image())
        process_events_until(qapp, lambda: not controller.busy)
        assert observer.states == [S.LOADING, S.RECOGNIZING, S.SUCCESS, S.IDLE]

    def test_已加载时跳过加载态(self, qapp):
        service = FakeService(delay=0.01)
        service.engine_loaded = True
        controller, observer = make_controller(service, qapp)
        controller.start_recognition(image())
        process_events_until(qapp, lambda: not controller.busy)
        assert observer.states == [S.RECOGNIZING, S.SUCCESS, S.IDLE]

    def test_空结果进入_empty_态(self, qapp):
        controller, observer = make_controller(FakeService(result=make_result(lines=0), delay=0.01), qapp)
        controller.start_recognition(image())
        process_events_until(qapp, lambda: not controller.busy)
        assert observer.states == [S.LOADING, S.RECOGNIZING, S.EMPTY, S.IDLE]

    def test_错误进入_error_态且可继续使用(self, qapp):
        controller, observer = make_controller(
            FakeService(error=RecognitionError("失败"), delay=0.01), qapp
        )
        controller.start_recognition(image())
        process_events_until(qapp, lambda: not controller.busy)
        assert observer.states == [S.LOADING, S.RECOGNIZING, S.ERROR, S.IDLE]
        assert len(observer.errors) == 1

        # 程序保持可用：再次发起识别成功
        controller._service = FakeService(delay=0.01)
        assert controller.start_recognition(image()) is True
        process_events_until(qapp, lambda: not controller.busy)
        assert controller.state is S.IDLE

    def test_加载失败直接由_loading_进入_error(self, qapp):
        class LoadFailService(FakeService):
            def preload(self) -> None:
                from ocrtool.ocr.exceptions import ModelLoadError

                raise ModelLoadError("加载失败")

        controller, observer = make_controller(LoadFailService(delay=0.01), qapp)
        controller.start_recognition(image())
        process_events_until(qapp, lambda: not controller.busy)
        assert observer.states == [S.LOADING, S.ERROR, S.IDLE]
