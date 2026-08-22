# OCRTool 第一版图片 OCR 功能

## Why

工程基线（见 `setup-project-baseline`）解决的是「程序能不能被打包出来并启动」，本变更解决的是「程序能做什么」。设计书 §35 / §54 / §56 定义的第一版功能边界为：打开 / 拖拽 / 粘贴图片 → 预览 → OCR → 展示文本 → 复制，且 OCR 执行期间窗口不得出现「未响应」。

这一层的核心风险不在功能多少，而在两处**契约不确定**：RapidOCR 自身在 2.x → 3.x 已发生破坏性 API 变更（返回值从 `(result, elapse)` 元组变为 `RapidOCROutput` 对象），且空结果时其 `boxes / txts / scores` 全为 `None`——设计书 §14 的文本合并与 §22 的状态机都没有覆盖这一分支。因此业务层必须建立与 OCR 引擎无关的结果契约（设计书 §47），这不是过度设计，而是对已发生过的上游变更的直接应对。

## What Changes

### OCR 引擎抽象

- 建立 `OCRService`：唯一持有 RapidOCR 实例的位置，向上只暴露 `OCRResult`，业务层不得接触 RapidOCR 返回结构。
- 采用惰性加载 + 单实例复用：启动不加载模型，首次 OCR 时加载，之后复用；禁止每次识别重建引擎。
- **BREAKING**（相对设计书 §13）：`OCRResult` 增加 `scale` 字段。设计书 §20 的大图等比缩放会使 OCR 返回的 box 处于缩放后坐标系，不记录缩放比例会导致后续绘制识别框（设计书 §36）时全部错位。
- 调用引擎时显式关闭方向分类，与 `setup-project-baseline` 中移除 `use_orientation` 的决定一致。

### 执行模型与状态机

- OCR 在 `QThreadPool` 后台执行，主线程只处理 UI；线程池显式限制为单线程，与单实例引擎匹配。
- 新增请求序号（token）机制：每次识别请求携带递增序号，回调时序号过期即丢弃结果。防止连续输入图片时出现「显示上一张图结果」。
- **BREAKING**（相对设计书 §22）：状态机新增 `EMPTY` 状态，表示识别成功但未检出文本。该情形既非 `SUCCESS` 也非 `ERROR`，需在状态栏提示而非弹窗报错。

### 图片输入

- 支持打开文件、拖拽、剪贴板三种输入，格式限 PNG / JPG / JPEG / BMP / WEBP。
- 输入需经扩展名与实际可解码双重校验；拖拽仅接受单张图片。
- 超过最大边长（默认 6000 px）时等比缩放，并将缩放比例带入 `OCRResult`。
- 全流程走内存（QImage → ndarray），不落临时文件（设计书 §44）。

### 主界面

- 图片预览区（等比缩放、自适应、滚轮缩放、拖动查看）、结果文本区（`QPlainTextEdit`）、状态栏（模型 / 状态 / 耗时 / 行数）、复制全部。
- 识别中禁用触发入口并显示状态；错误以 `QMessageBox` 呈现用户可读信息，技术细节仅入日志，不向用户暴露 traceback。
- 启动自检：检查配置与模型文件存在性，缺失时状态栏提示 + 日志 ERROR，但不在启动时加载 ONNX（设计书 §41）。

## Capabilities

### New Capabilities

- `ocr-engine`: OCR 服务抽象、模型惰性加载与单实例复用、引擎无关的结果契约（含空结果与缩放比例）、错误分类
- `ocr-execution`: 后台执行与主线程不阻塞、请求序号作废机制、OCR 状态机及其合法转换
- `image-input`: 三种图片输入方式、格式与可解码校验、大图缩放、内存内数据流
- `main-window`: 图片预览、识别结果展示与复制、状态栏信息、错误提示分级、启动自检呈现

### Modified Capabilities

（无——本变更依赖 `setup-project-baseline` 建立的 capability，但不修改其需求）

## Impact

- **依赖**：本变更依赖 `setup-project-baseline` 已完成。`OCRService` 消费 `model-assets` 的模型解析结果，日志与配置消费 `app-logging` / `app-config`，所有文件访问经由 `app-paths`
- **新增**：`src/ocrtool/ocr/{service,worker,result,exceptions}.py`、`controllers/ocr_controller.py`、`ui/main_window.py`、`ui/widgets/{image_viewer,result_panel,status_widget}.py`、`app/application.py`、`utils/{image,clipboard}.py`、`main.py`
- **新增测试**：`tests/samples/` 需提供中文 / 英文 / 中英混合 / 小字号样本，用于集成测试
- **修改**：`OCRTool_桌面OCR开发设计书.md` §13 / §14 / §22 需回写（`scale` 字段、空结果分支、`EMPTY` 状态）
- **不包含**：截图 OCR、全局快捷键、托盘、模型切换 UI、识别框绘制、批量与 PDF——均属设计书 §36 / §37 的后续阶段
- **前置未知**：`setup-project-baseline` 的冒烟验收若推翻打包方案，本变更的 UI 与线程假设需重新评估
