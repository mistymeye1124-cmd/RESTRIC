#!/bin/bash
# ==============================================================================
# 🚀 1-CLICK UNIVERSAL VPS & CLOUD DEPLOYMENT SCRIPT
# Project: Telegram Restricted Content Bot & Enterprise Web Studio
# Author: CYBR-MAHI Engine
# ==============================================================================

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}==================================================================${NC}"
echo -e "${GREEN}      🚀 TELEGRAM RESTRICTED CONTENT BOT — 1-CLICK DEPLOY       ${NC}"
echo -e "${CYAN}==================================================================${NC}"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# 0. Safety Backup (Guarantees accounts, database & sessions are never lost during redeploy)
SAFE_BACKUP="/tmp/tgbot_deploy_safe_$$"
PERSIST_BACKUP="/var/backups/tgbot_deploy_safe"
mkdir -p "$SAFE_BACKUP" "$PERSIST_BACKUP" 2>/dev/null || true

for db_file in "$PROJECT_DIR"/*.db; do
    [ -f "$db_file" ] && cp "$db_file" "$SAFE_BACKUP/" 2>/dev/null && cp "$db_file" "$PERSIST_BACKUP/" 2>/dev/null || true
done
[ -d "$PROJECT_DIR/sessions" ] && cp -r "$PROJECT_DIR/sessions" "$SAFE_BACKUP/" 2>/dev/null && cp -r "$PROJECT_DIR/sessions" "$PERSIST_BACKUP/" 2>/dev/null || true
[ -d "$PROJECT_DIR/data" ] && cp -r "$PROJECT_DIR/data" "$SAFE_BACKUP/" 2>/dev/null && cp -r "$PROJECT_DIR/data" "$PERSIST_BACKUP/" 2>/dev/null || true
[ -f "$PROJECT_DIR/.env" ] && cp "$PROJECT_DIR/.env" "$SAFE_BACKUP/" 2>/dev/null && cp "$PROJECT_DIR/.env" "$PERSIST_BACKUP/" 2>/dev/null || true

# 1. Detect Operating System & Package Manager
echo -e "\n${YELLOW}[Step 1/6] Detecting System Environment...${NC}"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION=$VERSION_ID
    echo -e "Detected OS: ${GREEN}$NAME ($VERSION)${NC}"
else
    OS="unknown"
    echo -e "Detected OS: ${YELLOW}Unknown Linux${NC}"
fi

# Determine privilege wrapper
SUDO=""
if [ "$EUID" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        echo -e "${RED}[ERROR] Please run as root or install sudo.${NC}"
        exit 1
    fi
fi

# 2. Check and Setup Configuration (.env)
echo -e "\n${YELLOW}[Step 2/6] Verifying Configuration (.env)...${NC}"
if [ ! -f ".env" ]; then
    if [ -f "$SAFE_BACKUP/.env" ]; then
        cp "$SAFE_BACKUP/.env" .env
    elif [ -f "$PERSIST_BACKUP/.env" ]; then
        cp "$PERSIST_BACKUP/.env" .env
    elif [ -f ".env.example" ]; then
        echo -e "Creating .env from .env.example..."
        cp .env.example .env
    else
        touch .env
    fi
fi

# Quick interactive setup if credentials are blank and running in interactive terminal
if [ -t 0 ]; then
    source .env 2>/dev/null || true
    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ "$TELEGRAM_BOT_TOKEN" = "your_bot_token_here" ] || [ -z "$TELEGRAM_API_ID" ]; then
        echo -e "${YELLOW}Notice: Telegram credentials missing in .env.${NC}"
        read -p "Enter BOT_TOKEN (from @BotFather): " input_token
        read -p "Enter API_ID (from my.telegram.org): " input_id
        read -p "Enter API_HASH (from my.telegram.org): " input_hash
        read -p "Enter Admin User ID(s) [e.g. 12345678]: " input_admin

        [ -n "$input_token" ] && sed -i.bak "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$input_token|" .env 2>/dev/null || echo "TELEGRAM_BOT_TOKEN=$input_token" >> .env
        [ -n "$input_id" ] && sed -i.bak "s|^TELEGRAM_API_ID=.*|TELEGRAM_API_ID=$input_id|" .env 2>/dev/null || echo "TELEGRAM_API_ID=$input_id" >> .env
        [ -n "$input_hash" ] && sed -i.bak "s|^TELEGRAM_API_HASH=.*|TELEGRAM_API_HASH=$input_hash|" .env 2>/dev/null || echo "TELEGRAM_API_HASH=$input_hash" >> .env
        [ -n "$input_admin" ] && sed -i.bak "s|^ADMIN_IDS=.*|ADMIN_IDS=$input_admin|" .env 2>/dev/null || echo "ADMIN_IDS=$input_admin" >> .env
        rm -f .env.bak
        echo -e "${GREEN}Credentials saved to .env!${NC}"
    fi
fi

# 3. Create Runtime Directories & Prevent Docker File-as-Directory Trap
echo -e "\n${YELLOW}[Step 3/6] Initializing Storage Directories & Databases...${NC}"
mkdir -p downloads sessions data/branding scratch
touch bot_database.db restricted_v2.db
chmod 755 downloads sessions data scratch 2>/dev/null || true

# Restore database and sessions if available in safe backup
for db_file in "$SAFE_BACKUP"/*.db; do
    [ -f "$db_file" ] && cp -n "$db_file" "$PROJECT_DIR/" 2>/dev/null || true
done
[ -d "$SAFE_BACKUP/sessions" ] && cp -rn "$SAFE_BACKUP/sessions/." "$PROJECT_DIR/sessions/" 2>/dev/null || true
[ -d "$SAFE_BACKUP/data" ] && cp -rn "$SAFE_BACKUP/data/." "$PROJECT_DIR/data/" 2>/dev/null || true

# 4. Choose Deployment Method (Docker or Native Systemd)
DEPLOY_MODE="native"
if [ "$1" == "--docker" ]; then
    DEPLOY_MODE="docker"
elif [ -z "$1" ] && [ -t 0 ]; then
    echo -e "\nSelect Deployment Mode:"
    echo -e "  1) ${GREEN}Native Systemd Services${NC} (Recommended - Fast, lightweight, auto-starts on boot)"
    echo -e "  2) ${GREEN}Docker Compose Container${NC} (Isolated, containerized)"
    read -p "Choice [1/2] (Default: 1): " choice
    if [ "$choice" == "2" ]; then
        DEPLOY_MODE="docker"
    fi
fi

if [ "$DEPLOY_MODE" == "docker" ]; then
    echo -e "\n${YELLOW}[Step 4/6] Configuring Docker Deployment...${NC}"
    if ! command -v docker >/dev/null 2>&1; then
        echo -e "[*] Installing Docker..."
        curl -fsSL https://get.docker.com | $SUDO sh
        $SUDO systemctl enable --now docker
    fi

    # Crucial: touch database files before mounting volume in Docker
    touch bot_database.db restricted_v2.db

    echo -e "[*] Building and starting Docker containers..."
    $SUDO docker compose up -d --build
    echo -e "${GREEN}Docker container is running!${NC}"
else
    # Native Linux Systemd Deployment
    echo -e "\n${YELLOW}[Step 4/6] Installing System Dependencies & FFmpeg...${NC}"
    if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
        $SUDO apt-get update -y
        $SUDO apt-get install -y python3 python3-pip python3-venv ffmpeg fonts-dejavu-core git curl build-essential libssl-dev libffi-dev
    elif [ "$OS" = "centos" ] || [ "$OS" = "almalinux" ] || [ "$OS" = "rocky" ] || [ "$OS" = "fedora" ]; then
        $SUDO dnf install -y epel-release || true
        $SUDO dnf install -y python3 python3-pip python3-devel ffmpeg git curl gcc openssl-devel libffi-devel
    elif [ "$OS" = "alpine" ]; then
        $SUDO apk add --no-cache python3 py3-pip py3-virtualenv ffmpeg git curl build-base libffi-dev openssl-dev
    fi

    echo -e "\n${YELLOW}[Step 5/6] Setting up Python Virtual Environment...${NC}"
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt

    # Setup Systemd Services
    echo -e "\n${YELLOW}[Step 6/6] Configuring Systemd Auto-Start Daemons...${NC}"
    CUR_USER=$(whoami)

    # 1. Bot Service
    cat <<EOF | $SUDO tee /etc/systemd/system/bot.service > /dev/null
[Unit]
Description=Telegram Restricted Forward Bot Service
After=network.target

[Service]
Type=simple
User=$CUR_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python $PROJECT_DIR/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

    # 2. Web Studio Service
    cat <<EOF | $SUDO tee /etc/systemd/system/bot-studio.service > /dev/null
[Unit]
Description=Telegram Bot Web Studio Cockpit
After=network.target

[Service]
Type=simple
User=$CUR_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python $PROJECT_DIR/run_studio.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

    # Run auto-recovery audit to ensure all sessions from vault, env, and backups are healthy
    echo -e "\n${YELLOW}[*] Running Session Vault & Multi-Account Auto-Recovery...${NC}"
    $PROJECT_DIR/venv/bin/python -c "
import sys; sys.path.insert(0, '.')
try:
    from core.auto_recover import run_auto_recovery
    import config
    count = run_auto_recovery(config.DB_PATH)
    print(f'[AutoRecover] {count} worker account(s) confirmed healthy in database.')
except Exception as e:
    print(f'[AutoRecover] skipped: {e}')
" 2>/dev/null || true

    $SUDO systemctl daemon-reload
    $SUDO systemctl enable --now bot
    $SUDO systemctl enable --now bot-studio

    echo -e "${GREEN}Services started and registered with systemd!${NC}"
fi

# Detect Public IP
SERVER_IP=$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')

echo -e "\n${CYAN}==================================================================${NC}"
echo -e "${GREEN}🎉 CONGRATULATIONS! DEPLOYMENT IS COMPLETE & RUNNING!${NC}"
echo -e "${CYAN}==================================================================${NC}"
echo -e "• Telegram Bot Status:   ${GREEN}Active & Auto-Restarting${NC}"
echo -e "• Web Studio Cockpit:   ${GREEN}http://${SERVER_IP}:8888${NC}"
echo -e "\n${YELLOW}Useful Management Commands:${NC}"
echo -e "  View Bot Logs:         ${CYAN}sudo journalctl -u bot -f${NC} (or: docker compose logs -f)"
echo -e "  Restart Bot:           ${CYAN}sudo systemctl restart bot${NC}"
echo -e "  Stop Bot:              ${CYAN}sudo systemctl stop bot${NC}"
echo -e "  Update from GitHub:    ${CYAN}bash update.sh${NC}"
echo -e "${CYAN}==================================================================${NC}\n"
