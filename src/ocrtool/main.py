"""OCRTool 应用入口。

spike 临时代码已随任务 1.8 移除；本入口随任务组 3-5（路径/日志/配置）逐步成形。
"""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("OCRTool")
    window.resize(480, 320)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
