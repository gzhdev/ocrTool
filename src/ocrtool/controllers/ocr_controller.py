"""识别控制器（spec: ocr-execution）——UI 与后台执行的接线层。

并发三道保险（design D3）：
1. 线程池容量 1        —— 机制层面杜绝并发进入单实例引擎；
2. 控制器拒绝重入      —— busy 期间 start_recognition 直接拒绝；
3. 请求序号作废        —— 回调 token 与当前序号不符即丢弃，无任何界面副作用。

UI 只与控制器对话，绝不直接调用 OCR 引擎（架构边界）。
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, Signal

from ocrtool.ocr.exceptions import OcrError
from ocrtool.ocr.result import OcrResult
from ocrtool.ocr.states import OcrState, StateMachine
from ocrtool.ocr.worker import OcrWorker

logger = logging.getLogger("ocrtool.ocr")


class OcrController(QObject):
    """驱动识别生命周期并向界面转发结果与状态。"""

    stateChanged = Signal(OcrState)
    busyChanged = Signal(bool)
    resultReady = Signal(OcrResult)  # 仅当前有效请求的结果
    errorOccurred = Signal(OcrError)  # 仅当前有效请求的错误

    def __init__(self, service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._state_machine = StateMachine()
        self._token = 0
        self._busy = False

        self._pool = QThreadPool(self)
        # 容量 1：与单实例引擎匹配，机制上杜绝并发进入引擎
        self._pool.setMaxThreadCount(1)
        # 持有活动 worker 及其 signals（QObject 无父对象，Python 引用是唯一
        # 生命周期锚点）——若在回调完成前释放，排队中的跨线程信号会随发送者
        # 一起被销毁，主线程将永远收不到结果。
        self._active_worker: OcrWorker | None = None

    @property
    def state(self) -> OcrState:
        return self._state_machine.state

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def model_name(self) -> str:
        return self._service.model_name

    @property
    def pool(self) -> QThreadPool:
        """暴露线程池供测试与显式等待；业务代码不应直接向其提交任务。"""
        return self._pool

    def start_recognition(self, image: np.ndarray, *, scale: float = 1.0) -> bool:
        """发起识别；busy 期间拒绝重入并返回 False（spec: ocr-execution）。"""
        if self._busy:
            logger.warning("识别进行中，拒绝重入请求")
            return False

        self._token += 1
        token = self._token
        self._set_busy(True)
        self._transition(
            OcrState.LOADING if not self._service.engine_loaded else OcrState.RECOGNIZING
        )

        worker = OcrWorker(self._service, image, token, scale)
        self._active_worker = worker
        worker.signals.loaded.connect(lambda t: self._on_loaded(t))
        worker.signals.finished.connect(lambda t, r: self._on_finished(t, r))
        worker.signals.failed.connect(lambda t, e: self._on_failed(t, e))
        self._pool.start(worker)
        return True

    # ---- 回调（主线程，经 Qt 排队信号到达）----

    def _on_loaded(self, token: int) -> None:
        if token != self._token:
            return  # 过期回调：丢弃且无副作用（design D3）
        self._transition(OcrState.RECOGNIZING)

    def _on_finished(self, token: int, result: OcrResult) -> None:
        if token != self._token:
            self._release_worker()
            return
        if result.line_count == 0:
            self._transition(OcrState.EMPTY)
        else:
            self._transition(OcrState.SUCCESS)
        self.resultReady.emit(result)
        self._finish_cycle()

    def _on_failed(self, token: int, error: OcrError) -> None:
        if token != self._token:
            self._release_worker()
            return
        self._transition(OcrState.ERROR)
        self.errorOccurred.emit(error)
        self._finish_cycle()

    # ---- 内部 ----

    def _release_worker(self) -> None:
        self._active_worker = None

    def _finish_cycle(self) -> None:
        self._transition(OcrState.IDLE)
        self._set_busy(False)
        self._release_worker()

    def _transition(self, new_state: OcrState) -> None:
        self._state_machine.transition(new_state)
        self.stateChanged.emit(new_state)

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busyChanged.emit(busy)
