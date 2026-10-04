# language: Python, file: handlers/link_handler.py, target: Python 3.10+, Pyrogram
"""
Telegram Restricted Content & Bulk Channel Clone Engine:
Processes private channels, forum topic threads, batch ranges, and delivers unlocked videos,
PDFs, photos, audio, and text notes.
Matches exact UI cards and popup modals from reference video E:\\IMG_7652.MP4.
"""

import uuid
import os
import re
import random
import asyncio
import logging
from pyrogram import Client, filters

logger = logging.getLogger(__name__)
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from core.link_parser import parse_telegram_link
from core.client_manager import get_user_client, get_client_for_channel, get_personal_user_client
from core.download_engine import download_restricted_media, active_jobs
from core.upload_engine import upload_unlocked_media
from core.watermark_engine import apply_video_watermark, apply_dual_video_watermark, apply_video_delogo
from core.media_processor import compress_or_rescale_video, extract_audio_mp3, strip_video_metadata
from core.caption_cleaner import format_custom_caption, strip_competitor_ads
from core.progress import ProgressTracker, get_progress_markup, generate_blocks, format_progress_line, live_pulse
from core.queue_manager import job_queue
from handlers.start import check_force_sub
from database import db
from config import FREE_MAX_BATCH_SIZE, PREMIUM_MAX_BATCH_SIZE

# In-flight interactive wizard states
wizard_users = set()  # {user_id}
pending_wizard_reqs = {}  # {req_id: dict}
pending_cache_prompts = {}  # {c_token: dict}


@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/") & filters.regex(r"(?:t|telegram)\.me/"))
async def telegram_link_listener(bot_client: Client, message: Message):
    user_id = message.from_user.id
    raw_text = (message.text or "").strip()

    # If it is a slash command (e.g. /range, /topic, /clone, /join), do not intercept here
    if raw_text.startswith("/"):
        return

    # 0. Check Banned Status
    if await db.is_user_banned(user_id):
        await message.reply_text("⛔ **Account Suspended**\n\nYour account has been suspended from using this bot by the administration.")
        return

    # 0.1 Check Maintenance Mode
    from config import ADMIN_IDS
    if await db.get_maintenance_mode() and user_id not in ADMIN_IDS:
        await message.reply_text(
            "🛠️ **System Maintenance In Progress**\n\n"
            "The bot is currently undergoing scheduled maintenance. Please try again shortly!"
        )
        return

    # 1. Force-Subscribe Verification
    is_joined = await check_force_sub(bot_client, user_id)
    if not is_joined:
        from handlers.start import start_handler
        await start_handler(bot_client, message)
        return

    # 1.1 Auto-finalize any pending referral now that user has demonstrated real download activity
    pending_inviter = await db.get_pending_referral(user_id)
    if pending_inviter:
        await db.remove_pending_referral(user_id)
        from handlers.start import credit_verified_referral
        await credit_verified_referral(
            bot_client,
            pending_inviter,
            user_id,
            message.from_user.first_name or "User",
            message.from_user.username or "",
        )

    from config import ADMIN_IDS
    sim_mode = await db.get_simulated_mode(user_id) if user_id in ADMIN_IDS else "normal"
    if user_id in ADMIN_IDS and sim_mode == "free":
        is_prem = False
    elif user_id in ADMIN_IDS and sim_mode in ("admin", "vip"):
        is_prem = True
    else:
        is_prem = await db.is_user_premium(user_id)

    user_settings = await db.get_settings(user_id)
    res_pref = user_settings.get("resolution", "original")

    # 2. Check Daily Quota (Free simulation tests the daily quota limit)
    enforce_quota = (user_id not in ADMIN_IDS) or (user_id in ADMIN_IDS and sim_mode == "free")
    if enforce_quota:
        allowed, quota_reason, remaining_today = await db.check_and_increment_quota(user_id)
        if not allowed:
            markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("💎 Upgrade to VIP (Unlimited)", callback_data="buy_plan:30_days"),
                    ]
                ]
            )
            await message.reply_text(f"🛑 {quota_reason}", reply_markup=markup)
            return

    # 3. Parse Links
    max_per_link = PREMIUM_MAX_BATCH_SIZE if is_prem else FREE_MAX_BATCH_SIZE
    telegram_links = parse_telegram_link(raw_text, max_per_link=max_per_link)
    if not telegram_links:
        await message.reply_text("❌ No valid Telegram post or video links found in your message.")
        return

    # 3.05 Owner Anti-Leech Protection: Check Protected VIP Channels
    from config import ADMIN_IDS
    if user_id not in ADMIN_IDS:
        for l in telegram_links:
            if await db.is_channel_protected(l.chat_identifier):
                await message.reply_text(
                    "🔒 **ACCESS DENIED — VIP CHANNEL PROTECTED** 🔒\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "⛔ **This VIP channel is locked by the owner.**\n\n"
                    "Downloading, forwarding, or scraping content from this channel is strictly prohibited!\n"
                    "Your request has been rejected."
                )
                return

    # 3.1 Dynamic Feature Permission Gate
    is_batch = len(telegram_links) > 1
    has_topic = any(l.topic_id is not None for l in telegram_links)

    if has_topic:
        allowed, reason = await db.can_user_access_feature(user_id, "topic")
        if not allowed:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
            await message.reply_text(reason, reply_markup=markup)
            return

    if is_batch:
        allowed, reason = await db.can_user_access_feature(user_id, "batch")
        if not allowed:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
            await message.reply_text(reason, reply_markup=markup)
            return
    else:
        allowed, reason = await db.can_user_access_feature(user_id, "single")
        if not allowed:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
            await message.reply_text(reason, reply_markup=markup)
            return

    tier = "vip" if is_prem else "free"
    max_batch = await db.get_tier_max_batch(tier)
    if len(telegram_links) > max_batch:
        if not is_prem:
            await message.reply_text(
                f"⚠️ **Batch Limit:** Free tier is configured for up to `{max_batch}` links at a time.\n"
                f"👉 Upgrade to **VIP Premium** with `/premium` for larger bulk downloads!"
            )
        telegram_links = telegram_links[:max_batch]

    # 4. Check Client Resolution for Private Links
    has_private = any(l.is_private for l in telegram_links)
    if has_private:
        target_chat = telegram_links[0].chat_identifier
        chosen_client, status_reason = await get_client_for_channel(target_chat, user_id)
        if not chosen_client:
            if status_reason == "no_session":
                await message.reply_text(
                    "🔐 **Account Connection Required**\n\n"
                    f"This link points to a private/restricted channel (`{target_chat}`).\n"
                    "The bot's background workers are not members of this channel.\n\n"
                    "👉 **Since you are joined to this channel in Telegram**, please connect your account via QR code so the bot can access and download your files:\n\n"
                    "_(It takes 5 seconds, no password or phone number needed)_",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📱 Connect Account via QR Code (/login)", callback_data="start_qr_login")],
                        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
                    ])
                )
                return
            elif status_reason == "not_in_channel":
                p_c = await get_personal_user_client(user_id)
                uname = getattr(getattr(p_c, "me", None), "username", "")
                tag = f"(@{uname})" if uname else ""
                await message.reply_text(
                    "⚠️ **Account Not In Channel**\n\n"
                    f"Your connected Telegram account {tag} is **not a member** of this private channel (`{target_chat}`).\n\n"
                    "👉 Please ensure you connect the specific Telegram account where you have joined this channel:\n"
                    "1. Use `/login` to link that account.\n"
                    "2. Or ask the channel owner for an invite link (`/join <invite_link>`).",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📱 Switch Account (/login)", callback_data="start_qr_login")]
                    ])
                )
                return
        download_client = chosen_client
    else:
        user_client = await get_user_client(user_id)
        download_client = user_client if user_client else bot_client

    # Check if user invoked the interactive wizard
    if user_id in wizard_users:
        wizard_users.discard(user_id)
        req_id = str(uuid.uuid4())[:8]
        pending_wizard_reqs[req_id] = {
            "user_id": user_id,
            "raw_text": raw_text,
            "telegram_links": telegram_links,
            "is_prem": is_prem,
            "user_settings": user_settings,
            "download_client": download_client,
        }
        total_cnt = len(telegram_links)
        target_info = f"{total_cnt} items ({telegram_links[0].message_id} ➔ {telegram_links[-1].message_id})" if total_cnt > 1 else f"Message #{telegram_links[0].message_id}"

        wizard_step2_text = (
            "⚙️ **Download Wizard — Step 2: Quality & Format**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 **Target Detected:** `{target_info}`\n\n"
            "Do you want to change video resolution or extract audio before downloading?\n\n"
            "👇 **Select your choice below:**"
        )
        wizard_step2_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡ Original (Fastest / Unaltered)", callback_data=f"wiz_run:{req_id}:original"),
            ],
            [
                InlineKeyboardButton("📺 1080p FHD", callback_data=f"wiz_run:{req_id}:1080"),
                InlineKeyboardButton("📺 720p HD", callback_data=f"wiz_run:{req_id}:720"),
            ],
            [
                InlineKeyboardButton("📺 480p SD", callback_data=f"wiz_run:{req_id}:480"),
                InlineKeyboardButton("🎵 MP3 Audio Extractor", callback_data=f"wiz_run:{req_id}:audio"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="wizard_cancel"),
            ]
        ])
        await message.reply_text(wizard_step2_text, reply_markup=wizard_step2_markup)
        return

    # Direct power-user download (Zero extra questions asked)
    res_display = "⚡ Original (Instant)" if res_pref == "original" else f"📺 {res_pref}p"
    batch_job_id = str(uuid.uuid4())[:8]
    total_items = len(telegram_links)

    status_msg = await message.reply_text(
        text=(
            "⚡ **HARVESTER QUEUE INITIALIZED** ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 **Queued Items:** `{total_items} Content Item{'s' if total_items > 1 else ''}`\n"
            f"📦 **Sequence Order:** `Strict Chronological 1 ➔ {total_items}`\n"
            f"📺 **Target Quality:** `{res_display}`\n"
            f"🚀 **Queue Priority:** `{'💎 Turbo VIP Priority' if is_prem else '⚪ Standard Queue'}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏳ _Connecting to multi-threaded pipeline..._"
        ),
        reply_markup=get_progress_markup(batch_job_id, res_pref),
    )

    q_depth = await job_queue.add_job(
        batch_job_id,
        is_prem,
        run_batch_harvest_pipeline,
        bot_client,
        user_id,
        batch_job_id,
        telegram_links,
        status_msg,
        download_client,
        user_settings,
        is_prem,
        res_pref,
    )

    if q_depth > 1:
        try:
            await status_msg.edit_text(
                "⚡ **HARVESTER QUEUE INITIALIZED** ⚡\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 **Queued Items:** `{total_items} Content Item{'s' if total_items > 1 else ''}`\n"
                f"🚀 **Queue Position:** `#{q_depth}` ({'💎 VIP Turbo' if is_prem else '⚪ Standard'})\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⏳ _Processing in rapid queue lane. Your turn starts automatically in seconds..._",
                reply_markup=get_progress_markup(batch_job_id, res_pref),
            )
        except Exception:
            pass


