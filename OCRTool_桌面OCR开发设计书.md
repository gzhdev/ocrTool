# OCRTool 桌面 OCR 软件开发设计书

> 文档版本：v1.0  
> 目标平台：Windows 10/11 x64  
> 应用形态：Portable 目录版桌面软件  
> 技术栈：Python 3.13 + PySide6 + RapidOCR + ONNX Runtime CPU  
> OCR 模型：PP-OCRv6 Small（默认），PP-OCRv6 Tiny（后续可选）  
> 打包方式：PyInstaller `onedir`  
> 文档状态：开发基线设计

---

## 1. 项目概述

### 1.1 项目名称

**OCRTool**

OCRTool 是一个面向 Windows 桌面环境的本地 OCR 识别工具，主要用于识别：

- 屏幕截图
- 本地图片
- 剪贴板图片
- 扫描件截图
- 中文/英文混合文本

软件默认完全在本地运行，不依赖云端 OCR 服务，不要求用户安装 Python、CUDA、.NET 或其他开发环境。

最终发布形态为：

```text
OCRTool-1.0.0-win-x64.zip
```

用户解压后直接执行：

```text
OCRTool.exe
```

即可使用。

---

## 2. 设计目标

### 2.1 核心目标

本项目需要满足以下核心目标：

1. **完全离线运行**
2. **无需 GPU**
3. **无需安装 Python**
4. **目录版解压即用**
5. **中文 OCR 效果优先**
6. **普通办公 PC 可流畅运行**
7. **OCR 模型和程序主体分离**
8. **UI 与 OCR 引擎解耦**
9. **OCR 过程不得阻塞主界面**
10. **支持后续模型替换和功能扩展**

---

### 2.2 非目标

第一阶段不实现：

- 云端 OCR
- 大语言模型纠错
- PDF 全文 OCR
- 表格结构恢复
- Word/Excel 直接导出
- OCR 历史数据库
- 用户账号系统
- 网络同步
- GPU 推理
- 多语言 UI
- macOS/Linux 发布

以上能力可在后续版本扩展。

---

## 3. 用户使用场景

### 3.1 图片 OCR

用户：

```text
打开 OCRTool
    ↓
点击“打开图片”
    ↓
选择 PNG/JPG/BMP
    ↓
显示图片
    ↓
执行 OCR
    ↓
显示识别文本
    ↓
复制结果
```

---

### 3.2 拖拽 OCR

用户直接将图片拖入主窗口：

```text
Explorer
    ↓
拖入图片
    ↓
OCRTool
    ↓
加载图片
    ↓
自动/手动 OCR
```

---

### 3.3 剪贴板 OCR

用户在其他程序复制图片：

```text
Ctrl + C
    ↓
OCRTool
    ↓
Ctrl + V
    ↓
读取剪贴板图片
    ↓
OCR
```

---

### 3.4 截图 OCR

第二阶段实现：

```text
点击“截图识别”
        ↓
隐藏主窗口
        ↓
截取当前屏幕
        ↓
显示透明截图层
        ↓
鼠标框选区域
        ↓
生成截图
        ↓
OCR
        ↓
显示结果
```

后续可增加全局快捷键：

```text
Alt + Shift + A
```

---

# 4. 技术选型

## 4.1 技术栈

| 模块 | 技术 |
|---|---|
| 开发语言 | Python 3.13 |
| GUI | PySide6 |
| OCR 调用 | RapidOCR |
| 推理运行时 | ONNX Runtime CPU |
| OCR 模型 | PP-OCRv6 Small |
| 图片处理 | Pillow / OpenCV（按实际依赖决定） |
| 数据结构 | dataclasses |
| 配置文件 | JSON |
| 日志 | Python logging |
| 线程 | QThreadPool + QRunnable |
| 打包 | PyInstaller |
| 发布 | ZIP Portable 目录包 |
| 依赖管理 | uv |

---

## 4.2 OCR 模型选择

第一版只内置：

```text
PP-OCRv6 Small
```

原因：

- 中文识别效果较好
- CPU 可运行
- 模型尺寸可接受
- 桌面 PC 不需要极致压缩模型
- 识别精度优先于几 MB 的体积差异

后续可增加：

```text
PP-OCRv6 Tiny
```

形成：

```text
极速模式
    ↓
PP-OCRv6 Tiny

标准模式
    ↓
PP-OCRv6 Small
```

---

# 5. 总体架构

## 5.1 分层结构

```text
┌─────────────────────────────────────┐
│               UI Layer              │
│ PySide6 MainWindow / Dialog / Widget│
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│          Application Layer          │
│ OCRController / ConfigManager       │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│             Worker Layer            │
│      OCRWorker / QThreadPool        │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│             OCR Service             │
│       RapidOCR Adapter Layer        │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│           ONNX Runtime CPU          │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│            PP-OCR Models            │
│       det.onnx / rec.onnx           │
└─────────────────────────────────────┘
```

---

## 5.2 核心设计原则

### UI 不直接调用 OCR

禁止：

```python
class MainWindow:
    def recognize(self):
        self.ocr_engine(...)
```

