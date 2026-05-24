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
    Write-Host "  Port $port is free. ✓" -ForegroundColor Green
}

function Ensure-Node {
    $v = (node -v 2>$null)
    if (-not $v -or ([Version]($v.TrimStart("v")) -lt [Version]"20.9")) {
        Write-Host "  Node.js 未安装或版本低于 20.9，正在通过 winget 安装..." -ForegroundColor Yellow
        winget install -e --id OpenJS.NodeJS --silent --accept-package-agreements 2>&1 | Out-Null
        # 刷新 PATH 让新安装的 node 生效
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        $v = (node -v 2>$null)
        if (-not $v) {
            Write-Host "  Node.js 安装失败，请从 https://nodejs.org 手动下载 >=20.9" -ForegroundColor Red
            exit 1
        }
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
            Write-Host "  pnpm 安装失败，请手动执行: npm install -g pnpm" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  pnpm $pnpmVer  ✓" -ForegroundColor Green
}

function Ensure-Python {
    $v = (python --version 2>$null)
    if (-not $v) { $v = (python3 --version 2>$null) }
    if (-not $v -or ([Version]($v -replace ".*\s", "") -lt [Version]"3.11")) {
        Write-Host "  Python 未安装或版本低于 3.11，正在通过 winget 安装..." -ForegroundColor Yellow
        winget install -e --id Python.Python.3.11 --silent --accept-package-agreements 2>&1 | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        $v = (python --version 2>$null)
        if (-not $v) {
            Write-Host "  Python 安装失败，请从 https://www.python.org/downloads/ 手动下载 >=3.11" -ForegroundColor Red
            exit 1
        }
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

function Ensure-EnvFiles {
    $rootEnv = Join-Path $ProjectRoot ".env"
    $rootExample = Join-Path $ProjectRoot ".env.example"
    $backEnv = Join-Path $ProjectRoot "backend\.env"
    $backExample = Join-Path $ProjectRoot "backend\.env.example"

    if (-not (Test-Path $rootEnv)) {
        if (Test-Path $rootExample) {
            Copy-Item $rootExample $rootEnv
            Write-Host "  .env 已从 .env.example 创建，请填入你的 APIMART_API_KEY" -ForegroundColor Yellow
        } else {
            Write-Host "  .env 和 .env.example 都不存在，请手动创建 .env" -ForegroundColor Red
        }
    } else {
        Write-Host "  .env  ✓" -ForegroundColor Green
    }

    if (-not (Test-Path $backEnv)) {
        if (Test-Path $backExample) {
            Copy-Item $backExample $backEnv
            # 自动生成随机 JWT_SECRET
            $jwtSecret = -join ((48..57) + (97..102) | Get-Random -Count 64 | ForEach-Object { [char]$_ })
            (Get-Content $backEnv) -replace "JWT_SECRET=.*", "JWT_SECRET=$jwtSecret" | Set-Content $backEnv
            Write-Host "  backend\.env 已从 .env.example 创建，JWT_SECRET 已自动生成" -ForegroundColor Yellow
            Write-Host "  请填入 APIMART_API_KEY（当前为占位符）" -ForegroundColor Yellow
        } else {
            Write-Host "  backend\.env 和 .env.example 都不存在，请手动创建" -ForegroundColor Red
        }
    } else {
        Write-Host "  backend\.env  ✓" -ForegroundColor Green
    }
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  One-click start: F&A Generation Tool" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $ProjectRoot

Write-Host "[1/8] Checking & installing runtime..." -ForegroundColor Cyan
Ensure-Node
Ensure-Pnpm
Ensure-Python

Write-Host "[2/8] Installing frontend dependencies..." -ForegroundColor Cyan
pnpm install --loglevel warn

Write-Host "[3/8] Installing backend dependencies..." -ForegroundColor Cyan
Install-PythonDeps

Write-Host "[4/8] Ensuring .env files..." -ForegroundColor Cyan
Ensure-EnvFiles

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
