# language: Python, file: core/client_manager.py, target: Python 3.10+, Pyrogram
"""
Enterprise Client Manager with Multi-Account Userbot Pool, Dynamic Session Routing,
Hot-Swap Failover, Proxy Support, and Anti-Ban Device Fingerprint Injection.
Every session is stamped with a realistic official device identity to minimize Telegram detection.
Supports dynamic addition, load balancing, and failover across multiple Telegram userbots.
"""

import os
import sys
import time
import asyncio
import logging

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from typing import Dict, Optional, List, Any, Tuple
from pyrogram import Client
from pyrogram.errors import ChannelInvalid, PeerIdInvalid, RPCError
import pyrogram.utils

# 64-bit Channel ID support
pyrogram.utils.MIN_CHANNEL_ID = -1009999999999999
pyrogram.utils.MAX_CHANNEL_ID = -1000000000000

_cm_orig_get_peer_type = getattr(pyrogram.utils, "_orig_get_peer_type", pyrogram.utils.get_peer_type)
def _cm_safe_get_peer_type(peer_id: int) -> str:
    if isinstance(peer_id, int):
        if peer_id <= -1000000000000:
            return "channel"
        if peer_id < 0:
            return "chat"
        if peer_id > 0:
            return "user"
    return _cm_orig_get_peer_type(peer_id)

pyrogram.utils.get_peer_type = _cm_safe_get_peer_type

def _cm_safe_get_channel_id(peer_id: int) -> int:
    return -1000000000000 - peer_id

pyrogram.utils.get_channel_id = _cm_safe_get_channel_id

# Critical: 64-bit peer resolution in Pyrogram SQLiteStorage
from pyrogram.storage.sqlite_storage import SQLiteStorage
_cm_orig_get_peer_by_id = getattr(SQLiteStorage, "_orig_get_peer_by_id", SQLiteStorage.get_peer_by_id)

async def _cm_safe_get_peer_by_id(self, peer_id: int):
    try:
        return await _cm_orig_get_peer_by_id(self, peer_id)
    except KeyError:
        s = str(peer_id)
        if s.startswith("-100"):
            alt_id = int(s[4:])
        else:
            alt_id = -int(f"100{abs(peer_id)}")
        return await _cm_orig_get_peer_by_id(self, alt_id)

SQLiteStorage._orig_get_peer_by_id = _cm_orig_get_peer_by_id
SQLiteStorage.get_peer_by_id = _cm_safe_get_peer_by_id
from config import API_ID, API_HASH, SESSIONS_DIR, ADMIN_IDS
from database import db
from core.device_spoofer import get_fingerprint_for_user
from core.rate_limiter import rate_registry
from core.parallel_uploader import install_turbo_uploader

logger = logging.getLogger(__name__)

# Dynamic Multi-Account Pool {account_id: Client}
account_pool: Dict[int, Client] = {}

# Metadata cache {account_id: {owner_user_id, phone, username, first_name, device_model}}
account_metadata: Dict[int, Dict[str, Any]] = {}

# Backward compatibility references
active_userbots: Dict[int, Client] = {}
admin_pool_clients: List[Client] = []
pool_index: int = 0
_pool_lock = asyncio.Lock()
_client_load_locks: Dict[int, asyncio.Lock] = {}


def _get_load_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _client_load_locks:
        _client_load_locks[user_id] = asyncio.Lock()
    return _client_load_locks[user_id]



async def _warmup_dialogs(client: Client):
    """Gently populates MTProto InputPeer cache in background without burst flooding Telegram."""
    try:
        count = 0
        async for _ in client.get_dialogs(limit=25):
            count += 1
            if count % 5 == 0:
                await asyncio.sleep(0.4)
    except Exception:
        pass


def get_configured_proxy() -> Optional[Dict[str, Any]]:
    """
    Parses SOCKS5/HTTP proxy from environment if configured.
    Format: socks5://user:pass@host:port or http://host:port
    """
    raw_proxy = os.getenv("TELEGRAM_PROXY", "").strip()
    if not raw_proxy:
        return None
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(raw_proxy)
        scheme_map = {
            "socks5": "socks5",
            "socks4": "socks4",
            "http": "http",
            "https": "http"
        }
        scheme = scheme_map.get(parsed.scheme.lower(), "socks5")
        proxy_dict = {
            "scheme": scheme,
            "hostname": parsed.hostname,
            "port": parsed.port or (1080 if "socks" in scheme else 8080)
        }
        if parsed.username:
            proxy_dict["username"] = parsed.username
        if parsed.password:
            proxy_dict["password"] = parsed.password
        return proxy_dict
    except Exception as e:
        print(f"[!] Invalid proxy configuration '{raw_proxy}': {e}")
        return None