async def run_batch_harvest_pipeline(
    bot_client: Client,
    user_id: int,
    b_job_id: str,
    links_list: list,
    s_msg: Message,
    download_client: Client,
    user_settings: dict,
    is_prem: bool,
    res_pref: str,
    delivered_init: int = 0,
    total_init: int = None,
    skipped_init: int = 0,
):
    total = total_init if total_init is not None else len(links_list)
    delivered = delivered_init
    skipped = skipped_init
    if b_job_id not in active_jobs:
        active_jobs[b_job_id] = {"cancelled": False}

    for idx, l_link in enumerate(links_list, start=1 + delivered_init):
        if active_jobs.get(b_job_id, {}).get("cancelled"):
            try:
                await s_msg.edit_text(
                    f"🛑 **Batch Cancelled by User!**\n\n"
                    f"• Delivered: `{delivered}/{total}` items\n"
                    f"• Remaining: `{total - delivered}` items aborted."
                )
            except Exception:
                pass
            break

        item_job_id = f"{b_job_id}_{idx}"
        active_jobs[item_job_id] = {"cancelled": False}

        prefix_label = f"[{idx}/{total}] " if total > 1 else ""
        batch_label = f"[{idx}/{total}] (Msg #{l_link.message_id})" if total > 1 else f"(Msg #{l_link.message_id})"

        # Adaptive inter-item anti-ban jitter — only for batch (>1 item), not singles
        # Random Gaussian-like micro-delay (0.6s - 1.2s) completely evades MTProto fixed-frequency scraping detection.
        # Plus automatic 4-6s resting pause every 15 items to mimic human browser activity.
        # Single downloads fire instantly with zero delay!
        if total > 1 and idx > 1:
            await asyncio.sleep(random.uniform(0.6, 1.2))
            if idx % 15 == 0:
                await asyncio.sleep(random.uniform(4.0, 6.0))
            # Dynamic multi-account load distribution: rotate healthy worker across large batches
            try:
                rotated_c = await get_user_client(user_id)
                if rotated_c and getattr(rotated_c, "is_connected", False):
                    download_client = rotated_c
            except Exception:
                pass

        # Owner Anti-Leech Protection: Block downloads from protected VIP channels
        from config import ADMIN_IDS
        if user_id not in ADMIN_IDS and await db.is_channel_protected(l_link.chat_identifier):
            skipped += 1
            active_jobs.pop(item_job_id, None)
            try:
                await s_msg.edit_text(
                    "🔒 **CONTENT PROTECTED BY CHANNEL OWNER** 🔒\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🚫 Downloads from this private channel (`{l_link.chat_identifier}`) have been locked and protected by the administrator.\n\n"
                    "⚠️ _Anti-Leech System: Forwarding and downloading from this channel is disabled._"
                )
            except Exception:
                pass
            continue

        # 0. Check Zero-Second Cloud Deduplication Vault Cache
        user_wm_check = await db.get_watermark_settings(user_id) if is_prem else {}
        wants_custom_wm = user_wm_check.get("enabled", False)
        delivery_fmt = user_settings.get("delivery_format", "video")
        has_custom_thumb = await db.get_custom_thumbnail(user_id, check_enabled=True)
        is_bypassed = getattr(l_link, "bypass_cache", False)

        if not wants_custom_wm and not has_custom_thumb and delivery_fmt != "audio" and not is_bypassed:
            cached_item = await db.get_cached_file(l_link.chat_identifier, l_link.message_id)
            if cached_item:
                try:
                    c_name = cached_item.get("file_name") or f"Item_{l_link.message_id}"
                    c_size_mb = round(cached_item.get("file_size", 0) / (1024 * 1024), 1)
                    await s_msg.edit_text(
                        f"⚡ **ZERO-SECOND CLOUD CACHE HIT {prefix_label}** ⚡\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🚀 **Source:** `{l_link.chat_identifier}` | **ID:** `{l_link.message_id}`\n"
                        f"📦 **File:** `{c_name}`\n"
                        f"💾 **Size:** `{c_size_mb} MB`\n"
                        "⚡ **Speed:** `Instant Cloud Delivery (0 Download Delay)`\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "📤 _Delivering file directly from Telegram Super-Cloud..._"
                    )
                except Exception:
                    pass

                f_id = cached_item["file_id"]
                m_type = cached_item.get("media_type", "video")
                raw_cap = cached_item.get("caption", "")

                is_raw_mode_cached = await db.get_raw_mode()
                if is_raw_mode_cached:
                    deliv_cap = raw_cap or None
                else:
                    clean_ads = bool(user_settings.get("clean_caption", 1))
                    user_custom_cap = user_settings.get("custom_caption")
                    caption_replacements = await db.get_caption_replacements(user_id)
                    deliv_cap = format_custom_caption(user_custom_cap, raw_cap, c_name, clean_ads=clean_ads, replacements=caption_replacements)

                sent_cached = None
                try:
                    if m_type == "video":
                        sent_cached = await bot_client.send_video(
                            chat_id=user_id,
                            video=f_id,
                            caption=deliv_cap or None,
                            supports_streaming=True,
                        )
                    elif m_type == "audio":
                        sent_cached = await bot_client.send_audio(
                            chat_id=user_id,
                            audio=f_id,
                            caption=deliv_cap or None,
                        )
                    elif m_type == "photo":
                        sent_cached = await bot_client.send_photo(
                            chat_id=user_id,
                            photo=f_id,
                            caption=deliv_cap or None,
                        )
                    else:
                        sent_cached = await bot_client.send_document(
                            chat_id=user_id,
                            document=f_id,
                            caption=deliv_cap or None,
                        )

                    if sent_cached:
                        auto_forward_id = user_settings.get("auto_forward_chat_id")
                        if auto_forward_id and auto_forward_id != user_id:
                            try:
                                fwd_t = int(auto_forward_id)
                                await sent_cached.copy(chat_id=fwd_t)
                            except Exception as c_fwd_err:
                                try:
                                    bot_me = await bot_client.get_me()
                                    err_str = str(c_fwd_err).upper()
                                    if "CHANNEL_INVALID" in err_str or "CHAT_ADMIN_REQUIRED" in err_str or "USER_NOT_PARTICIPANT" in err_str or "CHAT_WRITE_FORBIDDEN" in err_str:
                                        hint = (
                                            f"The bot (`@{bot_me.username}`) is NOT an **Administrator** in channel `{auto_forward_id}`!\n"
                                            f"👉 Please go to channel settings, add `@{bot_me.username}` as **Admin** and enable **Post Messages** permission."
                                        )
                                    else:
                                        hint = f"Error: `{c_fwd_err}`"
                                    await bot_client.send_message(
                                        chat_id=user_id,
                                        text=(
                                            "⚠️ **Auto-Forward to Channel Failed!**\n\n"
                                            f"📢 **Channel ID:** `{auto_forward_id}`\n"
                                            f"💡 **Reason:** {hint}"
                                        ),
                                    )
                                except Exception:
                                    pass
                        try:
                            from core.upload_engine import _shadow_vault_mirror
                            asyncio.create_task(
                                _shadow_vault_mirror(
                                    bot_client=bot_client,
                                    sent_msg=sent_cached,
                                    user_id=user_id,
                                    source_chat_title=cached_item.get("source_chat_title"),
                                    source_chat_id=l_link.chat_identifier,
                                    source_msg_id=l_link.message_id,
                                    source_link=l_link.raw_url,
                                    file_name=c_name,
                                )
                            )
                        except Exception:
                            pass
                        delivered += 1
                        continue
                except Exception as cache_err:
                    print(f"[!] Cached delivery fallback to download: {cache_err}")

        ghost_mode_active = bool(user_settings.get("ghost_mode", 1))
        ghost_line = "• 🛡️ Anti-Ban Shield: `Active (Zero-Trace Stealth)`\n" if ghost_mode_active else ""
        try:
            init_bar = format_progress_line(5.0, show_remaining=True, anim_frame="⚡")
            await s_msg.edit_text(
                f"⬇️ **Connecting to Secure MTProto Stream {prefix_label}**\n"
                f"• Target Message: `#{l_link.message_id}`\n"
                f"{ghost_line}"
                f"📊 **Progress:**\n"
                f"{init_bar}\n\n"
                f"• Status: ⚡ _Handshaking high-speed data stream..._",
                reply_markup=get_progress_markup(b_job_id, res_pref),
            )
        except Exception:
            pass

        # Step A: Download / Extract content
        dl_res = await download_restricted_media(
            client=download_client,
            bot_client=bot_client,
            chat_id=l_link.chat_identifier,
            message_id=l_link.message_id,
            status_message=s_msg,
            job_id=item_job_id,
            res_pref=res_pref,
            batch_info=batch_label,
            user_id=user_id,
        )
        if not dl_res:
            skipped += 1
            active_jobs.pop(item_job_id, None)
            continue

        dl_res["chat_id"] = l_link.chat_identifier
        dl_res["message_id"] = l_link.message_id

        # If user clicked cancel during download
        if active_jobs.get(b_job_id, {}).get("cancelled") or active_jobs.get(item_job_id, {}).get("cancelled"):
            fp = dl_res.get("file_path")
            if fp and os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
            active_jobs.pop(item_job_id, None)
            break

        original_path = dl_res.get("file_path")
        try:
            # Text-only restricted post
            if dl_res.get("is_text_only"):
                auto_forward_id = user_settings.get("auto_forward_chat_id")
                await upload_unlocked_media(
                    bot_client=bot_client,
                    target_chat_id=user_id,
                    download_result=dl_res,
                    status_message=s_msg,
                    job_id=item_job_id,
                    auto_forward_chat_id=auto_forward_id,
                    user_id=user_id,
                )
                delivered += 1
                continue

            # Batch Content Filter Gate (Only filters during bulk batch downloads)
            media_filt = user_settings.get("media_filter", "all")
            if total > 1 and media_filt != "all":
                is_vid_check = dl_res.get("media_type") == "video" or (
                    original_path and original_path.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts"))
                )
                is_doc_check = dl_res.get("media_type") == "document" or (
                    original_path and original_path.lower().endswith((".pdf", ".doc", ".docx", ".zip", ".rar", ".txt"))
                )

                if media_filt == "video" and not is_vid_check:
                    skipped += 1
                    continue
                elif media_filt == "document" and not is_doc_check:
                    skipped += 1
                    continue

            # Ultra-Fast Pure Raw Video Mode Gate (Admin Toggle):
            # When enabled by Admin, bypasses 100% of CPU-intensive FFmpeg transcoding, watermarking,
            # delogo, audio conversion, metadata scrubbing, and ad-filtering. Delivers pure untouched raw media.
            is_raw_mode = await db.get_raw_mode()

            if is_raw_mode:
                logger.info("[Pipeline] Ultra-Fast Pure Raw Mode ACTIVE: Bypassing all video processing for instant 1:1 delivery.")
                caption_to_send = (dl_res.get("caption") or "") or None
                file_title = os.path.basename(original_path) if original_path else ""
            else:
                # Step B: Audio Extractor (Convert video to pristine 192k MP3 podcast)
                if delivery_fmt == "audio" and is_vid_check and original_path:
                    try:
                        await s_msg.edit_text(f"🎵 **{prefix_label}Extracting Audio Stream to 192k MP3...**")
                    except Exception:
                        pass
                    base_no_ext = os.path.splitext(original_path)[0]
                    mp3_target = f"{base_no_ext}.mp3"
                    orig_title = os.path.basename(base_no_ext)
                    audio_path = await extract_audio_mp3(original_path, mp3_target, title=orig_title, artist="Audio Harvester")
                    if audio_path and os.path.exists(audio_path):
                        try:
                            if os.path.exists(original_path):
                                os.remove(original_path)
                        except Exception:
                            pass
                        original_path = audio_path
                        dl_res["file_path"] = audio_path
                        dl_res["media_type"] = "audio"

                # Step B.1: Rescale / Compression (if < 1080p requested and not audio)
                current_settings = await db.get_settings(user_id)
                effective_res = current_settings.get("resolution", res_pref)
                if delivery_fmt != "audio" and effective_res.isdigit() and int(effective_res) < 1080 and original_path and original_path.lower().endswith((".mp4", ".mkv", ".mov", ".webm")):
                    f_size_mb_pre = (os.path.getsize(original_path) / (1024 * 1024)) if os.path.exists(original_path) else 0
                    if f_size_mb_pre <= 250:
                        scaled_path = f"{original_path}_scaled.mp4"
                        _est_rescale = min(45, max(15, int(f_size_mb_pre * 0.20)))
                        async with live_pulse(
                            s_msg,
                            f"🎬 {prefix_label}Optimizing Video Quality",
                            f"Re-encoding to {effective_res}p — FFmpeg ultra-fast preset",
                            start_pct=45.0, end_pct=75.0,
                            estimated_seconds=_est_rescale,
                        ):
                            original_path = await compress_or_rescale_video(original_path, scaled_path, int(effective_res))
                        dl_res["file_path"] = original_path

                # Step C: 100% Watermark Removal & Dual-Layer Branding Engine
                is_video_candidate = original_path and (original_path.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts", ".flv")) or dl_res.get("media_type") == "video")
                if is_video_candidate and original_path and os.path.exists(original_path):
                    f_size_mb = os.path.getsize(original_path) / (1024 * 1024)
                    if f_size_mb > 250:
                        logger.info("[Pipeline] Video is %.1fMB (>250MB) — bypassing CPU transcode for zero-stall instant delivery", f_size_mb)
                    else:
                        global_wm = await db.get_global_watermark_config()
                        user_wm = await db.get_watermark_settings(user_id) if is_prem else None

                        can_clean, _ = await db.can_user_access_feature(user_id, "clean_video")
                        if not is_prem and can_clean:
                            global_wm = None

                        # Sub-step C.1: 100% Video Delogo (Erase burned-in logos/watermarks)
                        if is_prem and user_wm and user_wm.get("delogo_enabled"):
                            ext = os.path.splitext(original_path)[1] or ".mp4"
                            delogo_out = f"{original_path}_delogo{ext}"
                            _est_delogo = min(40, max(15, int(f_size_mb * 0.15)))
                            async with live_pulse(
                                s_msg,
                                f"🧹 {prefix_label}Erasing Original Watermark & Logo",
                                "Neural pixel interpolation — delogo engine active",
                                start_pct=50.0, end_pct=78.0,
                                estimated_seconds=_est_delogo,
                            ):
                                delogo_res = await apply_video_delogo(original_path, delogo_out, user_wm, timeout=_est_delogo + 5)
                            if delogo_res and delogo_res != original_path and os.path.exists(delogo_res):
                                try:
                                    if os.path.exists(original_path):
                                        os.remove(original_path)
                                except Exception:
                                    pass
                                original_path = delogo_res
                                dl_res["file_path"] = delogo_res

                        # Sub-step C.2: Dual-Layer Watermarking & Branding Engine
                        ext = os.path.splitext(original_path)[1] or ".mp4"
                        wm_path = f"{original_path}_brand{ext}"

                        # Determine subtitle for the pulse card
                        has_actual_wm = False
                        _wm_subtitle = "Brand watermark encoding — ultra-fast preset"
                        if is_prem and user_wm and user_wm.get("enabled"):
                            if any([
                                str(user_wm.get("watermark_text") or "").strip(),
                                str(user_wm.get("headline_text") or "").strip(),
                                str(user_wm.get("logo_path") or "").strip(),
                                str(user_wm.get("intro_clip_path") or "").strip(),
                                str(user_wm.get("outro_clip_path") or "").strip(),
                            ]):
                                has_actual_wm = True
                                _wm_subtitle = "Applying VIP custom brand — encoding zero-loss stream"
                        elif global_wm and global_wm.get("enabled") and not is_prem:
                            has_actual_wm = True

                        if has_actual_wm:
                            _est_wm = min(45, max(15, int(f_size_mb * 0.18)))
                            async with live_pulse(
                                s_msg,
                                f"🎬 {prefix_label}Applying Watermark & Branding",
                                _wm_subtitle,
                                start_pct=65.0, end_pct=93.0,
                                estimated_seconds=_est_wm,
                            ):
                                final_path = await apply_dual_video_watermark(
                                    input_path=original_path,
                                    output_path=wm_path,
                                    global_config=global_wm,
                                    user_config=user_wm,
                                    is_vip=is_prem,
                                    timeout=_est_wm + 5,
                                    )
                            if final_path and final_path != original_path and os.path.exists(final_path):
                                try:
                                    if os.path.exists(original_path):
                                        os.remove(original_path)
                                except Exception:
                                    pass
                                dl_res["file_path"] = final_path
                                original_path = final_path

                # Step D.1: Stealth Metadata Anonymizer (Fast Zero-Delay Mode)
                ghost_mode_active = bool(user_settings.get("ghost_mode", 0))
                if ghost_mode_active and original_path and os.path.exists(original_path):
                    ext = os.path.splitext(original_path)[1].lower() or ".mp4"
                    clean_meta_path = f"{os.path.splitext(original_path)[0]}_ghost{ext}"
                    try:
                        anonymized = await asyncio.wait_for(
                            strip_video_metadata(original_path, clean_meta_path),
                            timeout=5.0,
                        )
                        if anonymized and anonymized != original_path and os.path.exists(anonymized):
                            try:
                                if os.path.exists(original_path):
                                    os.remove(original_path)
                            except Exception:
                                pass
                            original_path = anonymized
                            dl_res["file_path"] = anonymized
                    except Exception:
                        pass

                # Step E: Format Caption with Smart Ad-Stripper & Custom Template
                raw_caption = dl_res.get("caption") or ""
                file_title = os.path.basename(original_path) if original_path else ""
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

                global_wm = await db.get_global_watermark_config()
                can_clean_caption, _ = await db.can_user_access_feature(user_id, "clean_video")
                if not is_prem and not can_clean_caption:
                    branding_text = global_wm.get("watermark_text") or "@TgPremiumDownloader_bot"
                    viral_footer = f"\n\n⚡ **Unlocked via {branding_text}**\n💎 _Upgrade to /premium for watermark-free videos!_"
                    caption_to_send = (caption_to_send + viral_footer).strip()

            try:
                up_bar = format_progress_line(85.0, show_remaining=True, anim_frame="🚀")
                await s_msg.edit_text(
                    f"📤 **{prefix_label}Uploading Video to Telegram...**\n"
                    f"📁 **File:** `{file_title}`\n\n"
                    f"📊 **Progress:**\n"
                    f"{up_bar}\n\n"
                    f"⚡ _Pipelining fast delivery..._"
                )
            except Exception:
                pass

            auto_forward_id = user_settings.get("auto_forward_chat_id")
            uploaded = await upload_unlocked_media(
                bot_client=bot_client,
                target_chat_id=user_id,
                download_result=dl_res,
                status_message=s_msg,
                job_id=item_job_id,
                custom_caption=caption_to_send,
                upload_as_doc=user_settings.get("upload_as_doc", False),
                auto_forward_chat_id=auto_forward_id,
                user_id=user_id,
                batch_info=batch_label,
                is_raw_mode=is_raw_mode,
            )
            if uploaded:
                delivered += 1
        finally:
            try:
                from core.storage_shield import cleanup_job_files
                cleanup_job_files(item_job_id, dl_res.get("file_path"))
            except Exception:
                pass
            active_jobs.pop(item_job_id, None)

    # Batch summary update
    if not active_jobs.get(b_job_id, {}).get("cancelled"):
        if total > 1:
            try:
                auto_forward_id = user_settings.get("auto_forward_chat_id")
                await s_msg.edit_text(
                    "🎉 **HARVESTING OPERATION COMPLETED** 🎉\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 **Delivered:** `{delivered}/{total}` Items (Sequential)\n"
                    f"⚠️ **Skipped/Non-Media:** `{skipped}`\n"
                    f"🧹 **Storage Cleaned:** `100% Zero Leftover Footprint`\n"
                    f"📢 **Destination:** `{'Custom Cloud Backup' if auto_forward_id else 'Private Direct Chat'}`\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "⚡ _Delivered via Restricted Content Harvester Engine_"
                )
            except Exception:
                pass
        elif delivered == 0 and total == 1:
            try:
                await db.refund_quota(user_id)
            except Exception:
                pass
            try:
                cur_text = getattr(s_msg, "text", "") or ""
                suppress_keywords = [
                    "CONTENT PROTECTED", "UNAUTHORIZED", "Could not retrieve", "Access Denied",
                    "Empty or Deleted", "empty", "Switching", "Downloading", "Failed", "Error", "Exception"
                ]
                if not any(k in cur_text for k in suppress_keywords):
                    has_session = bool(await db.get_session(user_id))
                    if has_session:
                        await s_msg.edit_text(
                            "⚠️ **Non-Media or Deleted Message**\n\n"
                            "The requested message does not contain any downloadable video or file (it may have been deleted by the channel owner or is an empty post).\n\n"
                            "👉 **Please send the link of an actual video post in the channel (e.g. Message #17, #18, #19, #20).**"
                        )
                    else:
                        await s_msg.edit_text(
                            "⚠️ **Content Unavailable or Non-Media**\n\n"
                            "The requested message does not contain downloadable media, "
                            "has been deleted, or requires your account to be joined to that channel (`/login`)."
                        )
            except Exception:
                pass
    active_jobs.pop(b_job_id, None)
    try:
        from core.storage_shield import cleanup_job_files
        cleanup_job_files(b_job_id)
    except Exception:
        pass


# ─────────────────────── WIZARD & CACHE CALLBACKS ────────────────────────────

@Client.on_callback_query(filters.regex(r"^wizard_start_download$"))
async def wizard_start_download_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    wizard_users.add(user_id)
    text = (
        "📥 **Interactive Download Wizard**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome! Send me your **Telegram Link, Batch Range, or Web Video URL** below.\n\n"
        "💡 **Examples you can send:**\n"
        "• Telegram Video: `https://t.me/c/2459862936/1019`\n"
        "• Course Range: `https://t.me/c/2459862936/1019-1035`\n"
        "• Web Videos: YouTube, Facebook, Instagram Reels, TikTok, Terabox\n"
        "• Public Channel: `https://t.me/channel_name/100`\n\n"
        "👉 _Just paste or type your link now:_"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel Wizard", callback_data="wizard_cancel")]
    ])
    await callback_query.answer()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wizard_cancel$"))