必须通过：

```text
MainWindow
    ↓
OCRController
    ↓
OCRWorker
    ↓
OCRService
```

这样可以避免：

- UI 与 RapidOCR 强耦合
- OCR 阻塞 UI
- 后续模型切换困难
- 后续替换 OCR 引擎困难

---

# 6. 项目源码目录

推荐目录：

```text
ocr-tool/
│
├─ pyproject.toml
├─ uv.lock
├─ README.md
├─ LICENSE
│
├─ src/
│  └─ ocrtool/
│     │
│     ├─ __init__.py
│     ├─ main.py
│     │
│     ├─ app/
│     │  ├─ __init__.py
│     │  ├─ application.py
│     │  └─ paths.py
│     │
│     ├─ ui/
│     │  ├─ __init__.py
│     │  ├─ main_window.py
│     │  ├─ screenshot_overlay.py
│     │  ├─ settings_dialog.py
│     │  │
│     │  └─ widgets/
│     │     ├─ __init__.py
│     │     ├─ image_viewer.py
│     │     ├─ result_panel.py
│     │     └─ status_widget.py
│     │
│     ├─ controllers/
│     │  ├─ __init__.py
│     │  └─ ocr_controller.py
│     │
│     ├─ ocr/
│     │  ├─ __init__.py
│     │  ├─ service.py
│     │  ├─ worker.py
│     │  ├─ model_manager.py
│     │  ├─ result.py
│     │  └─ exceptions.py
│     │
│     ├─ config/
│     │  ├─ __init__.py
│     │  ├─ manager.py
│     │  ├─ schema.py
│     │  └─ defaults.py
│     │
│     └─ utils/
│        ├─ __init__.py
│        ├─ logger.py
│        ├─ image.py
│        ├─ clipboard.py
│        └─ platform.py
│
├─ resources/
│  ├─ icons/
│  │  └─ app.ico
│  │
│  └─ styles/
│     └─ main.qss
│
├─ models/
│  └─ ppocrv6-small/
│     ├─ det.onnx
│     ├─ rec.onnx
│     └─ model.json
│
├─ config/
│  └─ default.json
│
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ samples/
│
├─ scripts/
│  ├─ build.ps1
│  ├─ clean.ps1
│  └─ release.ps1
│
└─ packaging/
   └─ ocrtool.spec
```

---

# 7. 发布目录设计

最终 Portable 目录：

```text
OCRTool/
│
├─ OCRTool.exe
│
├─ models/
│  └─ ppocrv6-small/
│     ├─ det.onnx
│     ├─ rec.onnx
│     └─ model.json
│
├─ config/
│  └─ default.json
│
├─ data/
│  └─ config.json
│
├─ logs/
│  └─ ocrtool.log
│
├─ cache/
│
└─ _runtime/
   ├─ python313.dll
   ├─ onnxruntime.dll
   ├─ Qt6Core.dll
   ├─ Qt6Gui.dll
   ├─ Qt6Widgets.dll
   ├─ PySide6/
   ├─ shiboken6/
   ├─ platforms/
   │  └─ qwindows.dll
   └─ ...
```

---

# 8. 路径管理设计

所有路径必须通过统一模块处理：

```text
src/ocrtool/app/paths.py
```

禁止在业务代码直接写：

```python
"./models/ppocrv6-small/det.onnx"
```

**双根模型**（取代早期的单一 APP_ROOT 设计）：

```text
APP_ROOT   只读资源根 = exe 同级（打包）/ 项目根（开发）   -> models/  config/  resources/
USER_ROOT  可写状态根 = 启动期探测决定                     -> data/    logs/    cache/
```

两者可以指向不同的物理位置：程序被安装到只读位置（Program Files、只读网络盘）时仍能正常运行。

**USER_ROOT 探测顺序**：

```text
OCRTOOL_DATA_DIR 环境变量（显式覆盖，无效则以明确原因终止启动，不静默回退）
    ↓ 未设置
APP_ROOT 实写探针（真实创建+写入+删除临时文件；禁用 os.access——Windows 上它不解析 ACL）
    ↓ 不可写 → 存储模式 Installed
%LOCALAPPDATA%\OCRTool（回退目录，按需创建）
```

存储模式：程序目录可写为 Portable（USER_ROOT = APP_ROOT），不可写回退为 Installed，设置 `OCRTOOL_DATA_DIR` 显式覆盖时为 Override。

初始化顺序约束：路径解析 MUST 先于日志初始化完成，保证启动期故障可被记录到最终位置。所有文件访问必须经由路径模块获得的绝对路径，不依赖当前工作目录。

实际接口（已实现）：

```python
paths.initialize() -> PathConfig   # 启动早期调用一次
paths.app_root() / paths.user_root() / paths.storage_mode()
paths.model_dir() / paths.default_config_path() / paths.resource_dir()
paths.data_dir() / paths.user_config_path() / paths.log_dir() / paths.cache_dir()
```

data / logs / cache 三个子目录在首次访问前按需创建。

---

# 9. 配置系统

## 9.1 默认配置

