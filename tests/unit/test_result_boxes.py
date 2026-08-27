"""result-box-overlay 测试：坐标还原、叠加绘制、视图变换、可见性生命周期、联动、性能。

验证样本（任务 0.2）均合成：
- 小尺寸图（不触发缩放，scale=1.0）
- 超过最大边长的大图（识别副本被等比缩小，scale<1.0）
- 含倾斜文本的图（box 四点非轴对齐）
- 数百行文本（性能样本，484 框）
- 深色与浅色背景图（描边对比度）
"""

from __future__ import annotations

import copy
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsSceneHoverEvent

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocrtool.config.defaults import BUILTIN_DEFAULTS
from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.ocr.result import OcrLine, OcrResult
from ocrtool.ui.main_window import MainWindow
from ocrtool.ui.widgets.image_viewer import (
    BOX_HIGHLIGHT_COLOR,
    BOX_PEN_COLOR,
    ImageViewer,
    polygons_from_result,
)
from ocrtool.ui.widgets.result_panel import ResultPanel

# ---- 样本构造 ----

# 倾斜四边形：绕 (50,50) 旋转的矩形（非轴对齐）
SKEWED_BOX = ((30.0, 30.0), (80.0, 20.0), (85.0, 60.0), (35.0, 70.0))

# 大图样本：识别副本被缩到一半（scale=0.5），box 处于缩小后坐标系
BIG_BOX_SCALED = ((10.0, 20.0), (210.0, 20.0), (210.0, 80.0), (10.0, 80.0))


def make_result(
    boxes=(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),),
    scale: float = 1.0,
) -> OcrResult:
    lines = tuple(OcrLine(text=f"第{i}行", score=0.9, box=box) for i, box in enumerate(boxes))
    return OcrResult(
        text="\n".join(line.text for line in lines),
        lines=lines,
        elapsed_ms=10.0,
        width=400,
        height=300,
        scale=scale,
    )


def solid_image(size: tuple[int, int], color: tuple[int, int, int]) -> QImage:
    """纯色合成图——深色/浅色背景样本（任务 3.3）。"""
    image = QImage(*size, QImage.Format.Format_RGB32)
    image.fill(QColor(*color))
    return image


def make_viewer(qapp, image_size=(400, 300), color=(255, 255, 255)) -> ImageViewer:
    viewer = ImageViewer()
    viewer.resize(500, 400)
    viewer.set_image(solid_image(image_size, color))
    viewer.show()
    qapp.processEvents()
    return viewer


def fire_hover(item, enter: bool) -> None:
    event = QGraphicsSceneHoverEvent(
        QEvent.Type.GraphicsSceneHoverEnter if enter else QEvent.Type.GraphicsSceneHoverLeave
    )
    pos = QPointF(0.0, 0.0)
    event.setScenePos(pos)
    event.setPos(pos)
    if enter:
        item.hoverEnterEvent(event)
    else:
        item.hoverLeaveEvent(event)


def render_viewer(viewer: ImageViewer) -> QImage:
    canvas = QImage(viewer.viewport().size(), QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    viewer.render(painter)
    painter.end()
    return canvas


def pixels_of_color(canvas: QImage, color: QColor, tolerance: int = 30) -> list[QPointF]:
    """收集画布上接近指定颜色的像素坐标（视口坐标）。"""
    found = []
    target = color.rgb() & 0xFFFFFF
    for y in range(canvas.height()):
        for x in range(canvas.width()):
            rgb = canvas.pixel(x, y) & 0xFFFFFF
            r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
            tr, tg, tb = (target >> 16) & 0xFF, (target >> 8) & 0xFF, target & 0xFF
            if (abs(r - tr) + abs(g - tg) + abs(b - tb)) <= tolerance:
                found.append(QPointF(x, y))
    return found


def has_pixel_near(pixels: list[QPointF], point: QPointF, radius: float = 3.0) -> bool:
    return any(
        abs(p.x() - point.x()) <= radius and abs(p.y() - point.y()) <= radius
        for p in pixels
    )


class DottedConfig:
    """ConfigManager 点路径替身：get/set/save，save 记录快照供断言。"""

    def __init__(self, values: dict) -> None:
        self._values = copy.deepcopy(values)
        self.snapshots: list[dict] = []

    def get(self, dotted_key: str, default=None):
        node = self._values
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted_key: str, value) -> None:
        parts = dotted_key.split(".")
        node = self._values
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def save(self) -> None:
        self.snapshots.append(copy.deepcopy(self._values))


