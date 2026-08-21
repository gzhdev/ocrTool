# fetch_models.ps1 —— 模型资产获取（spec: model-assets）
#
# 幂等：已存在且 SHA256 匹配则跳过；
# 校验失败：删除不可信文件并以非零码退出，绝不保留；
# 内网部署：替换 packaging/models.lock.json 中的 url 为镜像地址即可。
param(
    [string]$LockFile = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $LockFile) { $LockFile = Join-Path $repoRoot "packaging/models.lock.json" }

$lock = Get-Content $LockFile -Raw -Encoding UTF8 | ConvertFrom-Json
$failed = $false

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

foreach ($modelProp in $lock.models.PSObject.Properties) {
    $modelId = $modelProp.Name
    $modelDir = Join-Path $repoRoot "models/$modelId"

    foreach ($kind in @("det", "rec")) {
        $entry = $modelProp.Value.$kind
        $target = Join-Path $modelDir $entry.file

        if (Test-Path $target) {
            $actual = Get-Sha256 $target
            if ($actual -eq $entry.sha256) {
                Write-Host "跳过（已存在且校验通过）: models/$modelId/$($entry.file)"
                continue
            }
            Write-Host "校验失败，删除不可信文件: models/$modelId/$($entry.file)" -ForegroundColor Yellow
            Write-Host "  期望 $($entry.sha256)"
            Write-Host "  实际 $actual"
            Remove-Item $target -Force
            $failed = $true
            continue
        }

        New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
        $tmpFile = "$target.download"
        Write-Host "下载: models/$modelId/$($entry.file)"
        try {
            Invoke-WebRequest -Uri $entry.url -OutFile $tmpFile -UseBasicParsing
            $actual = Get-Sha256 $tmpFile
            if ($actual -ne $entry.sha256) {
                throw "SHA256 不匹配：期望 $($entry.sha256)，实际 $actual"
            }
            Move-Item $tmpFile $target -Force
            Write-Host "落地并校验通过: models/$modelId/$($entry.file)"
        }
        catch {
            if (Test-Path $tmpFile) { Remove-Item $tmpFile -Force }
            Write-Error "获取失败 ${modelId}/${kind}: $($_.Exception.Message)"
            $failed = $true
        }
    }
}

if ($failed) {
    Write-Host "模型资产获取存在失败项，详见上方日志。" -ForegroundColor Red
    exit 1
}
Write-Host "模型资产就绪。"