async def handle_dead_session(user_id: int, reason: str = "expired", bot_client: Optional[Client] = None):
    """
    Cleans up a dead/revoked user session from memory & DB, and notifies the user
    with an interactive button to re-authenticate without crash or cryptic error.
    """
    await handle_dead_account(user_id, reason=reason, bot_client=bot_client)


async def handle_dead_account(account_id: int, reason: str = "expired", bot_client: Optional[Client] = None):
    """Marks an account dead in DB, stops client, and notifies owner if possible."""
    c = account_pool.pop(account_id, None)
    if c:
        try:
            if c.is_connected:
                await c.stop()
        except Exception:
            pass

    if account_id in active_userbots:
        active_userbots.pop(account_id, None)

    meta = account_metadata.pop(account_id, {})
    owner_id = meta.get("owner_user_id", account_id)

    await db.update_bot_account_status(account_id, "dead", flood_wait_until=0)
    try:
        print(f"[🚨 AUTO-HEAL] Account {account_id} marked DEAD ({reason}).")
    except Exception:
        logger.warning("[AUTO-HEAL] Account %s marked DEAD (%s).", account_id, reason)

    if bot_client and owner_id:
        try:
            from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 Reconnect Account (/login)", callback_data="start_qr_login")],
                [InlineKeyboardButton("👥 Multi-Account Hub (/accounts)", callback_data="view_my_accounts")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
            ])
            await bot_client.send_message(
                chat_id=owner_id,
                text=(
                    f"⚠️ **Telegram Account Session Expired / Terminated**\n\n"
                    f"• Account ID: `{account_id}`\n"
                    f"• Reason: `{reason}`\n\n"
                    "The session was revoked by Telegram or logged out from devices.\n\n"
                    "👉 **Click below to reconnect safely:**"
                ),
                reply_markup=markup
            )
        except Exception as e:
            logger.debug("Could not send session-expired alert to owner %s: %s", owner_id, e)


def mark_account_flood_wait(account_id: int, wait_seconds: int):
    """Marks an account into cooldown quarantine in memory & DB."""
    flood_until = time.time() + wait_seconds
    limiter = rate_registry.get_sync(f"account_{account_id}")
    limiter.on_flood_wait(wait_seconds)
    asyncio.create_task(db.update_bot_account_status(account_id, "cooldown", flood_wait_until=flood_until))
    print(f"[⏳ COOLDOWN] Account {account_id} quarantined for {wait_seconds}s until {time.ctime(flood_until)}")


