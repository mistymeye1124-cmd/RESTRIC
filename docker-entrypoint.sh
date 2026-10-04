#!/bin/bash
# language: Bash, file: docker-entrypoint.sh, target: Docker/Dokploy/OpenShift
set -e

echo "=========================================================="
echo "🚀 Restricted Forward Bot & Web Studio Container Engine"
echo "   Auto-Deploy & Session Immunity Guard (Dokploy Active)"
echo "=========================================================="

# 1. Ensure runtime directories exist
mkdir -p /app/downloads /app/sessions /app/data /app/scratch /app/backups /app/cookies /app/data/cookies
chmod 755 /app/downloads /app/sessions /app/data /app/scratch /app/cookies 2>/dev/null || true

# 1.1 Automated Clean-up: Purge old download/scratch remnants and unlock SQLite sessions
echo "[*] Cleaning old temporary debris and stale session locks..."
find /app/downloads -type f -mmin +10 -delete 2>/dev/null || true
find /app/scratch -type f -mmin +10 -delete 2>/dev/null || true
rm -f /app/*.session-journal /app/*.session-wal /app/sessions/*.session-journal /app/sessions/*.session-wal 2>/dev/null || true

# Restore global YouTube cookies if in persistent data storage
if [ -f "/app/data/cookies/youtube_cookies.txt" ]; then
    cp -f "/app/data/cookies/youtube_cookies.txt" "/app/cookies/youtube_cookies.txt" 2>/dev/null || true
    cp -f "/app/data/cookies/youtube_cookies.txt" "/app/cookies/cookies.txt" 2>/dev/null || true
fi

# 2. Prevent Docker directory mount trap for SQLite files
touch /app/bot_database.db /app/restricted_v2.db

# 3. Check if .env exists, or restore from /app/data/.env or .env.example
if [ ! -f "/app/.env" ]; then
    if [ -f "/app/data/.env" ]; then
        echo "[+] Restoring .env from persistent data vault..."
        cp /app/data/.env /app/.env
    elif [ -f "/app/.env.example" ]; then
        echo "[!] .env not found. Creating from .env.example..."
        cp /app/.env.example /app/.env
    fi
fi

# Backup current .env to persistent data folder
[ -f "/app/.env" ] && cp "/app/.env" "/app/data/.env" 2>/dev/null || true

# 4. Run Session Vault & Self-Healing Auto-Recovery on every deploy/redeploy
echo "[*] Running Session Vault & Self-Healing Auto-Recovery..."
python3 -c "
import sys; sys.path.insert(0, '/app')
try:
    from core.auto_recover import run_auto_recovery
    import config
    count = run_auto_recovery(config.DB_PATH)
    print(f'[Container Entrypoint] {count} worker account(s) verified & healthy in database.')
except Exception as e:
    print(f'[Container Entrypoint] Auto-recovery note: {e}')
" 2>/dev/null || true

# 5. Trap termination signals for graceful shutdown and auto-sync
shutdown() {
    echo "[*] Graceful shutdown signal received. Syncing session vault..."
    python3 -c "
import sys; sys.path.insert(0, '/app')
try:
    from core.auto_recover import sync_db_to_sessions_vault
    import config
    sync_db_to_sessions_vault(config.DB_PATH)
except Exception:
    pass
" 2>/dev/null || true
    echo "[*] Stopping services..."
    kill -TERM "$BOT_PID" 2>/dev/null || true
    kill -TERM "$STUDIO_PID" 2>/dev/null || true
    wait
    exit 0
}
trap shutdown SIGTERM SIGINT

MODE="${SERVICE_TYPE:-both}"

case "$MODE" in
    bot)
        echo "[*] Starting Telegram Bot Engine..."
        exec python3 /app/main.py
        ;;
    studio)
        echo "[*] Starting Web Studio Cockpit on port 8888..."
        exec python3 /app/run_studio.py
        ;;
    both|*)
        echo "[*] Launching both Telegram Bot Engine and Web Studio Cockpit..."
        python3 /app/run_studio.py &
        STUDIO_PID=$!
        python3 /app/main.py &
        BOT_PID=$!
        wait -n $STUDIO_PID $BOT_PID
        ;;
esac
