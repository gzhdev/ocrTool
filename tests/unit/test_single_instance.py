"""单实例保证（spec: single-instance）的单元测试。

真实 QLocalServer/QLocalSocket 在同进程内即可模拟「两个实例」的完整
握手：guard A 监听、guard B 同名探测连接成功即判定 ALREADY_RUNNING，
消息经命名管道真实送达 A。降级路径用 monkeypatch 注入故障。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/qt_helpers
from qt_helpers import process_events_until  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from ocrtool.platform.single_instance import (
    SingleInstanceGuard,
    SingleInstanceOutcome,
    endpoint_name,
)



@pytest.fixture()
def unique_name(tmp_path):
    """每用例独立端点名，避免并行/残留干扰。"""
    return endpoint_name(app_root=tmp_path / "app-a", user="tester")


class TestEndpointName:
    def test_用户与目录共同派生_任一不同则端点不同(self):
        base = endpoint_name(app_root=Path("C:/Tools/OCRTool"), user="alice")
        other_user = endpoint_name(app_root=Path("C:/Tools/OCRTool"), user="bob")
        other_dir = endpoint_name(app_root=Path("D:/Copy/OCRTool"), user="alice")
        same = endpoint_name(app_root=Path("C:/Tools/OCRTool"), user="alice")
        assert base != other_user
        assert base != other_dir
        assert base == same

    def test_目录仅大小写不同落到同一端点(self):
        # Windows 命名管道不区分大小写，路径写入哈希前必须归一
        lower = endpoint_name(app_root=Path("C:/tools/ocrtool"), user="alice")
        upper = endpoint_name(app_root=Path("C:/TOOLS/OCRTOOL"), user="alice")
        assert lower == upper

    def test_名称为哈希形式不含路径原文(self):
        name = endpoint_name(app_root=Path("C:/Users/me/私密目录"), user="me")
        assert name.startswith("ocrtool-")
        assert "私密" not in name and "\\" not in name


class TestGuardLifecycle:
    def test_首次启动监听成功(self, qapp, unique_name):
        guard = SingleInstanceGuard(name=unique_name)
        assert guard.check_and_listen() is SingleInstanceOutcome.FIRST_INSTANCE
        assert guard.listening
        guard.shutdown()

    def test_二次启动判定已有实例并送达激活请求(self, qapp, unique_name):
        first = SingleInstanceGuard(name=unique_name)
        assert first.check_and_listen() is SingleInstanceOutcome.FIRST_INSTANCE
        activations = []
        first.activationRequested.connect(lambda: activations.append(1))

        second = SingleInstanceGuard(name=unique_name)
        assert second.check_and_listen() is SingleInstanceOutcome.ALREADY_RUNNING
        assert not second.listening  # 第二实例不建立监听

        process_events_until(qapp, lambda: bool(activations))
        assert activations == [1]
        first.shutdown()

    def test_自启拉起时不激活已有实例(self, qapp, unique_name):
        # spec: auto-start 自启时已有实例在运行——按重复启动处理但
        # MUST NOT 因自启而显示已有实例的主窗口
        first = SingleInstanceGuard(name=unique_name)
        assert first.check_and_listen() is SingleInstanceOutcome.FIRST_INSTANCE
        activations = []
        first.activationRequested.connect(lambda: activations.append(1))

        autostart_probe = SingleInstanceGuard(name=unique_name)
        assert (
            autostart_probe.check_and_listen(activate_existing=False)
            is SingleInstanceOutcome.ALREADY_RUNNING
        )
        qapp.processEvents()
        assert activations == []  # 未发送激活请求
        first.shutdown()

    def test_互斥量被持有时静默退出不产生第二实例(self, qapp, unique_name):
        # 毫秒级并发启动竞态的回归（真实 exe 实测发现）：先到者已持有
        # 互斥量仲裁但端点尚未监听时，后来者连接探测落空，必须由互斥量
        # 仲裁拦下——否则双方都能监听同名命名管道（多实例），单实例失效
        from ocrtool.platform.single_instance import _kernel32

        holder = _kernel32.CreateMutexW(None, False, f"Local\\{unique_name}")
        assert holder
        try:
            guard = SingleInstanceGuard(name=unique_name)
            assert (
                guard.check_and_listen()
                is SingleInstanceOutcome.ALREADY_RUNNING
            )
            assert not guard.listening
        finally:
            _kernel32.ReleaseMutex(holder)
            _kernel32.CloseHandle(holder)
        # 持有者释放后可正常成为首实例
        guard2 = SingleInstanceGuard(name=unique_name)
        assert guard2.check_and_listen() is SingleInstanceOutcome.FIRST_INSTANCE
        guard2.shutdown()

    def test_退出释放端点后名字可被重新监听(self, qapp, unique_name):
        first = SingleInstanceGuard(name=unique_name)
        first.check_and_listen()
        first.shutdown()
        # 释放后新实例应能以同名建立监听（spec: 退出时端点被释放）
        second = SingleInstanceGuard(name=unique_name)
        assert second.check_and_listen() is SingleInstanceOutcome.FIRST_INSTANCE
        second.shutdown()

    def test_监听失败时降级继续(self, qapp, unique_name, monkeypatch, caplog):
        monkeypatch.setattr(QLocalServer, "listen", lambda *a, **k: False)
        guard = SingleInstanceGuard(name=unique_name)
        with caplog.at_level(logging.ERROR, logger="ocrtool.platform"):
            outcome = guard.check_and_listen()
        assert outcome is SingleInstanceOutcome.DEGRADED
        assert not guard.listening
        assert any("放弃单实例保证" in r.message for r in caplog.records)

    def test_检测机制异常时不阻塞启动(self, qapp, unique_name, monkeypatch, caplog):
        def boom(self):
            raise RuntimeError("机制不可用")

        monkeypatch.setattr(QLocalSocket, "connectToServer", boom)
        guard = SingleInstanceGuard(name=unique_name)
        with caplog.at_level(logging.ERROR, logger="ocrtool.platform"):
            outcome = guard.check_and_listen()
        assert outcome is SingleInstanceOutcome.DEGRADED
        assert any("未预期异常" in r.message for r in caplog.records)

    def test_检测超时按无实例继续并记录日志(self, qapp, unique_name, monkeypatch, caplog):
        # 超时 = 连接既未成功也未明确拒绝（保持 ConnectingState）
        monkeypatch.setattr(
            QLocalSocket, "waitForConnected", lambda self, ms: False
        )
        monkeypatch.setattr(
            QLocalSocket,
            "state",
            lambda self: QLocalSocket.LocalSocketState.ConnectingState,
        )
        guard = SingleInstanceGuard(name=unique_name)
        with caplog.at_level(logging.WARNING, logger="ocrtool.platform"):
            outcome = guard.check_and_listen()
        assert outcome is SingleInstanceOutcome.FIRST_INSTANCE
        assert any("未在" in r.message and "继续启动" in r.message for r in caplog.records)
        guard.shutdown()
