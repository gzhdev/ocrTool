"""主窗口（spec: main-window）——工具栏、区域布局与事件接线。

依赖注入 OcrController 与配置（spec: main-window）：窗口只消费控制器，
绝不自行创建服务实例（架构边界：UI 禁止直接调用 OCR 引擎）。
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
    QWidget,
)

from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.main import window_title
from ocrtool.ocr.exceptions import InvalidImageError, ModelLoadError, ModelMissingError
from ocrtool.ocr.states import OcrState
from ocrtool.ui.widgets.image_viewer import ImageViewer
from ocrtool.ui.widgets.result_panel import ResultPanel
from ocrtool.ui.widgets.status_widget import StatusWidget
from ocrtool.utils.image import load_for_recognition, qimage_to_bgr, scale_to_limit

logger = logging.getLogger("ocrtool.ui")

STATE_TEXTS = {
    OcrState.IDLE: "就绪",
    OcrState.LOADING: "正在加载模型…",
    OcrState.RECOGNIZING: "识别中…",
    OcrState.SUCCESS: "完成",
    OcrState.EMPTY: "未识别到文本",
    OcrState.ERROR: "识别失败",
}


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: OcrController,
        config,
        startup_warnings: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._config = config
        self._max_edge = int(config.get("ocr.max_edge_px", 6000))

        # 当前图像：预览用原图与识别用（可能缩放的）副本分离（design D7）
        self._pending_image: np.ndarray | None = None
        self._pending_scale: float = 1.0

        self.setWindowTitle(window_title())
        self.resize(1000, 680)
        self._build_ui()
        self._wire_controller()
        self._run_startup_self_check(startup_warnings or [])

    # ---- 组装 ----

    def _build_ui(self) -> None:
        self._viewer = ImageViewer()
        self._result_panel = ResultPanel()
        self._status = StatusWidget()
        self._status.set_model(self._controller.model_name)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._viewer)
        splitter.addWidget(self._result_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.statusBar().addWidget(self._status)

        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._open_action = toolbar.addAction("打开图像")
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)
        self._open_action.triggered.connect(self.open_file_dialog)
        self.addAction(self._open_action)

        self._paste_action = toolbar.addAction("粘贴图像")
        self._paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self._paste_action.triggered.connect(self.load_from_clipboard)
        self.addAction(self._paste_action)

        self._recognize_action = toolbar.addAction("识别")
        self._recognize_action.setShortcut(QKeySequence("Ctrl+R"))
        self._recognize_action.triggered.connect(self.start_recognition)
        self.addAction(self._recognize_action)

        self._copy_action = toolbar.addAction("复制全部")
        self._copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self._copy_action.triggered.connect(self._result_panel.copy_all)
        self.addAction(self._copy_action)

        self._clear_action = toolbar.addAction("清空")
        self._clear_action.triggered.connect(self.clear_all)

        QShortcut(QKeySequence("Ctrl+V"), self).activated.connect(
            self.load_from_clipboard
        )

        self._viewer.imageDropped.connect(self.load_from_path)
        self._viewer.dropRejected.connect(self._notify_status)
        self._result_panel.statusMessage.connect(self._notify_status)

    def _wire_controller(self) -> None:
        self._controller.stateChanged.connect(self._on_state_changed)
        self._controller.busyChanged.connect(self._on_busy_changed)
        self._controller.resultReady.connect(self._on_result_ready)
        self._controller.errorOccurred.connect(self._on_error)
        self._on_busy_changed(False)

    # ---- 启动自检（spec: main-window：只查存在性，不加载模型）----

    def _run_startup_self_check(self, config_warnings: list[str]) -> None:
        from ocrtool.ocr import model_manager
        from ocrtool.app import paths

        problems: list[str] = list(config_warnings)
        model = model_manager.resolve_model(paths.model_dir(), self._config.get("ocr.model"))
        if model is None:
            problems.append("模型文件缺失，识别功能不可用，请恢复程序目录后重试")
        if problems:
            for problem in problems:
                logger.error("启动自检：%s", problem)
            self._status.set_state("自检发现问题")
            self._notify_status("；".join(problems))

    # ---- 图像载入（三种输入共用管线，design D8）----

    def open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图像",
            "",
            "图像文件 (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if path:
            self.load_from_path(path)

    def load_from_path(self, path) -> None:
        """文件选择与拖放共用的载入入口；拒绝时当前图像保持不变。"""
        try:
            original, scaled, scale = load_for_recognition(path, self._max_edge)
        except InvalidImageError as error:
            self._notify_status(error.message)  # 普通反馈：状态区，不弹窗
            return
        self._set_current_image(original, scaled, scale)

    def load_from_clipboard(self) -> None:
        from ocrtool.utils.clipboard import clipboard_image

        image = clipboard_image()
        if image is None:
            self._notify_status("剪贴板中没有图像")
            return
        bgr = qimage_to_bgr(image)
        scaled, scale = scale_to_limit(bgr, self._max_edge)
        self._set_current_image(image, scaled, scale)

    def _set_current_image(self, original, scaled: np.ndarray, scale: float) -> None:
        self._viewer.set_image(original)
        self._pending_image = scaled
        self._pending_scale = scale
        self._update_actions()
        self._status.set_state("已载入图像")

    # ---- 识别 ----

    def start_recognition(self) -> None:
        if self._pending_image is None:
            self._notify_status("请先载入一张图像")
            return
        if not self._controller.start_recognition(
            self._pending_image, scale=self._pending_scale
        ):
            return  # busy：重入被拒，无副作用

    # ---- 控制器回调 ----

    def _on_busy_changed(self, busy: bool) -> None:
        self._update_actions()
        if busy:
            self._status.clear_run_info()

    def _update_actions(self) -> None:
        """识别期间禁用触发入口（spec: ocr-execution）；识别入口还需已有图像。"""
        busy = self._controller.busy
        self._open_action.setEnabled(not busy)
        self._paste_action.setEnabled(not busy)
        self._clear_action.setEnabled(not busy)
        self._recognize_action.setEnabled(
            not busy and self._pending_image is not None
        )

    def _on_state_changed(self, state: OcrState) -> None:
        # IDLE 不改写状态文本：瞬时终态（完成/空结果/失败）的反馈需驻留
        # 到用户下一次操作（spec: main-window「识别完成后显示完成状态」）
        if state is OcrState.IDLE:
            return
        self._status.set_state(STATE_TEXTS[state])

    def _on_result_ready(self, result) -> None:
        self._result_panel.set_result(result.text)
        self._status.set_timing(result.elapsed_ms)
        self._status.set_lines(result.line_count)

    def _on_error(self, error) -> None:
        """错误分级（spec: main-window）：需介入 → 对话框；普通反馈 → 状态区。"""
        if isinstance(error, (ModelMissingError, ModelLoadError)):
            self._show_critical_error(error.message)
        else:
            self._notify_status(error.message)

    def _show_critical_error(self, message: str) -> None:
        """需用户介入的错误——模态对话框呈现可读说明，细节只在日志。"""
        QMessageBox.critical(self, "OCRTool", message)

    def _notify_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    # ---- 清空 ----

    def clear_all(self) -> None:
        """预览与结果同时清空，状态回空闲（spec: main-window）。"""
        self._viewer.clear_image()
        self._result_panel.clear()
        self._pending_image = None
        self._pending_scale = 1.0
        self._update_actions()
        self._status.set_state(STATE_TEXTS[OcrState.IDLE])
        self._status.clear_run_info()
