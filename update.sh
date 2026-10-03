#!/bin/bash
# 1-Click Automated Git Update & Zero-Downtime Reload for VPS & Docker
set -e

echo "=========================================================="
echo "🔄 Updating Telegram Restricted Forward Bot via Git..."
echo "=========================================================="

# 1. Pull latest code from remote repository safely
echo "[*] Fetching and pulling latest changes from Git..."
# Prevent local modifications on VPS from blocking update while preserving .env and database
git fetch origin main

# Check if there are local uncommitted changes to tracked files
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo "[!] Stashing temporary local changes on VPS..."
    git stash
fi

git pull origin main || {
    echo "[!] Standard pull failed, applying clean fast-forward sync..."
    git reset --hard origin/main
}

# 2. Check if Docker is running
if [ -f "docker-compose.yml" ] && command -v docker >/dev/null 2>&1 && docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "telegram-bot"; then
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
    echo "[*] Updating Python virtual environment dependencies..."
    source venv/bin/activate
    pip install --upgrade pip setuptools wheel --quiet
    pip install -r requirements.txt --quiet
fi

# 3.5 Ensure sessions and data directories exist safely
mkdir -p sessions downloads temp_sessions logs

# 3.8 Optimize Linux Network Kernel (Google BBR & 16MB TCP Buffers for 50+ MB/s)
if command -v sysctl >/dev/null 2>&1; then
    echo "[*] Activating Google BBR & high-speed 16MB TCP buffers..."
    sudo sysctl -w net.core.default_qdisc=fq >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1 || true
    sudo sysctl -w net.core.rmem_max=16777216 >/dev/null 2>&1 || true
    sudo sysctl -w net.core.wmem_max=16777216 >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216" >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216" >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_fastopen=3 >/dev/null 2>&1 || true
fi

# 4. Restart systemd services
if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl daemon-reload 2>/dev/null || true

    if systemctl is-active --quiet bot 2>/dev/null; then
        echo "[*] Restarting background bot service..."
        sudo systemctl restart bot
        echo "[+] bot.service restarted."
    elif [ -f "/etc/systemd/system/bot.service" ]; then
        echo "[*] Starting bot service..."
        sudo systemctl start bot
        echo "[+] bot.service started."
    fi

    if systemctl is-active --quiet bot-studio 2>/dev/null; then
        echo "[*] Restarting Web Studio service..."
        sudo systemctl restart bot-studio
        echo "[+] bot-studio.service restarted."
    fi

    echo "=========================================================="
    echo "✅ Bot updated & restarted successfully!"
    echo "=========================================================="
    sudo systemctl status bot --no-pager -n 5 2>/dev/null || true
else
    echo "[!] Not running systemd. If running in screen/tmux or manually, restart your 'python main.py' process."
fi