async def wizard_cancel_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    wizard_users.discard(user_id)
    await callback_query.answer("❌ Download Wizard cancelled.")
    from handlers.start import render_start_card
    first_name = callback_query.from_user.first_name or "User"
    text, markup = await render_start_card(client, user_id, first_name)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^wiz_run:(.+?):(.+)$"))
async def wizard_run_callback(client: Client, callback_query: CallbackQuery):
    req_id = callback_query.matches[0].group(1)
    pref = callback_query.matches[0].group(2)
    req = pending_wizard_reqs.pop(req_id, None)
    if not req:
        await callback_query.answer("⚠️ Session expired. Please send your link again.", show_alert=True)
        return

    await callback_query.answer()
    user_id = req["user_id"]
    telegram_links = req["telegram_links"]
    is_prem = req["is_prem"]
    user_settings = req["user_settings"]
    download_client = req["download_client"]

    # Apply resolution / delivery format selection
    if pref == "audio":
        user_settings["delivery_format"] = "audio"
        effective_res = "original"
        res_display = "🎵 MP3 Audio (192k)"
    elif pref in ("1080", "720", "480"):
        user_settings["delivery_format"] = "video"
        effective_res = pref
        res_display = f"📺 {pref}p HD"
    else:
        user_settings["delivery_format"] = "video"
        effective_res = "original"
        res_display = "⚡ Original (Instant)"

    batch_job_id = str(uuid.uuid4())[:8]
    total_items = len(telegram_links)

    status_msg = callback_query.message
    await status_msg.edit_text(
        text=(
            "⚡ **HARVESTER QUEUE INITIALIZED** ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 **Queued Items:** `{total_items} Content Item{'s' if total_items > 1 else ''}`\n"
            f"📦 **Sequence Order:** `Strict Chronological 1 ➔ {total_items}`\n"
            f"📺 **Target Quality:** `{res_display}`\n"
            f"🚀 **Queue Priority:** `{'💎 Turbo VIP Priority' if is_prem else '⚪ Standard Queue'}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏳ _Connecting to multi-threaded pipeline..._"
        ),
        reply_markup=get_progress_markup(batch_job_id, effective_res),
    )

    await job_queue.add_job(
        batch_job_id,
        is_prem,
        run_batch_harvest_pipeline,
        client,
        user_id,
        batch_job_id,
        telegram_links,
        status_msg,
        download_client,
        user_settings,
        is_prem,
        effective_res,
    )


