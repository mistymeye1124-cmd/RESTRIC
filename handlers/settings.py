# language: Python, file: handlers/settings.py, target: Python 3.10+, Pyrogram
"""
Enterprise Settings, Resolution Selector, Cookies Uploader, and Promo Code Handlers.
All render functions are extracted so they can be called from both commands and callbacks
with the correct user_id from callback_query.from_user.id.
"""

import os
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import db
from core.i18n import t, get_lang_display
from core.emojis import apply_custom_emojis
from config import BASE_DIR

COOKIES_DIR = BASE_DIR / "cookies"
COOKIES_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────── PURE RENDER FUNCTIONS ──────────────────────────

async def render_settings_card(user_id: int):
    """Returns (text, markup) for the settings menu. Safe to call from any context."""
    settings = await db.get_settings(user_id)
    lang = await db.get_user_language(user_id)
    lang_display = get_lang_display(lang)

    res = settings.get("resolution", "original")
    mode = "Document 📁" if settings.get("upload_as_doc") else "Streamable Video 📹"
    raw_fwd = settings.get("auto_forward_chat_id")
    forward_chat = f"Connected ({raw_fwd})" if raw_fwd else "Disabled (Direct to Chat)"
    caption_preview = settings.get("custom_caption") or "_Original Post Caption_"
    res_display = "⚡ Original (Instant / Best)" if res == "original" else f"{res}p"

    # Delivery Format (Video vs MP3 Audio Podcast)
    delivery_fmt = settings.get("delivery_format", "video")
    fmt_display = "🎵 MP3 Audio" if delivery_fmt == "audio" else "🎬 Video Stream"

    # Ad-Stripper & Clean Caption
    clean_ads = settings.get("clean_caption", 1)
    clean_display = "🟢 ON (Auto-Cleaned)" if clean_ads else "⚪ OFF (Raw Post)"

    # Media Harvest Filter
    media_filter = settings.get("media_filter", "all")
    filter_map = {"all": "📦 All Content", "video": "🎬 Videos Only", "document": "📄 PDFs Only"}
    filter_display = filter_map.get(media_filter, "📦 All Content")

    # Custom Thumbnail Status
    custom_thumb = await db.get_custom_thumbnail(user_id)
    thumb_display = "🟢 Active Custom Poster" if (custom_thumb and os.path.exists(custom_thumb)) else "⚪ Auto Frame"

    # Ghost Mode (Zero-Trace Forensic Scrub)
    ghost_mode = settings.get("ghost_mode", 1)
    ghost_display = "🟢 Active (Zero-Trace / Scrubbed)" if ghost_mode else "⚪ Disabled (Raw Media)"

    # Custom Filename Branding (Prefix/Suffix)
    pfx = settings.get("file_prefix", "") or ""
    sfx = settings.get("file_suffix", "") or ""
    branding_display = f"`{pfx}`...`{sfx}`" if (pfx or sfx) else "⚪ Default Original"

    text = (
        "⚙️ **USER PREFERENCES & CLOUD COCKPIT** ⚙️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **GLOBAL HARVESTER CONFIGURATION**\n\n"
        "┌── 📋 **ACTIVE PARAMETERS** ──────────┐\n"
        f"│ • 👻 Ghost Mode: `{ghost_display}`\n"
        f"│ • 🎯 Auto-Forward: `{forward_chat}`\n"
        f"│ • 🏷️ File Renaming: {branding_display}\n"
        f"│ • 📺 Default Quality: `{res_display}`\n"
        f"│ • 🚀 Delivery Format: `{fmt_display}`\n"
        f"│ • 📹 Video Mode: `{mode}`\n"
        f"│ • ✂️ Strip Competitor Ads: `{clean_display}`\n"
        f"│ • 🎯 Batch Harvest Filter: `{filter_display}`\n"
        f"│ • 🖼️ Custom Thumbnail: `{thumb_display}`\n"
        f"│ • 📝 Custom Caption: `{caption_preview}`\n"
        f"│ • 🌐 Interface Language: `{lang_display}`\n"
        "└──────────────────────────────────────┘\n\n"
        "👇 _Tap any button below to adjust your preferences:_"
    )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"{'✅ ' if res=='original' else ''}⚡ Original", callback_data="set_res:original"),
                InlineKeyboardButton(f"{'✅ ' if res=='1080' else ''}1080p", callback_data="set_res:1080"),
                InlineKeyboardButton(f"{'✅ ' if res=='720' else ''}720p", callback_data="set_res:720"),
            ],
            [
                InlineKeyboardButton(f"👻 Ghost Mode: {'ON 🟢' if ghost_mode else 'OFF ⚪'}", callback_data="toggle_ghost_mode"),
                InlineKeyboardButton(f"✂️ Strip Ads: {'ON 🟢' if clean_ads else 'OFF ⚪'}", callback_data="toggle_clean_ads"),
            ],
            [
                InlineKeyboardButton("🏷️ Filename Prefix/Suffix", callback_data="prompt_prefix_help"),
                InlineKeyboardButton("✂️ Caption & Credit Studio", callback_data="user_view_caption_studio"),
            ],
            [
                InlineKeyboardButton(f"🚀 Format: {fmt_display}", callback_data="toggle_delivery_fmt"),
                InlineKeyboardButton(f"🎯 Filter: {filter_display}", callback_data="cycle_media_filter"),
            ],
            [
                InlineKeyboardButton(f"📹 Player: {'📁 File' if settings.get('upload_as_doc') else '📹 Video Player'}", callback_data="toggle_doc_mode"),
                InlineKeyboardButton("🖼️ Custom Thumbnail Studio", callback_data="user_view_thumbnail"),
            ],
            [
                InlineKeyboardButton("👥 Referral & Earn VIP", callback_data="user_view_referral"),
                InlineKeyboardButton("📢 Auto-Forward Channel", callback_data="prompt_channel_help"),
            ],
            [
                InlineKeyboardButton(f"🌐 Language: {lang_display}", callback_data="user_view_language"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ],
        ]
    )
    return apply_custom_emojis(text), markup


