#!/bin/bash
# 1-Click Automated Git Update & Zero-Downtime Reload for VPS & Docker
set -e

echo "=========================================================="
echo "🔄 Updating Telegram Restricted Forward Bot via Git..."
echo "=========================================================="

# 1. Pull latest code from remote repository
echo "[*] Pulling latest changes from Git..."
git pull

# 2. Check if Docker is running
if [ -f "docker-compose.yml" ] && docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "telegram-bot"; then
    echo "[*] Rebuilding and restarting Docker containers..."
    docker compose up -d --build
    echo "=========================================================="
    echo "✅ Docker containers updated & restarted successfully!"
    echo "=========================================================="
    docker compose ps
    exit 0
fi

# 3. Update dependencies if requirements changed for Native mode
if [ -d "venv" ]; then
    source venv/bin/activate
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
fi

# 4. Restart systemd services
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet bot; then
        echo "[*] Restarting background bot service..."
        sudo systemctl restart bot
        echo "[+] bot.service restarted."
    fi

    if systemctl is-active --quiet bot-studio; then
        echo "[*] Restarting Web Studio service..."
        sudo systemctl restart bot-studio
        echo "[+] bot-studio.service restarted."
    fi

    echo "=========================================================="
    echo "✅ Bot updated & restarted successfully!"
    echo "=========================================================="
    sudo systemctl status bot --no-pager || true
else
    echo "[!] Not running systemd. If using manually, restart your 'python main.py' process."
fi