async def load_bot_account_client(account_record: Dict[str, Any]) -> Optional[Client]:
    """Instantiates and starts a Client for a bot_accounts DB record."""
    account_id = account_record.get("account_id")
    string_session = account_record.get("string_session")
    if not account_id or not string_session:
        return None

    # Deterministic official device fingerprint: never fluctuates, avoids device-mismatch ban
    fingerprint = get_fingerprint_for_user(account_id)
    proxy = get_configured_proxy()

    client_kwargs = {
        "name": f"account_{account_id}",
        "api_id": API_ID,
        "api_hash": API_HASH,
        "session_string": string_session.strip(),
        "in_memory": True,
        "max_concurrent_transmissions": 20,
        "workers": 32,
        "ipv6": False,
        "no_updates": True,
        "sleep_threshold": 60,
        **fingerprint,
    }
    if proxy:
        client_kwargs["proxy"] = proxy

    client = Client(**client_kwargs)
    install_turbo_uploader(client)
    try:
        await client.start()
        me = await client.get_me()
        raw_is_prem = bool(getattr(me, "is_premium", False))
        db_is_prem = bool(account_record.get("is_tg_premium", 0))
        is_tg_prem = raw_is_prem or db_is_prem

        if raw_is_prem and not db_is_prem:
            try:
                asyncio.create_task(db.update_bot_account_tg_premium(account_id, True))
            except Exception:
                pass

        owner_id = account_record.get("owner_user_id", account_id)
        is_admin_owner = (owner_id in ADMIN_IDS or account_id in ADMIN_IDS)

        # Dynamic Smart Worker Policy:
        # 1. Admin/owner accounts (AN0N's 20+ workers) -> ALWAYS dedicated shared workers in pool (can_share=1)
        # 2. Ordinary user accounts with Telegram Premium -> ALWAYS enlisted into Turbo Worker Pool (can_share=1)
        # 3. Regular free users -> Keep isolated as Personal Only (can_share=0) to prevent FloodWait on their private numbers
        if is_admin_owner or is_tg_prem:
            effective_can_share = 1
            try:
                asyncio.create_task(db.set_bot_account_sharing(account_id, 1))
            except Exception:
                pass
        else:
            effective_can_share = account_record.get("can_share", 0)

        # Stash client in dynamic pool
        account_pool[account_id] = client
        active_userbots[account_id] = client
        account_metadata[account_id] = {
            "owner_user_id": owner_id,
            "phone": account_record.get("phone", ""),
            "username": getattr(me, "username", "") or account_record.get("username", ""),
            "first_name": getattr(me, "first_name", "") or account_record.get("first_name", ""),
            "can_share": effective_can_share,
            "device_model": fingerprint.get("device_model", "Official Telegram"),
            "is_tg_premium": is_tg_prem,
        }
        if is_tg_prem:
            logger.info("[👑 TURBO VIP] Account %s (@%s) is TELEGRAM PREMIUM! Prioritized as Global Turbo Downloader.", account_id, getattr(me, "username", ""))
        # Initialize isolated rate limiter for this account
        rate_registry.get_sync(f"account_{account_id}")
        # Pre-warm dialogs in background non-blocking
        asyncio.create_task(_warmup_dialogs(client))
        return client
    except Exception as e:
        logger.warning("Could not start account %s: %s", account_id, e)
        err_str = str(e).upper()
        fatal_errors = (
            "AUTH_KEY_UNREGISTERED",
            "AUTH_KEY_INVALID",
            "USER_DEACTIVATED",
            "SESSION_REVOKED",
            "SESSION_EXPIRED",
        )
        if any(f in err_str for f in fatal_errors):
            await handle_dead_account(account_id, reason=str(e))
        else:
            logger.info("Account %s temporary network error: %s. Session preserved.", account_id, e)
        return None


async def register_and_start_account(
    owner_user_id: int,
    account_id: int,
    string_session: str,
    phone: str = "",
    first_name: str = "",
    username: str = "",
    can_share: int = 1,
) -> Tuple[bool, str, Optional[Client]]:
    """
    Dynamically registers a newly authenticated Telegram account into DB and active pool.
    Hot-adds the account with 0 seconds downtime and 0 bot restart!
    """
    if not string_session or not account_id:
        return False, "Invalid account ID or session string.", None

    # 1. ALWAYS persist user session in users table first (guaranteed persistence across updates)
    try:
        await db.save_session(owner_user_id, phone=phone, string_session=string_session)
    except Exception as e:
        logger.error("Error saving user session for %s: %s", owner_user_id, e)

    # 2. Add or update in bot_accounts pool
    ok, msg = await db.add_or_update_bot_account(
        owner_user_id=owner_user_id,
        account_id=account_id,
        phone=phone,
        first_name=first_name,
        username=username,
        string_session=string_session,
        can_share=can_share,
    )

    # Sync immediately to disk vault (data/sessions_vault.json) & .env
    try:
        from core.auto_recover import sync_db_to_sessions_vault
        from config import DB_PATH
        sync_db_to_sessions_vault(DB_PATH)
    except Exception as e:
        logger.warning("Error syncing to vault: %s", e)

    # 3. If already running, stop old instance first
    if account_id in account_pool:
        old_c = account_pool.pop(account_id, None)
        try:
            if old_c and old_c.is_connected:
                await old_c.stop()
        except Exception:
            pass

    record = {
        "account_id": account_id,
        "owner_user_id": owner_user_id,
        "phone": phone,
        "first_name": first_name,
        "username": username,
        "string_session": string_session,
        "can_share": can_share,
    }
    client = await load_bot_account_client(record)
    if client:
        return True, "Account successfully activated!", client
    return True, "Account session saved safely in database.", None


