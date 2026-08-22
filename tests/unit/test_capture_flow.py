"""RegionCaptureFlow 单元测试：隐藏等待、恢复、单一收尾出口、重入（任务 2.1/2.4/3.5–3.7）。"""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

import ocrtool.capture.region_overlay as region_overlay_mod
from ocrtool.capture.region_overlay import RegionCaptureFlow
from ocrtool.capture.screen_capture import ScreenSnapshot


def make_snapshot(
    x: int = 0, y: int = 0, w: int = 640, h: int = 480, dpr: float = 1.0
) -> ScreenSnapshot:
    pixmap = QPixmap(round(w * dpr), round(h * dpr))
    pixmap.fill(QColor(20, 40, 60))
    return ScreenSnapshot(
        screen_name="fake",
        geometry=QRect(x, y, w, h),
        device_pixel_ratio=dpr,
        pixmap=pixmap,
    )


@pytest.fixture(autouse=True)
def _require_qapp(qapp):
    """合成快照持有 QPixmap，必须先有 QApplication，否则 Qt qFatal 中止进程。"""
    yield


@pytest.fixture
def visible_window(qapp):
    window = QWidget()
    window.resize(300, 200)
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def patch_capture(monkeypatch, snapshots, spy=None):
    """替换捕获入口；spy 可记录捕获时刻的观测值（用于隐藏等待断言）。"""
    def fake_capture():
        if spy is not None:
            spy()
        return snapshots

    monkeypatch.setattr(region_overlay_mod, "capture_all_screens", fake_capture)


class TestHideAndWait:
    def test_捕获时主窗口已隐藏且未暴露(self, qapp, visible_window, monkeypatch):
        observations: dict[str, object] = {}

        def spy():
            handle = visible_window.windowHandle()
            observations["visible"] = visible_window.isVisible()
            observations["exposed"] = bool(handle and handle.isExposed())

        patch_capture(monkeypatch, [make_snapshot()], spy=spy)
        flow = RegionCaptureFlow()

        started = time.monotonic()
        flow.start(visible_window)

        assert observations["visible"] is False, "捕获时主窗口必须已隐藏"
        assert observations["exposed"] is False, "捕获时隐藏必须已被系统确认"
        elapsed = time.monotonic() - started
        assert elapsed >= region_overlay_mod.MIN_HIDE_DELAY_MS / 1000, (
            "必须等待下限延时（design D4），不得隐藏后立即捕获"
        )
        flow._cleanup()

    def test_隐藏等待期异常仍恢复主窗口(self, qapp, monkeypatch):
        """review 50-4：was_visible 必须在 hide 副作用之前落账——
        否则等待期异常走到 _cleanup 时读到 False，主窗口永不恢复。"""
        from PySide6.QtWidgets import QApplication, QWidget

        window = QWidget()
        window.show()
        qapp.processEvents()

        def boom(*args, **kwargs):
            raise RuntimeError("processEvents 崩了")

        monkeypatch.setattr(QApplication, "processEvents", boom)
        patch_capture(monkeypatch, [make_snapshot()])
        flow = RegionCaptureFlow()
        failed: list[str] = []
        flow.failed.connect(failed.append)

        flow.start(window)

        assert failed == ["截图流程启动失败"]
        assert window.isVisible(), "隐藏已发生但记录未落账——异常后主窗口必须恢复"

    def test_发起前就不可见的窗口保持不可见(self, qapp, monkeypatch):
        window = QWidget()  # 从不 show：windowHandle 为 None
        patch_capture(monkeypatch, [make_snapshot()])
        flow = RegionCaptureFlow()
        cancelled: list[bool] = []
        flow.cancelled.connect(lambda: cancelled.append(True))
        flow.start(window)
        assert not window.isVisible()
        flow._cleanup()
        assert not window.isVisible(), "发起前不可见则恢复后也不可见"


