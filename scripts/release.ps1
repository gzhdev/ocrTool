# release.ps1 —— 发布流程（spec: packaging）
#
# 流程：build → 冒烟验收（强制关卡，失败即中止且不产出 ZIP）→
#       清理日志/缓存/用户配置 → 打包 OCRTool-<version>-win-x64.zip。
# 版本号单一来源：src/ocrtool/__init__.py 的 __version__（与启动日志、界面显示一致）。
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $distDir = "dist/OCRTool"

    if (-not $SkipBuild) {
        & "$PSScriptRoot/build.ps1"
    }
    elseif (-not (Test-Path "$distDir/OCRTool.exe")) {
        throw "SkipBuild 模式下产物不存在：$distDir —— 请先执行完整构建"
    }

    # 冒烟验收：无 UI 端到端识别（中英混合样本）；死代理确保零网络依赖。
    # 这是发布强制关卡：失败即非零退出，不产出 ZIP。
    Write-Host "== 冒烟验收（--self-test，断网模拟）=="
    $env:HTTP_PROXY = "http://127.0.0.1:9"
    $env:HTTPS_PROXY = "http://127.0.0.1:9"
    $env:ALL_PROXY = "http://127.0.0.1:9"
    $outFile = New-TemporaryFile
    $errFile = New-TemporaryFile
    try {
        # -Wait 确保进程完全退出并释放 exe 句柄后再继续
        $proc = Start-Process -FilePath "$repoRoot/$distDir/OCRTool.exe" `
            -ArgumentList "--self-test" -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $smokeExit = $proc.ExitCode
        $smokeOutput = (Get-Content $outFile -Raw) + (Get-Content $errFile -Raw)
    }
    finally {
        Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
        Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
        Remove-Item Env:ALL_PROXY -ErrorAction SilentlyContinue
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
    $smokeOutput | Write-Host
    if ($smokeExit -ne 0) {
        throw "冒烟验收失败（退出码 $smokeExit），发布中止，不产出 ZIP"
    }
    if (-not ($smokeOutput -match "SELF-TEST OK")) {
        throw "冒烟验收输出异常（未见 SELF-TEST OK），发布中止，不产出 ZIP"
    }

    # 清理构建与冒烟残留：日志、缓存、用户配置必须为空（spec: packaging）
    foreach ($name in @("data", "logs", "cache")) {
        $dir = "$distDir/$name"
        if (Test-Path $dir) {
            Remove-Item "$dir/*" -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    foreach ($name in @("data", "logs", "cache")) {
        $leftover = Get-ChildItem "$distDir/$name" -Force -ErrorAction SilentlyContinue
        if ($leftover) { throw "清理失败：$distDir/$name 仍有残留" }
    }

    # 版本号取自单一来源
    $initPy = Get-Content "src/ocrtool/__init__.py" -Raw -Encoding UTF8
    if ($initPy -notmatch '__version__\s*=\s*"([^"]+)"') {
        throw "无法从 src/ocrtool/__init__.py 解析 __version__"
    }
    $version = $Matches[1]
    $zipName = "OCRTool-$version-win-x64.zip"
    $zipPath = "dist/$zipName"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    # 杀毒软件可能短暂锁定新构建的 exe，压缩带重试
    $zipped = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Compress-Archive -Path $distDir -DestinationPath $zipPath -Force
            $zipped = $true
            break
        }
        catch {
            if ($attempt -eq 3) { throw }
            Write-Host "压缩被占用，${attempt}/3 次重试前等待 2 秒…"
            Start-Sleep -Seconds 2
        }
    }
    if (-not $zipped) { throw "压缩失败" }

    Write-Host "发布完成：$repoRoot\$zipPath"
}
finally {
    Pop-Location
}
