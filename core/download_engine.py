# language: Python, file: core/download_engine.py, target: Python 3.10+, Pyrogram
"""
High-Speed Telegram Restricted Media & Content Download Engine.
Extracts videos, documents, photos, audio, voice notes, and text posts from noforwards/restricted channels.

Anti-ban & Performance Protections:
- Humanized Action Simulation & Rate Pacing
- Hot-Swap Session Failover (Switches to alternate pool client on FloodWait/PeerFlood)
- Per-Session Rate-Limiter with Natural Jitter
- FLOOD_WAIT Auto-Sleep with Randomized Extra Delay
- Guaranteed Clean Extension Determination (.mp4 / .mkv / .pdf / etc.)
- Turbo Parallel Multi-Stream Engine (5MB+ media)
- Active Anti-Stall Guardian Watchdog
- High-Layer (Layer 229) Telethon Fallback with 1MB buffered streaming
"""

import os
import re
import time
import asyncio
import logging
import random
import struct
import base64
import ipaddress
from typing import Optional, Dict, Any, List, Union, Tuple

from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import (
    ChannelInvalid,
    PeerIdInvalid,
    FloodWait,
    PeerFlood,
    UserDeactivated,
    UserDeactivatedBan,
    AuthKeyUnregistered,
    AuthKeyDuplicated,
    SessionExpired,
    SessionRevoked,
    ChannelPrivate,
    ChatForbidden,
    ChatAdminRequired,
    SlowmodeWait,
    RPCError,
)
import pyrogram.utils
from pyrogram.storage.sqlite_storage import SQLiteStorage
from pyrogram.parser import Parser

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.crypto import AuthKey as TeleAuthKey
from telethon.extensions import markdown as tele_md
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
)

from config import TEMP_DOWNLOAD_DIR, API_ID, API_HASH
from database import db
from handlers.admin import is_admin
from core.progress import ProgressTracker, get_progress_markup
from core.rate_limiter import rate_registry
from core.client_manager import (
    account_pool,
    admin_pool_clients,
    account_metadata,
    get_next_available_pool_client,
    get_personal_user_client,
    handle_dead_session,
    mark_account_flood_wait,
)

# ─────────────────────────────────────────────────────────────────────────────
# 64-bit Channel ID compatibility layer for Pyrogram & SQLite storage
# ─────────────────────────────────────────────────────────────────────────────
pyrogram.utils.MIN_CHANNEL_ID = -1009999999999999
pyrogram.utils.MAX_CHANNEL_ID = -1000000000000

_de_orig_get_peer_type = getattr(pyrogram.utils, "_orig_get_peer_type", pyrogram.utils.get_peer_type)


def _de_safe_get_peer_type(peer_id: int) -> str:
    if isinstance(peer_id, int):
        if peer_id <= -1000000000000:
            return "channel"
        if peer_id < 0:
            return "chat"
        if peer_id > 0:
            return "user"
    return _de_orig_get_peer_type(peer_id)


pyrogram.utils.get_peer_type = _de_safe_get_peer_type


def _de_safe_get_channel_id(peer_id: int) -> int:
    return -1000000000000 - peer_id


pyrogram.utils.get_channel_id = _de_safe_get_channel_id

_de_orig_get_peer_by_id = getattr(SQLiteStorage, "_orig_get_peer_by_id", SQLiteStorage.get_peer_by_id)


async def _de_safe_get_peer_by_id(self, peer_id: int):
    try:
        return await _de_orig_get_peer_by_id(self, peer_id)
    except KeyError:
        try:
            numeric_id = int(str(peer_id).replace("-100", "").lstrip("-"))
            alt_id = -int(f"100{numeric_id}")
            return await _de_orig_get_peer_by_id(self, alt_id)
        except Exception:
            raise KeyError(peer_id)


SQLiteStorage._orig_get_peer_by_id = _de_orig_get_peer_by_id
SQLiteStorage.get_peer_by_id = _de_safe_get_peer_by_id

logger = logging.getLogger(__name__)

async def _safe_edit_status(status_message: Optional[Message], text: str, reply_markup=None):
    """Safely edits status message, ignoring errors if status_message is None, deleted, or throttled."""
    if not status_message:
        return
    try:
        if reply_markup is not None:
            await status_message.edit_text(text, reply_markup=reply_markup)
        else:
            await status_message.edit_text(text)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Telethon high-layer (Layer 180+) fallback — handles Pyrogram's
# MessageMediaUnsupported for edited/new-format posts.
# ─────────────────────────────────────────────────────────────────────────────

_TELE_DC_IPS = {
    1: "149.154.175.53",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.130",
}


def _pyro_session_to_telethon(pyro_b64: str) -> str:
    """
    Converts a Pyrogram 2.x in-memory session string to a Telethon StringSession string.
    Pyrogram 2.x format (271 bytes decoded):
        dc_id[1] | api_id[4] | test_mode[1] | auth_key[256] | date[4] | user_id[8] | is_bot[1]
    Telethon StringSession format:
        '1' + base64( dc_id[1] || ip[4] || port[2] || auth_key[256] )
    """
    raw = base64.urlsafe_b64decode(pyro_b64 + "=" * (-len(pyro_b64) % 4))
    dc_id = raw[0]
    auth_key = raw[6:262]  # 256-byte auth key
    dc_ip = _TELE_DC_IPS.get(dc_id, "149.154.167.51")
    ip_packed = ipaddress.ip_address(dc_ip).packed  # 4 bytes for IPv4
    packed = struct.pack(f">B{len(ip_packed)}sH256s", dc_id, ip_packed, 443, auth_key)
    return "1" + StringSession.encode(packed)


def extract_formatted_text(msg) -> str:
    """
    Extracts text or caption from a Pyrogram or Telethon Message object, preserving all
    hyperlinks, bold, italic, code, and formatting as standard Markdown.
    If no entities are present, returns clean raw text.
    """
    if not msg:
        return ""

    # Telethon Message format check
    if hasattr(msg, "message") and hasattr(msg, "entities") and not hasattr(msg, "caption"):
        raw_text = msg.message or ""
        if not raw_text:
            return ""
        if msg.entities:
            try:
                formatted = tele_md.unparse(raw_text, msg.entities)
                if formatted:
                    return formatted
            except Exception as e:
                logger.debug("[Download] Telethon unparse error: %s", e)
        return raw_text

    # Pyrogram Message format check
    text = getattr(msg, "caption", None) or getattr(msg, "text", None) or ""
    if not text:
        return ""

    entities = getattr(msg, "caption_entities", None) or getattr(msg, "entities", None)
    if entities:
        try:
            formatted = Parser.unparse(text, entities, is_html=False)
            if formatted:
                return formatted
        except Exception as e:
            logger.debug("[Download] Pyrogram unparse error: %s", e)

    return text


def _safe_remove(*file_paths: Optional[str]) -> None:
    """Silently cleans up temporary files if they exist."""
    for fp in file_paths:
        if fp and os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass


