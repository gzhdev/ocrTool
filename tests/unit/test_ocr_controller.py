"""controllers/ocr_controller.py：序号作废、重入拒绝、状态序列（任务 2.2–2.6）。"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
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
                 delay: float = 0.0, switch_delay: float = 0.0,
                 switch_error: Exception | None = None) -> None:
        self.model_name = "fake-model"
        self.model_id = "fake-a"
        self.engine_loaded = False
        self._result = result if result is not None else make_result()
        self._error = error
        self._delay = delay
        self._switch_delay = switch_delay
        self._switch_error = switch_error
        self.recognize_calls = 0
        self.load_calls = 0
        self.switch_calls: list[str] = []

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

    def switch_model(self, model) -> None:
        time.sleep(self._switch_delay)
        if self._switch_error is not None:
            raise self._switch_error
        self.model_id = model.model_id
        self.model_name = getattr(model, "name", model.model_id)
        self.switch_calls.append(model.model_id)


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
        controller, _observer = make_controller(FakeService(delay=0.01), qapp)
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


def target_model(model_id: str = "fake-b"):
    from types import SimpleNamespace

    return SimpleNamespace(model_id=model_id, name=f"模型{model_id}")


class TestModelSwitching:
    """模型切换与识别互斥（model-switching 任务 2.3/2.4）。"""

    def test_空闲时切换_加载态开始_空闲态结束(self, qapp):
        service = FakeService(switch_delay=0.01)
        controller, observer = make_controller(service, qapp)
        switched: list[tuple[str, str]] = []
        controller.modelSwitched.connect(lambda i, n: switched.append((i, n)))

        assert controller.switch_model(target_model()) is True
        assert controller.busy is True
        process_events_until(qapp, lambda: not controller.busy)

        assert switched == [("fake-b", "模型fake-b")]
        assert observer.states == [S.LOADING, S.IDLE]
        assert service.switch_calls == ["fake-b"]
        assert controller.switching is False

    def test_识别在途时切换排队_识别先用旧模型完成(self, qapp):
        """2.3：在途识别不被取消、正常返回结果，切换随后执行。"""
        service = FakeService(delay=0.05)
        controller, observer = make_controller(service, qapp)
        switched: list[tuple[str, str]] = []
        controller.modelSwitched.connect(lambda i, n: switched.append((i, n)))

        assert controller.start_recognition(image()) is True
        assert controller.switch_model(target_model()) is True  # 排队，不被拒

        process_events_until(qapp, lambda: switched and not controller.busy)
        assert len(observer.results) == 1, "在途识别必须正常返回结果"
        assert service.recognize_calls == 1
        assert service.switch_calls == ["fake-b"], "切换在识别完成后才执行"
        assert observer.states[-3:-1] == [S.IDLE, S.LOADING], "识别结束后接续切换"

    def test_识别在途时切换排队_重复十次无时序竞争(self, qapp):
        """2.3：交错识别与切换 10 轮，结果与切换一一对应、无错配。"""
        for round_no in range(10):
            service = FakeService(delay=0.02, switch_delay=0.01)
            controller, observer = make_controller(service, qapp)
            switched: list[str] = []
            controller.modelSwitched.connect(
                lambda i, n, sink=switched: sink.append(i)
            )

            assert controller.start_recognition(image()) is True
            assert controller.switch_model(target_model(f"m{round_no}")) is True
            # 排队期间新识别被拒（busy 持续）
            assert controller.start_recognition(image()) is False

            process_events_until(
                qapp,
                lambda sink=switched, c=controller: sink and not c.busy,
                timeout_s=15,
            )
            assert len(observer.results) == 1
            assert switched == [f"m{round_no}"]
            assert service.recognize_calls == 1
            assert controller.state is S.IDLE

    def test_切换期间拒绝新识别_不产生堆积(self, qapp):
        """2.4：切换进行中识别请求被拒，多次请求不排队堆积。"""
        service = FakeService(switch_delay=0.05)
        controller, _observer = make_controller(service, qapp)
        assert controller.switch_model(target_model()) is True

        for _ in range(5):
            assert controller.start_recognition(image()) is False

        process_events_until(qapp, lambda: not controller.busy)
        assert service.recognize_calls == 0, "被拒的请求不得堆积执行"
        assert controller.start_recognition(image()) is True  # 结束后恢复
        process_events_until(qapp, lambda: not controller.busy)
        assert service.recognize_calls == 1

    def test_切换在途拒绝第二个切换请求(self, qapp):
        service = FakeService(switch_delay=0.05)
        controller, _ = make_controller(service, qapp)
        assert controller.switch_model(target_model("first")) is True
        assert controller.switch_model(target_model("second")) is False
        process_events_until(qapp, lambda: not controller.busy)
        assert service.switch_calls == ["first"]

    def test_切换失败_信号发出_状态回空闲_识别仍可用(self, qapp):
        from ocrtool.ocr.exceptions import ModelLoadError

        service = FakeService(switch_delay=0.01, switch_error=ModelLoadError("切换失败，仍在使用原模型"))
        controller, observer = make_controller(service, qapp)
        failures: list[object] = []
        controller.modelSwitchFailed.connect(failures.append)

        assert controller.switch_model(target_model()) is True
        process_events_until(qapp, lambda: failures and not controller.busy)

        assert len(failures) == 1
        assert controller.state is S.IDLE, "失败同样回空闲（spec: ocr-execution）"
        assert observer.states == [S.LOADING, S.IDLE]
        # 功能不中断：识别立即可用
        assert controller.start_recognition(image()) is True
        process_events_until(qapp, lambda: not controller.busy)
        assert len(observer.results) == 1

    def test_切换期间_busy_信号只翻转一次(self, qapp):
        service = FakeService(switch_delay=0.02)
        controller, observer = make_controller(service, qapp)
        controller.switch_model(target_model())
        process_events_until(qapp, lambda: not controller.busy)
        assert observer.busy_flips == [True, False]

    def test_识别结束接续切换_busy_无闪烁(self, qapp):
        """排队场景：识别→切换全程 busy，不出现中间释放。"""
        service = FakeService(delay=0.02)
        controller, observer = make_controller(service, qapp)
        controller.start_recognition(image())
        controller.switch_model(target_model())
        process_events_until(qapp, lambda: not controller.busy)
        assert observer.busy_flips == [True, False]
