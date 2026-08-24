# 任务：识别框绘制

## 0. 前置确认

- [x] 0.1 确认 `mvp-image-ocr` 已完成，`OCRResult.scale` 与 `OCRLine.box` 可正常取到
  - 核实于 `src/ocrtool/ocr/result.py`：`OcrLine.box` 为四点元组（缩放后坐标系），
    `OcrResult.scale` 默认 1.0，docstring 已写明「识别框绘制时须除以 scale 还原」。
- [x] 0.2 准备验证样本：一张小尺寸图（不触发缩放）、一张超过最大边长的大图、一张含倾斜文本的图、一张数百行文本的图、一张深色背景图
  - 全部在 `tests/unit/test_result_boxes.py` 合成：小图（scale=1.0）、大图
    （1200×900 + scale=0.5 的 BIG_BOX_SCALED）、倾斜四边形 SKEWED_BOX、
    数百行（44×11=484 框）、纯黑/纯白纯色图（`solid_image`）。

## 1. 坐标还原与几何构建

- [x] 1.1 实现「box ÷ scale」还原到原始图像坐标系
  - `image_viewer.py` 模块级 `polygons_from_result(result)`：四点逐坐标除以
    scale 返回 QPolygonF。测试：scale=1 原样保留；scale=0.5 整体 ×2 还原
    （`test_scale小于1时除以scale还原大图坐标`）。
- [x] 1.2 实现识别完成时一次性构建并缓存全部框的几何数据
  - `ImageViewer.set_boxes()` 在结果到达时一次性创建 `_BoxGraphicsItem` 列表
    并缓存（design D6）；性能测试断言连续 40 轮缩放平移后 `box_count()` 不变
    （几何不重建）。
- [x] 1.3 用小尺寸样本验证：框与文本贴合
  - `test_小图框场景坐标与文本位置贴合`：item 场景坐标逐点等于 box 期望值。
- [x] 1.4 用大图样本验证：`scale` 不为 1.0 时框仍贴合，无整体偏移或整体缩放错误
  - `test_scale小于1时除以scale还原大图坐标` + `test_缩放平移与调窗后框始终保持贴合`
    （大图 1200×900，scale=0.5，多档缩放 ×0.5/×2/×4/×0.8 + 平移 + resize，
    每步断言框顶点视口坐标与图像同一点视口坐标一致）。

## 2. 叠加绘制与视图变换

- [x] 2.1 实现在预览层之上叠加绘制，按四个角点绘制四边形
  - 框为 `_BoxGraphicsItem(QGraphicsPolygonItem)`，z=1（pixmap z=0），按
    `QPolygonF` 四角点绘制四边形，不取外接矩形（design D2/D3）。
    渲染级验证 `test_框绘制在预览层之上且位置正确`：render 到 QImage 后
    四个顶点的视口位置 ±3px 内检出描边像素（#00E676）。
- [x] 2.2 用倾斜文本样本验证：框呈倾斜四边形并与文本走向贴合
  - `test_倾斜文本框保持四边形顶点`：SKEWED_BOX 四顶点逐点保留，
    非轴对齐性断言 `at(0).y != at(1).y`。
- [x] 2.3 接入预览区的缩放与平移变换
  - 实现方式：框 item 处于场景中（场景坐标 == 原始图像坐标），QGraphicsView
    的视图变换（滚轮缩放/ScrollHandDrag 平移/resize 重适配）天然作用于场景
    整体——第二级变换零手工代码，不存在会漏掉它的重绘路径（design D1 的
    「合并系数」风险从结构上排除）。
- [x] 2.4 用大图样本验证组合场景：滚轮缩放至多个不同倍率、拖动平移、调整窗口大小，每一步后框都保持贴合
  - `test_缩放平移与调窗后框始终保持贴合`：四档缩放 × 两次平移 × resize 组合，
    每步断言贴合（见 1.4 注记）。
- [x] 2.5 验证图像像素数据未被修改（对比绘制前后的图像数据）
  - `test_图像像素数据不被修改`：set_boxes + 实际 render 一次绘制路径后，
    `pixmap().toImage()` 位图与绘制前逐字节一致。

## 3. 可见性与生命周期

- [x] 3.1 新增 `ui.show_boxes` 配置项，默认 `false`，纳入三层合并
  - `config/defaults.py` BUILTIN_DEFAULTS 与 `config/default.json` 同步加
    `"show_boxes": false`（字段集合一致性由既有 test_config.py 校验，全量通过）。