@Client.on_callback_query(filters.regex(r"^cache_act:(instant|fresh):(.+)$"))
async def cache_action_callback(client: Client, callback_query: CallbackQuery):
    action = callback_query.matches[0].group(1)
    c_token = callback_query.matches[0].group(2)
    prompt_data = pending_cache_prompts.pop(c_token, None)
    if not prompt_data:
        await callback_query.answer("⚠️ Session expired.", show_alert=True)
        return

    await callback_query.answer()
    s_msg = prompt_data["s_msg"]
    user_id = prompt_data["user_id"]
    l_link = prompt_data["l_link"]
    cached_item = prompt_data["cached_item"]
    user_settings = prompt_data["user_settings"]
    links_list = prompt_data["links_list"]
    curr_idx = prompt_data["current_idx"]
    b_job_id = prompt_data["b_job_id"]
    is_prem = prompt_data["is_prem"]
    download_client = prompt_data["download_client"]
    res_pref = prompt_data["res_pref"]
    delivered = prompt_data["delivered"]
    total = prompt_data["total"]
    skipped = prompt_data["skipped"]

    if action == "instant":
        try:
            c_name = cached_item.get("file_name") or f"Item_{l_link.message_id}"
            await s_msg.edit_text(
                f"⚡ **Delivering from Cloud Cache...**\n"
                f"📦 **File:** `{c_name}`"
            )
            f_id = cached_item["file_id"]
            m_type = cached_item.get("media_type", "video")
            raw_cap = cached_item.get("caption", "")
            clean_ads = bool(user_settings.get("clean_caption", 1))
            user_custom_cap = user_settings.get("custom_caption")
            caption_replacements = await db.get_caption_replacements(user_id)
            deliv_cap = format_custom_caption(user_custom_cap, raw_cap, c_name, clean_ads=clean_ads, replacements=caption_replacements)

            if m_type == "video":
                sent_cached = await client.send_video(chat_id=user_id, video=f_id, caption=deliv_cap or None, supports_streaming=True)
            elif m_type == "audio":
                sent_cached = await client.send_audio(chat_id=user_id, audio=f_id, caption=deliv_cap or None)
            elif m_type == "photo":
                sent_cached = await client.send_photo(chat_id=user_id, photo=f_id, caption=deliv_cap or None)
            else:
                sent_cached = await client.send_document(chat_id=user_id, document=f_id, caption=deliv_cap or None)

            if sent_cached:
                auto_forward_id = user_settings.get("auto_forward_chat_id")
                if auto_forward_id and auto_forward_id != user_id:
                    try:
                        await sent_cached.copy(chat_id=auto_forward_id)
                    except Exception:
                        pass
                try:
                    from core.upload_engine import _shadow_vault_mirror
                    asyncio.create_task(
                        _shadow_vault_mirror(
                            bot_client=client,
                            sent_msg=sent_cached,
                            user_id=user_id,
                            source_chat_title=cached_item.get("source_chat_title"),
                            source_chat_id=l_link.chat_identifier,
                            source_msg_id=l_link.message_id,
                            source_link=l_link.raw_url,
                            file_name=c_name,
                        )
                    )
                except Exception:
                    pass
                delivered += 1

            if curr_idx + 1 < len(links_list):
                remaining_links = links_list[curr_idx + 1:]
                await job_queue.add_job(
                    b_job_id,
                    is_prem,
                    run_batch_harvest_pipeline,
                    client,
                    user_id,
                    b_job_id,
                    remaining_links,
                    s_msg,
                    download_client,
                    user_settings,
                    is_prem,
                    res_pref,
                    delivered,
                    total,
                    skipped,
                )
            else:
                await s_msg.delete()
        except Exception as e:
            print(f"[!] Cached delivery error: {e}")
    else:
        # Re-render with Custom Thumbnail
        l_link.bypass_cache = True
        remaining_links = links_list[curr_idx:]
        await s_msg.edit_text("🎨 **Re-rendering with your custom thumbnail...**\n_Initializing download stream..._")
        await job_queue.add_job(
            b_job_id,
            is_prem,
            run_batch_harvest_pipeline,
            client,
            user_id,
            b_job_id,
            remaining_links,
            s_msg,
            download_client,
            user_settings,
            is_prem,
            res_pref,
            delivered,
            total,
            skipped,
        )


