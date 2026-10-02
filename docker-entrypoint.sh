#!/bin/bash
# language: Bash, file: docker-entrypoint.sh, target: Docker/OpenShift
set -e

echo "=========================================================="
echo "🚀 Restricted Forward Bot & Web Studio Container Engine"
echo "=========================================================="

# Ensure runtime directories exist
mkdir -p /app/downloads /app/sessions /app/data /app/scratch

# Check if .env exists
if [ ! -f "/app/.env" ] && [ -f "/app/.env.example" ]; then
    echo "[!] .env not found. Creating from .env.example..."
    cp /app/.env.example /app/.env
fi

# Trap termination signals for graceful shutdown
shutdown() {
    echo "[*] Graceful shutdown signal received. Stopping services..."
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