async def unregister_account(account_id: int, owner_user_id: Optional[int] = None) -> bool:
    """Removes an account from active memory pool and deletes it from database."""
    c = account_pool.pop(account_id, None)
    if c:
        try:
            if c.is_connected:
                await c.stop()
        except Exception:
            pass
    active_userbots.pop(account_id, None)
    account_metadata.pop(account_id, None)
    deleted = await db.delete_bot_account(account_id, owner_user_id)
    try:
        from core.auto_recover import sync_db_to_sessions_vault
        from config import DB_PATH
        sync_db_to_sessions_vault(DB_PATH)
    except Exception as e:
        logger.warning("Error syncing to vault after deletion: %s", e)
    return deleted


async def toggle_account_active(account_id: int, owner_user_id: Optional[int] = None) -> Tuple[bool, int]:
    """Toggles account active state (pauses or resumes worker)."""
    ok, new_state = await db.toggle_bot_account(account_id, owner_user_id)
    if not ok:
        return False, -1

    if new_state == 0:
        # Paused -> stop client
        c = account_pool.pop(account_id, None)
        if c:
            try:
                if c.is_connected:
                    await c.stop()
            except Exception:
                pass
        active_userbots.pop(account_id, None)
    else:
        # Resumed -> start client
        rec = await db.get_bot_account_by_id(account_id)
        if rec:
            await load_bot_account_client(rec)

    return True, new_state


async def toggle_account_premium(account_id: int) -> Tuple[bool, int]:
    """Toggles account Telegram Premium Turbo VIP state and syncs in-memory metadata."""
    ok, new_state = await db.toggle_bot_account_tg_premium(account_id)
    if not ok:
        return False, -1

    if account_id in account_metadata:
        account_metadata[account_id]["is_tg_premium"] = bool(new_state)
        if new_state == 1:
            account_metadata[account_id]["can_share"] = 1
            await db.set_bot_account_sharing(account_id, 1)
    else:
        account_metadata[account_id] = {
            "owner_user_id": account_id,
            "can_share": 1,
            "is_tg_premium": bool(new_state),
        }

    return True, new_state


async def get_personal_user_client(user_id: int) -> Optional[Client]:
    """
    Returns strictly the personal Pyrogram client for user_id (where client Telegram ID matches user_id).
    Excludes third-party worker accounts merely configured/added by an admin.
    """
    if not user_id:
        return None

    # 1. First check if personal client is already loaded in account_pool
    if user_id in account_pool:
        client = account_pool[user_id]
        if not getattr(client, "is_connected", False):
            try:
                await client.connect()
            except Exception:
                pass
        if getattr(client, "is_connected", False):
            me = getattr(client, "me", None)
            if me and me.id == user_id:
                return client
            elif not me:
                try:
                    me = await client.get_me()
                    if me and me.id == user_id:
                        return client
                except Exception:
                    pass

    # 2. Check if user has personal session in DB
    async with _get_load_lock(user_id):
        session_string = await db.get_session(user_id)
        if session_string:
            # Check if this session is already loaded under another key or invalid
            rec = {
                "account_id": user_id,
                "owner_user_id": user_id,
                "string_session": session_string,
                "can_share": 0,
            }
            client = await load_bot_account_client(rec)
            if client and getattr(client, "is_connected", False):
                me = getattr(client, "me", None)
                if me and me.id == user_id:
                    return client
                elif not me:
                    try:
                        me = await client.get_me()
                        if me and me.id == user_id:
                            return client
                    except Exception:
                        pass
    return None


_verified_chat_access: Dict[Tuple[str, str], float] = {}


