#!/bin/bash
set -Eeuo pipefail

PROJECT_DIR="/opt/project"          # 项目目录，修改前确认
BACKUP_DIR="/var/backups/sqlite"    # 数据库备份目录
DATE=$(date +%Y%m%d_%H%M%S)

echo "=== Deploy: F&A Generation Tool ==="
echo ""

cd "$PROJECT_DIR"

echo "[1/4] Pulling latest code..."
git pull

echo "[2/4] Backing up database..."
mkdir -p "$BACKUP_DIR"
if [ -f "backend/data.db" ]; then
    cp backend/data.db "$BACKUP_DIR/data.$DATE.db"
    echo "  Backup saved: $BACKUP_DIR/data.$DATE.db"
fi

echo "[3/4] Building and restarting containers..."
docker compose build
docker compose up -d

echo "[4/4] Cleaning up old backups (retain 30 days)..."
find "$BACKUP_DIR" -name "data.*.db" -mtime +30 -delete

echo ""
echo "=== Deploy complete ==="
echo "Use 'docker compose logs -f' to follow logs."
echo "Use 'docker compose down' to stop."
