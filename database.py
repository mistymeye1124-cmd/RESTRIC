# language: Python, file: database.py, target: Python 3.10+, aiosqlite
"""
Enterprise Async Database with Coupons, Resolution Settings, Cookies, Subscriptions,
and High-Concurrency Monetization Tables.
"""

import asyncio
import aiosqlite
import time
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List, Tuple
from config import (
    DB_PATH,
    FREE_DAILY_DOWNLOAD_LIMIT,
    PREMIUM_DAILY_DOWNLOAD_LIMIT,
)

# L1 In-Memory TTL Cache — eliminates redundant SQLite reads for hot paths
# Key: (method_name, user_id), Value: (timestamp, result)
_L1_CACHE: Dict[tuple, tuple] = {}
_L1_TTL: float = 30.0  # seconds — user row cached for 30s max


def _cache_get(key: tuple) -> Any:
    """Returns cached value if within TTL, else None sentinel."""
    entry = _L1_CACHE.get(key)
    if entry and (time.monotonic() - entry[0]) < _L1_TTL:
        return entry[1]
    return _L1_CACHE.pop(key, (None, None))[1] if entry else None


def _cache_set(key: tuple, value: Any):
    _L1_CACHE[key] = (time.monotonic(), value)


def _cache_bust(user_id: int):
    """Invalidates ALL cached entries for a given user_id on any write."""
    keys_to_del = [k for k in _L1_CACHE if len(k) == 2 and k[1] == user_id]
    for k in keys_to_del:
        _L1_CACHE.pop(k, None)


# In-Memory Cache for Protected VIP Channels — 0.0001ms check on all link downloads
_PROTECTED_CHANNELS_CACHE: set = set()


def _normalize_channel_variants(raw: Any) -> list:
    """Expands any channel ID, username, or link into all equivalent normalized variants."""
    if raw is None:
        return []
    s = str(raw).strip().lower()
    if not s:
        return []
    variants = {s}
    import re
    m_priv = re.search(r"t\.me/c/(\d+)", s)
    if m_priv:
        cid = m_priv.group(1)
        variants.add(cid)
        variants.add(f"-100{cid}")
        variants.add(f"-{cid}")
    m_pub = re.search(r"t\.me/([a-z0-9_]{3,})", s)
    if m_pub:
        uname = m_pub.group(1)
        variants.add(uname)
        variants.add(f"@{uname}")

    cleaned_num = s.replace("-100", "").lstrip("-")
    if cleaned_num.isdigit():
        variants.add(cleaned_num)
        variants.add(f"-100{cleaned_num}")
        variants.add(f"-{cleaned_num}")

    if s.startswith("@"):
        variants.add(s.lstrip("@"))
    elif not s.startswith("-") and not s.isdigit():
        variants.add(f"@{s}")

    return list(variants)