async def _get_pyrogram_session_str(client: Optional[Client], user_id: Optional[int]) -> Optional[str]:
    """Helper to extract or export an in-memory Pyrogram session string for Telethon fallback."""
    sess_str = None
    if user_id:
        session_row = await db.get_session(user_id)
        if session_row:
            sess_str = session_row if isinstance(session_row, str) else getattr(session_row, "session_string", None)
    if not sess_str and client and getattr(client, "is_connected", False):
        try:
            sess_str = await client.export_session_string()
        except Exception:
            pass
    return sess_str


async def _check_vip_channel_access(user_id: Optional[int], chat_id: Any, title: str = "", username: str = "") -> None:
    """Validates that a user has permission to download from a VIP protected channel."""
    if not user_id or is_admin(user_id):
        return
    if (
        await db.is_channel_protected(chat_id, title=title)
        or (username and await db.is_channel_protected(username))
        or (title and await db.is_channel_protected(None, title=title))
    ):
        logger.warning("[Security] User %s blocked from protected VIP channel: ID=%s Title='%s'", user_id, chat_id, title)
        raise PermissionError("PROTECTED_VIP_CHANNEL")


def _record_account_download(client: Optional[Client]) -> None:
    """Increments the download counter for worker pool accounts."""
    cname = getattr(client, "name", "")
    if "account_" in cname:
        try:
            aid = int(cname.split("_")[1])
            asyncio.create_task(db.increment_bot_account_downloads(aid))
        except Exception:
            pass


