"""图像预览控件（spec: main-window）：等比显示、自适应、滚轮缩放、拖动平移、接收拖放、识别框叠加。

基于 QGraphicsView 实现：滚轮以光标为锚缩放；ScrollHandDrag 提供拖动
平移；载入新图与窗口尺寸变化时自适应完整显示；用户一旦手动缩放则不再
强制自适应（ZoomMode），直至载入新图重置。

识别框（result-box-overlay）以场景图形项叠加：场景坐标即原始图像坐标，
识别时一次性完成「box ÷ scale」第一级还原（design D1）并构建图形项缓存
（design D6）；此后视图的第二级缩放/平移由 QGraphicsView 机制天然施加，
无需任何手工换算，也就不存在会漏掉一级变换的重绘路径。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsView,
)

from ocrtool.utils.image import validate_dropped_urls

if TYPE_CHECKING:
    from ocrtool.ocr.result import OcrResult

# 框描边用高亮绿 + cosmetic pen（宽度以视口像素计，不随缩放变粗变细），
# 亮绿在纯黑与纯白背景上的亮度都与背景拉开足够距离（任务 3.3 验证）
BOX_PEN_COLOR = QColor(0x00, 0xE6, 0x76)
BOX_PEN = QPen(BOX_PEN_COLOR, 2)
BOX_PEN.setCosmetic(True)
BOX_HIGHLIGHT_COLOR = QColor(0xFF, 0x9A, 0x00)
BOX_HIGHLIGHT_PEN = QPen(BOX_HIGHLIGHT_COLOR, 3)
BOX_HIGHLIGHT_PEN.setCosmetic(True)
BOX_HIGHLIGHT_FILL = QColor(0xFF, 0x9A, 0x00, 60)


def polygons_from_result(result: OcrResult) -> list[QPolygonF]:
    """位置框两级还原的第一级：box ÷ scale → 原始图像坐标四边形。

    box 处于「送入识别的图像」坐标系（大图被等比缩小后识别时小于原始
    尺寸）；本函数在识别完成时执行一次（design D1），返回值即场景坐标
    ——第二级（视图缩放/平移）由 QGraphicsView 施加于场景整体，框架代偿。
    """
    scale = result.scale if result.scale else 1.0
    return [
        QPolygonF([QPointF(x / scale, y / scale) for x, y in line.box])
        for line in result.lines
    ]


class _BoxGraphicsItem(QGraphicsPolygonItem):
    """单个位置框：携带行索引，hover 进出经回调上报驱动联动。"""

    def __init__(self, index: int, polygon: QPolygonF, on_hover, parent=None) -> None:
        super().__init__(polygon, parent)
        self._index = index
        self._on_hover = on_hover
        self.setAcceptHoverEvents(True)

    @property
    def index(self) -> int:
        return self._index

    def hoverEnterEvent(self, event) -> None:
        self._on_hover(self._index, True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._on_hover(self._index, False)
        super().hoverLeaveEvent(event)


class ImageViewer(QGraphicsView):
    """预览区——只负责显示与查看，不参与识别流程。"""

    imageDropped = Signal(Path)  # 拖放校验通过的本地图像路径
    dropRejected = Signal(str)  # 拖放被拒（多文件/非图像）的提示文本
    boxHovered = Signal(int)  # 指向的位置框行索引；-1 表示离开（联动用）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = None
        self._adaptive = True  # 自适应模式：窗口变化时 fitInView

        # 位置框状态：图形项列表 + 可见性 + 两个高亮来源（hover / 文本行联动）
        self._box_items: list[_BoxGraphicsItem] = []
        self._boxes_visible = False
        self._hovered_box = -1
        self._linked_box = -1

        self.setRenderHints(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setAcceptDrops(True)

    # ---- 图像 ----

    def set_image(self, image: QImage) -> None:
        from PySide6.QtGui import QPixmap

        self._scene.clear()  # 连带销毁位置框图形项（C++ 侧已析构）
        self._reset_box_state()
        self._pixmap_item = self._scene.addPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(QRectF(self._pixmap_item.pixmap().rect()))
        self._adaptive = True
        self.fit_to_view()

    def clear_image(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._adaptive = True
        self._reset_box_state()

    def has_image(self) -> bool:
        return self._pixmap_item is not None

    # ---- 识别框（spec: main-window 识别框绘制）----

    def set_boxes(self, polygons: list[QPolygonF] | None) -> None:
        """替换全部位置框（原始图像坐标即场景坐标）；None/空即清除。

        几何在此一次性构建为图形项并缓存（design D6）——此后重绘只做
        变换与绘制，不再回读识别结果结构。
        """
        self._discard_box_items()
        if not polygons:
            return
        for index, polygon in enumerate(polygons):
            item = _BoxGraphicsItem(index, polygon, self._handle_box_hover)
            item.setZValue(1.0)  # 画在预览层（pixmap，z=0）之上（design D2）
            item.setVisible(self._boxes_visible)
            self._apply_box_style(item)
            self._scene.addItem(item)
            self._box_items.append(item)

    def set_boxes_visible(self, visible: bool) -> None:
        if visible == self._boxes_visible:
            return
        self._boxes_visible = visible
        for item in self._box_items:
            item.setVisible(visible)

    @property
    def boxes_visible(self) -> bool:
        return self._boxes_visible

    def box_count(self) -> int:
        return len(self._box_items)

    def box_item(self, index: int) -> _BoxGraphicsItem:
        """测试/联动用：按行索引取图形项。"""
        return self._box_items[index]

    def set_highlighted_box(self, index: int) -> None:
        """文本行联动高亮指定框；-1 清除（与 hover 高亮相互独立）。"""
        if index == self._linked_box:
            return
        self._linked_box = index
        for item in self._box_items:
            self._apply_box_style(item)

    def highlighted_box(self) -> int:
        return self._linked_box

    def hovered_box(self) -> int:
        return self._hovered_box

    def _handle_box_hover(self, index: int, entered: bool) -> None:
        if not self._boxes_visible:
            return  # 不可见项本就不收 hover，双保险
        if entered and self._hovered_box != index:
            self._hovered_box = index
        elif not entered and self._hovered_box == index:
            self._hovered_box = -1
        else:
            return
        for item in self._box_items:
            self._apply_box_style(item)
        self.boxHovered.emit(self._hovered_box)

    def _apply_box_style(self, item: _BoxGraphicsItem) -> None:
        if item.index in (self._hovered_box, self._linked_box):
            item.setPen(BOX_HIGHLIGHT_PEN)
            item.setBrush(BOX_HIGHLIGHT_FILL)
        else:
            item.setPen(BOX_PEN)
            item.setBrush(Qt.BrushStyle.NoBrush)

    def _discard_box_items(self) -> None:
        self._reset_box_state()
        for item in list(self._scene.items()):
            if isinstance(item, _BoxGraphicsItem):
                self._scene.removeItem(item)

    def _reset_box_state(self) -> None:
        self._box_items = []
        self._hovered_box = -1
        self._linked_box = -1

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
