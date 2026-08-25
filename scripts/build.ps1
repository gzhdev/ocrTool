# build.ps1 —— 构建发布目录（spec: packaging）
#
# 流程：清理 → uv sync --frozen → 测试 → PyInstaller → 复制 models/config →
#       创建 data/logs/cache → 产物断言（结构 + 禁止组件）。
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    # 1 清理旧产物
    foreach ($dir in @("build", "dist")) {
        if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    }

    # 2 可复现依赖
    uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw "uv sync --frozen 失败" }

    # 3 测试（依赖红线、隐私回归等）
    if (-not $SkipTests) {
        uv run pytest tests/ -q
        if ($LASTEXITCODE -ne 0) { throw "测试未通过，构建中止" }
    }

    # 4 模型资产必须在场（权重不入库，构建前须先 fetch）
    foreach ($weight in @("det.onnx", "rec.onnx")) {
        $p = "models/ppocrv6-small/$weight"
        if (-not (Test-Path $p)) {
            throw "模型缺失：$p —— 请先运行 scripts/fetch_models.ps1"
        }
    }

    # 5 PyInstaller（spec 单一来源）
    uv run pyinstaller packaging/ocrtool.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

    # 6 外置资产与 exe 平级（设计书 §7）；resources 含托盘图标（任务 2.1）
    Copy-Item models dist/OCRTool/ -Recurse
    Copy-Item config dist/OCRTool/ -Recurse
    Copy-Item resources dist/OCRTool/ -Recurse

    # 7 可写状态目录骨架
    foreach ($name in @("data", "logs", "cache")) {
        New-Item -ItemType Directory -Force -Path "dist/OCRTool/$name" | Out-Null
    }

    # 8 产物断言（结构 + 禁止组件）
    & "$PSScriptRoot/assert_dist.ps1" -DistDir "dist/OCRTool"

    Write-Host "构建完成：$repoRoot\dist\OCRTool"
}
finally {
    Pop-Location
}
