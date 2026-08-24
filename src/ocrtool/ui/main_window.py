"""主窗口（spec: main-window）——工具栏、区域布局与事件接线。

依赖注入 OcrController 与配置（spec: main-window）：窗口只消费控制器，
绝不自行创建服务实例（架构边界：UI 禁止直接调用 OCR 引擎）。
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QToolBar,
    QToolButton,
    QWidget,
)

from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.main import window_title
from ocrtool.ocr.exceptions import InvalidImageError, ModelLoadError, ModelMissingError
from ocrtool.ocr.states import OcrState
from ocrtool.ui.widgets.image_viewer import ImageViewer, polygons_from_result
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
        # 当前展示结果的产出模型（design D5）：None = 无结果在展示，
        # 状态区模型段此时跟随当前引擎模型；有结果时跟随该结果
        self._result_model_name: str | None = None
        # 进行中的截图流程（选区期间保持引用，防止回收）
        self._capture_flow = None

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

        self._capture_action = toolbar.addAction("截图识别")
        self._capture_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._capture_action.triggered.connect(self.start_region_capture)
        self.addAction(self._capture_action)

        self._recognize_action = toolbar.addAction("识别")
        self._recognize_action.setShortcut(QKeySequence("Ctrl+R"))
        self._recognize_action.triggered.connect(self.start_recognition)
        self.addAction(self._recognize_action)

        # 识别框可见性（spec: main-window）：默认关闭，切换即持久化（design D5）
        self._boxes_action = toolbar.addAction("识别框")
        self._boxes_action.setCheckable(True)
        self._boxes_action.setChecked(bool(self._config.get("ui.show_boxes", False)))
        self._boxes_action.toggled.connect(self._toggle_boxes)

        # 模型选择入口（spec: main-window 模型选择入口）：菜单每次呈现前
        # 重新扫描模型目录（design D4），当前模型打勾标示
        self._model_menu = QMenu(self)
        self._model_menu.aboutToShow.connect(self._rebuild_model_menu)
        self._model_button = QToolButton()
        self._model_button.setText("模型")
        self._model_button.setToolTip("选择识别模型")
        self._model_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._model_button.setMenu(self._model_menu)
        toolbar.addWidget(self._model_button)

        self._copy_action = toolbar.addAction("复制全部")
        self._copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self._copy_action.triggered.connect(self._result_panel.copy_all)
        self.addAction(self._copy_action)

        self._clear_action = toolbar.addAction("清空")
        self._clear_action.triggered.connect(self.clear_all)

        # 注意：粘贴快捷键只由 _paste_action（StandardKey.Paste）承担。
        # 不得再叠加独立 QShortcut——同键序列双注册会被 Qt 判为 ambiguous
        # overload，两条都不触发（review 100-1），且独立 QShortcut 不受
        # busy 期禁用控制。

        self._viewer.imageDropped.connect(self.load_from_path)
        self._viewer.dropRejected.connect(self._notify_status)
        self._viewer.boxHovered.connect(self._on_box_hover)
        self._result_panel.statusMessage.connect(self._notify_status)
        self._result_panel.currentLineChanged.connect(self._viewer.set_highlighted_box)
        self._viewer.set_boxes_visible(self._boxes_action.isChecked())

    def _wire_controller(self) -> None:
        self._controller.stateChanged.connect(self._on_state_changed)
        self._controller.busyChanged.connect(self._on_busy_changed)
        self._controller.resultReady.connect(self._on_result_ready)
        self._controller.errorOccurred.connect(self._on_error)
        self._controller.modelSwitched.connect(self._on_model_switched)
        self._controller.modelSwitchFailed.connect(self._on_model_switch_failed)
        self._on_busy_changed(False)

    # ---- 启动自检（spec: main-window：只查存在性，不加载模型）----

    def _run_startup_self_check(self, config_warnings: list[str]) -> None:
        from ocrtool.app import paths
        from ocrtool.ocr import model_manager

        problems: list[str] = list(config_warnings)
        model = model_manager.resolve_model(paths.model_dir(), self._config.get("ocr.model"))
        if model is None:
            problems.append("模型文件缺失，识别功能不可用，请恢复程序目录后重试")
        if problems:
            for problem in problems:
                logger.error("启动自检：%s", problem)
            self._status.set_state("自检发现问题")
            self._notify_status("；".join(problems))

    # ---- 图像载入（四种输入共用管线，design D8；截图入口见下方独立段）----

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
        """文件选择与拖放共用的载入入口；拒绝时当前图像保持不变。

        识别进行中忽略载入（review 75-3）：识别中换图会使旧请求的结果
        配到新预览上——token 只随识别递增，换图不识别无法作废旧回调。
        """
        if self._controller.busy:
            self._notify_status("识别进行中，请等待完成后更换图像")
            return
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

    # ---- 截图识别（spec: screen-capture，第四种输入）----

    def start_region_capture(self) -> None:
        """截图识别入口：隐藏主窗口 → 冻结帧框选 → 裁剪 → 自动识别。"""
        if self._controller.busy:
            return  # 入口已禁用，双保险（spec: main-window 识别进行中入口不可用）
        if self._capture_flow is not None and self._capture_flow.active:
            return  # 选区进行中不允许重入
        from ocrtool.capture.region_overlay import RegionCaptureFlow

        flow = RegionCaptureFlow(self)
        flow.finished.connect(self._on_capture_finished)
        flow.cancelled.connect(lambda: self._notify_status("已取消截图"))
        flow.failed.connect(self._on_capture_failed)
        self._capture_flow = flow
        flow.start(self)

    def _on_capture_finished(self, image) -> None:
        """捕获图像与粘贴同路（已是内存 QImage，跳过文件格式校验），
        完成后自动发起识别——截图是唯一自动触发识别的输入（design D7）。"""
        if self._controller.busy:
            self._notify_status("识别进行中，截图结果已丢弃")
            return
        bgr = qimage_to_bgr(image)
        scaled, scale = scale_to_limit(bgr, self._max_edge)
        self._set_current_image(image, scaled, scale)
        self.start_recognition()

    def _on_capture_failed(self, message: str) -> None:
        # 捕获失败是可读提示而非需介入错误（spec: screen-capture）
        self._notify_status(message)

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
        # 切换期间不清运行信息——旧结果（含耗时/行数）保持原样展示
        # （design D5：不得让用户误以为结果与新模型有关）；识别开始才清
        if busy and not self._controller.switching:
            self._status.clear_run_info()

    def _update_actions(self) -> None:
        """识别期间禁用触发入口（spec: ocr-execution）；识别入口还需已有图像。

        模型入口与识别入口同规则禁用（spec: main-window 识别或切换进行中
        模型选择入口不可用）。
        """
        busy = self._controller.busy
        self._open_action.setEnabled(not busy)
        self._paste_action.setEnabled(not busy)
        self._capture_action.setEnabled(not busy)
        self._clear_action.setEnabled(not busy)
        self._model_button.setEnabled(not busy)
        self._recognize_action.setEnabled(
            not busy and self._pending_image is not None
        )

    def _on_state_changed(self, state: OcrState) -> None:
        # IDLE 不改写状态文本：瞬时终态（完成/空结果/失败）的反馈需驻留
        # 到用户下一次操作（spec: main-window「识别完成后显示完成状态」）
        if state is OcrState.IDLE:
            return
        self._status.set_state(STATE_TEXTS[state])

    # ---- 识别框（spec: main-window 识别框绘制与联动）----

    def _toggle_boxes(self, visible: bool) -> None:
        """切换识别框可见性并写入用户配置（状态持久化）。"""
        self._viewer.set_boxes_visible(visible)
        self._config.set("ui.show_boxes", visible)
        self._config.save()

    def _on_box_hover(self, index: int) -> None:
        """指向位置框 → 高亮对应结果行；离开 → 清除高亮。"""
        if index >= 0:
            self._result_panel.highlight_line(index)
        else:
            self._result_panel.clear_highlight()

    # ---- 模型切换（spec: main-window 模型选择入口 / 结果标明产出模型）----

    def _rebuild_model_menu(self) -> None:
        """菜单呈现前重建（design D4）：重新扫描模型目录，放入新模型立即可见。"""
        from ocrtool.app import paths
        from ocrtool.ocr import model_manager

        self._model_menu.clear()
        models = model_manager.available_models(paths.model_dir())
        if not models:
            empty = self._model_menu.addAction("无可用模型")
            empty.setEnabled(False)
            return
        current_id = self._controller.model_id
        group = QActionGroup(self._model_menu)
        group.setExclusive(True)
        for info in models:
            action = group.addAction(info.name)
            action.setCheckable(True)
            action.setChecked(info.model_id == current_id)
            action.triggered.connect(
                lambda checked=False, target=info: self._request_model_switch(target)
            )
            self._model_menu.addAction(action)

    def _request_model_switch(self, info) -> None:
        """菜单选择 → 请求切换。入口已随 busy 禁用，此处再查是双保险。"""
        if self._controller.busy or self._controller.switching:
            self._notify_status("识别或切换进行中，暂不能切换模型")
            return
        if info.model_id == self._controller.model_id:
            return  # 当前模型：直接视为无操作（spec: ocr-engine）
        self._controller.switch_model(info)

    def _on_model_switched(self, model_id: str, model_name: str) -> None:
        """切换生效：仅成功才写配置（design D6）；模型标注按是否有结果
        在展示决定——旧结果的产出模型标注不被覆盖（design D5）。"""
        self._config.set("ocr.model", model_id)
        self._config.save()
        if self._result_model_name is None:
            self._status.set_model(model_name)
        self._notify_status(f"模型已切换：{model_name}")

    def _on_model_switch_failed(self, error) -> None:
        """切换未生效：可读提示（error.message 不含技术细节），细节已入日志。"""
        QMessageBox.warning(self, "OCRTool", error.message)

    def _on_result_ready(self, result) -> None:
        self._result_panel.set_result(result.text)
        # 位置框几何在此一次性还原（÷ scale）并缓存（design D1/D6）；
        # 空结果得到空列表，等价于清除
        self._viewer.set_boxes(polygons_from_result(result))
        # 状态区模型段 = 本结果的产出模型（design D5）；旧版结果可能缺字段则回退当前引擎
        self._result_model_name = result.model_name or None
        self._status.set_model(result.model_name or self._controller.model_name)
        self._status.set_timing(result.elapsed_ms)
        self._status.set_lines(result.line_count)
        # 自动复制仅在「成功且检出文本」时写剪贴板（design D5）：
        # 空结果/失败写入空串等于清空用户剪贴板原有内容
        if result.text.strip() and self._config.get("ui.auto_copy", True):
            from ocrtool.utils.clipboard import set_clipboard_text

            set_clipboard_text(result.text)
            self._notify_status("识别结果已自动复制到剪贴板")

    def _on_error(self, error) -> None:
        """错误分级（spec: main-window）：需介入 → 对话框；普通反馈 → 状态区。

        识别失败同时清除上一次的位置框——结果与框同生命周期，不允许
        旧框与新错误状态并存（spec: main-window 识别框随结果一并清除）；
        文本行高亮同步清除，不留指向已清空联动的孤儿（review 50-2）。
        """
        self._viewer.set_boxes(None)
        self._result_panel.clear_highlight()
        self._result_model_name = None
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
        self._result_model_name = None
        self._update_actions()
        self._status.set_model(self._controller.model_name)
        self._status.set_state(STATE_TEXTS[OcrState.IDLE])
        self._status.clear_run_info()
