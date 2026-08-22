"""后台识别工作单元（spec: ocr-execution，design D5）。

运行在 QThreadPool 的后台线程；结果经信号投递回主线程。信号签名使用
通用对象类型（object）——PySide6 的信号类型系统不接受任意 Python 数据
类作为签名类型，且签名必须携带请求序号以配套作废机制（design D3）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, Signal

from ocrtool.ocr.exceptions import OcrError

logger = logging.getLogger("ocrtool.ocr")


class OcrWorkerSignals(QObject):
    loaded = Signal(int)  # 引擎加载完成（仅首次），token 为请求序号
    finished = Signal(int, object)  # (token, OcrResult)
    failed = Signal(int, object)  # (token, OcrError)


class OcrWorker(QRunnable):
    """单次识别任务：惰性加载 → 识别 → 以 token 投递结果。"""

    def __init__(self, service, image, token: int, scale: float) -> None:
        super().__init__()
        self._service = service
        self._image = image
        self._token = token
        self._scale = scale
        self.signals = OcrWorkerSignals()

    def run(self) -> None:
        try:
            if not self._service.engine_loaded:
                self._service.preload()
                self.signals.loaded.emit(self._token)
            result = self._service.recognize(self._image, scale=self._scale)
            self.signals.finished.emit(self._token, result)
        except OcrError as error:
            self.signals.failed.emit(self._token, error)
        except Exception as exc:  # 兜底：工作线程绝不让异常逃逸到线程池
            logger.exception("工作线程未预期异常")
            from ocrtool.ocr.exceptions import RecognitionError

            self.signals.failed.emit(
                self._token, RecognitionError("识别过程发生错误", detail=repr(exc))
            )