class FakeService:
    model_name = "测试模型"

    def preload(self) -> None:  # pragma: no cover - 未用到的接口占位
        pass

    def recognize(self, image, *, scale: float = 1.0) -> OcrResult:  # pragma: no cover
        return make_result()


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
    from ocrtool.app import paths

    paths.initialize()
    controller = OcrController(FakeService())
    config = DottedConfig(
        {
            "ocr": {"model": "x", "max_edge_px": 6000},
            "runtime": {"cpu_threads": 4},
            "logging": {"level": "INFO"},
        }
    )
    win = MainWindow(controller, config, startup_warnings=[])
    win.resize(900, 600)
    yield win
    paths.reset_for_tests()


# ---- 1. 坐标还原与几何构建 ----


class TestPolygonsFromResult:
    def test_scale为1时小图坐标原样保留(self):
        box = ((10.0, 12.0), (110.0, 12.0), (110.0, 40.0), (10.0, 40.0))
        polygon = polygons_from_result(make_result([box]))[0]
        assert [polygon.at(i).toTuple() for i in range(4)] == [
            (10.0, 12.0), (110.0, 12.0), (110.0, 40.0), (10.0, 40.0),
        ]

    def test_scale小于1时除以scale还原大图坐标(self):
        # 识别副本缩到一半：box 在缩小坐标系，还原须整体放大 2 倍
        polygon = polygons_from_result(make_result([BIG_BOX_SCALED], scale=0.5))[0]
        points = [polygon.at(i).toTuple() for i in range(4)]
        assert points == [(20.0, 40.0), (420.0, 40.0), (420.0, 160.0), (20.0, 160.0)]

    def test_空结果返回空列表(self):
        assert polygons_from_result(
            OcrResult(text="", lines=(), elapsed_ms=1.0, width=10, height=10)
        ) == []


class TestGeometryBuild:
    def test_set_boxes一次性构建并缓存全部框(self, qapp):
        viewer = make_viewer(qapp)
        boxes = [
            ((f, 0.0), (f + 50, 0.0), (f + 50, 20.0), (f, 20.0))
            for f in (0.0, 60.0, 120.0)
        ]
        viewer.set_boxes(polygons_from_result(make_result(boxes)))
        assert viewer.box_count() == 3
        assert viewer.box_item(2).polygon().at(0).toTuple() == (120.0, 0.0)

    def test_小图框场景坐标与文本位置贴合(self, qapp):
        """1.3：小尺寸样本（scale=1.0）——框顶点即文本在原图中的位置。"""
        viewer = make_viewer(qapp)
        box = ((40.0, 30.0), (140.0, 30.0), (140.0, 52.0), (40.0, 52.0))
        viewer.set_boxes(polygons_from_result(make_result([box])))
        item = viewer.box_item(0)
        # 场景坐标 == 原始图像坐标：第一级还原正确
        assert [item.mapToScene(item.polygon().at(i)).toTuple() for i in range(4)] == [
            (40.0, 30.0), (140.0, 30.0), (140.0, 52.0), (40.0, 52.0),
        ]

    def test_倾斜文本框保持四边形顶点(self, qapp):
        """2.2：倾斜样本——框不退化为轴对齐矩形，四顶点逐点保留。"""
        viewer = make_viewer(qapp)
        viewer.set_boxes(polygons_from_result(make_result([SKEWED_BOX])))
        polygon = viewer.box_item(0).polygon()
        assert [polygon.at(i).toTuple() for i in range(4)] == list(SKEWED_BOX)
        # 非轴对齐性未被抹平
        assert polygon.at(0).y() != polygon.at(1).y()

    def test_set_boxes替换旧框不残留(self, qapp):
        viewer = make_viewer(qapp)
        viewer.set_boxes(polygons_from_result(make_result()))
        viewer.set_boxes(polygons_from_result(make_result([SKEWED_BOX])))
        assert viewer.box_count() == 1

    def test_None清除全部框(self, qapp):
        viewer = make_viewer(qapp)
        viewer.set_boxes(polygons_from_result(make_result()))
        viewer.set_boxes(None)
        assert viewer.box_count() == 0
        # 清除后场景中不再有框图形项
        from ocrtool.ui.widgets.image_viewer import _BoxGraphicsItem

        assert not any(
            isinstance(item, _BoxGraphicsItem) for item in viewer.scene().items()
        )


