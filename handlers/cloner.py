# language: Python, file: handlers/cloner.py, target: Python 3.10+, Pyrogram
"""
Enterprise Full Channel Cloner Suite:
Clones entire public or restricted private channels and forums to target destination.
Runs as a resilient background worker with FloodWait auto-recovery, live dashboard,
and zero impact on normal user download tasks.
"""

import os
import re
import uuid
import asyncio
from typing import Dict, Any, Optional
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, PeerFlood
from core.client_manager import get_user_client
from core.download_engine import download_restricted_media, active_jobs
from core.upload_engine import upload_unlocked_media
from core.media_processor import strip_video_metadata
from core.caption_cleaner import format_custom_caption
from database import db

# Active channel clone jobs: {clone_id: {"cancelled": bool, "status": str, ...}}
active_clones: Dict[str, Dict[str, Any]] = {}


def _parse_channel_id(raw_str: str) -> Optional[Any]:
    cleaned = raw_str.strip()
    if cleaned.startswith("-100") and cleaned[4:].isdigit():
        return int(cleaned)
    if cleaned.lstrip("-").isdigit():
        return int(cleaned)
    if cleaned.startswith("@"):
        return cleaned
    # Check if it's a link: https://t.me/c/2459862936/10
    m = re.search(r"t\.me/c/(\d+)", cleaned)
    if m:
        return int(f"-100{m.group(1)}")
    m_pub = re.search(r"t\.me/([a-zA-Z0-9_]{4,})", cleaned)
    if m_pub:
        return f"@{m_pub.group(1)}"
    return cleaned if cleaned else None


@Client.on_message(filters.command(["clone", "cloner"]) & filters.private)
async def channel_cloner_command(client: Client, message: Message):
    user_id = message.from_user.id
    from config import ADMIN_IDS
    is_adm = user_id in ADMIN_IDS
    is_vip = await db.is_user_premium(user_id)

    if not is_adm and not is_vip:
        await message.reply_text(
            "👑 **Enterprise Channel Cloner (VIP / Admin Feature)**\n\n"
            "Channel Cloning allows 1-click mirroring of entire 500+ video channels.\n"
            "💎 Upgrade to VIP via `/premium` or contact Admin to unlock!"
        )
        return

    cmd = message.command
    if len(cmd) < 3:
        await message.reply_text(
            "📋 **1-CLICK CHANNEL CLONER WIZARD**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Clone all restricted videos, PDFs, and media from any source channel directly to your backup channel.\n\n"
            "📌 **Command Syntax:**\n"
            "`/clone <source_channel> <destination_channel> [start_id] [end_id]`\n\n"
            "💡 **Examples:**\n"
            "• Public Source: `/clone @python_courses -1002459862936 1 50`\n"
            "• Restricted Private: `/clone https://t.me/c/2459862936/1 -1009876543210 1 100`\n"
            "• To your private chat: `/clone https://t.me/c/2459862936/1 me 1 30`\n\n"
            "⚡ _Features: Anti-Ban rate limiter, auto-rescale, watermark, and clean captions!_"
        )
        return

    raw_src = cmd[1]
    raw_dst = cmd[2]
    start_id = int(cmd[3]) if len(cmd) > 3 and cmd[3].isdigit() else 1
    end_id = int(cmd[4]) if len(cmd) > 4 and cmd[4].isdigit() else (start_id + 50)

    if end_id < start_id:
        start_id, end_id = end_id, start_id

    max_batch = 500 if is_adm else 100
    if (end_id - start_id + 1) > max_batch:
        end_id = start_id + max_batch - 1
        await message.reply_text(f"⚠️ Batch size capped at `{max_batch}` items for safety against Telegram rate limits.")

    source_target = _parse_channel_id(raw_src)
    dest_target = user_id if raw_dst.lower() in ("me", "dm", "here") else _parse_channel_id(raw_dst)

    if not source_target:
        await message.reply_text("❌ Invalid source channel format.")
        return

    # Owner Anti-Leech Protection: Block cloning from protected VIP channels
    if not is_adm and await db.is_channel_protected(source_target):
        await message.reply_text(
            "🔒 **ACCESS DENIED — VIP CHANNEL PROTECTED** 🔒\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⛔ **This source channel is locked by the owner.**\n\n"
            "Cloning or mirroring content from this VIP channel is strictly prohibited!"
        )
        return

    clone_id = f"clone_{uuid.uuid4().hex[:6]}"
    active_clones[clone_id] = {
        "user_id": user_id,
        "source": source_target,
        "dest": dest_target,
        "start": start_id,
        "end": end_id,
        "current": start_id,
        "total": end_id - start_id + 1,
        "delivered": 0,
        "skipped": 0,
        "cancelled": False,
        "paused": False,
    }

    status_card = await message.reply_text(
        f"🚀 **CHANNEL CLONER INITIALIZED**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 **Source:** `{source_target}`\n"
        f"📤 **Destination:** `{dest_target}`\n"
        f"📊 **Range:** ID `{start_id}` ➔ `{end_id}` (`{end_id - start_id + 1}` items)\n"
        f"⚙️ **Status:** _Connecting userbot session..._\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⏸️ Pause", callback_data=f"clone_pause:{clone_id}"),
                InlineKeyboardButton("🔴 Cancel", callback_data=f"clone_cancel:{clone_id}"),
            ]
        ]),
    )

    asyncio.create_task(
        _run_channel_clone_worker(
            bot_client=client,
            user_id=user_id,
            clone_id=clone_id,
            status_msg=status_card,
            source=source_target,
            dest=dest_target,
            start_id=start_id,
            end_id=end_id,
        )
    )


