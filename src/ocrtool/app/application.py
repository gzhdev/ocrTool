"""应用组装（spec: main-window）：初始化顺序与组件接线。

启动顺序（spec: app-paths / app-logging / app-config）：
路径 → 日志 → 配置 → 环境记录 → 服务与控制器 → 主窗口。
启动不加载模型（spec: ocr-engine 惰性加载）。
"""

from __future__ import annotations

import logging
import sys

from ocrtool.app import paths
from ocrtool.config import manager as config_manager_mod
from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.ocr import model_manager
from ocrtool.ocr.service import OCRService
from ocrtool.ui.main_window import MainWindow
from ocrtool.utils import logger as app_logging

logger = logging.getLogger("ocrtool.app")


class ApplicationStartupError(RuntimeError):
    """组装失败（路径解析失败等），携带用户可读说明。"""


def bootstrap() -> tuple[OCRService, OcrController, object, list[str]]:
    """完成启动序列（不含 UI 事件循环），返回组装好的组件。

    返回 (服务, 控制器, 配置, 配置警告)。模型缺失不在此失败——自检只查
    存在性，明确的错误等到用户实际识别时呈现（spec: main-window）。
    """
    paths.initialize()  # PathResolutionError 由调用方转译为用户可读信息
    # 日志必须先于配置初挂（默认级）：配置加载期的错误（默认配置缺失、
    # 用户配置损坏）依赖 file handler 落盘（spec: app-config 记录错误日志）
    app_logging.setup_logging()
    config = config_manager_mod.load_config()
    app_logging.setup_logging(level=config.get("logging.level", "INFO"))
    app_logging.log_startup_environment(
        provider=config.get("runtime.provider", "CPUExecutionProvider"),
        cpu_threads=int(config.get("runtime.cpu_threads", 4)),
    )

    model = model_manager.resolve_model(paths.model_dir(), config.get("ocr.model"))
    if model is None:
        # 占位模型信息：界面状态区仍可组装，识别时报告模型缺失
        from ocrtool.ocr.model_manager import ModelInfo

        model = ModelInfo(
            model_id="<missing>",
            directory=paths.model_dir(),
            det_path=paths.model_dir() / "missing.onnx",
            rec_path=paths.model_dir() / "missing.onnx",
            name="模型缺失",
            recommended=False,
            language_coverage=(),
            raw={},
        )

    service = OCRService(model, cpu_threads=int(config.get("runtime.cpu_threads", 4)))
    controller = OcrController(service)
    assert not service.engine_loaded  # 启动不加载模型（spec: ocr-engine）
    return service, controller, config, list(config.warnings)


def create_main_window(controller: OcrController, config, warnings: list[str]) -> MainWindow:
    return MainWindow(controller, config, startup_warnings=warnings)


def run() -> int:
    """图形界面入口。"""
    from PySide6.QtWidgets import QApplication

    try:
        service, controller, config, warnings = bootstrap()
    except paths.PathResolutionError as exc:
        # 日志系统依赖路径解析，此刻必然未初始化，只能写标准错误
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1

    try:
        app = QApplication(sys.argv)
        window = create_main_window(controller, config, warnings)
        window.show()
    except Exception:
        # UI 组装异常必须有日志防护（还原旧 main.py 行为，review 50-4）
        logger.exception("启动失败：初始化界面时发生未预期异常")
        raise
    return app.exec()
