# result-box-overlay 代码审查报告

## 审查元信息与结论

- **审查对象**：工作区未提交变更 vs HEAD（5018453）——result-box-overlay（识别框绘制）完整实现
- **变更范围**：`src/ocrtool/ui/widgets/image_viewer.py`（+167，叠加绘制层）、`src/ocrtool/ui/widgets/result_panel.py`（+53，行高亮联动）、`src/ocrtool/ui/main_window.py`（+38，接线与工具栏开关）、`config/default.json` + `src/ocrtool/config/defaults.py`（新增 `ui.show_boxes`）、新增 `tests/unit/test_result_boxes.py`（517 行 27 用例）、设计书 §17.2/§36 回写
- **方法**：变更摘要代理 + 5 并行审查代理（AGENTS.md 合规 / 浅层 bug / git 历史回归 / 既往审查适用性 / 注释指引）→ 汇总去重 7 个候选 → 逐问题独立验证评分（rubric 0/25/50/75/100，≥80 必须报告）→ 过滤
- **验证证据**：全量 `uv run pytest -q` = 273 passed（246 既有 + 27 新增）；`openspec validate --strict result-box-overlay` 通过；评分代理对 75/50 分项均做了 offscreen 探针实测
- **结论**：**无 ≥80 置信度必须报告问题**。2 项 75 分（建议提交前顺手修复，各约一行代码）+ 5 项 50 分留档。变更整体质量高，可提交。

## 变更整体评价

- **两级坐标变换链——本变更最高风险面——结构性地做对了**：第一级 `polygons_from_result` 在识别回调一次性 `box ÷ scale` 还原到原图坐标（`image_viewer.py:57-61`，`QPointF` 浮点无截断，`scale=0/None` 防御回退 1.0）；第二级零手工换算——框与 pixmap 同处一个 QGraphicsScene（场景坐标=原图像素坐标），视图缩放/平移/调窗由 QGraphicsView 变换机制整体施加。不存在会漏掉一级变换的重绘路径，从结构上排除了 screen-region-ocr review 100-1 那类坐标错位。测试以多档缩放+平移+调窗的 `mapFromScene` 双源一致性断言贴合。
- **四边形不退化**（D3）：QPolygonF 四角点逐点保留，SKEWED_BOX 测试断言非轴对齐。
- **呈现层绘制**（D2）：QGraphicsPolygonItem z=1 叠加，`test_图像像素数据不被修改` 逐字节断言位图不变。
- **可见性持久化**（D5）：`ui.show_boxes` 两层默认一致（有专门测试锁定）、切换即 `set`+`save`、真 ConfigManager 重启读回验证。
- **清除路径齐全**：换图（`set_image → _reset_box_state`）、清空（`clear_all`）、识别失败（`_on_error` 显式 `set_boxes(None)`）、空结果（空列表等价清除）、不可见时行为一致——各有独立测试。
- **既往审查教训全部未重犯**：无信号双注册（mvp 100-1）、busy/token 守卫未绕过（mvp 75-3）、坐标双重变换结构性排除（screen-region 100-1）、fixture 恒真已吸收（DottedConfig 点路径 + 真 ConfigManager，键写错会红）、Qt 生命周期无泄漏（screen-region 50-1）、日志隐私零新增调用。
- **AGENTS.md 红线逐条通过**：分层（UI 只消费 `OCRResult` 契约，`polygons_from_result` 是唯一消费面）、无文件 I/O、无引擎接触、主线程一次性几何构建 + 缓存（484 框 40 轮变换 <100ms/帧门限）。
- tasks.md 24/24 勾选与交付吻合（关键任务逐一实证复核，含 5.3 声明复跑）。

## 75 分问题（建议提交前修复，均附修复方案）

### 75-1 hover 离开识别框后，框高亮永不复位，两侧高亮不对称

