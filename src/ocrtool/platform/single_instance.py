"""单实例保证（spec: single-instance）。

以本地套接字端点承担检测与通信（design D2）：命名管道/本地套接字既能
回答「是否已有实例」，又能把「用户又双击了一次」传达给已有实例——
互斥量只提供前者。

- 端点名称由当前用户与程序所在目录共同派生（design D4）：多用户互不
  干扰，不同目录的便携副本可同时运行；
- 建立监听前先尝试连接同名端点，连接成功即已有实例（design D3 的
  「先连接」半步）；连接不上时先显式移除同名遗留端点再监听（「再清理」
  半步）——上一次强杀残留的端点不得让程序此后永远启动不了；
- 检测全程有超时与异常兜底：任何失败都不阻塞启动，代价是放弃单实例
  保证并记录日志（spec: single-instance 检测不得阻塞启动）。

Qt 映射：QLocalServer 在 Windows 上即命名管道，在其他平台为本地套接字
文件（removeServer 清理其文件系统残留；Windows 命名管道随进程终止由系统
回收，removeServer 为无害空操作，调用以保持跨平台语义统一）。
"""

from __future__ import annotations

import ctypes
import getpass
import hashlib
import logging
import os
from ctypes import wintypes
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QEventLoop, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger("ocrtool.platform")

_CONNECT_TIMEOUT_MS = 1500
_ACTIVATE_SETTLE_MS = 250

_ERROR_ALREADY_EXISTS = 183
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = (
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.LPCWSTR,
)
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
_kernel32.ReleaseMutex.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
_kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstanceOutcome(Enum):
    """check_and_listen 的三种结论。"""

    FIRST_INSTANCE = "first_instance"
    ALREADY_RUNNING = "already_running"
    DEGRADED = "degraded"


def endpoint_name(app_root: Path | None = None, user: str | None = None) -> str:
    """端点名称 = 用户 + 程序目录 的哈希派生（design D4）。

    路径参与哈希前统一小写：Windows 命名管道名不区分大小写，仅大小号
    不同的目录写法（`C:/A` 与 `c:/a`）必须落到同一端点。
    """
    if app_root is None:
        from ocrtool.app import paths

        app_root = paths.get_app_root()
    if user is None:
        try:
            user = getpass.getuser()
        except Exception:  # noqa: BLE001 —— getuser 在异常环境下的兜底
            user = f"uid-{os.getuid() if hasattr(os, 'getuid') else 'unknown'}"
    digest_source = f"{user}|{str(app_root).casefold()}"
    return "ocrtool-" + hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]


