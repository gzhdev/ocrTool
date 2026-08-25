"""全局快捷键（spec: global-hotkey）单元测试。

- 组合解析/格式化与黑名单（design D6）四层规则逐条验证；
- 真实 RegisterHotKey 注册/冲突/注销（本机 Windows，冷门组合避免环境干扰）；
- WM_HOTKEY 消息分发与长按去重（构造 MSG 直接喂给原生过滤器——
  不合成真实键盘输入，不触碰用户环境）。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ocrtool.platform.hotkey import (
    WM_HOTKEY,
    GlobalHotkey,
    HotkeyCombo,
    validate_combo,
)
from ocrtool.ui.widgets.hotkey_capture_dialog import HotkeyCaptureDialog

# 冷门组合：避开常见软件（输入法/截图工具/IDE）占用的键位
COMBO_A = HotkeyCombo.parse("Ctrl+Alt+F9")
COMBO_B = HotkeyCombo.parse("Alt+Shift+J")


class TestHotkeyCombo:
    def test_解析与格式化往返(self):
        for text in ("Alt+Shift+A", "Ctrl+Alt+F5", "Ctrl+Shift+7"):
            assert HotkeyCombo.parse(text).format() == text

    def test_格式化修饰键顺序稳定(self):
        combo = HotkeyCombo.parse("Shift+Ctrl+A")
        assert combo.format() == "Ctrl+Shift+A"

    @pytest.mark.parametrize(
        ("text", "fragment"),
        [
            ("", "不能为空"),
            ("Ctrl+Meta+A", "未知的修饰键"),
            ("Ctrl+Alt", "非修饰键结尾"),
            ("Ctrl+Alt+Pause", "不支持的主键"),
        ],
    )
    def test_非法输入给出可读原因(self, text, fragment):
        with pytest.raises(ValueError, match=fragment):
            HotkeyCombo.parse(text)


class TestBlacklist:
    @pytest.mark.parametrize(
        "text",
        [
            "A",  # 无修饰单键
            "F5",  # 无修饰功能键
            "Win+D",  # 系统组合
            "Win+F9",
            "Ctrl+C",  # 单 Ctrl：通用编辑
            "Ctrl+S",
            "Alt+Tab",  # 单 Alt：系统组合
            "Alt+F4",
            "Shift+A",  # 单 Shift：截走大写输入
        ],
    )
    def test_黑名单组合被拒绝(self, text):
        assert validate_combo(HotkeyCombo.parse(text)) is not None

    @pytest.mark.parametrize("text", ["Ctrl+Alt+Left", "Alt+Shift+Tab", "Ctrl+Shift+Space"])
    def test_保留主键无论修饰键均被拒绝(self, text):
        assert validate_combo(HotkeyCombo.parse(text)) is not None

    @pytest.mark.parametrize(
        "text", ["Alt+Shift+A", "Ctrl+Alt+F9", "Ctrl+Shift+J", "Ctrl+Alt+Shift+B"]
    )
    def test_合法双修饰组合通过(self, text):
        assert validate_combo(HotkeyCombo.parse(text)) is None

    def test_拒绝原因不含技术细节且指向操作(self):
        reason = validate_combo(HotkeyCombo.parse("Ctrl+C"))
        assert "修饰键" in reason  # 可读说明，而非错误码


class TestRegisterLifecycle:
    def test_黑名单组合注册被拒且给出可读原因(self, qapp):
        hotkey = GlobalHotkey()
        assert hotkey.register(HotkeyCombo.parse("Ctrl+C")) is False
        assert "修饰键" in hotkey.last_error
        assert hotkey.registered is False

    def test_注册与注销_注销后可再注册(self, qapp):
        hotkey = GlobalHotkey()
        try:
            assert hotkey.register(COMBO_A) is True
            assert hotkey.registered
        finally:
            hotkey.unregister()
        assert not hotkey.registered
        # 退出后立即重注册必须成功（spec: 退出时注销快捷键）
        try:
            assert hotkey.register(COMBO_A) is True
        finally:
            hotkey.unregister()

    def test_组合被占用时注册失败且原因可见(self, qapp):
        holder = GlobalHotkey(hotkey_id=101)
        late = GlobalHotkey(hotkey_id=102)
        try:
            assert holder.register(COMBO_B) is True
            assert late.register(COMBO_B) is False
            assert "已被其他程序占用" in late.last_error
            assert late.registered is False
        finally:
            holder.unregister()
            late.unregister()

    def test_重绑成功旧组合让位(self, qapp):
        hotkey = GlobalHotkey()
        try:
            assert hotkey.register(COMBO_A) is True
            ok, message = hotkey.rebind(COMBO_B)
            assert ok, message
            assert hotkey.combo == COMBO_B
        finally:
            hotkey.unregister()

    def test_重绑失败恢复原组合(self, qapp):
        holder = GlobalHotkey(hotkey_id=201)  # 占住新组合的「第三方」
        hotkey = GlobalHotkey(hotkey_id=202)
        try:
            assert hotkey.register(COMBO_A) is True
            assert holder.register(COMBO_B) is True
            ok, message = hotkey.rebind(COMBO_B)  # B 被占用 → 失败
            assert ok is False
            assert "已保留原组合" in message or "不可用" in message
            assert hotkey.combo == COMBO_A  # 原组合恢复注册且继续生效
        finally:
            holder.unregister()
            hotkey.unregister()


def make_wm_hotkey_message(hotkey_id: int, message_id: int = WM_HOTKEY):
    msg = wintypes.MSG()
    msg.message = message_id
    msg.wParam = hotkey_id
    return ctypes.pointer(msg)


class TestMessageDispatch:
    def _dispatch(self, hotkey: GlobalHotkey, ptr, event_type=b"windows_generic_MSG"):
        return hotkey._filter.nativeEventFilter(event_type, ptr)

    def test_注册后安装原生过滤器(self, qapp):
        hotkey = GlobalHotkey()
        try:
            hotkey.register(COMBO_A)
            assert hotkey._filter is not None
        finally:
            hotkey.unregister()
        assert hotkey._filter is None  # 注销后卸载

    def test_本热键消息触发一次(self, qapp):
        hotkey = GlobalHotkey()
        fired = []
        hotkey.triggered.connect(lambda: fired.append(1))
        try:
            hotkey.register(COMBO_A)
            self._dispatch(hotkey, make_wm_hotkey_message(1))
            assert fired == [1]
        finally:
            hotkey.unregister()

    def test_长按重复被抑制(self, qapp):
        hotkey = GlobalHotkey()
        fired = []
        hotkey.triggered.connect(lambda: fired.append(1))
        try:
            hotkey.register(COMBO_A)
            for _ in range(5):  # 按住期间的自动重复投递
                self._dispatch(hotkey, make_wm_hotkey_message(1))
            assert fired == [1]  # 只触发一次
        finally:
            hotkey.unregister()

    def test_组合释放后可再次触发(self, qapp):
        import time as _time

        hotkey = GlobalHotkey()
        fired = []
        hotkey.triggered.connect(lambda: fired.append(1))
        try:
            hotkey.register(COMBO_A)
            self._dispatch(hotkey, make_wm_hotkey_message(1))
            # 测试环境无真实按键：释放轮询首跳即观察到「已释放」并重新武装
            deadline = _time.monotonic() + 1.0
            while hotkey._awaiting_release and _time.monotonic() < deadline:
                qapp.processEvents()
                _time.sleep(0.02)
            assert not hotkey._awaiting_release
            self._dispatch(hotkey, make_wm_hotkey_message(1))
            assert fired == [1, 1]  # 第二次独立按下正常触发
        finally:
            hotkey.unregister()

    def test_其他消息与他例热键id不触发(self, qapp):
        hotkey = GlobalHotkey(hotkey_id=1)
        fired = []
        hotkey.triggered.connect(lambda: fired.append(1))
        try:
            hotkey.register(COMBO_A)
            self._dispatch(hotkey, make_wm_hotkey_message(999))  # 他人 id
            self._dispatch(
                hotkey, make_wm_hotkey_message(1, message_id=0x0010)  # WM_CLOSE
            )
            self._dispatch(
                hotkey, make_wm_hotkey_message(1), event_type=b"other_event"
            )
            assert fired == []
        finally:
            hotkey.unregister()


class TestCaptureDialog:
    def _press(self, dialog, key, modifiers):
        event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers)
        QApplication.postEvent(dialog, event)
        QApplication.processEvents()

    def test_合法组合被捕获并接受(self, qapp):
        from PySide6.QtCore import Qt

        dialog = HotkeyCaptureDialog(current_text="Alt+Shift+A")
        dialog.show()
        self._press(
            dialog,
            Qt.Key.Key_J,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
        )
        assert dialog.combo is not None
        assert dialog.combo.format() == "Ctrl+Alt+J"

    def test_黑名单组合在框内说明原因且不关闭(self, qapp):
        from PySide6.QtCore import Qt

        dialog = HotkeyCaptureDialog(current_text="")
        dialog.show()
        self._press(dialog, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        assert dialog.combo is None
        assert "修饰键" in dialog._feedback.text()
        assert dialog.isVisible()

    def test_esc_取消(self, qapp):
        from PySide6.QtCore import Qt

        dialog = HotkeyCaptureDialog(current_text="Alt+Shift+A")
        dialog.show()
        self._press(dialog, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        assert dialog.combo is None
