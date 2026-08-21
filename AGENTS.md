# AGENTS.md — OCRTool 工作区指南

## 项目概述

OCRTool：Windows 10/11 x64 桌面 OCR 工具，完全离线运行（无网络、无 GPU、无需用户装 Python）。技术栈：Python 3.13 + PySide6 + RapidOCR + ONNX Runtime CPU + PP-OCRv6 Small 模型；uv 管理依赖；PyInstaller `onedir` 打包为 Portable ZIP（禁用 onefile）。

**当前状态**：绿地项目，尚无源码。`src/`、`tests/`、`scripts/` 均未创建。规划已完成，见下方 OpenSpec 部分。git 分支 `dev`。

## 必读文档与权威顺序

1. `openspec/changes/setup-project-baseline/`（proposal.md + design.md + specs/ + tasks.md）— 工程基线，**必须先于 mvp-image-ocr 实施**
2. `openspec/changes/mvp-image-ocr/` — 第一版图片 OCR 功能
3. `OCRTool_桌面OCR开发设计书.md` — 原始设计基线，**已部分作废**

**关键规则：OpenSpec 变更中标记 BREAKING 的决定覆盖设计书。** 设计书以下章节已被推翻，不要按其实现：

- §57「Python 3.11」→ 实际基线 **Python 3.13**（`requires-python = ">=3.13,<3.14"`，上界必须保留：onnxruntime 1.29.0 无 cp314 wheel）
- §8 单一 APP_ROOT → 双根：`APP_ROOT`（只读资源）/ `USER_ROOT`（可写状态），含可写性探测与 `OCRTOOL_DATA_DIR` 覆盖
- §10 模型目录 `default` → 带版本目录名如 `models/ppocrv6-small/`，唯一键为 `model.json` 的 `id`；移除方向分类（cls 模型不要）
- §31 打包命令行 → 统一走 `packaging/ocrtool.spec`，必须含 `collect_data_files("rapidocr")` 与 `collect_submodules("rapidocr")`
- §13 `OCRResult` 增加 `scale` 字段（大图缩放后坐标还原用）；§22 状态机新增 `EMPTY` 状态（识别成功但零文本）

## OpenSpec 工作流

本仓库用 spec-driven 流程（`openspec/config.yaml`，schema: spec-driven）。变更位于 `openspec/changes/<id>/`（proposal / design / specs / tasks）。改需求先改规划件，再动代码。使用已安装的 skills：`openspec-propose`、`openspec-apply-change`、`openspec-update-change`、`openspec-archive-change`、`openspec-sync-specs`、`openspec-explore`。

## 依赖红线（打包失败的常见根因）

- 用 `pyside6-essentials`，**禁止** `pyside6` 元包（拖入 pyside6-addons → QtWebEngine 等，违反设计书 §29 且体积 +160 MB）
- **禁止** `opencv-python`（自带 Qt5 插件，与 PySide6 同进程冲突闪退）；必须用 uv override 覆盖为 `opencv-python-headless`
- 提交 `uv.lock`，构建走 `uv sync --frozen`
- 模型权重（`models/**/*.onnx`）不入库，由带 SHA256 校验的获取脚本落地；`model.json` 保留入库
- RapidOCR 必须显式传入本地 det/rec 模型路径，**禁用其联网下载回退**（应用全程无网络访问）
- RapidOCR 3.x 返回 `RapidOCROutput` 对象（非 2.x 元组），空结果时 `boxes/txts/scores` 全为 `None`，需规范化为空集合

## 架构边界

- 分层：`MainWindow → OCRController → OCRWorker(QThreadPool, 容量 1) → OCRService → RapidOCR`。**UI 禁止直接调用 OCR 引擎**；业务层禁止接触 RapidOCR 返回结构，只消费 `OCRResult`
- 模型惰性加载 + 单实例复用；启动只做文件存在性自检，不加载 ONNX
- 所有文件访问必须经 `app/paths.py`，业务代码禁止硬编码相对路径
- 识别请求带递增序号（token），回调时序号过期即丢弃（防串图）；识别中拒绝重入
- 主线程只做 UI；OCR 推理一律在后台线程，识别期间窗口不得「未响应」

## 隐私与日志

- 日志**禁止记录 OCR 文本内容与图片内容**，只记尺寸/行数/耗时/异常；需接管并静默 RapidOCR 自带 logger
- 用户可见错误用 QMessageBox 显示简短信息，traceback 只入日志
- 默认不保存原始图片与 OCR 历史，不产生临时文件（QImage → ndarray 全内存）

## 平台与命令

- Windows 10/11 x64 唯一目标平台；shell 是 Git Bash，但构建脚本规划为 PowerShell（`scripts/{build,release,fetch_models}.ps1`，尚未创建）
- 依赖管理统一用 `uv`：`uv sync --frozen`、`uv run <entry>`、`uv pip list`；测试用 pytest（`tests/unit/`、`tests/integration/`，尚未创建）
- `.venv` 为 Python 3.13.14

## 约定

- 文档、提案、提交信息一律用中文；提交信息带前缀，如 `ADD: ...`、`Init: ...`。
- 工作分支 `dev`，PR 目标分支 `master`。
- 不确定某 API 怎么用时，用 `gh_grep` 搜 GitHub 真实代码示例。
- 查库文档用 `context7`（先 resolve-library-id 再 query-docs）。
- 在思考和回复用户时**必须**使用简体中文。