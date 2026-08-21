# 建立 OCRTool 工程基线与可发布骨架

## Why

`OCRTool_桌面OCR开发设计书.md` 已确定技术路线，但其中最吃重的假设集中在**运行环境与发布形态**上：Python 版本在文档（3.11）、`pyproject.toml`（>=3.13）、`.venv`（3.13.14）三处不一致；「完全离线」与 RapidOCR 默认联网下载模型冲突；「解压即用」与 Portable 目录可能不可写冲突；§29「禁止引入 QtWebEngine 等组件」只有禁令没有执行机制。

这些问题**不会在业务代码里暴露，只会在打包产物交付给用户时暴露**。设计书 §54 的全部验收标准都压在「解压双击能跑」上，因此必须先把工程基线和打包链路打通并验证，再开发业务功能——否则业务代码写完才发现打不出可用的包，返工成本极高。

## What Changes

### 版本与依赖基线（已实测验证）

- 确定 Python 基线为 **3.13**：`onnxruntime 1.29.0 (cp313)`、`PySide6 6.11.2 (cp310-abi3)`、`pyclipper`、`shapely` 均有 win_amd64 wheel，PyInstaller 6.22.2 明确支持 3.13，`uv` 完整解析通过（32 包，零冲突）。**BREAKING**：设计书 §57 的「Python 3.11」基线作废。
- `requires-python` 收敛为 `>=3.13,<3.14`。onnxruntime 1.29.0 无 cp314 wheel，开区间会让 3.14 机器解析失败。
- 依赖 `pyside6-essentials` 而非 `pyside6` 元包。后者会拖入 `pyside6-addons`（160 MB，含 QtWebEngine / QtMultimedia / Qt3D / QtCharts），直接违反设计书 §29。这是 §29 的执行机制。
- 将 rapidocr 传递依赖的 `opencv-python` 覆盖为 `opencv-python-headless`。opencv-python 自带 Qt5 插件，与 PySide6 同进程会导致 Qt platform plugin 冲突并闪退；两者体积几乎相同（42.0 / 41.8 MB），覆盖无代价。

### 路径与存储模式

- **BREAKING**：设计书 §8 的单一 `APP_ROOT` 拆为双根——`APP_ROOT`（只读资源：models / config / resources）与 `USER_ROOT`（可写状态：data / logs / cache）。
- 新增启动期可写性探测：Portable 模式（exe 同级可写）与 Installed 模式（回退 `%LOCALAPPDATA%\OCRTool`），并支持 `OCRTOOL_DATA_DIR` 覆盖。此设计同时使设计书 §45 的「手工复制 config.json 保配置」不再必要。

### 模型资产

- **BREAKING**：模型目录名改为带版本形式（如 `models/ppocrv6-small/`），`default` 不再是目录名，仅作为解析失败时的回退策略；唯一键为 `model.json` 中的 `id`。
- **BREAKING**：移除方向分类（`use_orientation`），配置项直接删除而非置 false，模型目录不含 cls 模型。
- 模型权重不入版本库，改由带 SHA256 校验的获取脚本落地；校验值取自 RapidOCR 上游 `default_models.yaml`。
- 强制显式指定 det / rec 模型路径，禁用 RapidOCR 的联网下载回退，以满足设计书 §42「无网络访问」。

### 配置与日志

- 三层配置优先级（内置默认 → `config/default.json` → `data/config.json`），用户配置不被程序升级覆盖。
- 日志落在 `USER_ROOT/logs`，轮转 5 MB × 3；记录启动环境信息（含存储模式与 USER_ROOT）；禁止记录 OCR 文本内容，并主动关闭 RapidOCR 自带 logger 的 handler。

### 打包与发布

- **BREAKING**：废弃设计书 §31 的 PyInstaller 命令行方案，改为 `packaging/ocrtool.spec` 单一来源；必须包含 `collect_data_files("rapidocr")` 与 `collect_submodules("rapidocr")`，否则 rapidocr 的 `config.yaml` / `default_models.yaml` / 字典文件不会进包。
- `models/` 与 `config/` 不进 PyInstaller `datas`，由构建脚本在打包后复制到 `dist/OCRTool/`，与 exe 平级（设计书 §7）。
- 发布产物需通过冒烟验证：无 Python 环境的机器上解压双击可运行。

## Capabilities

### New Capabilities

- `app-paths`: 双根路径解析、存储模式探测（Portable / Installed）、环境变量覆盖，以及所有文件访问必须经由路径模块的约束
- `app-config`: 配置的三层加载优先级、用户配置持久化与升级不覆盖、配置损坏时的降级行为
- `app-logging`: 日志落地位置、轮转策略、启动环境记录，以及 OCR 内容不得入日志的隐私约束
- `model-assets`: 模型目录契约（带版本目录名 + `model.json`）、模型 id 解析与回退顺序、离线校验与获取、禁止联网下载
- `packaging`: 依赖基线约束、Portable 发布目录结构、PyInstaller 打包契约与发布产物冒烟验收

### Modified Capabilities

（无——项目尚无既有 spec）

## Impact

- **新增**：`src/ocrtool/app/paths.py`、`config/manager.py`、`utils/logger.py`、`ocr/model_manager.py`、`packaging/ocrtool.spec`、`scripts/{build,release,fetch_models}.ps1`、`packaging/models.lock.json`
- **修改**：`pyproject.toml`（Python 上下界、`pyside6-essentials`、opencv 覆盖）、`.gitignore`（排除 `models/**/*.onnx`，保留 `model.json`）
- **修改**：`OCRTool_桌面OCR开发设计书.md` §8 / §10 / §26 / §29 / §31 / §45 / §57 与设计基线不再一致，需回写
- **依赖**：新增 `pyside6-essentials`、`onnxruntime`、`rapidocr`、`pyinstaller`；显式覆盖 `opencv-python-headless`
- **不影响**：OCR 识别、UI 交互、图片输入等业务行为，由后续 `mvp-image-ocr` 变更承载
- **风险**：打包产物能否在干净机器上运行是本变更唯一无法通过静态推理消除的未知项，须由冒烟验收实跑确认