文件：

```text
config/default.json
```

示例：

```json
{
  "ocr": {
    "model": "ppocrv6-small",
    "max_edge_px": 6000
  },
  "runtime": {
    "provider": "CPUExecutionProvider",
    "cpu_threads": 4
  },
  "ui": {
    "always_on_top": false,
    "auto_copy": false,
    "auto_ocr_after_open": true
  },
  "screenshot": {
    "auto_ocr": true
  },
  "logging": {
    "level": "INFO"
  }
}
```

注意：配置中不存在方向分类（orientation/cls）相关开关——该能力已整体移除，保留开关项会暗示能力可被开启。`ui` / `screenshot` 段随 MVP 界面功能落地，当前基线仅含 `ocr` / `runtime` / `logging`。

---

## 9.2 用户配置

运行后生成：

```text
data/config.json
```

规则：

```text
第一次启动
    ↓
data/config.json 不存在
    ↓
读取 config/default.json
    ↓
创建 data/config.json
```

后续始终优先读取：

```text
data/config.json
```

程序升级不得覆盖用户配置。

---

## 9.3 配置加载优先级

```text
程序内默认值
      ↓
config/default.json
      ↓
data/config.json
```

最终值采用后加载配置覆盖前值。

---

# 10. 模型管理

## 10.1 模型目录结构

目录名携带版本信息，`default` 不再是目录名（与「多版本模型并存」矛盾），仅作为解析失败时的回退策略名。

第一版：

```text
models/
└─ ppocrv6-small/
   ├─ det.onnx
   ├─ rec.onnx
   └─ model.json
```

未来：

```text
models/
├─ ppocrv6-tiny/
│  ├─ det.onnx
│  ├─ rec.onnx
│  └─ model.json
│
└─ ppocrv7-small/
   ├─ det.onnx
   ├─ rec.onnx
   └─ model.json
```

三个概念分离：目录名（文件系统，任意）／唯一键（`model.json` 的 `id`）／当前选择（配置项 `ocr.model`）。模型目录不含方向分类（cls）模型——该能力已整体移除。

模型权重不入版本库（`.gitignore` 排除 `models/**/*.onnx`），由 `scripts/fetch_models.ps1` 依据 `packaging/models.lock.json`（登记上游官方 SHA256）幂等获取；`model.json` 作为契约的一部分保留入库。

---

## 10.2 model.json

示例（已落地）：

```json
{
  "id": "ppocrv6-small",
  "name": "PP-OCRv6 Small",
  "ocr_version": "PP-OCRv6",
  "description": "标准模式：统一多语种识别模型（中英混合优先），推荐普通桌面电脑",
  "det_model": "det.onnx",
  "rec_model": "rec.onnx",
  "language_coverage": [
    "zh",
    "en"
  ],
  "note": "PP-OCRv6 识别模型为统一多语种模型；language_coverage 描述该模型覆盖的语种，模型本身不按语种拆分",
  "recommended": true
}
```

`language_coverage` 取代早期的 `languages` 字段：PP-OCRv6 的识别模型是统一多语种模型，该字段描述「覆盖语种」而非「模型按语种拆分」。识别字典内嵌于 ONNX metadata（`character` 键），模型目录无需独立字典文件。

---

## 10.3 模型解析（model_manager）

职责：

```text
scan_models()       扫描 models/*/model.json，校验完整性与 id 唯一性
resolve_model()     按回退链解析当前模型
to_engine_params()  生成引擎构造参数（显式本地路径 + 关闭方向分类，禁用联网下载回退）
```

解析回退链：

```text
配置指定的 id
    ↓ 找不到
recommended: true 的模型（记录 ERROR 日志）
    ↓ 无推荐
扫描到的第一个可用模型（目录名排序，保证确定性）
    ↓ 无任何可用模型
启动自检失败（程序仍可启动，实际识别时报错）
```

校验：

- model.json 是否存在且可解析
- det / rec 模型文件是否存在（缺文件的目录不计入可用集，并记录缺失清单）
- id 是否重复（重复则判定整个模型集合非法，不静默选择其一）

---

# 11. OCR 服务设计

## 11.1 OCRService

文件：

```text
ocr/service.py
```

职责：

- 初始化 RapidOCR
- 加载 ONNX 模型
- 保存 OCR Engine 实例
- 执行识别
- 转换 OCR 结果
- 切换模型
- 释放模型
- 捕获 RapidOCR/ONNX 异常

接口：

```python
class OCRService:

    def load_model(self, model_id: str) -> None:
        ...

    def recognize(self, image) -> OCRResult:
        ...

    def switch_model(self, model_id: str) -> None:
        ...

    def unload(self) -> None:
        ...

    @property
    def loaded(self) -> bool:
        ...
```

---

# 12. 模型加载策略

采用：

```text
Lazy Loading
+
Single OCR Engine Instance
```

即：

```text
程序启动
    ↓
不加载模型
    ↓
用户第一次 OCR
    ↓
初始化 OCRService
    ↓
加载模型
    ↓
保存 engine
```

后续：

```text
OCR
 ↓
直接复用 engine
```

