"""OCR 服务层——GUI 识别路径唯一持有 RapidOCR 实例的位置（spec: ocr-engine）。

（`main.py --self-test` 冒烟路径自建实例直连引擎，属基线遗留；迁移至本
服务层已留档为后续变更。）

职责（design D1）：吸收底层引擎的三件「与业务无关」的差异——
返回格式差异、None 与空集合的差异、第三方 logger 的接管；
向上只暴露 OcrResult。模型惰性加载 + 单实例复用（spec: ocr-engine）。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ocrtool.ocr.exceptions import (
    InvalidImageError,
    ModelLoadError,
    ModelMissingError,
    OcrError,
    RecognitionError,
)
from ocrtool.ocr.model_manager import ModelInfo
from ocrtool.ocr.result import OcrLine, OcrResult, merge_line_texts
from ocrtool.utils.logger import log_recognition_summary, silence_third_party_loggers

logger = logging.getLogger("ocrtool.ocr")

EngineFactory = Callable[[dict[str, Any]], Any]


def default_engine_factory(params: dict[str, Any]) -> Any:
    from rapidocr import RapidOCR

    # rapidocr 的 Logger 是模块级单例：首次 import 时发现 handlers 为空会
    # 重新挂上 StreamHandler。因此静默必须发生在 import 之后、构造之前，
    # 否则引擎构造期间的输出（模型路径等）会泄漏到标准输出。
    silence_third_party_loggers()
    return RapidOCR(params=params)


def map_thread_count(configured: int, logical_cores: int) -> int:
    """线程数映射（design D6）：runtime.cpu_threads → 引擎的 num_threads。

    配置为 0 或负值时传 -1 交由推理运行时决定；否则不超过逻辑核心数。
    """
    if configured <= 0:
        return -1
    return min(configured, logical_cores)


class OCRService:
    """识别服务：惰性加载、单实例复用、引擎结果规范化。"""

    def __init__(
        self,
        model: ModelInfo,
        cpu_threads: int = 4,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        self._model = model
        self._engine_factory = engine_factory or default_engine_factory
        self._engine_params = self._build_params(model, cpu_threads)
        self._engine: Any | None = None

    @staticmethod
    def _build_params(model: ModelInfo, cpu_threads: int) -> dict[str, Any]:
        threads = map_thread_count(cpu_threads, os.cpu_count() or 1)
        params = dict(model.to_engine_params())
        # 底层键名与本项目 runtime.cpu_threads 不同名（design D6），此处单点映射
        params["EngineConfig.onnxruntime.intra_op_num_threads"] = threads
        params["EngineConfig.onnxruntime.inter_op_num_threads"] = threads
        return params

    @property
    def model_name(self) -> str:
        return self._model.name

    @property
    def model_id(self) -> str:
        return self._model.model_id

    @property
    def engine_loaded(self) -> bool:
        return self._engine is not None

    def preload(self) -> None:
        """显式加载引擎——worker 在识别前调用，作为状态机
        「加载模型 → 识别中」的分界（spec: ocr-execution）。"""
        self._ensure_engine()

    def recognize(self, image: np.ndarray, *, scale: float = 1.0) -> OcrResult:
        """执行一次识别。输入为 BGR ndarray；scale 由输入层缩放时带入。"""
        if not isinstance(image, np.ndarray) or image.size == 0:
            raise InvalidImageError("图像数据为空或格式无效", detail=repr(type(image)))

        engine = self._ensure_engine()
        height, width = image.shape[:2]
        start = time.perf_counter()
        try:
            output = engine(image)
        except OcrError:
            raise
        except Exception as exc:
            logger.exception("识别执行异常：%s", exc)
            raise RecognitionError(
                "识别过程发生错误，请重试或更换图片", detail=repr(exc)
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000

        result = self._convert_output(output, elapsed_ms=elapsed_ms, width=width, height=height, scale=scale)
        log_recognition_summary(
            width=width, height=height, lines=result.line_count, elapsed_ms=elapsed_ms
        )
        return result

    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine

        missing = [
            str(path)
            for path in (self._model.det_path, self._model.rec_path)
            if not Path(path).is_file()
        ]
        if missing:
            raise ModelMissingError(
                "模型文件缺失，请重新获取或恢复程序目录", detail="缺失：" + "; ".join(missing)
            )

        logger.info("开始加载模型：%s", self._model.model_id)
        start = time.perf_counter()
        try:
            engine = self._engine_factory(self._engine_params)
        except Exception as exc:
            logger.exception("模型加载失败：%s", self._model.model_id)
            raise ModelLoadError(
                "模型加载失败，程序可能已损坏，请重新获取", detail=repr(exc)
            ) from exc
        load_ms = (time.perf_counter() - start) * 1000

        # 引擎初始化可能重挂第三方 logger 的 handler，接管必须在其后重做
        silence_third_party_loggers()
        self._engine = engine
        logger.info(
            "模型已加载：%s 耗时=%.1fms", self._model.model_id, load_ms
        )
        return self._engine

    @staticmethod
    def _convert_output(
        output: Any,
        *,
        elapsed_ms: float,
        width: int,
        height: int,
        scale: float,
    ) -> OcrResult:
        """RapidOCROutput → OcrResult；None 字段规范化为空集合（spec: ocr-engine）。"""
        txts = list(output.txts) if output is not None and output.txts else []
        if not txts:
            return OcrResult.empty(
                elapsed_ms=elapsed_ms, width=width, height=height, scale=scale
            )

        boxes = output.boxes if output.boxes is not None else (None,) * len(txts)
        scores = output.scores if output.scores is not None else (None,) * len(txts)
        lines = []
        for index, text in enumerate(txts):
            quad = boxes[index] if index < len(boxes) else None
            box = (
                tuple((float(x), float(y)) for x, y in quad)
                if quad is not None
                else ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0))
            )
            score = float(scores[index]) if index < len(scores) and scores[index] is not None else 0.0
            lines.append(OcrLine(text=text, score=score, box=box))
        return OcrResult(
            text=merge_line_texts(txts),
            lines=tuple(lines),
            elapsed_ms=elapsed_ms,
            width=width,
            height=height,
            scale=scale,
        )