# ---- 2. 叠加绘制与视图变换 ----


class TestDevicePixelRatio:
    """截图捕获的图带着来源屏幕的 dpr —— 缩放屏幕下的识别框错位。

    既有贴合性用例全部以 dpr==1 的合成图构造，且只在场景坐标系内自比，
    对这一类缺陷结构性不可见：错的不是框的坐标，而是图像项在场景中的
    占位（size/dpr）。故此处一律对照 `_pixmap_item.boundingRect()`。
    """

    @pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
    def test_带dpr的图像在场景中仍按像素尺寸占位(self, qapp, dpr):
        viewer = ImageViewer()
        viewer.resize(500, 400)
        image = solid_image((900, 600), (255, 255, 255))
        image.setDevicePixelRatio(dpr)  # 缩放屏幕捕获所得
        viewer.set_image(image)
        viewer.show()
        qapp.processEvents()

        # 一个场景单位恒等于图像的一个像素，识别框才有共同坐标系
        assert viewer._pixmap_item.boundingRect().size().toTuple() == (900.0, 600.0)
        assert viewer._scene.sceneRect().size().toTuple() == (900.0, 600.0)

    @pytest.mark.parametrize("dpr", [1.25, 1.5, 2.0])
    def test_带dpr时贴边框不溢出图像(self, qapp, dpr):
        """未抹平 dpr 时，右下角的框会溢出图像 (dpr-1)×尺寸。"""
        viewer = ImageViewer()
        viewer.resize(500, 400)
        image = solid_image((900, 600), (255, 255, 255))
        image.setDevicePixelRatio(dpr)
        viewer.set_image(image)
        viewer.show()
        qapp.processEvents()

        box = ((800.0, 500.0), (880.0, 500.0), (880.0, 560.0), (800.0, 560.0))
        viewer.set_boxes(polygons_from_result(make_result([box])))
        item = viewer.box_item(0)
        image_rect = viewer._pixmap_item.boundingRect()
        for index in range(4):
            point = item.mapToScene(item.polygon().at(index))
            assert image_rect.contains(point), f"顶点{point.toTuple()}落在图像之外"


class TestOverlayDrawing:
    def test_框绘制在预览层之上且位置正确(self, qapp):
        """2.1：渲染级断言——描边像素出现在框顶点的视口位置处。"""
        viewer = make_viewer(qapp)
        viewer.set_boxes_visible(True)
        qapp.processEvents()
        box = ((50.0, 40.0), (150.0, 40.0), (150.0, 60.0), (50.0, 60.0))
        viewer.set_boxes(polygons_from_result(make_result([box])))
        canvas = render_viewer(viewer)

        pixels = pixels_of_color(canvas, BOX_PEN_COLOR)
        assert pixels, "识别框描边未绘制"
        # 框四个顶点（视口坐标）附近都应有描边像素
        for x, y in box:
            view_point = viewer.mapFromScene(QPointF(x, y))
            assert has_pixel_near(pixels, view_point), f"顶点({x},{y})处无描边"

    def test_缩放平移与调窗后框始终保持贴合(self, qapp):
        """2.3 + 2.4：大图样本 + 多档缩放 + 平移 + 调整窗口尺寸的组合场景。

        断言方式：框顶点的视口坐标（mapFromScene）与图像中同一点的
        视口坐标一致——两级变换叠加后无偏移、无错位。
        """
        viewer = make_viewer(qapp, image_size=(1200, 900))  # 超过视口的大图
        viewer.set_boxes(polygons_from_result(make_result([BIG_BOX_SCALED], scale=0.5)))
        corner = QPointF(20.0, 40.0)  # 还原后的框顶点（原始图像坐标）

        def assert_sticks():
            item_point = viewer.mapFromScene(viewer.box_item(0).polygon().at(0))
            image_point = viewer.mapFromScene(corner)
            assert (item_point - image_point).manhattanLength() < 0.001

        for factor in (0.5, 2.0, 4.0, 0.8):
            viewer._apply_zoom(factor, QPointF(300.0, 200.0))
            assert_sticks()
            viewer.translate(15.0, -10.0)
            assert_sticks()
        viewer.resize(700, 500)
        qapp.processEvents()
        assert_sticks()

    def test_图像像素数据不被修改(self, qapp):
        """2.5：叠加绘制只存在于呈现层，预览位图逐字节不变。"""
        viewer = make_viewer(qapp)
        before = viewer._pixmap_item.pixmap().toImage().copy()
        viewer.set_boxes_visible(True)
        viewer.set_boxes(polygons_from_result(make_result([SKEWED_BOX])))
        render_viewer(viewer)  # 实际走一次绘制路径
        after = viewer._pixmap_item.pixmap().toImage()
        assert before.size() == after.size()
        assert before.constBits() == after.constBits()


