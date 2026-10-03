# language: Python, file: handlers/omni_downloader.py, target: Python 3.10+, Pyrogram, yt-dlp
"""
Universal Omni Web Video Harvester:
Extracts and delivers high-speed media from YouTube, Facebook, Instagram Reels,
TikTok, Twitter/X, Pinterest, Terabox, Reddit, and direct MP4/M3U8 streams.
Excludes Telegram URLs (handled by link_handler.py) to guarantee zero interference.
"""

import os
import re
import uuid
import asyncio
from typing import Optional, Dict, Any
from urllib.parse import urlparse
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from core.upload_engine import upload_unlocked_media
from core.media_processor import strip_video_metadata
from core.caption_cleaner import format_custom_caption
from core.download_engine import active_jobs
from core.progress import ProgressTracker, get_progress_markup
from database import db
from config import TEMP_DOWNLOAD_DIR

OMNI_DOMAINS_REGEX = re.compile(
    r"https?://(?:www\.)?(?:"
    r"youtube\.com|youtu\.be|"
    r"instagram\.com|"
    r"facebook\.com|fb\.watch|"
    r"tiktok\.com|"
    r"twitter\.com|x\.com|"
    r"pinterest\.com|pin\.it|"
    r"reddit\.com|"
    r"terabox\.com|1024tera\.com|teraboxapp\.com|"
    r"[^\s/$.?#].[^\s]*\.(?:mp4|mkv|mov|webm|m3u8)"
    r")(?:/[^\s]*)?",
    re.IGNORECASE,
)


def _safe_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c.isalnum() or c in (" ", ".", "_", "-")).strip()
    return cleaned[:80] or "video"


