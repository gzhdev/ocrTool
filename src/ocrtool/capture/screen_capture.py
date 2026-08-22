"""屏幕捕获与逐屏坐标换算（spec: screen-capture）。

核心约束：每块屏幕用**自身**的 devicePixelRatio 把逻辑坐标映射为物理
像素。整虚拟桌面单次捕获只携带一个比例，混合 DPI（如 150% + 100%）下
必然错位，因此逐屏捕获、逐屏换算（design D2）。

日志只记几何与耗时，不记图像内容（spec: app-logging 隐私约定）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QImage, QPixmap, QScreen

logger = logging.getLogger("ocrtool.capture")


class ScreenCaptureError(RuntimeError):
    """屏幕捕获失败，message 面向用户，detail 仅入日志。"""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class ScreenSnapshot:
    """单块屏幕的冻结帧：物理像素画面 + 该屏逻辑几何 + 该屏自身缩放比例。"""

    screen_name: str
    geometry: QRect  # 该屏在全局逻辑坐标系中的几何
    device_pixel_ratio: float
    pixmap: QPixmap  # 该屏的物理像素捕获结果

    @property
    def physical_size(self) -> tuple[int, int]:
        return self.pixmap.width(), self.pixmap.height()


def enumerate_screens() -> list[QScreen]:
    """枚举所有屏幕（顺序与 QGuiApplication.screens() 一致）。"""
    from PySide6.QtGui import QGuiApplication

    return list(QGuiApplication.screens())


def log_screen_layout(screens: list[QScreen]) -> None:
    """把每块屏幕的逻辑几何与缩放比例记入日志（不含任何画面内容）。"""
    for index, screen in enumerate(screens):
        logger.info(
            "屏幕[%d] name=%s 逻辑几何=%s 缩放=%.2f",
            index,
            screen.name(),
            screen.geometry().getRect(),
            screen.devicePixelRatio(),
        )


def capture_screen(screen: QScreen) -> ScreenSnapshot:
    """捕获单块屏幕，得到该屏的物理像素图像。

    远程桌面 / 虚拟显示器等环境下 grabWindow 可能返回空图像，此时给出
    可读错误而非崩溃（design 风险表）。
    """
    geometry = screen.geometry()
    dpr = screen.devicePixelRatio()
    started = time.monotonic()
    pixmap = screen.grabWindow(0)
    elapsed_ms = (time.monotonic() - started) * 1000
    if pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
        raise ScreenCaptureError(
            "屏幕捕获失败，无法进行截图识别",
            detail=f"screen={screen.name()} 返回空图像",
        )
    logger.info(
        "已捕获屏幕 name=%s 物理像素=%dx%d 缩放=%.2f 耗时=%.0fms",
        screen.name(),
        pixmap.width(),
        pixmap.height(),
        dpr,
        elapsed_ms,
    )
    return ScreenSnapshot(
        screen_name=screen.name(),
        geometry=geometry,
        device_pixel_ratio=dpr,
        pixmap=pixmap,
    )


def capture_all_screens() -> list[ScreenSnapshot]:
    """枚举并逐屏捕获所有屏幕；先记录布局，再逐屏捕获。"""
    screens = enumerate_screens()
    log_screen_layout(screens)
    snapshots: list[ScreenSnapshot] = []
    for screen in screens:
        snapshots.append(capture_screen(screen))
    return snapshots


def snapshot_at(snapshots: list[ScreenSnapshot], point_logical_x: int, point_logical_y: int) -> ScreenSnapshot | None:
    """返回逻辑坐标点所在的屏幕快照；不在任何屏幕内返回 None。"""
    for snapshot in snapshots:
        if snapshot.geometry.contains(point_logical_x, point_logical_y):
            return snapshot
    return None


def logical_to_physical(rect: QRect, snapshot: ScreenSnapshot) -> QRect:
    """逻辑选区 → 该屏物理像素矩形（design D2 坐标换算）。

    全局逻辑坐标先平移到屏内局部坐标，再乘以**该屏自身**缩放比例，
    最后夹取到捕获图范围内（选区只在屏内，正常不会越界，夹取是保险）。
    """
    local = QRectF(rect.translated(-snapshot.geometry.topLeft()))
    dpr = snapshot.device_pixel_ratio
    scaled = QRectF(
        local.x() * dpr,
        local.y() * dpr,
        local.width() * dpr,
        local.height() * dpr,
    )
    physical = scaled.toAlignedRect()
    full = QRect(0, 0, snapshot.pixmap.width(), snapshot.pixmap.height())
    return physical.intersected(full)


def physical_size_of(rect: QRect, snapshot: ScreenSnapshot) -> tuple[int, int]:
    """逻辑选区对应的物理像素尺寸（用于「面积过小视为取消」判定）。"""
    physical = logical_to_physical(rect, snapshot)
    return physical.width(), physical.height()


def crop_snapshot(snapshot: ScreenSnapshot, logical_rect: QRect) -> QImage:
    """从冻结帧裁剪出逻辑选区对应的物理像素图像（纯内存操作）。"""
    physical = logical_to_physical(logical_rect, snapshot)
    if physical.width() <= 0 or physical.height() <= 0:
        raise ScreenCaptureError(
            "选区无效，请重新框选", detail=f"physical={physical.getRect()}"
        )
    return snapshot.pixmap.copy(physical).toImage()