async def resolve_chat_access(client: Client, chat_id: Any) -> bool:
    """
    Tests if client has access to chat_id.
    Handles Pyrogram MTProto peer resolution and dialog syncing without invoking
    GetFullChannel (which causes 0xa04e8d3a ChannelFull deserialization crashes on Layer 158).
    Includes high-performance TTL cache to eliminate redundant get_dialogs RPC sweeps.
    """
    if not client or not getattr(client, "is_connected", False):
        return False

    c_key = getattr(client, "name", "client")
    ch_key = str(chat_id)
    cache_key = (c_key, ch_key)
    now = time.time()
    if cache_key in _verified_chat_access:
        if now < _verified_chat_access[cache_key]:
            return True

    target_raw = None
    try:
        target_raw = int(str(chat_id).replace("-100", "").lstrip("-"))
    except Exception:
        pass

    # 1. Direct peer cache hit check (fastest, 0 RPC calls if cached)
    try:
        peer = await client.resolve_peer(chat_id)
        if peer:
            _verified_chat_access[cache_key] = now + 3600
            return True
    except Exception:
        pass

    # 2. Peer cache miss — MTProto needs get_dialogs to learn access_hash
    try:
        count = 0
        async for dialog in client.get_dialogs(limit=50):
            count += 1
            if dialog.chat:
                d_id = dialog.chat.id
                d_raw = None
                try:
                    d_raw = int(str(d_id).replace("-100", "").lstrip("-"))
                except Exception:
                    pass
                if d_id == chat_id or (target_raw is not None and d_raw == target_raw):
                    _verified_chat_access[cache_key] = now + 3600
                    return True
            if count % 10 == 0:
                await asyncio.sleep(0.05)
    except Exception:
        pass

    # 3. Final verification after dialog sync
    try:
        peer = await client.resolve_peer(chat_id)
        if peer:
            _verified_chat_access[cache_key] = now + 3600
            return True
        return False
    except Exception:
        return False


async def get_client_for_channel(chat_id: Any, user_id: Optional[int] = None) -> Tuple[Optional[Client], str]:
    """
    Resolves the best client that has access to chat_id:
    1. Checks user's personal client (highest priority for private channels).
    2. If personal client doesn't have access or user isn't logged in, checks all healthy worker accounts in the pool.
    Returns: (client, reason)
    reason can be: "personal", "worker", "no_session", or "not_in_channel".
    """
    personal_client = None
    if user_id:
        personal_client = await get_personal_user_client(user_id)
        if personal_client:
            has_access = await resolve_chat_access(personal_client, chat_id)
            if has_access:
                return personal_client, "personal"

    # Check worker accounts in pool
    candidate_workers: List[Client] = []
    for aid, client in list(account_pool.items()):
        if client.is_connected and client != personal_client:
            meta = account_metadata.get(aid, {})
            if meta.get("can_share", 1):
                candidate_workers.append(client)

    for ac in admin_pool_clients:
        if ac.is_connected and ac != personal_client and ac not in candidate_workers:
            candidate_workers.append(ac)

    for worker in candidate_workers:
        has_access = await resolve_chat_access(worker, chat_id)
        if has_access:
            return worker, "worker"

    if not personal_client:
        return None, "no_session"
    else:
        return None, "not_in_channel"


