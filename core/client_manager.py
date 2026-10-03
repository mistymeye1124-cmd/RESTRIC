# language: Python, file: core/client_manager.py, target: Python 3.10+, Pyrogram
"""
Enterprise Client Manager with Multi-Account Userbot Pool, Dynamic Session Routing,
Hot-Swap Failover, Proxy Support, and Anti-Ban Device Fingerprint Injection.
Every session is stamped with a realistic official device identity to minimize Telegram detection.
Supports dynamic addition, load balancing, and failover across multiple Telegram userbots.
"""

import os
import time
import asyncio
import logging
from typing import Dict, Optional, List, Any, Tuple
from pyrogram import Client
from config import API_ID, API_HASH, SESSIONS_DIR, ADMIN_IDS
from database import db
from core.device_spoofer import get_fingerprint_for_user
from core.rate_limiter import rate_registry

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
    await db.remove_session(account_id)
    print(f"[🚨 AUTO-HEAL] Account {account_id} marked DEAD ({reason}).")

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
    try:
        await client.start()
        me = await client.get_me()
        is_tg_prem = bool(getattr(me, "is_premium", False))

        owner_id = account_record.get("owner_user_id", account_id)
        is_admin_owner = owner_id in ADMIN_IDS

        # Dynamic Smart Worker Policy:
        # 1. Admin/owner accounts -> Always dedicated shared workers (can_share=1)
        # 2. Ordinary user accounts ->
        #    - If Telegram Premium: Silently enlist into Turbo Worker Pool (can_share=1)
        #    - If Regular/Free: Keep strictly isolated as Personal Only (can_share=0) to prevent FloodWait
        if is_admin_owner:
            effective_can_share = account_record.get("can_share", 1)
        else:
            effective_can_share = 1 if is_tg_prem else 0
            try:
                asyncio.create_task(db.set_bot_account_sharing(account_id, effective_can_share))
            except Exception:
                pass

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
    return await db.delete_bot_account(account_id, owner_user_id)


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

    # 1. Global Turbo Downloader: Prioritize Telegram Premium accounts for maximum speed
    if prefer_premium:
        premium_candidates: List[Client] = []
        for aid, client in list(account_pool.items()):
            if client.is_connected:
                meta = account_metadata.get(aid, {})
                if meta.get("is_tg_premium") and meta.get("can_share", 1):
                    limiter = rate_registry.get_sync(f"account_{aid}")
                    if not limiter.is_quarantined:
                        premium_candidates.append(client)
        if premium_candidates:
            selected = premium_candidates[pool_index % len(premium_candidates)]
            pool_index += 1
            return selected

    # 2. Check personal accounts owned by this user
    personal_healthy: List[Client] = []
    for aid, client in list(account_pool.items()):
        meta = account_metadata.get(aid, {})
        if meta.get("owner_user_id") == user_id or aid == user_id:
            if not client.is_connected:
                try:
                    await client.connect()
                except Exception:
                    pass
            if client.is_connected:
                limiter = rate_registry.get_sync(f"account_{aid}")
                if not limiter.is_quarantined:
                    personal_healthy.append(client)

    if personal_healthy:
        client = personal_healthy[pool_index % len(personal_healthy)]
        pool_index += 1
        return client

    # 2. Check if user has session in DB not yet loaded or if account in pool needs re-initialization
    async with _get_load_lock(user_id):
        # Re-check personal after acquiring lock
        for aid, client in list(account_pool.items()):
            meta = account_metadata.get(aid, {})
            if (meta.get("owner_user_id") == user_id or aid == user_id) and client.is_connected:
                return client

        session_string = await db.get_session(user_id)
        if session_string:
            if user_id in account_pool:
                old_c = account_pool.pop(user_id, None)
                try:
                    if old_c and old_c.is_connected:
                        await old_c.stop()
                except Exception:
                    pass
            rec = {
                "account_id": user_id,
                "owner_user_id": user_id,
                "string_session": session_string,
                "can_share": 1,
            }
            client = await load_bot_account_client(rec)
            if client and client.is_connected:
                return client

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
                await asyncio.sleep(0.4)  # stagger
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
            await client.start()
            admin_pool_clients.append(client)
            me = await client.get_me()
            print(f"[+] Legacy pool account {idx+1} loaded: @{me.username or me.id} [{fingerprint['device_model']}]")
            rate_registry.get_sync(f"admin_pool_{idx}")

            # Auto-save to bot_accounts DB
            primary_admin = ADMIN_IDS[0] if ADMIN_IDS else me.id
            await db.add_or_update_bot_account(
                owner_user_id=primary_admin,
                account_id=me.id,
                phone=me.phone_number or "",
                first_name=me.first_name or "",
                username=me.username or "",
                string_session=sess_clean,
                can_share=1,
            )
            account_pool[me.id] = client
            account_metadata[me.id] = {
                "owner_user_id": primary_admin,
                "phone": me.phone_number or "",
                "username": me.username or "",
                "first_name": me.first_name or "",
                "can_share": 1,
                "device_model": fingerprint.get("device_model", "Official Telegram"),
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
