"""冻结帧选区界面与截图流程（spec: screen-capture）。

RegionOverlay：单块屏幕的全屏置顶覆盖层，显示该屏冻结帧，承担
按下-拖动-释放框选、边界截止、ESC/右键取消。

RegionCaptureFlow：整个流程的协调器——隐藏主窗口并等待生效 → 逐屏
捕获 → 创建覆盖层 → 等待用户选区。所有结束路径（完成、取消、异常）
汇聚到 _cleanup 单一收尾出口（design D6），销毁全部覆盖层并恢复主窗口。
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from ocrtool.capture.screen_capture import (
    ScreenCaptureError,
    ScreenSnapshot,
    capture_all_screens,
    crop_snapshot,
    physical_size_of,
    snapshot_at,
)

logger = logging.getLogger("ocrtool.capture")

# 面积过小阈值（物理像素）：任一边小于该值视为取消（误触单击兜底）。
MIN_SELECTION_PX = 8

# 隐藏主窗口后等待合成生效的下限延时：窗口隐藏对画面生效由合成器异步
# 完成，事件循环仅能确认 Qt 侧状态；下限延时覆盖合成器延迟（design D4）。
MIN_HIDE_DELAY_MS = 200


class RegionOverlay(QWidget):
    """单屏选区覆盖层：冻结帧背景 + 框选交互。"""

    selectionDone = Signal(QRect)  # 全局逻辑坐标选区（屏内局部坐标 + 该屏原点）
    cancelled = Signal()

    def __init__(self, snapshot: ScreenSnapshot, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self._frozen = snapshot.pixmap
        # 标注物理像素密度，绘制时按逻辑尺寸原样铺满且保持原生清晰度
        self._frozen.setDevicePixelRatio(snapshot.device_pixel_ratio)
        self._origin: QRect | None = None  # 按下点（局部逻辑坐标）
        self._selection: QRect | None = None  # 当前选区（局部逻辑坐标）

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(snapshot.geometry)
        self.setMouseTracking(True)

    # ---- 绘制 ----

    def paintEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._frozen)
        dim = QColor(0, 0, 0, 110)
        selection = self._selection
        if selection is None:
            painter.fillRect(self.rect(), dim)
            return
        # 选区外弱化（spec: screen-capture「选区反馈」）
        width, height = self.width(), self.height()
        for part in (
            QRect(0, 0, width, selection.top()),
            QRect(0, selection.bottom() + 1, width, height - selection.bottom() - 1),
            QRect(0, selection.top(), selection.left(), selection.height()),
            QRect(
                selection.right() + 1,
                selection.top(),
                width - selection.right() - 1,
                selection.height(),
            ),
        ):
            if part.width() > 0 and part.height() > 0:
                painter.fillRect(part, dim)
        painter.setPen(QPen(QColor(80, 180, 255), 2))
        painter.drawRect(selection)
        self._paint_size_hint(painter, selection)

    def _paint_size_hint(self, painter: QPainter, selection: QRect) -> None:
        # selection 是屏内局部坐标；换算接口的契约是全局逻辑坐标（review 100-1）
        global_selection = selection.translated(self._snapshot.geometry.topLeft())
        physical_width, physical_height = physical_size_of(
            global_selection, self._snapshot
        )
        painter.setFont(QFont(self.font().family(), 10))
        painter.setPen(QColor(255, 255, 255))
        label = f"{physical_width}×{physical_height}"
        margin = 6
        label_y = selection.top() - 24
        if label_y < 0:
            label_y = selection.bottom() + margin
        painter.drawText(selection.left(), label_y, label)

    # ---- 交互 ----

    def _clamped(self, point: QPoint) -> QPoint:
        """把指针位置夹取在本屏内（design D2：选区不延伸到相邻屏幕）。"""
        return QPoint(
            max(0, min(point.x(), self.width() - 1)),
            max(0, min(point.y(), self.height() - 1)),
        )

    @staticmethod
    def _selection_between(anchor: QPoint, current: QPoint) -> QRect:
        """含端点的选区矩形：显式 min/max 构造，规避 QRect(QPoint, QPoint)
        在反向拖动下的取整语义不确定性。"""
        return QRect(
            min(anchor.x(), current.x()),
            min(anchor.y(), current.y()),
            abs(anchor.x() - current.x()) + 1,
            abs(anchor.y() - current.y()) + 1,
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._origin = self._clamped(event.position().toPoint())
        self._selection = self._selection_between(self._origin, self._origin)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is None:
            return
        self._selection = self._selection_between(
            self._origin, self._clamped(event.position().toPoint())
        )
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        # 释放点是选区权威终点（不用最后一次 move 的位置兜底）
        selection = self._selection_between(
            self._origin, self._clamped(event.position().toPoint())
        )
        self._origin = None
        # 坐标契约对齐（review 100-1）：下游 logical_to_physical 接收全局逻辑
        # 坐标并自行减屏原点，此处必须先加上屏原点，否则非原点屏被双重平移
        global_selection = selection.translated(self._snapshot.geometry.topLeft())
        physical_width, physical_height = physical_size_of(
            global_selection, self._snapshot
        )
        if physical_width < MIN_SELECTION_PX or physical_height < MIN_SELECTION_PX:
            # 面积过小按取消处理：不报错、不识别（spec: screen-capture）
            self.cancelled.emit()
            return
        self.selectionDone.emit(global_selection)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        # 外部关闭（Alt+F4 / WM_CLOSE）也必须走取消路径（review 75-1）：
        # 覆盖层是 Qt::Tool，被关闭不会退出应用，若不收尾则流程僵尸化。
        # flow 的 _ended 守卫保证 _cleanup 主动 close 时不递归。
        self.cancelled.emit()
        super().closeEvent(event)


class RegionCaptureFlow(QObject):
    """截图流程协调器：隐藏 → 捕获 → 覆盖层 → 选区 → 裁剪结果。

    信号在主线程发射；finished 携带裁剪出的 QImage（物理像素），
    cancelled / failed 均为正常路径，不按错误处理。
    """

    finished = Signal(object)  # QImage
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._overlays: list[RegionOverlay] = []
        self._snapshots: list[ScreenSnapshot] = []
        self._window: QWidget | None = None
        self._window_was_visible = False
        self._started = False
        self._ended = False

    @property
    def active(self) -> bool:
        return self._started and not self._ended

    # ---- 启动 ----

    def start(self, window: QWidget | None) -> None:
        """进入截图流程。异常（含捕获失败）统一走 _abort。"""
        if self._started:
            return  # 重入保护（任务 3.7：取消后立即再发起由新流程实例承担）
        self._started = True
        self._window = window
        try:
            self._hide_and_wait(window)
            snapshots = capture_all_screens()
            self._show_overlays(snapshots)
        except Exception as exc:  # noqa: BLE001 —— 单一收尾出口兜底一切异常
            self._abort(exc, "截图流程启动失败")

    def _hide_and_wait(self, window: QWidget | None) -> None:
        """隐藏主窗口并等待实际生效。

        以「Qt 侧已不再暴露 + 下限延时」双条件为准（design D4）：
        事件循环确认窗口状态，下限延时覆盖系统合成器的异步生效。
        可见性必须在 hide 副作用之前落账（review 50-4）——等待期若抛异常，
        _cleanup 仍能按发起前状态恢复主窗口。
        """
        self._window_was_visible = window is not None and window.isVisible()
        if window is None or not self._window_was_visible:
            return
        window.hide()
        app = QApplication.instance()
        deadline = time.monotonic() + MIN_HIDE_DELAY_MS / 1000
        hard_deadline = deadline + 5.0  # 硬上限：状态不可得时也不死等
        while time.monotonic() < hard_deadline:
            app.processEvents()
            handle = window.windowHandle()
            exposed = handle is not None and handle.isExposed()
            if not exposed and time.monotonic() >= deadline:
                break
            time.sleep(0.01)

    def _show_overlays(self, snapshots: list[ScreenSnapshot]) -> None:
        from PySide6.QtGui import QCursor

        self._snapshots = snapshots
        for snapshot in snapshots:
            overlay = RegionOverlay(snapshot)
            overlay.selectionDone.connect(self._on_selection_done)
            overlay.cancelled.connect(self._on_cancelled)
            # 先入列表再显示（review 50-2）：show 异常时 _cleanup 才能销毁它
            self._overlays.append(overlay)
            overlay.show()
        # 键盘焦点落在光标所在屏的覆盖层，保证 ESC 生效
        target = next(
            (o for o in self._overlays if o.geometry().contains(QCursor.pos())),
            self._overlays[0] if self._overlays else None,
        )
        if target is not None:
            target.activateWindow()
            target.setFocus()

    # ---- 结束路径（全部汇聚到 _cleanup）----

    def _on_selection_done(self, rect: QRect) -> None:
        """rect 为全局逻辑坐标；按其中心定位所在屏，再用该屏快照裁剪。"""
        if self._ended:
            return
        center = rect.center()
        snapshot = snapshot_at(self._snapshots, center.x(), center.y())
        if snapshot is None:
            self._abort(
                ScreenCaptureError(
                    "选区不在任何屏幕内", detail=f"rect={rect.getRect()}"
                ),
                "截图选区异常",
            )
            return
        try:
            image = crop_snapshot(snapshot, rect)
        except Exception as exc:  # noqa: BLE001
            self._abort(exc, "截图裁剪失败")
            return
        self._cleanup()
        self.finished.emit(image)

    def _on_cancelled(self) -> None:
        if self._ended:
            return
        self._cleanup()
        self.cancelled.emit()

    def _abort(self, exc: Exception, message: str) -> None:
        """异常收尾：记录、销毁覆盖层、恢复主窗口、发可读提示。"""
        detail = getattr(exc, "detail", "") or repr(exc)
        logger.exception("截图流程异常：%s", detail)
        self._cleanup()
        self.failed.emit(message)

    def _cleanup(self) -> None:
        """单一收尾出口（design D6）：销毁全部覆盖层并恢复主窗口。"""
        self._ended = True
        for overlay in self._overlays:
            overlay.close()
            overlay.deleteLater()
        self._overlays.clear()
        window = self._window
        if window is not None and self._window_was_visible:
            window.show()
            window.raise_()
            window.activateWindow()
        # 流程对象一次性（任务 3.7），结束后自毁，避免主窗口父链累积（review 50-1）
        self.deleteLater()
