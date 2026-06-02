$FrontendPort = 5000
$BackendPort = 8001

# Script always runs from project root
$ProjectRoot = (Get-Location).Path

# Safety check
if (-not (Test-Path (Join-Path $ProjectRoot "package.json"))) {
    Write-Host "ERROR: Run this script from the project root (where package.json is)." -ForegroundColor Red
    Write-Host "  cd D:\project\projects" -ForegroundColor Yellow
    exit 1
}

function Stop-ProcessOnPort($port) {
    $conn = netstat -ano | Select-String "LISTENING" | Select-String ":$port "
    if ($conn) {
        $pid = $conn.Line.Trim().Split()[-1]
        Write-Host "Port $port occupied by PID $pid, killing..." -ForegroundColor Yellow
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
    Write-Host "  Port $port is free." -ForegroundColor Green
}

function Ensure-Node {
    $v = (node -v 2>$null)
    if (-not $v -or ([Version]($v.TrimStart("v")) -lt [Version]"20.9")) {
        Write-Host "  Node.js not found or below 20.9, installing via winget..." -ForegroundColor Yellow
        winget install -e --id OpenJS.NodeJS --silent --accept-package-agreements 2>&1 | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        $v = (node -v 2>$null)
        if (-not $v) {
            Write-Host "  Node.js install failed. Download from https://nodejs.org (>=20.9)" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  Node.js $v" -ForegroundColor Green
}

function Ensure-Pnpm {
    $pnpmVer = (pnpm -v 2>$null)
    if (-not $pnpmVer) {
        Write-Host "  pnpm not found, installing via corepack..." -ForegroundColor Yellow
        corepack enable 2>$null
        corepack prepare pnpm@latest --activate 2>$null
        $pnpmVer = (pnpm -v 2>$null)
        if (-not $pnpmVer) {
            Write-Host "  corepack unavailable, trying npm install -g pnpm..." -ForegroundColor Yellow
            npm install -g pnpm 2>$null
            $pnpmVer = (pnpm -v 2>$null)
        }
        if (-not $pnpmVer) {
            Write-Host "  pnpm install failed. Run: npm install -g pnpm" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  pnpm $pnpmVer" -ForegroundColor Green
}

function Ensure-Python {
    $v = (python --version 2>$null)
    if (-not $v) { $v = (python3 --version 2>$null) }
    if (-not $v -or ([Version]($v -replace ".*\s", "") -lt [Version]"3.11")) {
        Write-Host "  Python not found or below 3.11, installing via winget..." -ForegroundColor Yellow
        winget install -e --id Python.Python.3.11 --silent --accept-package-agreements 2>&1 | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        $v = (python --version 2>$null)
        if (-not $v) {
            Write-Host "  Python install failed. Download from https://www.python.org/downloads/ (>=3.11)" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "  $v" -ForegroundColor Green
}

function Install-PythonDeps {
    $req = Join-Path $ProjectRoot "backend\requirements.txt"
    if (Test-Path $req) {
        Write-Host "  Installing Python dependencies..." -ForegroundColor Cyan
        pip install -r $req -q
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  pip failed, trying --break-system-packages..." -ForegroundColor Yellow
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
            Write-Host "  .env created from .env.example." -ForegroundColor Yellow
        } else {
            Write-Host "  .env and .env.example not found. Create .env manually." -ForegroundColor Red
        }
    } else {
        Write-Host "  .env" -ForegroundColor Green
    }

    if (-not (Test-Path $backEnv)) {
        if (Test-Path $backExample) {
            Copy-Item $backExample $backEnv
            $jwtSecret = -join ((48..57) + (97..102) | Get-Random -Count 64 | ForEach-Object { [char]$_ })
            (Get-Content $backEnv) -replace "JWT_SECRET=.*", "JWT_SECRET=$jwtSecret" | Set-Content $backEnv
            $adminPw = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 12 | ForEach-Object { [char]$_ })
            Add-Content -Path $backEnv -Value "`nADMIN_PASSWORD=$adminPw"
            Write-Host "  backend\.env created with random JWT_SECRET and ADMIN_PASSWORD." -ForegroundColor Yellow
        } else {
            Write-Host "  backend\.env and .env.example not found. Create manually." -ForegroundColor Red
        }
    } else {
        Write-Host "  backend\.env" -ForegroundColor Green
    }
}

# ─── Windows Job Object: 确保关闭终端时子进程也被终止 ───
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class JobObject {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetInformationJobObject(IntPtr hJob, int JobObjectInfoType,
        IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr hObject);

    public const int JobObjectExtendedLimitInformation = 9;
    public const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public uint ProcessMemoryLimit;
        public uint JobMemoryLimit;
        public uint PeakProcessMemoryUsed;
        public uint PeakJobMemoryUsed;
    }

    public static IntPtr CreateKillOnClose() {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        var limit = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        limit.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int size = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        IntPtr ptr = Marshal.AllocHGlobal(size);
        Marshal.StructureToPtr(limit, ptr, false);
        SetInformationJobObject(job, JobObjectExtendedLimitInformation, ptr, (uint)size);
        Marshal.FreeHGlobal(ptr);
        return job;
    }

    public static bool Assign(IntPtr hJob, IntPtr hProcess) {
        return AssignProcessToJobObject(hJob, hProcess);
    }
}
"@

$JobHandle = [JobObject]::CreateKillOnClose()

function Test-HealthEndpoint {
    param([string]$Url, [string]$Name, [int]$TimeoutSeconds = 30)
    Write-Host "  Waiting for $Name at $Url ..." -ForegroundColor Cyan
    $start = Get-Date
    while (((Get-Date) - $start).TotalSeconds -lt $TimeoutSeconds) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) {
                $elapsed = [int]((Get-Date) - $start).TotalSeconds
                Write-Host "  $Name is ready. (${elapsed}s)" -ForegroundColor Green
                return $true
            }
        } catch {
            # Not ready yet
        }
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
    }
    Write-Host ""
    Write-Host "  ERROR: $Name failed to start within ${TimeoutSeconds}s." -ForegroundColor Red
    return $false
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  One-click start: F+A Generation Tool" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray

Write-Host "[1/8] Checking and installing runtime..." -ForegroundColor Cyan
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
$backendCwd = Join-Path $ProjectRoot "backend"
$backendProc = Start-Process -NoNewWindow -PassThru -FilePath "python" `
    -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port $BackendPort --reload" `
    -WorkingDirectory $backendCwd

# Assign to Job Object: 关闭终端时自动杀掉此进程
if ($JobHandle -and $backendProc -and !$backendProc.HasExited) {
    [JobObject]::Assign($JobHandle, $backendProc.Handle) | Out-Null
}

if (-not (Test-HealthEndpoint "http://localhost:$BackendPort/health" "Backend" 30)) {
    if ($backendProc -and !$backendProc.HasExited) {
        $backendProc.Kill()
        $backendProc.WaitForExit(3000)
    }
    Write-Host "  Backend failed to start. Check logs above." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[7/8] Starting Next.js frontend (port $FrontendPort)..." -ForegroundColor Cyan
$frontendUrl = "http://localhost:$FrontendPort"
Write-Host "  Open $frontendUrl in your browser." -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop all services." -ForegroundColor Magenta
Write-Host ""

try {
    $env:BACKEND_URL = "http://localhost:$BackendPort"
    $env:PORT = $FrontendPort
    pnpm tsx watch src/server.ts
}
finally {
    Write-Host "Stopping backend..." -ForegroundColor Yellow
    if ($backendProc -and !$backendProc.HasExited) {
        $backendProc.Kill()
        $backendProc.WaitForExit(5000)
        $backendProc.Dispose()
    }
    Write-Host "All services stopped." -ForegroundColor Green
}