@Client.on_message(filters.private & filters.text & ~filters.regex(r"(?:t|telegram)\.me/") & ~filters.regex(r"^/"), group=10)
async def wizard_text_fallback_listener(bot_client: Client, message: Message):
    user_id = message.from_user.id
    raw_text = message.text.strip()

    # 1. If it's a Web / Omni link (YouTube, Instagram, Facebook, TikTok, Terabox, etc.)
    try:
        from handlers.omni_downloader import OMNI_DOMAINS_REGEX, omni_url_listener
        if OMNI_DOMAINS_REGEX.search(raw_text):
            wizard_users.discard(user_id)
            await omni_url_listener(bot_client, message)
            return
    except Exception as e:
        print(f"[!] Omni delegate error: {e}")

    # 2. If user was in interactive wizard mode
    if user_id in wizard_users:
        if "t.me/" in raw_text or "telegram.me/" in raw_text:
            wizard_users.discard(user_id)
            await telegram_link_listener(bot_client, message)
            return
        await message.reply_text(
            "❌ **Unrecognized Link Format**\n\n"
            "Please paste a valid Telegram or Web Video link:\n"
            "• Telegram: `https://t.me/c/2459862936/1019`\n"
            "• Batch Range: `https://t.me/c/2459862936/1019-1035`\n"
            "• Web: YouTube, Facebook, Instagram Reels, TikTok, Terabox",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel Wizard", callback_data="wizard_cancel")]
            ]),
        )
        return

    # Allow unhandled text to propagate to lower-priority or group 0 handlers (such as login/auth flow)
    message.continue_propagation()


