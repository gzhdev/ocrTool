"""OCRTool 应用入口。

启动顺序（spec: app-paths / app-logging / app-config）：
路径解析 → 日志 → 配置 → 启动环境记录 → 启动自检 → UI。

`--self-test`：无界面的端到端自检（生成中英混合样本图 → 本地模型识别 →
打印行数 → 退出），供发布冒烟验收脚本化调用（spec: packaging）。
"""

import sys
import time

from PySide6.QtWidgets import QApplication, QMainWindow

from ocrtool import __version__
from ocrtool.app import paths
from ocrtool.config import manager as config_manager_mod
from ocrtool.ocr import model_manager
from ocrtool.utils import logger as app_logging


def window_title() -> str:
    """界面显示的版本（spec: packaging 三处一致性的界面位）。"""
    return f"OCRTool {__version__}"


def _startup():
    """路径 → 日志 → 配置 → 环境记录 → 模型自检；返回配置。"""
    try:
        paths.initialize()
    except paths.PathResolutionError as exc:
        # 日志系统尚未就绪（其初始化依赖路径），只能写标准错误
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1)

    app_logging.setup_logging()

    config = config_manager_mod.load_config()
    app_logging.setup_logging(level=config.get("logging.level", "INFO"))

    app_logging.log_startup_environment(
        provider=config.get("runtime.provider", "CPUExecutionProvider"),
        cpu_threads=int(config.get("runtime.cpu_threads", 4)),
    )

    # 启动自检：仅扫描文件存在性（spec: model-assets），不加载 ONNX
    model_manager.resolve_model(paths.model_dir(), config.get("ocr.model"))
    return config


def _make_sample_image():
    """生成中英混合样本图（RGB -> BGR ndarray），冒烟自检用。"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            font = ImageFont.truetype(candidate, 48)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    img = Image.new("RGB", (760, 300), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 60), "OCRTool Self Test 2026", fill="black", font=font)
    draw.text((40, 160), "中英文混合识别冒烟验收", fill="black", font=font)
    return np.asarray(img)[..., ::-1].copy()


def run_self_test() -> int:
    """端到端自检：本地模型显式路径识别一张中英混合样本图。"""
    _startup()
    resolved = model_manager.resolve_model(
        paths.model_dir(), None
    )
    if resolved is None:
        print("SELF-TEST FAIL: 无可用模型")
        return 1

    from rapidocr import RapidOCR

    image = _make_sample_image()
    app_logging.silence_third_party_loggers()  # 引擎初始化可能重挂其 handler
    engine = RapidOCR(params=resolved.to_engine_params())
    start = time.perf_counter()
    result = engine(image)
    elapsed_ms = (time.perf_counter() - start) * 1000

    txts = list(result.txts) if result is not None and result.txts else []
    height, width = image.shape[:2]
    app_logging.log_recognition_summary(
        width=width, height=height, lines=len(txts), elapsed_ms=elapsed_ms
    )

    if not txts:
        print("SELF-TEST FAIL: 识别结果为空")
        return 1
    print(f"SELF-TEST OK: lines={len(txts)}")
    for text in txts:
        print(f"  {text}")
    return 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return run_self_test()

    _startup()

    try:
        app = QApplication(sys.argv)
        window = QMainWindow()
        window.setWindowTitle(window_title())
        window.resize(480, 320)
        window.show()
    except Exception:
        app_logging.get_logger().exception("启动失败：初始化界面时发生未预期异常")
        raise

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