async def get_user_client(user_id: int, prefer_premium: bool = True) -> Optional[Client]:
    """
    Returns an active Pyrogram client for downloading:
    1. TOP PRIORITY: If any healthy Telegram Premium account exists in the pool (with can_share=1),
       use it as the Global Turbo Downloader so all users get 30-50+ MB/s MTProto speeds!
    2. If no shared Premium account is available, and the user owns personal connected accounts,
       selects a healthy personal account.
    3. Otherwise selects the next healthy account from the general multi-account worker pool.
    4. Seamlessly skips accounts on FloodWait or quarantine.
    """
    global pool_index
    now = time.time()

    # 1. Global Turbo Downloader: Prioritize real Telegram Premium accounts first, then fallback to normal admin workers
    if prefer_premium:
        real_premium_candidates: List[Client] = []
        normal_admin_candidates: List[Client] = []

        for aid, client in list(account_pool.items()):
            if client.is_connected:
                meta = account_metadata.get(aid, {})
                owner_id = meta.get("owner_user_id", aid)
                is_admin_acc = (owner_id in ADMIN_IDS or aid in ADMIN_IDS)
                is_tg_prem = bool(meta.get("is_tg_premium") or getattr(getattr(client, "me", None), "is_premium", False))
                
                # Any premium account (admin or logged-in user) OR any normal admin worker operates in pool
                if meta.get("can_share", 1):
                    limiter = rate_registry.get_sync(f"account_{aid}")
                    if not limiter.is_quarantined:
                        if is_tg_prem:
                            real_premium_candidates.append(client)
                        elif is_admin_acc:
                            normal_admin_candidates.append(client)

        # Include legacy admin pool clients from .env
        for c in admin_pool_clients:
            if c.is_connected and c not in real_premium_candidates and c not in normal_admin_candidates:
                limiter = rate_registry.get_sync(getattr(c, "name", "unknown"))
                if not limiter.is_quarantined:
                    normal_admin_candidates.append(c)

        # 1st PRIORITY: Real Telegram Premium accounts (AN0N's premium ID or stealth enlisted user premium IDs)
        if real_premium_candidates:
            selected = real_premium_candidates[pool_index % len(real_premium_candidates)]
            pool_index += 1
            return selected

        # 2nd PRIORITY: Normal admin worker accounts (rotates through the 20 normal accounts to avoid flood wait)
        if normal_admin_candidates:
            selected = normal_admin_candidates[pool_index % len(normal_admin_candidates)]
            pool_index += 1
            return selected

    # 2. Check personal account belonging directly to this user
    personal_c = await get_personal_user_client(user_id)
    if personal_c:
        limiter = rate_registry.get_sync(f"account_{user_id}")
        if not limiter.is_quarantined:
            return personal_c

    # 3. Round-robin through all healthy accounts in the general multi-account worker pool
    all_healthy_pool: List[Client] = []
    for aid, client in account_pool.items():
        if client.is_connected:
            meta = account_metadata.get(aid, {})
            # Only use accounts designated for shared worker pooling
            if meta.get("can_share", 1):
                limiter = rate_registry.get_sync(f"account_{aid}")
                if not limiter.is_quarantined:
                    all_healthy_pool.append(client)

    if all_healthy_pool:
        client = all_healthy_pool[pool_index % len(all_healthy_pool)]
        pool_index += 1
        return client

    # 4. Check shared admin legacy pool
    if admin_pool_clients:
        for c in admin_pool_clients:
            if c.is_connected:
                limiter = rate_registry.get_sync(getattr(c, "name", "unknown"))
                if not limiter.is_quarantined:
                    return c

    return None


def get_next_available_pool_client(exclude_client: Optional[Client] = None) -> Optional[Client]:
    """
    Hot-swap failover: returns an alternate, unquarantined client from the multi-account pool.
    Called immediately when a userbot encounters FLOOD_WAIT or PEER_FLOOD.
    """
    # 1. Search in dynamic multi-account pool
    for aid, c in account_pool.items():
        if c == exclude_client or not c.is_connected:
            continue
        limiter = rate_registry.get_sync(f"account_{aid}")
        if not limiter.is_quarantined:
            return c

    # 2. Search in legacy admin pool
    for c in admin_pool_clients:
        if c == exclude_client or not c.is_connected:
            continue
        limiter = rate_registry.get_sync(getattr(c, "name", "unknown"))
        if not limiter.is_quarantined:
            return c

    return None


async def initialize_all_bot_accounts():
    """
    Called on bot boot. Connects all active accounts from bot_accounts database.
    Staggers connections by 0.4s to avoid burst IP-level flags.
    """
    try:
        records = await db.get_bot_accounts(active_only=True)
        if not records:
            print("[*] Multi-Account Pool: No accounts registered in database yet.")
            return

        print(f"[*] Booting Multi-Account Worker Pool: Loading {len(records)} active account(s)...")
        for rec in records:
            try:
                aid = rec["account_id"]
                c = await load_bot_account_client(rec)
                if c:
                    fp = get_fingerprint_for_user(aid)
                    uname = rec.get("username") or rec.get("first_name") or str(aid)
                    print(f"  [+] Worker @{uname} [{aid}] online [{fp.get('device_model')}]")
                await asyncio.sleep(0.5)  # gentle 0.5s stagger avoids IP-level Telegram connection burst flags
            except Exception as e:
                print(f"  [!] Failed loading worker {rec.get('account_id')}: {e}")
    except Exception as e:
        print(f"[!] Error in initialize_all_bot_accounts: {e}")


