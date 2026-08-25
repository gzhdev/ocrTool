"""快捷键捕获对话框（spec: global-hotkey 快捷键可重新绑定）。

按下新组合即捕获；黑名单组合在框内即时给出拒绝原因（design D6），
不产生「设置了却无效」的错觉。Esc 取消。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from ocrtool.platform.hotkey import HotkeyCombo, validate_combo

_MODIFIER_KEYS = {
    Qt.Key.Key_Control,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Shift,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
}


class HotkeyCaptureDialog(QDialog):
    def __init__(self, current_text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置全局快捷键")
        self.setMinimumWidth(360)
        self.combo: HotkeyCombo | None = None

        layout = QVBoxLayout(self)
        current = QLabel(f"当前组合：{current_text or '未设置'}")
        hint = QLabel("请按下新的组合键（需要至少两个修饰键，Esc 取消）")
        hint.setWordWrap(True)
        self._feedback = QLabel("")
        self._feedback.setWordWrap(True)
        self._feedback.setStyleSheet("color: #b91c1c;")
        layout.addWidget(current)
        layout.addWidget(hint)
        layout.addWidget(self._feedback)

    def keyPressEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in _MODIFIER_KEYS or key == Qt.Key.Key_unknown:
            return  # 只按了修饰键：等待主键

        key_name = QKeySequence(key).toString()
        modifiers: set[str] = set()
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            modifiers.add("Ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            modifiers.add("Alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            modifiers.add("Shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            modifiers.add("Win")

        try:
            combo = HotkeyCombo(frozenset(modifiers), key_name)
        except ValueError as exc:
            self._feedback.setText(str(exc))
            return
        reason = validate_combo(combo)
        if reason is not None:
            self._feedback.setText(reason)
            return
        self.combo = combo
        self.accept()
