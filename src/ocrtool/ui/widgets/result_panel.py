"""识别结果面板（spec: main-window）：展示、选中、复制全部、清空。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class ResultPanel(QWidget):
    statusMessage = Signal(str)  # 普通操作反馈——由状态区呈现，不弹窗

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setPlaceholderText("识别结果将显示在这里")

        self._copy_button = QPushButton("复制全部")
        self._copy_button.clicked.connect(self.copy_all)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._text_edit)
        layout.addWidget(self._copy_button)

    def set_result(self, text: str) -> None:
        self._text_edit.setPlainText(text)

    @property
    def text(self) -> str:
        return self._text_edit.toPlainText()

    def copy_all(self) -> None:
        """复制全部；空结果不改剪贴板、只提示（spec: main-window）。"""
        text = self._text_edit.toPlainText()
        if not text.strip():
            self.statusMessage.emit("当前无可复制内容")
            return
        QApplication.clipboard().setText(text)
        self.statusMessage.emit("已复制到剪贴板")

    def clear(self) -> None:
        self._text_edit.setPlainText("")