class TestCompleteAndRestore:
    def test_有效选区完成_裁剪冻结帧并恢复窗口(self, qapp, visible_window, monkeypatch):
        snapshot = make_snapshot()
        painter = QPainter(snapshot.pixmap)
        painter.fillRect(0, 0, 320, 480, QColor(200, 30, 40))  # 左半红
        painter.fillRect(320, 0, 320, 480, QColor(30, 60, 200))  # 右半蓝
        painter.end()
        patch_capture(monkeypatch, [snapshot])

        flow = RegionCaptureFlow()
        finished: list[object] = []
        flow.finished.connect(finished.append)
        flow.start(visible_window)

        assert not visible_window.isVisible(), "选区期间主窗口保持隐藏"
        overlay = flow._overlays[0]
        from qt_helpers import mouse_move, mouse_press, mouse_release

        mouse_press(overlay, 40, 50)
        mouse_move(overlay, 200, 300)
        mouse_release(overlay, 200, 300)
        qapp.processEvents()

        assert len(finished) == 1
        image = finished[0]
        assert image.size() == QSize(161, 251)  # 逻辑 (40,50)-(200,300) 规范化，dpr=1
        for px, py in ((0, 0), (80, 125), (160, 250)):
            assert image.pixelColor(px, py).rgb() == QColor(200, 30, 40).rgb()
        assert visible_window.isVisible(), "结束后主窗口必须恢复可见"
        assert flow._overlays == []
        assert not flow.active

    def test_选区期间不发生二次捕获(self, qapp, visible_window, monkeypatch):
        """冻结帧（design D1）：裁剪只读捕获时刻的画面，结构上保证——
        整个流程（启动 → 选区 → 完成）捕获入口恰好被调用一次。"""
        calls: list[int] = []

        def fake_capture():
            calls.append(1)
            return [make_snapshot()]

        monkeypatch.setattr(region_overlay_mod, "capture_all_screens", fake_capture)
        flow = RegionCaptureFlow()
        finished: list[object] = []
        flow.finished.connect(finished.append)
        flow.start(visible_window)
        flow._on_selection_done(QRect(10, 10, 100, 100))  # 全局坐标（review 100-1）

        assert len(finished) == 1
        assert calls == [1], "选区与裁剪阶段不得再次捕获屏幕"


class TestNonOriginScreen:
    """review 100-1 回归：非原点屏（副屏）全链路「框选 → 裁剪 → 内容」。

    合成双屏：主屏 (0,0,640,480) + 副屏 (640,0,800,600)，两屏均左半红右半蓝。
    overlay 鼠标事件是屏内局部坐标，下游换算是全局逻辑坐标——修复前局部坐标
    被再减一次屏原点 (640,0)：副屏左半选区整体落屏外 → 静默取消；右半选区
    → 裁出左偏 640px 的错误区域。
    """

    @staticmethod
    def _dual_screen():
        def two_tone(x: int, y: int, w: int, h: int) -> ScreenSnapshot:
            snapshot = make_snapshot(x, y, w, h)
            painter = QPainter(snapshot.pixmap)
            painter.fillRect(
                0, 0, snapshot.pixmap.width() // 2, snapshot.pixmap.height(),
                QColor(200, 30, 40),
            )
            painter.fillRect(
                snapshot.pixmap.width() // 2, 0,
                snapshot.pixmap.width() - snapshot.pixmap.width() // 2,
                snapshot.pixmap.height(),
                QColor(30, 60, 200),
            )
            painter.end()
            return snapshot

        return [two_tone(0, 0, 640, 480), two_tone(640, 0, 800, 600)]

    def _finish_on_secondary(self, qapp, monkeypatch, visible_window, x0, x1):
        patch_capture(monkeypatch, self._dual_screen())
        flow = RegionCaptureFlow()
        finished: list[object] = []
        cancelled: list[bool] = []
        flow.finished.connect(finished.append)
        flow.cancelled.connect(lambda: cancelled.append(True))
        flow.start(visible_window)

        overlay = flow._overlays[1]  # 副屏覆盖层
        from qt_helpers import mouse_move, mouse_press, mouse_release

        mouse_press(overlay, x0, 100)
        mouse_move(overlay, x1, 300)
        mouse_release(overlay, x1, 300)
        qapp.processEvents()
        return finished, cancelled

    def test_副屏左半框选得到正确内容(self, qapp, visible_window, monkeypatch):
        finished, cancelled = self._finish_on_secondary(
            qapp, monkeypatch, visible_window, x0=100, x1=400
        )
        assert cancelled == [], "副屏有效选区不得被静默取消（review 100-1）"
        assert len(finished) == 1
        image = finished[0]
        assert image.size() == QSize(301, 201)
        assert image.pixelColor(
            image.width() // 2, image.height() // 2
        ).rgb() == QColor(200, 30, 40).rgb(), "副屏左半应为红色"

    def test_副屏右半框选得到正确内容(self, qapp, visible_window, monkeypatch):
        finished, cancelled = self._finish_on_secondary(
            qapp, monkeypatch, visible_window, x0=500, x1=800
        )
        assert cancelled == []
        assert len(finished) == 1
        image = finished[0]
        # 释放点 800 被夹取到屏内最右列 799：500..799 含端点宽 300
        assert image.size() == QSize(300, 201)
        assert image.pixelColor(
            image.width() // 2, image.height() // 2
        ).rgb() == QColor(30, 60, 200).rgb(), "副屏右半应为蓝色，左偏 640px 即双重平移"

    def test_覆盖层被外部关闭按取消收尾并恢复主窗口(self, qapp, visible_window, monkeypatch):
        """review 75-1：选区期间 Alt+F4 → WM_CLOSE 关闭覆盖层，flow 不得僵尸化。"""
        patch_capture(monkeypatch, [make_snapshot()])
        flow = RegionCaptureFlow()
        cancelled: list[bool] = []
        flow.cancelled.connect(lambda: cancelled.append(True))
        flow.start(visible_window)

        flow._overlays[0].close()  # 等价 WM_CLOSE 外部关闭
        qapp.processEvents()

        assert cancelled == [True]
        assert not flow.active
        assert flow._overlays == []
        assert visible_window.isVisible(), "外部关闭后主窗口必须恢复"


