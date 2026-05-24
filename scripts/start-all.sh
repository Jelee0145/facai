#!/bin/bash
set -Eeuo pipefail

FRONTEND_PORT=5000
BACKEND_PORT=8001



cleanup() {
    echo ""
    echo "Stopping all services..."
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
    echo "All services stopped."
}
trap cleanup EXIT INT TERM

kill_port() {
    local port=$1
    local pids
    pids=$(ss -H -lntp 2>/dev/null | awk -v port="${port}" '$4 ~ ":"port"$"' | grep -o 'pid=[0-9]*' | cut -d= -f2 | paste -sd' ' - || true)
    if [[ -n "${pids}" ]]; then
        echo "Port ${port} in use by PIDs: ${pids}, killing..."
        echo "${pids}" | xargs -I {} kill -9 {} 2>/dev/null || true
        sleep 1
    fi
    echo "Port ${port} is free."
}

echo "=== One-click Start ==="
echo ""

echo "[1/3] Cleaning ports..."
kill_port ${BACKEND_PORT}
kill_port ${FRONTEND_PORT}

echo "[2/3] Starting FastAPI backend (port ${BACKEND_PORT})..."
cd backend
pip install -r requirements.txt -q 2>/dev/null || true
uvicorn main:app --host 0.0.0.0 --port ${BACKEND_PORT} --reload &
BACKEND_PID=$!
for i in $(seq 1 15); do
    if curl -s "http://localhost:${BACKEND_PORT}/" > /dev/null 2>&1; then
        echo "Backend ready on port ${BACKEND_PORT}."
        break
    fi
    sleep 1
done

echo "[3/3] Starting Next.js frontend (port ${FRONTEND_PORT})..."
echo "Press Ctrl+C to stop all services."
echo ""
PORT=${FRONTEND_PORT} pnpm tsx watch src/server.ts