class SingleInstanceGuard(QObject):
    """持有实例端点：检测、监听与接收二次启动的激活请求。

    生命周期：启动早期调用 :meth:`check_and_listen`；程序退出时调用
    :meth:`shutdown` 释放端点（spec: single-instance 退出时端点被释放）。
    """

    activationRequested = Signal()

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = name or endpoint_name()
        self._server: QLocalServer | None = None
        self._pending: list[QLocalSocket] = []  # 持有已接受连接防回收
        self._mutex: int | None = None  # 命名互斥量句柄（原子仲裁）

    @property
    def name(self) -> str:
        return self._name

    @property
    def listening(self) -> bool:
        return self._server is not None and self._server.isListening()

    def check_and_listen(
        self, *, activate_existing: bool = True
    ) -> SingleInstanceOutcome:
        """启动序列：连接探测 → 陈旧清理 → 监听；任何异常降级不阻塞。

        activate_existing=False 用于登录自启拉起的实例：发现已有实例时
        直接退出，MUST NOT 请求其显示主窗口（spec: auto-start 自启时
        已有实例在运行）。
        """
        self._activate_existing = activate_existing
        try:
            return self._check_and_listen()
        except Exception:
            # 检测机制不可用：功能以放弃单实例为代价继续可用（spec）
            logger.exception("单实例检测发生未预期异常，放弃单实例保证继续启动")
            return SingleInstanceOutcome.DEGRADED

    def _check_and_listen(self) -> SingleInstanceOutcome:
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            if not getattr(self, "_activate_existing", True):
                probe.disconnectFromServer()
                logger.info(
                    "自启拉起时检测到已有实例（端点=%s），不激活其窗口，本次退出",
                    self._name,
                )
                return SingleInstanceOutcome.ALREADY_RUNNING
            # 已有实例存活：传达「激活窗口」意图后由调用方退出本次启动。
            # Windows 命名管道的写由后台线程异步完成且只随事件循环运转
            # 而推进（waitForBytesWritten 实测无效）；probe 是局部对象，
            # 不等数据送达就返回会让管道在数据抵达前被析构，激活消息丢失。
            # 用一段短事件循环驱动写完成（spec: single-instance 检测有限时间）。
            probe.write(b"activate\n")
            loop = QEventLoop()
            QTimer.singleShot(_ACTIVATE_SETTLE_MS, loop.quit)
            loop.exec()
            probe.disconnectFromServer()
            logger.info("检测到已有实例（端点=%s），已请求其显示主窗口", self._name)
            return SingleInstanceOutcome.ALREADY_RUNNING
        if probe.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            # 连接既未成功也未明确拒绝（如超时）：按无实例继续并记录（spec）
            logger.warning(
                "单实例检测未在 %dms 内得到结论（端点=%s），按无已有实例继续启动",
                _CONNECT_TIMEOUT_MS,
                self._name,
            )
        # 命名互斥量原子仲裁：毫秒级并发启动时，双方连接探测都落空、
        # 双方监听同名命名管道都可能成功（Windows 管道允许多实例）——
        # 端点套接字无法关闭这个竞态窗口，互斥量可以（先到先得，且
        # 进程终止时由系统回收，不存在陈旧残留问题）。
        mutex = _kernel32.CreateMutexW(None, False, f"Local\\{self._name}")
        if not mutex:
            logger.error("实例互斥量创建失败，放弃单实例保证继续启动")
            return SingleInstanceOutcome.DEGRADED
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            # 先到者已持有仲裁：即使其端点尚未开始监听（初始化早期），
            # 也按已有实例处理——本实例静默退出，杜绝双实例
            _kernel32.CloseHandle(mutex)
            logger.info(
                "互斥量仲裁判定已有实例（端点=%s，其端点尚未监听），本次退出",
                self._name,
            )
            return SingleInstanceOutcome.ALREADY_RUNNING
        self._mutex = mutex
        # 连不上：要么从未有实例，要么端点是强杀残留——先显式移除再监听
        QLocalServer.removeServer(self._name)
        server = QLocalServer()
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._name):
            logger.error(
                "实例端点监听失败（端点=%s，原因=%s），放弃单实例保证继续启动",
                self._name,
                server.errorString(),
            )
            # 持仲裁却不监听 = 拦截所有后来者又无法被其激活（此后双击
            # 永久无反应）——释放互斥量，与「以放弃单实例为代价继续
            # 可用」语义对齐（review 50-5）
            self._release_mutex()
            return SingleInstanceOutcome.DEGRADED
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        logger.info("已建立实例端点（端点=%s）", self._name)
        return SingleInstanceOutcome.FIRST_INSTANCE

    def _on_new_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                return
            self._pending.append(socket)
            # 数据可能在接线前已到达（readyRead 不回放），先接线再补查一次
            socket.readyRead.connect(lambda sock=socket: self._on_ready_read(sock))
            socket.disconnected.connect(lambda sock=socket: self._release(sock))
            if socket.bytesAvailable() > 0:
                self._on_ready_read(socket)

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        data = bytes(socket.readAll())
        if b"activate" in data:
            logger.info("收到二次启动的激活请求")
            self.activationRequested.emit()
        socket.disconnectFromServer()

    def _release(self, socket: QLocalSocket) -> None:
        if socket in self._pending:
            self._pending.remove(socket)
        socket.deleteLater()

    def shutdown(self) -> None:
        """退出时释放端点（spec: system-tray 退出时释放系统资源）。"""
        if self._server is not None:
            for socket in list(self._pending):
                socket.disconnectFromServer()
            self._pending.clear()
            self._server.close()
            self._server = None
            logger.info("实例端点已释放（端点=%s）", self._name)
        self._release_mutex()

    def _release_mutex(self) -> None:
        if self._mutex is not None:
            _kernel32.ReleaseMutex(self._mutex)
            _kernel32.CloseHandle(self._mutex)
            self._mutex = None
