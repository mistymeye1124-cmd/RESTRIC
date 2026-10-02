#!/bin/bash
# Hostinger VPS 1-Click Automated Setup for Telegram Restricted Content Bot
set -e

echo "=========================================================="
echo "🚀 Setting up Telegram Restricted Forward Bot on VPS..."
echo "=========================================================="

# 1. Update system packages
echo "[*] Updating apt repositories..."
sudo apt update -y

# 2. Install essential system dependencies
echo "[*] Installing Python 3, pip, ffmpeg, and fonts..."
sudo apt install -y python3 python3-pip python3-venv ffmpeg fonts-dejavu-core git curl

# 3. Create virtual environment
if [ ! -d "venv" ]; then
    echo "[*] Creating Python virtual environment..."
    python3 -m venv venv
fi

# 4. Activate virtual environment and install python packages
echo "[*] Installing Python requirements..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5. Create necessary runtime directories
mkdir -p downloads sessions data/branding

echo "=========================================================="
echo "✅ VPS Setup Completed Successfully!"
echo "To run bot in background using systemd:"
echo "  sudo cp bot.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable --now bot"
echo "To view live logs:"
echo "  sudo journalctl -u bot -f"
echo "=========================================================="