def _extract_and_download(url: str, output_template: str) -> Optional[Dict[str, Any]]:
    """Synchronous worker invoked in asyncio.to_thread."""
    from core.watermark_engine import get_ffmpeg_binary
    opts = {
        "ffmpeg_location": get_ffmpeg_binary(),
        "outtmpl": output_template,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 8,
        "buffersize": 1048576,
        "http_chunk_size": 10485760,
        "socket_timeout": 30,
        "retries": 3,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            return None
        # Locate downloaded file path
        expected = ydl.prepare_filename(info)
        base, _ = os.path.splitext(expected)
        candidates = [
            f"{base}.mp4",
            expected,
            f"{base}.webm",
            f"{base}.mkv",
        ]
        final_file = None
        for cand in candidates:
            if os.path.exists(cand) and os.path.getsize(cand) > 100:
                final_file = cand
                break

        if final_file and os.path.exists(final_file) and os.path.getsize(final_file) > 100:
            return {
                "file_path": final_file,
                "title": info.get("title") or "Web Video",
                "duration": int(info.get("duration") or 0),
                "uploader": info.get("uploader") or info.get("channel") or "",
                "description": info.get("description") or "",
                "thumbnail": info.get("thumbnail"),
            }
        return None


@Client.on_message(filters.private & filters.text & filters.regex(OMNI_DOMAINS_REGEX))
async def omni_url_listener(client: Client, message: Message):
    user_id = message.from_user.id
    raw_text = message.text.strip()

    # Never interfere with Telegram URLs (handled by link_handler.py)
    if "t.me/" in raw_text or "telegram.me/" in raw_text:
        return

    # 0. Check Banned Status
    if await db.is_user_banned(user_id):
        await message.reply_text("⛔ **Account Suspended**")
        return

    # 0.1 Check Maintenance Mode
    from config import ADMIN_IDS
    if await db.get_maintenance_mode() and user_id not in ADMIN_IDS:
        await message.reply_text(
            "🛠️ **System Maintenance Active.** Please try again shortly."
        )
        return

    # 0.2 Check daily download quota
    sim_mode = await db.get_simulated_mode(user_id) if user_id in ADMIN_IDS else "normal"
    enforce_quota = (user_id not in ADMIN_IDS) or (user_id in ADMIN_IDS and sim_mode == "free")
    if enforce_quota:
        allowed, quota_reason, rem = await db.check_and_increment_quota(user_id)
        if not allowed:
            await message.reply_text(
                f"🛑 {quota_reason}\n\n"
                "💎 Upgrade to **VIP** using `/premium` for unlimited ultra-fast downloads!"
            )
            return

    match = OMNI_DOMAINS_REGEX.search(raw_text)
    if not match:
        return

    target_url = match.group(0).strip()
    domain = urlparse(target_url).netloc.replace("www.", "")

    job_id = f"omni_{uuid.uuid4().hex[:8]}"
    active_jobs[job_id] = {
        "status": "extracting",
        "chat_id": user_id,
        "cancelled": False,
    }

    status_msg = await message.reply_text(
        f"🌐 **Omni Web Harvester** ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 **Platform:** `{domain}`\n"
        f"⚙️ **Status:** _Connecting to high-speed stream parser..._\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ _Please wait while video is processed..._",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Cancel Operation", callback_data=f"cancel:{job_id}")]
        ]),
    )

    try:
        out_tmpl = str(TEMP_DOWNLOAD_DIR / f"{job_id}_%(title).50s.%(ext)s")
        meta = await asyncio.to_thread(_extract_and_download, target_url, out_tmpl)

        if not meta or not os.path.exists(meta.get("file_path", "")):
            await status_msg.edit_text(
                f"❌ **Harvest Failed:** Could not extract stream from `{domain}`.\n"
                "The link might be private, geo-blocked, or expired."
            )
            return

        if active_jobs.get(job_id, {}).get("cancelled"):
            if os.path.exists(meta["file_path"]):
                try:
                    os.remove(meta["file_path"])
                except Exception:
                    pass
            await status_msg.edit_text("❌ Download was cancelled.")
            return

        dl_path = meta["file_path"]
        v_title = meta.get("title", "Web Video")
        v_uploader = meta.get("uploader", domain)

        # Apply stealth digital anonymizer (strip author tags / metadata)
        anon_path = f"{dl_path}_anon.mp4"
        cleaned_path = await strip_video_metadata(dl_path, anon_path)
        if cleaned_path and cleaned_path != dl_path and os.path.exists(cleaned_path):
            try:
                if os.path.exists(dl_path):
                    os.remove(dl_path)
            except Exception:
                pass
            dl_path = cleaned_path

        # Step: Apply VIP Custom Watermark if enabled
        is_prem = await db.is_user_premium(user_id)
        if is_prem and dl_path and os.path.exists(dl_path):
            user_wm = await db.get_watermark_settings(user_id)
            if user_wm.get("enabled"):
                try:
                    from core.watermark_engine import apply_video_watermark
                    ext = os.path.splitext(dl_path)[1] or ".mp4"
                    wm_out = f"{dl_path}_omni_wm{ext}"
                    final_wm = await apply_video_watermark(dl_path, wm_out, user_wm)
                    if final_wm and final_wm != dl_path and os.path.exists(final_wm):
                        try:
                            if os.path.exists(dl_path):
                                os.remove(dl_path)
                        except Exception:
                            pass
                        dl_path = final_wm
                except Exception as wm_err:
                    print(f"[!] Omni watermark error: {wm_err}")

        user_settings = await db.get_settings(user_id)
        auto_forward_id = user_settings.get("auto_forward_chat_id")

        caption_replacements = await db.get_caption_replacements(user_id)
        clean_cap = format_custom_caption(
            template=user_settings.get("custom_caption"),
            original_caption=f"🎬 **{v_title}**\n👤 **Source:** `{v_uploader}`",
            file_name=os.path.basename(dl_path),
            clean_ads=bool(user_settings.get("clean_caption", 1)),
            replacements=caption_replacements,
        )

        dl_result = {
            "file_path": dl_path,
            "original_file_name": f"{_safe_filename(v_title)}.mp4",
            "caption": clean_cap,
            "media_type": "video",
            "source_msg": None,
            "chat_id": f"web:{domain}",
            "message_id": 1,
        }

        # Deliver as pristine playable video
        uploaded = await upload_unlocked_media(
            bot_client=client,
            target_chat_id=user_id,
            download_result=dl_result,
            status_message=status_msg,
            job_id=job_id,
            custom_caption=clean_cap,
            upload_as_doc=user_settings.get("upload_as_doc", False),
            auto_forward_chat_id=auto_forward_id,
            user_id=user_id,
        )

        if uploaded:
            try:
                await status_msg.edit_text(
                    f"✅ **Omni Download Complete!**\n"
                    f"🎬 **Title:** `{v_title[:45]}`\n"
                    f"🌐 **Platform:** `{domain}`\n"
                    f"⚡ Delivered directly to your chat."
                )
            except Exception:
                pass

    except Exception as err:
        print(f"[!] Omni-downloader error: {err}")
        try:
            await status_msg.edit_text(f"❌ **Download Error:** `{str(err)[:100]}`")
        except Exception:
            pass

    finally:
        active_jobs.pop(job_id, None)


async def process_omni_link(client: Client, message: Message, target_url: str):
    """Processes an omni web link on behalf of batch runners."""
    dummy_msg = message
    dummy_msg.text = target_url
    await omni_url_listener(client, dummy_msg)

