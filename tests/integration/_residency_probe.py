"""驻留探针（测试夹具，非测试）：最小常驻骨架子进程。

以真实进程验证单实例语义（spec: single-instance）：启动即检测端点并
写 outcome 标记；驻留期间收到激活请求写 activated 标记；发现 stop 标记
则正常退出（走 shutdown 释放端点）。被 taskkill /F 杀死则模拟强杀残留
场景（不走任何清理路径）。
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ocrtool.platform.single_instance import (  # noqa: E402
    SingleInstanceGuard,
    SingleInstanceOutcome,
)


def main() -> int:
    name, workdir = sys.argv[1], Path(sys.argv[2])
    workdir.mkdir(parents=True, exist_ok=True)
    app = QApplication([])

    guard = SingleInstanceGuard(name=name)
    outcome = guard.check_and_listen()
    (workdir / "outcome.txt").write_text(outcome.value, encoding="utf-8")
    if outcome is not SingleInstanceOutcome.FIRST_INSTANCE:
        return 0  # 重复实例：传达激活意图后立即退出，不驻留

    (workdir / "ready.txt").write_text("1", encoding="utf-8")
    guard.activationRequested.connect(
        lambda: (workdir / "activated.txt").write_text("1", encoding="utf-8")
    )

    def check_stop() -> None:
        if (workdir / "stop.txt").exists():
            guard.shutdown()
            app.quit()

    timer = QTimer()
    timer.timeout.connect(check_stop)
    timer.start(200)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