禁止每次 OCR 都重新：

```text
创建 RapidOCR
加载 ONNX
执行
销毁
```

---

## 12.1 模型切换

未来支持：

```text
Tiny
Small
```

切换：

```text
用户选择模型
    ↓
OCRController
    ↓
OCRService.switch_model()
    ↓
释放旧 engine
    ↓
加载新 engine
    ↓
更新配置
```

切换模型期间 UI 显示：

```text
正在加载 OCR 模型...
```

---

# 13. OCR 结果对象

## 13.1 OCRLine

```python
@dataclass
class OCRLine:
    text: str
    score: float
    box: list[list[float]]
```

---

## 13.2 OCRResult

```python
@dataclass
class OCRResult:
    text: str
    lines: list[OCRLine]
    elapsed_ms: int
    width: int
    height: int
    scale: float = 1.0
```

`scale` 为送入识别的图像相对原始图像的等比缩放比例（见 §20 尺寸上限；未被缩放时为 1.0）。`box` 处于缩放后坐标系，后续绘制识别框（§36）时须除以 `scale` 还原到原始图像坐标系。第一版界面不消费该字段，但自 MVP 起随结果返回（openspec 变更 mvp-image-ocr 的 BREAKING 决定）。

---

## 13.3 示例

```json
{
  "text": "招商银行\n账户余额",
  "elapsed_ms": 183,
  "width": 1024,
  "height": 768,
  "lines": [
    {
      "text": "招商银行",
      "score": 0.991,
      "box": [
        [10, 10],
        [120, 10],
        [120, 40],
        [10, 40]
      ]
    },
    {
      "text": "账户余额",
      "score": 0.987,
      "box": [
        [10, 50],
        [120, 50],
        [120, 80],
        [10, 80]
      ]
    }
  ]
}
```

---

# 14. OCR 文本合并规则

第一版按 OCR 引擎返回顺序：

```text
line1
line2
line3
```

合并：

```python
"\n".join(line.text for line in lines)
```

空结果分支（mvp-image-ocr 补充）：零行得到空字符串、单行得到该行文本，均无多余换行符；「识别成功但未检出文本」属成功而非错误（状态机进入 EMPTY 态，见 §22）。底层引擎（RapidOCR 3.x）在无检出时 `boxes / txts / scores` 均为 `None` 而非空集合，服务层（OCRService）负责将其规范化为空结果结构，合并逻辑不因此失败。

暂不实现复杂布局重建。

后续可以加入：

```text
行间距判断
X/Y 坐标排序
段落识别
多栏检测
表格检测
```

---

# 15. 线程模型

## 15.1 原则

所有 OCR 推理必须在后台线程执行。

主线程只负责：

- UI
- 用户事件
- 状态更新
- 显示图片
- 显示 OCR 结果

---

## 15.2 推荐架构

```text
Main Thread
    │
    │ requestOCR
    ▼
OCRController
    │
    ▼
QThreadPool
    │
    ▼
OCRWorker
    │
    ▼
OCRService
    │
    ▼
RapidOCR
    │
    ▼
ONNX Runtime
```

返回：

```text
OCRWorker
    │
    │ finished(OCRResult)
    ▼
MainWindow
```

---

## 15.3 OCRWorker

基于：

```text
QRunnable
+
QObject Signals
```

信号：

```python
started
finished
failed
progress
```

示意：

```python
class WorkerSignals(QObject):
    started = Signal()
    finished = Signal(OCRResult)
    failed = Signal(str)
```

---

# 16. OCRController

职责：

```text
MainWindow
     ↓
OCRController
```

OCRController 负责：

- 验证图片
- 防止重复任务
- 创建 Worker
- 提交 QThreadPool
- 转发执行状态
- 更新 UI 状态
- 调用 OCRService
- 处理错误

MainWindow 不关心 RapidOCR API。

---

# 17. UI 设计

## 17.1 主窗口

建议：

```text
┌───────────────────────────────────────────────────────┐
│ OCRTool                                     _  □  X   │
├───────────────────────────────────────────────────────┤
│ [截图识别] [打开图片] [粘贴图片] [清空] [设置]       │
├────────────────────────┬──────────────────────────────┤
│                        │                              │
│                        │       OCR 识别结果           │
│                        │                              │
│       图片预览         │   招商银行                   │
│                        │   账户余额                   │
│                        │                              │
│                        │                              │
├────────────────────────┴──────────────────────────────┤
│ PP-OCRv6 Small │ 识别 183 ms │ 2 行 │ [复制全部]    │
└───────────────────────────────────────────────────────┘
```

---

## 17.2 UI 模块

### MainWindow

负责：

- 菜单/工具栏
- 图片区域
- OCR 结果区域
- 状态栏
- 按钮事件

---

### ImageViewer

支持：

- 显示图片
- 等比缩放
- 自适应窗口
- 鼠标滚轮缩放
- 拖动查看
- 接收拖拽图片

未来：

- OCR bounding box 绘制

---

### ResultPanel

支持：

- OCR 文本显示
- 全选
- 复制
- 清空

