"""ui/ 组件测试：预览交互、结果面板、状态区、错误分级与自检（任务 4.1–4.7）。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QWheelEvent
from PySide6.QtWidgets import QMessageBox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_helpers import process_events_until

from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.ocr.exceptions import (
    ModelLoadError,
    ModelMissingError,
    RecognitionError,
)
from ocrtool.ocr.result import OcrResult
from ocrtool.ocr.states import OcrState as S
from ocrtool.ui.main_window import MainWindow, STATE_TEXTS
from ocrtool.ui.widgets.image_viewer import ImageViewer
from ocrtool.ui.widgets.result_panel import ResultPanel
from ocrtool.ui.widgets.status_widget import StatusWidget


def sample_qimage(size: tuple[int, int] = (120, 80)) -> QImage:
    pil = Image.new("RGB", size, (30, 144, 255))
    import io

    buffer = io.BytesIO()
    pil.save(buffer, format="png")
    image = QImage()
    image.loadFromData(buffer.getvalue())
    return image


def make_result(lines: int = 2) -> OcrResult:
    from ocrtool.ocr.result import OcrLine

    line = OcrLine(text="行", score=0.9, box=((0, 0), (1, 0), (1, 1), (0, 1)))
    return OcrResult(
        text="\n".join("行" for _ in range(lines)) if lines else "",
        lines=(line,) * lines if lines else (),
        elapsed_ms=321.0,
        width=120,
        height=80,
    )


class FakeService:
    model_name = "测试模型"

    def __init__(self) -> None:
        self.engine_loaded = False

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


class TestImageViewer:
    def test_载入图像等比自适应显示(self, qapp):
        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.set_image(sample_qimage((200, 100)))
        viewer.show()
        qapp.processEvents()
        # fitInView(KeepAspectRatio) 的等比性：水平/垂直缩放分量一致
        transform = viewer.transform()
        assert abs(transform.m11() - transform.m22()) < 1e-6
        assert viewer.has_image()

    def test_窗口尺寸变化保持等比(self, qapp):
        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.set_image(sample_qimage((200, 100)))
        viewer.show()
        qapp.processEvents()
        before = viewer.zoom_scale
        viewer.resize(600, 400)
        qapp.processEvents()
        transform = viewer.transform()
        assert abs(transform.m11() - transform.m22()) < 1e-6
        assert viewer.zoom_scale != before  # 自适应重算

    def test_滚轮缩放以光标为中心(self, qapp):
        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.set_image(sample_qimage((400, 300)))
        viewer.show()
        qapp.processEvents()
        scale_before = viewer.zoom_scale

        position = QPointF(200.0, 150.0)
        event = QWheelEvent(
            position, position,
            QPoint(0, 0), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        viewer.wheelEvent(event)
        assert viewer.zoom_scale == pytest.approx(scale_before * 1.2, rel=1e-3)

    def test_拖动平移启用(self, qapp):
        viewer = ImageViewer()
        assert viewer.dragMode() == ImageViewer.DragMode.ScrollHandDrag

    def test_拖放单张图像发出路径信号(self, qapp, tmp_path):
        viewer = ImageViewer()
        png = tmp_path / "drop.png"
        Image.new("RGB", (10, 10)).save(png)

        received: list[Path] = []
        viewer.imageDropped.connect(received.append)

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(png))])
        event = QDropEvent(
            QPointF(10, 10), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        viewer.dropEvent(event)
        assert received == [png]

    def test_拖放多个文件被拒绝且当前图像不变(self, qapp, tmp_path):
        viewer = ImageViewer()
        viewer.set_image(sample_qimage())
        rejected: list[str] = []
        received: list[Path] = []
        viewer.dropRejected.connect(rejected.append)
        viewer.imageDropped.connect(received.append)

        mime = QMimeData()
        mime.setUrls([
            QUrl.fromLocalFile(str(tmp_path / "a.png")),
            QUrl.fromLocalFile(str(tmp_path / "b.png")),
        ])
        event = QDropEvent(
            QPointF(10, 10), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        viewer.dropEvent(event)
        assert received == []
        assert rejected and "一次只能处理一张" in rejected[0]
        assert viewer.has_image(), "拒绝后当前图像必须保持不变"

    def test_拖放非图像被拒绝(self, qapp, tmp_path):
        viewer = ImageViewer()
        viewer.set_image(sample_qimage())
        rejected: list[str] = []
        received: list[Path] = []
        viewer.dropRejected.connect(rejected.append)
        viewer.imageDropped.connect(received.append)

        txt = tmp_path / "note.txt"
        txt.write_text("x", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(txt))])
        event = QDropEvent(
            QPointF(10, 10), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        viewer.dropEvent(event)
        assert received == []
        assert viewer.has_image()


class TestResultPanel:
    def test_识别成功展示文本且可选中(self, qapp):
        panel = ResultPanel()
        panel.set_result("第一行\n第二行")
        assert panel.text == "第一行\n第二行"
        assert panel._text_edit.isReadOnly()

    def test_无结果复制不改剪贴板并提示(self, qapp):
        panel = ResultPanel()
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText("既有内容")
        messages: list[str] = []
        panel.statusMessage.connect(messages.append)
        panel.copy_all()
        assert QApplication.clipboard().text() == "既有内容"
        assert messages == ["当前无可复制内容"]

    def test_复制全部写入剪贴板(self, qapp):
        panel = ResultPanel()
        panel.set_result("待复制文本")
        messages: list[str] = []
        panel.statusMessage.connect(messages.append)
        panel.copy_all()
        from PySide6.QtWidgets import QApplication

        assert QApplication.clipboard().text() == "待复制文本"
        assert messages == ["已复制到剪贴板"]

    def test_清空(self, qapp):
        panel = ResultPanel()
        panel.set_result("x")
        panel.clear()
        assert panel.text == ""


class TestStatusWidget:
    def test_识别完成后四项信息正确显示(self, qapp):
        status = StatusWidget()
        status.set_model("PP-OCRv6 Small")
        status.set_state("完成")
        status.set_timing(321.0)
        status.set_lines(2)
        assert "PP-OCRv6 Small" in status._model_label.text()
        assert status._state_label.text() == "完成"
        assert "321" in status._timing_label.text()
        assert status._lines_label.text() == "行数 2"

    def test_秒级耗时格式(self, qapp):
        status = StatusWidget()
        status.set_timing(1500.0)
        assert "s" in status._timing_label.text()


class TestMainWindow:
    def test_依赖注入不创建服务实例(self, window):
        # 窗口仅持有控制器；构造函数签名即为契约（controller, config）
        assert window._controller is not None
        assert window._controller.model_name == "测试模型"

    def test_载入受支持格式成为当前图像(self, window, qapp, tmp_path):
        png = tmp_path / "ok.png"
        Image.new("RGB", (60, 40), "red").save(png)
        window.load_from_path(png)
        assert window._viewer.has_image()
        assert window._pending_image is not None
        assert window._pending_image.shape[:2] == (40, 60)
        assert window._pending_scale == 1.0

    def test_载入不受支持格式被拒绝且当前图像不变(self, window, tmp_path):
        png = tmp_path / "ok.png"
        Image.new("RGB", (60, 40), "red").save(png)
        window.load_from_path(png)
        before = window._pending_image.copy()

        gif = tmp_path / "bad.gif"
        gif.write_bytes(b"GIF89a")
        window.load_from_path(gif)
        assert window._viewer.has_image()
        np.testing.assert_array_equal(window._pending_image, before)

    def test_超大图像生成缩放副本而预览保持原图(self, window, tmp_path):
        pil = Image.new("RGB", (6200, 300), "blue")
        png = tmp_path / "big.png"
        pil.save(png)
        window.load_from_path(png)
        assert window._viewer._pixmap_item.pixmap().width() == 6200  # 原图
        assert window._pending_image.shape[1] <= 6000  # 识别副本已缩放
        assert window._pending_scale < 1.0

    def test_识别完成后结果与状态呈现(self, window, qapp, tmp_path):
        png = tmp_path / "ok.png"
        Image.new("RGB", (60, 40), "red").save(png)
        window.load_from_path(png)
        window.start_recognition()
        process_events_until(qapp, lambda: not window._controller.busy)

        assert window._result_panel.text.count("\n") == 1  # 2 行结果
        assert "完成" in window._status._state_label.text()
        assert "行数 2" == window._status._lines_label.text()
        assert window._status._timing_label.text() != "-"

    def test_识别期间触发入口禁用并恢复(self, window, qapp, tmp_path):
        import time

        window._controller._service.__class__ = type(
            "SlowService", (FakeService,), {"recognize": staticmethod(lambda img, scale=1.0: (time.sleep(0.15), make_result())[1])}
        )
        png = tmp_path / "ok.png"
        Image.new("RGB", (60, 40), "red").save(png)
        window.load_from_path(png)
        window.start_recognition()
        qapp.processEvents()
        assert not window._recognize_action.isEnabled()
        assert not window._open_action.isEnabled()
        process_events_until(qapp, lambda: not window._controller.busy)
        assert window._recognize_action.isEnabled()

    def test_空结果状态区提示且不弹窗(self, window, qapp, tmp_path, monkeypatch):
        dialogs: list[tuple] = []
        monkeypatch.setattr(
            QMessageBox, "critical",
            staticmethod(lambda *a, **k: dialogs.append(a)),
        )
        window._controller._service.recognize = lambda img, scale=1.0: make_result(lines=0)
        png = tmp_path / "blank.png"
        Image.new("RGB", (60, 40), "white").save(png)
        window.load_from_path(png)
        window.start_recognition()
        process_events_until(qapp, lambda: not window._controller.busy)

        assert window._status._state_label.text() == "未识别到文本"
        assert dialogs == []

    def test_模型缺失错误用对话框(self, window, qapp, monkeypatch):
        dialogs: list[str] = []
        monkeypatch.setattr(
            "ocrtool.ui.main_window.QMessageBox.critical",
            lambda self, title, text: dialogs.append(text),
        )
        window._on_error(ModelMissingError("模型文件缺失，请重新获取或恢复程序目录"))
        assert dialogs and "模型文件缺失" in dialogs[0]

    def test_普通识别失败只用状态区不弹窗(self, window, qapp, monkeypatch):
        dialogs: list[str] = []
        monkeypatch.setattr(
            "ocrtool.ui.main_window.QMessageBox.critical",
            lambda self, title, text: dialogs.append(text),
        )
        window._on_error(RecognitionError("识别过程发生错误，请重试或更换图片"))
        assert dialogs == []

    def test_格式不支持与剪贴板无图不弹窗(self, window, qapp, tmp_path, monkeypatch):
        dialogs: list[str] = []
        monkeypatch.setattr(
            "ocrtool.ui.main_window.QMessageBox.critical",
            lambda self, title, text: dialogs.append(text),
        )
        gif = tmp_path / "x.gif"
        gif.write_bytes(b"GIF89a")
        window.load_from_path(gif)  # 格式不支持
        window.load_from_clipboard()  # 剪贴板无图（offscreen 下无图像数据）
        assert dialogs == []

    def test_错误界面文本不含调用栈与原始异常消息(self, window, monkeypatch):
        evidence: list[str] = []

        def capture(title, text):
            evidence.append(text)
            return 0

        monkeypatch.setattr(
            "ocrtool.ui.main_window.QMessageBox.critical",
            lambda self, title, text: capture(title, text),
        )
        error = ModelLoadError("模型加载失败，程序可能已损坏，请重新获取")
        error.detail = 'Traceback (most recent call last):\n  File "x.py"\nRuntimeError: onnx broken'
        window._on_error(error)
        assert evidence
        for forbidden in ("Traceback", "File", "RuntimeError", "onnx"):
            assert forbidden not in evidence[0]

    def test_清空后状态回空闲(self, window, qapp, tmp_path):
        png = tmp_path / "ok.png"
        Image.new("RGB", (60, 40), "red").save(png)
        window.load_from_path(png)
        window._result_panel.set_result("旧结果")
        window.clear_all()
        assert not window._viewer.has_image()
        assert window._result_panel.text == ""
        assert window._pending_image is None
        assert not window._recognize_action.isEnabled()
        assert window._status._state_label.text() == "就绪"


class TestStartupSelfCheck:
    def test_自检发现模型缺失时仍可启动并提示(self, qapp, tmp_path, monkeypatch):
        monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "u"))
        from ocrtool.app import paths

        paths.initialize()
        # 指向不存在的模型根 → 自检失败但不抛异常
        monkeypatch.setattr(paths, "model_dir", lambda: tmp_path / "no-such-models")

        controller = OcrController(FakeService())
        config = {"ocr": {"model": "x", "max_edge_px": 6000}}
        win = MainWindow(controller, config, startup_warnings=[])
        assert win._status._state_label.text() == "自检发现问题"
        assert win._controller._service.engine_loaded is False, "自检不得加载模型"
        paths.reset_for_tests()

    def test_自检通过显示就绪(self, window):
        assert window._status._state_label.text() in ("就绪", "已载入图像")
        assert window._controller._service.engine_loaded is False
