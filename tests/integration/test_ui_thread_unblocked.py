"""ocr-execution 集成测试：识别在后台执行，主线程事件持续处理（任务 2.7）。"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_helpers import process_events_until

from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.ocr.result import OcrResult
from ocrtool.ocr.states import OcrState


class SlowService:
    """模拟一次耗时 0.4s 的识别（加载 0.2s + 识别 0.2s）。"""

    model_name = "slow-fake"

    def __init__(self) -> None:
        self.engine_loaded = False
        self.done = threading.Event()

    def preload(self) -> None:
        time.sleep(0.2)
        self.engine_loaded = True

    def recognize(self, image, *, scale: float = 1.0) -> OcrResult:
        time.sleep(0.2)
        self.done.set()
        return OcrResult(text="行", lines=(), elapsed_ms=400.0, width=8, height=6)


def test_识别执行期间主线程事件持续投递不被阻塞(qapp):
    service = SlowService()
    controller = OcrController(service)

    timer_ticks: list[int] = []

    def on_tick() -> None:
        timer_ticks.append(1)

    # 主线程 10ms 定时器——若识别阻塞主线程，tick 将完全停滞
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(on_tick)
    timer.start()

    recognize_thread: list[str] = []
    original_recognize = service.recognize

    def traced_recognize(image, *, scale: float = 1.0):
        recognize_thread.append(threading.current_thread().name)
        return original_recognize(image, scale=scale)

    service.recognize = traced_recognize

    assert controller.start_recognition(np.zeros((4, 4, 3), dtype=np.uint8))
    process_events_until(qapp, lambda: not controller.busy, timeout_s=5)
    timer.stop()

    assert service.done.is_set(), "识别应已完成"
    assert recognize_thread and recognize_thread[0] != "MainThread", (
        "识别必须运行在后台线程"
    )
    # 0.4s 识别期间，10ms 定时器应触发数十次；被阻塞则接近 0
    assert len(timer_ticks) >= 20, (
        f"主线程事件处理停滞：0.4s 内仅 {len(timer_ticks)} 次 tick"
    )
    assert controller.state is OcrState.IDLE