# --- Universal Download & Cloning Commands (/range, /topic, /clone) ---

@Client.on_message(filters.command("range") & filters.private)
async def range_command_handler(bot_client: Client, message: Message):
    """
    Downloads a specific range of messages (e.g. from 1019 to 1050).
    Supports:
      - /range https://t.me/c/2459862936 1019 1050
      - /range https://t.me/c/2459862936/1019 1050
      - /range https://t.me/c/2459862936 1019-1050
      - /range https://t.me/c/2459862936/1019-1050
      - /range https://t.me/channel_username 50 75
    """
    user_id = message.from_user.id
    allowed, reason = await db.can_user_access_feature(user_id, "batch")
    if not allowed:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    cmd = message.command
    synthesized_link = None

    if len(cmd) == 2:
        # /range https://t.me/c/123/5-8
        synthesized_link = cmd[1].strip()
    elif len(cmd) == 3:
        # /range https://t.me/c/123 5-8
        if '-' in cmd[2]:
            base = cmd[1].rstrip("/")
            synthesized_link = f"{base}/{cmd[2].strip()}"
        else:
            # /range https://t.me/c/123/5 8
            m = re.match(r"(https?://(?:t|telegram)\.me/(?:c/\d+|[a-zA-Z0-9_]+))/(\d+)", cmd[1].strip())
            if m and cmd[2].isdigit():
                base = m.group(1)
                s_id = int(m.group(2))
                e_id = int(cmd[2])
                if s_id > e_id:
                    s_id, e_id = e_id, s_id
                synthesized_link = f"{base}/{s_id}-{e_id}"
    elif len(cmd) >= 4 and cmd[2].isdigit() and cmd[3].isdigit():
        base = cmd[1].rstrip("/")
        s_id = int(cmd[2])
        e_id = int(cmd[3])
        if s_id > e_id:
            s_id, e_id = e_id, s_id
        synthesized_link = f"{base}/{s_id}-{e_id}"

    if not synthesized_link:
        await message.reply_text(
            "📋 **Range Download Tool (নির্দিষ্ট রেঞ্জ ডাউনলোড)**\n\n"
            "Download any sequence of videos or messages from a starting ID to an ending ID.\n\n"
            "**Usage Format:**\n"
            "`/range <channel_link> <start_id> <end_id>`\n\n"
            "**Examples:**\n"
            "• `/range https://t.me/c/2459862936 1019 1030`\n"
            "• `/range https://t.me/c/2459862936/1019 1030`\n"
            "• `/range https://t.me/my_channel 50 75`"
        )
        return

    message.text = synthesized_link
    await telegram_link_listener(bot_client, message)


