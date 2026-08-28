# ============================================================
#  KaoyanVocab 启动脚本 (Windows 11)
#  用法：
#    - 双击 start.bat（推荐）
#    - 或 PowerShell 中执行:
#        powershell -NoProfile -ExecutionPolicy Bypass -File start-server.ps1
#  功能：检查 Python/依赖 → 杀掉占用 8000 端口的旧服务
#        → 轮转 server.log → 后台启动服务 → 打开浏览器
# ============================================================

$ErrorActionPreference = 'SilentlyContinue'
$Port = 8000
$Url  = "http://127.0.0.1:$Port"

Write-Host ""
Write-Host "  KaoyanVocab · 考研英语词汇本" -ForegroundColor Cyan
Write-Host "  ============================" -ForegroundColor Cyan
Write-Host ""

# ---------- [1/5] 定位 Python 3 ----------
# 优先 py 启动器（Win11 常见），其次 python；自动过滤 Microsoft Store 的 python 占位程序
$pyExe = $null
foreach ($c in @('py', 'python')) {
    $cmdPath = Get-Command $c -ErrorAction SilentlyContinue
    if (-not $cmdPath) { continue }
    $ver = & $c --version 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -and $ver -match 'Python 3') {
        $pyExe = $cmdPath.Source
        break
    }
}
if (-not $pyExe) {
    Write-Host "[错误] 未找到 Python 3。" -ForegroundColor Red
    Write-Host "       请到 https://www.python.org/downloads/ 安装，安装时务必勾选 Add Python to PATH" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}
Write-Host "[1/5] Python 就绪: $pyExe" -ForegroundColor Green

# ---------- [2/5] 检查依赖，缺失则自动安装 ----------
& $pyExe -c "import fastapi, uvicorn, requests, dotenv" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[2/5] 缺少依赖，正在安装 requirements.txt ..." -ForegroundColor Yellow
    & $pyExe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 依赖安装失败，请手动执行：" -ForegroundColor Red
        Write-Host "       $pyExe -m pip install -r requirements.txt" -ForegroundColor Red
        Read-Host "按回车退出"
        exit 1
    }
} else {
    Write-Host "[2/5] 依赖已就绪" -ForegroundColor Green
}

# ---------- [3/5] 杀掉占用 8000 端口的旧服务 ----------
Write-Host "[3/5] 检查端口 $Port ..."
$killed = 0
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    if ($?) { $killed++; Write-Host "      已停止旧进程 (PID $($c.OwningProcess))" -ForegroundColor Yellow }
}
if (-not $conns) {
    # 兜底：用 netstat 找监听 PID
    $lines = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING"
    foreach ($line in $lines) {
        $procId = ($line.ToString() -split '\s+')[-1]
        if ($procId -match '^\d+$') {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            if ($?) { $killed++ }
        }
    }
}
if ($killed -eq 0) { Write-Host "      端口空闲，无需清理" -ForegroundColor Green }
Start-Sleep -Milliseconds 500

# ---------- [4/5] 轮转 server.log（超过 5MB 备份为 server.log.1）----------
Write-Host "[4/5] 准备启动服务 ..."
if (Test-Path server.log) {
    $len = (Get-Item server.log).Length
    if ($len -gt 5MB) {
        Move-Item -Force server.log server.log.1
        Write-Host "      server.log 超过 5MB，已轮转为 server.log.1" -ForegroundColor Yellow
    }
}

# 后台启动：最小化窗口运行 python main.py，日志写入 server.log
$quoted = if ($pyExe -match '\s') { '"' + $pyExe + '"' } else { $pyExe }
$cmdLine = "$quoted main.py >> server.log 2>&1"
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmdLine -WorkingDirectory $PWD -WindowStyle Minimized

# ---------- [5/5] 等待启动并打开浏览器 ----------
Start-Sleep -Seconds 2
$up = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($up) {
    Write-Host "[5/5] 服务器已启动 ✅" -ForegroundColor Green
    Write-Host "      访问地址: $Url" -ForegroundColor Green
    Start-Process $Url
} else {
    Write-Host "[5/5] 服务器未检测到监听，请查看 server.log" -ForegroundColor Red
}

# ---------- 配置提示 ----------
if (-not (Test-Path .env)) {
    Write-Host ""
    Write-Host "提示: 未找到 .env 配置文件，AI 补全功能不可用。" -ForegroundColor Yellow
    Write-Host "      请复制 .env.example 为 .env 并填入 API Key 后重启。" -ForegroundColor Yellow
}
Write-Host ""