class TestCancelAndLifecycle:
    def test_取消后覆盖层销毁且窗口恢复(self, qapp, visible_window, monkeypatch):
        patch_capture(monkeypatch, [make_snapshot()])
        flow = RegionCaptureFlow()
        cancelled: list[bool] = []
        flow.cancelled.connect(lambda: cancelled.append(True))
        flow.start(visible_window)
        overlay = flow._overlays[0]
        from qt_helpers import mouse_press, mouse_release

        mouse_press(overlay, 400, 240)
        mouse_release(overlay, 401, 240)  # 单击 → 取消
        qapp.processEvents()

        assert cancelled == [True]
        assert flow._overlays == []
        assert not overlay.isVisible()
        assert visible_window.isVisible()

    def test_多屏覆盖层一致关闭(self, qapp, visible_window, monkeypatch):
        patch_capture(
            monkeypatch,
            [make_snapshot(0, 0, 640, 480), make_snapshot(640, 0, 800, 600, dpr=1.5)],
        )
        flow = RegionCaptureFlow()
        flow.start(visible_window)
        assert len(flow._overlays) == 2
        overlays = list(flow._overlays)

        flow._on_cancelled()  # 在任一屏取消 → 全部关闭（3.5）

        assert flow._overlays == []
        assert all(not o.isVisible() for o in overlays), (
            "其他屏幕的覆盖层必须同时消失（spec: screen-capture）"
        )
        assert visible_window.isVisible()

    def test_捕获异常走单一收尾出口(self, qapp, visible_window, monkeypatch):
        def boom():
            raise RuntimeError("grabWindow 崩了")

        monkeypatch.setattr(region_overlay_mod, "capture_all_screens", boom)
        flow = RegionCaptureFlow()
        failed: list[str] = []
        flow.failed.connect(failed.append)
        flow.start(visible_window)

        assert failed == ["截图流程启动失败"]
        assert flow._overlays == []
        assert visible_window.isVisible(), "异常后主窗口必须恢复（spec: screen-capture）"

    def test_选区阶段异常同样销毁覆盖层并恢复(self, qapp, visible_window, monkeypatch):
        patch_capture(monkeypatch, [make_snapshot()])
        flow = RegionCaptureFlow()
        failed: list[str] = []
        flow.failed.connect(failed.append)
        flow.start(visible_window)
        overlay = flow._overlays[0]

        # 完全落在所有屏幕之外的选区 → 定位失败：注入异常路径（任务 3.6）
        flow._on_selection_done(QRect(6000, 6000, 10, 10))
        qapp.processEvents()

        assert failed == ["截图选区异常"]
        assert flow._overlays == []
        assert not overlay.isVisible()
        assert visible_window.isVisible()

    def test_结束后重复信号被忽略(self, qapp, visible_window, monkeypatch):
        patch_capture(monkeypatch, [make_snapshot()])
        flow = RegionCaptureFlow()
        cancelled: list[bool] = []
        flow.cancelled.connect(lambda: cancelled.append(True))
        flow.start(visible_window)
        flow._on_cancelled()
        flow._on_cancelled()  # 迟到的第二个取消
        assert cancelled == [True]

    def test_取消后立即再次发起可正常工作(self, qapp, visible_window, monkeypatch):
        patch_capture(monkeypatch, [make_snapshot()])

        first = RegionCaptureFlow()
        first.start(visible_window)
        first._on_cancelled()
        assert visible_window.isVisible()

        second = RegionCaptureFlow()
        finished: list[object] = []
        second.finished.connect(finished.append)
        second.start(visible_window)  # 上次取消不得影响新流程（3.7）
        assert len(second._overlays) == 1
        assert not visible_window.isVisible()
        second._on_selection_done(QRect(10, 10, 100, 100))
        assert len(finished) == 1
        assert visible_window.isVisible()
