"""Qt 测试辅助：驱动主线程事件循环直到条件成立。"""

from __future__ import annotations

import time


def process_events_until(qapp, predicate, *, timeout_s: float = 10.0) -> None:
    """持续投递主线程事件直到条件成立——事件处理本身即被测对象。

    每轮 processEvents 之后短暂让出 CPU，避免空转占满一个核。
    """
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("process_events_until 超时")
        qapp.processEvents()
        time.sleep(0.005)
