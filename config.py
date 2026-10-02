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

# Admin User IDs and Channel/Group IDs who receive payment notifications, stats, and control panel
def _parse_admin_ids(raw_val: str) -> list[int]:
    parsed = []
    for x in raw_val.split(","):
        cleaned = x.strip()
        if not cleaned:
            continue
        try:
            val = int(cleaned)
            if val != 0:
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
PAYMENT_METHODS = {
    "bKash (Send Money)": os.getenv("BKASH_NUMBER", "017XXXXXXXX"),
    "Nagad (Send Money)": os.getenv("NAGAD_NUMBER", "018XXXXXXXX"),
    "Rocket": os.getenv("ROCKET_NUMBER", "019XXXXXXXX"),
    "Binance Pay ID / USDT": os.getenv("BINANCE_PAY_ID", "123456789"),
}

PREMIUM_PLANS = {
    "7_days": {"name": "7 Days VIP Pass", "price_bdt": 100, "days": 7},
    "30_days": {"name": "30 Days VIP Pass", "price_bdt": 250, "days": 30},
    "lifetime": {"name": "Lifetime VIP Access", "price_bdt": 600, "days": 3650},
}

# ----------------- QUOTAS & CONCURRENCY -----------------
# Free tier limitations
FREE_DAILY_DOWNLOAD_LIMIT = 3        # Number of downloads free users can do per 24 hours
FREE_MAX_BATCH_SIZE = 1              # Only 1 video at a time for free users

# Premium tier advantages
PREMIUM_DAILY_DOWNLOAD_LIMIT = 100   # Effectively unlimited
PREMIUM_MAX_BATCH_SIZE = 30          # Can paste 30 links at once

# Concurrency: Maximum simultaneous downloads (Auto-tunes to hardware cores, min 12 workers)
MAX_CONCURRENT_WORKERS = int(os.getenv("MAX_CONCURRENT_WORKERS", max(12, (os.cpu_count() or 4) * 3)))

# Throttle interval in seconds for editing Telegram progress messages (prevents FloodWait)
# 2.5s is the sweet spot: snappy UI without hitting Telegram's edit rate-limit
PROGRESS_UPDATE_INTERVAL = 2.5

# Web Studio Dashboard & Mini App URL
WEB_DASHBOARD_URL = os.getenv("WEB_DASHBOARD_URL", "http://127.0.0.1:8888")
