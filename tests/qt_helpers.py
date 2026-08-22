"""Qt 测试辅助：驱动主线程事件循环直到条件成立；合成鼠标事件。"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent


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


def mouse_press(widget, x: float, y: float, button=Qt.MouseButton.LeftButton) -> None:
    widget.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(x, y), QPointF(x, y),
            button, button, Qt.KeyboardModifier.NoModifier,
        )
    )


def mouse_move(widget, x: float, y: float) -> None:
    widget.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(x, y), QPointF(x, y),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def mouse_release(widget, x: float, y: float) -> None:
    widget.mouseReleaseEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(x, y), QPointF(x, y),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
