$FrontendPort = 5000
$BackendPort = 8001
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

function Stop-ProcessOnPort($port) {
    $conn = netstat -ano | Select-String "LISTENING" | Select-String ":$port "
    if ($conn) {
        $pid = $conn.Line.Trim().Split()[-1]
        Write-Host "Port $port occupied by PID $pid, killing..." -ForegroundColor Yellow
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
    Write-Host "Port $port is free." -ForegroundColor Green
}

function Check-NodeVersion {
    $v = (node -v 2>$null)
    if (-not $v) {
        Write-Host "Node.js 未安装！请从 https://nodejs.org 下载 >=20.9" -ForegroundColor Red
        exit 1
    }
    $ver = $v.TrimStart("v")
    if ([Version]$ver -lt [Version]"20.9") {
        Write-Host "Node.js $v 版本过低，需要 >=20.9。请从 https://nodejs.org 升级" -ForegroundColor Red
        exit 1
    }
    Write-Host "  Node.js $v  ✓" -ForegroundColor Green
}

function Ensure-Pnpm {
    $pnpmVer = (pnpm -v 2>$null)
    if (-not $pnpmVer) {
        Write-Host "  pnpm 未安装，正在通过 corepack 安装..." -ForegroundColor Yellow
        corepack enable 2>$null
        corepack prepare pnpm@latest --activate 2>$null
        $pnpmVer = (pnpm -v 2>$null)
        if (-not $pnpmVer) {
            Write-Host "  corepack 不可用，尝试 npm install -g pnpm ..." -ForegroundColor Yellow
            npm install -g pnpm 2>$null
            $pnpmVer = (pnpm -v 2>$null)
        }
        if (-not $pnpmVer) {
            Write-Host "  pnpm 安装失败，请手动安装: npm install -g pnpm" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  pnpm $pnpmVer  ✓" -ForegroundColor Green
}

function Check-Python {
    $v = (python --version 2>$null)
    if (-not $v) { $v = (python3 --version 2>$null) }
    if (-not $v) {
        Write-Host "Python 未安装！请从 https://www.python.org/downloads/ 下载 >=3.11" -ForegroundColor Red
        exit 1
    }
    $ver = ($v -replace ".*\s", "")
    if ([Version]$ver -lt [Version]"3.11") {
        Write-Host "$v 版本过低，需要 >=3.11" -ForegroundColor Red
        exit 1
    }
    Write-Host "  $v  ✓" -ForegroundColor Green
}

function Install-PythonDeps {
    $req = Join-Path $ProjectRoot "backend\requirements.txt"
    if (Test-Path $req) {
        Write-Host "  Installing Python dependencies..." -ForegroundColor Cyan
        pip install -r $req -q
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  pip install failed, trying with --break-system-packages..." -ForegroundColor Yellow
            pip install -r $req -q --break-system-packages
        }
    }
}

function Check-EnvFiles {
    $rootEnv = Join-Path $ProjectRoot ".env"
    $backEnv = Join-Path $ProjectRoot "backend\.env"
    if (-not (Test-Path $rootEnv)) {
        Write-Host "  .env 不存在！请创建并填入 APIMART_API_KEY" -ForegroundColor Yellow
        Write-Host "    参考 .env.example 模板" -ForegroundColor Gray
    } else {
        Write-Host "  .env  ✓" -ForegroundColor Green
    }
    if (-not (Test-Path $backEnv)) {
        Write-Host "  backend\.env 不存在！请创建并填入 APIMART_API_KEY 和 JWT_SECRET" -ForegroundColor Yellow
        Write-Host "    参考 backend\.env.example 模板" -ForegroundColor Gray
        Write-Host "    JWT_SECRET 生成: python -c ""import secrets; print(secrets.token_hex(32))""" -ForegroundColor Gray
    } else {
        Write-Host "  backend\.env  ✓" -ForegroundColor Green
    }
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  One-click start: F&A Generation Tool" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $ProjectRoot

Write-Host "[1/8] Checking environment..." -ForegroundColor Cyan
Check-NodeVersion
Ensure-Pnpm
Check-Python

Write-Host "[2/8] Installing frontend dependencies..." -ForegroundColor Cyan
pnpm install --loglevel warn

Write-Host "[3/8] Installing backend dependencies..." -ForegroundColor Cyan
Install-PythonDeps

Write-Host "[4/8] Checking .env configuration..." -ForegroundColor Cyan
Check-EnvFiles

Write-Host "[5/8] Cleaning ports..." -ForegroundColor Cyan
Stop-ProcessOnPort $BackendPort
Stop-ProcessOnPort $FrontendPort

Write-Host "[6/8] Starting FastAPI backend (port $BackendPort)..." -ForegroundColor Cyan
$backendJob = Start-Job -ScriptBlock {
    param($root, $port)
    Set-Location "$root\backend"
    uvicorn main:app --host 0.0.0.0 --port $port --reload
} -ArgumentList $ProjectRoot, $BackendPort

Start-Sleep -Seconds 3
$backendOut = Receive-Job -Job $backendJob 2>&1
if ($backendOut) { Write-Host $backendOut -ForegroundColor Gray }

Write-Host "[7/8] Starting Next.js frontend (port $FrontendPort)..." -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop all services." -ForegroundColor Magenta
Write-Host ""

try {
    $env:BACKEND_URL = "http://localhost:$BackendPort"
    $env:PORT = $FrontendPort
    pnpm tsx watch src/server.ts
}
finally {
    Write-Host "`nStopping backend..." -ForegroundColor Yellow
    Stop-Job -Job $backendJob -ErrorAction SilentlyContinue
    Remove-Job -Job $backendJob -ErrorAction SilentlyContinue
    Write-Host "All services stopped." -ForegroundColor Green
}
