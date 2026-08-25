"""系统托盘与关闭语义测试（spec: system-tray / single-instance 激活）。

覆盖任务 2.2/2.3/2.4/2.5/2.6/2.9 与 1.5/1.6：
- 托盘菜单结构与信号、托盘不可用降级；
- 关闭窗口两分支（驻留托盘 / 退出程序）与托盘不可用时强制退出；
- 首次驻留一次性提示；
- bring_to_front 对隐藏/最小化/可见三状态的还原；
- 启动显示决策矩阵（--tray / start_minimized / 托盘不可用）。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocrtool.app.application import should_show_main_window
from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.ui.main_window import MainWindow
from ocrtool.ui.tray import TrayController


class ConfigStub:
    """点路径访问 + 写回计数的配置替身。"""

    def __init__(self, values: dict) -> None:
        self._values = copy.deepcopy(values)
        self.saved = 0

    def get(self, dotted: str, default=None):
        node = self._values
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value) -> None:
        parts = dotted.split(".")
        node = self._values
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def save(self) -> None:
        self.saved += 1


class FakeService:
    model_name = "测试模型"
    model_id = "test-model"

    def __init__(self) -> None:
        self.engine_loaded = False


def make_window(qapp, tmp_path, monkeypatch, *, tray_available=False, values=None):
    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
    from ocrtool.app import paths

    paths.initialize()
    config = ConfigStub(values or {})
    win = MainWindow(
        OcrController(FakeService()),
        config,
        startup_warnings=[],
        tray_available=tray_available,
    )
    win.show()
    qapp.processEvents()
    paths.reset_for_tests()
    return win, config


@pytest.fixture()
def tray_env(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
    from ocrtool.app import paths

    paths.initialize()
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    yield
    paths.reset_for_tests()


class TestTrayController:
    def test_托盘不可用时降级且不创建图标(self, qapp, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
        from ocrtool.app import paths

        paths.initialize()
        monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
        tray = TrayController("OCRTool 1.0")
        assert tray.available is False
        assert tray._tray is None  # 不得创建托盘对象（降级为前台程序）
        assert any("托盘不可用" in r.message for r in caplog.records)
        paths.reset_for_tests()

    def test_菜单结构与信号(self, tray_env):
        tray = TrayController("OCRTool 1.0")
        assert tray.available is True
        texts = [a.text() for a in tray._menu.actions() if a.text()]
        assert "显示主窗口" in texts
        assert "截图识别" in texts
        assert "退出" in texts
        assert "开机启动" in texts
        assert "关闭时驻留托盘" in texts

        shown, captured, quitted = [], [], []
        tray.showRequested.connect(lambda: shown.append(1))
        tray.captureRequested.connect(lambda: captured.append(1))
        tray.quitRequested.connect(lambda: quitted.append(1))
        tray._show_action.trigger()
        tray._capture_action.trigger()
        tray._quit_action.trigger()
        assert shown and captured and quitted
        tray.shutdown()

    def test_单击或双击图标请求显示主窗口(self, tray_env):
        tray = TrayController("OCRTool 1.0")
        shown = []
        tray.showRequested.connect(lambda: shown.append(1))
        tray._tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
        tray._tray.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert len(shown) == 2
        # 非点击类激活（如中键）不触发
        tray._tray.activated.emit(QSystemTrayIcon.ActivationReason.MiddleClick)
        assert len(shown) == 2
        tray.shutdown()

    def test_程序化刷新勾选不回灌用户信号(self, tray_env):
        tray = TrayController("OCRTool 1.0")
        toggles = []
        tray.autoStartToggled.connect(lambda on: toggles.append(on))
        tray.set_auto_start_checked(True)  # 刷新实际生效状态
        assert toggles == []  # 程序化变更不得再触发写回
        assert tray._auto_start_action.isChecked() is True
        tray.shutdown()


class TestCloseBehavior:
    def test_默认关闭即请求退出(self, qapp, tmp_path, monkeypatch):
        win, _ = make_window(qapp, tmp_path, monkeypatch, tray_available=False)
        quits = []
        win.quitRequested.connect(lambda: quits.append(1))
        win.close()
        assert quits == [1]
        assert not win.isVisible()

    def test_驻留开启且托盘可用_关闭为隐藏(self, qapp, tmp_path, monkeypatch):
        win, _ = make_window(
            qapp,
            tmp_path,
            monkeypatch,
            tray_available=True,
            values={"ui": {"close_to_tray": True, "tray_hint_done": True}},
        )
        quits = []
        win.quitRequested.connect(lambda: quits.append(1))
        win.close()
        assert quits == []  # 不退出
        assert not win.isVisible()  # 隐藏，进程继续运行
        assert win._tray_available

    def test_驻留开启但托盘不可用_仍退出(self, qapp, tmp_path, monkeypatch):
        # 不能把程序藏进一个不存在的托盘（spec: system-tray 降级）
        win, _ = make_window(
            qapp,
            tmp_path,
            monkeypatch,
            tray_available=False,
            values={"ui": {"close_to_tray": True, "tray_hint_done": True}},
        )
        quits = []
        win.quitRequested.connect(lambda: quits.append(1))
        win.close()
        assert quits == [1]

    def test_首次驻留提示只出现一次(self, qapp, tmp_path, monkeypatch):
        win, config = make_window(
            qapp,
            tmp_path,
            monkeypatch,
            tray_available=True,
            values={"ui": {"close_to_tray": True, "tray_hint_done": False}},
        )
        # 捕获 patch 必须在窗口构造之后：否则会被构造路径覆盖
        info_calls = []
        monkeypatch.setattr(
            "ocrtool.ui.main_window.QMessageBox.information",
            lambda *a, **k: info_calls.append(1) or QMessageBox.StandardButton.Ok,
        )
        win.close()
        assert info_calls == [1]
        assert config.get("ui.tray_hint_done") is True  # 已持久化
        assert config.saved >= 1

        win.show()  # 再次打开后再关闭：不再提示
        qapp.processEvents()
        win.close()
        assert info_calls == [1]

    def test_关闭驻留开关持久化(self, qapp, tmp_path, monkeypatch, tray_env):
        win, config = make_window(
            qapp, tmp_path, monkeypatch, tray_available=True
        )
        win.set_close_to_tray(True)
        assert config.get("ui.close_to_tray") is True
        assert config.saved >= 1

    def test_识别进行中关闭不阻止退出(self, qapp, tmp_path, monkeypatch):
        # spec: system-tray 识别进行中退出——closeEvent 不得因 busy 拒绝；
        # 后台线程的收尾由 application 的 aboutToQuit 在控制器私有池上
        # 有界等待（waitForDone，review 75-3）
        win, _ = make_window(qapp, tmp_path, monkeypatch, tray_available=False)
        monkeypatch.setattr(
            type(win._controller), "busy", property(lambda self: True)
        )
        quits = []
        win.quitRequested.connect(lambda: quits.append(1))
        win.close()
        assert quits == [1]


class TestBringToFront:
    @pytest.mark.parametrize("pre_state", ["visible", "minimized", "hidden"])
    def test_三种既有状态均恢复可见(self, qapp, tmp_path, monkeypatch, pre_state):
        win, _ = make_window(qapp, tmp_path, monkeypatch, tray_available=True)
        if pre_state == "minimized":
            win.showMinimized()
            qapp.processEvents()
        elif pre_state == "hidden":
            win.hide()
            qapp.processEvents()

        win.bring_to_front()
        qapp.processEvents()
        assert win.isVisible()
        assert not win.isMinimized()


class TestShowDecision:
    def test_手动启动正常显示(self):
        from ocrtool.config.defaults import BUILTIN_DEFAULTS

        assert should_show_main_window([], BUILTIN_DEFAULTS, True) is True

    def test_登录自启参数驻留托盘(self):
        from ocrtool.config.defaults import BUILTIN_DEFAULTS

        assert should_show_main_window(["--tray"], BUILTIN_DEFAULTS, True) is False

    def test_start_minimized配置驻留托盘(self):
        config = ConfigStub({"ui": {"start_minimized": True}})
        assert should_show_main_window([], config, True) is False

    @pytest.mark.parametrize("argv", [[], ["--tray"]])
    def test_托盘不可用时无论何种启动意图都显示主窗口(self, argv):
        # 不得成为用户无法访问的隐形进程（spec: auto-start / system-tray）
        config = ConfigStub({"ui": {"start_minimized": True}})
        assert should_show_main_window(argv, config, False) is True


class FakeHotkey(QObject):
    triggered = Signal()

    def __init__(self, ok: bool = True) -> None:
        super().__init__()
        self.ok = ok
        self.calls = []

    def rebind(self, combo):
        self.calls.append(combo)
        if self.ok:
            return True, f"快捷键已更新为 {combo.format()}"
        return False, "新组合不可用：已被其他程序占用，已保留原组合"


class TestHotkeyWiring:
    def test_重绑成功写入配置(self, qapp, tmp_path, monkeypatch):
        from ocrtool.platform.hotkey import HotkeyCombo

        win, config = make_window(qapp, tmp_path, monkeypatch)
        hotkey = FakeHotkey(ok=True)
        win.attach_hotkey(hotkey)
        ok, _ = win.apply_hotkey_combo(HotkeyCombo.parse("Ctrl+Alt+F9"))
        assert ok
        assert config.get("hotkey.capture") == "Ctrl+Alt+F9"
        assert config.saved >= 1

    def test_重绑失败配置保持不变(self, qapp, tmp_path, monkeypatch):
        # spec: global-hotkey 重新绑定失败——原组合生效、配置 MUST NOT 更新
        from ocrtool.platform.hotkey import HotkeyCombo

        win, config = make_window(
            qapp, tmp_path, monkeypatch, values={"hotkey": {"capture": "Alt+Shift+A"}}
        )
        hotkey = FakeHotkey(ok=False)
        win.attach_hotkey(hotkey)
        ok, message = win.apply_hotkey_combo(HotkeyCombo.parse("Ctrl+Alt+F9"))
        assert not ok and "不可用" in message
        assert config.get("hotkey.capture") == "Alt+Shift+A"

    def test_全局热键触发唤起截图识别(self, qapp, tmp_path, monkeypatch):
        win, _ = make_window(qapp, tmp_path, monkeypatch, tray_available=True)
        win.hide()  # 模拟驻留托盘状态（spec: 主窗口隐藏时触发）
        qapp.processEvents()
        calls = []
        monkeypatch.setattr(MainWindow, "start_region_capture", lambda self: calls.append(1))
        hotkey = FakeHotkey()
        win.attach_hotkey(hotkey)
        win._on_global_hotkey()
        assert calls == [1]
        assert win.isVisible()  # 唤起：窗口恢复可见（结果不静默丢弃）


from ocrtool.platform.hotkey import HotkeyCombo


class FakeHotkey2(QObject):
    """带 register/unregister 生命周期记录的热键替身（review 50-1/50-6 用）。"""

    triggered = Signal()

    def __init__(self, ok: bool = True) -> None:
        super().__init__()
        self.ok = ok
        self.calls: list[tuple] = []
        self._combo = None

    @property
    def combo(self):
        return self._combo

    @property
    def registered(self) -> bool:
        return self._combo is not None

    def register(self, combo) -> bool:
        self.calls.append(("register", combo))
        self._combo = combo
        return True

    def unregister(self) -> None:
        self.calls.append(("unregister",))
        self._combo = None

    def rebind(self, combo):
        self.calls.append(("rebind", combo))
        if self.ok:
            self._combo = combo
            return True, f"快捷键已更新为 {combo.format()}"
        return False, "新组合不可用：已被其他程序占用，已保留原组合"


class TestCaptureEntryUnified:
    """review 75-2/50-3：托盘与热键共用截图入口；busy 拒绝无副作用。"""

    def test_驻留态共用入口先置前再截图(self, qapp, tmp_path, monkeypatch):
        win, _ = make_window(qapp, tmp_path, monkeypatch, tray_available=True)
        win.hide()
        qapp.processEvents()
        calls = []
        monkeypatch.setattr(MainWindow, "start_region_capture", lambda self: calls.append(1))
        win.start_capture_and_show()
        assert calls == [1]
        assert win.isVisible()  # 结果不得静默丢进剪贴板（review 75-2）

    def test_识别中共用入口拒绝且无置前副作用(self, qapp, tmp_path, monkeypatch):
        win, _ = make_window(qapp, tmp_path, monkeypatch, tray_available=True)
        win.hide()
        qapp.processEvents()
        monkeypatch.setattr(type(win._controller), "busy", property(lambda self: True))
        calls = []
        monkeypatch.setattr(MainWindow, "start_region_capture", lambda self: calls.append(1))
        win.start_capture_and_show()
        assert calls == []
        assert not win.isVisible()  # 拒绝时不得先抢焦点置前（review 50-3）

    def test_全局热键与托盘共用同一入口(self, qapp, tmp_path, monkeypatch):
        win, _ = make_window(qapp, tmp_path, monkeypatch, tray_available=True)
        calls = []
        monkeypatch.setattr(MainWindow, "start_capture_and_show", lambda self: calls.append(1))
        win._on_global_hotkey()
        assert calls == [1]


class TestHotkeyDialogLifecycle:
    """review 50-1/50-6：对话框期间挂起热键；exec 后释放不累积。"""

    def _window_with_hotkey(self, qapp, tmp_path, monkeypatch):
        win, _ = make_window(qapp, tmp_path, monkeypatch)
        hotkey = FakeHotkey2()
        hotkey.register(HotkeyCombo.parse("Ctrl+Alt+F9"))
        win.attach_hotkey(hotkey)
        return win, hotkey

    def test_对话框exec后释放不累积(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtCore import QEvent

        from ocrtool.ui.widgets.hotkey_capture_dialog import HotkeyCaptureDialog

        win, _ = self._window_with_hotkey(qapp, tmp_path, monkeypatch)
        monkeypatch.setattr(
            HotkeyCaptureDialog, "exec", lambda self: HotkeyCaptureDialog.DialogCode.Rejected
        )
        for _ in range(20):
            win._open_hotkey_dialog()
        qapp.processEvents()
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert win.findChildren(HotkeyCaptureDialog) == []

    def test_对话框期间挂起热键_取消后恢复(self, qapp, tmp_path, monkeypatch):
        from ocrtool.ui.widgets.hotkey_capture_dialog import HotkeyCaptureDialog

        win, hotkey = self._window_with_hotkey(qapp, tmp_path, monkeypatch)
        seen_during = {}

        def fake_exec(self):
            seen_during["registered"] = hotkey.registered
            return HotkeyCaptureDialog.DialogCode.Rejected

        monkeypatch.setattr(HotkeyCaptureDialog, "exec", fake_exec)
        win._open_hotkey_dialog()
        assert seen_during["registered"] is False  # 模态期间热键已挂起（50-1）
        assert hotkey.registered is True  # 取消后恢复原组合
        kinds = [c[0] for c in hotkey.calls]
        assert kinds == ["register", "unregister", "register"]