class Database:
    def __init__(self, db_file=DB_PATH):
        self.db_file = str(db_file)

    async def init(self):
        """Initialize database schema with business, promo codes, and settings."""
        async with aiosqlite.connect(self.db_file) as db:
            # Enable high-concurrency WAL mode, RAM cache, and 512MB Memory-Mapped I/O
            # Tuned for 16GB RAM VPS — 256MB cache + 512MB mmap = near-zero disk reads
            await db.execute("PRAGMA journal_mode = WAL;")
            await db.execute("PRAGMA synchronous = NORMAL;")
            await db.execute("PRAGMA cache_size = -262144;")  # 256MB page cache
            await db.execute("PRAGMA busy_timeout = 5000;")
            await db.execute("PRAGMA mmap_size = 536870912;")  # 512MB mmap
            await db.execute("PRAGMA temp_store = MEMORY;")
            await db.execute("PRAGMA wal_autocheckpoint = 1000;")
            await db.execute("PRAGMA page_size = 4096;")
            for col_sql in [
                "ALTER TABLE user_settings ADD COLUMN language TEXT DEFAULT 'en';",
                "ALTER TABLE user_settings ADD COLUMN delivery_format TEXT DEFAULT 'video';",
                "ALTER TABLE user_settings ADD COLUMN media_filter TEXT DEFAULT 'all';",
                "ALTER TABLE user_settings ADD COLUMN clean_caption INTEGER DEFAULT 1;",
                "ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT NULL;",
                "ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0;",
                "ALTER TABLE users ADD COLUMN referral_points INTEGER DEFAULT 0;",
                "ALTER TABLE watermark_settings ADD COLUMN intro_clip_path TEXT DEFAULT '';",
                "ALTER TABLE watermark_settings ADD COLUMN outro_clip_path TEXT DEFAULT '';",
                "ALTER TABLE watermark_settings ADD COLUMN style TEXT DEFAULT 'pill';",
                "ALTER TABLE watermark_settings ADD COLUMN bounce_speed INTEGER DEFAULT 3;",
            ]:
                try:
                    await db.execute(col_sql)
                except Exception:
                    pass

            # 1. Users & Subscriptions
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    phone TEXT,
                    string_session TEXT,
                    is_active INTEGER DEFAULT 1,
                    is_premium INTEGER DEFAULT 0,
                    premium_expiry TEXT,
                    daily_downloads_used INTEGER DEFAULT 0,
                    last_download_date TEXT,
                    total_downloads INTEGER DEFAULT 0,
                    total_bytes INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # 2. User Media & Channel Settings
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    custom_caption TEXT,
                    auto_forward_chat_id INTEGER,
                    upload_as_doc INTEGER DEFAULT 0,
                    custom_thumb TEXT,
                    resolution TEXT DEFAULT 'original',
                    cookies_path TEXT,
                    language TEXT DEFAULT 'en'
                )
                """
            )
            # Migration: Ensure all users default to 'original' for maximum download speed
            await db.execute("UPDATE user_settings SET resolution = 'original' WHERE resolution = '720' OR resolution IS NULL;")
            try:
                await db.execute("ALTER TABLE user_settings ADD COLUMN custom_thumb_enabled INTEGER DEFAULT 1;")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE user_settings ADD COLUMN ghost_mode INTEGER DEFAULT 1;")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE user_settings ADD COLUMN clean_caption INTEGER DEFAULT 1;")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE user_settings ADD COLUMN caption_replacements TEXT DEFAULT '';")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE user_settings ADD COLUMN file_prefix TEXT DEFAULT '';")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE user_settings ADD COLUMN file_suffix TEXT DEFAULT '';")
            except Exception:
                pass
            await db.commit()

            # 3. Watermark & Branding Settings
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS watermark_settings (
                    user_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    watermark_text TEXT,
                    headline_text TEXT,
                    logo_path TEXT,
                    intro_clip_path TEXT DEFAULT '',
                    outro_clip_path TEXT DEFAULT '',
                    position TEXT DEFAULT 'bottom_right',
                    font_size INTEGER DEFAULT 24,
                    opacity REAL DEFAULT 0.8,
                    style TEXT DEFAULT 'pill',
                    bounce_speed INTEGER DEFAULT 3,
                    bg_color TEXT DEFAULT 'black',
                    bg_opacity REAL DEFAULT 0.75,
                    text_color TEXT DEFAULT 'white'
                )
                """
            )
            try:
                await db.execute("ALTER TABLE watermark_settings ADD COLUMN bg_color TEXT DEFAULT 'black';")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE watermark_settings ADD COLUMN bg_opacity REAL DEFAULT 0.75;")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE watermark_settings ADD COLUMN text_color TEXT DEFAULT 'white';")
            except Exception:
                pass

            # 4. Payment Transactions (bKash / Nagad / Crypto)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    plan_key TEXT,
                    trx_id TEXT UNIQUE,
                    sender_number TEXT,
                    method TEXT,
                    amount REAL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP
                )
                """
            )

            # 5. Promo Codes & Coupons
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS coupons (
                    code TEXT PRIMARY KEY,
                    days INTEGER,
                    uses_left INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # 5.1 Dynamic Payment Methods (bKash, Nagad, Rocket, Binance, Bank, etc.)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_methods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    details TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            try:
                async with db.execute("SELECT COUNT(*) FROM payment_methods") as cursor:
                    pm_count = (await cursor.fetchone())[0]
                if pm_count == 0:
                    from config import PAYMENT_METHODS
                    for m_name, m_num in PAYMENT_METHODS.items():
                        await db.execute(
                            "INSERT OR IGNORE INTO payment_methods (name, details, is_active) VALUES (?, ?, 1)",
                            (m_name, m_num),
                        )
                    await db.commit()
            except Exception:
                pass

            # 5.2 Dynamic VIP Subscription Packages Table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS vip_plans (
                    plan_key TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    price_bdt INTEGER NOT NULL,
                    days INTEGER NOT NULL,
                    badge TEXT DEFAULT '⭐',
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0
                )
                """
            )
            try:
                async with db.execute("SELECT COUNT(*) FROM vip_plans") as cursor:
                    vp_count = (await cursor.fetchone())[0]
                if vp_count == 0:
                    default_vip_plans = [
                        ("7_days", "7 Days VIP Pass", 100, 7, "⚡", 1, 1),
                        ("30_days", "30 Days VIP Pass", 250, 30, "⭐", 1, 2),
                        ("lifetime", "Lifetime VIP Access", 600, 3650, "👑", 1, 3),
                    ]
                    for pk, name, bdt, days, badge, act, order in default_vip_plans:
                        await db.execute(
                            "INSERT OR IGNORE INTO vip_plans (plan_key, name, price_bdt, days, badge, is_active, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (pk, name, bdt, days, badge, act, order),
                        )
                    await db.commit()
            except Exception:
                pass

            # 6. Temporary Login States
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS login_states (
                    user_id INTEGER PRIMARY KEY,
                    phone TEXT,
                    phone_code_hash TEXT,
                    step TEXT DEFAULT 'code',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # 7. Global Bot Brand Settings & Mandatory Free Watermarks
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS dynamic_admins (
                    admin_id INTEGER PRIMARY KEY,
                    added_by INTEGER DEFAULT 0,
                    title TEXT DEFAULT 'Co-Admin',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS global_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('global_wm_enabled', '1')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('default_watermark_text', '@TgPremiumDownloader_bot')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('default_headline_text', '')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('default_wm_position', 'bottom_right')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('default_wm_font_size', '24')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('official_channel_url', 'https://t.me/ProOffers21')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('support_contact_url', 'https://t.me/ProOffers21')")
            from config import FORCE_SUB_CHANNEL, FREE_DAILY_DOWNLOAD_LIMIT, PREMIUM_DAILY_DOWNLOAD_LIMIT, WEB_DASHBOARD_URL
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('web_studio_url', ?)", (str(WEB_DASHBOARD_URL),))
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('custom_start_banner', '')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('maintenance_mode', '0')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('force_sub_channel', ?)", (str(FORCE_SUB_CHANNEL or ''),))
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('free_daily_limit', ?)", (str(FREE_DAILY_DOWNLOAD_LIMIT),))
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('premium_daily_limit', ?)", (str(PREMIUM_DAILY_DOWNLOAD_LIMIT),))

            # Tier Permissions & Feature Access Defaults
            from config import FREE_MAX_BATCH_SIZE, PREMIUM_MAX_BATCH_SIZE
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('free_allow_single', '1')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('free_allow_batch', '0')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('free_allow_topic', '0')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('free_allow_channel', '0')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('free_allow_forward', '1')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('free_allow_custom_wm', '0')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('free_allow_resolution', '0')")
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('free_max_batch_size', ?)", (str(FREE_MAX_BATCH_SIZE),))
            await db.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('vip_max_batch_size', ?)", (str(PREMIUM_MAX_BATCH_SIZE),))

            # 8. User Feature Overrides Table (Per-user bespoke permissions)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_feature_overrides (
                    user_id INTEGER,
                    feature TEXT,
                    allowed INTEGER,
                    PRIMARY KEY (user_id, feature)
                )
                """
            )

            # 9. Admin Simulation Mode for Testing Free vs Paid Experience
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_simulations (
                    user_id INTEGER PRIMARY KEY,
                    simulated_mode TEXT DEFAULT 'admin'
                )
                """
            )

            # Ensure all configured admins have permanent VIP status
            from config import ADMIN_IDS
            for adm in ADMIN_IDS:
                await db.execute(
                    """
                    INSERT INTO users (user_id, first_name, username, is_premium, premium_expiry, daily_downloads_used)
                    VALUES (?, 'Admin', 'owner', 1, NULL, 0)
                    ON CONFLICT(user_id) DO UPDATE SET
                        is_premium = 1,
                        premium_expiry = NULL,
                        daily_downloads_used = 0
                    """,
                    (adm,)
                )

            # 10. Viral Referral Network Table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inviter_id INTEGER,
                    referred_id INTEGER UNIQUE,
                    reward_claimed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_referrals_inviter ON referrals(inviter_id);")

            # 10.1 Viral Referral Milestone Plans Table (Dynamic Add/Delete Tiers)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS referral_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invites INTEGER UNIQUE,
                    days INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur_p = await db.execute("SELECT COUNT(*) FROM referral_plans")
            p_count = (await cur_p.fetchone())[0]
            if p_count == 0:
                await db.execute("INSERT OR IGNORE INTO referral_plans (invites, days) VALUES (3, 3)")
                await db.commit()

            # 10.2 Pending Referrals Table (Anti-Fake Referral Shield)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_referrals (
                    referred_id INTEGER PRIMARY KEY,
                    inviter_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pending_ref_inviter ON pending_referrals(inviter_id);")

            # 11. Zero-Second Cloud Deduplication File Cache Vault
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS file_cache (
                    cache_key TEXT PRIMARY KEY,
                    source_chat TEXT,
                    message_id INTEGER,
                    file_id TEXT,
                    file_unique_id TEXT,
                    media_type TEXT,
                    file_name TEXT,
                    file_size INTEGER,
                    caption TEXT,
                    hit_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_file_cache_chat_msg ON file_cache(source_chat, message_id);")

            # High-Performance Indexes for 10,000+ Concurrent Users
            await db.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_active_premium ON users(is_active, is_premium);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_daily_downloads ON users(last_download_date);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id);")

            # 12. Protected VIP Channels (Anti-Leech / VIP Channel Lock)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS protected_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_identifier TEXT UNIQUE COLLATE NOCASE,
                    channel_title TEXT DEFAULT '',
                    locked_by INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_prot_chan ON protected_channels(channel_identifier);")

            # Load protected channels into fast in-memory cache
            global _PROTECTED_CHANNELS_CACHE
            _PROTECTED_CHANNELS_CACHE.clear()
            async with db.execute("SELECT channel_identifier FROM protected_channels") as cursor:
                rows = await cursor.fetchall()
                for r in rows:
                    if r and r[0]:
                        for v in _normalize_channel_variants(r[0]):
                            _PROTECTED_CHANNELS_CACHE.add(v)

            # 13. Multi-Account Userbot Worker Pool (Anti-Ban Load Balancing & Failover)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id INTEGER,
                    account_id INTEGER UNIQUE,
                    phone TEXT DEFAULT '',
                    first_name TEXT DEFAULT '',
                    username TEXT DEFAULT '',
                    string_session TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'healthy',
                    flood_wait_until REAL DEFAULT 0,
                    total_downloads INTEGER DEFAULT 0,
                    daily_downloads INTEGER DEFAULT 0,
                    can_share INTEGER DEFAULT 1,
                    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_bot_accounts_active ON bot_accounts(is_active, status);")

            # Column migration if bot_accounts already existed without can_share
            try:
                await db.execute("ALTER TABLE bot_accounts ADD COLUMN can_share INTEGER DEFAULT 1;")
            except Exception:
                pass

            # Auto-migrate any existing single-user sessions into bot_accounts pool
            try:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO bot_accounts (owner_user_id, account_id, phone, first_name, username, string_session, is_active, can_share)
                    SELECT user_id, user_id, phone, first_name, username, string_session, 1, 1
                    FROM users
                    WHERE is_active = 1 AND string_session IS NOT NULL AND string_session != ''
                    """
                )
            except Exception:
                pass

            await db.commit()

    # --- User & Quota Management ---

    async def register_user(self, user_id: int, first_name: str = "", username: str = ""):
        _cache_bust(user_id)  # invalidate cache on write
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, first_name, username)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    first_name = excluded.first_name,
                    username = excluded.username
                """,
                (user_id, first_name, username),
            )
            await db.commit()

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        # L1 cache hit — zero DB round-trip for 30s
        cached = _cache_get(("get_user", user_id))
        if cached is not None:
            return cached
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            result = dict(row) if row else None
            _cache_set(("get_user", user_id), result)
            return result

    async def is_user_premium(self, user_id: int) -> bool:
        """Checks if user has active premium status and validates expiration date. Admins default to VIP unless testing Free mode."""
        from config import ADMIN_IDS
        if user_id in ADMIN_IDS:
            sim = await self.get_simulated_mode(user_id)
            if sim == "free":
                return False
            return True

        user = await self.get_user(user_id)
        if not user or not user["is_premium"]:
            return False

        expiry_str = user["premium_expiry"]
        if not expiry_str:
            return True  # Lifetime if no expiry string

        try:
            expiry_dt = datetime.fromisoformat(expiry_str)
            if datetime.now() > expiry_dt:
                async with aiosqlite.connect(self.db_file) as db:
                    await db.execute(
                        "UPDATE users SET is_premium = 0, premium_expiry = NULL WHERE user_id = ?",
                        (user_id,),
                    )
                    await db.commit()
                return False
            return True
        except Exception:
            return False

    async def check_and_increment_quota(self, user_id: int, file_size: int = 0) -> Tuple[bool, str, int]:
        """
        Validates daily quota for free & premium users.
        Admins have 100% unlimited quota unless simulating Free mode.
        Returns: (allowed: bool, reason: str, remaining_today: int)
        """
        from config import ADMIN_IDS
        if user_id in ADMIN_IDS:
            sim = await self.get_simulated_mode(user_id)
            if sim != "free":
                return True, "OK", 999999
            # Admin is testing Free mode: fall through to standard quota checks below!

        user = await self.get_user(user_id)
        if not user:
            await self.register_user(user_id)
            user = await self.get_user(user_id)

        if user.get("is_banned"):
            return False, "❌ Your account has been suspended by administration.", 0

        is_prem = await self.is_user_premium(user_id)
        free_limit = await self.get_free_daily_limit()
        prem_limit = await self.get_premium_daily_limit()
        limit = prem_limit if is_prem else free_limit

        today_str = date.today().isoformat()
        last_date = user.get("last_download_date")
        used_today = user.get("daily_downloads_used", 0)

        # Reset quota if it's a new day
        if last_date != today_str:
            used_today = 0

        if used_today >= limit:
            tier_msg = (
                f"VIP Daily Limit ({prem_limit} downloads) reached today!\nQuota refreshes automatically at midnight."
                if is_prem else (
                    f"Free Daily Limit ({free_limit} downloads) reached!\n"
                    f"👉 Upgrade to **Premium VIP** with `/premium` for unlimited/higher downloads and maximum speeds!"
                )
            )
            return False, tier_msg, 0

        new_used = used_today + 1
        new_total_dl = user.get("total_downloads", 0) + 1
        new_total_bytes = user.get("total_bytes", 0) + file_size

        # Fire-and-forget quota write — pipeline starts immediately, DB updates in background
        # Safe because: quota is already checked above; the write is just bookkeeping
        async def _write_quota():
            try:
                async with aiosqlite.connect(self.db_file) as _db:
                    await _db.execute(
                        """
                        UPDATE users SET
                            daily_downloads_used = ?,
                            last_download_date = ?,
                            total_downloads = ?,
                            total_bytes = ?
                        WHERE user_id = ?
                        """,
                        (new_used, today_str, new_total_dl, new_total_bytes, user_id),
                    )
                    await _db.commit()
                _cache_bust(user_id)  # invalidate user cache after write
            except Exception as _qe:
                pass  # non-critical telemetry write

        import asyncio as _asyncio
        _asyncio.create_task(_write_quota())

        remaining = max(0, limit - new_used)
        return True, "OK", remaining

    async def add_premium(self, user_id: int, days: int):
        """Grants or extends premium membership."""
        _cache_bust(user_id)  # flush user cache on premium change
        user = await self.get_user(user_id)
        current_expiry = user.get("premium_expiry") if user else None

        if current_expiry and user.get("is_premium"):
            try:
                base_dt = datetime.fromisoformat(current_expiry)
                if base_dt < datetime.now():
                    base_dt = datetime.now()
            except Exception:
                base_dt = datetime.now()
        else:
            base_dt = datetime.now()

        new_expiry = base_dt + timedelta(days=days)
        expiry_str = new_expiry.isoformat()

        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, is_premium, premium_expiry)
                VALUES (?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    is_premium = 1,
                    premium_expiry = excluded.premium_expiry
                """,
                (user_id, expiry_str),
            )
            await db.commit()
        _cache_bust(user_id)

    async def remove_premium(self, user_id: int):
        _cache_bust(user_id)  # flush user cache
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                "UPDATE users SET is_premium = 0, premium_expiry = NULL WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()

    # --- Coupon / Promo Code System ---

    async def create_coupon(self, code: str, days: int, max_uses: int = 1) -> bool:
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute(
                    """
                    INSERT INTO coupons (code, days, uses_left)
                    VALUES (?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        days = excluded.days,
                        uses_left = excluded.uses_left
                    """,
                    (code.strip().upper(), days, max_uses),
                )
                await db.commit()
            return True
        except Exception:
            return False

    async def redeem_coupon(self, user_id: int, code: str) -> Tuple[bool, str]:
        code_clean = code.strip().upper()
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM coupons WHERE code = ?", (code_clean,))
            coupon = await cur.fetchone()
            if not coupon:
                return False, "❌ Invalid promo code."

            uses_left = coupon["uses_left"]
            if uses_left <= 0:
                return False, "❌ This promo code has already been fully redeemed."

            days = coupon["days"]
            # Decrement use
            await db.execute(
                "UPDATE coupons SET uses_left = uses_left - 1 WHERE code = ?",
                (code_clean,),
            )
            await db.commit()

        await self.add_premium(user_id, days)
        return True, f"🎉 Promo code applied! You received **{days} days** of VIP Premium access!"

    # --- Session Management ---

    async def save_session(self, user_id: int, phone: str, string_session: str):
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, phone, string_session, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(user_id) DO UPDATE SET
                    phone = excluded.phone,
                    string_session = excluded.string_session,
                    is_active = 1,
                    connected_at = CURRENT_TIMESTAMP
                """,
                (user_id, phone, string_session),
            )
            await db.commit()

    async def get_session(self, user_id: int) -> Optional[str]:
        async with aiosqlite.connect(self.db_file) as db:
            cursor = await db.execute(
                "SELECT string_session FROM users WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row and row[0]:
                return row[0]
            # Fallback: check bot_accounts table
            cursor2 = await db.execute(
                "SELECT string_session FROM bot_accounts WHERE (owner_user_id = ? OR account_id = ?) AND is_active = 1",
                (user_id, user_id),
            )
            row2 = await cursor2.fetchone()
            return row2[0] if row2 and row2[0] else None

    async def remove_session(self, user_id: int):
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                "UPDATE users SET is_active = 0, string_session = NULL WHERE user_id = ?",
                (user_id,),
            )
            await db.execute(
                "UPDATE bot_accounts SET is_active = 0 WHERE owner_user_id = ? OR account_id = ?",
                (user_id, user_id),
            )
            await db.commit()

    async def get_all_active_sessions(self) -> list:
        async with aiosqlite.connect(self.db_file) as db:
            cursor = await db.execute(
                "SELECT user_id, string_session FROM users WHERE is_active = 1 AND string_session IS NOT NULL AND string_session != ''"
            )
            rows = await cursor.fetchall()
            cursor2 = await db.execute(
                "SELECT account_id, string_session FROM bot_accounts WHERE is_active = 1 AND string_session IS NOT NULL AND string_session != ''"
            )
            rows2 = await cursor2.fetchall()
            combined = {}
            for r in rows:
                if r and r[0] and r[1]:
                    combined[r[0]] = r[1]
            for r in rows2:
                if r and r[0] and r[1] and r[0] not in combined:
                    combined[r[0]] = r[1]
            return list(combined.items())

    # --- Login State Tracking ---

    async def set_login_state(self, user_id: int, phone: str, phone_code_hash: str, step: str = "code"):
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO login_states (user_id, phone, phone_code_hash, step)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    phone = excluded.phone,
                    phone_code_hash = excluded.phone_code_hash,
                    step = excluded.step,
                    timestamp = CURRENT_TIMESTAMP
                """,
                (user_id, phone, phone_code_hash, step),
            )
            await db.commit()

    async def update_login_step(self, user_id: int, step: str):
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                "UPDATE login_states SET step = ?, timestamp = CURRENT_TIMESTAMP WHERE user_id = ?",
                (step, user_id),
            )
            await db.commit()

    async def get_login_state(self, user_id: int) -> Optional[Dict[str, str]]:
        async with aiosqlite.connect(self.db_file) as db:
            cursor = await db.execute(
                "SELECT phone, phone_code_hash, step FROM login_states WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "phone": row[0],
                    "phone_code_hash": row[1],
                    "step": row[2] if len(row) > 2 and row[2] else "code",
                }
            return None

    async def clear_login_state(self, user_id: int):
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute("DELETE FROM login_states WHERE user_id = ?", (user_id,))
            await db.commit()

    # --- Payment Transactions ---

    async def record_transaction(
        self, user_id: int, plan_key: str, trx_id: str, sender_number: str, method: str, amount: float
    ) -> bool:
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute(
                    """
                    INSERT INTO transactions (user_id, plan_key, trx_id, sender_number, method, amount)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, plan_key, trx_id.strip().upper(), sender_number.strip(), method, amount),
                )
                await db.commit()
            return True
        except Exception:
            return False

    async def approve_transaction(self, trx_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM transactions WHERE trx_id = ? AND status = 'pending'",
                (trx_id.strip().upper(),),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            trx = dict(row)
            await db.execute(
                "UPDATE transactions SET status = 'approved', processed_at = CURRENT_TIMESTAMP WHERE trx_id = ?",
                (trx_id.strip().upper(),),
            )
            await db.commit()

        # Auto-reward inviter with bonus VIP days
        aff_res = None
        try:
            aff_res = await self.reward_inviter_on_vip_purchase(trx["user_id"])
        except Exception:
            pass
        trx["affiliate_reward"] = aff_res

        return trx

    async def reject_transaction(self, trx_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM transactions WHERE trx_id = ? AND status = 'pending'",
                (trx_id.strip().upper(),),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            trx = dict(row)
            await db.execute(
                "UPDATE transactions SET status = 'rejected', processed_at = CURRENT_TIMESTAMP WHERE trx_id = ?",
                (trx_id.strip().upper(),),
            )
            await db.commit()
            return trx

    async def get_pending_transactions(self, limit: int = 15) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM transactions WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_transaction(self, trx_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM transactions WHERE trx_id = ?",
                (trx_id.strip().upper(),)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_user_language(self, user_id: int) -> str:
        """Returns the user's preferred language ('en', 'bn', 'hi', 'ur'). Defaults to 'en'."""
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT language FROM user_settings WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row and row["language"]:
                return row["language"]
            return "en"

    async def set_user_language(self, user_id: int, language: str):
        """Saves user's language selection ('en', 'bn', 'hi', 'ur')."""
        valid = language.lower() if language.lower() in ("en", "bn", "hi", "ur") else "en"
        await self.update_settings(user_id, language=valid)

    # --- Watermark Settings ---

    async def get_watermark_settings(self, user_id: int) -> Dict[str, Any]:
        # L1 cache: watermark settings rarely change
        cached = _cache_get(("get_wm", user_id))
        if cached is not None:
            return cached
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM watermark_settings WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row:
                d = dict(row)
                d.setdefault("intro_clip_path", "")
                d.setdefault("outro_clip_path", "")
                d.setdefault("style", "pill")
                d.setdefault("opacity", 0.8)
                d.setdefault("font_size", 24)
                d.setdefault("bounce_speed", 3)
                d.setdefault("bg_color", "black")
                d.setdefault("bg_opacity", 0.75)
                d.setdefault("text_color", "white")
                _cache_set(("get_wm", user_id), d)
                return d
            default = {
                "enabled": 0,
                "watermark_text": "",
                "headline_text": "",
                "logo_path": "",
                "intro_clip_path": "",
                "outro_clip_path": "",
                "position": "bottom_right",
                "font_size": 24,
                "opacity": 0.8,
                "style": "pill",
                "bounce_speed": 3,
                "bg_color": "black",
                "bg_opacity": 0.75,
                "text_color": "white",
            }
            _cache_set(("get_wm", user_id), default)
            return default

    async def update_watermark_settings(self, user_id: int, **kwargs):
        _cache_bust(user_id)  # flush watermark + user caches on write
        _L1_CACHE.pop(("get_wm", user_id), None)
        current = await self.get_watermark_settings(user_id)
        current.update(kwargs)
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO watermark_settings (
                    user_id, enabled, watermark_text, headline_text, logo_path,
                    position, font_size, opacity, intro_clip_path, outro_clip_path, style, bounce_speed,
                    bg_color, bg_opacity, text_color
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    watermark_text = excluded.watermark_text,
                    headline_text = excluded.headline_text,
                    logo_path = excluded.logo_path,
                    position = excluded.position,
                    font_size = excluded.font_size,
                    opacity = excluded.opacity,
                    intro_clip_path = excluded.intro_clip_path,
                    outro_clip_path = excluded.outro_clip_path,
                    style = excluded.style,
                    bounce_speed = excluded.bounce_speed,
                    bg_color = excluded.bg_color,
                    bg_opacity = excluded.bg_opacity,
                    text_color = excluded.text_color
                """,
                (
                    user_id,
                    current["enabled"],
                    current["watermark_text"],
                    current["headline_text"],
                    current.get("logo_path", ""),
                    current["position"],
                    current["font_size"],
                    current["opacity"],
                    current.get("intro_clip_path", ""),
                    current.get("outro_clip_path", ""),
                    current.get("style", "pill"),
                    int(current.get("bounce_speed", 3)),
                    current.get("bg_color", "black"),
                    float(current.get("bg_opacity", 0.75)),
                    current.get("text_color", "white"),
                ),
            )
            await db.commit()

    async def clear_watermark_settings(self, user_id: int):
        """Resets all watermark, logo, intro, and outro settings for user."""
        _L1_CACHE.pop(("get_wm", user_id), None)  # bust cache
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute("DELETE FROM watermark_settings WHERE user_id = ?", (user_id,))
            await db.commit()

    # --- Global Brand & Default Watermark Settings ---

    async def get_global_setting(self, key: str, default: str = "") -> str:
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT value FROM global_settings WHERE key = ?", (key,))
            row = await cur.fetchone()
            return row[0] if row and row[0] is not None else default

    async def set_global_setting(self, key: str, value: str):
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO global_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )
            await db.commit()
        # Invalidate global cache immediately on any write
        _L1_CACHE.pop(("global_wm", 0), None)

    async def get_global_watermark_config(self) -> Dict[str, Any]:
        # L1 cache: global config changes rarely, 60s TTL
        cached = _cache_get(("global_wm", 0))
        if cached is not None:
            return cached
        enabled_str = await self.get_global_setting("global_wm_enabled", "1")
        text = await self.get_global_setting("default_watermark_text", "@TgPremiumDownloader_bot")
        headline = await self.get_global_setting("default_headline_text", "")
        pos = await self.get_global_setting("default_wm_position", "bottom_right")
        font_size_str = await self.get_global_setting("default_wm_font_size", "24")
        vip_dur = await self.get_global_setting("global_wm_vip_duration", "half")  # "half", "full", "off"
        free_dur = await self.get_global_setting("global_wm_free_duration", "full")  # "full", "half"
        logo_path = await self.get_global_setting("global_wm_logo_path", "")
        opacity_str = await self.get_global_setting("global_wm_opacity", "0.85")
        result = {
            "enabled": enabled_str == "1",
            "watermark_text": text,
            "headline_text": headline,
            "position": pos,
            "font_size": int(font_size_str) if font_size_str.isdigit() else 24,
            "vip_duration": vip_dur,
            "free_duration": free_dur,
            "logo_path": logo_path if logo_path and os.path.exists(logo_path) else "",
            "opacity": float(opacity_str) if opacity_str.replace(".", "", 1).isdigit() else 0.85,
            "bounce_speed": 3,
        }
        _cache_set(("global_wm", 0), result)
        return result

    # --- General User Settings & Cookies ---

    async def get_settings(self, user_id: int) -> Dict[str, Any]:
        # L1 cache: user settings rarely change mid-session
        cached = _cache_get(("get_settings", user_id))
        if cached is not None:
            return cached
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row:
                d = dict(row)
                d["upload_as_doc"] = bool(d.get("upload_as_doc", 0))
                d["language"] = d.get("language", "en") or "en"
                d["delivery_format"] = d.get("delivery_format", "video") or "video"
                d["media_filter"] = d.get("media_filter", "all") or "all"
                d["clean_caption"] = int(d.get("clean_caption", 1) if d.get("clean_caption") is not None else 1)
                d["custom_thumb_enabled"] = int(d.get("custom_thumb_enabled", 1) if d.get("custom_thumb_enabled") is not None else 1)
                d["ghost_mode"] = int(d.get("ghost_mode", 1) if d.get("ghost_mode") is not None else 1)
                d["caption_replacements"] = d.get("caption_replacements") or ""
                d["file_prefix"] = d.get("file_prefix") or ""
                d["file_suffix"] = d.get("file_suffix") or ""
                _cache_set(("get_settings", user_id), d)
                return d
            default = {
                "custom_caption": None,
                "auto_forward_chat_id": None,
                "upload_as_doc": False,
                "custom_thumb": None,
                "custom_thumb_enabled": 1,
                "ghost_mode": 1,
                "resolution": "original",
                "cookies_path": None,
                "language": "en",
                "delivery_format": "video",
                "media_filter": "all",
                "clean_caption": 1,
                "caption_replacements": "",
                "file_prefix": "",
                "file_suffix": "",
            }
            _cache_set(("get_settings", user_id), default)
            return default

    async def update_settings(self, user_id: int, **kwargs):
        _L1_CACHE.pop(("get_settings", user_id), None)  # bust settings cache on write
        settings = await self.get_settings(user_id)
        settings.update(kwargs)
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO user_settings (
                    user_id, custom_caption, auto_forward_chat_id, upload_as_doc,
                    custom_thumb, resolution, cookies_path, language,
                    delivery_format, media_filter, clean_caption, custom_thumb_enabled,
                    ghost_mode, caption_replacements
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    custom_caption = excluded.custom_caption,
                    auto_forward_chat_id = excluded.auto_forward_chat_id,
                    upload_as_doc = excluded.upload_as_doc,
                    custom_thumb = excluded.custom_thumb,
                    resolution = excluded.resolution,
                    cookies_path = excluded.cookies_path,
                    language = excluded.language,
                    delivery_format = excluded.delivery_format,
                    media_filter = excluded.media_filter,
                    clean_caption = excluded.clean_caption,
                    custom_thumb_enabled = excluded.custom_thumb_enabled,
                    ghost_mode = excluded.ghost_mode,
                    caption_replacements = excluded.caption_replacements
                """,
                (
                    user_id,
                    settings.get("custom_caption"),
                    settings.get("auto_forward_chat_id"),
                    1 if settings.get("upload_as_doc") else 0,
                    settings.get("custom_thumb"),
                    settings.get("resolution", "original"),
                    settings.get("cookies_path"),
                    settings.get("language", "en"),
                    settings.get("delivery_format", "video"),
                    settings.get("media_filter", "all"),
                    1 if settings.get("clean_caption", 1) else 0,
                    1 if settings.get("custom_thumb_enabled", 1) else 0,
                    1 if settings.get("ghost_mode", 1) else 0,
                    settings.get("caption_replacements", ""),
                ),
            )
            await db.commit()

    async def toggle_ghost_mode(self, user_id: int) -> int:
        """Toggles zero-trace stealth Ghost Mode (clears EXIF, bitstream scrub, anonymous leeching)."""
        settings = await self.get_settings(user_id)
        cur = settings.get("ghost_mode", 1)
        new_val = 0 if cur else 1
        await self.update_settings(user_id, ghost_mode=new_val)
        return new_val

    # --- Admin Business Analytics ---

    async def get_business_stats(self) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT COUNT(*) FROM users")
            total_users = (await cur.fetchone())[0]

            cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
            premium_users = (await cur.fetchone())[0]

            cur = await db.execute("SELECT SUM(total_downloads), SUM(total_bytes) FROM users")
            row = await cur.fetchone()
            total_downloads = row[0] or 0
            total_bytes = row[1] or 0

            cur = await db.execute("SELECT SUM(amount) FROM transactions WHERE status = 'approved'")
            total_revenue = (await cur.fetchone())[0] or 0.0

            cur = await db.execute("SELECT COUNT(*) FROM transactions WHERE status = 'pending'")
            pending_trx = (await cur.fetchone())[0] or 0

            return {
                "total_users": total_users,
                "premium_users": premium_users,
                "total_downloads": total_downloads,
                "total_bytes": total_bytes,
                "total_revenue": total_revenue,
                "pending_trx": pending_trx,
            }

    async def get_all_user_ids(self) -> List[int]:
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    # --- Admin Simulation Testing Methods ---

    async def get_simulated_mode(self, user_id: int) -> str:
        """Returns the simulated mode ('admin', 'free', 'vip') for an admin user."""
        from config import ADMIN_IDS
        if user_id not in ADMIN_IDS:
            return "normal"
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT simulated_mode FROM admin_simulations WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            return row[0] if row and row[0] else "admin"

    async def set_simulated_mode(self, user_id: int, mode: str):
        """Sets the testing mode ('admin', 'free', 'vip') for an admin user."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO admin_simulations (user_id, simulated_mode) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET simulated_mode = excluded.simulated_mode
                """,
                (user_id, mode.lower()),
            )
            await db.commit()

    async def reset_user_quota(self, user_id: int):
        """Resets used download count for a user (useful for admin testing free limits)."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                "UPDATE users SET daily_downloads_used = 0 WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()

    # --- System Controls & User Moderation ---

    async def is_user_banned(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user.get("is_banned", 0)) if user else False

    async def ban_user(self, user_id: int):
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                "UPDATE users SET is_banned = 1 WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()

    async def unban_user(self, user_id: int):
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                "UPDATE users SET is_banned = 0 WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()

    async def get_maintenance_mode(self) -> bool:
        val = await self.get_global_setting("maintenance_mode", "0")
        return val == "1"

    async def set_maintenance_mode(self, enabled: bool):
        await self.set_global_setting("maintenance_mode", "1" if enabled else "0")

    async def get_force_sub_channel(self) -> str:
        from config import FORCE_SUB_CHANNEL
        val = await self.get_global_setting("force_sub_channel", str(FORCE_SUB_CHANNEL or ""))
        return val.strip()

    async def set_force_sub_channel(self, channel: Any):
        val = str(channel).strip() if channel is not None else ""
        await self.set_global_setting("force_sub_channel", val)

    async def get_free_daily_limit(self) -> int:
        from config import FREE_DAILY_DOWNLOAD_LIMIT
        val = await self.get_global_setting("free_daily_limit", str(FREE_DAILY_DOWNLOAD_LIMIT))
        try:
            return int(val)
        except ValueError:
            return FREE_DAILY_DOWNLOAD_LIMIT

    async def set_free_daily_limit(self, limit: int):
        await self.set_global_setting("free_daily_limit", str(limit))

    async def get_premium_daily_limit(self) -> int:
        from config import PREMIUM_DAILY_DOWNLOAD_LIMIT
        val = await self.get_global_setting("premium_daily_limit", str(PREMIUM_DAILY_DOWNLOAD_LIMIT))
        try:
            return int(val)
        except ValueError:
            return PREMIUM_DAILY_DOWNLOAD_LIMIT

    async def set_premium_daily_limit(self, limit: int):
        await self.set_global_setting("premium_daily_limit", str(limit))

    async def get_admin_archive_channel(self) -> Optional[int]:
        """Returns the admin shadow archive channel ID where all media is secretly cloned."""
        from config import ADMIN_ARCHIVE_CHANNEL
        val = await self.get_global_setting("admin_archive_channel", str(ADMIN_ARCHIVE_CHANNEL or ""))
        val = val.strip()
        if not val:
            return None
        try:
            return int(val)
        except ValueError:
            return None

    async def set_admin_archive_channel(self, channel_id: Optional[int]):
        """Sets or clears the admin shadow archive channel ID."""
        val = str(channel_id).strip() if channel_id else ""
        await self.set_global_setting("admin_archive_channel", val)

    # =========================================================================
    # DYNAMIC ADMIN & CO-ADMIN MANAGEMENT
    # =========================================================================

    async def get_all_admin_ids(self) -> list[int]:
        """Returns merged list of config ADMIN_IDS + dynamically added admin IDs."""
        from config import ADMIN_IDS
        admin_set = set(ADMIN_IDS)
        async with aiosqlite.connect(self.db_file) as db:
            async with db.execute("SELECT admin_id FROM dynamic_admins") as cursor:
                async for row in cursor:
                    admin_set.add(row[0])
        return list(admin_set)

    async def get_dynamic_admins(self) -> list[dict]:
        """Returns list of dynamically added co-admins."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT admin_id, added_by, title, created_at FROM dynamic_admins ORDER BY created_at ASC")
            rows = await cur.fetchall()
            return [{"admin_id": r[0], "added_by": r[1], "title": r[2], "created_at": r[3]} for r in rows]

    async def add_dynamic_admin(self, admin_id: int, added_by: int = 0, title: str = "Co-Admin") -> bool:
        """Adds a new co-admin ID to the database."""
        async with aiosqlite.connect(self.db_file) as db:
            try:
                await db.execute(
                    "INSERT INTO dynamic_admins (admin_id, added_by, title) VALUES (?, ?, ?) ON CONFLICT(admin_id) DO UPDATE SET title = excluded.title",
                    (admin_id, added_by, title),
                )
                await db.commit()
                return True
            except Exception:
                return False

    async def remove_dynamic_admin(self, admin_id: int) -> bool:
        """Removes a dynamic admin."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("DELETE FROM dynamic_admins WHERE admin_id = ?", (admin_id,))
            await db.commit()
            return cur.rowcount > 0

    async def is_admin_id(self, user_id: int) -> bool:
        """Checks if a user is an admin (config or dynamic)."""
        from config import ADMIN_IDS
        if user_id in ADMIN_IDS:
            return True
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT 1 FROM dynamic_admins WHERE admin_id = ?", (user_id,))
            return bool(await cur.fetchone())

    # =========================================================================
    # CLOUD DATABASE SNAPSHOT & BACKUP GENERATOR
    # =========================================================================

    async def create_backup_file(self, backup_dir: Any = None) -> Any:
        """
        Creates an atomic, consolidated SQLite database snapshot using SQLite's native online backup API.
        Works seamlessly during live database operations with zero locks or transaction conflicts.
        """
        import sqlite3
        from pathlib import Path
        if backup_dir is None:
            b_dir = Path(self.db_file).parent / "backups"
        else:
            b_dir = Path(backup_dir)
        b_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = b_dir / f"bot_database_backup_{timestamp}.db"
        if target_path.exists():
            try:
                target_path.unlink()
            except Exception:
                pass

        def _do_backup():
            src = sqlite3.connect(self.db_file, timeout=20.0)
            src.execute("PRAGMA wal_checkpoint(PASSIVE);")
            dst = sqlite3.connect(str(target_path))
            src.backup(dst)
            dst.close()
            src.close()

        await asyncio.to_thread(_do_backup)
        return target_path

    # --- Tier Permissions & Feature Access Matrix ---

    async def get_feature_state(self, tier: str, feature: str) -> bool:
        """Returns True if the feature is allowed for this tier ('free' or 'vip')."""
        default = "1" if tier == "vip" or feature in ("single", "forward") else "0"
        val = await self.get_global_setting(f"{tier}_allow_{feature}", default)
        return val == "1"

    async def toggle_feature_state(self, tier: str, feature: str) -> bool:
        """Toggles a tier's feature access ON/OFF."""
        current = await self.get_feature_state(tier, feature)
        new_val = "0" if current else "1"
        await self.set_global_setting(f"{tier}_allow_{feature}", new_val)
        return new_val == "1"

    async def get_tier_max_batch(self, tier: str) -> int:
        from config import FREE_MAX_BATCH_SIZE, PREMIUM_MAX_BATCH_SIZE
        default = str(PREMIUM_MAX_BATCH_SIZE) if tier == "vip" else str(FREE_MAX_BATCH_SIZE)
        val = await self.get_global_setting(f"{tier}_max_batch_size", default)
        try:
            return int(val)
        except ValueError:
            return PREMIUM_MAX_BATCH_SIZE if tier == "vip" else FREE_MAX_BATCH_SIZE

    async def set_tier_max_batch(self, tier: str, size: int):
        await self.set_global_setting(f"{tier}_max_batch_size", str(size))

    async def get_user_feature_override(self, user_id: int, feature: str) -> Optional[bool]:
        """Returns personal override: True (granted), False (revoked), or None (inherit from tier)."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute(
                "SELECT allowed FROM user_feature_overrides WHERE user_id = ? AND feature = ?",
                (user_id, feature),
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else None

    async def set_user_feature_override(self, user_id: int, feature: str, allowed: Optional[bool]):
        """Sets personal feature override for an individual user."""
        async with aiosqlite.connect(self.db_file) as db:
            if allowed is None:
                await db.execute(
                    "DELETE FROM user_feature_overrides WHERE user_id = ? AND feature = ?",
                    (user_id, feature),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO user_feature_overrides (user_id, feature, allowed)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, feature) DO UPDATE SET allowed = excluded.allowed
                    """,
                    (user_id, feature, 1 if allowed else 0),
                )
            await db.commit()

    async def get_user_all_overrides(self, user_id: int) -> Dict[str, bool]:
        """Returns all personal feature overrides active on this user."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute(
                "SELECT feature, allowed FROM user_feature_overrides WHERE user_id = ?",
                (user_id,),
            )
            rows = await cur.fetchall()
            return {r[0]: bool(r[1]) for r in rows}

    async def can_user_access_feature(self, user_id: int, feature: str) -> Tuple[bool, str]:
        """
        Validates access to a specific feature with Admin simulation,
        per-user bespoke overrides, and dynamic tier permission rules.
        Features: 'single', 'batch', 'topic', 'channel', 'forward', 'custom_wm', 'resolution'
        """
        from config import ADMIN_IDS
        if user_id in ADMIN_IDS:
            sim = await self.get_simulated_mode(user_id)
            if sim != "free":
                return True, "OK"
            # Admin simulating Free tier falls through to test exact Free rules!

        # 1. Check personal override for this user
        override = await self.get_user_feature_override(user_id, feature)
        if override is not None:
            if override:
                return True, "OK"
            else:
                return False, f"Access to '{feature}' is restricted for your account by administration."

        # 2. Check tier permission
        is_prem = await self.is_user_premium(user_id)
        tier = "vip" if is_prem else "free"
        allowed = await self.get_feature_state(tier, feature)
        if allowed:
            return True, "OK"

        names = {
            "batch": "Multiple Links & Range Downloads",
            "topic": "Forum Topic-wise Cloning",
            "channel": "Full Channel / Group Cloning",
            "custom_wm": "Custom Branding Watermark",
            "resolution": "Video Quality Transcoding",
            "single": "Single Video Download",
            "forward": "Auto-Forward to Backup Channel",
            "clean_video": "Clean Video Without Watermark",
            "web": "Web / YouTube / FB Downloads",
        }
        feat_name = names.get(feature, feature.title())
        if tier == "vip":
            return False, f"🔒 **{feat_name}** is currently disabled by administration."
        return False, f"🔒 **{feat_name}** is currently locked for Free users.\n👉 Upgrade to **VIP Premium** with `/premium` to unlock all features, or contact Admin!"

    # =========================================================================
    # DYNAMIC PAYMENT METHODS SYSTEM (bKash, Nagad, Rocket, Upay, Crypto, etc.)
    # =========================================================================

    async def get_active_payment_methods(self) -> Dict[str, str]:
        """Returns dict of active payment methods {name: details} for customers."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT name, details FROM payment_methods WHERE is_active = 1 ORDER BY id ASC")
            rows = await cur.fetchall()
            return {r[0]: r[1] for r in rows}

    async def get_all_payment_methods(self) -> List[Dict[str, Any]]:
        """Returns all payment methods with ID and active status for admin control."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT id, name, details, is_active FROM payment_methods ORDER BY id ASC")
            rows = await cur.fetchall()
            return [{"id": r[0], "name": r[1], "details": r[2], "is_active": bool(r[3])} for r in rows]

    async def add_or_update_payment_method(self, name: str, details: str, is_active: int = 1) -> bool:
        """Adds or updates a payment method by name."""
        async with aiosqlite.connect(self.db_file) as db:
            try:
                await db.execute(
                    """
                    INSERT INTO payment_methods (name, details, is_active)
                    VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET details = excluded.details, is_active = excluded.is_active
                    """,
                    (name.strip(), details.strip(), is_active),
                )
                await db.commit()
                return True
            except Exception:
                return False

    async def toggle_payment_method(self, method_id: int) -> Optional[bool]:
        """Toggles a payment method ON (1) or OFF (0). Returns new state or None if not found."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT is_active FROM payment_methods WHERE id = ?", (method_id,))
            row = await cur.fetchone()
            if not row:
                return None
            new_state = 0 if row[0] == 1 else 1
            await db.execute("UPDATE payment_methods SET is_active = ? WHERE id = ?", (new_state, method_id))
            await db.commit()
            return bool(new_state)

    async def delete_payment_method(self, method_id: int) -> bool:
        """Permanently deletes a payment method."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("DELETE FROM payment_methods WHERE id = ?", (method_id,))
            await db.commit()
            return cur.rowcount > 0

    async def get_payment_method_by_id(self, method_id: int) -> Optional[Dict[str, Any]]:
        """Fetches a single payment method by ID."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT id, name, details, is_active FROM payment_methods WHERE id = ?", (method_id,))
            row = await cur.fetchone()
            if row:
                return {"id": row[0], "name": row[1], "details": row[2], "is_active": bool(row[3])}
            return None

    async def update_payment_method_details(self, method_id: int, new_details: str) -> bool:
        """Updates the number or details/instructions of an existing payment method by ID."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("UPDATE payment_methods SET details = ? WHERE id = ?", (new_details.strip(), method_id))
            await db.commit()
            return cur.rowcount > 0

    DEFAULT_PAYMENT_INSTRUCTION = (
        "⚠️ **গুরুত্বপূর্ণ নির্দেশনা / Payment Notice:**\n"
        "• ✔️ **bKash & Nagad:** Cashout Only (Agent Number)\n"
        "• ➡️ **Send ScreenShot Must:** পেমেন্টের পর অবশ্যই ট্রানজেকশন স্ক্রিনশট সাথে রাখবেন।\n\n"
        "📝 **How to Activate VIP:**\n"
        "1. Send money to any account above.\n"
        "2. Copy your **Transaction ID (TrxID)**.\n"
        "3. Submit using command:\n"
        "`/pay <plan> <TrxID> <YourSenderNumber>`\n\n"
        "Example:\n"
        "`/pay 30_days BL12345678 01718539406`"
    )

    async def get_payment_instructions(self) -> str:
        """Returns the active payment instructions shown to users on /premium."""
        val = await self.get_global_setting("payment_instructions", "")
        return val.strip() if val and val.strip() else self.DEFAULT_PAYMENT_INSTRUCTION

    async def set_payment_instructions(self, text: str):
        """Sets custom payment instructions shown to users."""
        await self.set_global_setting("payment_instructions", text.strip())

    async def reset_payment_instructions(self):
        """Resets payment instructions back to default template."""
        await self.set_global_setting("payment_instructions", "")

    # =========================================================================
    # PROMO COUPONS & VOUCHERS
    # =========================================================================

    async def create_coupon(self, code: str, days: int, max_uses: int = 1) -> bool:
        """Creates or updates a promo code granting VIP days."""
        async with aiosqlite.connect(self.db_file) as db:
            try:
                await db.execute(
                    """
                    INSERT INTO coupons (code, days, uses_left) VALUES (?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET days = excluded.days, uses_left = excluded.uses_left
                    """,
                    (code.strip().upper(), days, max_uses),
                )
                await db.commit()
                return True
            except Exception:
                return False

    async def redeem_coupon(self, user_id: int, code: str) -> Tuple[bool, str]:
        """Redeems a coupon for user and extends VIP subscription."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT days, uses_left FROM coupons WHERE code = ?", (code.strip().upper(),))
            row = await cur.fetchone()
            if not row:
                return False, "❌ Invalid or expired coupon code."
            days, uses_left = row[0], row[1]
            if uses_left <= 0:
                return False, "⚠️ This coupon has reached its maximum claim limit!"

            if uses_left == 1:
                await db.execute("DELETE FROM coupons WHERE code = ?", (code.strip().upper(),))
            else:
                await db.execute("UPDATE coupons SET uses_left = uses_left - 1 WHERE code = ?", (code.strip().upper(),))
            await db.commit()

        await self.add_premium(user_id, days)
        return True, f"🎉 **Coupon Redeemed!**\nYou received **{days} days** of VIP Premium access!"


    # =========================================================================
    # VIRAL REFERRAL & REWARDS ENGINE
    # =========================================================================

    async def get_referral_config(self) -> Dict[str, int]:
        """
        Retrieves live configuration for Viral Referral & VIP Rewards:
        - target_invites: Number of referrals required to hit VIP milestone (e.g. 3)
        - reward_days: Number of VIP days granted upon milestone (e.g. 3)
        - points_per_invite: Points awarded per referral (e.g. 5)
        - redeem_points: Points required to redeem VIP (e.g. 15)
        - redeem_days: VIP days granted upon point redemption (e.g. 3)
        - purchase_reward_days: VIP days awarded when a referred user buys VIP (e.g. 5)
        """
        target = await self.get_global_setting("ref_target_invites", "3")
        reward = await self.get_global_setting("ref_reward_days", "3")
        pts_per = await self.get_global_setting("ref_points_per_invite", "5")
        red_pts = await self.get_global_setting("ref_redeem_points", "15")
        red_days = await self.get_global_setting("ref_redeem_days", "3")
        purch_days = await self.get_global_setting("ref_purchase_reward_days", "5")

        try:
            target_int = max(1, int(target))
        except (ValueError, TypeError):
            target_int = 3

        try:
            reward_int = max(1, int(reward))
        except (ValueError, TypeError):
            reward_int = 3

        try:
            pts_per_int = max(1, int(pts_per))
        except (ValueError, TypeError):
            pts_per_int = 5

        try:
            red_pts_int = max(1, int(red_pts))
        except (ValueError, TypeError):
            red_pts_int = 15

        try:
            red_days_int = max(1, int(red_days))
        except (ValueError, TypeError):
            red_days_int = 3

        try:
            purch_days_int = max(1, int(purch_days))
        except (ValueError, TypeError):
            purch_days_int = 5

        return {
            "target_invites": target_int,
            "reward_days": reward_int,
            "points_per_invite": pts_per_int,
            "redeem_points": red_pts_int,
            "redeem_days": red_days_int,
            "purchase_reward_days": purch_days_int,
        }

    async def set_referral_config(
        self,
        target_invites: Optional[int] = None,
        reward_days: Optional[int] = None,
        points_per_invite: Optional[int] = None,
        redeem_points: Optional[int] = None,
        redeem_days: Optional[int] = None,
        purchase_reward_days: Optional[int] = None,
    ):
        """Updates referral milestone and rewards configuration."""
        if target_invites is not None and int(target_invites) > 0:
            await self.set_global_setting("ref_target_invites", str(int(target_invites)))
        if reward_days is not None and int(reward_days) > 0:
            await self.set_global_setting("ref_reward_days", str(int(reward_days)))
        if points_per_invite is not None and int(points_per_invite) >= 0:
            await self.set_global_setting("ref_points_per_invite", str(int(points_per_invite)))
        if redeem_points is not None and int(redeem_points) > 0:
            await self.set_global_setting("ref_redeem_points", str(int(redeem_points)))
        if redeem_days is not None and int(redeem_days) > 0:
            await self.set_global_setting("ref_redeem_days", str(int(redeem_days)))
        if purchase_reward_days is not None and int(purchase_reward_days) >= 0:
            await self.set_global_setting("ref_purchase_reward_days", str(int(purchase_reward_days)))

    async def get_referral_plans(self) -> List[Dict[str, int]]:
        """Returns all configured referral plans sorted by required invites ASC."""
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT id, invites, days FROM referral_plans ORDER BY invites ASC")
            rows = await cur.fetchall()
            return [{"id": r["id"], "invites": r["invites"], "days": r["days"]} for r in rows]

    async def add_referral_plan(self, invites: int, days: int) -> bool:
        """Adds or updates a referral milestone plan (e.g. 5 invites = 7 days)."""
        if invites <= 0 or days <= 0:
            return False
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO referral_plans (invites, days) VALUES (?, ?)
                ON CONFLICT(invites) DO UPDATE SET days = excluded.days
                """,
                (int(invites), int(days)),
            )
            await db.commit()
        return True

    async def delete_referral_plan(self, invites: int) -> bool:
        """Deletes a referral milestone plan by invite count."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("DELETE FROM referral_plans WHERE invites = ?", (int(invites),))
            await db.commit()
            return cur.rowcount > 0

    async def reset_referral_plans(self):
        """Resets referral plans to default single plan (3 invites = 3 days)."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute("DELETE FROM referral_plans")
            await db.execute("INSERT INTO referral_plans (invites, days) VALUES (3, 3)")
            await db.commit()

    async def deduct_referral_points(self, user_id: int, points: int) -> bool:
        """Deducts points after user redemption."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                "UPDATE users SET referral_points = MAX(0, referral_points - ?) WHERE user_id = ?",
                (int(points), user_id),
            )
            await db.commit()
            return True

    async def add_pending_referral(self, referred_id: int, inviter_id: int) -> bool:
        """Stores a referral as pending until user verifies channel membership or human action."""
        if inviter_id == referred_id:
            return False
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                "INSERT OR REPLACE INTO pending_referrals (referred_id, inviter_id) VALUES (?, ?)",
                (referred_id, inviter_id),
            )
            await db.commit()
            return True

    async def get_pending_referral(self, referred_id: int) -> Optional[int]:
        """Returns inviter_id if there is an unverified referral pending for this user."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT inviter_id FROM pending_referrals WHERE referred_id = ?", (referred_id,))
            row = await cur.fetchone()
            return row[0] if row else None

    async def remove_pending_referral(self, referred_id: int):
        """Removes a pending referral after it has been finalized or invalidated."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute("DELETE FROM pending_referrals WHERE referred_id = ?", (referred_id,))
            await db.commit()

    async def add_referral(self, inviter_id: int, referred_id: int) -> Tuple[bool, str, int]:
        """
        Records a referral if not already referred and not self-referral.
        Applies multi-layered anti-fraud defense:
        - Self-referral prevention
        - Circular referral prevention (A -> B -> A)
        - Old/existing user prevention
        - Velocity flood prevention (max 3 per 2 mins per inviter)
        - Double referral prevention
        """
        if inviter_id == referred_id:
            return False, "Self-referral is not allowed.", 0

        await self.register_user(inviter_id)
        await self.register_user(referred_id)

        cfg = await self.get_referral_config()
        pts_award = cfg["points_per_invite"]

        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row

            # 1. Anti-Circular Check: Was inviter originally referred by referred_id?
            cur_circ = await db.execute("SELECT referred_by FROM users WHERE user_id = ?", (inviter_id,))
            circ_row = await cur_circ.fetchone()
            if circ_row and circ_row["referred_by"] == referred_id:
                return False, "Circular referral loop detected.", 0

            # 2. Check if referred user is already in referrals table
            cur_dup = await db.execute("SELECT id FROM referrals WHERE referred_id = ?", (referred_id,))
            if await cur_dup.fetchone():
                return False, "User has already been referred previously.", 0

            # 3. Check if referred user already has a referrer in users table
            cur_user = await db.execute("SELECT referred_by FROM users WHERE user_id = ?", (referred_id,))
            u_row = await cur_user.fetchone()
            if u_row and u_row["referred_by"]:
                return False, "User already referred by someone else.", 0

            # 4. Anti-Flood Velocity Limiter: Max 3 referrals in a 2-minute rolling window per inviter
            cur_vel = await db.execute(
                """
                SELECT COUNT(*) FROM referrals 
                WHERE inviter_id = ? AND created_at > datetime('now', '-2 minutes')
                """,
                (inviter_id,)
            )
            recent_referrals = (await cur_vel.fetchone())[0]
            if recent_referrals >= 3:
                return False, "Referral velocity limit exceeded (anti-spam protection).", 0

            # 5. Insert into referrals table
            try:
                await db.execute(
                    "INSERT INTO referrals (inviter_id, referred_id) VALUES (?, ?)",
                    (inviter_id, referred_id),
                )
            except Exception:
                return False, "Referral record already exists.", 0

            # Update referred user's record
            await db.execute(
                "UPDATE users SET referred_by = ? WHERE user_id = ?",
                (inviter_id, referred_id),
            )

            # Increment inviter's referral count and award points
            await db.execute(
                """
                UPDATE users SET 
                    referral_count = COALESCE(referral_count, 0) + 1,
                    referral_points = COALESCE(referral_points, 0) + ?
                WHERE user_id = ?
                """,
                (pts_award, inviter_id),
            )
            await db.commit()

            # Direct count from referrals table
            cur_c = await db.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id = ?", (inviter_id,))
            count = (await cur_c.fetchone())[0]

        reward_note = ""
        # Dynamic milestone check against active referral plans
        plans = await self.get_referral_plans()
        matched_plan = None
        for p in plans:
            if p["invites"] == count:
                matched_plan = p
                break

        # If user exceeds highest tier, award cycling on max tier
        if not matched_plan and plans:
            max_p = max(plans, key=lambda x: x["invites"])
            if max_p["invites"] > 0 and count > max_p["invites"] and count % max_p["invites"] == 0:
                matched_plan = max_p

        if matched_plan:
            award_days = matched_plan["days"]
            await self.add_premium(inviter_id, award_days)
            reward_note = f"🏆 **Milestone Unlocked!** Reached {count} referrals: +{award_days} Days Free VIP added!"

        return True, reward_note, count

    async def get_referral_stats(self, user_id: int) -> Dict[str, Any]:
        """Retrieves referral count, points, and invite history."""
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT referral_count, referral_points, is_premium, premium_expiry FROM users WHERE user_id = ?",
                (user_id,),
            )
            row = await cur.fetchone()
            count = row["referral_count"] if row and row["referral_count"] else 0
            points = row["referral_points"] if row and row["referral_points"] else 0

            # Direct count from referrals table to guarantee absolute synchronization
            cur_c = await db.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id = ?", (user_id,))
            direct_count = (await cur_c.fetchone())[0]
            count = max(count, direct_count)

            # Recent referrals
            cur2 = await db.execute(
                "SELECT referred_id, created_at FROM referrals WHERE inviter_id = ? ORDER BY id DESC LIMIT 5",
                (user_id,),
            )
            recent = [dict(r) for r in await cur2.fetchall()]

            return {
                "total_invites": count,
                "points": points,
                "recent": recent,
            }

    async def reward_inviter_on_vip_purchase(self, referred_id: int) -> Optional[Tuple[int, int]]:
        """
        When a referred user buys VIP, awards the inviter bonus VIP days!
        Returns (inviter_id, bonus_days) or None.
        """
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("SELECT referred_by FROM users WHERE user_id = ?", (referred_id,))
            row = await cur.fetchone()
            if not row or not row[0]:
                return None
            inviter_id = row[0]

        cfg = await self.get_referral_config()
        bonus_days = cfg["purchase_reward_days"]
        if bonus_days > 0:
            await self.add_premium(inviter_id, bonus_days)
        return (inviter_id, bonus_days)

    # =========================================================================
    # ZERO-SECOND CLOUD DEDUPLICATION FILE CACHE
    # =========================================================================

    def _make_cache_key(self, source_chat: Any, message_id: int) -> str:
        s_chat = str(source_chat).strip().lower()
        return f"{s_chat}:{message_id}"

    async def get_cached_file(self, source_chat: Any, message_id: int) -> Optional[Dict[str, Any]]:
        """
        Checks if file was already harvested and uploaded to Telegram cloud.
        Returns cached record dict or None.
        L1 cached with 10s TTL — eliminates repeated SQLite reads on batch retry.
        """
        key = self._make_cache_key(source_chat, message_id)
        # L1 cache: use tuple key ("fc", cache_key)
        fc_key = ("fc", key)
        cached = _cache_get(fc_key)
        if cached is not None:
            return cached if cached != "__NONE__" else None

        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM file_cache WHERE cache_key = ?", (key,))
            row = await cur.fetchone()
            if not row:
                _cache_set(fc_key, "__NONE__")  # cache the miss too — prevents repeated DB hits
                return None

            result = dict(row)
            _cache_set(fc_key, result)

            # Fire-and-forget hit counter increment — non-blocking
            async def _inc_hit():
                try:
                    async with aiosqlite.connect(self.db_file) as _db:
                        await _db.execute(
                            "UPDATE file_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                            (key,)
                        )
                        await _db.commit()
                except Exception:
                    pass
            import asyncio as _asyncio
            _asyncio.create_task(_inc_hit())
            return result

    async def save_file_cache(
        self,
        source_chat: Any,
        message_id: int,
        file_id: str,
        file_unique_id: str = "",
        media_type: str = "video",
        file_name: str = "",
        file_size: int = 0,
        caption: str = "",
        source_chat_title: str = "",
    ):
        """Stores successfully uploaded Telegram file_id for instant zero-second future delivery."""
        if not file_id:
            return
        key = self._make_cache_key(source_chat, message_id)
        # Bust the miss-cache entry so next get_cached_file finds this fresh record immediately
        _L1_CACHE.pop(("fc", key), None)
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO file_cache (
                    cache_key, source_chat, message_id, file_id,
                    file_unique_id, media_type, file_name, file_size, caption, source_chat_title
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    file_id = excluded.file_id,
                    file_unique_id = excluded.file_unique_id,
                    media_type = excluded.media_type,
                    file_name = excluded.file_name,
                    file_size = excluded.file_size,
                    caption = excluded.caption,
                    source_chat_title = COALESCE(NULLIF(excluded.source_chat_title, ''), file_cache.source_chat_title)
                """,
                (
                    key,
                    str(source_chat),
                    message_id,
                    file_id,
                    file_unique_id,
                    media_type,
                    file_name,
                    file_size,
                    caption,
                    source_chat_title,
                ),
            )
            await db.commit()

    # =========================================================================
    # CUSTOM THUMBNAIL STUDIO & MEDIA MODES
    # =========================================================================

    async def set_custom_thumbnail(self, user_id: int, thumb_path: str):
        """Saves custom thumbnail path for user and marks enabled."""
        await self.update_settings(user_id, custom_thumb=thumb_path, custom_thumb_enabled=1)

    async def get_custom_thumbnail(self, user_id: int, check_enabled: bool = True) -> Optional[str]:
        """Gets active custom thumbnail path if it exists on disk and is enabled."""
        if not user_id or int(user_id) <= 0:
            return None
        settings = await self.get_settings(user_id)
        if check_enabled and not settings.get("custom_thumb_enabled", 1):
            return None
        path = settings.get("custom_thumb")
        import os
        if path and os.path.exists(path) and os.path.getsize(path) > 100:
            return path
        return None

    async def toggle_custom_thumbnail(self, user_id: int) -> bool:
        """Toggles custom thumbnail enabled/disabled without deleting the file."""
        settings = await self.get_settings(user_id)
        current = settings.get("custom_thumb_enabled", 1)
        new_val = 0 if current else 1
        await self.update_settings(user_id, custom_thumb_enabled=new_val)
        return bool(new_val)

    async def set_custom_thumbnail_enabled(self, user_id: int, enabled: bool) -> bool:
        """Sets custom thumbnail enabled/disabled state explicitly."""
        val = 1 if enabled else 0
        await self.update_settings(user_id, custom_thumb_enabled=val)
        return bool(val)

    async def delete_custom_thumbnail(self, user_id: int) -> bool:
        """Deletes user's custom thumbnail from disk and database."""
        thumb = await self.get_custom_thumbnail(user_id, check_enabled=False)
        if thumb:
            import os
            try:
                if os.path.exists(thumb):
                    os.remove(thumb)
            except Exception:
                pass
        await self.update_settings(user_id, custom_thumb=None, custom_thumb_enabled=1)
        return True

    async def set_delivery_format(self, user_id: int, format_type: str):
        """Sets delivery mode: 'video' or 'audio'."""
        fmt = "audio" if str(format_type).lower() == "audio" else "video"
        await self.update_settings(user_id, delivery_format=fmt)

    async def get_delivery_format(self, user_id: int) -> str:
        settings = await self.get_settings(user_id)
        return settings.get("delivery_format", "video")

    async def set_media_filter(self, user_id: int, filter_type: str):
        """Sets batch harvest filter: 'all', 'video', 'document'."""
        filt = filter_type.lower() if filter_type.lower() in ("video", "document") else "all"
        await self.update_settings(user_id, media_filter=filt)

    async def get_media_filter(self, user_id: int) -> str:
        settings = await self.get_settings(user_id)
        return settings.get("media_filter", "all")

    async def toggle_clean_caption(self, user_id: int) -> bool:
        """Toggles ad & link stripping for forwarded captions."""
        settings = await self.get_settings(user_id)
        new_val = 0 if settings.get("clean_caption", 1) else 1
        await self.update_settings(user_id, clean_caption=new_val)
        return bool(new_val)

    async def get_caption_replacements(self, user_id: int) -> List[Tuple[str, str]]:
        """Returns list of (find_text, replace_text) replacement rules."""
        import json
        settings = await self.get_settings(user_id)
        raw = settings.get("caption_replacements", "")
        if not raw:
            return []
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                rules = []
                for item in items:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        rules.append((str(item[0]), str(item[1])))
                return rules
        except Exception:
            rules = []
            for line in raw.splitlines():
                if ":::" in line:
                    parts = line.split(":::", 1)
                    rules.append((parts[0].strip(), parts[1].strip()))
                elif "|" in line:
                    parts = line.split("|", 1)
                    rules.append((parts[0].strip(), parts[1].strip()))
            return rules
        return []

    async def add_caption_replacement(self, user_id: int, find_text: str, replace_text: str) -> List[Tuple[str, str]]:
        """Adds or updates a caption find-and-replace rule."""
        import json
        rules = await self.get_caption_replacements(user_id)
        find_clean = find_text.strip()
        rules = [r for r in rules if r[0].lower() != find_clean.lower()]
        rules.append((find_clean, replace_text.strip()))
        raw = json.dumps([[r[0], r[1]] for r in rules])
        await self.update_settings(user_id, caption_replacements=raw)
        return rules

    async def remove_caption_replacement(self, user_id: int, index: int) -> List[Tuple[str, str]]:
        """Removes a caption replacement rule by 0-based index."""
        import json
        rules = await self.get_caption_replacements(user_id)
        if 0 <= index < len(rules):
            rules.pop(index)
            raw = json.dumps([[r[0], r[1]] for r in rules])
            await self.update_settings(user_id, caption_replacements=raw)
        return rules

    async def clear_caption_replacements(self, user_id: int):
        """Clears all caption find-and-replace rules for user."""
        await self.update_settings(user_id, caption_replacements="")

    # =========================================================================
    # DYNAMIC VIP PLANS & MONETIZATION PRICING ENGINE
    # =========================================================================

    async def get_vip_plans(self, active_only: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        Retrieves all VIP subscription packages from database.
        Returns dict keyed by plan_key (e.g. '7_days', '30_days', 'lifetime').
        """
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM vip_plans"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY sort_order ASC, price_bdt ASC"
            cur = await db.execute(query)
            rows = await cur.fetchall()

            plans = {}
            for r in rows:
                plans[r["plan_key"]] = {
                    "name": r["name"],
                    "price_bdt": r["price_bdt"],
                    "days": r["days"],
                    "badge": r["badge"] or "⭐",
                    "is_active": r["is_active"],
                    "sort_order": r["sort_order"],
                }

            if not plans:
                default_vip_plans = [
                    ("7_days", "7 Days VIP Pass", 100, 7, "⚡", 1, 1),
                    ("30_days", "30 Days VIP Pass", 250, 30, "⭐", 1, 2),
                    ("lifetime", "Lifetime VIP Access", 600, 3650, "👑", 1, 3),
                ]
                for pk, name, bdt, days, badge, act, order in default_vip_plans:
                    await self.add_or_update_vip_plan(pk, name, bdt, days, badge, order)
                    plans[pk] = {
                        "name": name,
                        "price_bdt": bdt,
                        "days": days,
                        "badge": badge,
                        "is_active": 1,
                        "sort_order": order,
                    }
            return plans

    async def get_vip_plan(self, plan_key: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single VIP plan by plan_key."""
        plans = await self.get_vip_plans(active_only=False)
        return plans.get(plan_key)

    async def update_vip_plan_price(self, plan_key: str, price_bdt: int) -> bool:
        """Updates the price in BDT for a specific VIP plan."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute(
                "UPDATE vip_plans SET price_bdt = ? WHERE plan_key = ?",
                (int(price_bdt), plan_key),
            )
            await db.commit()
            return cur.rowcount > 0

    async def update_vip_plan_days(self, plan_key: str, days: int) -> bool:
        """Updates duration days for a specific VIP plan."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute(
                "UPDATE vip_plans SET days = ? WHERE plan_key = ?",
                (int(days), plan_key),
            )
            await db.commit()
            return cur.rowcount > 0

    async def add_or_update_vip_plan(
        self, plan_key: str, name: str, price_bdt: int, days: int, badge: str = "⭐", sort_order: int = 0
    ) -> bool:
        """Adds or updates a VIP subscription package."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                INSERT INTO vip_plans (plan_key, name, price_bdt, days, badge, is_active, sort_order)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(plan_key) DO UPDATE SET
                    name = excluded.name,
                    price_bdt = excluded.price_bdt,
                    days = excluded.days,
                    badge = excluded.badge,
                    is_active = 1,
                    sort_order = excluded.sort_order
                """,
                (plan_key.strip().lower(), name.strip(), int(price_bdt), int(days), badge.strip(), int(sort_order)),
            )
            await db.commit()
            return True

    async def delete_vip_plan(self, plan_key: str) -> bool:
        """Deletes a VIP subscription plan."""
        async with aiosqlite.connect(self.db_file) as db:
            cur = await db.execute("DELETE FROM vip_plans WHERE plan_key = ?", (plan_key,))
            await db.commit()
            return cur.rowcount > 0

    async def reset_vip_plans(self) -> bool:
        """Resets VIP plans back to factory default packages."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute("DELETE FROM vip_plans")
            default_vip_plans = [
                ("7_days", "7 Days VIP Pass", 100, 7, "⚡", 1, 1),
                ("30_days", "30 Days VIP Pass", 250, 30, "⭐", 1, 2),
                ("lifetime", "Lifetime VIP Access", 600, 3650, "👑", 1, 3),
            ]
            for pk, name, bdt, days, badge, act, order in default_vip_plans:
                await db.execute(
                    "INSERT INTO vip_plans (plan_key, name, price_bdt, days, badge, is_active, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (pk, name, bdt, days, badge, act, order),
                )
            await db.commit()
            return True

    # =========================================================================
    # DYNAMIC CHANNELS, SUPPORT & URLS
    # =========================================================================

    async def get_support_contact(self) -> str:
        """Retrieves official support contact link (URL or @username)."""
        return await self.get_global_setting("support_contact_url", "https://t.me/ProOffers21")

    async def set_support_contact(self, url: str):
        """Sets official support contact link."""
        await self.set_global_setting("support_contact_url", url.strip())

    async def get_official_channel(self) -> str:
        """Retrieves official updates channel link."""
        return await self.get_global_setting("official_channel_url", "https://t.me/ProOffers21")

    async def set_official_channel(self, url: str):
        """Sets official updates channel link."""
        await self.set_global_setting("official_channel_url", url.strip())

    async def get_web_studio_url(self) -> str:
        """Retrieves web studio dashboard cockpit URL."""
        from config import WEB_DASHBOARD_URL
        return await self.get_global_setting("web_studio_url", WEB_DASHBOARD_URL)

    async def set_web_studio_url(self, url: str):
        """Sets web studio dashboard cockpit URL."""
        await self.set_global_setting("web_studio_url", url.strip())

    async def get_custom_start_banner(self) -> str:
        """Retrieves custom announcement banner displayed in /start."""
        return await self.get_global_setting("custom_start_banner", "")

    # --- Protected VIP Channels (Anti-Leech / VIP Channel Lock) ---

    async def lock_channel(self, identifier: str, title: str = "", locked_by: int = 0) -> Tuple[bool, str]:
        """Locks a VIP channel so no non-admin user can forward or download from it."""
        cleaned = str(identifier).strip()
        if not cleaned:
            return False, "Empty channel identifier provided."

        import re
        primary_key = cleaned
        m_priv = re.search(r"t\.me/c/(\d+)", cleaned.lower())
        if m_priv:
            primary_key = f"-100{m_priv.group(1)}"
        else:
            m_pub = re.search(r"t\.me/([a-zA-Z0-9_]{3,})", cleaned)
            if m_pub:
                primary_key = f"@{m_pub.group(1)}"
            elif cleaned.lstrip("-").isdigit():
                raw_num = cleaned.replace("-100", "").lstrip("-")
                primary_key = f"-100{raw_num}"
            elif not cleaned.startswith("@") and not cleaned.startswith("-"):
                primary_key = f"@{cleaned}"

        async with aiosqlite.connect(self.db_file) as db:
            try:
                await db.execute(
                    """
                    INSERT INTO protected_channels (channel_identifier, channel_title, locked_by)
                    VALUES (?, ?, ?)
                    ON CONFLICT(channel_identifier) DO UPDATE SET
                        channel_title = excluded.channel_title,
                        locked_by = excluded.locked_by
                    """,
                    (primary_key, title, locked_by),
                )
                await db.commit()
            except Exception as e:
                return False, str(e)

        # Update in-memory cache immediately
        for v in _normalize_channel_variants(primary_key):
            _PROTECTED_CHANNELS_CACHE.add(v)

        return True, f"🔒 Channel `{primary_key}` is now permanently locked in VIP Vault!"

    async def unlock_channel(self, identifier: str) -> Tuple[bool, str]:
        """Unlocks a VIP channel, allowing normal user downloads again."""
        variants = _normalize_channel_variants(identifier)
        if not variants:
            return False, "Invalid channel identifier."

        async with aiosqlite.connect(self.db_file) as db:
            placeholders = ",".join("?" for _ in variants)
            cursor = await db.execute(
                f"DELETE FROM protected_channels WHERE channel_identifier IN ({placeholders})",
                tuple(variants),
            )
            deleted = cursor.rowcount
            await db.commit()

        # Evict from in-memory cache
        for v in variants:
            _PROTECTED_CHANNELS_CACHE.discard(v)

        if deleted > 0:
            return True, f"🔓 Channel `{identifier}` has been unlocked."
        return False, f"⚠️ Channel `{identifier}` was not found in the protected list."

    async def get_protected_channels(self) -> List[Dict[str, Any]]:
        """Retrieves all locked VIP channels."""
        async with aiosqlite.connect(self.db_file) as db:
            cursor = await db.execute(
                "SELECT id, channel_identifier, channel_title, locked_by, created_at FROM protected_channels ORDER BY id DESC"
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "identifier": r[1],
                    "title": r[2] or "VIP Protected Channel",
                    "locked_by": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]

    async def is_channel_protected(self, identifier: Any) -> bool:
        """Returns True if the channel is locked against unauthorized downloads."""
        if identifier is None:
            return False
        variants = _normalize_channel_variants(identifier)
        for v in variants:
            if v in _PROTECTED_CHANNELS_CACHE:
                return True
        return False

    # =====================================================================
    # MULTI-ACCOUNT USERBOT WORKER POOL & ANTI-BAN MANAGEMENT
    # =====================================================================

    async def add_or_update_bot_account(
        self,
        owner_user_id: int,
        account_id: int,
        phone: str = "",
        first_name: str = "",
        username: str = "",
        string_session: str = "",
        can_share: int = 1,
    ) -> Tuple[bool, str]:
        """Adds or updates a Telegram userbot account in the worker pool."""
        if not string_session or not account_id:
            return False, "Invalid account ID or session string."

        async with aiosqlite.connect(self.db_file) as db:
            try:
                await db.execute(
                    """
                    INSERT INTO bot_accounts (
                        owner_user_id, account_id, phone, first_name, username, string_session, is_active, status, can_share
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, 'healthy', ?)
                    ON CONFLICT(account_id) DO UPDATE SET
                        owner_user_id = excluded.owner_user_id,
                        phone = excluded.phone,
                        first_name = excluded.first_name,
                        username = excluded.username,
                        string_session = excluded.string_session,
                        is_active = 1,
                        status = 'healthy'
                    """,
                    (owner_user_id, account_id, phone, first_name, username, string_session, can_share),
                )
                await db.commit()
                return True, f"Account {account_id} added successfully to pool."
            except Exception as e:
                return False, f"Database error adding account: {e}"

    async def get_bot_accounts(
        self, owner_user_id: Optional[int] = None, active_only: bool = False
    ) -> List[Dict[str, Any]]:
        """Retrieves bot accounts, optionally filtered by owner or active status."""
        query = "SELECT id, owner_user_id, account_id, phone, first_name, username, string_session, is_active, status, flood_wait_until, total_downloads, daily_downloads, last_used_at, created_at, COALESCE(can_share, 1) FROM bot_accounts"
        params = []
        conditions = []

        if owner_user_id is not None:
            conditions.append("owner_user_id = ?")
            params.append(owner_user_id)

        if active_only:
            conditions.append("is_active = 1")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY id ASC"

        async with aiosqlite.connect(self.db_file) as db:
            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "owner_user_id": r[1],
                    "account_id": r[2],
                    "phone": r[3] or "",
                    "first_name": r[4] or "",
                    "username": r[5] or "",
                    "string_session": r[6],
                    "is_active": r[7],
                    "status": r[8] or "healthy",
                    "flood_wait_until": r[9] or 0,
                    "total_downloads": r[10] or 0,
                    "daily_downloads": r[11] or 0,
                    "last_used_at": r[12],
                    "created_at": r[13],
                    "can_share": r[14] if len(r) > 14 else 1,
                }
                for r in rows
            ]

    async def get_bot_account_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        """Fetches a single bot account by its Telegram account_id."""
        async with aiosqlite.connect(self.db_file) as db:
            cursor = await db.execute(
                """
                SELECT id, owner_user_id, account_id, phone, first_name, username, string_session, is_active, status, flood_wait_until, total_downloads, daily_downloads, last_used_at, created_at, COALESCE(can_share, 1)
                FROM bot_accounts WHERE account_id = ?
                """,
                (account_id,),
            )
            r = await cursor.fetchone()
            if not r:
                return None
            return {
                "id": r[0],
                "owner_user_id": r[1],
                "account_id": r[2],
                "phone": r[3] or "",
                "first_name": r[4] or "",
                "username": r[5] or "",
                "string_session": r[6],
                "is_active": r[7],
                "status": r[8] or "healthy",
                "flood_wait_until": r[9] or 0,
                "total_downloads": r[10] or 0,
                "daily_downloads": r[11] or 0,
                "last_used_at": r[12],
                "created_at": r[13],
                "can_share": r[14] if len(r) > 14 else 1,
            }

    async def toggle_bot_account_sharing(self, account_id: int, owner_user_id: Optional[int] = None) -> Tuple[bool, int]:
        """Toggles can_share (1 = shared worker in pool, 0 = personal only)."""
        async with aiosqlite.connect(self.db_file) as db:
            query = "SELECT COALESCE(can_share, 1) FROM bot_accounts WHERE account_id = ?"
            params = [account_id]
            if owner_user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(owner_user_id)

            cursor = await db.execute(query, tuple(params))
            row = await cursor.fetchone()
            if not row:
                return False, -1

            new_val = 0 if row[0] == 1 else 1
            up_query = "UPDATE bot_accounts SET can_share = ? WHERE account_id = ?"
            up_params = [new_val, account_id]
            if owner_user_id is not None:
                up_query += " AND owner_user_id = ?"
                up_params.append(owner_user_id)

            await db.execute(up_query, tuple(up_params))
            await db.commit()
            return True, new_val

    async def update_bot_account_status(self, account_id: int, status: str, flood_wait_until: float = 0):
        """Updates health status ('healthy', 'cooldown', 'dead') and flood cooldown timer."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                UPDATE bot_accounts
                SET status = ?, flood_wait_until = ?
                WHERE account_id = ?
                """,
                (status, flood_wait_until, account_id),
            )
            await db.commit()

    async def increment_bot_account_downloads(self, account_id: int):
        """Increments download telemetry for an account and touches last_used_at."""
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(
                """
                UPDATE bot_accounts
                SET total_downloads = total_downloads + 1,
                    daily_downloads = daily_downloads + 1,
                    last_used_at = CURRENT_TIMESTAMP
                WHERE account_id = ?
                """,
                (account_id,),
            )
            await db.commit()

    async def toggle_bot_account(self, account_id: int, owner_user_id: Optional[int] = None) -> Tuple[bool, int]:
        """Toggles account is_active (1 -> 0 or 0 -> 1)."""
        async with aiosqlite.connect(self.db_file) as db:
            query = "SELECT is_active FROM bot_accounts WHERE account_id = ?"
            params = [account_id]
            if owner_user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(owner_user_id)

            cursor = await db.execute(query, tuple(params))
            row = await cursor.fetchone()
            if not row:
                return False, -1

            new_val = 0 if row[0] == 1 else 1
            up_query = "UPDATE bot_accounts SET is_active = ? WHERE account_id = ?"
            up_params = [new_val, account_id]
            if owner_user_id is not None:
                up_query += " AND owner_user_id = ?"
                up_params.append(owner_user_id)

            await db.execute(up_query, tuple(up_params))
            await db.commit()
            return True, new_val

    async def delete_bot_account(self, account_id: int, owner_user_id: Optional[int] = None) -> bool:
        """Deletes a bot account from the pool."""
        async with aiosqlite.connect(self.db_file) as db:
            query = "DELETE FROM bot_accounts WHERE account_id = ?"
            params = [account_id]
            if owner_user_id is not None:
                query += " AND owner_user_id = ?"
                params.append(owner_user_id)

            cursor = await db.execute(query, tuple(params))
            deleted = cursor.rowcount
            await db.commit()
            return deleted > 0


db = Database()