async def initialize_admin_pool(sessions: List[str]):
    """Initializes legacy admin pool userbots from .env and auto-migrates them into bot_accounts."""
    global admin_pool_clients
    proxy = get_configured_proxy()

    for idx, sess in enumerate(sessions):
        if not sess or not sess.strip():
            continue
        try:
            import hashlib
            sess_clean = sess.strip()
            seed_val = int(hashlib.md5(sess_clean.encode()).hexdigest()[:8], 16)
            fingerprint = get_fingerprint_for_user(seed_val)
            client_kwargs = {
                "name": f"admin_pool_{idx}",
                "api_id": API_ID,
                "api_hash": API_HASH,
                "session_string": sess_clean,
                "in_memory": True,
                "max_concurrent_transmissions": 20,
                "workers": 32,
                "ipv6": False,
                "no_updates": True,
                "sleep_threshold": 60,
                **fingerprint,
            }
            if proxy:
                client_kwargs["proxy"] = proxy

            client = Client(**client_kwargs)
            install_turbo_uploader(client)
            await client.start()
            admin_pool_clients.append(client)
            me = await client.get_me()
            print(f"[+] Legacy pool account {idx+1} loaded: @{me.username or me.id} [{fingerprint['device_model']}]")
            rate_registry.get_sync(f"admin_pool_{idx}")

            # Auto-save to bot_accounts DB
            primary_admin = ADMIN_IDS[0] if ADMIN_IDS else me.id
            is_tg_prem = bool(getattr(me, "is_premium", False))
            db_rec = await db.get_bot_account_by_id(me.id)
            if db_rec and db_rec.get("is_tg_premium"):
                is_tg_prem = True

            await db.add_or_update_bot_account(
                owner_user_id=primary_admin,
                account_id=me.id,
                phone=me.phone_number or "",
                first_name=me.first_name or "",
                username=me.username or "",
                string_session=sess_clean,
                can_share=1,
                is_tg_premium=1 if is_tg_prem else 0,
            )
            account_pool[me.id] = client
            account_metadata[me.id] = {
                "owner_user_id": primary_admin,
                "phone": me.phone_number or "",
                "username": me.username or "",
                "first_name": me.first_name or "",
                "can_share": 1,
                "device_model": fingerprint.get("device_model", "Official Telegram"),
                "is_tg_premium": is_tg_prem,
            }
        except Exception as e:
            print(f"[!] Could not load admin pool account {idx+1}: {e}")


async def warmup_all_active_sessions():
    """Warms up all registered bot accounts and active user personal sessions on startup."""
    await initialize_all_bot_accounts()

    # Pre-warm any personal user sessions from users table not yet loaded into account_pool
    try:
        active_sessions = await db.get_all_active_sessions()
        for uid, s_str in active_sessions:
            if uid not in account_pool and s_str:
                rec = {
                    "account_id": uid,
                    "owner_user_id": uid,
                    "string_session": s_str,
                    "can_share": 1,
                }
                c = await load_bot_account_client(rec)
                if c:
                    logger.info("Warmed up personal user session %s", uid)
    except Exception as e:
        logger.warning("Error warming up active user personal sessions: %s", e)


async def stop_all_user_clients():
    """Gracefully stops all active userbot sessions and admin pool on bot shutdown."""
    for aid, client in list(account_pool.items()):
        try:
            if client.is_connected:
                await client.stop()
        except Exception:
            pass
    account_pool.clear()
    active_userbots.clear()

    for client in admin_pool_clients:
        try:
            if client.is_connected:
                await client.stop()
        except Exception:
            pass
    admin_pool_clients.clear()


async def sync_pool_with_database() -> int:
    """
    Scans database for any active, healthy accounts that are currently missing
    from in-memory account_pool, and mounts them.
    Guarantees accounts added while bot was running or restored by auto-recover
    are immediately mounted with 0 downtime and 0 bot restart!
    """
    loaded_count = 0
    try:
        from database import db
        records = await db.get_bot_accounts(active_only=True)
        for rec in records:
            aid = rec.get("account_id")
            if not aid:
                continue
            if aid not in account_pool:
                try:
                    c = await load_bot_account_client(rec)
                    if c and c.is_connected:
                        loaded_count += 1
                        logger.info("[Guardian] Dynamically mounted worker account %s into active pool.", aid)
                except Exception as e:
                    logger.debug("[Guardian] Could not load account %s: %s", aid, e)
                await asyncio.sleep(0.3)
    except Exception as e:
        logger.warning("[Guardian] Error in sync_pool_with_database: %s", e)
    return loaded_count


