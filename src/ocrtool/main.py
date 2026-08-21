"""OCRTool 应用入口。

启动顺序（spec: app-paths / app-logging / app-config）：
路径解析 → 日志 → 配置 → 启动环境记录 → UI。
"""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow

from ocrtool.app import paths
from ocrtool.config import manager as config_manager_mod
from ocrtool.ocr import model_manager
from ocrtool.utils import logger as app_logging


def main() -> int:
    try:
        paths.initialize()
    except paths.PathResolutionError as exc:
        # 日志系统尚未就绪（其初始化依赖路径），只能写标准错误
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1

    app_logging.setup_logging()

    config = config_manager_mod.load_config()
    app_logging.setup_logging(level=config.get("logging.level", "INFO"))

    app_logging.log_startup_environment(
        provider=config.get("runtime.provider", "CPUExecutionProvider"),
        cpu_threads=int(config.get("runtime.cpu_threads", 4)),
    )

    # 启动自检：仅扫描文件存在性（spec: model-assets），不加载 ONNX；
    # 无可用模型时程序仍可启动，错误留待用户实际发起识别时呈现
    model_manager.resolve_model(paths.model_dir(), config.get("ocr.model"))

    try:
        app = QApplication(sys.argv)
        window = QMainWindow()
        window.setWindowTitle("OCRTool")
        window.resize(480, 320)
        window.show()
    except Exception:
        app_logging.get_logger().exception("启动失败：初始化界面时发生未预期异常")
        raise

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
