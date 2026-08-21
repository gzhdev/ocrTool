# assert_dist.ps1 —— 发布产物断言（spec: packaging）
#
# 7.2 结构断言：models/ 与 config/ 必须与 exe 平级，不得进入 _runtime/；
# 7.3 禁止组件断言：产物内不存在 WebEngine / Multimedia / Qml / Quick / 3D / Charts 库文件。
# 可独立运行：assert_dist.ps1 -DistDir <路径>，供构建脚本与负向验证共用。
param(
    [Parameter(Mandatory = $true)]
    [string]$DistDir
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path (Join-Path $DistDir "OCRTool.exe"))) {
    throw "结构断言失败：$DistDir 下不存在 OCRTool.exe"
}
if (-not (Test-Path (Join-Path $DistDir "models"))) {
    throw "结构断言失败：models/ 必须与 exe 平级（$DistDir\models）"
}
if (-not (Test-Path (Join-Path $DistDir "config"))) {
    throw "结构断言失败：config/ 必须与 exe 平级（$DistDir\config）"
}
foreach ($runtimeSub in @("models", "config")) {
    $misplaced = Join-Path $DistDir "_runtime/$runtimeSub"
    if (Test-Path $misplaced) {
        throw "结构断言失败：$runtimeSub/ 被误封装进运行时目录（$misplaced）——应与 exe 平级"
    }
}

$forbiddenPattern = "(?i)(webengine|multimedia|qml|quick|3d|charts)"
$forbiddenFiles = Get-ChildItem $DistDir -Recurse -File |
    Where-Object { $_.Name -match $forbiddenPattern } |
    Select-Object -ExpandProperty FullName
if ($forbiddenFiles) {
    throw "禁止组件断言失败：产物内存在被禁组件相关文件：`n$($forbiddenFiles -join "`n")"
}

Write-Host "产物断言通过：$DistDir"
