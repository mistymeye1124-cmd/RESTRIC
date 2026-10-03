#!/bin/bash
# 1-Click Automated Git Update & Zero-Downtime Reload for VPS & Docker
# SESSIONS & DATABASE are physically backed up BEFORE any git operation.
# They are restored AFTER — so logout is IMPOSSIBLE regardless of git behavior.

set -e

echo "=========================================================="
echo "🔄 Updating Telegram Restricted Forward Bot via Git..."
echo "=========================================================="

# ──────────────────────────────────────────────────────────────
# PHASE 0: Physical backup of sessions + database BEFORE git
# ──────────────────────────────────────────────────────────────
BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
SAFE_DIR="/tmp/tgbot_session_safe_$$"   # $$ = PID, unique per run
mkdir -p "$SAFE_DIR/sessions"

echo "[*] Backing up sessions & database to $SAFE_DIR ..."

# Backup database (all .db files in project root)
for db_file in "$BOT_DIR"/*.db; do
    [ -f "$db_file" ] && cp "$db_file" "$SAFE_DIR/" 2>/dev/null && \
        echo "    [+] Backed up: $(basename $db_file)"
done

# Backup session files
if [ -d "$BOT_DIR/sessions" ]; then
    cp -r "$BOT_DIR/sessions/." "$SAFE_DIR/sessions/" 2>/dev/null || true
    SESSION_COUNT=$(find "$SAFE_DIR/sessions" -name "*.session" 2>/dev/null | wc -l)
    echo "    [+] Backed up $SESSION_COUNT session file(s)"
fi

# Backup .env (never lose credentials either)
[ -f "$BOT_DIR/.env" ] && cp "$BOT_DIR/.env" "$SAFE_DIR/.env" 2>/dev/null || true

echo "[✅] Backup complete. Now safe to pull from GitHub."

# ──────────────────────────────────────────────────────────────
# PHASE 1: Git pull latest code
# ──────────────────────────────────────────────────────────────
echo "[*] Fetching and pulling latest changes from Git..."
cd "$BOT_DIR"

git fetch origin main

# Stash only if tracked files have uncommitted changes (code changes, not db/sessions)
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo "[!] Stashing tracked file changes on VPS..."
    git stash push --include-untracked --message "auto-stash before update $(date '+%Y%m%d_%H%M%S')" 2>/dev/null || \
    git stash 2>/dev/null || true
fi

git pull origin main || {
    echo "[!] Standard pull failed, applying clean fast-forward sync..."
    git reset --hard origin/main
}

# Re-apply stash if any code-level stash exists
if git stash list 2>/dev/null | grep -q "stash@{0}"; then
    echo "[*] Restoring stashed code changes..."
    git stash pop 2>/dev/null || git stash drop 2>/dev/null || true
fi

# ──────────────────────────────────────────────────────────────
# PHASE 2: RESTORE sessions & database from physical backup
# This runs UNCONDITIONALLY — git cannot override this.
# ──────────────────────────────────────────────────────────────
echo "[*] Restoring sessions & database from safe backup..."

# Restore all backed-up .db files
for db_file in "$SAFE_DIR"/*.db; do
    [ -f "$db_file" ] && cp "$db_file" "$BOT_DIR/" 2>/dev/null && \
        echo "    [+] Restored: $(basename $db_file)"
done

# Restore session files (merge: don't wipe new ones, just restore old ones)
mkdir -p "$BOT_DIR/sessions"
if [ -d "$SAFE_DIR/sessions" ]; then
    cp -rn "$SAFE_DIR/sessions/." "$BOT_DIR/sessions/" 2>/dev/null || \
    rsync -a "$SAFE_DIR/sessions/" "$BOT_DIR/sessions/" 2>/dev/null || \
    cp -r  "$SAFE_DIR/sessions/." "$BOT_DIR/sessions/" 2>/dev/null || true
    SESSION_RESTORED=$(find "$BOT_DIR/sessions" -name "*.session" 2>/dev/null | wc -l)
    echo "    [+] $SESSION_RESTORED session file(s) confirmed on disk"
fi

# Restore .env
[ -f "$SAFE_DIR/.env" ] && cp "$SAFE_DIR/.env" "$BOT_DIR/.env" 2>/dev/null || true

echo "[✅] Sessions & database fully restored. Accounts are safe!"

# ──────────────────────────────────────────────────────────────
# PHASE 2.5: Auto-recovery audit (merge any stale/orphan accounts)
# ──────────────────────────────────────────────────────────────
if [ -d "$BOT_DIR/venv" ]; then
    source "$BOT_DIR/venv/bin/activate" 2>/dev/null || true
fi
python3 -c "
import sys; sys.path.insert(0, '.')
try:
    from core.auto_recover import run_auto_recovery
    import config
    count = run_auto_recovery(config.DB_PATH)
    print(f'[AutoRecover] {count} worker account(s) confirmed healthy in database.')
except Exception as e:
    print(f'[AutoRecover] skipped: {e}')
" 2>/dev/null || true

# Cleanup temp backup (optional — comment out to keep it as extra safety net)
rm -rf "$SAFE_DIR" 2>/dev/null || true

# ──────────────────────────────────────────────────────────────
# PHASE 3: Docker (if applicable)
# ──────────────────────────────────────────────────────────────
if [ -f "docker-compose.yml" ] && command -v docker >/dev/null 2>&1 && \
   docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "telegram-bot"; then
    echo "[*] Rebuilding and restarting Docker containers..."
    docker compose up -d --build
    echo "=========================================================="
    echo "✅ Docker containers updated & restarted successfully!"
    echo "=========================================================="
    docker compose ps
    exit 0
fi

# ──────────────────────────────────────────────────────────────
# PHASE 4: Update Python dependencies
# ──────────────────────────────────────────────────────────────
if [ -d "venv" ]; then
    echo "[*] Updating Python virtual environment dependencies..."
    source venv/bin/activate
    pip install --upgrade pip setuptools wheel --quiet
    pip install -r requirements.txt --quiet
fi

# Ensure directories exist
mkdir -p sessions downloads temp_sessions logs

# ──────────────────────────────────────────────────────────────
# PHASE 5: Network kernel tuning (Google BBR + 16MB buffers)
# ──────────────────────────────────────────────────────────────
if command -v sysctl >/dev/null 2>&1; then
    echo "[*] Activating Google BBR & high-speed 16MB TCP buffers..."
    sudo sysctl -w net.core.default_qdisc=fq                   >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_congestion_control=bbr          >/dev/null 2>&1 || true
    sudo sysctl -w net.core.rmem_max=16777216                   >/dev/null 2>&1 || true
    sudo sysctl -w net.core.wmem_max=16777216                   >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"      >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"      >/dev/null 2>&1 || true
    sudo sysctl -w net.ipv4.tcp_fastopen=3                      >/dev/null 2>&1 || true
fi

# ──────────────────────────────────────────────────────────────
# PHASE 6: Restart systemd services
# ──────────────────────────────────────────────────────────────
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
    echo "✅ Bot updated & restarted. Sessions preserved! 🔐"
    echo "=========================================================="
    sudo systemctl status bot --no-pager -n 5 2>/dev/null || true
else
    echo "[!] Not running systemd. Restart your 'python main.py' process manually."
fi