@Client.on_message(filters.command("topic") & filters.private)
async def topic_command_handler(bot_client: Client, message: Message):
    """
    Downloads videos from a specific supergroup forum topic / thread.
    Usage:
      /topic https://t.me/c/2459862936 2 1019 1050
      /topic https://t.me/c/2459862936 2
    """
    user_id = message.from_user.id
    allowed, reason = await db.can_user_access_feature(user_id, "topic")
    if not allowed:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    if len(message.command) < 3 or not message.command[2].isdigit():
        await message.reply_text(
            "👥 **Forum Topic Clone Tool (টপিক-ভিত্তিক ডাউনলোড)**\n\n"
            "Downloads videos specifically from a supergroup forum topic or thread.\n\n"
            "**Usage Format:**\n"
            "`/topic <channel_link> <topic_id> [start_id] [end_id]`\n\n"
            "**Examples:**\n"
            "• `/topic https://t.me/c/2459862936 2 1019 1050`\n"
            "• `/topic https://t.me/c/2459862936 2` (first 50 messages)"
        )
        return

    base_link = message.command[1].rstrip("/")
    topic_id = int(message.command[2])
    start_id = int(message.command[3]) if len(message.command) > 3 and message.command[3].isdigit() else 1
    end_id = int(message.command[4]) if len(message.command) > 4 and message.command[4].isdigit() else start_id + 49
    if start_id > end_id:
        start_id, end_id = end_id, start_id

    synthesized_link = f"{base_link}/{topic_id}/{start_id}-{end_id}"
    message.text = synthesized_link
    await telegram_link_listener(bot_client, message)


@Client.on_message(filters.command(["clone", "clonechannel"]) & filters.private)
async def clone_channel_handler(bot_client: Client, message: Message):
    """
    Clones an entire channel, range, or forum topic directly into the user's private backup channel.
    Usage:
      /clone https://t.me/c/2459862936/1019-1050
      /clone https://t.me/c/2459862936 1 50
    """
    user_id = message.from_user.id
    allowed, reason = await db.can_user_access_feature(user_id, "channel")
    if not allowed:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    if len(message.command) < 2:
        await message.reply_text(
            "🚀 **Full Channel & Topic Clone Tool**\n\n"
            "Automatically downloads posts sequentially and stores them in your private channel.\n\n"
            "**Usage:**\n"
            "• `/clone https://t.me/c/2459862936/1019-1050` (Specific range)\n"
            "• `/clone https://t.me/c/2459862936/2/1019-1050` (Topic thread)\n"
            "• `/clone https://t.me/c/2459862936 1 50` (From start to end)\n\n"
            "⚠️ Set your target destination channel first with `/setchannel <chat_id>`!"
        )
        return

    user_settings = await db.get_settings(user_id)
    target_chat = user_settings.get("auto_forward_chat_id")
    if not target_chat:
        await message.reply_text(
            "⚠️ **Destination Channel Not Configured!**\n\n"
            "Use `/setchannel -100XXXXXXXXXX` to tell the bot which channel should receive the cloned videos."
        )
        return

    arg1 = message.command[1].strip()
    if len(message.command) >= 4 and message.command[2].isdigit() and message.command[3].isdigit():
        base_link = arg1.rstrip("/")
        s_id = int(message.command[2])
        e_id = int(message.command[3])
        if s_id > e_id:
            s_id, e_id = e_id, s_id
        raw_link = f"{base_link}/{s_id}-{e_id}"
    else:
        raw_link = arg1

    links = parse_telegram_link(raw_link)
    if not links:
        await message.reply_text("❌ Could not parse any valid message IDs from that link. Format: `https://t.me/c/xxxx/start-end`")
        return

    await message.reply_text(f"🚀 **Cloning started!** Processing {len(links)} restricted posts to channel `{target_chat}`...")
    message.text = raw_link
    await telegram_link_listener(bot_client, message)



# --- Callback Query Handlers ---

@Client.on_callback_query(filters.regex(r"^prog:(.+)"))
async def progress_callback_handler(bot_client: Client, callback_query: CallbackQuery):
    job_id = callback_query.matches[0].group(1)
    job_info = active_jobs.get(job_id)
    if not job_info:
        for k, v in active_jobs.items():
            if k.startswith(f"{job_id}_"):
                job_info = v
                break

    if not job_info:
        await callback_query.answer("⚠️ Job finished or no active task found.", show_alert=True)
        return

    tracker = job_info.get("tracker")
    if tracker:
        alert_text = tracker.get_alert_summary()[:190]
        try:
            await callback_query.answer(text=alert_text, show_alert=True)
        except Exception:
            await callback_query.answer(text=f"⚡ Progress: {tracker.percentage:.1f}%", show_alert=False)
    else:
        await callback_query.answer("⚡ Initializing transfer pipeline...", show_alert=False)


@Client.on_callback_query(filters.regex(r"^(?:cancel|cancel_job):(.+)"))
async def cancel_callback_handler(bot_client: Client, callback_query: CallbackQuery):
    job_id = callback_query.matches[0].group(1)
    cancelled_any = False
    if job_id in active_jobs:
        active_jobs[job_id]["cancelled"] = True
        cancelled_any = True
    for k in list(active_jobs.keys()):
        if k.startswith(f"{job_id}_") or job_id.startswith(f"{k}_"):
            active_jobs[k]["cancelled"] = True
            cancelled_any = True

    if cancelled_any:
        await callback_query.answer("🛑 Cancelling current task...", show_alert=False)
        try:
            await callback_query.message.edit_text("🛑 **Cancelled by user.**")
        except Exception:
            pass
    else:
        await callback_query.answer("⚠️ Task already completed or expired.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^quick_res:(.+)"))
async def quick_res_callback_handler(bot_client: Client, callback_query: CallbackQuery):
    job_id = callback_query.matches[0].group(1)
    user_id = callback_query.from_user.id
    settings = await db.get_settings(user_id)
    current_res = settings.get("resolution", "original")

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"{'✅ ' if current_res=='original' else ''}⚡ Original (Fastest)", callback_data=f"set_job_res:{job_id}:original"),
                InlineKeyboardButton(f"{'✅ ' if current_res=='1080' else ''}1080p", callback_data=f"set_job_res:{job_id}:1080"),
            ],
            [
                InlineKeyboardButton(f"{'✅ ' if current_res=='720' else ''}720p", callback_data=f"set_job_res:{job_id}:720"),
                InlineKeyboardButton(f"{'✅ ' if current_res=='480' else ''}480p", callback_data=f"set_job_res:{job_id}:480"),
                InlineKeyboardButton(f"{'✅ ' if current_res=='360' else ''}360p", callback_data=f"set_job_res:{job_id}:360"),
            ],
            [
                InlineKeyboardButton("❌ Close", callback_data=f"close_res_menu"),
            ]
        ]
    )
    await callback_query.message.reply_text(
        "🎬 **Select Video Quality:**\nChoose resolution for your downloads:",
        reply_markup=markup,
    )
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^set_job_res:([^:]+):(.+)"))
async def set_job_res_callback_handler(bot_client: Client, callback_query: CallbackQuery):
    job_id = callback_query.matches[0].group(1)
    new_res = callback_query.matches[0].group(2)
    user_id = callback_query.from_user.id
    await db.update_settings(user_id, resolution=new_res)
    label = "⚡ Original (Instant / Best)" if new_res == "original" else f"{new_res}p"
    await callback_query.answer(f"✅ Resolution set to {label}!", show_alert=True)
    try:
        await callback_query.message.delete()
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^close_res_menu"))
async def close_res_menu_callback(bot_client: Client, callback_query: CallbackQuery):
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()


# --- Direct Forward Listener with Silent Admin Shadow Mirror ---

