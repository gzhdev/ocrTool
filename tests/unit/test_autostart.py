"""开机自启动（spec: auto-start）单元测试。

对真实 HKCU Run 键操作，但使用独立值名（OCRTool-Test-*），不触碰程序
自身的登录启动项；夹具保证清理。写失败回退用 monkeypatch 注入。
"""

from __future__ import annotations

import uuid
import winreg

import pytest

from ocrtool.platform import autostart
from ocrtool.platform.autostart import AutoStartError


@pytest.fixture()
def value_name():
    name = f"OCRTool-Test-{uuid.uuid4().hex[:8]}"
    yield name
    try:
        autostart.disable(name)
    except AutoStartError:
        pass


def read_raw(name: str) -> str | None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY) as key:
        try:
            value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        return str(value)


class TestEnableDisable:
    def test_开启写入当前用户Run键且指向本程序带tray参数(self, value_name):
        autostart.enable(value_name)
        command = read_raw(value_name)
        assert command is not None
        assert command.endswith(autostart.TRAY_ARG)
        assert command.startswith('"')  # 路径引号包裹（含空格安全）
        assert autostart.is_enabled(value_name) is True

    def test_关闭移除登录启动项(self, value_name):
        autostart.enable(value_name)
        autostart.disable(value_name)
        assert read_raw(value_name) is None
        assert autostart.is_enabled(value_name) is False

    def test_关闭未设置值时幂等(self, value_name):
        autostart.disable(value_name)  # 未设置：不抛错
        assert read_raw(value_name) is None

    def test_写失败抛可读异常(self, value_name, monkeypatch):
        def boom(*a, **k):
            raise OSError("denied")

        monkeypatch.setattr(winreg, "SetValueEx", boom)
        with pytest.raises(AutoStartError, match="写入登录启动项失败"):
            autostart.enable(value_name)

    def test_移除失败抛可读异常(self, value_name, monkeypatch):
        def boom(*a, **k):
            raise OSError("denied")

        monkeypatch.setattr(winreg, "DeleteValue", boom)
        with pytest.raises(AutoStartError, match="移除登录启动项失败"):
            autostart.disable(value_name)


class TestHeal:
    def test_关闭状态不写入(self, value_name):
        assert autostart.heal(value_name) is False
        assert read_raw(value_name) is None  # MUST NOT 写入

    def test_路径未变化不重复写入(self, value_name):
        autostart.enable(value_name)
        before = read_raw(value_name)
        assert autostart.heal(value_name) is False
        assert read_raw(value_name) == before  # 未被重写

    def test_旧路径指向别处时自愈重写(self, value_name):
        # 模拟「程序目录被移动」：遗留值指向旧位置
        stale = '"C:\\Moved Away\\OCRTool\\OCRTool.exe" --tray'
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, stale)
        assert autostart.heal(value_name) is True
        assert read_raw(value_name) == autostart.launch_command()


def test_路径仅大小写或斜杠风格差异不触发重写(value_name):
    """同一位置的等价写法（大小写 / 正反斜杠）不得判为路径变化。"""
    autostart.enable(value_name)
    command = autostart.launch_command()
    variant = command.replace("\\", "/")
    assert autostart._command_paths(variant) == autostart._command_paths(command)
    assert autostart._command_paths(command.upper()) == autostart._command_paths(command)


def test_含空格路径的命令解析往返():
    command = '"C:\\Tools With Space\\OCRTool\\OCRTool.exe" --tray'
    paths = autostart._command_paths(command)
    assert paths == ["c:\\tools with space\\ocrtool\\ocrtool.exe"]


class TestApplyAutoStartFallback:
    def test_切换失败时开关回退到实际生效状态(self, monkeypatch):
        from ocrtool.app.application import _apply_auto_start

        class TrayStub:
            def __init__(self):
                self.checked = None

            def set_auto_start_checked(self, enabled):
                self.checked = enabled

        class WindowStub:
            def __init__(self):
                self.notified = []

            def notify(self, message):
                self.notified.append(message)

        class ConfigStub:
            def __init__(self):
                self.values = {}
                self.saved = 0

            def set(self, key, value):
                self.values[key] = value

            def save(self):
                self.saved += 1

        def boom(*a, **k):
            raise OSError("denied")

        monkeypatch.setattr(winreg, "SetValueEx", boom)
        tray, window, config = TrayStub(), WindowStub(), ConfigStub()
        _apply_auto_start(True, config, window, tray)
        assert tray.checked is False  # 回退到实际状态（未生效）
        assert config.values["system.auto_start"] is False
        assert window.notified  # 失败对用户可见
        assert config.saved >= 1
