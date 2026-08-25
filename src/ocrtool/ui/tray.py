"""系统托盘控制器（spec: system-tray）。

托盘图标与菜单（显示主窗口 / 截图识别 / 开机启动 / 关闭时驻留 / 退出）。
托盘不可用时（`available=False`）不创建任何托盘对象——调用方据此降级为
前台程序（关闭窗口即退出），MUST NOT 启动失败（spec: system-tray 降级）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

logger = logging.getLogger("ocrtool.ui")

_ICON_SIZES = (16, 24, 32, 48, 256)


def load_tray_icon() -> QIcon:
    """加载多尺寸托盘图标（resources/icons，任务 2.1）。

    QIcon 按实际显示尺寸自动选最接近的位图，高 DPI 缩放下不模糊。
    资源缺失时返回空图标——托盘仍可用（显示为空位），不因此失败。
    """
    from ocrtool.app import paths

    icon = QIcon()
    for size in _ICON_SIZES:
        path = paths.resource_dir() / "icons" / f"tray-{size}.png"
        if path.exists():
            icon.addFile(str(path), QSize(size, size))
    if icon.isNull():
        logger.error("托盘图标资源缺失：%s", paths.resource_dir() / "icons")
    return icon


class TrayController(QObject):
    """托盘入口的生命周期与信号接线。"""

    showRequested = Signal()
    captureRequested = Signal()
    quitRequested = Signal()
    autoStartToggled = Signal(bool)
    closeToTrayToggled = Signal(bool)

    def __init__(
        self,
        title: str,
        auto_start_enabled: bool = False,
        close_to_tray: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.available = bool(QSystemTrayIcon.isSystemTrayAvailable())
        self._tray: QSystemTrayIcon | None = None
        if not self.available:
            logger.warning("系统托盘不可用，降级为前台程序（关闭窗口即退出）")
            return

        self._menu = QMenu()
        self._show_action = self._menu.addAction("显示主窗口")
        self._show_action.triggered.connect(self.showRequested.emit)
        self._capture_action = self._menu.addAction("截图识别")
        self._capture_action.triggered.connect(self.captureRequested.emit)
        self._menu.addSeparator()

        self._auto_start_action = self._menu.addAction("开机启动")
        self._auto_start_action.setCheckable(True)
        self._auto_start_action.setChecked(auto_start_enabled)
        self._auto_start_action.toggled.connect(self.autoStartToggled.emit)

        self._close_to_tray_action = self._menu.addAction("关闭时驻留托盘")
        self._close_to_tray_action.setCheckable(True)
        self._close_to_tray_action.setChecked(close_to_tray)
        self._close_to_tray_action.toggled.connect(self.closeToTrayToggled.emit)

        self._menu.addSeparator()
        self._quit_action = self._menu.addAction("退出")
        self._quit_action.triggered.connect(self.quitRequested.emit)

        self._tray = QSystemTrayIcon(load_tray_icon(), self)
        self._tray.setToolTip(title)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def _on_activated(self, reason) -> None:
        # 单击 / 双击图标 = 显示主窗口（spec: system-tray 通过托盘显示）
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.showRequested.emit()

    def set_auto_start_checked(self, enabled: bool) -> None:
        """以实际生效状态刷新勾选；程序化变更不得回灌用户信号。"""
        if self._auto_start_action.isChecked() != enabled:
            self._auto_start_action.blockSignals(True)
            self._auto_start_action.setChecked(enabled)
            self._auto_start_action.blockSignals(False)

    def set_close_to_tray_checked(self, enabled: bool) -> None:
        if self._close_to_tray_action.isChecked() != enabled:
            self._close_to_tray_action.blockSignals(True)
            self._close_to_tray_action.setChecked(enabled)
            self._close_to_tray_action.blockSignals(False)

    def shutdown(self) -> None:
        """退出时移除托盘图标（spec: system-tray 退出时释放系统资源）。"""
        if self._tray is not None:
            self._tray.hide()
            self._tray = None
