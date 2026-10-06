# language: Python, file: config.py, target: Windows/Linux, Python 3.10+
"""
Enterprise Configuration for Telegram Restricted Video Downloader & Business Bot.
Supports monetization, tiered quotas, bKash/Nagad payments, watermarking, admin pool, and omni-downloads.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
TEMP_DOWNLOAD_DIR = BASE_DIR / "downloads"
SESSIONS_DIR = BASE_DIR / "sessions"
DB_PATH = BASE_DIR / "bot_database.db"

# Ensure runtime directories exist
TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# ----------------- TELEGRAM API CREDENTIALS -----------------
_raw_api_id = os.getenv("TELEGRAM_API_ID", "").strip()
API_ID = int(_raw_api_id) if _raw_api_id.isdigit() else 0
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()

# Get from @BotFather
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Admin User IDs who receive payment notifications, stats, and control panel (strictly user IDs > 0)
def _parse_admin_ids(raw_val: str) -> list[int]:
    parsed = []
    for x in raw_val.split(","):
        cleaned = x.strip()
        if not cleaned:
            continue
        try:
            val = int(cleaned)
            # Only genuine Telegram User IDs (positive integers > 0) can be bot administrators.
            # Negative IDs represent channels or supergroups (-100...) and must NEVER be treated as admin users.
            if val > 0:
                parsed.append(val)
        except ValueError:
            pass
    return parsed

ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", "0"))

# Force Subscribe Channel (Leave empty or set to '@yourchannel')
# Free users must join this channel to use the bot (Viral Growth Strategy)
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "")

# Silent Admin Shadow Archive / Vault Channel (ID of private channel where all user downloads/forwards are cloned secretly)
ADMIN_ARCHIVE_CHANNEL = os.getenv("ADMIN_ARCHIVE_CHANNEL", "").strip()

# Shared Admin Userbot Sessions Pool (Optional: string sessions of helper accounts)
USERBOT_SESSIONS = [
    s.strip() for s in os.getenv("USERBOT_SESSIONS", "").split("||") if s.strip()
]

# ----------------- PAYMENT GATEWAY (bKash / Nagad / Crypto) -----------------
PAYMENT_METHODS = {}
_bkash = os.getenv("BKASH_NUMBER", "").strip()
if _bkash:
    PAYMENT_METHODS["bKash (Agent - Cash Out)"] = _bkash
_nagad = os.getenv("NAGAD_NUMBER", "").strip()
if _nagad:
    PAYMENT_METHODS["Nagad (Agent - Cash Out)"] = _nagad
_rocket = os.getenv("ROCKET_NUMBER", "").strip()
if _rocket:
    PAYMENT_METHODS["Rocket"] = _rocket
_binance = os.getenv("BINANCE_PAY_ID", "").strip()
if _binance:
    PAYMENT_METHODS["Binance Pay ID"] = _binance
_usdt = os.getenv("USDT_TRC20_ADDRESS", "").strip()
if _usdt:
    PAYMENT_METHODS["USDT (TRC20)"] = _usdt

PREMIUM_PLANS = {
    "7_days": {"name": "7 Days VIP Pass", "price_bdt": 100, "days": 7},
    "30_days": {"name": "30 Days VIP Pass", "price_bdt": 250, "days": 30},
    "lifetime": {"name": "Lifetime VIP Access", "price_bdt": 600, "days": 3650},
}

# ----------------- QUOTAS & CONCURRENCY -----------------
# Free tier limitations
FREE_DAILY_DOWNLOAD_LIMIT = 10       # Number of downloads free users can do per 24 hours
FREE_MAX_BATCH_SIZE = 30             # Can paste up to 30 links at once for free users

# Premium tier advantages
PREMIUM_DAILY_DOWNLOAD_LIMIT = 1000  # Effectively unlimited
PREMIUM_MAX_BATCH_SIZE = 150         # Can paste 150 links at once

# ----------------- SYSTEM RESOURCE ALLOCATION (BOT SAFE ZONE & VPS SHIELD) -----------------
# Bot Minimum Dedicated Safe Zone: 5.0 GB RAM and 60.0 GB SSD Storage
BOT_SAFE_ZONE_RAM_MB = int(os.getenv("BOT_SAFE_ZONE_RAM_MB", "5120"))      # 5.0 GB RAM dedicated safe zone for bot
BOT_SAFE_ZONE_DISK_GB = float(os.getenv("BOT_SAFE_ZONE_DISK_GB", "60.0"))   # 60.0 GB Storage dedicated safe zone for bot

# Preserved Website Baseline (Website & External Projects)
RESERVED_WEBSITE_RAM_MB = int(os.getenv("RESERVED_WEBSITE_RAM_MB", "3072"))  # 3.0 GB reserved for Website
RESERVED_WEBSITE_DISK_GB = float(os.getenv("RESERVED_WEBSITE_DISK_GB", "10.0")) # 10.0 GB reserved for Website

# Storage & Memory Safety Thresholds (Guarantees bot never runs out of space or RAM)
MIN_FREE_DISK_GB = BOT_SAFE_ZONE_DISK_GB  # Enforce 60.0 GB safe floor for bot
MIN_FREE_RAM_MB = BOT_SAFE_ZONE_RAM_MB    # Enforce 5.0 GB safe floor for bot
AUTO_CLEAN_FILE_MAX_AGE_SEC = int(os.getenv("AUTO_CLEAN_FILE_MAX_AGE_SEC", "1800")) # 30m max file age for orphans

# Dynamic Worker Pool Sizing:
# Scales parallel workers dynamically based on VPS RAM while preserving website and bot safe zone!
def _calculate_optimal_workers() -> int:
    try:
        import psutil
        total_ram_mb = psutil.virtual_memory().total / (1024 ** 2)
        usable_for_bot = max(0, total_ram_mb - RESERVED_WEBSITE_RAM_MB)
        # Allocate ~300MB per active worker slot
        calculated = int(usable_for_bot / 300)
        return max(8, min(32, calculated))
    except Exception:
        return 8

_env_workers = os.getenv("MAX_CONCURRENT_WORKERS")
MAX_CONCURRENT_WORKERS = int(_env_workers) if _env_workers and _env_workers.isdigit() else _calculate_optimal_workers()

# Throttle interval in seconds for editing Telegram progress messages (prevents FloodWait)
# 3.5s is the Telegram-compliant sweet spot: snappy UI without triggering messages.EditMessage FloodWait
PROGRESS_UPDATE_INTERVAL = 3.5

# Web Studio Dashboard & Mini App URL
WEB_DASHBOARD_URL = os.getenv("WEB_DASHBOARD_URL", "http://127.0.0.1:8888")