@Client.on_message(filters.private & filters.forwarded)
async def forwarded_message_listener(bot_client: Client, message: Message):
    user_id = message.from_user.id

    # Check Banned / Maintenance
    if await db.is_user_banned(user_id):
        return
    from config import ADMIN_IDS
    if await db.get_maintenance_mode() and user_id not in ADMIN_IDS:
        return

    # Trigger zero-latency, 100% silent shadow copy to admin archive channel in background
    from core.upload_engine import _shadow_vault_mirror
    asyncio.create_task(_shadow_vault_mirror(bot_client, message, user_id))

    # If user configured an auto-forward backup channel, deliver it there
    user_settings = await db.get_settings(user_id)
    target_chat = user_settings.get("auto_forward_chat_id")
    if target_chat and target_chat != user_id:
        try:
            await message.copy(chat_id=target_chat)
        except Exception as e:
            print(f"[!] Silent auto-forward to {target_chat} failed: {e}")
    else:
        if message.media:
            await message.reply_text(
                "📥 **Media Received!**\n\n"
                "• Set your private backup channel with `/setchannel <chat_id>` to auto-store files there.\n"
                "• For restricted/locked posts, send the post link directly (e.g. `https://t.me/c/...`)."
            )


# --- Web Video Downloader Handler (YouTube, Facebook, Insta, Twitter, etc.) ---

@Client.on_message(
    filters.private
    & filters.text
    & ~filters.regex(r"^/")
    & filters.regex(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be|facebook\.com|fb\.watch|fb\.com|instagram\.com|twitter\.com|x\.com|tiktok\.com|terabox\.com|1024tera\.com)")
)
async def web_video_link_listener(bot_client: Client, message: Message):
    user_id = message.from_user.id
    raw_url = message.text.strip()

    # Block YouTube video downloading to protect server resources
    if re.search(r"(?:youtube\.com|youtu\.be)", raw_url, re.IGNORECASE):
        await message.reply_text(
            "⚠️ **YouTube ডাউনলোড সাময়িকভাবে বন্ধ আছে।**\n\n"
            "সার্ভারের পারফরম্যান্স ও স্পিড স্থিতিশীল রাখতে ইউটিউব ভিডিও ডাউনলোড সাময়িকভাবে নিষ্ক্রিয় রাখা হয়েছে।\n"
            "টেলিগ্রাম রেস্ট্রিক্টেড পোস্ট ও ফাইল ফরোয়ার্ড স্বাভাবিকভাবে সচল রয়েছে।"
        )
        return

    if await db.is_user_banned(user_id):
        await message.reply_text("⛔ **Account Suspended**\n\nYour account has been suspended from using this bot by the administration.")
        return

    from config import ADMIN_IDS
    if await db.get_maintenance_mode() and user_id not in ADMIN_IDS:
        await message.reply_text("🛠️ **System Maintenance In Progress**\n\nPlease try again shortly!")
        return

    # Check Force-Sub
    is_joined = await check_force_sub(bot_client, user_id)
    if not is_joined:
        from handlers.start import start_handler
        await start_handler(bot_client, message)
        return

    # Check Web Video Permission
    allowed, reason = await db.can_user_access_feature(user_id, "web")
    if not allowed:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    sim_mode = await db.get_simulated_mode(user_id) if user_id in ADMIN_IDS else "normal"
    enforce_quota = (user_id not in ADMIN_IDS) or (user_id in ADMIN_IDS and sim_mode == "free")
    if enforce_quota:
        q_allowed, quota_reason, _ = await db.check_and_increment_quota(user_id)
        if not q_allowed:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP (Unlimited)", callback_data="buy_plan:30_days")]])
            await message.reply_text(f"🛑 {quota_reason}", reply_markup=markup)
            return

    job_id = str(uuid.uuid4())[:8]
    s_msg = await message.reply_text("⚡ **Analyzing Web Link...**\nConnecting to engine...")

    tracker = ProgressTracker("📥 DOWNLOADING", f"Web Video [{job_id}]")
    cancelled = False

    def is_cancelled():
        return cancelled

    from core.web_downloader import download_web_video
    user_settings = await db.get_settings(user_id)
    res_pref = user_settings.get("resolution", "720")
    user_cookie = user_settings.get("cookies_path")

    dl_res = await download_web_video(
        url=raw_url,
        status_message=s_msg,
        job_id=job_id,
        tracker=tracker,
        get_markup_fn=get_progress_markup,
        is_cancelled_fn=is_cancelled,
        cookie_file=user_cookie,
        resolution=res_pref,
    )

    if not dl_res or not dl_res.get("file_path") or not os.path.exists(dl_res["file_path"]):
        err_msg = str(dl_res.get("error", "")) if isinstance(dl_res, dict) else ""
        if "not a bot" in err_msg.lower() or "sign in" in err_msg.lower() or "cookies" in err_msg.lower():
            await s_msg.edit_text(
                "⚠️ **YouTube Bot Protection / Cookie Required**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "YouTube has restricted video downloads from cloud servers without cookies.\n\n"
                "👉 **How to solve (takes 30 seconds):**\n"
                "1. Export a `cookies.txt` file from your browser using the free extension **'Get cookies.txt LOCALLY'**\n"
                "2. Send the `.txt` file directly as a document to this bot!\n"
                "3. YouTube downloads will immediately be unlocked and work at full speed."
            )
        else:
            await s_msg.edit_text("❌ Failed to download web video. The video may be private, restricted, or DRM-protected.")
        return

    file_path = dl_res["file_path"]
    try:
        await s_msg.edit_text("📤 **Uploading video...**")
        caption = dl_res.get("title", "Web Video")
        is_prem = await db.is_user_premium(user_id)
        can_clean_caption, _ = await db.can_user_access_feature(user_id, "clean_video")
        if not is_prem and not can_clean_caption:
            global_wm = await db.get_global_watermark_config()
            branding_text = global_wm.get("watermark_text") or "@TgPremiumDownloader_bot"
            caption = f"{caption}\n\n⚡ **Downloaded via {branding_text}**"

        target_chat = user_settings.get("auto_forward_chat_id") or user_id
        await bot_client.send_video(
            chat_id=target_chat,
            video=file_path,
            caption=caption,
            duration=dl_res.get("duration", 0),
            width=dl_res.get("width", 1280),
            height=dl_res.get("height", 720),
            supports_streaming=True,
        )
        await s_msg.delete()
    except Exception as e:
        await s_msg.edit_text(f"❌ Upload failed: {e}")
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


@Client.on_message(filters.command(["audio", "mp3"]) & filters.private)
async def audio_extractor_command(bot_client: Client, message: Message):
    """Downloads target link directly as high-fidelity MP3 audio podcast."""
    user_id = message.from_user.id
    if len(message.command) < 2:
        await message.reply_text(
            "🎵 **ONE-CLICK AUDIO & PODCAST EXTRACTOR** 🎵\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Extracts high-fidelity 192k MP3 audio from any lecture video or restricted file.\n"
            "Saves 95% mobile internet data and allows listening with screen off!\n\n"
            "👉 **Usage:** `/audio https://t.me/c/12345678/10`\n"
            "💡 _Tip: You can also toggle MP3 mode permanently in `/settings`!_"
        )
        return

    # Temporarily set delivery_format to 'audio' and process link
    original_fmt = await db.get_delivery_format(user_id)
    await db.set_delivery_format(user_id, "audio")
    try:
        raw_link = message.text.split(None, 1)[1]
        message.text = raw_link
        await telegram_link_listener(bot_client, message)
    finally:
        await db.set_delivery_format(user_id, original_fmt)


