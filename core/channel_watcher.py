# language: Python, file: core/channel_watcher.py, target: Python 3.10+, Pyrogram
"""
Enterprise Real-Time Channel Auto-Forwarder & Mirror Watcher Engine:
Monitors designated source channels (public or restricted private) 24/7.
Whenever a new post, video, document, photo, or album arrives in the source channel,
it is instantly mirrored to the destination channel in real time with ad-cleaning,
anti-ban rate limiting, and optional custom watermarking.
"""

import os
import time
import asyncio
import logging
from typing import Dict, Any, Optional, List, Union
from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError, ChatForwardsRestricted

from database import db
from core.client_manager import get_user_client, account_pool
from core.download_engine import download_restricted_media, active_jobs
from core.upload_engine import upload_unlocked_media
from core.media_processor import strip_video_metadata
from core.caption_cleaner import format_custom_caption

logger = logging.getLogger(__name__)

# Concurrency lock to prevent duplicate concurrent mirroring of the same message
_mirror_locks: Dict[str, asyncio.Lock] = {}


def _get_mirror_lock(key: str) -> asyncio.Lock:
    if key not in _mirror_locks:
        _mirror_locks[key] = asyncio.Lock()
    return _mirror_locks[key]


async def mirror_post_to_destination(
    bot_client: Client,
    monitor: Dict[str, Any],
    source_msg: Optional[Message] = None,
    source_msg_id: Optional[int] = None,
) -> bool:
    """
    Executes the mirroring of a single post from source channel to destination channel.
    Handles both direct Pyrogram Message objects and message IDs discovered during background sync.
    """
    monitor_id = monitor["id"]
    user_id = monitor["user_id"]
    source_chat_id = monitor["source_chat_id"]
    dest_chat_id = monitor["dest_chat_id"]
    clean_ads = bool(monitor.get("clean_ads", 1))
    custom_caption_tmpl = monitor.get("custom_caption", "")

    msg_id = source_msg.id if source_msg else source_msg_id
    if not msg_id:
        return False

    lock_key = f"m_{monitor_id}_{msg_id}"
    lock = _get_mirror_lock(lock_key)

    async with lock:
        # Step 1: Idempotency check — ensure never mirrored twice
        if await db.is_monitor_post_forwarded(monitor_id, msg_id):
            return True

        # Step 2: Anti-Leech VIP channel protection check
        from config import ADMIN_IDS
        is_admin = user_id in ADMIN_IDS
        if not is_admin and await db.is_channel_protected(source_chat_id):
            logger.warning("[Mirror Guard] Access denied: source %s is VIP protected.", source_chat_id)
            return False

        # Step 3: Fast-path attempt using native Telegram copy (0 disk usage, instant delivery)
        fast_copied = False
        try:
            copied_msg = await bot_client.copy_message(
                chat_id=dest_chat_id,
                from_chat_id=source_chat_id,
                message_id=msg_id,
            )
            if copied_msg:
                fast_copied = True
                await db.record_monitor_forward(
                    monitor_id=monitor_id,
                    source_msg_id=msg_id,
                    dest_msg_id=copied_msg.id,
                )
                logger.info("[Fast Mirror] Successfully copied msg %s to dest %s", msg_id, dest_chat_id)
                return True
        except (ChatForwardsRestricted, RPCError) as copy_err:
            # Protected / restricted content or bot not member — fallback to Worker Engine
            logger.debug("[Fast Mirror Bypass] Native copy skipped (%s), falling back to Worker...", copy_err)
        except Exception as general_err:
            logger.debug("[Fast Mirror Bypass] Exception (%s), falling back to Worker...", general_err)

        # Step 4: Worker Engine Path for Restricted / Protected Content
        worker_client = await get_user_client(user_id)
        if not worker_client and account_pool:
            # Borrow healthy worker from shared pool
            worker_client = next(iter(account_pool.values()), None)

        if not worker_client:
            logger.warning("[Worker Engine] No active worker client available for user %s", user_id)
            return False

        job_id = f"wm_{monitor_id}_{msg_id}_{int(time.time())}"
        active_jobs[job_id] = {"status": "mirroring", "cancelled": False}

        try:
            dl_res = await download_restricted_media(
                client=worker_client,
                bot_client=bot_client,
                chat_id=source_chat_id,
                message_id=msg_id,
                status_message=None,
                job_id=job_id,
                user_id=user_id,
            )

            if not dl_res:
                logger.debug("[Worker Engine] Nothing to mirror for msg %s", msg_id)
                return False

            dl_res["chat_id"] = source_chat_id
            dl_res["message_id"] = msg_id

            # Apply stealth metadata anonymizer if video file
            orig_fp = dl_res.get("file_path")
            if orig_fp and os.path.exists(orig_fp):
                anon_fp = f"{orig_fp}_anon.mp4"
                cleaned = await strip_video_metadata(orig_fp, anon_fp)
                if cleaned and cleaned != orig_fp and os.path.exists(cleaned):
                    try:
                        if os.path.exists(orig_fp):
                            os.remove(orig_fp)
                    except Exception:
                        pass
                    dl_res["file_path"] = cleaned

            # Apply watermark / branding if configured
            is_vip = await db.is_user_premium(user_id) or is_admin
            if is_vip and dl_res.get("file_path"):
                user_wm = await db.get_watermark_settings(user_id)
                current_fp = dl_res["file_path"]
                if current_fp.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts")):
                    if user_wm.get("delogo_enabled"):
                        try:
                            from core.watermark_engine import apply_video_delogo
                            ext = os.path.splitext(current_fp)[1] or ".mp4"
                            delogo_fp = f"{current_fp}_delogo{ext}"
                            final_delogo = await apply_video_delogo(current_fp, delogo_fp, user_wm)
                            if final_delogo and final_delogo != current_fp and os.path.exists(final_delogo):
                                try:
                                    if os.path.exists(current_fp):
                                        os.remove(current_fp)
                                except Exception:
                                    pass
                                current_fp = final_delogo
                                dl_res["file_path"] = final_delogo
                        except Exception as dl_err:
                            logger.debug("[Delogo Error] %s", dl_err)

                    if user_wm.get("enabled"):
                        try:
                            from core.watermark_engine import apply_video_watermark
                            ext = os.path.splitext(current_fp)[1] or ".mp4"
                            wm_fp = f"{current_fp}_wm{ext}"
                            final_wm = await apply_video_watermark(current_fp, wm_fp, user_wm)
                            if final_wm and final_wm != current_fp and os.path.exists(final_wm):
                                try:
                                    if os.path.exists(current_fp):
                                        os.remove(current_fp)
                                except Exception:
                                    pass
                                dl_res["file_path"] = final_wm
                        except Exception as wm_err:
                            logger.debug("[Watermark Error] %s", wm_err)

            # Format caption
            raw_caption = dl_res.get("caption") or dl_res.get("text") or ""
            file_title = os.path.basename(dl_res.get("file_path", "")) if dl_res.get("file_path") else ""
            caption_replacements = await db.get_caption_replacements(user_id)

            caption_to_send = format_custom_caption(
                template=custom_caption_tmpl if custom_caption_tmpl else None,
                original_caption=raw_caption,
                file_name=file_title,
                clean_ads=clean_ads,
                replacements=caption_replacements,
            )

            # Deliver unlocked content to destination channel
            uploaded = await upload_unlocked_media(
                bot_client=bot_client,
                target_chat_id=dest_chat_id,
                download_result=dl_res,
                status_message=None,
                job_id=job_id,
                custom_caption=caption_to_send,
                upload_as_doc=False,
                user_id=user_id,
            )

            if uploaded:
                await db.record_monitor_forward(
                    monitor_id=monitor_id,
                    source_msg_id=msg_id,
                    dest_msg_id=0,
                )
                logger.info("[Worker Mirror] Mirrored restricted msg %s -> dest %s", msg_id, dest_chat_id)
                return True

            return False

        except Exception as e:
            logger.warning("[Mirror Error] Msg %s from source %s: %s", msg_id, source_chat_id, e)
            return False
        finally:
            active_jobs.pop(job_id, None)
            # Immediate sweep of leftover file
            fp = dl_res.get("file_path") if "dl_res" in locals() and dl_res else None
            if fp and os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass


