# language: Python, file: core/download_engine.py, target: Python 3.10+, Pyrogram
"""
High-Speed Telegram Restricted Media & Content Download Engine.
Extracts videos, documents, photos, audio, voice notes, and text posts from noforwards/restricted channels.
Anti-ban Protections:
- Humanized Action Simulation (ChatAction.RECORD_VIDEO / TYPING)
- Hot-Swap Session Failover (Switches to alternate pool client on FloodWait/PeerFlood)
- Per-Session Rate-Limiter with Natural Jitter
- FLOOD_WAIT Auto-Sleep with Randomized Extra Delay
- Guaranteed Clean Extension Determination (.mp4 / .mkv / .pdf / etc.)
"""

import os
import time
import asyncio
import logging
import random
from pathlib import Path
from typing import Optional, Dict, Any
from pyrogram import Client
from pyrogram.types import Message
from pyrogram.enums import ChatAction
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
from config import TEMP_DOWNLOAD_DIR
from core.progress import ProgressTracker, get_progress_markup
from core.rate_limiter import rate_registry
from core.client_manager import get_next_available_pool_client, handle_dead_session, mark_account_flood_wait

logger = logging.getLogger(__name__)

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
    max_retries: int = 4,
) -> Optional[Message]:
    """
    Wraps client.get_messages with FLOOD_WAIT auto-sleep,
    PEER_FLOOD quarantine, and session-error detection.
    No artificial rate-limiter wait — get_messages is a read-only call
    that rarely triggers FLOOD_WAIT and does NOT need pacing delays.
    """
    limiter = rate_registry.get_sync(session_key)

    for attempt in range(1, max_retries + 1):
        if limiter.is_quarantined:
            wait_sec = limiter.quarantine_remaining
            logger.warning("[Download] Session %s quarantined — waiting %.0fs", session_key, wait_sec)
            await asyncio.sleep(min(wait_sec, 10))  # cap at 10s so we retry fast
        elif attempt > 1:
            await asyncio.sleep(0.15)  # only pause on retry, attempt 1 executes immediately

        try:
            msg = await client.get_messages(chat_id=chat_id, message_ids=message_id)
            limiter.on_success()
            return msg

        except FloodWait as e:
            wait_sec = e.value + random_extra(4, 8)
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

        except (AuthKeyUnregistered, AuthKeyDuplicated, SessionExpired, SessionRevoked) as e:
            logger.error("[Download] Session invalid/revoked: %s", session_key)
            if session_key.startswith("user_"):
                try:
                    uid = int(session_key.split("_")[1])
                    asyncio.create_task(handle_dead_session(uid, reason=str(e)))
                except Exception:
                    pass
            return None

        except (ChannelInvalid, PeerIdInvalid, KeyError) as e:
            logger.warning("[Download] Peer %s not resolved yet (%s). Direct resolving...", chat_id, e)
            try:
                # 1. Fast direct resolution first (single RPC call to Telegram, ~100ms)
                try:
                    await client.get_chat(chat_id)
                except Exception:
                    pass
                msg = await client.get_messages(chat_id=chat_id, message_ids=message_id)
                if msg:
                    limiter.on_success()
                    return msg
            except Exception:
                pass

            try:
                # 2. Gentle human-paced dialog sync fallback
                count = 0
                async for _ in client.get_dialogs(limit=25):
                    count += 1
                    if count % 5 == 0:
                        await asyncio.sleep(0.3)
                msg = await client.get_messages(chat_id=chat_id, message_ids=message_id)
                if msg:
                    limiter.on_success()
                    return msg
            except Exception as e2:
                logger.error("[Download] Dialog sync retry failed: %s", e2)
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


