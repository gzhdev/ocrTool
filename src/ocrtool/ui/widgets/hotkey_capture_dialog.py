"""快捷键捕获对话框（spec: global-hotkey 快捷键可重新绑定）。

按下新组合即捕获；黑名单组合在框内即时给出拒绝原因（design D6），
不产生「设置了却无效」的错觉。Esc 取消。

符号键归一（review 75-1）：Shift 按下期间 event.key() 返回布局映射后的
符号键（美式/中文布局 Shift+1 → Key_Exclam），直接入名会绕过主键校验
并在注册链抛 KeyError。此处先映射回 unshifted 数字主键；无法映射的
符号（非拉丁布局字母等）经 HotkeyCombo.parse 可读拒绝。
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

# Shift+数字产出的符号键 → unshifted 数字主键（review 75-1）
_SYMBOL_TO_DIGIT = {
    Qt.Key.Key_Exclam: "1",
    Qt.Key.Key_At: "2",
    Qt.Key.Key_NumberSign: "3",
    Qt.Key.Key_Dollar: "4",
    Qt.Key.Key_Percent: "5",
    Qt.Key.Key_AsciiCircum: "6",
    Qt.Key.Key_Ampersand: "7",
    Qt.Key.Key_Asterisk: "8",
    Qt.Key.Key_ParenLeft: "9",
    Qt.Key.Key_ParenRight: "0",
}


def _key_name_for(key: int) -> str:
    """事件主键 → 组合记名主键：符号键归一为数字，其余取键名原文。"""
    if key in _SYMBOL_TO_DIGIT:
        return _SYMBOL_TO_DIGIT[key]
    return QKeySequence(key).toString()


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

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in _MODIFIER_KEYS or key == Qt.Key.Key_unknown:
            return  # 只按了修饰键：等待主键

        key_name = _key_name_for(key)
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

        ordered = [m for m in ("Ctrl", "Alt", "Shift", "Win") if m in modifiers]
        # 经 parse 构造：主键合法性（含不支持符号的拒绝）由此统一把关，
        # 对话框不再绕过校验直接组装（review 75-1 的根因之一）
        try:
            combo = HotkeyCombo.parse("+".join([*ordered, key_name]))
        except ValueError as exc:
            self._feedback.setText(str(exc))
            return
        reason = validate_combo(combo)
        if reason is not None:
            self._feedback.setText(reason)
            return
        self.combo = combo
        self.accept()