- **位置**：`src/ocrtool/ui/widgets/image_viewer.py:170-176`（`set_highlighted_box` 唯一入口是 `currentLineChanged`，全代码无路径把 `_linked_box` 置回 -1）、`src/ocrtool/ui/widgets/image_viewer.py:184-195`（hover 离开只清 `_hovered_box` 并 emit -1）、`src/ocrtool/ui/main_window.py:280-285`（`_on_box_hover(-1)` 只调 `clear_highlight()`，不动光标不发信号）
- **机制**：hover 进入框 2 → `boxHovered(2)` → `highlight_line(2)`（副作用 `setTextCursor`）→ `cursorPositionChanged` → `currentLineChanged(2)` → `set_highlighted_box(2)` 把 `_linked_box` 锁定为 2。hover 离开后仅清文本行高亮，框的橙色 pen/brush 与 `_linked_box` 全部保留。
- **实证**：offscreen 探针——hover 离开后 pen 仍 `#ffff9a00`、brush 仍半透明填充、linked 仍 2；文本行高亮已清。用户视角「鼠标移走了，这个框却一直亮着」，直到点击结果区其他行。结果面板 `setReadOnly(True)` 不显示可见光标，「与光标状态自洽」的设计权衡辩解被驳回；`_on_box_hover` docstring 写明「离开 → 清除高亮」，属实现未闭环而非有意设计。
- **影响**：「鼠标扫框查文字」是本功能核心交互（design D4「这段文字是从图上哪里来的」），每次扫过再移开必触发；残留橙色与真正选中文本行的框高亮视觉不可区分，直接损害联动语义。
- **测试缺口**：`tests/unit/test_result_boxes.py:429-435` `test_指向框后离开时高亮框复位` 只断言 `hovered_box() == -1`，未断言 pen/brush 复位——补 `item.pen().color() == BOX_PEN_COLOR` 断言会红，测试名宣称的行为未被验证（mvp 50-5「断言不足」模式复发）。
- **修复方案**：`_handle_box_hover` 离开分支（或 `main_window` 的 `_on_box_hover(-1)`）在清文本高亮的同时 `set_highlighted_box(-1)` 复位 `_linked_box`；并给上述测试补 pen/brush 复位断言。

### 75-2 再次识别后，旧行高亮残留且漂移到错误行

- **位置**：`src/ocrtool/ui/widgets/result_panel.py:39-40`（`set_result` 只 `setPlainText` 不清 extraSelections；对照 `clear()` 在 :55-57 显式调 `clear_highlight()`——两条路径不对称，佐证漏修而非有意）、`src/ocrtool/ui/main_window.py:287-291`（`_on_result_ready`）
- **机制**：`QPlainTextEdit.setPlainText` 不清 extraSelections，旧高亮的 QTextCursor 按绝对字符位置被 clamp 到新文档。
- **实证**：产品类 ResultPanel offscreen 探针——3 行文本 hover 框 2 高亮第 2 行；`set_result("a\nb\nc\nd")` 后 extraSelections 残留 1 条、block 漂移到第 3 行、`highlighted_line()` 返回 3，渲染级检出橙色像素。MainWindow 全链路：再次识别后 viewer 侧框已重建全无高亮（`highlighted_box()==-1`），panel 侧却残留高亮——两侧联动状态不一致。
- **触发路径**：鼠标停框上配合键盘流（Ctrl+R 同图重识别 / Ctrl+V 粘贴识别 / 截图自动识别流）确定触发；鼠标移开再点按钮的路径经 `boxHovered(-1)` 自动清，故 75 非 100。
- **修复方案**：`set_result` 中 `setPlainText` 之后补一行 `self.clear_highlight()`；补「hover 后再次识别，行高亮被清除」的回归测试（与 75-1 同源于「清除路径只清单侧」，可一并加）。

## 50 分问题（留档，可顺手修）

### 50-1 `clear_all` 后联动框索引泄漏为 0

