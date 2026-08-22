"""capture/ 单元测试：逐屏坐标换算、混合 DPI、裁剪与捕获错误路径（任务 1.1–1.3）。"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap

from ocrtool.capture.screen_capture import (
    ScreenCaptureError,
    ScreenSnapshot,
    crop_snapshot,
    logical_to_physical,
    physical_size_of,
    snapshot_at,
)


@pytest.fixture(autouse=True)
def _require_qapp(qapp):
    """合成快照持有 QPixmap，必须先有 QApplication，否则 Qt qFatal 中止进程。"""
    yield


def make_snapshot(
    x: int,
    y: int,
    w: int,
    h: int,
    dpr: float,
    name: str = "fake",
) -> ScreenSnapshot:
    """合成屏幕快照：物理像素尺寸 = 逻辑尺寸 × 自身缩放比例。"""
    pixmap = QPixmap(round(w * dpr), round(h * dpr))
    pixmap.fill(QColor(20, 40, 60))
    return ScreenSnapshot(
        screen_name=name,
        geometry=QRect(x, y, w, h),
        device_pixel_ratio=dpr,
        pixmap=pixmap,
    )


def mixed_setup() -> list[ScreenSnapshot]:
    """合成混合 DPI 环境：主屏 100%（左）+ 副屏 150%（右）+ 左侧 100% 副屏。"""
    primary = make_snapshot(0, 0, 1920, 1080, 1.0, name="primary")
    secondary = make_snapshot(1920, 0, 1536, 864, 1.5, name="secondary")
    left = make_snapshot(-1024, 0, 1024, 768, 1.0, name="left")
    return [primary, secondary, left]


class TestLogicalToPhysical:
    def test_主屏100百分比坐标恒等(self):
        primary = mixed_setup()[0]
        assert logical_to_physical(QRect(100, 200, 300, 400), primary) == QRect(
            100, 200, 300, 400
        )

    def test_副屏用自身150百分比换算(self):
        secondary = mixed_setup()[1]
        # 副屏内局部 (100,200,300x400) → 全局逻辑 (2020,200,300,400) → 物理 ×1.5
        physical = logical_to_physical(QRect(2020, 200, 300, 400), secondary)
        assert physical.x() == pytest.approx(150, abs=1)
        assert physical.y() == pytest.approx(300, abs=1)
        assert physical.width() == pytest.approx(450, abs=1)
        assert physical.height() == pytest.approx(600, abs=1)

    def test_混合DPI两屏各自独立互不串扰(self):
        """决策关卡 1.6 的结构性保证：每屏只用自身比例。"""
        primary, secondary, _ = mixed_setup()
        rect_primary = logical_to_physical(QRect(960, 540, 100, 100), primary)
        rect_secondary = logical_to_physical(QRect(960 + 1920, 540, 100, 100), secondary)
        assert rect_primary.width() == 100  # ×1.0
        assert rect_secondary.width() == pytest.approx(150, abs=1)  # ×1.5

    def test_负坐标屏同样正确(self):
        left = mixed_setup()[2]
        # 左屏局部 (24,100) → 全局 (-1000,100) → 物理 ×1.0
        assert logical_to_physical(QRect(-1000, 100, 1, 1), left).x() == 24

    def test_选区越界被夹取在捕获图范围内(self):
        primary = mixed_setup()[0]
        physical = logical_to_physical(QRect(1900, 1000, 200, 200), primary)
        assert physical.right() <= primary.pixmap.width() - 1
        assert physical.bottom() <= primary.pixmap.height() - 1

    def test_物理尺寸供过小判定(self):
        secondary = mixed_setup()[1]
        # 逻辑 4px × 1.5 = 物理 6px（< 8），逻辑 8px × 1.5 = 12px（≥ 8）
        assert physical_size_of(QRect(1920, 0, 4, 4), secondary)[0] < 8
        assert physical_size_of(QRect(1920, 0, 8, 8), secondary)[0] >= 8


class TestSnapshotAt:
    def test_按逻辑坐标定位所在屏(self):
        snapshots = mixed_setup()
        assert snapshot_at(snapshots, 500, 500) is snapshots[0]
        assert snapshot_at(snapshots, 1920 + 500, 400) is snapshots[1]
        assert snapshot_at(snapshots, -500, 100) is snapshots[2]

    def test_屏幕之外的点返回None(self):
        assert snapshot_at(mixed_setup(), 20000, 20000) is None


class TestCrop:
    def test_裁剪内容与冻结帧逐像素对应(self, qapp):
        snapshot = make_snapshot(0, 0, 400, 300, 1.0)
        painter = QPainter(snapshot.pixmap)
        painter.fillRect(0, 0, 200, 300, QColor(200, 30, 40))  # 左半红
        painter.fillRect(200, 0, 200, 300, QColor(30, 60, 200))  # 右半蓝
        painter.end()

        left = crop_snapshot(snapshot, QRect(10, 10, 100, 100))
        assert left.size() == QSize(100, 100)
        for x in (0, 50, 99):
            for y in (0, 50, 99):
                assert left.pixelColor(x, y).rgb() == QColor(200, 30, 40).rgb()

        right = crop_snapshot(snapshot, QRect(250, 50, 100, 200))
        assert right.pixelColor(50, 100).rgb() == QColor(30, 60, 200).rgb()

    def test_裁剪用自身缩放比例保留原始密度(self, qapp):
        snapshot = make_snapshot(0, 0, 400, 300, 2.0)  # 物理 800×600
        cropped = crop_snapshot(snapshot, QRect(100, 150, 200, 100))
        assert cropped.width() == 400  # 逻辑 200 × dpr 2
        assert cropped.height() == 200

    def test_空选区给出可读错误(self, qapp):
        snapshot = make_snapshot(0, 0, 400, 300, 1.0)
        with pytest.raises(ScreenCaptureError) as exc_info:
            crop_snapshot(snapshot, QRect(10000, 10000, 10, 10))
        assert "选区" in exc_info.value.message


class TestCaptureScreen:
    def test_空图像转为可读错误(self, qapp, monkeypatch):
        from PySide6.QtGui import QScreen

        screen = qapp.screens()[0]
        monkeypatch.setattr(QScreen, "grabWindow", lambda self, *a, **k: QPixmap())
        with pytest.raises(ScreenCaptureError) as exc_info:
            from ocrtool.capture.screen_capture import capture_screen

            capture_screen(screen)
        assert "屏幕捕获失败" in exc_info.value.message

    def test_正常捕获携带该屏几何与比例(self, qapp, monkeypatch):
        from PySide6.QtGui import QScreen

        from ocrtool.capture.screen_capture import capture_screen

        screen = qapp.screens()[0]
        fake = QPixmap(64, 48)
        monkeypatch.setattr(QScreen, "grabWindow", lambda self, *a, **k: fake)
        snapshot = capture_screen(screen)
        assert snapshot.geometry == screen.geometry()
        assert snapshot.device_pixel_ratio == screen.devicePixelRatio()
        assert snapshot.pixmap is fake