建议使用：

```text
QPlainTextEdit
```

而不是 QTextEdit，以降低复杂度。

---

### StatusWidget

显示：

```text
模型
OCR 状态
耗时
文本行数
```

例如：

```text
PP-OCRv6 Small | 识别完成 | 183 ms | 12 行
```

---

# 18. 图片输入

支持格式：

```text
PNG
JPG
JPEG
BMP
WEBP
```

第一阶段可暂不支持：

```text
GIF
TIFF
PDF
SVG
```

---

## 18.1 Open File

使用：

```text
QFileDialog
```

加载后：

```text
验证文件
    ↓
读取图片
    ↓
ImageViewer
    ↓
保存 current_image
```

---

## 18.2 Drag & Drop

MainWindow：

```python
setAcceptDrops(True)
```

处理：

```text
dragEnterEvent
dropEvent
```

必须：

- 只允许单张图片
- 校验扩展名
- 校验实际图片可读取

---

## 18.3 Clipboard

读取：

```text
QApplication.clipboard()
```

判断：

```text
mimeData().hasImage()
```

如果不是图片：

```text
当前剪贴板中没有图片
```

---

# 19. 图片预处理

第一阶段仅做必要转换：

```text
输入图片
    ↓
统一 RGB/BGR
    ↓
numpy.ndarray
    ↓
RapidOCR
```

暂不主动：

- 二值化
- 锐化
- 放大
- 对比度增强
- 去噪

原因：

PP-OCR 本身对普通截图已经具有较好的适应能力。

后续可增加：

```text
图像增强模式
```

---

# 20. 大图处理

防止用户加载：

```text
20000 × 20000
```

超大图片导致：

- 内存暴涨
- OCR 极慢
- UI 卡顿
- ONNX Runtime 内存不足

建议：

```text
最大边长默认：6000 px
```

超过时：

```text
等比缩放
```

设置：

```json
{
  "ocr": {
    "max_edge_px": 6000
  }
}
```

---

# 21. OCR 执行流程

完整流程：

```text
用户点击 OCR
    ↓
MainWindow
    ↓
检查 current_image
    ↓
OCRController
    ↓
判断 OCR 是否正在执行
    ↓
创建 OCRWorker
    ↓
禁用 OCR 按钮
    ↓
状态 = "识别中"
    ↓
QThreadPool
    ↓
OCRService.recognize()
    ↓
必要时 Lazy Load 模型
    ↓
RapidOCR
    ↓
ONNX Runtime
    ↓
OCRResult
    ↓
Worker.finished
    ↓
MainWindow
    ↓
ResultPanel
    ↓
状态 = "完成"
```

---

# 22. 状态机

OCR 状态：

```text
IDLE
LOADING_MODEL
RUNNING
SUCCESS
EMPTY
ERROR
```

`EMPTY`（mvp-image-ocr 新增，BREAKING）：识别成功但未检出任何文本。归入 SUCCESS 会让用户无法区分「没识别出来」与「程序出问题」，归入 ERROR 则对正常输入弹窗过度反应；单列一态，界面反馈为状态区提示「未识别到文本」，不弹对话框。

状态转换：

```text
IDLE
 ↓
LOADING_MODEL          （模型已加载则跳过，IDLE → RUNNING）
 ↓
RUNNING
 ↓ ↓ ↓
 SUCCESS  EMPTY  ERROR
 ↓ ↓ ↓
IDLE
```

异常：

```text
RUNNING
 ↓
ERROR
 ↓
IDLE
```

加载失败（mvp-image-ocr 补充）：

```text
LOADING_MODEL
 ↓
ERROR
 ↓
IDLE
```

禁止：

```text
RUNNING
 ↓
再次启动 RUNNING
```

---

# 23. 错误处理

## 23.1 错误分类

定义：

```text
OCRToolError
├─ ModelNotFoundError
├─ ModelLoadError
├─ OCRExecutionError
├─ InvalidImageError
├─ ConfigError
└─ RuntimeError
```

---

## 23.2 用户可见错误

例如：

```text
OCR 模型文件缺失
```

详细信息写入日志：

```text
models/ppocrv6-small/rec.onnx not found
```

UI 不直接显示 Python traceback。

---

# 24. 日志设计

日志文件：

```text
logs/ocrtool.log
```

默认等级：

```text
INFO
```

开发环境：

```text
DEBUG
```

---

## 24.1 日志格式

```text
2026-08-22 10:00:00.123 INFO  [MainThread] ocrtool.app - OCRTool 1.0.0 startup
```

---

## 24.2 必须记录

启动：

```text
应用版本
Windows 版本
Python Runtime 版本
ONNX Runtime provider
CPU 线程数
```

模型：

```text
模型 ID
模型目录
加载耗时
```

OCR：

```text
图片尺寸
OCR 耗时
识别行数
```

异常：

```text
Exception Type
Message
Traceback
```

---

## 24.3 日志轮转

建议：

```text
单文件最大 5 MB
最多保留 3 个
```

使用：

```python
RotatingFileHandler
```

---

# 25. UI 错误提示