- [x] 3.2 实现可见性切换入口，切换后写入用户配置
  - 主窗口工具栏 checkable「识别框」action；`_toggle_boxes` 调用
    `config.set("ui.show_boxes", …)` + `config.save()`。
    测试 `test_工具栏切换写入用户配置` 断言快照落盘。
- [x] 3.3 在深色与浅色两类图像上验证框的描边清晰可辨
  - `test_深色与浅色背景上描边均清晰可辨`：纯黑/纯白样本渲染后均检出描边像素，
    描边亮度与背景亮度差 >80（亮绿 #00E676 对黑白两极均高对比）。
    描边用 cosmetic pen：宽度以视口像素计，缩放时不变粗变细。
- [x] 3.4 验证重启后可见性状态保持
  - `test_重启后可见性状态保持`：真 ConfigManager（临时 USER_ROOT）首运行生成
    默认 false → 切换勾选并 save → `load_config()` 重新加载（模拟重启）→
    新窗口 action 勾选态与 viewer 可见性均为 true。
- [x] 3.5 实现载入新图像、清空、识别失败三种情形下清除位置框
  - 载入新图/清空：`ImageViewer.set_image/clear_image` 内 `_reset_box_state()`
    （scene.clear 连带销毁框 item）；识别失败：`MainWindow._on_error` 显式
    `set_boxes(None)`（预览图像保留、框清除）。三情形各有独立测试。
- [x] 3.6 验证空结果时不绘制框且不报错
  - `test_空结果不绘制框且不报错`：`_on_result_ready(empty result)` →
    `box_count()==0`；`polygons_from_result` 对空 lines 返回空列表。

## 4. 联动

- [x] 4.1 实现指向位置框时高亮对应结果行，必要时滚动到可见范围
  - 框 item `hoverEnterEvent/hoverLeaveEvent` → `ImageViewer.boxHovered(index)`
    → `MainWindow._on_box_hover` → `ResultPanel.highlight_line(index)`：
    FullWidthSelection 背景高亮 + 光标移至该行 + `ensureCursorVisible()`。
    测试：hover 进入 → `highlighted_line()==1`；离开 → 复位 -1。
- [x] 4.2 实现选中结果行时高亮对应位置框
  - `ResultPanel.currentLineChanged(blockNumber)`（cursorPositionChanged 转发）
    → `viewer.set_highlighted_box(index)`：高亮样式描边（橙 #FF9A00 宽 3）+
    半透明填充。测试断言 linked 状态与 pen 颜色。hover 高亮与行联动高亮
    相互独立、任一命中即高亮；`highlight_line` 移动光标触发的回环因同索引
    幂等不构成振荡。
- [x] 4.3 验证识别框隐藏时结果区行为与引入本功能前一致
  - `test_识别框隐藏时结果区行为与引入前一致`：隐藏态下行选中/光标移动后，
    全部框 item 不可见（无视觉副作用）、结果文本原样、不报错。
- [x] 4.4 验证多个框重叠处的指向取最靠上的一个，不出现歧义高亮
  - `test_重叠框指向取最靠上的一个`：两框部分重叠，`scene().itemAt(重叠点)`
    命中视觉最上层（后绘制、index=1）框，hover 后高亮第 1 行。

## 5. 性能与收尾

- [x] 5.1 用数百行样本验证：识别框可见时连续缩放与平移，预览保持流畅，界面不出现无响应
  - `test_数百框连续缩放平移保持流畅`：484 框 × 40 轮（缩放+平移+全帧 render），
    断言平均单帧 <100ms 门限（offscreen 实测远低于此）、几何不重建。
    框 item 依托 QGraphicsScene 视口剔除，视口外框不参与绘制。
- [x] 5.2 在设计书 §36 勾选「OCR bounding box」，§17.2 补充两级坐标变换说明
  - §36「OCR bounding box」已勾选；§17.2 ImageViewer 能力清单移入已支持，
    并补两级变换链说明（÷ scale 一次缓存 + 视图变换框架代偿）。
- [x] 5.3 `openspec validate --strict result-box-overlay` 通过
  - 输出 `Change 'result-box-overlay' is valid`。全量测试 273 passed
    （246 既有 + 27 新增）。