# ---- 3. 可见性与生命周期 ----


class TestVisibility:
    def test_配置默认关闭且两层默认值一致(self):
        assert BUILTIN_DEFAULTS["ui"]["show_boxes"] is False
        import json

        repo_default = json.loads(
            (Path(__file__).resolve().parents[2] / "config" / "default.json").read_text(
                encoding="utf-8"
            )
        )
        assert repo_default["ui"]["show_boxes"] is False

    def test_初始不可见_切换后可见并写配置(self, qapp):
        viewer = make_viewer(qapp)
        viewer.set_boxes(polygons_from_result(make_result()))
        assert viewer.boxes_visible is False
        assert not viewer.box_item(0).isVisible()

        viewer.set_boxes_visible(True)
        assert viewer.box_item(0).isVisible()

    def test_工具栏切换写入用户配置(self, qapp, window):
        assert window._boxes_action.isChecked() is False
        window._boxes_action.setChecked(True)
        qapp.processEvents()
        assert window._viewer.boxes_visible is True
        assert window._config.get("ui.show_boxes") is True
        assert window._config.snapshots, "切换后未持久化"
        assert window._config.snapshots[-1]["ui"]["show_boxes"] is True

    def test_重启后可见性状态保持(self, qapp, tmp_path, monkeypatch):
        """3.4：真 ConfigManager 三层合并——切换落盘，新窗口读回。"""
        monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
        from ocrtool.app import paths

        paths.initialize()
        from ocrtool.config.manager import load_config

        config = load_config()
        assert config.get("ui.show_boxes", None) is False  # 首运行生成默认（关闭）

        first = MainWindow(OcrController(FakeService()), config)
        first._boxes_action.setChecked(True)
        qapp.processEvents()

        reloaded = load_config()  # 模拟重启：从磁盘重新加载用户配置
        second = MainWindow(OcrController(FakeService()), reloaded)
        assert second._boxes_action.isChecked() is True
        assert second._viewer.boxes_visible is True
        paths.reset_for_tests()

    def test_深色与浅色背景上描边均清晰可辨(self, qapp):
        """3.3：纯黑/纯白样本渲染后，描边与背景的亮度差足够大。"""
        for color in ((0, 0, 0), (255, 255, 255)):
            viewer = make_viewer(qapp, color=color)
            viewer.set_boxes_visible(True)
            viewer.set_boxes(polygons_from_result(make_result([SKEWED_BOX])))
            canvas = render_viewer(viewer)
            pixels = pixels_of_color(canvas, BOX_PEN_COLOR)
            assert pixels, f"背景{color}上未检出描边"
            background_luma = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            stroke_luma = 0.299 * BOX_PEN_COLOR.red() + 0.587 * BOX_PEN_COLOR.green() + 0.114 * BOX_PEN_COLOR.blue()
            assert abs(stroke_luma - background_luma) > 80, (
                f"背景{color}上描边对比度不足"
            )

    def test_载入新图像清除位置框(self, qapp):
        viewer = make_viewer(qapp)
        viewer.set_boxes(polygons_from_result(make_result()))
        viewer.set_image(solid_image((200, 100), (10, 10, 10)))
        assert viewer.box_count() == 0

    def test_清空清除位置框(self, qapp, window):
        window._on_result_ready(make_result())
        assert window._viewer.box_count() > 0
        window.clear_all()
        assert window._viewer.box_count() == 0

    def test_识别失败清除位置框(self, qapp, window):
        from ocrtool.ocr.exceptions import RecognitionError

        window._on_result_ready(make_result())
        assert window._viewer.box_count() > 0
        window._on_error(RecognitionError("识别失败"))
        assert window._viewer.box_count() == 0

    def test_空结果不绘制框且不报错(self, qapp, window):
        window._on_result_ready(
            OcrResult(text="", lines=(), elapsed_ms=5.0, width=100, height=80)
        )
        assert window._viewer.box_count() == 0


# ---- 4. 联动 ----