使用：

```text
QMessageBox
```

场景：

- 模型加载失败
- 图片无法读取
- 文件格式不支持
- OCR 引擎初始化失败
- 配置损坏

普通操作状态使用状态栏，不弹窗。

---

# 26. 运行时配置

ONNX Runtime 默认：

```text
CPUExecutionProvider
```

配置：

```json
{
  "runtime": {
    "provider": "CPUExecutionProvider",
    "cpu_threads": 4
  }
}
```

线程配置映射：`runtime.cpu_threads` 由 `OCRService`（`ocr/service.py` 的 `_build_params` + `map_thread_count`）在引擎初始化时映射为 ONNX Runtime 的 `intra_op_num_threads` 与 `inter_op_num_threads`（两者同值）；配置为 0 或负值时传 `-1` 交由推理运行时决定，正值不超过逻辑核心数。默认值 4，如需可按 `min(4, logical_cpu_count)` 收窄。

方向分类（cls / orientation）已整体移除：配置中不存在相关开关，引擎构造参数固定 `Global.use_cls: false`，模型目录也不要求 cls 模型文件。

第一阶段不开放 UI 调节线程数。

---

# 27. 性能目标

参考目标，不作为绝对保证：

### 启动

```text
冷启动 < 3 秒
```

普通办公 PC。

### 模型第一次加载

```text
< 2 秒
```

### 普通截图 OCR

典型：

```text
1920 × 1080
```

目标：

```text
< 1 秒
```

具体性能取决于：

- CPU
- 图片文字密度
- 模型
- ONNX Runtime

---

# 28. 内存目标

启动但未加载模型：

```text
< 200 MB
```

加载 OCR 模型：

```text
建议控制在 500 MB 内
```

实际数值以 benchmark 为准。

---

# 29. PySide6 资源控制

禁止引入不必要组件：

```text
QtWebEngine
QtMultimedia
QtQml
QtQuick
Qt3D
QtCharts
```

优先只使用：

```text
QtCore
QtGui
QtWidgets
```

以控制：

- 发布目录体积
- DLL 数量
- 启动时间

**依赖侧断源机制**（取代单纯的「禁止」约定）：

- 依赖 `pyside6-essentials` 而非 `pyside6` 元包——后者会拖入 `pyside6-addons`（+160 MB，含上述全部禁用组件），从依赖声明上断绝来源；
- rapidocr 传递依赖的 `opencv-python` 通过 uv `override-dependencies` 覆盖为 `opencv-python-headless`（opencv-python 自带 Qt5 平台插件，与 PySide6 同进程会冲突闪退）；
- `tests/unit/test_dependency_constraints.py` 作为回归红线，环境出现禁止包即测试失败；
- PyInstaller spec 的 `excludes` 列表作为第二道防线；
- `scripts/assert_dist.ps1` 在构建产物上断言禁止组件库文件不存在。

---

# 30. 打包方案

采用：

```text
PyInstaller
+
onedir
```

不采用：

```text
onefile
```

原因：

- onefile 启动时需要临时解压
- 启动速度更慢
- ONNX DLL 问题更难排查
- 模型外置后 onefile 优势不大
- 目录版更方便内网发布和升级

---

# 31. PyInstaller 配置

统一以 spec 文件为单一来源（早期建议的命令行方案已废弃——命令行参数散落且无法版本化评审）：

```text
packaging/ocrtool.spec
```

构建入口：

```powershell
uv run pyinstaller packaging/ocrtool.spec --noconfirm --clean
```

（实际由 `scripts/build.ps1` 调用，不要手工单跑。）

spec 必含契约：

```text
datas         = collect_data_files("rapidocr")   # config.yaml / default_models.yaml / 自带模型与字典
hiddenimports = collect_submodules("rapidocr")   # 动态导入的子模块
excludes      = [WebEngine, Multimedia, Qml, Quick, 3D, Charts, ...]  # 第二道防线
contents_directory = "_runtime"                  # 参数位于 EXE 对象（COLLECT 会继承）
```

`models/` 与 `config/` 绝不进入 `datas`：它们必须与 exe 平级（§7），由构建脚本在 PyInstaller 之后复制；若误入 `datas` 会落到 `_runtime/models/` 导致运行期解析失败——`scripts/assert_dist.ps1` 在构建末尾断言其位置。

---

# 32. 构建流程

`scripts/build.ps1`：

```text
清理 build
    ↓
清理 dist
    ↓
uv sync --frozen
    ↓
运行测试
    ↓
PyInstaller
    ↓
复制 models
    ↓
复制 config
    ↓
创建 data
    ↓
创建 logs
    ↓
创建 cache
```

最终：

```text
dist/OCRTool/
```

---

# 33. 发布流程

`scripts/release.ps1`：

```text
执行 build.ps1
    ↓
验证 OCRTool.exe
    ↓
运行 smoke test
    ↓
删除缓存/日志
    ↓
ZIP
```

生成：

```text
OCRTool-1.0.0-win-x64.zip
```

---

# 34. 版本信息

建议：

```text
src/ocrtool/__init__.py
```

