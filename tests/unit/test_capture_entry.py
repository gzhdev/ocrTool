"""截图识别入口与自动复制测试（spec: screen-capture / main-window，任务 4.1–4.6、5.1–5.5）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image as PILImage
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_helpers import mouse_move, mouse_press, mouse_release, process_events_until  # noqa: E402

import ocrtool.capture.region_overlay as region_overlay_mod  # noqa: E402
from ocrtool.capture.screen_capture import ScreenSnapshot  # noqa: E402
from ocrtool.controllers.ocr_controller import OcrController  # noqa: E402
from ocrtool.ocr.result import OcrResult  # noqa: E402
from ocrtool.ui.main_window import MainWindow  # noqa: E402


def make_result(lines: int = 2) -> OcrResult:
    from ocrtool.ocr.result import OcrLine

    line = OcrLine(text="行", score=0.9, box=((0, 0), (1, 0), (1, 1), (0, 1)))
    return OcrResult(
        text="\n".join("行" for _ in range(lines)) if lines else "",
        lines=(line,) * lines if lines else (),
        elapsed_ms=88.0,
        width=100,
        height=60,
    )


class FakeService:
    model_name = "测试模型"
    engine_loaded = False

    def preload(self) -> None:
        self.engine_loaded = True

    def recognize(self, image, *, scale: float = 1.0) -> OcrResult:
        return make_result()


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
    from ocrtool.app import paths

    paths.initialize()
    controller = OcrController(FakeService())
    config = {
        "ocr": {"model": "x", "max_edge_px": 6000},
        "runtime": {"cpu_threads": 4},
        "logging": {"level": "INFO"},
    }
    win = MainWindow(controller, config, startup_warnings=[])
    yield win
    paths.reset_for_tests()


@pytest.fixture(autouse=True)
def _require_qapp(qapp):
    yield


def patch_capture(monkeypatch, snapshot: ScreenSnapshot | None = None):
    if snapshot is None:
        snapshot = make_snapshot()
    monkeypatch.setattr(region_overlay_mod, "capture_all_screens", lambda: [snapshot])
    return snapshot


def make_snapshot(w: int = 640, h: int = 480) -> ScreenSnapshot:
    pixmap = QPixmap(w, h)
    pixmap.fill(QColor(120, 160, 200))
    return ScreenSnapshot(
        screen_name="fake",
        geometry=QRect(0, 0, w, h),
        device_pixel_ratio=1.0,
        pixmap=pixmap,
    )


class TestCaptureEntry:
    def test_空闲时触发入口进入截图流程(self, window, qapp, monkeypatch):
        patch_capture(monkeypatch)
        window.show()
        qapp.processEvents()
        window.start_region_capture()
        assert not window.isVisible(), "主窗口必须已隐藏"
        assert window._capture_flow is not None and window._capture_flow.active

    def test_识别期间截图入口禁用与其他入口一致(self, window, qapp):
        window._controller._busy = True
        window._on_busy_changed(True)
        assert not window._capture_action.isEnabled()
        assert not window._open_action.isEnabled()
        assert not window._paste_action.isEnabled()

    def test_完成选区自动载入并识别(self, window, qapp, monkeypatch):
        snapshot = patch_capture(monkeypatch)
        window.show()
        qapp.processEvents()
        window.start_region_capture()

        overlay = window._capture_flow._overlays[0]
        mouse_press(overlay, 50, 60)
        mouse_move(overlay, 300, 260)
        mouse_release(overlay, 300, 260)
        process_events_until(qapp, lambda: not window._controller.busy)

        assert window.isVisible(), "结束后主窗口必须恢复"
        assert window._viewer.has_image(), "捕获图像必须进入预览区"
        assert window._pending_image is not None, "必须成为当前待识别图像"
        assert window._result_panel.text.count("\n") == 1, "必须已自动发起识别（design D7）"

    def test_捕获图像不经文件格式校验(self, window, qapp, monkeypatch):
        """捕获由程序自身生成，扩展名/解码校验不适用（spec: image-input）。"""
        import ocrtool.utils.image as image_mod

        def must_not_validate(*args, **kwargs):
            raise AssertionError("捕获路径不得调用文件校验")

        monkeypatch.setattr(image_mod, "validate_and_load", must_not_validate)
        patch_capture(monkeypatch)

        image = QImage(80, 60, QImage.Format.Format_RGB32)
        image.fill(QColor(10, 20, 30))
        window._on_capture_finished(image)

        assert window._viewer.has_image()
        assert window._pending_image is not None

    def test_超大捕获按既有等比缩放并携带比例(self, window, qapp, monkeypatch):
        patch_capture(monkeypatch, make_snapshot(w=7000, h=400))
        image = QImage(7000, 400, QImage.Format.Format_RGB32)
        image.fill(QColor(9, 9, 9))
        window._on_capture_finished(image)
        assert window._viewer._pixmap_item.pixmap().width() == 7000  # 预览原图
        assert window._pending_image.shape[1] <= 6000  # 识别副本已缩放
        assert window._pending_scale < 1.0  # 结果携带缩放比例

    def test_取消只提示不弹错不识别(self, window, qapp, monkeypatch):
        patch_capture(monkeypatch)
        window.show()
        qapp.processEvents()
        window.start_region_capture()
        flow = window._capture_flow

        flow._on_cancelled()
        qapp.processEvents()

        assert window.isVisible()
        assert not flow.active
        assert window._pending_image is None, "取消不得产生识别请求"
        assert window._result_panel.text == ""

    def test_截图识别全程不落任何图像文件(self, window, qapp, monkeypatch, tmp_path):
        """spec: screen-capture「捕获不落磁盘」：USER_ROOT 下不得出现图像/临时文件。"""
        patch_capture(monkeypatch)
        window.show()
        qapp.processEvents()
        window.start_region_capture()

        overlay = window._capture_flow._overlays[0]
        mouse_press(overlay, 20, 20)
        mouse_move(overlay, 500, 400)
        mouse_release(overlay, 500, 400)
        process_events_until(qapp, lambda: not window._controller.busy)

        image_files = [
            p
            for p in (tmp_path / "user").rglob("*")
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tmp"}
        ]
        assert image_files == [], f"截图识别产生了磁盘文件：{image_files}"


class DottedDict:
    """点路径 get 替身：MainWindow 的配置契约是 ConfigManager 的 dotted get，
    普通 dict.get 不识别点路径会恒返回默认值。"""

    def __init__(self, values: dict) -> None:
        self._values = values

    def get(self, dotted_key: str, default=None):
        node = self._values
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


class TestAutoCopy:
    def test_默认开启成功检出文本自动复制(self, window, qapp, monkeypatch):
        patch_capture(monkeypatch)
        clipboard = QApplication.clipboard()
        clipboard.clear()
        image = QImage(60, 40, QImage.Format.Format_RGB32)
        window._on_capture_finished(image)
        process_events_until(qapp, lambda: not window._controller.busy)
        assert clipboard.text() == "行\n行"

    def test_空结果剪贴板保持不变(self, window, qapp, monkeypatch):
        patch_capture(monkeypatch)
        clipboard = QApplication.clipboard()
        clipboard.setText("用户既有的重要文本")
        window._controller._service.recognize = lambda img, scale=1.0: make_result(lines=0)

        image = QImage(60, 40, QImage.Format.Format_RGB32)
        window._on_capture_finished(image)
        process_events_until(qapp, lambda: not window._controller.busy)

        assert clipboard.text() == "用户既有的重要文本", "空结果写入空串即清空用户剪贴板（design D5）"

    def test_识别失败剪贴板保持不变(self, window, qapp, monkeypatch):
        from ocrtool.ocr.exceptions import RecognitionError

        patch_capture(monkeypatch)
        clipboard = QApplication.clipboard()
        clipboard.setText("用户既有的重要文本")

        def fail(image, *, scale: float = 1.0):
            raise RecognitionError("识别过程发生错误，请重试或更换图片")

        window._controller._service.recognize = fail
        image = QImage(60, 40, QImage.Format.Format_RGB32)
        window._on_capture_finished(image)
        process_events_until(qapp, lambda: not window._controller.busy)

        assert clipboard.text() == "用户既有的重要文本"

    def test_关闭自动复制后剪贴板不变且手动复制可用(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user2"))
        from ocrtool.app import paths

        paths.initialize()
        controller = OcrController(FakeService())
        config = DottedDict(
            {"ocr": {"model": "x", "max_edge_px": 6000}, "ui": {"auto_copy": False}}
        )
        win = MainWindow(controller, config, startup_warnings=[])
        clipboard = QApplication.clipboard()
        clipboard.setText("原有内容")

        win._on_result_ready(make_result())

        assert clipboard.text() == "原有内容"
        win._result_panel.copy_all()  # 手动复制仍可用（5.5）
        assert clipboard.text() == "行\n行"
        paths.reset_for_tests()

    def test_配置缺省时按默认开启(self, qapp, tmp_path, monkeypatch):
        """spec: main-window「配置项缺省」——用户配置无 ui 段时按内置默认开启。"""
        monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user3"))
        from ocrtool.app import paths

        paths.initialize()
        controller = OcrController(FakeService())
        config = DottedDict({"ocr": {"model": "x", "max_edge_px": 6000}})  # 无 ui 段
        win = MainWindow(controller, config, startup_warnings=[])
        clipboard = QApplication.clipboard()
        clipboard.clear()
        win._on_result_ready(make_result())
        assert clipboard.text() == "行\n行"
        paths.reset_for_tests()


class TestAutoCopyConfigLayer:
    def test_内置默认与分发默认一致且默认开启(self):
        from ocrtool.config.defaults import BUILTIN_DEFAULTS

        assert BUILTIN_DEFAULTS["ui"]["auto_copy"] is True

    def test_用户层可覆盖关闭(self, tmp_path):
        import json

        from ocrtool.config import manager as config_manager_mod

        default_file = tmp_path / "default.json"
        default_file.write_text(json.dumps({"ui": {"auto_copy": True}}), encoding="utf-8")
        user_file = tmp_path / "config.json"
        user_file.write_text(json.dumps({"ui": {"auto_copy": False}}), encoding="utf-8")
        mgr = config_manager_mod.load_config(default_file, user_file)
        assert mgr.get("ui.auto_copy") is False, "三层合并用户层优先"
