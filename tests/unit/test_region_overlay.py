"""RegionOverlay 单元测试：框选交互、边界截止、取消语义（任务 3.1–3.4）。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_helpers import mouse_move, mouse_press, mouse_release  # noqa: E402

from ocrtool.capture.region_overlay import RegionOverlay  # noqa: E402
from ocrtool.capture.screen_capture import ScreenSnapshot  # noqa: E402


def make_overlay(
    qapp, w: int = 800, h: int = 600, dpr: float = 2.0, x: int = 0, y: int = 0
) -> RegionOverlay:
    pixmap = QPixmap(round(w * dpr), round(h * dpr))
    pixmap.fill(QColor(20, 40, 60))
    snapshot = ScreenSnapshot(
        screen_name="fake",
        geometry=QRect(x, y, w, h),
        device_pixel_ratio=dpr,
        pixmap=pixmap,
    )
    overlay = RegionOverlay(snapshot)
    overlay.show()
    qapp.processEvents()  # 触发首帧绘制（冻结帧 + 弱化层不崩溃）
    return overlay


class TestSelectionInteraction:
    def test_按下拖动释放产生规范化选区(self, qapp):
        overlay = make_overlay(qapp)
        done: list[QRect] = []
        cancelled: list[bool] = []
        overlay.selectionDone.connect(done.append)
        overlay.cancelled.connect(lambda: cancelled.append(True))

        mouse_press(overlay, 300, 200)
        mouse_move(overlay, 250, 260)  # 反向拖动也须规范化
        mouse_release(overlay, 260, 250)

        assert cancelled == []
        assert done == [QRect(260, 200, 41, 51)]  # 两角 (300,200)-(260,250) 含端点

    def test_拖动越过屏幕边界选区截止(self, qapp):
        overlay = make_overlay(qapp, 800, 600)
        done: list[QRect] = []
        overlay.selectionDone.connect(done.append)

        mouse_press(overlay, 700, 300)
        mouse_move(overlay, 2000, 900)  # 远超本屏 800×600
        mouse_release(overlay, 2000, 900)

        selection = done[0]
        assert selection.right() <= 799
        assert selection.bottom() <= 599
        assert selection.width() >= 90  # 仍是从 700 到右缘的有效选区

    def test_拖动期间选区实时更新(self, qapp):
        overlay = make_overlay(qapp)
        mouse_press(overlay, 100, 100)
        mouse_move(overlay, 300, 200)
        assert overlay._selection == QRect(100, 100, 201, 101)

    def test_非原点屏选区以全局逻辑坐标发出(self, qapp):
        """review 100-1：选区信号必须是全局逻辑坐标（局部 + 屏原点）——
        下游 logical_to_physical 会再减一次屏原点，双重平移使副屏静默取消或裁错。"""
        overlay = make_overlay(qapp, w=800, h=600, dpr=1.0, x=640, y=0)
        done: list[QRect] = []
        overlay.selectionDone.connect(done.append)

        mouse_press(overlay, 100, 100)
        mouse_release(overlay, 400, 300)

        assert done == [QRect(740, 100, 301, 201)], (
            f"副屏 (640,0) 上局部 (100,100)-(400,300) 应发出全局 (740,100,301,201)，"
            f"实际 {done}"
        )

    def test_覆盖层被外部关闭按取消发出信号(self, qapp):
        """review 75-1：Alt+F4 / WM_CLOSE 关闭覆盖层不得让流程失去收尾。"""
        overlay = make_overlay(qapp)
        cancelled: list[bool] = []
        overlay.cancelled.connect(lambda: cancelled.append(True))

        overlay.close()
        qapp.processEvents()

        assert cancelled == [True]


class TestCancelSemantics:
    def test_ESC取消(self, qapp):
        overlay = make_overlay(qapp)
        cancelled: list[bool] = []
        overlay.cancelled.connect(lambda: cancelled.append(True))
        QTest.keyClick(overlay, Qt.Key.Key_Escape)
        assert cancelled == [True]

    def test_右键取消_拖动中也生效(self, qapp):
        overlay = make_overlay(qapp)
        cancelled: list[bool] = []
        done: list[QRect] = []
        overlay.cancelled.connect(lambda: cancelled.append(True))
        overlay.selectionDone.connect(done.append)

        mouse_press(overlay, 100, 100)
        mouse_move(overlay, 300, 200)
        mouse_press(overlay, 200, 150, button=Qt.MouseButton.RightButton)

        assert cancelled == [True]
        assert done == []

    def test_单击按取消处理不识别不报错(self, qapp):
        overlay = make_overlay(qapp)
        done: list[QRect] = []
        cancelled: list[bool] = []
        overlay.selectionDone.connect(done.append)
        overlay.cancelled.connect(lambda: cancelled.append(True))

        mouse_press(overlay, 400, 300)
        mouse_release(overlay, 401, 300)  # 位移 1 逻辑像素 = 2 物理像素 < 8

        assert done == []
        assert cancelled == [True]

    def test_过小选区按取消处理(self, qapp):
        overlay = make_overlay(qapp, dpr=1.0)  # 8 物理像素 = 8 逻辑像素
        done: list[QRect] = []
        cancelled: list[bool] = []
        overlay.selectionDone.connect(done.append)
        overlay.cancelled.connect(lambda: cancelled.append(True))

        mouse_press(overlay, 100, 100)
        mouse_release(overlay, 106, 104)  # 7×5 物理像素，低于阈值

        assert done == []
        assert cancelled == [True]