保存：

```python
__version__ = "1.0.0"
```

发布包：

```text
OCRTool-1.0.0-win-x64.zip
```

日志：

```text
OCRTool version 1.0.0
```

设置窗口：

```text
OCRTool 1.0.0
```

---

# 35. 第一阶段 UI 功能

## 必须实现

- [ ] 打开图片
- [ ] 拖拽图片
- [ ] 粘贴图片
- [ ] 图片预览
- [ ] OCR
- [ ] 显示结果
- [ ] 复制结果
- [ ] OCR 状态显示
- [ ] OCR 耗时显示
- [ ] 配置文件
- [ ] 日志
- [ ] Portable 打包

---

# 36. 第二阶段功能

- [ ] 截图 OCR
- [ ] 全局快捷键
- [ ] 自动复制
- [ ] OCR bounding box
- [ ] Tiny / Small 模型切换
- [ ] 开机启动
- [ ] 系统托盘
- [ ] UI 设置窗口

---

# 37. 第三阶段功能

可选：

- [ ] OCR 历史
- [ ] PDF OCR
- [ ] 批量图片
- [ ] 表格 OCR
- [ ] JSON 导出
- [ ] Markdown 导出
- [ ] LLM 文本纠错
- [ ] 翻译
- [ ] 自定义模型安装

---

# 38. 测试设计

## 38.1 Unit Test

测试：

```text
ConfigManager
ModelManager
PathManager
OCRResult
ImageUtils
```

---

## 38.2 Integration Test

测试：

```text
图片
 ↓
OCRService
 ↓
OCRResult
```

样本：

```text
tests/samples/
├─ chinese.png
├─ english.png
├─ mixed.png
├─ small_text.png
└─ rotated.png
```

---

## 38.3 UI Test

重点人工测试：

- 打开图片
- 拖拽
- 粘贴
- 连续 OCR
- OCR 时拖动窗口
- OCR 时最小化
- 无模型启动
- 模型损坏
- 无效图片
- 超大图片

---

# 39. OCR Benchmark

建议建立：

```text
benchmark/
```

样本分类：

```text
截图
扫描件
网页
IDE
终端
表格
中文
中英混合
```

记录：

| 文件 | 分辨率 | OCR 时间 | 字符数 | 准确率 |
|---|---:|---:|---:|---:|
| test01.png | 1920×1080 | 280ms | 125 | 99% |
| test02.png | 2560×1440 | 510ms | 310 | 97% |

用于比较：

```text
Tiny
vs
Small
```

---

# 40. 稳定性测试

连续：

```text
OCR 100 次
```

观察：

- 内存是否持续上涨
- handle 是否泄漏
- UI 是否卡死
- 模型是否重复加载
- ONNX Runtime 是否异常

---

# 41. 启动自检

软件启动时执行轻量检查（通过模型扫描与解析完成）：

```text
config/default.json
models/*/model.json（描述文件结构校验）
models/*/det.onnx、rec.onnx（文件存在性）
```

不立即加载 ONNX。

如果缺失：

```text
状态栏提示
+
日志 ERROR
```

真正 OCR 时再显示明确错误。

---

# 42. 安全设计

默认：

```text
无网络访问
```

不：

- 上传图片
- 上传 OCR 文本
- 收集用户数据
- 自动联网下载模型

如果未来增加网络能力，必须：

- 独立配置
- 默认关闭
- 明确提示

---

# 43. 隐私设计

OCR 输入可能包含敏感内容。

因此：

```text
默认不保存原始图片
默认不保存 OCR 历史
默认不发送网络请求
```

日志禁止记录：

```text
完整 OCR 文本
图片内容
```

日志只记录：

```text
图片尺寸
文本行数
执行时间
异常
```

---

# 44. 临时文件

第一阶段尽量：

```text
不生成临时图片
```

数据流：

```text
QImage
 ↓
memory
 ↓
numpy
 ↓
OCR
```

截图 OCR 同样优先走内存。

---

# 45. 软件升级策略

程序升级：

```text
OCRTool/
```

推荐用户：

```text
解压新版本，整体替换程序目录
```

无需任何配置迁移：用户配置位于可写状态根（USER_ROOT，见 §8 双根设计），Portable 模式下若用户数据在程序目录内，`data/`、`logs/`、`cache/` 与 exe 平级，整体替换时注意保留这三个目录即可；Installed 模式下用户数据在 `%LOCALAPPDATA%\OCRTool`，与程序目录无关，替换程序目录即完成升级。

（早期「升级时手工复制 data/config.json」的建议已随双根设计作废。）

---

# 46. 模型升级策略

因为模型位于：

```text
models/
```

模型可以独立升级。

例如：

```text
models/
├─ small-v6/
└─ small-v7/
```

程序扫描：

```text
model.json
```

即可识别。

这样：

```text
模型升级
```

不必修改 UI 和 Controller。

---

# 47. OCR 引擎替换能力

业务层禁止依赖 RapidOCR 返回格式。

必须：

```text
RapidOCR Result
      ↓
OCRService
      ↓
OCRResult
```