async def start_channel_mirror_daemon(bot_client: Client):
    """
    24/7 background sync watchdog:
    Iterates through all active channel monitors every 12 seconds.
    Ensures that any new message posted in any monitored channel is automatically
    mirrored, even if the bot missed a live update event or was restarting.
    """
    await asyncio.sleep(15)  # Initial grace delay after boot
    logger.info("[Channel Mirror Daemon] Started 24/7 live sync loop.")

    while True:
        try:
            monitors = await db.get_all_active_monitors()
            if not monitors:
                await asyncio.sleep(12)
                continue

            for mon in monitors:
                try:
                    source_id = mon["source_chat_id"]
                    mon_id = mon["id"]
                    user_id = mon["user_id"]
                    last_seen_id = mon.get("last_msg_id", 0)

                    # Obtain reading client (either user's personal client or pool worker or bot)
                    reader_client = await get_user_client(user_id)
                    if not reader_client and account_pool:
                        reader_client = next(iter(account_pool.values()), None)
                    if not reader_client:
                        reader_client = bot_client

                    # Fetch the latest 5 messages from source channel
                    recent_msgs: List[Message] = []
                    try:
                        async for m in reader_client.get_chat_history(source_id, limit=5):
                            recent_msgs.append(m)
                    except Exception as ch_err:
                        logger.debug("[Mirror Daemon] Cannot fetch history for %s: %s", source_id, ch_err)
                        continue

                    if not recent_msgs:
                        continue

                    # Sort oldest first so messages are mirrored in order
                    recent_msgs.sort(key=lambda x: x.id)

                    # Initialize last_seen_id on first scan if it was 0
                    if last_seen_id == 0:
                        highest_id = max(m.id for m in recent_msgs)
                        await db.update_monitor_last_msg(mon_id, highest_id)
                        continue

                    for msg in recent_msgs:
                        if msg.id > last_seen_id:
                            # New post detected!
                            await mirror_post_to_destination(
                                bot_client=bot_client,
                                monitor=mon,
                                source_msg=msg,
                                source_msg_id=msg.id,
                            )
                            await db.update_monitor_last_msg(mon_id, msg.id)
                            # Polite delay between multiple historical items
                            await asyncio.sleep(1.5)

                except FloodWait as fw:
                    await asyncio.sleep(fw.value + 2)
                except Exception as mon_err:
                    logger.debug("[Mirror Daemon] Mon %s error: %s", mon.get("id"), mon_err)

            await asyncio.sleep(12)

        except asyncio.CancelledError:
            break
        except Exception as loop_err:
            logger.warning("[Channel Mirror Daemon] Outer loop error: %s", loop_err)
            await asyncio.sleep(15)
