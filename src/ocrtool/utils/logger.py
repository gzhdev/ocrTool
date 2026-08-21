"""日志系统（spec: app-logging）。

- 落地 `USER_ROOT/logs/ocrtool.log`，RotatingFileHandler 5 MB × 3；
- 隐私边界：绝不记录识别文本与图像内容，只记尺寸/行数/耗时；
- 主动接管第三方 OCR 组件的 logger（清空 handler、断开传播）；
- 初始化依赖 paths.initialize() 已完成（路径先于日志，spec: app-paths）。
"""

from __future__ import annotations

import logging
import platform
import sys
from logging.handlers import RotatingFileHandler

from ocrtool import __version__
from ocrtool.app import paths

LOG_FILE_NAME = "ocrtool.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

_LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-5s [%(threadName)s] %(name)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# rapidocr 自带 "RapidOCR" logger，会向 stderr 输出识别内容，必须接管
THIRD_PARTY_LOGGER_NAMES = ("RapidOCR", "rapidocr")


def get_logger() -> logging.Logger:
    return logging.getLogger("ocrtool")


def setup_logging(level: str = "INFO") -> logging.Logger:
    """初始化日志；必须在 paths.initialize() 之后调用。"""
    log_dir = paths.log_dir()  # 未初始化路径时在此抛 RuntimeError，强制顺序
    logger = get_logger()
    logger.setLevel(level.upper())
    handler = RotatingFileHandler(
        log_dir / LOG_FILE_NAME,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    for old in logger.handlers[:]:
        logger.removeHandler(old)
        old.close()
    logger.addHandler(handler)
    logger.propagate = False
    silence_third_party_loggers()
    return logger


def silence_third_party_loggers() -> None:
    """清空第三方组件 logger 的 handler 并断开传播，抑制其自带输出。"""
    for name in THIRD_PARTY_LOGGER_NAMES:
        third_party = logging.getLogger(name)
        third_party.handlers.clear()
        third_party.propagate = False


def log_startup_environment(*, provider: str, cpu_threads: int) -> None:
    """记录启动环境首段：版本 / OS / 运行时 / provider / 线程数 / 存储模式 / USER_ROOT。"""
    get_logger().info(
        "启动环境: 版本=%s 操作系统=%s 运行时=%s 推理执行提供者=%s 推理线程数=%d "
        "存储模式=%s 可写状态根=%s",
        __version__,
        platform.platform(),
        sys.version.replace("\n", " "),
        provider,
        cpu_threads,
        paths.storage_mode().value,
        paths.user_root(),
    )


def log_recognition_summary(
    *, width: int, height: int, lines: int, elapsed_ms: float
) -> None:
    """识别摘要——隐私边界的唯一许可格式：只记尺寸、行数与耗时。"""
    get_logger().info(
        "识别完成: 尺寸=%dx%d 行数=%d 耗时=%.1fms", width, height, lines, elapsed_ms
    )