async def render_resolution_card(user_id: int):
    """Returns (text, markup) for the resolution picker. Safe to call from any context."""
    settings = await db.get_settings(user_id)
    res = settings.get("resolution", "original")
    res_display = "⚡ Original Stream (Instant / Best)" if res == "original" else f"📺 {res}p HD"

    text = (
        "📺 **VIDEO RESOLUTION & TRANSCODING SUITE** 📺\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **ADAPTIVE RESOLUTION CONTROLLER**\n\n"
        f"Active Quality: **{res_display}**\n\n"
        "┌── 🎬 **RESOLUTION MATRIX** ───────────┐\n"
        "│ • ⚡ Original: Instant delivery, 0 quality loss\n"
        "│ • 🌟 1080p: Full HD (1920x1080) Pristine\n"
        "│ • 📺 720p: Standard HD (1280x720) Balanced\n"
        "│ • 📱 480p: Mobile SD (854x480) Data Saver\n"
        "│ • 🪶 360p: Ultra Compressed (640x360) Light\n"
        "└──────────────────────────────────────┘\n\n"
        "👇 _Tap below to select your delivery quality:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"{'✅ ' if res=='original' else ''}⚡ Original (Fastest)", callback_data="set_res:original"),
                InlineKeyboardButton(f"{'✅ ' if res=='1080' else ''}🌟 1080p FHD", callback_data="set_res:1080"),
            ],
            [
                InlineKeyboardButton(f"{'✅ ' if res=='720' else ''}📺 720p HD", callback_data="set_res:720"),
                InlineKeyboardButton(f"{'✅ ' if res=='480' else ''}📱 480p SD", callback_data="set_res:480"),
                InlineKeyboardButton(f"{'✅ ' if res=='360' else ''}🪶 360p Mini", callback_data="set_res:360"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Settings", callback_data="user_view_settings"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return apply_custom_emojis(text), markup


async def render_caption_studio(user_id: int):
    """Returns (text, markup) for the Caption & Credit Studio Cockpit."""
    settings = await db.get_settings(user_id)
    clean_ads = settings.get("clean_caption", 1)
    custom_cap = settings.get("custom_caption")
    replacements = await db.get_caption_replacements(user_id)

    clean_status = "🟢 ACTIVE (Stripping Links & Credits)" if clean_ads else "⚪ DISABLED (Original Credits Kept)"

    if custom_cap is None:
        template_display = "📝 Original Caption (Cleaned)" if clean_ads else "📄 Raw Original Caption"
    elif custom_cap.lower() in ("none", "empty", "off", "clear", "0", "no"):
        template_display = "🚫 ZERO CAPTION (Blank / All Captions Removed)"
    else:
        template_display = f"✨ `{custom_cap}`"

    rules_lines = []
    if replacements:
        for idx, (f, r) in enumerate(replacements, 1):
            r_repr = f"`{r}`" if r else "_(Deleted/Empty)_"
            rules_lines.append(f"  {idx}. `{f}` ➔ {r_repr}")
        rules_text = "\n".join(rules_lines)
    else:
        rules_text = "  _(No custom replacement rules set)_"

    text = (
        "✂️ **CAPTION & CREDIT STUDIO COCKPIT** ✂️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Control exactly what text, credit, or branding appears on your forwarded videos.\n\n"
        "┌── 📋 **ACTIVE CAPTION ENGINE** ────────┐\n"
        f"│ • ✂️ Auto-Strip Competitor Ads: `{clean_status}`\n"
        f"│ • 📝 Caption Mode: {template_display}\n"
        "└──────────────────────────────────────┘\n\n"
        f"🔄 **CUSTOM FIND & REPLACE RULES ({len(replacements)}):**\n"
        f"{rules_text}\n\n"
        "⚡ **COMMAND QUICK SHORTCUTS:**\n"
        "• `/setcaption none` ➔ Remove all captions completely (Blank)\n"
        "• `/setcaption 🎬 {title}\\n📢 @MyChannel` ➔ Custom branding template\n"
        "• `/replacecaption @OldChannel | @MyChannel` ➔ Swap channel names\n"
        "• `/replacecaption Join @spam | ` ➔ Remove specific text/ad\n"
        "• `/clearcaption` ➔ Reset template\n"
        "• `/clearreplacements` ➔ Clear all replace rules\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 _Tap below to toggle settings or configure:_"
    )

    buttons = [
        [
            InlineKeyboardButton(
                f"✂️ Strip Credits: {'ON 🟢' if clean_ads else 'OFF ⚪'}",
                callback_data="toggle_caption_clean_ads",
            ),
            InlineKeyboardButton(
                "🚫 Zero Caption" if custom_cap != "none" else "✅ Zero Caption Mode",
                callback_data="set_caption_zero",
            ),
        ],
        [
            InlineKeyboardButton("📝 Set Custom Template", callback_data="caption_help_template"),
            InlineKeyboardButton("🔄 Add Replace Rule", callback_data="caption_help_replace"),
        ],
        [
            InlineKeyboardButton("🗑️ Clear Template", callback_data="caption_action_cleartemplate"),
            InlineKeyboardButton("🗑️ Clear Replace Rules", callback_data="caption_action_clearreplacements"),
        ],
        [
            InlineKeyboardButton("⚙️ Full Settings", callback_data="user_view_settings"),
            InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
        ],
    ]
    markup = InlineKeyboardMarkup(buttons)
    return apply_custom_emojis(text), markup


# ─────────────────────── COMMAND HANDLERS (from /settings /resolution) ──────

@Client.on_message(filters.command("settings") & filters.private)
async def settings_handler(client: Client, message: Message):
    user_id = message.from_user.id
    text, markup = await render_settings_card(user_id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command(["res", "resolution"]) & filters.private)
async def resolution_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    cmd = message.command

    # Allow direct setting via /res 720, /res 480, /res original
    if cmd and len(cmd) > 1:
        choice = cmd[1].strip().lower().replace("p", "")
        valid = {"original", "1080", "720", "480", "360"}
        if choice in valid:
            await db.update_settings(user_id, resolution=choice)
            label = "⚡ Original (Instant / Best Quality)" if choice == "original" else f"{choice}p"
            await message.reply_text(f"✅ **Resolution updated!**\nDefault set to: `{label}`")
            return

    text, markup = await render_resolution_card(user_id)
    await message.reply_text(text, reply_markup=markup)


# ────────────────────────── CALLBACK HANDLERS ───────────────────────────────

@Client.on_callback_query(filters.regex(r"^user_view_settings$"))
async def user_view_settings_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text, markup = await render_settings_card(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^user_view_resolution$"))
async def user_view_resolution_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text, markup = await render_resolution_card(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^set_res:(.+)"))
async def set_res_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    new_res = callback_query.matches[0].group(1)
    if new_res != "original":
        allowed, reason = await db.can_user_access_feature(user_id, "resolution")
        if not allowed:
            await callback_query.answer(reason, show_alert=True)
            return
    await db.update_settings(user_id, resolution=new_res)
    label = "⚡ Original (Fastest)" if new_res == "original" else f"{new_res}p"
    await callback_query.answer(f"Resolution set to {label}!", show_alert=False)
    text, markup = await render_settings_card(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^toggle_doc_mode$"))
async def toggle_doc_mode_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    settings = await db.get_settings(user_id)
    new_mode = not settings.get("upload_as_doc", False)
    await db.update_settings(user_id, upload_as_doc=new_mode)
    label = "📁 Document (Downloaded as File)" if new_mode else "📹 Streamable Video (Native Player with Scrub Bar)"
    await callback_query.answer(f"Delivery mode changed to:\n{label}", show_alert=True)
    text, markup = await render_settings_card(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^(?:user_view_caption_studio|prompt_caption_help)$"))
async def user_view_caption_studio_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    text, markup = await render_caption_studio(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^toggle_caption_clean_ads$"))
async def toggle_caption_clean_ads_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    new_state = await db.toggle_clean_caption(user_id)
    status_label = "ENABLED (Ads & Credits Stripped)" if new_state else "DISABLED (Original Preserved)"
    await callback_query.answer(f"✂️ Strip Credits: {status_label}", show_alert=False)
    text, markup = await render_caption_studio(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^set_caption_zero$"))
async def set_caption_zero_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    settings = await db.get_settings(user_id)
    cur = settings.get("custom_caption")
    if cur == "none":
        # Toggle back to None (restore original)
        await db.update_settings(user_id, custom_caption=None)
        await callback_query.answer("Original caption restored!", show_alert=False)
    else:
        # Set to zero caption mode
        await db.update_settings(user_id, custom_caption="none")
        await callback_query.answer("Zero Caption Mode: All media will have NO caption!", show_alert=True)
    text, markup = await render_caption_studio(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^caption_action_cleartemplate$"))
async def caption_action_cleartemplate_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await db.update_settings(user_id, custom_caption=None)
    await callback_query.answer("Custom template cleared!", show_alert=False)
    text, markup = await render_caption_studio(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^caption_action_clearreplacements$"))
async def caption_action_clearreplacements_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await db.clear_caption_replacements(user_id)
    await callback_query.answer("All text replacement rules cleared!", show_alert=False)
    text, markup = await render_caption_studio(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^caption_help_template$"))
async def caption_help_template_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔙 Back to Caption Studio", callback_data="user_view_caption_studio"),
                InlineKeyboardButton("⚙️ Full Settings", callback_data="user_view_settings"),
            ]
        ]
    )
    help_text = (
        "📝 **HOW TO CONFIGURE CUSTOM CAPTION TEMPLATES:**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Send the command `/setcaption <template>` in chat.\n\n"
        "💡 **Available Dynamic Placeholders:**\n"
        "• `{title}` ➔ Video or file name\n"
        "• `{filename}` ➔ Exact original file name\n"
        "• `{caption}` ➔ Cleaned original message caption\n"
        "• `{size}` ➔ Human-readable file size (e.g. 245.8 MB)\n\n"
        "📌 **Ready Examples to Copy & Send:**\n"
        "1. Minimal Brand:\n"
        "   `/setcaption 🎬 {title}\n📢 @MyChannel`\n\n"
        "2. Clean with Original Text:\n"
        "   `/setcaption {caption}\n\n⚡ Unlocked by @MyChannel`\n\n"
        "3. Complete Caption Removal (Zero Caption):\n"
        "   `/setcaption none`\n\n"
        "👉 To reset back to default: `/clearcaption`"
    )
    try:
        await callback_query.message.edit_text(help_text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^caption_help_replace$"))
async def caption_help_replace_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔙 Back to Caption Studio", callback_data="user_view_caption_studio"),
                InlineKeyboardButton("⚙️ Full Settings", callback_data="user_view_settings"),
            ]
        ]
    )
    help_text = (
        "🔄 **HOW TO SWAP & REPLACE TEXT IN CAPTIONS:**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Use `/replacecaption <find_text> | <replace_with>`\n\n"
        "💡 **Real-World Examples:**\n"
        "• **Change Competitor Channel Name:**\n"
        "  `/replacecaption @CompetitorChannel | @MyVIPChannel`\n\n"
        "• **Remove Ad/Promo Lines Completely:**\n"
        "  `/replacecaption Join @badchannel for daily leaks | `\n\n"
        "• **Replace Target Website Links:**\n"
        "  `/replacecaption t.me/badlink | t.me/mylink`\n\n"
        "📋 **View Active Rules:** `/listreplacements`\n"
        "🗑️ **Delete a Rule:** `/delrule 1`\n"
        "🧹 **Clear All:** `/clearreplacements`"
    )
    try:
        await callback_query.message.edit_text(help_text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^prompt_channel_help$"))
async def prompt_channel_help_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔙 Back to Settings", callback_data="user_view_settings"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    try:
        await callback_query.message.edit_text(
            "📢 **How to Set Auto-Forward Channel:**\n\n"
            "1. Add this bot as an **Admin** in your private backup channel.\n"
            "2. Send: `/setchannel -100XXXXXXXXXX` (your channel ID)\n\n"
            "All unlocked files will automatically be backed up to your channel!",
            reply_markup=markup,
        )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^toggle_delivery_fmt$"))
async def callback_toggle_delivery_fmt(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    current = await db.get_delivery_format(user_id)
    new_fmt = "audio" if current == "video" else "video"
    await db.set_delivery_format(user_id, new_fmt)
    await query.answer(f"🚀 Format: {'MP3 AUDIO (PODCAST)' if new_fmt == 'audio' else 'STREAMABLE VIDEO'}", show_alert=False)
    text, markup = await render_settings_card(user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^toggle_clean_ads$"))
async def callback_toggle_clean_ads(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    new_state = await db.toggle_clean_caption(user_id)
    status_label = "ENABLED (Competitor ads & links removed)" if new_state else "DISABLED (Original ads preserved)"
    await query.answer(f"✂️ Ad-Stripper: {status_label}", show_alert=False)
    text, markup = await render_settings_card(user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^cycle_media_filter$"))
async def callback_cycle_media_filter(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    current = await db.get_media_filter(user_id)
    next_map = {"all": "video", "video": "document", "document": "all"}
    new_filter = next_map.get(current, "all")
    await db.set_media_filter(user_id, new_filter)
    label_map = {"all": "All Media", "video": "Videos Only", "document": "Documents/PDFs Only"}
    await query.answer(f"🎯 Harvest Filter: {label_map.get(new_filter)}", show_alert=False)
    text, markup = await render_settings_card(user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^toggle_ghost_mode$"))
async def callback_toggle_ghost_mode(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    new_state = await db.toggle_ghost_mode(user_id)
    status_label = "ENABLED 🟢 (Zero-Trace EXIF & Bitstream Scrub)" if new_state else "DISABLED ⚪ (Standard Mode)"
    await query.answer(f"👻 Ghost Mode: {status_label}", show_alert=False)
    text, markup = await render_settings_card(user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_message(filters.command("ghost") & filters.private)
async def ghost_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    settings = await db.get_settings(user_id)
    ghost_mode = settings.get("ghost_mode", 1)
    status_str = "🟢 **ACTIVE (Zero-Trace / Forensic Scrub)**" if ghost_mode else "⚪ **DISABLED (Raw Metadata)**"

    text = (
        "👻 **STEALTH GHOST MODE SUITE** 👻\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Status: {status_str}\n\n"
        "┌── 🛡️ **ZERO-TRACE PROTECTIONS** ─────┐\n"
        "│ • 🧼 Wipes Camera Serial, Model, GPS\n"
        "│ • 🚫 Purges Telegram Author & Channel Tags\n"
        "│ • 🔒 Lossless Bitstream Stream Sanitization\n"
        "│ • ⚡ FastStart Web-Streaming Optimization\n"
        "│ • 🕵️ Silent Leeching (No Typing / Read Seen)\n"
        "└──────────────────────────────────────┘\n\n"
        "👇 _Tap below to toggle Ghost Mode:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"👻 Ghost Mode: {'ON 🟢' if ghost_mode else 'OFF ⚪'}",
                    callback_data="toggle_ghost_mode",
                )
            ],
            [
                InlineKeyboardButton("⚙️ Full Settings", callback_data="user_view_settings"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ],
        ]
    )
    await message.reply_text(text=apply_custom_emojis(text), reply_markup=markup)


# ─────────────────── COOKIE MANAGEMENT ──────────────────────────────────────

@Client.on_message(filters.command("cookie") & filters.private)
async def cookie_handler(client: Client, message: Message):
    await message.reply_text(
        "🍪 **Cookie Configuration for Private Web Sources**\n\n"
        "To download videos from private Facebook groups, paid course sites:\n\n"
        "1. Export browser cookies in **Netscape `cookies.txt` format** using _Get cookies.txt LOCALLY_.\n"
        "2. Send the `cookies.txt` file directly as a document to this bot.\n"
        "3. The bot will automatically use your cookies for web video downloads!"
    )


@Client.on_message(filters.document & filters.private)
async def cookie_document_receiver(client: Client, message: Message):
    if not message.document.file_name.lower().endswith((".txt", ".cookie", ".cookies")):
        return
    user_id = message.from_user.id
    os.makedirs(COOKIES_DIR, exist_ok=True)
    target_path = os.path.join(COOKIES_DIR, f"cookie_{user_id}.txt")
    await message.download(file_name=target_path)
    await db.update_settings(user_id, cookies_path=target_path)

    from config import ADMIN_IDS
    import shutil
    if user_id in ADMIN_IDS:
        try:
            shutil.copy(target_path, os.path.join(COOKIES_DIR, "youtube_cookies.txt"))
            shutil.copy(target_path, os.path.join(COOKIES_DIR, "cookies.txt"))
        except Exception:
            pass
        await message.reply_text(
            "👑 **Global System Cookies Installed!**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Cookies have been saved as the **Global Server Cookie** for all bot users.\n"
            "🚀 YouTube and all web video downloads are now unlocked across the bot!"
        )
    else:
        await message.reply_text("✅ **Personal Cookies Saved Successfully!**\nYou can now download from private web sources.")


# ─────────────────── PROMO CODE REDEMPTION ─────────────────────────────────

@Client.on_message(filters.command(["coupon", "redeem", "voucher"]) & filters.private)
async def redeem_coupon_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2:
        await message.reply_text(
            "🎟️ **REDEEM VIP GIVEAWAY CODE** 🎁\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Have a giveaway or promo voucher code? Redeem it now for free VIP days!\n\n"
            "👉 **Usage:** `/redeem <CODE>`\n"
            "💡 **Example:** `/redeem VIP2026`\n\n"
            "_(Type `/redeem` followed by your code and send)_"
        )
        return
    code = message.command[1].strip()
    success, reply = await db.redeem_coupon(user_id, code)
    await message.reply_text(reply)


# ─────────────────── CAPTION & REPLACEMENT COMMANDS ────────────────────────

@Client.on_message(filters.command(["caption", "captions", "credit"]) & filters.private)
async def caption_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    text, markup = await render_caption_studio(user_id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command("setcaption") & filters.private)
async def set_caption_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2:
        help_msg = (
            "📝 **Set Custom Caption Template**\n\n"
            "**Usage:**\n"
            "• Remove all captions completely (Blank / Clean):\n"
            "  `/setcaption none`\n\n"
            "• Custom Channel Branding Template:\n"
            "  `/setcaption 🎬 {title}\n📢 @MyAwesomeChannel`\n\n"
            "• Keep Cleaned Caption with Custom Credit:\n"
            "  `/setcaption {caption}\n\n⚡ Unlocked by @MyChannel`\n\n"
            "**Available Dynamic Placeholders:**\n"
            "• `{title}` - File name or video title\n"
            "• `{filename}` - Exact file name\n"
            "• `{caption}` - Cleaned original caption (without competitor ads)\n"
            "• `{size}` - Formatted file size\n\n"
            "👉 To reset back to default: `/clearcaption`\n"
            "👉 Open Caption Studio Cockpit: `/caption`"
        )
        await message.reply_text(help_msg)
        return

    custom_text = message.text.split(None, 1)[1].strip()
    if custom_text.lower() in ("none", "empty", "off", "clear", "0", "no"):
        await db.update_settings(user_id, custom_caption="none")
        await message.reply_text("🚫 **Zero Caption Mode Enabled!**\nAll downloaded and forwarded media will now be delivered with **no caption** (completely clean and blank).")
    else:
        await db.update_settings(user_id, custom_caption=custom_text)
        await message.reply_text(
            f"✅ **Custom Caption Template Saved!**\n\n"
            f"**Preview Template:**\n`{custom_text}`\n\n"
            f"_Tip: Competitor links and promo credits will be automatically removed according to your settings!_"
        )


@Client.on_message(filters.command(["clearcaption", "resetcaption"]) & filters.private)
async def clear_caption_handler(client: Client, message: Message):
    user_id = message.from_user.id
    await db.update_settings(user_id, custom_caption=None)
    await message.reply_text("🔄 **Caption Cleared!**\nVideos will now preserve the original source post caption (with competitor credits automatically cleaned if Strip Credits is ON).")


@Client.on_message(filters.command(["replacecaption", "captionreplace", "replace"]) & filters.private)
async def replace_caption_handler(client: Client, message: Message):
    user_id = message.from_user.id
    full_text = message.text.split(None, 1)
    if len(full_text) < 2:
        help_msg = (
            "🔄 **Find & Replace Caption Text Tool**\n\n"
            "Automatically replace competitor names, links, or phrases with your own channel branding!\n\n"
            "**Format:**\n"
            "`/replacecaption <find_text> | <replace_with>`\n\n"
            "**Examples:**\n"
            "• Swap competitor with your channel:\n"
            "  `/replacecaption @OldChannel | @MyCoolChannel`\n\n"
            "• Remove competitor promo phrase:\n"
            "  `/replacecaption Join @badchannel for more | `\n\n"
            "• Replace link:\n"
            "  `/replacecaption t.me/badchannel | t.me/mychannel`\n\n"
            "📋 To view all rules: `/listreplacements`\n"
            "🧹 To clear all rules: `/clearreplacements`"
        )
        await message.reply_text(help_msg)
        return

    arg_str = full_text[1].strip()
    if "|" in arg_str:
        parts = arg_str.split("|", 1)
        find_t = parts[0].strip()
        rep_t = parts[1].strip()
    elif ":::" in arg_str:
        parts = arg_str.split(":::", 1)
        find_t = parts[0].strip()
        rep_t = parts[1].strip()
    else:
        find_t = arg_str
        rep_t = ""

    if not find_t:
        await message.reply_text("❌ Please specify the text to find and replace.")
        return

    rules = await db.add_caption_replacement(user_id, find_t, rep_t)
    rep_display = f"`{rep_t}`" if rep_t else "_(Removed completely)_"
    await message.reply_text(
        f"✅ **Replacement Rule Saved!**\n\n"
        f"🔍 **Find:** `{find_t}`\n"
        f"🔄 **Replace with:** {rep_display}\n\n"
        f"📊 **Active Rules Count:** `{len(rules)}`\n"
        f"_All incoming captions will now apply this rule automatically!_"
    )


@Client.on_message(filters.command(["listreplacements", "replacements"]) & filters.private)
async def list_replacements_handler(client: Client, message: Message):
    user_id = message.from_user.id
    rules = await db.get_caption_replacements(user_id)
    if not rules:
        await message.reply_text(
            "📋 **No active replacement rules.**\n\n"
            "Add a rule using:\n"
            "`/replacecaption @OldChannel | @MyChannel`"
        )
        return

    lines = ["🔄 **ACTIVE CAPTION REPLACEMENT RULES:**\n"]
    for idx, (f, r) in enumerate(rules, 1):
        r_str = f"`{r}`" if r else "_(Removed)_"
        lines.append(f"{idx}. `{f}` ➔ {r_str}")
    lines.append("\n• Delete a rule: `/delrule <number>`\n• Clear all: `/clearreplacements`")
    await message.reply_text("\n".join(lines))


@Client.on_message(filters.command(["delrule", "delreplacement", "removerule"]) & filters.private)
async def delete_replacement_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2 or not message.command[1].isdigit():
        await message.reply_text("Usage: `/delrule 1` (number of the rule from `/listreplacements`)")
        return
    idx = int(message.command[1]) - 1
    rules = await db.remove_caption_replacement(user_id, idx)
    await message.reply_text(f"✅ Rule deleted. `{len(rules)}` active rule(s) remaining.")


@Client.on_message(filters.command(["clearreplacements", "resetreplacements"]) & filters.private)
async def clear_replacements_handler(client: Client, message: Message):
    user_id = message.from_user.id
    await db.clear_caption_replacements(user_id)
    await message.reply_text("🗑️ **All caption replacement rules cleared!**")


@Client.on_message(filters.command("setchannel") & filters.private)
async def set_channel_handler(client: Client, message: Message):
    user_id = message.from_user.id
    allowed, reason = await db.can_user_access_feature(user_id, "forward")
    if not allowed:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    if len(message.command) < 2:
        help_text = (
            "📢 **Auto-Forward Target Channel Setup**\n\n"
            "Send your destination channel ID:\n"
            "👉 `/setchannel -1001234567890`\n\n"
            "Or remove auto-forwarding:\n"
            "👉 `/clearchannel`\n\n"
            "_Note: Make sure this bot is an Admin in the target channel._"
        )
        await message.reply_text(help_text)
        return

    arg = message.command[1].strip()
    if arg.lower() in ("clear", "none", "off", "remove", "0"):
        await db.update_settings(user_id, auto_forward_chat_id=None)
        await message.reply_text("✅ Auto-forward destination disabled. Files will be sent to your private chat only.")
        return

    try:
        target_id = int(arg)
        bot_is_admin = False
        bot_username = "TgPremiumDownlaoder_bot"
        try:
            bot_me = await client.get_me()
            bot_username = bot_me.username or bot_username
            bot_member = await client.get_chat_member(target_id, "me")
            if bot_member and bot_member.status in ("administrator", "creator"):
                bot_is_admin = True
        except Exception:
            bot_is_admin = False

        await db.update_settings(user_id, auto_forward_chat_id=target_id)

        if bot_is_admin:
            msg_text = (
                "✅ **Auto-forward channel configured & verified!**\n\n"
                f"📢 **Target Chat ID:** `{target_id}`\n"
                "🛡️ **Bot Admin Status:** 🟢 Verified (Ready to Post)\n\n"
                "Downloaded files will now automatically mirror to this channel!\n"
                "💡 To disable auto-forwarding anytime, send `/clearchannel`."
            )
        else:
            msg_text = (
                "⚠️ **Target Channel Saved, BUT Action Required!**\n\n"
                f"📢 **Target Chat ID:** `{target_id}`\n\n"
                f"🚨 **The bot (@{bot_username}) is NOT an Admin in this channel yet!**\n\n"
                "Telegram will **block** the bot from forwarding files until you add it:\n"
                f"1. Open your channel (`{target_id}`) ➔ **Channel Settings / Manage Channel**.\n"
                f"2. Go to **Administrators** ➔ **Add Administrator**.\n"
                f"3. Search for `@{bot_username}` and add it with **Post Messages** permission.\n\n"
                "Once added as Admin, all downloads will automatically mirror to your channel!"
            )
        await message.reply_text(msg_text)
    except ValueError:
        await message.reply_text("❌ Invalid channel ID. Must be a numeric channel ID like `-1001234567890`.")


@Client.on_message(filters.command(["clearchannel", "removechannel"]) & filters.private)
async def clear_channel_handler(client: Client, message: Message):
    user_id = message.from_user.id
    await db.update_settings(user_id, auto_forward_chat_id=None)
    await message.reply_text("✅ Auto-forward destination removed. Files will be sent directly to your private chat.")


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_command_handler(client: Client, message: Message):
    from core.download_engine import active_jobs
    cancelled_count = 0
    for jid, job in list(active_jobs.items()):
        job["cancelled"] = True
        cancelled_count += 1
    if cancelled_count > 0:
        await message.reply_text(f"🛑 Cancelled {cancelled_count} active task(s).")
    else:
        await message.reply_text("ℹ️ No active download tasks running.")


@Client.on_message(filters.command(["prefix", "setprefix"]) & filters.private)
async def set_prefix_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2:
        s = await db.get_settings(user_id)
        curr = s.get("file_prefix", "") or "_None_"
        await message.reply_text(
            "🏷️ **Custom Filename Prefix**\n\n"
            f"• Current Prefix: `{curr}`\n\n"
            "Prepend your channel or brand name to every downloaded file!\n\n"
            "👉 **Usage:** `/setprefix [MyChannel] `\n"
            "👉 **Example:** `/setprefix [ACS Vault] `\n"
            "👉 **Reset:** `/clearprefix`"
        )
        return
    prefix_val = message.text.split(None, 1)[1]
    await db.update_settings(user_id, file_prefix=prefix_val)
    await message.reply_text(f"✅ **Filename Prefix set to:** `{prefix_val}`\n\nExample file: `{prefix_val}Lecture_01.mp4`")


@Client.on_message(filters.command(["suffix", "setsuffix"]) & filters.private)
async def set_suffix_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2:
        s = await db.get_settings(user_id)
        curr = s.get("file_suffix", "") or "_None_"
        await message.reply_text(
            "🏷️ **Custom Filename Suffix**\n\n"
            f"• Current Suffix: `{curr}`\n\n"
            "Append your channel or brand name right before the file extension!\n\n"
            "👉 **Usage:** `/setsuffix  - @MyChannel`\n"
            "👉 **Example:** `/setsuffix  [1080p]`\n"
            "👉 **Reset:** `/clearsuffix`"
        )
        return
    suffix_val = message.text.split(None, 1)[1]
    await db.update_settings(user_id, file_suffix=suffix_val)
    await message.reply_text(f"✅ **Filename Suffix set to:** `{suffix_val}`\n\nExample file: `Lecture_01{suffix_val}.mp4`")


@Client.on_message(filters.command(["clearprefix", "clearsuffix", "delprefix"]) & filters.private)
async def clear_prefix_suffix_handler(client: Client, message: Message):
    user_id = message.from_user.id
    await db.update_settings(user_id, file_prefix="", file_suffix="")
    await message.reply_text("🗑️ **Custom filename prefix and suffix cleared!** Original filenames restored.")


@Client.on_callback_query(filters.regex(r"^prompt_prefix_help$"))
async def prompt_prefix_help_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    s = await db.get_settings(user_id)
    curr_p = s.get("file_prefix", "") or "_None_"
    curr_s = s.get("file_suffix", "") or "_None_"
    text = (
        "🏷️ **CUSTOM FILENAME PREFIX & SUFFIX STUDIO**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Brand your channel name directly on the filename of every downloaded video & PDF!\n\n"
        f"• **Current Prefix:** `{curr_p}`\n"
        f"• **Current Suffix:** `{curr_s}`\n\n"
        "💡 **Commands to Configure:**\n"
        "• Add Prefix: `/setprefix [MyChannel] `\n"
        "• Add Suffix: `/setsuffix  - @MyChannel`\n"
        "• Reset Both: `/clearprefix`"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Settings", callback_data="user_view_settings")]
    ])
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
