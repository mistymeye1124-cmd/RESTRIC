#!/bin/bash
# 1-Click Automated Git Update & Zero-Downtime Reload for VPS
set -e

echo "=========================================================="
echo "🔄 Updating Telegram Restricted Forward Bot via Git..."
echo "=========================================================="

# 1. Pull latest code from remote repository
echo "[*] Pulling latest changes from Git..."
git pull

# 2. Update dependencies if requirements changed
if [ -d "venv" ]; then
    source venv/bin/activate
    pip install -r requirements.txt
fi

# 3. Restart systemd bot service
if systemctl is-active --quiet bot; then
    echo "[*] Restarting background bot service..."
    sudo systemctl restart bot
    echo "=========================================================="
    echo "✅ Bot updated & restarted successfully!"
    echo "=========================================================="
    sudo systemctl status bot --no-pager
else
    echo "[!] Bot service is not active. Run 'bash start.sh' or 'sudo systemctl enable --now bot'."
fi