因此未来可以：

```text
RapidOCR
   ↓
替换
   ↓
PaddleOCR / Tesseract / Other ONNX OCR
```

UI 无需改变。

---

# 48. 启动入口

`main.py`：

职责：

```text
初始化 Paths
    ↓
初始化 Logger
    ↓
加载 Config
    ↓
创建 QApplication
    ↓
加载 QSS
    ↓
创建 MainWindow
    ↓
exec()
```

Main 不处理 OCR 业务。

---

# 49. Application 对象

`app/application.py` 可负责组装：

```text
ConfigManager
ModelManager
OCRService
OCRController
MainWindow
```

避免 MainWindow 自己创建所有对象。

形成：

```text
Application
├─ ConfigManager
├─ ModelManager
├─ OCRService
├─ OCRController
└─ MainWindow
```

---

# 50. 依赖注入

MainWindow：

```python
MainWindow(
    controller=ocr_controller,
    config=config_manager
)
```

而不是：

```python
MainWindow():
    self.ocr = OCRService()
```

便于：

- 单元测试
- Mock
- 替换 OCR 引擎

---

# 51. 推荐核心类

```text
Application
Paths
ConfigManager
ModelManager
OCRService
OCRController
OCRWorker
OCRResult
OCRLine
MainWindow
ImageViewer
ResultPanel
SettingsDialog
```

---

# 52. 第一版类依赖

```text
Application
│
├── ConfigManager
├── ModelManager
├── OCRService
│      └── ModelManager
│
├── OCRController
│      └── OCRService
│
└── MainWindow
       └── OCRController
```

---

# 53. 第一版开发顺序

## Stage 1

基础工程：

```text
pyproject.toml
路径
配置
日志
MainWindow
```

---

## Stage 2

OCR：

```text
ModelManager
OCRService
OCRResult
```

先通过 CLI 测试：

```text
test.png
 ↓
OCRResult
```

---

## Stage 3

异步：

```text
OCRWorker
OCRController
QThreadPool
```

---

## Stage 4

UI：

```text
图片预览
结果展示
打开图片
拖拽
剪贴板
```

---

## Stage 5

打包：

```text
PyInstaller onedir
```

---

## Stage 6

截图：

```text
ScreenshotOverlay
```

---

# 54. MVP 验收标准

第一版必须满足：

### 环境

目标 PC：

```text
Windows 10/11 x64
无 Python
无 CUDA
无 .NET 开发环境
```

可以直接：

```text
OCRTool.exe
```

---

### OCR

至少支持：

```text
中文
英文
中英文混合
```

---

### 输入

支持：

```text
PNG
JPG
剪贴板图片
拖拽图片
```

---

### UI

OCR 执行期间：

```text
窗口不能出现“未响应”
```

---

### 模型

启动时：

```text
不立即加载模型
```

第一次 OCR：

```text
Lazy Load
```

之后：

```text
复用 Engine
```

---

### 发布

用户只需：

```text
解压 ZIP
双击 OCRTool.exe
```

---

# 55. 推荐 MVP 发布目录

```text
OCRTool/
│
├─ OCRTool.exe
│
├─ models/
│  └─ ppocrv6-small/
│     ├─ det.onnx
│     ├─ rec.onnx
│     └─ model.json
│
├─ config/
│  └─ default.json
│
├─ data/
│
├─ logs/
│
├─ cache/
│
└─ _runtime/
```

---

# 56. 第一版推荐功能边界

建议第一版严格控制在：

```text
打开图片
拖拽图片
粘贴图片
图片预览
OCR
文本展示
复制
日志
配置
Portable 打包
```

不建议第一版同时开发：

```text
PDF
表格
翻译
LLM
历史
自动升级
插件
```

先确保：

```text
OCR 稳定
+
UI 不冻结
+
Portable 发布稳定
```

再继续增加功能。

---

# 57. 最终技术基线

项目第一阶段最终确定为：

```text
Python 3.13（requires-python = ">=3.13,<3.14"，上界必须保留：onnxruntime 1.29.0 无 cp314 wheel）
    +
PySide6（pyside6-essentials，禁用 addons 元包）
    +
RapidOCR
    +
ONNX Runtime CPU
    +
PP-OCRv6 Small
    +
QThreadPool
    +
PyInstaller onedir（packaging/ocrtool.spec 单一来源）
```

最终软件：

```text
OCRTool-1.0.0-win-x64.zip
```

用户：

```text
解压
 ↓
OCRTool.exe
 ↓
使用
```

不要求：

```text
Python
CUDA
Visual Studio
.NET SDK
Node.js
Docker
```

---

# 58. 后续演进路线

```text
v1.0
图片 OCR
    ↓
v1.1
截图 OCR
    ↓
v1.2
Tiny / Small 模型切换
    ↓
v1.3
全局快捷键 + 托盘
    ↓
v1.4
批量 OCR
    ↓
v2.0
PDF / 表格 / OCR 历史 / 可选 LLM
```

该路线保证第一阶段代码结构已经为后续扩展预留能力，同时避免 MVP 过度设计。