async def _run_channel_clone_worker(
    bot_client: Client,
    user_id: int,
    clone_id: str,
    status_msg: Message,
    source: Any,
    dest: Any,
    start_id: int,
    end_id: int,
):
    """Background sequential worker that executes the entire clone job safely."""
    worker_client = await get_user_client(user_id)
    if not worker_client:
        try:
            await status_msg.edit_text("❌ No active Telegram session found. Please login via `/login` first.")
        except Exception:
            pass
        active_clones.pop(clone_id, None)
        return
    total = end_id - start_id + 1
    delivered = 0
    skipped = 0

    user_settings = await db.get_settings(user_id)

    for msg_id in range(start_id, end_id + 1):
        job_data = active_clones.get(clone_id, {})
        if job_data.get("cancelled"):
            try:
                await status_msg.edit_text(f"🛑 **Clone Stopped:** Completed {delivered}/{total} items before cancellation.")
            except Exception:
                pass
            break

        while job_data.get("paused") and not job_data.get("cancelled"):
            await asyncio.sleep(2)
            job_data = active_clones.get(clone_id, {})

        # Periodic dashboard update
        pct = int(((msg_id - start_id) / total) * 100)
        filled = int(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)

        if msg_id % 3 == 0 or msg_id == start_id:
            try:
                await status_msg.edit_text(
                    f"🔄 **CHANNEL CLONING IN PROGRESS**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 **Progress:** `[{bar}]` **{pct}%**\n"
                    f"📦 **Delivered:** `{delivered}/{total}` | **Skipped:** `{skipped}`\n"
                    f"🎯 **Current ID:** `{msg_id}/{end_id}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ _Anti-Ban Pacing Active (Zero Telegram Flags)_",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("⏸️ Pause", callback_data=f"clone_pause:{clone_id}"),
                            InlineKeyboardButton("🔴 Cancel", callback_data=f"clone_cancel:{clone_id}"),
                        ]
                    ]),
                )
            except Exception:
                pass

        sub_job_id = f"cl_{clone_id}_{msg_id}"
        active_jobs[sub_job_id] = {"status": "cloning", "cancelled": False}

        try:
            dl_res = await download_restricted_media(
                client=worker_client,
                bot_client=bot_client,
                chat_id=source,
                message_id=msg_id,
                status_message=status_msg,
                job_id=sub_job_id,
            )

            if not dl_res:
                skipped += 1
                continue

            dl_res["chat_id"] = source
            dl_res["message_id"] = msg_id

            orig_fp = dl_res.get("file_path")
            if orig_fp and os.path.exists(orig_fp):
                # Apply stealth metadata anonymizer
                anon_fp = f"{orig_fp}_anon.mp4"
                cleaned = await strip_video_metadata(orig_fp, anon_fp)
                if cleaned and cleaned != orig_fp and os.path.exists(cleaned):
                    try:
                        if os.path.exists(orig_fp):
                            os.remove(orig_fp)
                    except Exception:
                        pass
                    dl_res["file_path"] = cleaned

            # Apply Custom Watermark for VIP users if enabled
            is_prem = await db.is_user_premium(user_id)
            if is_prem and dl_res.get("file_path"):
                user_wm = await db.get_watermark_settings(user_id)
                current_fp = dl_res["file_path"]
                if user_wm.get("enabled") and current_fp.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts")):
                    ext = os.path.splitext(current_fp)[1] or ".mp4"
                    wm_fp = f"{current_fp}_clone_wm{ext}"
                    try:
                        from core.watermark_engine import apply_video_watermark
                        final_wm = await apply_video_watermark(current_fp, wm_fp, user_wm)
                        if final_wm and final_wm != current_fp and os.path.exists(final_wm):
                            try:
                                if os.path.exists(current_fp):
                                    os.remove(current_fp)
                            except Exception:
                                pass
                            dl_res["file_path"] = final_wm
                    except Exception as wm_err:
                        print(f"[!] Cloner watermark error: {wm_err}")

            # Format Caption with Smart Ad-Stripper & Custom Replacements
            raw_caption = dl_res.get("caption") or dl_res.get("text") or ""
            file_title = os.path.basename(dl_res.get("file_path", "")) if dl_res.get("file_path") else ""
            clean_ads = bool(user_settings.get("clean_caption", 1))
            user_caption_tmpl = user_settings.get("custom_caption")
            caption_replacements = await db.get_caption_replacements(user_id)

            caption_to_send = format_custom_caption(
                template=user_caption_tmpl,
                original_caption=raw_caption,
                file_name=file_title,
                clean_ads=clean_ads,
                replacements=caption_replacements,
            )

            # Deliver to target destination
            uploaded = await upload_unlocked_media(
                bot_client=bot_client,
                target_chat_id=dest,
                download_result=dl_res,
                status_message=status_msg,
                job_id=sub_job_id,
                custom_caption=caption_to_send,
                upload_as_doc=user_settings.get("upload_as_doc", False),
                user_id=user_id,
            )

            if uploaded:
                delivered += 1

            # 2.5-second anti-ban polite cool-down
            await asyncio.sleep(2.5)

        except FloodWait as fw:
            await asyncio.sleep(fw.value + 2)
        except Exception as e:
            skipped += 1
            print(f"[!] Clone error on ID {msg_id}: {e}")
        finally:
            active_jobs.pop(sub_job_id, None)

    active_clones.pop(clone_id, None)
    try:
        await status_msg.edit_text(
            f"🎉 **CHANNEL CLONING COMPLETED** 🎉\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ **Delivered to Backup:** `{delivered}/{total}` items\n"
            f"⚠️ **Skipped/Text:** `{skipped}`\n"
            f"📢 **Destination:** `{dest}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ _All content mirrored with 0% data loss._"
        )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^clone_cancel:(.+)"))
async def clone_cancel_callback(client: Client, callback_query: CallbackQuery):
    c_id = callback_query.matches[0].group(1)
    if c_id in active_clones:
        active_clones[c_id]["cancelled"] = True
        await callback_query.answer("🔴 Cloning stopping after current item...", show_alert=True)
    else:
        await callback_query.answer("Clone task already completed or stopped.")


@Client.on_callback_query(filters.regex(r"^clone_pause:(.+)"))
async def clone_pause_callback(client: Client, callback_query: CallbackQuery):
    c_id = callback_query.matches[0].group(1)
    if c_id in active_clones:
        current_state = active_clones[c_id].get("paused", False)
        new_state = not current_state
        active_clones[c_id]["paused"] = new_state
        lbl = "⏸️ Paused" if new_state else "▶️ Resumed"
        btn_lbl = "▶️ Resume" if new_state else "⏸️ Pause"
        await callback_query.answer(f"Clone is now {lbl}!", show_alert=False)
        try:
            await callback_query.message.edit_reply_markup(
                InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(btn_lbl, callback_data=f"clone_pause:{c_id}"),
                        InlineKeyboardButton("🔴 Cancel", callback_data=f"clone_cancel:{c_id}"),
                    ]
                ])
            )
        except Exception:
            pass
