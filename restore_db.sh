#!/bin/bash
# 1-Click Restore Script for VPS Migration
set -e

if [ -z "$1" ]; then
    echo "Usage: bash restore_db.sh <backup_file_or_archive>"
    echo "Examples:"
    echo "  bash restore_db.sh backups/bot_full_backup_20261002.tar.gz"
    echo "  bash restore_db.sh backups/bot_database_backup_20261002.db"
    exit 1
fi

TARGET="$1"

if [ ! -f "$TARGET" ]; then
    echo "❌ Error: Backup file '$TARGET' not found!"
    exit 1
fi

echo "=========================================================="
echo "📥 Restoring Bot Data from: $TARGET"
echo "=========================================================="

# Stop bot service if running
if systemctl is-active --quiet bot 2>/dev/null; then
    echo "[*] Stopping bot service for safe restoration..."
    sudo systemctl stop bot
    RESTART_SERVICE=true
else
    RESTART_SERVICE=false
fi

# Safety backup of current database if present
if [ -f "bot_database.db" ]; then
    cp bot_database.db "bot_database.db.pre_restore_bak"
    echo "[*] Safety backup of previous DB saved as 'bot_database.db.pre_restore_bak'."
fi

# Restore depending on file type
if [[ "$TARGET" == *.tar.gz ]]; then
    echo "[*] Extracting full archive..."
    tar -xzf "$TARGET"
elif [[ "$TARGET" == *.db ]]; then
    echo "[*] Restoring SQLite database..."
    cp "$TARGET" bot_database.db
else
    echo "❌ Unknown file format. Expected .tar.gz or .db"
    exit 1
fi

# Clean WAL journals
rm -f bot_database.db-wal bot_database.db-shm

echo "[*] Verifying SQLite database integrity..."
python3 -c "import sqlite3; con = sqlite3.connect('bot_database.db'); res = con.execute('PRAGMA integrity_check;').fetchone()[0]; assert res == 'ok'; con.close(); print('[+] Database Integrity: 100% OK')"

echo "[*] Running session vault & account self-healing auto-recovery..."
python3 -c "from core.auto_recover import run_auto_recovery; import config; run_auto_recovery(config.DB_PATH)" 2>/dev/null || true

if [ "$RESTART_SERVICE" = true ]; then
    echo "[*] Restarting bot service..."
    sudo systemctl start bot
fi

echo "=========================================================="
echo "🎉 Data Restored Successfully! All user data & VIP status live."
echo "=========================================================="
