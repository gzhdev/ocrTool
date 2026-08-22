"""状态区（spec: main-window）：模型、状态、耗时、行数。"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class StatusWidget(QWidget):
    """四个信息段的轻量组合；全部可独立更新。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model_label = QLabel("模型：-")
        self._state_label = QLabel("就绪")
        self._timing_label = QLabel("-")
        self._lines_label = QLabel("-")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.addWidget(self._model_label)
        layout.addStretch(1)
        layout.addWidget(self._state_label)
        layout.addWidget(self._timing_label)
        layout.addWidget(self._lines_label)

    def set_model(self, name: str) -> None:
        self._model_label.setText(f"模型：{name}")

    def set_state(self, text: str) -> None:
        self._state_label.setText(text)

    def set_timing(self, elapsed_ms: float) -> None:
        if elapsed_ms >= 1000:
            self._timing_label.setText(f"耗时 {elapsed_ms / 1000:.2f} s")
        else:
            self._timing_label.setText(f"耗时 {elapsed_ms:.0f} ms")

    def set_lines(self, count: int) -> None:
        self._lines_label.setText(f"行数 {count}")

    def clear_run_info(self) -> None:
        """新一轮识别开始前清除上次的耗时与行数。

        状态文本不在此清除——瞬时终态（完成/空结果/失败）的展示需要
        驻留到用户下一次操作，由调用方显式重置。
        """
        self._timing_label.setText("-")
        self._lines_label.setText("-")
