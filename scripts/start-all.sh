#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_PORT="${FRONTEND_PORT:-4524}"
BACKEND_PORT="${BACKEND_PORT:-8001}"
BACKEND_URL="${BACKEND_URL:-http://localhost:${BACKEND_PORT}}"
if [[ -z "${PYTHON_BIN:-}" && -x "${ROOT_DIR}/backend/.venv/Scripts/python.exe" ]]; then
    PYTHON_BIN="${ROOT_DIR}/backend/.venv/Scripts/python.exe"
elif [[ -z "${PYTHON_BIN:-}" && -x "${ROOT_DIR}/backend/.venv/bin/python" ]]; then
    PYTHON_BIN="${ROOT_DIR}/backend/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON_BIN:-python}"
fi

BACKEND_PID=""

cleanup() {
    echo ""
    echo "Stopping all services..."
    if [[ -n "${BACKEND_PID}" ]]; then
        kill "${BACKEND_PID}" 2>/dev/null || true
        wait "${BACKEND_PID}" 2>/dev/null || true
    fi
    echo "All services stopped."
}
trap cleanup EXIT INT TERM

kill_port() {
    local port=$1
    local pids
    if command -v ss >/dev/null 2>&1; then
        pids=$(ss -H -lntp 2>/dev/null | awk -v port="${port}" '$4 ~ ":"port"$"' | grep -o 'pid=[0-9]*' | cut -d= -f2 | paste -sd' ' - || true)
    else
        pids=""
    fi
    if [[ -n "${pids}" ]]; then
        echo "Port ${port} in use by PIDs: ${pids}, killing..."
        echo "${pids}" | xargs -I {} kill -9 {} 2>/dev/null || true
        sleep 1
    fi
    echo "Port ${port} is free or unavailable to inspect."
}

wait_for_backend() {
    for _ in $(seq 1 30); do
        if curl -fsS "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
            echo "Backend ready: http://localhost:${BACKEND_PORT}/health"
            return 0
        fi
        sleep 1
    done
    echo "Backend failed health check: http://localhost:${BACKEND_PORT}/health" >&2
    return 1
}

echo "=== One-click Start ==="
echo ""

echo "[1/3] Cleaning ports..."
kill_port "${BACKEND_PORT}"
kill_port "${FRONTEND_PORT}"

echo "[2/3] Starting FastAPI backend (port ${BACKEND_PORT})..."
cd "${ROOT_DIR}/backend"
"${PYTHON_BIN}" -m pip install -r requirements.txt -q 2>/dev/null || true
"${PYTHON_BIN}" -m uvicorn main:app --host 0.0.0.0 --port "${BACKEND_PORT}" --reload &
BACKEND_PID=$!
wait_for_backend

echo "[3/3] Starting Next.js frontend (port ${FRONTEND_PORT})..."
cd "${ROOT_DIR}"
echo "Backend URL: ${BACKEND_URL}"
echo "Press Ctrl+C to stop all services."
echo ""
BACKEND_URL="${BACKEND_URL}" PORT="${FRONTEND_PORT}" pnpm tsx watch src/server.ts