async def check_and_revive_dead_accounts() -> int:
    """
    Attempts to re-test and revive any bot_accounts marked 'dead' or missing from pool.
    If Telegram accepts the session, restores status to 'healthy' and mounts to pool.
    Returns count of successfully revived accounts.
    """
    revived = 0
    try:
        from database import db
        all_accs = await db.get_bot_accounts(active_only=False)
        for rec in all_accs:
            if rec.get("status") == "dead" and rec.get("string_session"):
                aid = rec["account_id"]
                try:
                    c = await load_bot_account_client(rec)
                    if c and c.is_connected:
                        await db.update_bot_account_status(aid, "healthy", flood_wait_until=0)
                        revived += 1
                        logger.info("[Guardian] Successfully revived previously dead account %s!", aid)
                except Exception as e:
                    logger.debug("[Guardian] Account %s still inactive: %s", aid, e)
                await asyncio.sleep(0.5)
    except Exception as e:
        logger.warning("[Guardian] Error in check_and_revive_dead_accounts: %s", e)
    return revived


async def ping_all_active_sessions(bot_client: Optional[Client] = None):
    """
    Sends a lightweight keep-alive heartbeat ping to Telegram servers for all connected accounts.
    Keeps MTProto TCP connections alive and prevents Telegram server from terminating idle sessions.
    """
    for aid, client in list(account_pool.items()):
        try:
            if not getattr(client, "is_connected", False):
                try:
                    await client.connect()
                except Exception:
                    pass

            if getattr(client, "is_connected", False):
                # Lightweight MTProto query to keep socket & session auth key active
                await client.get_me()
            await asyncio.sleep(1.5)  # Staggered to prevent burst requests
        except Exception as e:
            err_str = str(e).upper()
            fatal_errors = (
                "AUTH_KEY_UNREGISTERED",
                "AUTH_KEY_INVALID",
                "USER_DEACTIVATED",
                "SESSION_REVOKED",
                "SESSION_EXPIRED",
            )
            if any(f in err_str for f in fatal_errors):
                logger.warning("[Guardian] Account %s session revoked by Telegram: %s", aid, e)
                await handle_dead_account(aid, reason=str(e), bot_client=bot_client)
            else:
                logger.debug("[Guardian] Account %s transient ping warning: %s (session preserved)", aid, e)


async def session_heartbeat_guardian(bot_client: Optional[Client] = None):
    """
    24/7 Enterprise Session Keep-Alive & Anti-Logout Guardian Daemon.
    Guarantees:
    1. Zero-Idle Timeout: Sends MTProto heartbeat pings every 10 minutes so Telegram never
       terminates inactive worker or user sessions.
    2. Dynamic Auto-Mount: Immediately detects and mounts any accounts in the database
       that are missing from account_pool (e.g. after container redeploy or db restore).
    3. Auto-Heal & Auto-Reconnect: Reconnects dropped sockets without marking dead.
    4. Disk Vault Sync: Keeps data/sessions_vault.json and .env updated.
    """
    logger.info("🛡️ [Guardian] Session Keep-Alive & Anti-Logout Guardian starting...")

    # Fast initial sync 4 seconds after startup to ensure newly restored DB accounts are loaded
    await asyncio.sleep(4)
    try:
        await sync_pool_with_database()
        from core.auto_recover import sync_db_to_sessions_vault
        from config import DB_PATH
        sync_db_to_sessions_vault(DB_PATH)
    except Exception as e:
        logger.warning("[Guardian] Initial sync error: %s", e)

    while True:
        try:
            # If account_pool is completely empty, poll every 20s until accounts appear in DB
            if not account_pool:
                await sync_pool_with_database()
                if not account_pool:
                    await asyncio.sleep(20)
                    continue

            # Sleep 10 minutes between heartbeat cycles
            await asyncio.sleep(600)

            # 1. Sync any new accounts added to database
            await sync_pool_with_database()

            # 2. Send MTProto keep-alive heartbeat to Telegram for all accounts
            await ping_all_active_sessions(bot_client)

            # 3. Synchronize sessions vault to disk
            try:
                from core.auto_recover import sync_db_to_sessions_vault
                from config import DB_PATH
                sync_db_to_sessions_vault(DB_PATH)
            except Exception:
                pass

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("[Guardian] Unexpected loop error: %s", e)
            await asyncio.sleep(30)

