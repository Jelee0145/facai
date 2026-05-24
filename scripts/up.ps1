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

function Install-PythonDeps {
    $req = Join-Path $ProjectRoot "backend\requirements.txt"
    if (Test-Path $req) {
        Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
        pip install -r $req -q
        if ($LASTEXITCODE -ne 0) {
            Write-Host "pip install failed, trying with --break-system-packages..." -ForegroundColor Yellow
            pip install -r $req -q --break-system-packages
        }
    }
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  One-click start: F&A Generation Tool" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $ProjectRoot

Write-Host "[1/4] Cleaning ports..." -ForegroundColor Cyan
Stop-ProcessOnPort $BackendPort
Stop-ProcessOnPort $FrontendPort

Write-Host "[2/4] Installing backend Python deps..." -ForegroundColor Cyan
Install-PythonDeps

Write-Host "[3/4] Starting FastAPI backend (port $BackendPort)..." -ForegroundColor Cyan
$backendJob = Start-Job -ScriptBlock {
    param($root, $port)
    Set-Location "$root\backend"
    uvicorn main:app --host 0.0.0.0 --port $port --reload
} -ArgumentList $ProjectRoot, $BackendPort

Start-Sleep -Seconds 3
$backendOut = Receive-Job -Job $backendJob 2>&1
if ($backendOut) { Write-Host $backendOut -ForegroundColor Gray }

Write-Host "[4/4] Starting Next.js frontend (port $FrontendPort)..." -ForegroundColor Cyan
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
