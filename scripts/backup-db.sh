#!/bin/bash
set -Eeuo pipefail

BACKUP_DIR="/var/backups/sqlite"
PROJECT_DIR="/opt/project"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=${1:-30}

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backing up database..."

mkdir -p "$BACKUP_DIR"

# 从 Docker volume 挂载路径复制，或从本地复制
SRC="${PROJECT_DIR}/backend/data.db"
if [ -f "$SRC" ]; then
    cp "$SRC" "${BACKUP_DIR}/data.${DATE}.db"
    gzip "${BACKUP_DIR}/data.${DATE}.db"
    echo "  Backup: ${BACKUP_DIR}/data.${DATE}.db.gz ($(du -h "${BACKUP_DIR}/data.${DATE}.db.gz" | cut -f1))"
else
    echo "  WARNING: data.db not found at $SRC"
fi

# 清理过期备份
echo "  Cleaning backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name "data.*.db*" -mtime +${RETENTION_DAYS} -delete

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup done."