class TestLinkage:
    def _arm(self, window):
        """置入带三行结果与三个横向排列框的窗口状态。"""
        boxes = [
            ((f, 100.0), (f + 40, 100.0), (f + 40, 130.0), (f, 130.0))
            for f in (20.0, 80.0, 140.0)
        ]
        result = make_result(boxes)
        window._on_result_ready(result)
        window._boxes_action.setChecked(True)
        return result

    def test_指向位置框高亮对应结果行(self, qapp, window):
        self._arm(window)
        fire_hover(window._viewer.box_item(1), enter=True)
        assert window._result_panel.highlighted_line() == 1

        fire_hover(window._viewer.box_item(1), enter=False)
        assert window._result_panel.highlighted_line() == -1

    def test_指向框后离开时高亮框复位(self, qapp, window):
        self._arm(window)
        item = window._viewer.box_item(2)
        fire_hover(item, enter=True)
        assert window._viewer.hovered_box() == 2
        fire_hover(item, enter=False)
        assert window._viewer.hovered_box() == -1
        # review 75-1：离开后 pen/brush 必须复位——框侧与文本侧高亮对称
        assert item.pen().color().rgb() == BOX_PEN_COLOR.rgb()
        assert item.brush().style() == Qt.BrushStyle.NoBrush
        assert window._viewer.highlighted_box() == -1
        assert window._result_panel.highlighted_line() == -1

    def test_选中结果行高亮对应位置框(self, qapp, window):
        self._arm(window)
        # 模拟点击第 2 行：光标移到该行触发 currentLineChanged
        cursor = window._result_panel._text_edit.textCursor()
        block = window._result_panel._text_edit.document().findBlockByNumber(2)
        cursor.setPosition(block.position())
        window._result_panel._text_edit.setTextCursor(cursor)
        qapp.processEvents()
        assert window._viewer.highlighted_box() == 2
        # 高亮样式生效（描边为高亮色）
        item = window._viewer.box_item(2)
        assert item.pen().color().rgb() == BOX_HIGHLIGHT_COLOR.rgb()

    def test_识别框隐藏时结果区行为与引入前一致(self, qapp, window):
        """4.3：隐藏状态下行选中/光标移动不产生任何额外表现。"""
        self._arm(window)
        window._boxes_action.setChecked(False)  # 隐藏
        cursor = window._result_panel._text_edit.textCursor()
        block = window._result_panel._text_edit.document().findBlockByNumber(1)
        cursor.setPosition(block.position())
        window._result_panel._text_edit.setTextCursor(cursor)
        qapp.processEvents()
        # 状态可更新但全部框保持不可见——无视觉副作用、不报错
        assert window._viewer.boxes_visible is False
        assert all(
            not window._viewer.box_item(i).isVisible() for i in range(3)
        )
        assert window._result_panel.text == "第0行\n第1行\n第2行"

    def test_重叠框指向取最靠上的一个(self, qapp, window):
        """4.4：两框部分重叠，指向重叠区应命中视觉最上层（后绘制者）。"""
        boxes = [
            ((20.0, 20.0), (120.0, 20.0), (120.0, 70.0), (20.0, 70.0)),
            ((80.0, 40.0), (180.0, 40.0), (180.0, 90.0), (80.0, 90.0)),
        ]
        window._on_result_ready(make_result(boxes))
        window._boxes_action.setChecked(True)

        # 重叠区内取一点：场景坐标 (100, 55)
        top = window._viewer.scene().itemAt(QPointF(100.0, 55.0), QTransform())
        assert top is not None
        assert top.index == 1  # 后加入（视觉在上）的框
        fire_hover(top, enter=True)
        assert window._result_panel.highlighted_line() == 1
        fire_hover(top, enter=False)

    def test_结果行为超界高亮安全忽略(self, qapp):
        panel = ResultPanel()
        panel.set_result("a\nb")
        panel.highlight_line(5)  # 超界：等价清除，不抛
        assert panel.highlighted_line() == -1
        panel.highlight_line(-1)
        assert panel.highlighted_line() == -1


# ---- review.md 修复回归（75-1/75-2/50-1/50-2/50-4）----