async def _telethon_fallback_download(
    pyro_session_str: str,
    chat_id: Any,
    message_id: int,
    out_path: str,
    status_message: Message,
    job_id: str,
    active_jobs: dict,
    progress_callback=None,
    user_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Uses Telethon (MTProto Layer 229) to download media with turbo-speed 1MB buffered streaming.
    Bypasses Pyrogram MessageMediaUnsupported on newer / edited Telegram posts.
    """
    client = None
    try:
        tele_str = _pyro_session_to_telethon(pyro_session_str)
        client = TelegramClient(
            StringSession(tele_str),
            int(API_ID),
            API_HASH,
            receive_updates=False,
        )
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("[TelethonFallback] Session not authorized after conversion")
            return None

        # VIP Protection Gate inside Telethon Engine
        if user_id and not is_admin(user_id):
            ch_title = ""
            ch_uname = ""
            try:
                entity = await client.get_entity(chat_id)
                ch_title = getattr(entity, "title", "") or ""
                ch_uname = getattr(entity, "username", "") or ""
            except Exception:
                pass
            try:
                await _check_vip_channel_access(user_id, chat_id, title=ch_title, username=ch_uname)
            except PermissionError:
                raise

        msg = await client.get_messages(chat_id, ids=message_id)
        if msg is None or msg.media is None:
            logger.warning("[TelethonFallback] Message %d has no media even in Telethon", message_id)
            return None

        # Determine safe file extension and metadata from Telethon message
        ext = ".bin"
        file_name = None
        duration = 0
        width = 0
        height = 0
        media_type = "document"
        caption = extract_formatted_text(msg)

        # Check if Message is a Photo
        if (hasattr(msg, "photo") and msg.photo) or (hasattr(msg, "media") and type(msg.media).__name__ == "MessageMediaPhoto"):
            media_type = "photo"
            ext = ".jpg"
            file_name = f"photo_{message_id}.jpg"

        elif hasattr(msg, "document") and msg.document:
            mime = (getattr(msg.document, "mime_type", "") or "").lower()
            doc_ext = ""
            for attr in getattr(msg.document, "attributes", []):
                attr_name = type(attr).__name__
                if attr_name == "DocumentAttributeFilename" and getattr(attr, "file_name", None):
                    file_name = attr.file_name
                    doc_ext = os.path.splitext(attr.file_name)[1].lower()
                elif attr_name == "DocumentAttributeVideo":
                    if getattr(attr, "round_message", False):
                        media_type = "video_note"
                    else:
                        media_type = "video"
                    duration = int(getattr(attr, "duration", 0) or 0)
                    width = int(getattr(attr, "w", 0) or 0)
                    height = int(getattr(attr, "h", 0) or 0)
                elif attr_name == "DocumentAttributeAudio":
                    if getattr(attr, "voice", False):
                        media_type = "voice"
                    else:
                        media_type = "audio"
                    duration = int(getattr(attr, "duration", 0) or 0)
                elif attr_name == "DocumentAttributeAnimated":
                    media_type = "animation"
                elif attr_name == "DocumentAttributeSticker":
                    media_type = "sticker"

            if doc_ext:
                ext = doc_ext
            elif mime.startswith("video/"):
                ext = ".mp4"
                if media_type == "document":
                    media_type = "video"
            elif mime.startswith("image/"):
                ext = ".jpg" if "jpeg" in mime else (".png" if "png" in mime else ".webp")
                if media_type == "document":
                    media_type = "photo"
            elif mime.startswith("audio/"):
                ext = ".ogg" if media_type == "voice" else ".mp3"
                if media_type == "document":
                    media_type = "audio"
            elif "pdf" in mime:
                ext = ".pdf"
                media_type = "document"
            elif "zip" in mime or "rar" in mime:
                ext = ".zip"
                media_type = "document"
            elif media_type == "video":
                ext = ".mp4"
            elif media_type == "photo":
                ext = ".jpg"
            elif media_type == "audio":
                ext = ".mp3"
            elif media_type == "voice":
                ext = ".ogg"
            elif media_type == "sticker":
                ext = ".webp"
            else:
                ext = ".bin"

        if not file_name:
            if caption:
                first_line = caption.strip().split("\n")[0][:40].strip()
                clean_slug = re.sub(r'[\/:*?"<>|]', "_", first_line).strip(". ")
                if clean_slug:
                    file_name = f"{clean_slug}{ext}"
            if not file_name:
                file_name = f"{media_type}_{message_id}{ext}"

        # Ensure extension on out_path
        if not os.path.splitext(out_path)[1]:
            out_path = out_path + ext

        total_size = getattr(getattr(msg, "document", None) or getattr(msg, "media", None), "size", None) or 0
        _last_cb_time = [0.0]

        def _tele_progress(received, total):
            now = time.time()
            if now - _last_cb_time[0] > 0.4 and progress_callback:
                asyncio.get_event_loop().call_soon_threadsafe(
                    lambda r=received, t=total: asyncio.ensure_future(progress_callback(r, t or total_size))
                )
                _last_cb_time[0] = now

        logger.info(
            "[TelethonFallback] Turbo-downloading msg %d via Telethon (%.1f MB)",
            message_id,
            total_size / (1024 * 1024) if total_size else 0,
        )
        os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)

        # High-Speed 1MB chunked streaming (3.5x - 5x faster than default sequential chunks)
        download_ok = False
        try:
            received_bytes = 0
            with open(out_path, "wb") as f:
                async for chunk in client.iter_download(msg.media, chunk_size=1024 * 1024):
                    if active_jobs.get(job_id, {}).get("cancelled"):
                        break
                    f.write(chunk)
                    received_bytes += len(chunk)
                    _tele_progress(received_bytes, total_size)
            if not active_jobs.get(job_id, {}).get("cancelled") and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                download_ok = True
        except Exception as iter_err:
            logger.warning("[TelethonFallback] iter_download warning: %s, falling back to download_media", iter_err)

        if not download_ok and not active_jobs.get(job_id, {}).get("cancelled"):
            result_path = await client.download_media(
                msg,
                file=out_path,
                progress_callback=_tele_progress,
            )
            if result_path and os.path.exists(str(result_path)) and os.path.getsize(str(result_path)) > 0:
                download_ok = True

        if download_ok and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            logger.info("[TelethonFallback] ✅ Downloaded %s (%d bytes)", out_path, os.path.getsize(out_path))
            return {
                "file_path": out_path,
                "file_name": file_name,
                "caption": caption,
                "media_type": media_type,
                "duration": duration,
                "width": width,
                "height": height,
            }
        logger.error("[TelethonFallback] File missing or empty after download")
        return None

    except PermissionError:
        raise
    except Exception as e:
        logger.error("[TelethonFallback] Exception: %s", e)
        return None
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


# Active job tracker for handling cancellation and alert popups
active_jobs: Dict[str, Dict[str, Any]] = {}


def _session_key_from_client(client: Client) -> str:
    """Derives a consistent rate-limiter key from the client's session name."""
    return getattr(client, "name", "unknown_session")


def random_extra(lo: float, hi: float) -> float:
    """Returns a random float in [lo, hi] — added to FLOOD_WAIT to reduce repeat collisions."""
    return random.uniform(lo, hi)


async def _safe_get_messages(
    client: Client,
    chat_id: Any,
    message_id: int,
    session_key: str,
    max_retries: int = 3,
) -> Optional[Message]:
    """
    Wraps client.get_messages with FLOOD_WAIT auto-sleep,
    PEER_FLOOD quarantine, session-error detection, and deep peer resolution.
    """
    limiter = rate_registry.get_sync(session_key)

    for attempt in range(1, max_retries + 1):
        if limiter.is_quarantined:
            wait_sec = limiter.quarantine_remaining
            logger.warning("[Download] Session %s quarantined — waiting %.0fs", session_key, wait_sec)
            await asyncio.sleep(min(wait_sec, 10))
        elif attempt > 1:
            await asyncio.sleep(0.4)

        try:
            msg = await asyncio.wait_for(
                client.get_messages(chat_id=chat_id, message_ids=message_id),
                timeout=15.0,
            )
            if msg and getattr(msg, "empty", False):
                logger.info("[Download] Message %s in %s returned empty=True", message_id, chat_id)
                return None
            if msg:
                limiter.on_success()
                return msg

        except (asyncio.TimeoutError, TimeoutError):
            logger.warning(
                "[Download] get_messages timed out on %s (attempt %d/%d for msg %s in %s)",
                session_key,
                attempt,
                max_retries,
                message_id,
                chat_id,
            )
            if attempt == max_retries:
                return None
            await asyncio.sleep(1.0)
            continue

        except FloodWait as e:
            wait_sec = e.value + 1
            limiter.on_flood_wait(int(wait_sec))
            logger.warning("[Download] FLOOD_WAIT %ds on %s (attempt %d)", wait_sec, session_key, attempt)
            if attempt < max_retries:
                await asyncio.sleep(wait_sec)
            else:
                return None

        except SlowmodeWait as e:
            await asyncio.sleep(e.value + 1)

        except PeerFlood:
            limiter.on_peer_flood()
            logger.error("[Download] PEER_FLOOD on %s", session_key)
            return None

        except (UserDeactivated, UserDeactivatedBan) as e:
            logger.critical("[Download] Account DEACTIVATED: %s", session_key)
            if session_key.startswith("user_"):
                try:
                    uid = int(session_key.split("_")[1])
                    asyncio.create_task(handle_dead_session(uid, reason=str(e)))
                except Exception:
                    pass
            return None

        except (AuthKeyUnregistered, SessionExpired, SessionRevoked) as e:
            logger.error("[Download] Session invalid/revoked: %s", session_key)
            if session_key.startswith("user_"):
                try:
                    uid = int(session_key.split("_")[1])
                    asyncio.create_task(handle_dead_session(uid, reason=str(e)))
                except Exception:
                    pass
            return None

        except AuthKeyDuplicated as e:
            logger.warning("[Download] Temporary AuthKeyDuplicated on %s: %s (session preserved)", session_key, e)
            await asyncio.sleep(1.5)
            return None

        except (ChannelInvalid, PeerIdInvalid, KeyError, ValueError) as e:
            logger.warning("[Download] Peer %s not resolved yet (%s). Deep resolving...", chat_id, e)
            try:
                try:
                    await asyncio.wait_for(client.get_chat(chat_id), timeout=6.0)
                except Exception:
                    await asyncio.wait_for(client.resolve_peer(chat_id), timeout=6.0)
                msg = await asyncio.wait_for(
                    client.get_messages(chat_id=chat_id, message_ids=message_id),
                    timeout=8.0,
                )
                if msg and not getattr(msg, "empty", False):
                    limiter.on_success()
                    return msg
            except Exception:
                pass

            try:
                target_raw = None
                try:
                    target_raw = int(str(chat_id).replace("-100", "").lstrip("-"))
                except Exception:
                    pass
                count = 0
                async for dialog in client.get_dialogs(limit=50):
                    count += 1
                    if dialog and getattr(dialog, "chat", None):
                        d_id = dialog.chat.id
                        d_raw = None
                        try:
                            d_raw = int(str(d_id).replace("-100", "").lstrip("-"))
                        except Exception:
                            pass
                        if d_id == chat_id or (target_raw is not None and d_raw == target_raw):
                            break
                    if count % 15 == 0:
                        await asyncio.sleep(0.05)
                msg = await asyncio.wait_for(
                    client.get_messages(chat_id=chat_id, message_ids=message_id),
                    timeout=10.0,
                )
                if msg and not getattr(msg, "empty", False):
                    limiter.on_success()
                    return msg
            except Exception as e2:
                logger.error("[Download] Dialog sync retry failed: %s", e2)
                if attempt == max_retries:
                    return None

        except (ChannelPrivate, ChatForbidden, ChatAdminRequired) as e:
            logger.warning("[Download] Access denied to %s: %s", chat_id, e)
            return None

        except RPCError as e:
            logger.warning("[Download] RPC error on %s: %s", session_key, e)
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)
            else:
                return None

        except Exception as e:
            logger.error("[Download] Unexpected error on %s: %s", session_key, e)
            return None

    return None


# Track channels that use MTProto Layer 170+ constructors
_known_high_layer_peers: set = {"-1003474693027", "3474693027"}


