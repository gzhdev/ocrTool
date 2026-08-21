# OCRTool

Windows 10/11 x64 桌面本地 OCR 工具：**完全离线**、无需 GPU、无需用户安装任何运行环境，解压即用。

技术栈：Python 3.13 · PySide6（essentials）· RapidOCR · ONNX Runtime CPU · PP-OCRv6 Small · PyInstaller onedir

## 开发环境搭建

前置条件：Windows 10/11 x64 + [uv](https://docs.astral.sh/uv/getting-started/installation/)。

两步：

```powershell
# 1. 安装依赖（uv.lock 锁定版本，完全可复现）
uv sync --frozen

# 2. 落地模型资产（从锁文件登记的 URL 下载，SHA256 校验，幂等可重跑；权重不入 git）
powershell -ExecutionPolicy Bypass -File scripts/fetch_models.ps1
```

验证环境就绪：

```powershell
uv run ocrtool --self-test   # 端到端自检：本地模型识别中英混合样本图，应输出 SELF-TEST OK
uv run pytest                # 全量测试（含依赖红线、日志隐私回归、模型目录契约）
```

## 日常开发

```powershell
uv run ocrtool        # 启动应用（开发模式）
uv run pytest         # 测试
```

## 构建与发布

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1     # 构建 dist/OCRTool/（清理→同步→测试→打包→外置资产→断言）
powershell -ExecutionPolicy Bypass -File scripts/release.ps1   # 发布（构建→冒烟验收→清理残留→ZIP）
```

发布产物为 `dist/OCRTool-<version>-win-x64.zip`，冒烟验收（断网模拟下端到端识别）是发布强制关卡，失败不产出 ZIP。

## 目录速览

```text
src/ocrtool/          源码（app/paths 路径 · utils/logger 日志 · config 配置 · ocr/model_manager 模型解析）
config/default.json   随程序分发的默认配置
models/               模型资产（model.json 入库，*.onnx 由脚本落地）
packaging/            ocrtool.spec 打包单一来源 · models.lock.json 模型锁文件
scripts/              fetch_models / build / release / assert_dist
tests/                unit / integration
openspec/             规划与规格（proposal / design / specs / tasks）
```

## 更多文档

- `OCRTool_桌面OCR开发设计书.md` —— 原始设计基线（部分章节已被 OpenSpec 变更覆盖，以 OpenSpec 为准）
- `openspec/changes/` —— 变更提案与规格
