"""图像预览控件（spec: main-window）：等比显示、自适应、滚轮缩放、拖动平移、接收拖放。

基于 QGraphicsView 实现：滚轮以光标为锚缩放；ScrollHandDrag 提供拖动
平移；载入新图与窗口尺寸变化时自适应完整显示；用户一旦手动缩放则不再
强制自适应（ZoomMode），直至载入新图重置。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ocrtool.utils.image import validate_dropped_urls


class ImageViewer(QGraphicsView):
    """预览区——只负责显示与查看，不参与识别流程。"""

    imageDropped = Signal(Path)  # 拖放校验通过的本地图像路径
    dropRejected = Signal(str)  # 拖放被拒（多文件/非图像）的提示文本

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = None
        self._adaptive = True  # 自适应模式：窗口变化时 fitInView

        self.setRenderHints(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setAcceptDrops(True)

    # ---- 图像 ----

    def set_image(self, image: QImage) -> None:
        from PySide6.QtGui import QPixmap

        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(QRectF(self._pixmap_item.pixmap().rect()))
        self._adaptive = True
        self.fit_to_view()

    def clear_image(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._adaptive = True

    def has_image(self) -> bool:
        return self._pixmap_item is not None

    # ---- 缩放与平移 ----

    def fit_to_view(self) -> None:
        if self._pixmap_item is None:
            return
        self._adaptive = True
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    @property
    def zoom_scale(self) -> float:
        """当前视图缩放倍数——等比性由单一 scale 保证，测试据此断言。"""
        return self.transform().m11()

    def _apply_zoom(self, factor: float, anchor: QPointF) -> None:
        if self._pixmap_item is None:
            return
        self._adaptive = False
        view_center = self.mapToScene(self.viewport().rect().center())
        self.scale(factor, factor)
        # 以指定锚点（如光标处场景坐标）为不动点修正平移
        delta = view_center - anchor
        self.translate(delta.x() * (1 - 1 / factor), delta.y() * (1 - 1 / factor))

    # ---- 事件 ----

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._pixmap_item is None:
            event.ignore()
            return
        steps = event.angleDelta().y() / 120
        factor = 1.2**steps
        anchor = self.mapToScene(event.position().toPoint())
        self._apply_zoom(factor, anchor)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._adaptive:
            self.fit_to_view()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        path = validate_dropped_urls(urls)
        if path is not None:
            self.imageDropped.emit(path)
        elif len(urls) > 1:
            self.dropRejected.emit("一次只能处理一张图像")
        else:
            self.dropRejected.emit("仅支持 PNG / JPG / JPEG / BMP / WEBP 图像文件")
        event.acceptProposedAction()
