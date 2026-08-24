"""识别结果面板（spec: main-window）：展示、选中、复制全部、清空、行高亮联动。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QApplication,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# 与预览区位置框高亮同色系（橙），指向框时用户能把两处高亮对应起来
LINE_HIGHLIGHT_COLOR = QColor(0xFF, 0x9A, 0x00, 76)


class ResultPanel(QWidget):
    statusMessage = Signal(str)  # 普通操作反馈——由状态区呈现，不弹窗
    currentLineChanged = Signal(int)  # 光标所在结果行变化（框↔行联动的行侧来源）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setPlaceholderText("识别结果将显示在这里")
        self._text_edit.cursorPositionChanged.connect(self._forward_cursor_line)

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
        self.clear_highlight()

    # ---- 行高亮与联动（spec: main-window 识别框与结果文本联动）----

    def highlight_line(self, index: int) -> None:
        """高亮第 index 行（与 OCRLine 序一致），必要时滚动到可见范围。

        光标同步移至该行：指向位置框时用户视点被引导到对应文本。移动光标
        会再次触发 currentLineChanged——同索引联动幂等，不构成振荡。
        """
        document = self._text_edit.document()
        if index < 0 or index >= document.blockCount():
            self.clear_highlight()
            return
        cursor = QTextCursor(document.findBlockByNumber(index))
        self._text_edit.setTextCursor(cursor)
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(LINE_HIGHLIGHT_COLOR)
        selection.format.setProperty(
            QTextFormat.Property.FullWidthSelection, True
        )  # 高亮整行宽度而非仅文本长度
        selection.cursor = cursor
        self._text_edit.setExtraSelections([selection])
        self._text_edit.ensureCursorVisible()

    def clear_highlight(self) -> None:
        self._text_edit.setExtraSelections([])

    def highlighted_line(self) -> int:
        selections = self._text_edit.extraSelections()
        if not selections:
            return -1
        return selections[0].cursor.blockNumber()

    def _forward_cursor_line(self) -> None:
        self.currentLineChanged.emit(self._text_edit.textCursor().blockNumber())
