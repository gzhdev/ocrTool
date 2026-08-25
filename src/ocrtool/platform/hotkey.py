"""全局快捷键（spec: global-hotkey）——注册式热键，不做键盘监听。

design D5 的三条独立理由：隐私（只接触被注册的组合，接触不到用户
其他按键——含密码）、安全软件（全局键盘钩子是键盘记录器特征）、
不抢占（组合被占用时系统直接拒绝注册，不会从其他程序手里夺走热键）。

实现映射：Win32 RegisterHotKey / UnregisterHotKey（ctypes 直调，
零第三方依赖）；WM_HOTKEY 经 QAbstractNativeEventFilter 在 Qt 主线程
消息循环中接收。长按产生的自动重复以时间阈值抑制（spec: 长按不重复
触发）。黑名单在 :func:`validate_combo`（design D6：用户不该有能力
通过一次设置把自己的系统弄到不可用）。
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass
from enum import IntFlag

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal

logger = logging.getLogger("ocrtool.platform")

WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# 组合释放的轮询周期：触发后以该周期查询键态，观察到释放才允许
# 下一次触发（spec: 长按不重复触发）。Windows 键盘重复延迟约 500ms，
# 纯时间阈值会在窗口期外放行重复投递；人类连按间隔下限约 50ms，
# 30ms 轮询足以捕捉两次独立按下之间的释放间隙。
_RELEASE_POLL_MS = 30

_MODIFIER_VK = {
    "Ctrl": 0x11,
    "Alt": 0x12,
    "Shift": 0x10,
    "Win": 0x5B,
}

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RegisterHotKey.argtypes = (
    wintypes.HWND,
    ctypes.c_int,
    wintypes.UINT,
    wintypes.UINT,
)
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.UnregisterHotKey.restype = wintypes.BOOL
_user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
_user32.GetAsyncKeyState.restype = ctypes.c_short


class NativeModifier(IntFlag):
    ALT = 0x0001
    CONTROL = 0x0002
    SHIFT = 0x0004
    WIN = 0x0008


# 组合字符串的修饰键记名（解析与格式化共用，顺序即输出顺序）
_MODIFIER_ORDER = ("Ctrl", "Alt", "Shift", "Win")
_MODIFIER_BITS = {
    "Ctrl": NativeModifier.CONTROL,
    "Alt": NativeModifier.ALT,
    "Shift": NativeModifier.SHIFT,
    "Win": NativeModifier.WIN,
}

# 主键 → 虚拟键码。含保留键（Tab/方向等）：黑名单的语义是「可解析、
# 可读地拒绝」，而不是在解析层报「不支持」（spec: global-hotkey 保留
# 组合键拒绝并说明原因）
_KEY_VK = {
    **{chr(ord("A") + i): 0x41 + i for i in range(26)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"F{n}": 0x70 + n - 1 for n in range(1, 13)},
    "Backspace": 0x08,
    "Tab": 0x09,
    "Enter": 0x0D,
    "Esc": 0x1B,
    "Space": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "Left": 0x25,
    "Up": 0x26,
    "Right": 0x27,
    "Down": 0x28,
    "PrtScn": 0x2C,
    "Insert": 0x2D,
    "Delete": 0x2E,
}

# 黑名单第三层：这些主键无论配什么修饰键都保留给系统或通用编辑
# （方向键=显卡旋转/导航，Tab/Enter/Esc=对话框导航，PrintScreen=截图，
#  Delete/Insert/Home/End/PageUp/PageDown/Backspace/Space=编辑与导航）
_RESERVED_KEYS = frozenset(
    {
        "Tab", "Enter", "Esc", "Space", "Backspace", "Delete", "Insert",
        "Home", "End", "PageUp", "PageDown", "PrtScn",
        "Up", "Down", "Left", "Right",
    }
)


@dataclass(frozen=True)
class HotkeyCombo:
    """一个全局快捷键组合（修饰键集合 + 主键）。"""

    modifiers: frozenset[str]
    key: str

    @classmethod
    def parse(cls, text: str) -> HotkeyCombo:
        """解析「Alt+Shift+A」形式；非法记名抛 ValueError（可读消息）。"""
        parts = [part.strip() for part in text.split("+") if part.strip()]
        if not parts:
            raise ValueError("快捷键不能为空")
        modifiers: set[str] = set()
        for part in parts[:-1]:
            if part not in _MODIFIER_BITS:
                raise ValueError(f"未知的修饰键：{part}")
            modifiers.add(part)
        key = parts[-1]
        if key in _MODIFIER_BITS:
            raise ValueError("组合必须以非修饰键结尾（如 A、F5、3）")
        if key not in _KEY_VK:
            raise ValueError(f"不支持的主键：{key}")
        return cls(modifiers=frozenset(modifiers), key=key)

    def format(self) -> str:
        ordered = [m for m in _MODIFIER_ORDER if m in self.modifiers]
        return "+".join([*ordered, self.key])

    def native_modifiers(self) -> int:
        bits = NativeModifier(0)
        for name in self.modifiers:
            bits |= _MODIFIER_BITS[name]
        return int(bits)

    def native_vk(self) -> int:
        return _KEY_VK[self.key]


def validate_combo(combo: HotkeyCombo) -> str | None:
    """黑名单校验（design D6）：返回拒绝原因，None 表示允许注册。

    规则（每条独立可解释）：
    1. 必须含修饰键——无修饰单键会把普通输入键变成全局热键；
    2. Win 不参与——Win+D/E/L/Tab 等系统组合保留；
    3. 至少两个修饰键——单 Ctrl/Alt/Shift 配字母数字会占用通用编辑
       （Ctrl+C/V/X/Z/A/S）、大写输入（Shift+字母）或菜单访问键
       （Alt+字母），单 Shift/Alt 同时覆盖 Alt+Tab / Alt+F4 等系统组合；
    4. 主键不得为系统保留键（方向、导航、Tab/Enter/Esc 等）。
    """
    if not combo.modifiers:
        return "快捷键必须包含修饰键（Ctrl / Alt / Shift 中至少两个）"
    if "Win" in combo.modifiers:
        return "不支持 Win 键组合——Win+D / Win+E 等系统快捷键需要保留"
    if len(combo.modifiers) < 2:
        return (
            "至少需要两个修饰键（如 Ctrl+Alt、Alt+Shift）：单个 Ctrl / Alt / Shift "
            "组合会占用复制粘贴、菜单访问等通用操作"
        )
    if combo.key in _RESERVED_KEYS:
        return f"按键 {combo.key} 保留给系统或通用编辑操作，不能用作快捷键"
    return None


def _pointer_value(message) -> int:
    """从 PySide6 传入的 void* 形参中取出地址。

    真实事件循环下为 Shiboken.VoidPtr（int() 直接给地址）；测试注入的
    ctypes 指针会被绑定层转为 8 字节小端 bytes。异常返回 0——
    MSG.from_address(0) 由上层 except 兜住，不影响消息循环。
    """
    try:
        return int(message)
    except (TypeError, ValueError):
        pass
    try:
        raw = bytes(message)
        return int.from_bytes(raw[:8], "little")
    except Exception:  # 任何形态异常都不能拖垮事件循环（有意兜底）
        return 0


class _HotkeyMessageFilter(QAbstractNativeEventFilter):
    """从 Qt 主线程消息循环中挑出本程序的 WM_HOTKEY。"""

    def __init__(self, hotkey_id: int, on_triggered) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._on_triggered = on_triggered

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        try:
            if bytes(event_type) == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(_pointer_value(message))
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    self._on_triggered()
        except Exception:  # 过滤器内异常不得中断消息循环（有意兜底）
            logger.exception("处理热键消息时发生未预期异常")
        return False


class GlobalHotkey(QObject):
    """一个全局热键的注册、接收与注销。

    必须在 QApplication 存在后使用（原生事件过滤器挂在其上）。
    """

    triggered = Signal()

    def __init__(self, hotkey_id: int = 1, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkey_id = hotkey_id
        self._combo: HotkeyCombo | None = None
        self._filter: _HotkeyMessageFilter | None = None
        self._awaiting_release = False
        self._release_timer = QTimer(self)
        self._release_timer.setInterval(_RELEASE_POLL_MS)
        self._release_timer.timeout.connect(self._check_released)
        self.last_error: str = ""

    @property
    def combo(self) -> HotkeyCombo | None:
        return self._combo

    @property
    def registered(self) -> bool:
        return self._combo is not None

    def register(self, combo: HotkeyCombo) -> bool:
        """注册组合；失败置 last_error（可读原因）并保持未注册状态。"""
        reason = validate_combo(combo)
        if reason is not None:
            self.last_error = reason
            logger.warning("快捷键组合被黑名单拒绝：%s（%s）", combo.format(), reason)
            return False
        if self._combo is not None:
            self.unregister()
        if _user32.RegisterHotKey(None, self._hotkey_id, combo.native_modifiers(), combo.native_vk()):
            self._combo = combo
            self._install_filter()
            self._awaiting_release = False
            self._release_timer.stop()
            logger.info("全局快捷键已注册：%s", combo.format())
            return True
        error_code = ctypes.get_last_error()
        if error_code == ERROR_HOTKEY_ALREADY_REGISTERED:
            self.last_error = f"组合键 {combo.format()} 已被其他程序占用"
        else:
            self.last_error = f"组合键 {combo.format()} 注册失败（系统错误 {error_code}）"
        logger.warning("快捷键注册失败：%s（错误码 %d）", combo.format(), error_code)
        return False

    def unregister(self) -> None:
        """注销当前组合；程序退出路径必经（spec: 退出时注销快捷键）。"""
        if self._combo is None:
            return
        if not _user32.UnregisterHotKey(None, self._hotkey_id):
            logger.warning(
                "快捷键注销失败：%s（错误码 %d）",
                self._combo.format(),
                ctypes.get_last_error(),
            )
        logger.info("全局快捷键已注销：%s", self._combo.format())
        self._combo = None
        self._remove_filter()

    def shutdown(self) -> None:
        self.unregister()

    def rebind(self, new_combo: HotkeyCombo) -> tuple[bool, str]:
        """重绑（spec: 快捷键可重新绑定）：先注销旧组合再注册新组合。

        失败时原组合恢复注册且继续生效（spec: 重新绑定失败）。
        返回 (是否成功, 可读消息)。
        """
        old_combo = self._combo
        if self.register(new_combo):  # register 内部先注销旧组合
            return True, f"快捷键已更新为 {new_combo.format()}"
        # 新组合注册失败：恢复旧组合（其注销由 register 内部完成）
        if old_combo is not None and not self.register(old_combo):
            logger.error("旧快捷键恢复注册失败：%s", old_combo.format())
            return False, f"新组合不可用（{self.last_error}），且原组合恢复失败，请重新设置"
        return False, f"新组合不可用：{self.last_error}，已保留原组合"

    def _install_filter(self) -> None:
        if self._filter is None:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                logger.error("热键注册时 QApplication 尚未创建，无法接收触发消息")
                return
            self._filter = _HotkeyMessageFilter(self._hotkey_id, self._on_hotkey)
            app.installNativeEventFilter(self._filter)

    def _remove_filter(self) -> None:
        if self._filter is not None:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._filter)
            self._filter = None

    def _on_hotkey(self) -> None:
        if self._awaiting_release:
            # 组合仍处于「触发后未观察到释放」状态：此后的 WM_HOTKEY
            # 投递均为按住产生的自动重复，一律忽略（spec: 长按不重复触发）
            return
        self._awaiting_release = True
        self._release_timer.start()
        self.triggered.emit()

    def _check_released(self) -> None:
        """轮询键态：主键与全部修饰键都已松开才重新武装。"""
        if self._combo is None or not self._keys_down():
            self._awaiting_release = False
            self._release_timer.stop()

    def _keys_down(self) -> bool:
        assert self._combo is not None
        codes = [self._combo.native_vk()]
        codes += [_MODIFIER_VK[name] for name in self._combo.modifiers]
        return any(_user32.GetAsyncKeyState(code) & 0x8000 for code in codes)