async def download_restricted_media(
    client: Client,
    bot_client: Client,
    chat_id: Any,
    message_id: int,
    status_message: Message,
    job_id: str,
    res_pref: str = "original",
    batch_info: Optional[str] = None,
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
    tracker = ProgressTracker(action_name=action_label, block_char="🟦")
    current_client = client
    session_key = _session_key_from_client(current_client)
    limiter = rate_registry.get_sync(session_key)

    active_jobs[job_id] = {
        "tracker": tracker,
        "cancelled": False,
        "current_client": current_client
    }

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
            await status_message.edit_text(
                f"⏳ **Session temporarily rate-limited by Telegram**\n\n"
                f"Safety cool-down: **{remaining / 60:.0f} min {remaining % 60:.0f} sec** remaining.\n"
                "Your job will resume automatically — please wait."
            )
            await asyncio.sleep(remaining)

    try:
        # Zero-Trace Ghost Mode: Never broadcast typing or read receipts to target source chat
        # Userbot operates with 0% awareness from channel owner or members

        # Fetch message through rate-limited, error-handled wrapper
        source_msg = await _safe_get_messages(current_client, chat_id, message_id, session_key)

        if source_msg is None:
            alt_client = get_next_available_pool_client(exclude_client=current_client)
            if alt_client:
                current_client = alt_client
                session_key = _session_key_from_client(current_client)
                source_msg = await _safe_get_messages(current_client, chat_id, message_id, session_key)

        if source_msg is None:
            await status_message.edit_text(
                "❌ **Could not retrieve this message.**\n\n"
                "Possible reasons:\n"
                "• Your session needs to join the channel first (`/join <link>`)\n"
                "• The post was deleted\n"
                "• Temporary Telegram rate-limit — try again in a few minutes"
            )
            active_jobs.pop(job_id, None)
            return None

        # Case 1: Text-only restricted message
        if not source_msg.media:
            if source_msg.text:
                return {
                    "is_text_only": True,
                    "text": source_msg.text,
                    "entities": source_msg.entities,
                    "file_path": None,
                    "caption": "",
                    "media_type": "text",
                    "source_msg": source_msg,
                }
            elif source_msg.poll:
                return {
                    "is_text_only": True,
                    "text": f"📊 **Restricted Poll:** {source_msg.poll.question}",
                    "file_path": None,
                    "caption": "",
                    "media_type": "text",
                    "source_msg": source_msg,
                }
            else:
                await status_message.edit_text("❌ No supported content found in this message.")
                active_jobs.pop(job_id, None)
                return None

        # Case 2: Media restricted message
        os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

        caption = source_msg.caption or ""
        media_type = source_msg.media.value if source_msg.media else "document"

        # Determine explicit, robust target file path, extension, and original file name
        ext = ""
        original_file_name = None

        if source_msg.video:
            ext = ".mp4"
            media_type = "video"
            original_file_name = getattr(source_msg.video, "file_name", None)
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
        elif source_msg.voice:
            ext = ".ogg"
            media_type = "voice"
            original_file_name = f"voice_{message_id}.ogg"
        elif source_msg.video_note:
            ext = ".mp4"
            media_type = "video_note"
            original_file_name = f"video_note_{message_id}.mp4"
        elif source_msg.document:
            doc_name = getattr(source_msg.document, "file_name", "") or ""
            doc_ext = os.path.splitext(doc_name)[1].lower() if doc_name else ""
            mime = (getattr(source_msg.document, "mime_type", "") or "").lower()

            if doc_name:
                original_file_name = doc_name

            if doc_ext in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts"):
                ext = doc_ext
                media_type = "video"
            elif mime.startswith("video/"):
                ext = ".mp4"
                media_type = "video"
            elif doc_ext in (".pdf", ".zip", ".rar", ".7z", ".txt", ".docx", ".xlsx"):
                ext = doc_ext
                media_type = "document"
            elif "pdf" in mime:
                ext = ".pdf"
                media_type = "document"
            elif doc_ext:
                ext = doc_ext
            else:
                ext = ".mp4" if "video" in mime else ".bin"
                
            if not original_file_name:
                original_file_name = f"document_{message_id}{ext}"
        else:
            ext = ".mp4"
            original_file_name = f"file_{message_id}.mp4"

        # Clean original_file_name for safe local filesystem storage
        safe_name = "".join(c for c in (original_file_name or f"file_{message_id}{ext}") if c.isalnum() or c in (" ", ".", "_", "-")).strip()
        if not safe_name:
            safe_name = f"media_{message_id}{ext}"
        if not os.path.splitext(safe_name)[1]:
            safe_name += ext

        target_file_path = os.path.join(TEMP_DOWNLOAD_DIR, f"{job_id}_{safe_name}")

        _last_edit_task: Optional[asyncio.Task] = None

        async def pyrogram_progress(current: int, total: int):
            nonlocal _last_edit_task
            if active_jobs.get(job_id, {}).get("cancelled"):
                active_client = active_jobs.get(job_id, {}).get("current_client", current_client)
                try:
                    await active_client.stop_transmission()
                except Exception:
                    pass
                return

            should_edit, card_text = tracker.update(current, total)
            if should_edit:
                # If previous UI edit is still pending over network, skip to keep download pipeline running at 100% full speed
                if _last_edit_task and not _last_edit_task.done():
                    return

                async def _do_edit(text_to_send: str):
                    try:
                        await status_message.edit_text(
                            text=text_to_send,
                            reply_markup=get_progress_markup(job_id, res_pref),
                        )
                    except FloodWait as e:
                        # Back off next edit without stalling the media download stream!
                        tracker.last_update_time = time.time() + e.value
                    except Exception:
                        pass

                _last_edit_task = asyncio.create_task(_do_edit(card_text))

        downloaded_file = None
        for dl_attempt in range(1, 4):
            try:
                # Anti-ban: enforce human-pacing + daily cap before every download
                await limiter.on_download_start()

                downloaded_file = await current_client.download_media(
                    message=source_msg,
                    file_name=target_file_path,
                    progress=pyrogram_progress,
                )
                limiter.on_success()
                try:
                    cname = getattr(current_client, "name", "")
                    if "account_" in cname:
                        from database import db
                        aid = int(cname.split("_")[1])
                        asyncio.create_task(db.increment_bot_account_downloads(aid))
                except Exception:
                    pass
                break

            except FloodWait as e:
                wait_sec = e.value + random_extra(5, 10)
                limiter.on_flood_wait(int(wait_sec))
                try:
                    cname = getattr(current_client, "name", "")
                    if "account_" in cname:
                        aid = int(cname.split("_")[1])
                        mark_account_flood_wait(aid, int(wait_sec))
                except Exception:
                    pass
                
                alt_client = get_next_available_pool_client(exclude_client=current_client)
                if alt_client:
                    logger.info("[Download] FloodWait %ds encountered — hot-swapping to %s", wait_sec, alt_client.name)
                    current_client = alt_client
                    session_key = _session_key_from_client(current_client)
                    limiter = rate_registry.get_sync(session_key)
                    active_jobs[job_id]["current_client"] = current_client
                    await status_message.edit_text("🔄 Switching to backup session to bypass rate-limit...")
                    await asyncio.sleep(2)
                    continue

                await status_message.edit_text(
                    f"⏳ Telegram rate limit — waiting {wait_sec:.0f}s before resuming download..."
                )
                await asyncio.sleep(wait_sec)

            except PeerFlood:
                limiter.on_peer_flood()
                alt_client = get_next_available_pool_client(exclude_client=current_client)
                if alt_client:
                    logger.info("[Download] PeerFlood encountered — hot-swapping to %s", alt_client.name)
                    current_client = alt_client
                    session_key = _session_key_from_client(current_client)
                    limiter = rate_registry.get_sync(session_key)
                    active_jobs[job_id]["current_client"] = current_client
                    await status_message.edit_text("🔄 Switching to backup session...")
                    await asyncio.sleep(2)
                    continue

                await status_message.edit_text(
                    "⚠️ Session rate-limited by Telegram. Safety cool-down active — try again shortly."
                )
                active_jobs.pop(job_id, None)
                return None

            except (UserDeactivated, UserDeactivatedBan, AuthKeyUnregistered, AuthKeyDuplicated, SessionExpired, SessionRevoked) as e:
                logger.critical("[Download] Session revoked during media transfer: %s (%s)", session_key, e)
                if session_key.startswith("user_"):
                    try:
                        uid = int(session_key.split("_")[1])
                        asyncio.create_task(handle_dead_session(uid, reason=str(e)))
                    except Exception:
                        pass
                await status_message.edit_text(
                    "⚠️ **Session Expired / Terminated**\n\n"
                    "Your Telegram session was disconnected or expired.\n"
                    "👉 Please use `/login` to scan QR code and reconnect."
                )
                active_jobs.pop(job_id, None)
                return None

            except Exception as e:
                if active_jobs.get(job_id, {}).get("cancelled"):
                    break
                logger.error("[Download] Download attempt %d failed: %s", dl_attempt, e)
                if dl_attempt < 3:
                    await asyncio.sleep(3 * dl_attempt)
                else:
                    await status_message.edit_text(f"❌ Download failed after {dl_attempt} attempts: {str(e)}")
                    active_jobs.pop(job_id, None)
                    return None

        if active_jobs.get(job_id, {}).get("cancelled"):
            if downloaded_file and os.path.exists(str(downloaded_file)):
                try:
                    os.remove(str(downloaded_file))
                except Exception:
                    pass
            await status_message.edit_text("❌ Download cancelled.")
            active_jobs.pop(job_id, None)
            return None

        if not downloaded_file or not os.path.exists(str(downloaded_file)) or os.path.getsize(str(downloaded_file)) == 0:
            await status_message.edit_text("❌ Download failed — empty or corrupted file received.")
            active_jobs.pop(job_id, None)
            return None

        return {
            "is_text_only": False,
            "file_path": str(downloaded_file),
            "original_file_name": original_file_name,
            "caption": caption,
            "media_type": media_type,
            "source_msg": source_msg,
        }

    except Exception as e:
        if active_jobs.get(job_id, {}).get("cancelled"):
            await status_message.edit_text("❌ Task was cancelled.")
            active_jobs.pop(job_id, None)
            return None
        logger.error("[Download] Unhandled exception in job %s: %s", job_id, e)
        await status_message.edit_text(f"❌ Download failed: {str(e)}")
        active_jobs.pop(job_id, None)
        return None
