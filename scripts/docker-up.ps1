$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$MIRROR = "docker.m.daocloud.io"

function Ensure-Image($img) {
    if (-not (docker image inspect $img 2>$null)) {
        Write-Host "Pulling $img via $MIRROR ..." -ForegroundColor Cyan
        docker pull ${MIRROR}/library/$img
        docker tag ${MIRROR}/library/$img $img
    }
}

Set-Location $ProjectRoot

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Docker one-click: F&A Generation Tool" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "[1/3] Ensuring base images..." -ForegroundColor Cyan
Ensure-Image "node:22-alpine"
Ensure-Image "python:3.11-slim"

Write-Host "[2/3] Building and starting containers..." -ForegroundColor Cyan
docker compose up --build -d

Write-Host "[3/3] Checking status..." -ForegroundColor Cyan
docker compose ps
Write-Host ""
Write-Host "Frontend: http://localhost:4524" -ForegroundColor Green
Write-Host ""
Write-Host "Use 'docker compose logs -f' to follow logs." -ForegroundColor Yellow
Write-Host "Use 'docker compose down' to stop." -ForegroundColor Yellow
