"""识别控制器（spec: ocr-execution）——UI 与后台执行的接线层。

并发三道保险（design D3）：
1. 线程池容量 1        —— 机制层面杜绝并发进入单实例引擎；
2. 控制器拒绝重入      —— busy 期间 start_recognition 直接拒绝；
3. 请求序号作废        —— 回调 token 与当前序号不符即丢弃，无任何界面副作用。

模型切换（spec: ocr-execution 切换与识别互斥）与识别共用同一容量 1
的线程池：识别在途时切换任务排队其后（不取消在途识别，design D2），
切换期间 busy 持续、新识别被拒（design D3）。

UI 只与控制器对话，绝不直接调用 OCR 引擎（架构边界）。
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, Signal

from ocrtool.ocr.exceptions import OcrError
from ocrtool.ocr.result import OcrResult
from ocrtool.ocr.states import OcrState, StateMachine
from ocrtool.ocr.worker import ModelSwitchWorker, OcrWorker

logger = logging.getLogger("ocrtool.ocr")


class OcrController(QObject):
    """驱动识别生命周期并向界面转发结果与状态。"""

    stateChanged = Signal(OcrState)
    busyChanged = Signal(bool)
    resultReady = Signal(OcrResult)  # 仅当前有效请求的结果
    errorOccurred = Signal(OcrError)  # 仅当前有效请求的错误
    modelSwitched = Signal(str, str)  # 切换生效：(model_id, model_name)
    modelSwitchFailed = Signal(object)  # 切换失败：OcrError（旧模型仍在用）

    def __init__(self, service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._state_machine = StateMachine()
        self._token = 0
        self._busy = False
        self._switching = False
        self._pending_switch = None  # 识别在途时暂存的切换目标

        self._pool = QThreadPool(self)
        # 容量 1：与单实例引擎匹配，机制上杜绝并发进入引擎
        self._pool.setMaxThreadCount(1)
        # 持有活动 worker 及其 signals（QObject 无父对象，Python 引用是唯一
        # 生命周期锚点）——若在回调完成前释放，排队中的跨线程信号会随发送者
        # 一起被销毁，主线程将永远收不到结果。
        self._active_worker: OcrWorker | None = None
        self._active_switch_worker: ModelSwitchWorker | None = None

    @property
    def state(self) -> OcrState:
        return self._state_machine.state

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def switching(self) -> bool:
        return self._switching

    @property
    def model_name(self) -> str:
        return self._service.model_name

    @property
    def model_id(self) -> str:
        return self._service.model_id

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

    def switch_model(self, model) -> bool:
        """请求切换模型（spec: ocr-execution 模型切换与识别互斥）。

        识别在途 → 排队等待其完成，不取消在途识别（design D2）；
        切换在途 → 直接拒绝。返回 False 表示请求被拒。
        """
        if self._switching:
            logger.warning("模型切换进行中，拒绝新的切换请求")
            return False
        self._switching = True
        if self._busy:
            # 识别在途：暂存目标，_finish_cycle 接续启动。期间 busy 持续，
            # 新识别请求被拒（design D3），无请求堆积。
            logger.info("识别在途，模型切换排队等待：%s", model.model_id)
            self._pending_switch = model
            return True
        self._token += 1  # 作废任何残余识别回调（正常时序下不存在）
        self._set_busy(True)
        self._transition(OcrState.LOADING)
        self._launch_switch(model)
        return True

    # ---- 回调（主线程，经 Qt 排队信号到达）----

    def _on_loaded(self, token: int) -> None:
        if token != self._token:
            return  # 过期回调：丢弃且无副作用（design D3）
        self._transition(OcrState.RECOGNIZING)

    def _on_finished(self, token: int, result: OcrResult) -> None:
        if token != self._token:
            return  # 过期回调：丢弃且不动 _active_worker（它锚定的是新请求）
        if result.line_count == 0:
            self._transition(OcrState.EMPTY)
        else:
            self._transition(OcrState.SUCCESS)
        self.resultReady.emit(result)
        self._finish_cycle()

    def _on_failed(self, token: int, error: OcrError) -> None:
        if token != self._token:
            return  # 同上：释放会拆掉新 worker 的生命周期锚点
        self._transition(OcrState.ERROR)
        self.errorOccurred.emit(error)
        self._finish_cycle()

    def _on_switched(self, token: int) -> None:
        if token != self._token:
            return
        self._finish_switch()
        self.modelSwitched.emit(self._service.model_id, self._service.model_name)

    def _on_switch_failed(self, token: int, error: OcrError) -> None:
        if token != self._token:
            return
        self._finish_switch()
        self.modelSwitchFailed.emit(error)

    # ---- 内部 ----

    def _launch_switch(self, model) -> None:
        worker = ModelSwitchWorker(self._service, model, self._token)
        self._active_switch_worker = worker
        worker.signals.switched.connect(lambda t: self._on_switched(t))
        worker.signals.failed.connect(lambda t, e: self._on_switch_failed(t, e))
        self._pool.start(worker)

    def _finish_switch(self) -> None:
        """切换结束（成功或失败）：回空闲并恢复触发入口（spec: ocr-execution）。"""
        self._transition(OcrState.IDLE)
        self._switching = False
        self._active_switch_worker = None
        self._set_busy(False)

    def _release_worker(self) -> None:
        self._active_worker = None

    def _finish_cycle(self) -> None:
        self._transition(OcrState.IDLE)
        self._release_worker()
        if self._pending_switch is not None:
            # 识别结束后接续排队的模型切换（design D2）——busy 全程保持，
            # 不产生「短暂可用又立刻禁用」的入口闪烁
            model = self._pending_switch
            self._pending_switch = None
            self._token += 1
            self._transition(OcrState.LOADING)
            self._launch_switch(model)
        else:
            self._set_busy(False)

    def _transition(self, new_state: OcrState) -> None:
        self._state_machine.transition(new_state)
        self.stateChanged.emit(new_state)

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busyChanged.emit(busy)