- `src/ocrtool/ui/main_window.py:323-331` + `src/ocrtool/ui/widgets/result_panel.py:55-57`：`clear()` 的 `setPlainText("")` 同步触发 `currentLineChanged(0)` → `set_highlighted_box(0)`，把 `_linked_box` 从 -1 改写为 0。实证每次 clear_all 必发生（含全新空面板），且 clear_all 自身无法自愈；但泄漏值只在无框窗口期存活——加框唯一入口 `set_boxes` 必先 `_reset_box_state()`，不存在与非空框列表共存的路径，渲染级零可见后果。属状态卫生（「全复位后 `highlighted_box()` 应为 -1」契约），修复方向：`clear()` 中先 blockSignals 再复位，或 `set_highlighted_box` 对 `index >= box_count` 钳制为 -1。

### 50-2 `_on_error` 清框不清行高亮

- `src/ocrtool/ui/main_window.py:302-308`：新增 `set_boxes(None)` 且注释宣称「结果与框同生命周期」，但错误路径下旧文本行的橙色高亮残留成孤儿（光标移动无法清除）。削减因素：spec 的 MUST 主语是「位置框」且 `_on_error` 保留旧文本（高亮与保留文本自洽，非指向错误内容）；触发组合窄（悬停 + 键盘发起 + 识别失败）。修复一行：`_on_error` 补 `clear_highlight()`。

### 50-3 设计书 §9.1 配置示例缺 `show_boxes` 键

- `OCRTool_桌面OCR开发设计书.md:539-542`：ui 段示例仍只有 `"auto_copy": true`，且全文 grep 零处提及 `show_boxes`。mvp review 50-7 同模式第三次人肉漏更（46e651e 修过 `ocr.max_edge_px`、954c848 补过 `auto_copy`）。纯文档零运行时影响，一行修复。

### 50-4 `set_result` 先于 `set_boxes` 是无注释的隐式顺序依赖

- `src/ocrtool/ui/main_window.py:288-291`：当前顺序下任何用户操作序列行为正确（实验验证最终 `_linked_box==-1`）；但实验证实交换两行则第 0 框每次识别后恒高亮（`setPlainText` 触发的 `currentLineChanged(0)` 会作用于已建的新框），且现有测试无防护。纯防御性提示：补一行注释说明顺序约束 + 「识别完成后 `highlighted_box() == -1`」断言锁进测试。

### 50-5 两处文档数字/状态过时

- `tests/unit/test_result_boxes.py:7` docstring「400 行」实际 484（同文件 :504 断言即 484）；`src/ocrtool/ocr/result.py:41-44`「第一版界面不消费此字段（scale）」——本次变更正是消费方（`polygons_from_result`），状态描述失真，建议顺手更新为现状表述（该文件不在 diff 内，酌情）。

## 留档备注（不计问题）

1. 性能门限 `elapsed/rounds < 0.1`（100ms/帧）偏宽松，任务 5.1「不迟滞」标准未严格锁定回归；测试直调私有 `_apply_zoom`/`_pixmap_item` 沿袭既有风格。
2. 新测试 `_on_result_ready` 路径经 `set_clipboard_text` 写真实系统剪贴板（DottedConfig 无 `ui.auto_copy` 键 → 默认 True）——沿袭 test_capture_entry 风格，后续可统一 monkeypatch。
3. `load_from_clipboard` 无 busy 守卫的预存遗留（main_window.py:186-195）非本次引入、未触碰，仍归后续变更。

## 提交建议

- 变更整体质量高、无阻塞问题，可直接 `ADD:` 提交（result-box-overlay 实现与规划件一并）。
- 75 分两项建议提交前顺手修（各一行修复 + 补断言；同源于「清除路径只清单侧」，可共用回归测试），或先提交、修复另起一笔 `FIX:` 提交（沿用 mvp/screen-region 先例，修复后在本文档追加修复落地记录）。
- 50-3/50-4 建议随 75 分修复同批顺手处理（各一行）；50-1/50-2 可留后续。
- 三个纯提案目录（background-residency、model-switching、result-box-overlay 目录本身如需与实现分开）按既往建议与实现分开提交。