class TestReviewFixes:
    def test_再次识别后旧行高亮被清除(self, qapp, window):
        """review 75-2：鼠标停在框上（高亮保持）时再次识别，旧行高亮不得
        残留漂移——review 实测 setPlainText 不清 extraSelections，旧行
        QTextCursor 被 clamp 到新文档。"""
        TestLinkage()._arm(window)
        fire_hover(window._viewer.box_item(1), enter=True)
        assert window._result_panel.highlighted_line() == 1

        # hover 保持进入状态，经 Ctrl+R / 粘贴 / 截图流再次识别
        window._on_result_ready(make_result([
            ((f, 100.0), (f + 40, 100.0), (f + 40, 130.0), (f, 130.0))
            for f in (20.0, 80.0, 140.0)
        ]))
        assert window._result_panel.highlighted_line() == -1

    def test_clear_all后联动索引不泄漏(self, qapp, window):
        """review 50-1：clear() 的程序性光标复位不得把联动索引改写为 0。"""
        TestLinkage()._arm(window)
        assert window._viewer.highlighted_box() in (-1, 0, 1, 2)
        window.clear_all()
        # 全复位契约：无结果、无框、无联动
        assert window._viewer.box_count() == 0
        assert window._viewer.highlighted_box() == -1

    def test_识别失败后行高亮被清除(self, qapp, window):
        """review 50-2：错误路径清框的同时清除文本行高亮，不留孤儿。"""
        TestLinkage()._arm(window)
        window._result_panel.highlight_line(1)
        assert window._result_panel.highlighted_line() == 1
        from ocrtool.ocr.exceptions import RecognitionError

        window._on_error(RecognitionError("识别失败"))
        assert window._viewer.box_count() == 0
        assert window._result_panel.highlighted_line() == -1

    def test_识别完成后联动状态无残留(self, qapp, window):
        """review 50-4：新结果到达后框 0 不得因 set_result 的程序性信号恒高亮。"""
        TestLinkage()._arm(window)
        window._on_result_ready(make_result([
            ((f, 100.0), (f + 40, 100.0), (f + 40, 130.0), (f, 130.0))
            for f in (20.0, 80.0, 140.0)
        ]))
        assert window._viewer.highlighted_box() == -1
        for i in range(3):
            item = window._viewer.box_item(i)
            assert item.pen().color().rgb() == BOX_PEN_COLOR.rgb(), f"框{i}被程序性信号点亮"

    def test_用户选中的行高亮不被hover离开误清(self, qapp, window):
        """修复方案的语义约束：hover 离开只清 hover 侧高亮，
        用户主动选中的行（currentLineChanged 正当来源）保持联动。"""
        TestLinkage()._arm(window)
        # 用户点击第 1 行（正当来源）
        cursor = window._result_panel._text_edit.textCursor()
        block = window._result_panel._text_edit.document().findBlockByNumber(1)
        cursor.setPosition(block.position())
        window._result_panel._text_edit.setTextCursor(cursor)
        qapp.processEvents()
        assert window._viewer.highlighted_box() == 1

        # 扫过框 2 再离开——用户选中的框 1 联动不得被误清
        fire_hover(window._viewer.box_item(2), enter=True)
        qapp.processEvents()
        fire_hover(window._viewer.box_item(2), enter=False)
        qapp.processEvents()
        assert window._viewer.highlighted_box() == 1
        assert window._viewer.box_item(1).pen().color().rgb() == BOX_HIGHLIGHT_COLOR.rgb()


# ---- 5. 性能 ----


class TestPerformance:
    def test_数百框连续缩放平移保持流畅(self, qapp):
        """5.1：484 框样本，连续缩放+平移+渲染；几何缓存不重建、单帧耗时有上限。"""
        viewer = make_viewer(qapp, image_size=(1200, 900))
        boxes = [
            ((x, y), (x + 60, y), (x + 60, y + 18), (x, y + 18))
            for y in range(0, 880, 20)
            for x in range(0, 1100, 100)
        ]
        assert len(boxes) == 484  # 44 行 × 11 列，满足「数百行」样本
        viewer.set_boxes(polygons_from_result(make_result(boxes)))
        viewer.set_boxes_visible(True)

        start = time.perf_counter()
        rounds = 40
        for i in range(rounds):
            viewer._apply_zoom(1.05 if i % 2 == 0 else 1 / 1.05, QPointF(250.0, 200.0))
            viewer.translate(6.0, 4.0)
            render_viewer(viewer)
        elapsed = time.perf_counter() - start

        assert viewer.box_count() == 484  # 变换不重建几何（design D6）
        assert elapsed / rounds < 0.1, f"平均单帧 {elapsed / rounds * 1000:.1f}ms，超出流畅门限"