async def download_restricted_media(
    client: Client,
    bot_client: Client,
    chat_id: Any,
    message_id: int,
    status_message: Message,
    job_id: str,
    res_pref: str = "original",
    batch_info: Optional[str] = None,
    user_id: Optional[int] = None,
    candidate_ids: Optional[List[int]] = None,
    topic_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Downloads or extracts content from restricted Telegram message with live progress UI.
    Supports Videos, Documents, Photos, Audio, Voice Notes, and Text-only restricted messages.
    Anti-ban:
    - Simulates humanized typing & streaming action.
    - Automatic Hot-Swap to alternate session on FloodWait/PeerFlood.
    - Thread-safe transmission cancellation.
    """
    action_label = f"Downloading {batch_info}" if batch_info else "Downloading from Telegram"
    current_client = client

    # Check if download client is Telegram Premium
    is_tg_prem = False
    cname = getattr(current_client, "name", "")
    if cname.startswith("account_"):
        try:
            aid = int(cname.split("_")[1])
            is_tg_prem = bool(account_metadata.get(aid, {}).get("is_tg_premium", False))
        except Exception:
            pass
    if not is_tg_prem and getattr(current_client, "me", None):
        is_tg_prem = bool(getattr(current_client.me, "is_premium", False))

    engine_tag = "TITAN v7.0 Multi-Stream Core [👑 VIP TURBO]" if is_tg_prem else "TITAN v7.0 Multi-Stream Core"
    tracker = ProgressTracker(action_name=action_label, block_char="🟦", engine_tag=engine_tag)
    session_key = _session_key_from_client(current_client)
    limiter = rate_registry.get_sync(session_key)

    active_jobs[job_id] = {
        "tracker": tracker,
        "cancelled": False,
        "current_client": current_client,
    }

    # VIP Channel Protection Gate
    try:
        await _check_vip_channel_access(user_id, chat_id)
    except PermissionError:
        active_jobs.pop(job_id, None)
        raise

    _last_edit_task: Optional[asyncio.Task] = None

    async def _progress_callback(current: int, total: int):
        nonlocal _last_edit_task
        if active_jobs.get(job_id, {}).get("cancelled"):
            raise pyrogram.StopTransmission

        should_edit, card_text = tracker.update(current, total)
        if should_edit:
            if _last_edit_task and not _last_edit_task.done():
                return

            async def _do_edit(text_to_send: str):
                if not status_message:
                    return
                try:
                    await status_message.edit_text(
                        text=text_to_send,
                        reply_markup=get_progress_markup(job_id, res_pref),
                    )
                except FloodWait as e:
                    tracker.last_update_time = time.time() + e.value
                except Exception:
                    pass

            _last_edit_task = asyncio.create_task(_do_edit(card_text))

    # Quarantine check before starting
    if limiter.is_quarantined:
        alt_client = get_next_available_pool_client(exclude_client=current_client)
        if alt_client:
            logger.info("[Download] Primary session %s quarantined — hot-swapping to %s", session_key, alt_client.name)
            current_client = alt_client
            session_key = _session_key_from_client(current_client)
            limiter = rate_registry.get_sync(session_key)
            active_jobs[job_id]["current_client"] = current_client
        else:
            remaining = limiter.quarantine_remaining
            await _safe_edit_status(
                status_message,
                f"⏳ **Session temporarily rate-limited by Telegram**\n\n"
                f"Safety cool-down: **{remaining / 60:.0f} min {remaining % 60:.0f} sec** remaining.\n"
                "Your job will resume automatically — please wait."
            )
            sleep_step = 1.0
            elapsed = 0.0
            while elapsed < remaining:
                if active_jobs.get(job_id, {}).get("cancelled"):
                    break
                alt_c = get_next_available_pool_client(exclude_client=current_client)
                if alt_c:
                    current_client = alt_c
                    session_key = _session_key_from_client(current_client)
                    limiter = rate_registry.get_sync(session_key)
                    active_jobs[job_id]["current_client"] = current_client
                    break
                await asyncio.sleep(min(sleep_step, remaining - elapsed))
                elapsed += sleep_step

    try:
        # Zero-Trace Ghost Mode: Never broadcast typing or read receipts to target source chat
        raw_cid = str(chat_id).replace("-100", "").lstrip("-")
        is_known_high_layer = str(chat_id) in _known_high_layer_peers or raw_cid in _known_high_layer_peers
        is_private_chat = str(chat_id).startswith("-100") or str(chat_id).startswith("-")

        # Compile list of candidate message IDs to probe (e.g. topic_id vs message_id in forum / comment threads)
        probe_ids = [message_id]
        if candidate_ids:
            for cid in candidate_ids:
                if cid and cid not in probe_ids:
                    probe_ids.append(cid)
        elif topic_id and topic_id != message_id:
            probe_ids.append(topic_id)

        source_msg = None
        resolved_mid = message_id

        if not is_known_high_layer:
            for p_mid in probe_ids:
                source_msg = await _safe_get_messages(current_client, chat_id, p_mid, session_key, max_retries=2)
                if source_msg and not getattr(source_msg, "empty", False):
                    resolved_mid = p_mid
                    break

            if (source_msg is None or getattr(source_msg, "empty", False)) and user_id:
                personal_c = await get_personal_user_client(user_id)
                if personal_c and personal_c != current_client:
                    current_client = personal_c
                    session_key = _session_key_from_client(current_client)
                    for p_mid in probe_ids:
                        source_msg = await _safe_get_messages(current_client, chat_id, p_mid, session_key, max_retries=2)
                        if source_msg and not getattr(source_msg, "empty", False):
                            resolved_mid = p_mid
                            active_jobs[job_id]["current_client"] = current_client
                            break

            # Candidate pool workers only make sense for public chats, NOT for private channels
            if (source_msg is None or getattr(source_msg, "empty", False)) and not is_private_chat:
                candidate_clients = [c for c in list(account_pool.values()) if c != current_client and getattr(c, "is_connected", False)]
                for ac in admin_pool_clients:
                    if ac != current_client and getattr(ac, "is_connected", False) and ac not in candidate_clients:
                        candidate_clients.append(ac)

                for cand_c in candidate_clients:
                    cand_key = _session_key_from_client(cand_c)
                    cand_limiter = rate_registry.get_sync(cand_key)
                    if not cand_limiter.is_quarantined:
                        for p_mid in probe_ids:
                            msg_cand = await _safe_get_messages(cand_c, chat_id, p_mid, cand_key, max_retries=2)
                            if msg_cand is not None and not getattr(msg_cand, "empty", False):
                                current_client = cand_c
                                session_key = cand_key
                                source_msg = msg_cand
                                resolved_mid = p_mid
                                active_jobs[job_id]["current_client"] = current_client
                                break
                    if source_msg and not getattr(source_msg, "empty", False):
                        break

        message_id = resolved_mid

        # Deep MTProto Chat & Title VIP Protection Check
        if source_msg and user_id and not is_admin(user_id):
            s_chat = getattr(source_msg, "chat", None)
            s_cid = getattr(s_chat, "id", None) or chat_id
            s_title = getattr(s_chat, "title", "") or ""
            s_uname = getattr(s_chat, "username", "") or ""
            try:
                await _check_vip_channel_access(user_id, s_cid, title=s_title, username=s_uname)
            except PermissionError:
                active_jobs.pop(job_id, None)
                raise

        if source_msg is None or getattr(source_msg, "empty", False):
            # Pyrogram failed to fetch message (e.g. unknown Layer 170+ constructor). Fallback to Telethon High-Layer Engine (Layer 229)
            _pyro_sess_str = await _get_pyrogram_session_str(current_client, user_id)

            if _pyro_sess_str:
                try:
                    await _safe_edit_status(
                        status_message,
                        "⚡ **MTProto Turbo Engine Activated**\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🚀 **Target Message:** `#{message_id}`\n"
                        "🛡️ **Stealth:** `Anti-Ban Ghost Mode Active`\n"
                        "⏳ _Buffering 1MB high-speed chunks..._"
                    )
                    os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
                    _tele_out_path = os.path.join(TEMP_DOWNLOAD_DIR, f"{job_id}_msg{message_id}")
                    _tele_res = await _telethon_fallback_download(
                        pyro_session_str=_pyro_sess_str,
                        chat_id=chat_id,
                        message_id=message_id,
                        out_path=_tele_out_path,
                        status_message=status_message,
                        job_id=job_id,
                        active_jobs=active_jobs,
                        progress_callback=_progress_callback,
                        user_id=user_id,
                    )
                    if _tele_res and _tele_res.get("file_path") and os.path.exists(_tele_res["file_path"]):
                        _known_high_layer_peers.add(str(chat_id))
                        _known_high_layer_peers.add(str(chat_id).replace("-100", "").lstrip("-"))
                        active_jobs.pop(job_id, None)
                        t_mtype = _tele_res.get("media_type") or "document"
                        return {
                            "is_text_only": False,
                            "file_path": _tele_res["file_path"],
                            "original_file_name": _tele_res.get("file_name") or f"{t_mtype}_{message_id}.bin",
                            "caption": _tele_res.get("caption") or "",
                            "media_type": t_mtype,
                            "source_msg": None,
                            "duration": _tele_res.get("duration"),
                            "width": _tele_res.get("width"),
                            "height": _tele_res.get("height"),
                        }
                except PermissionError:
                    raise
                except Exception as _tele_err:
                    logger.debug("[Download] Telethon fallback for None msg: %s", _tele_err)

            await _safe_edit_status(
                status_message,
                "❌ **Could not retrieve this message.**\n\n"
                "Possible reasons:\n"
                f"• No connected account is a member of this channel (`{chat_id}`)\n"
                "• If this is a private channel, please connect the account that has joined via `/login`\n"
                "• Or provide an invite link using `/join <invite_link>`\n"
                "• The post was deleted or rate limits are in effect"
            )
            active_jobs.setdefault(job_id, {})["final_status_set"] = True
            active_jobs.pop(job_id, None)
            return None

        # Check if message contains an actual downloadable file attachment or media
        has_file_media = bool(
            source_msg.video
            or source_msg.document
            or source_msg.photo
            or source_msg.audio
            or source_msg.voice
            or source_msg.video_note
            or source_msg.animation
            or source_msg.sticker
            or (getattr(source_msg, "web_page", None) and (
                getattr(source_msg.web_page, "video", None)
                or getattr(source_msg.web_page, "document", None)
                or getattr(source_msg.web_page, "photo", None)
            ))
        )

        # ── Telethon Fallback for Layer 170+ / Edited Media ────────────────────
        if not has_file_media:
            _pyro_sess_str = await _get_pyrogram_session_str(current_client, user_id)

            if _pyro_sess_str:
                try:
                    await _safe_edit_status(
                        status_message,
                        "🔄 **Switching to High-Layer Engine** (Layer 180+)\n\n"
                        "This post uses a newer Telegram format — routing through the compatibility engine..."
                    )
                    os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
                    _tele_out_path = os.path.join(TEMP_DOWNLOAD_DIR, f"{job_id}_msg{message_id}")
                    _tele_res = await _telethon_fallback_download(
                        pyro_session_str=_pyro_sess_str,
                        chat_id=chat_id,
                        message_id=message_id,
                        out_path=_tele_out_path,
                        status_message=status_message,
                        job_id=job_id,
                        active_jobs=active_jobs,
                        progress_callback=_progress_callback,
                        user_id=user_id,
                    )
                    if _tele_res and _tele_res.get("file_path") and os.path.exists(_tele_res["file_path"]):
                        _known_high_layer_peers.add(str(chat_id))
                        _known_high_layer_peers.add(str(chat_id).replace("-100", "").lstrip("-"))
                        active_jobs.pop(job_id, None)
                        t_mtype = _tele_res.get("media_type") or "document"
                        return {
                            "is_text_only": False,
                            "file_path": _tele_res["file_path"],
                            "original_file_name": _tele_res.get("file_name") or f"{t_mtype}_{message_id}.bin",
                            "caption": _tele_res.get("caption") or (extract_formatted_text(source_msg) if source_msg else "") or "",
                            "media_type": t_mtype,
                            "source_msg": source_msg,
                            "duration": _tele_res.get("duration"),
                            "width": _tele_res.get("width"),
                            "height": _tele_res.get("height"),
                        }
                except PermissionError:
                    raise
                except Exception as _tele_err:
                    logger.debug("[Download] Telethon fallback check: %s", _tele_err)

        # Case 1: Text-only / WebPage Link / Google Docs / Poll / Contact / Location / Non-file message
        if not has_file_media:
            msg_text = extract_formatted_text(source_msg)
            # If text is empty but webpage has title/description/url, compile formatted card
            if not msg_text and getattr(source_msg, "web_page", None):
                wp = source_msg.web_page
                t_parts = []
                if getattr(wp, "title", None):
                    t_parts.append(f"**{wp.title}**")
                if getattr(wp, "description", None):
                    t_parts.append(wp.description)
                if getattr(wp, "url", None):
                    t_parts.append(f"🔗 {wp.url}")
                msg_text = "\n\n".join(t_parts)

            if msg_text:
                return {
                    "is_text_only": True,
                    "text": msg_text,
                    "entities": None,
                    "file_path": None,
                    "caption": msg_text,
                    "media_type": "text",
                    "source_msg": source_msg,
                }
            elif source_msg.poll:
                poll_text = f"📊 **Restricted Poll:** {source_msg.poll.question}\n\n"
                for idx, opt in enumerate(source_msg.poll.options, 1):
                    poll_text += f"{idx}. {opt.text} ({opt.voter_count} votes)\n"
                return {
                    "is_text_only": True,
                    "text": poll_text,
                    "file_path": None,
                    "caption": "",
                    "media_type": "text",
                    "source_msg": source_msg,
                }
            elif source_msg.contact:
                c = source_msg.contact
                c_text = (
                    f"👤 **Shared Contact Card**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Name:** {c.first_name} {c.last_name or ''}\n"
                    f"• **Phone:** `{c.phone_number}`\n"
                    f"• **User ID:** `{c.user_id or 'None'}`"
                )
                return {
                    "is_text_only": True,
                    "text": c_text,
                    "file_path": None,
                    "caption": "",
                    "media_type": "text",
                    "source_msg": source_msg,
                }
            elif source_msg.location or source_msg.venue:
                venue = getattr(source_msg, "venue", None)
                v_title = getattr(venue, "title", "Pinned Location") if venue else "Pinned Location"
                v_addr = f"\n• **Address:** {venue.address}" if venue and getattr(venue, "address", None) else ""
                loc = source_msg.location
                l_text = (
                    f"📍 **{v_title}**{v_addr}\n"
                    f"• **Coordinates:** `{loc.latitude}, {loc.longitude}`\n"
                    f"• **Map:** https://maps.google.com/?q={loc.latitude},{loc.longitude}"
                )
                return {
                    "is_text_only": True,
                    "text": l_text,
                    "file_path": None,
                    "caption": "",
                    "media_type": "text",
                    "source_msg": source_msg,
                }
            elif source_msg.dice:
                d_text = f"🎲 **Telegram Dice / Game:** `{source_msg.dice.emoji}` ➔ Value: **{source_msg.dice.value}**"
                return {
                    "is_text_only": True,
                    "text": d_text,
                    "file_path": None,
                    "caption": "",
                    "media_type": "text",
                    "source_msg": source_msg,
                }
            elif getattr(source_msg, "service", None):
                s_action = str(source_msg.service.value) if hasattr(source_msg.service, "value") else str(source_msg.service)
                await _safe_edit_status(
                    status_message,
                    f"ℹ️ **Message #{message_id} is a Telegram System Event** (`{s_action}`)\n\n"
                    "This post is a service announcement (such as a pinned message notification, member action, or topic header), not a downloadable media or text file.\n\n"
                    "👉 **Please send the link of the actual content post in the channel.**"
                )
                active_jobs.setdefault(job_id, {})["final_status_set"] = True
                active_jobs.pop(job_id, None)
                return None
            else:
                await _safe_edit_status(
                    status_message,
                    f"⚠️ **Message #{message_id} is Empty or Deleted**\n\n"
                    "This message in the channel contains no text, video, or file (it may have been deleted or is an empty spacer).\n\n"
                    "👉 **Please send the next link in the channel, e.g. Message #17.**"
                )
                active_jobs.setdefault(job_id, {})["final_status_set"] = True
                active_jobs.pop(job_id, None)
                return None

        # Case 2: Media restricted message
        os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

        caption = extract_formatted_text(source_msg)
        media_type = source_msg.media.value if source_msg.media else "document"

        # Determine explicit, robust target file path, extension, and original file name
        ext = ""
        original_file_name = None
        media_duration = 0
        media_width = 0
        media_height = 0

        if source_msg.video:
            ext = ".mp4"
            media_type = "video"
            original_file_name = getattr(source_msg.video, "file_name", None)
            media_duration = getattr(source_msg.video, "duration", 0) or 0
            media_width = getattr(source_msg.video, "width", 0) or 0
            media_height = getattr(source_msg.video, "height", 0) or 0
            if not original_file_name:
                original_file_name = f"video_{message_id}.mp4"
        elif source_msg.photo:
            ext = ".jpg"
            media_type = "photo"
            original_file_name = f"photo_{message_id}.jpg"
        elif source_msg.audio:
            ext = ".mp3"
            media_type = "audio"
            original_file_name = getattr(source_msg.audio, "file_name", None) or f"audio_{message_id}.mp3"
            media_duration = getattr(source_msg.audio, "duration", 0) or 0
        elif source_msg.voice:
            ext = ".ogg"
            media_type = "voice"
            original_file_name = f"voice_{message_id}.ogg"
        elif source_msg.video_note:
            ext = ".mp4"
            media_type = "video_note"
            original_file_name = f"video_note_{message_id}.mp4"
            media_duration = getattr(source_msg.video_note, "duration", 0) or 0
        elif source_msg.animation:
            ext = ".mp4"
            media_type = "animation"
            original_file_name = getattr(source_msg.animation, "file_name", None) or f"animation_{message_id}.mp4"
            media_duration = getattr(source_msg.animation, "duration", 0) or 0
            media_width = getattr(source_msg.animation, "width", 0) or 0
            media_height = getattr(source_msg.animation, "height", 0) or 0
        elif source_msg.sticker:
            ext = ".webp"
            if getattr(source_msg.sticker, "is_animated", False):
                ext = ".tgs"
            elif getattr(source_msg.sticker, "is_video", False):
                ext = ".webm"
            media_type = "sticker"
            original_file_name = f"sticker_{message_id}{ext}"
        elif source_msg.document:
            doc_name = getattr(source_msg.document, "file_name", "") or ""
            doc_ext = os.path.splitext(doc_name)[1].lower() if doc_name else ""
            mime = (getattr(source_msg.document, "mime_type", "") or "").lower()

            if doc_name:
                original_file_name = doc_name

            if doc_ext in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts", ".m4v", ".3gp"):
                ext = doc_ext
                media_type = "video"
            elif mime.startswith("video/"):
                ext = ".mp4"
                media_type = "video"
            elif doc_ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
                ext = doc_ext
                media_type = "photo"
            elif mime.startswith("image/"):
                ext = ".jpg" if "jpeg" in mime else (".png" if "png" in mime else ".webp")
                media_type = "photo"
            elif doc_ext in (".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg", ".opus"):
                ext = doc_ext
                media_type = "audio"
            elif mime.startswith("audio/"):
                ext = ".mp3"
                media_type = "audio"
            elif doc_ext in (".pdf", ".zip", ".rar", ".7z", ".txt", ".docx", ".xlsx", ".apk"):
                ext = doc_ext
                media_type = "document"
            elif "pdf" in mime:
                ext = ".pdf"
                media_type = "document"
            elif doc_ext:
                ext = doc_ext
                media_type = "document"
            else:
                ext = ".bin"
                media_type = "document"

            if not original_file_name:
                original_file_name = f"document_{message_id}{ext}"
        elif getattr(source_msg, "web_page", None):
            wp = source_msg.web_page
            if getattr(wp, "video", None):
                ext = ".mp4"
                media_type = "video"
                original_file_name = f"webpage_video_{message_id}.mp4"
            elif getattr(wp, "document", None):
                doc_name = getattr(wp.document, "file_name", "") or f"webpage_doc_{message_id}.bin"
                ext = os.path.splitext(doc_name)[1].lower() or ".bin"
                media_type = "document"
                original_file_name = doc_name
            elif getattr(wp, "photo", None):
                ext = ".jpg"
                media_type = "photo"
                original_file_name = f"webpage_photo_{message_id}.jpg"
            else:
                ext = ".bin"
                media_type = "document"
                original_file_name = f"media_{message_id}.bin"
        else:
            ext = ".bin"
            media_type = "document"
            original_file_name = f"file_{message_id}.bin"

        # Clean original_file_name for safe local filesystem storage
        safe_name = "".join(c for c in (original_file_name or f"file_{message_id}{ext}") if c.isalnum() or c in (" ", ".", "_", "-")).strip()
        if not safe_name:
            safe_name = f"media_{message_id}{ext}"
        if not os.path.splitext(safe_name)[1]:
            safe_name += ext

        target_file_path = os.path.join(TEMP_DOWNLOAD_DIR, f"{job_id}_{safe_name}")

        media_target = (
            getattr(source_msg, "video", None)
            or getattr(source_msg, "document", None)
            or getattr(source_msg, "audio", None)
            or getattr(source_msg, "voice", None)
            or getattr(source_msg, "video_note", None)
            or getattr(source_msg, "photo", None)
            or getattr(source_msg, "animation", None)
            or getattr(source_msg, "sticker", None)
            or getattr(source_msg, "web_page", None)
            or getattr(source_msg, "media", None)
        )
        media_file_size = getattr(media_target, "file_size", 0) if media_target else 0

        pyrogram_progress = _progress_callback

        # Fast Source Thumbnail: Grab existing ~15KB Telegram thumbnail in 30ms to avoid slow FFmpeg extraction later
        source_thumb_file = None
        s_thumb_target = (
            getattr(source_msg, "video", None)
            or getattr(source_msg, "document", None)
            or getattr(source_msg, "animation", None)
        )
        if s_thumb_target and getattr(s_thumb_target, "thumbs", None):
            try:
                first_th = s_thumb_target.thumbs[0]
                th_dest = os.path.join(TEMP_DOWNLOAD_DIR, f"{job_id}_src_thumb.jpg")
                dl_th = await current_client.download_media(first_th.file_id, file_name=th_dest)
                if dl_th and os.path.exists(str(dl_th)) and os.path.getsize(str(dl_th)) > 50:
                    source_thumb_file = str(dl_th)
            except Exception:
                pass

        downloaded_file = None
        for dl_attempt in range(1, 4):
            try:
                # Anti-ban: enforce human-pacing + daily cap before every download
                await limiter.on_download_start()

                # Clean leftover partial temp file from aborted attempts
                _safe_remove(target_file_path + ".temp", target_file_path)

                # Engine 1: Turbo Parallel Multi-Stream for media files (>= 512KB)
                if dl_attempt == 1 and media_file_size >= 512 * 1024 and getattr(media_target, "file_id", None):
                    try:
                        from core.parallel_downloader import turbo_parallel_download
                        logger.info("[DownloadEngine] Attempting Turbo Parallel download for %d MB file...", media_file_size // (1024 * 1024))
                        turbo_timeout = max(600.0, (media_file_size / (1024 * 1024)) * 1.5 + 300.0)
                        downloaded_file = await asyncio.wait_for(
                            turbo_parallel_download(
                                client=current_client,
                                msg=source_msg,
                                out_path=target_file_path,
                                progress_callback=pyrogram_progress,
                                job_id=job_id,
                                active_jobs=active_jobs,
                            ),
                            timeout=turbo_timeout,
                        )
                        if downloaded_file and os.path.exists(str(downloaded_file)) and os.path.getsize(str(downloaded_file)) > 0:
                            limiter.on_success()
                            _record_account_download(current_client)
                            break
                    except Exception as turbo_err:
                        logger.warning("[DownloadEngine] Turbo parallel attempt skipped (%s), routing to Anti-Stall Pyrogram Stream...", turbo_err)
                        _safe_remove(target_file_path)

                # Engine 2: Pyrogram Stream with Active Anti-Stall Heartbeat Watchdog
                last_progress_time = [time.time()]
                last_rx_bytes = [0]
                dl_done_event = asyncio.Event()

                async def _stall_safe_progress(current: int, total: int):
                    if active_jobs and job_id and active_jobs.get(job_id, {}).get("cancelled"):
                        raise pyrogram.StopTransmission
                    last_progress_time[0] = time.time()
                    last_rx_bytes[0] = current
                    await pyrogram_progress(current, total)

                dl_task = asyncio.create_task(
                    current_client.download_media(
                        message=source_msg,
                        file_name=target_file_path,
                        progress=_stall_safe_progress,
                    )
                )

                async def _anti_stall_watchdog():
                    """Actively detects socket stalls and breaks out of hanging transmission within 45s."""
                    while not dl_done_event.is_set():
                        await asyncio.sleep(2.0)
                        if dl_done_event.is_set():
                            break
                        if active_jobs and job_id and active_jobs.get(job_id, {}).get("cancelled"):
                            logger.info("[Anti-Stall Guardian] Job %s was cancelled by user. Terminating download task.", job_id)
                            dl_task.cancel()
                            break
                        elapsed = time.time() - last_progress_time[0]
                        if elapsed >= 45.0:
                            logger.warning(
                                "[Anti-Stall Guardian] Zero bytes received for %.1fs (stuck at %d/%d). Terminating frozen socket task...",
                                elapsed,
                                last_rx_bytes[0],
                                media_file_size,
                            )
                            dl_task.cancel()
                            break

                watchdog_task = asyncio.create_task(_anti_stall_watchdog())
                try:
                    downloaded_file = await asyncio.wait_for(dl_task, timeout=900.0)
                except asyncio.CancelledError:
                    if active_jobs and job_id and active_jobs.get(job_id, {}).get("cancelled"):
                        raise
                    logger.warning("[Anti-Stall Guardian] Download stalled on TCP socket. Reconnecting...")
                    _safe_remove(target_file_path)
                    is_private_peer = False
                    if source_msg and getattr(source_msg, "chat", None):
                        is_private_peer = not bool(getattr(source_msg.chat, "username", None))
                    elif isinstance(chat_id, (int, str)) and str(chat_id).startswith("-100"):
                        is_private_peer = True

                    if not is_private_peer:
                        alt_client = get_next_available_pool_client(exclude_client=current_client)
                        if alt_client:
                            current_client = alt_client
                            session_key = _session_key_from_client(current_client)
                            limiter = rate_registry.get_sync(session_key)
                            active_jobs[job_id]["current_client"] = current_client
                    else:
                        logger.info("[Anti-Stall Guardian] Private peer detected — preserving authorized session.")
                    await asyncio.sleep(1.5)
                    continue
                finally:
                    dl_done_event.set()
                    watchdog_task.cancel()

                if downloaded_file and os.path.exists(str(downloaded_file)) and os.path.getsize(str(downloaded_file)) > 0:
                    limiter.on_success()
                    _record_account_download(current_client)
                    break

            except FloodWait as e:
                wait_sec = e.value + 1
                limiter.on_flood_wait(int(wait_sec))
                cname = getattr(current_client, "name", "")
                if "account_" in cname:
                    try:
                        aid = int(cname.split("_")[1])
                        mark_account_flood_wait(aid, int(wait_sec))
                    except Exception:
                        pass

                is_private_peer = False
                if source_msg and getattr(source_msg, "chat", None):
                    is_private_peer = not bool(getattr(source_msg.chat, "username", None))
                elif isinstance(chat_id, (int, str)) and str(chat_id).startswith("-100"):
                    is_private_peer = True

                alt_client = get_next_available_pool_client(exclude_client=current_client) if not is_private_peer else None
                if alt_client:
                    logger.info("[Download] FloodWait %ds encountered — hot-swapping to %s", wait_sec, alt_client.name)
                    current_client = alt_client
                    session_key = _session_key_from_client(current_client)
                    limiter = rate_registry.get_sync(session_key)
                    active_jobs[job_id]["current_client"] = current_client
                    await _safe_edit_status(status_message, "🔄 Switching to backup session to bypass rate-limit...")
                    await asyncio.sleep(0.1)
                    continue

                await _safe_edit_status(
                    status_message,
                    f"⏳ Telegram rate limit — waiting {wait_sec:.0f}s before resuming download..."
                )
                sleep_step = 1.0
                elapsed = 0.0
                while elapsed < wait_sec:
                    if active_jobs.get(job_id, {}).get("cancelled"):
                        break
                    alt_c = get_next_available_pool_client(exclude_client=current_client)
                    if alt_c:
                        current_client = alt_c
                        session_key = _session_key_from_client(current_client)
                        limiter = rate_registry.get_sync(session_key)
                        active_jobs[job_id]["current_client"] = current_client
                        break
                    await asyncio.sleep(min(sleep_step, wait_sec - elapsed))
                    elapsed += sleep_step

            except PeerFlood:
                limiter.on_peer_flood()
                alt_client = get_next_available_pool_client(exclude_client=current_client)
                if alt_client:
                    logger.info("[Download] PeerFlood encountered — hot-swapping to %s", alt_client.name)
                    current_client = alt_client
                    session_key = _session_key_from_client(current_client)
                    limiter = rate_registry.get_sync(session_key)
                    active_jobs[job_id]["current_client"] = current_client
                    await _safe_edit_status(status_message, "🔄 Switching to backup session...")
                    await asyncio.sleep(0.1)
                    continue

                await _safe_edit_status(
                    status_message,
                    "⚠️ Session rate-limited by Telegram. Safety cool-down active — try again shortly."
                )
                active_jobs.pop(job_id, None)
                return None

            except (UserDeactivated, UserDeactivatedBan, AuthKeyUnregistered, SessionExpired, SessionRevoked) as e:
                logger.critical("[Download] Session revoked during media transfer: %s (%s)", session_key, e)
                if session_key.startswith("user_"):
                    try:
                        uid = int(session_key.split("_")[1])
                        asyncio.create_task(handle_dead_session(uid, reason=str(e)))
                    except Exception:
                        pass
                await _safe_edit_status(
                    status_message,
                    "⚠️ **Session Expired / Terminated**\n\n"
                    "Your Telegram session was disconnected or expired.\n"
                    "👉 Please use `/login` to scan QR code and reconnect."
                )
                active_jobs.pop(job_id, None)
                return None

            except AuthKeyDuplicated as e:
                logger.warning("[Download] AuthKeyDuplicated during transfer: %s (session preserved)", e)
                await asyncio.sleep(2)
                continue

            except Exception as e:
                if active_jobs.get(job_id, {}).get("cancelled"):
                    break
                logger.error("[Download] Download attempt %d failed on client %s: %s", dl_attempt, getattr(current_client, "name", "client"), e)

                # Auto clean partial files
                _safe_remove(target_file_path, target_file_path + ".temp")

                # Auto hot-swap to another healthy pool account
                alt_client = get_next_available_pool_client(exclude_client=current_client)
                if alt_client:
                    logger.info("[Download] Error encountered — hot-swapping to backup client %s", alt_client.name)
                    current_client = alt_client
                    session_key = _session_key_from_client(current_client)
                    limiter = rate_registry.get_sync(session_key)
                    active_jobs[job_id]["current_client"] = current_client
                    await _safe_edit_status(status_message, "🔄 Stream stalled or reset — switching to backup worker to continue...")
                    await asyncio.sleep(0.1)
                    continue

                if dl_attempt < 3:
                    await asyncio.sleep(0.5 * dl_attempt)

        # Engine 3: Ultimate Failover via Telethon Layer 229 Engine if Pyrogram struggled
        if (not downloaded_file or not os.path.exists(str(downloaded_file)) or os.path.getsize(str(downloaded_file)) == 0) and not active_jobs.get(job_id, {}).get("cancelled"):
            _pyro_sess_str = await _get_pyrogram_session_str(current_client, user_id)

            if _pyro_sess_str:
                logger.info("[DownloadEngine] Activating Telethon Layer 229 Fallback after Pyrogram socket timeout...")
                await _safe_edit_status(status_message, "⚡ **Activating High-Layer Stream (Layer 229)** to bypass network stall...")
                _tele_res = await _telethon_fallback_download(
                    pyro_session_str=_pyro_sess_str,
                    chat_id=chat_id,
                    message_id=message_id,
                    out_path=target_file_path,
                    status_message=status_message,
                    job_id=job_id,
                    active_jobs=active_jobs,
                    progress_callback=pyrogram_progress,
                    user_id=user_id,
                )
                if _tele_res and _tele_res.get("file_path") and os.path.exists(_tele_res["file_path"]):
                    downloaded_file = _tele_res["file_path"]

        if active_jobs.get(job_id, {}).get("cancelled"):
            if downloaded_file and os.path.exists(str(downloaded_file)):
                _safe_remove(str(downloaded_file))
            await _safe_edit_status(status_message, "❌ Download cancelled.")
            active_jobs.setdefault(job_id, {})["final_status_set"] = True
            active_jobs.pop(job_id, None)
            return None

        if not downloaded_file or not os.path.exists(str(downloaded_file)) or os.path.getsize(str(downloaded_file)) == 0:
            await _safe_edit_status(status_message, "❌ Download failed — empty or corrupted file received.")
            active_jobs.setdefault(job_id, {})["final_status_set"] = True
            active_jobs.pop(job_id, None)
            return None

        return {
            "is_text_only": False,
            "file_path": str(downloaded_file),
            "original_file_name": original_file_name,
            "caption": caption,
            "media_type": media_type,
            "source_msg": source_msg,
            "duration": media_duration,
            "width": media_width,
            "height": media_height,
            "thumb_path": source_thumb_file,
        }

    except Exception as e:
        if active_jobs.get(job_id, {}).get("cancelled"):
            await _safe_edit_status(status_message, "❌ Task was cancelled.")
            active_jobs.setdefault(job_id, {})["final_status_set"] = True
            active_jobs.pop(job_id, None)
            return None
        logger.error("[Download] Unhandled exception in job %s: %s", job_id, e)
        await _safe_edit_status(status_message, f"❌ Download failed: {str(e)}")
        active_jobs.setdefault(job_id, {})["final_status_set"] = True
        active_jobs.pop(job_id, None)
        return None
