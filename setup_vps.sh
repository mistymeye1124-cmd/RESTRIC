#!/bin/bash
# Hostinger VPS 1-Click Automated Setup for Telegram Restricted Content Bot
set -e

echo "=========================================================="
echo "🚀 Setting up Telegram Restricted Forward Bot on VPS..."
echo "=========================================================="

# 1. Update system packages
echo "[*] Updating apt repositories..."
sudo apt update -y

# 2. Install essential system & C-compilation dependencies
echo "[*] Installing Python 3, pip, venv, ffmpeg, build-essential, and system libraries..."
sudo apt install -y python3 python3-pip python3-venv ffmpeg fonts-dejavu-core git curl build-essential python3-dev libssl-dev libffi-dev

# 3. Create virtual environment
if [ ! -d "venv" ]; then
    echo "[*] Creating Python virtual environment..."
    python3 -m venv venv
fi

# 4. Activate virtual environment and install python packages
echo "[*] Installing Python requirements..."
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# 5. Create necessary runtime directories
mkdir -p downloads sessions data/branding

# 6. Auto-generate systemd service with dynamic current directory & user
CUR_DIR=$(pwd)
CUR_USER=$(whoami)
echo "[*] Configuring systemd service for directory: $CUR_DIR (User: $CUR_USER)..."
cat <<EOF | sudo tee /etc/systemd/system/bot.service > /dev/null
[Unit]
Description=Telegram Restricted Forward Bot Daemon
After=network.target

[Service]
Type=simple
User=$CUR_USER
WorkingDirectory=$CUR_DIR
ExecStart=$CUR_DIR/venv/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

# 7. Permanent Linux BBR & High-Speed TCP Buffer Optimization (50+ MB/s Wire Speed)
echo "[*] Permanently configuring Google BBR Congestion Control & 16MB TCP Buffers..."
cat <<EOF | sudo tee /etc/sysctl.d/99-bbr.conf > /dev/null
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_fastopen = 3
EOF
sudo sysctl --system > /dev/null 2>&1 || true

echo "=========================================================="
echo "✅ VPS Setup & systemd Service Configured Successfully!"
echo "To start the bot now:"
echo "  sudo systemctl enable --now bot"
echo "To view live logs:"
echo "  sudo journalctl -u bot -f"
echo "To restart bot:"
echo "  sudo systemctl restart bot"
echo "=========================================================="
