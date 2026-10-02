#!/bin/bash
# 1-Click Offline Backup Script for VPS Migration
set -e

BACKUP_DIR="backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
ARCHIVE_NAME="bot_full_backup_${TIMESTAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "=========================================================="
echo "📦 Generating Complete Bot & User Data Backup..."
echo "=========================================================="

# Checkpoint SQLite WAL database safely if python3 is available
if [ -f "bot_database.db" ]; then
    echo "[*] Checkpointing SQLite WAL database..."
    python3 -c "import sqlite3; con = sqlite3.connect('bot_database.db'); con.execute('PRAGMA wal_checkpoint(TRUNCATE);'); con.close()" 2>/dev/null || true
fi

# Package database, environment, and userbot sessions
tar -czf "${BACKUP_DIR}/${ARCHIVE_NAME}" \
    --exclude='downloads/*' \
    --exclude='__pycache__' \
    --exclude='venv' \
    bot_database.db .env sessions/ 2>/dev/null || \
tar -czf "${BACKUP_DIR}/${ARCHIVE_NAME}" bot_database.db .env 2>/dev/null

FILE_SIZE=$(du -h "${BACKUP_DIR}/${ARCHIVE_NAME}" | cut -f1)

echo "=========================================================="
echo "✅ Backup Completed Successfully!"
echo "• Archive: ${BACKUP_DIR}/${ARCHIVE_NAME}"
echo "• Size:    ${FILE_SIZE}"
echo "=========================================================="
echo "To copy this backup to your new VPS, run from your local PC:"
echo "  scp root@OLD_VPS_IP:$(pwd)/${BACKUP_DIR}/${ARCHIVE_NAME} ."
echo "  scp ${ARCHIVE_NAME} root@NEW_VPS_IP:/root/RESTRIC/"
echo "=========================================================="
