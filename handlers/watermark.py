# language: Python, file: handlers/watermark.py, target: Python 3.10+, Pyrogram
"""
Enterprise Video Branding & Watermarking Studio (World-Class Edition):
- Text badges, Lecture Top Headline banners, PNG transparent logo overlays
- Anti-Leak & Anti-Theft Dynamic Moving / Bouncing Watermark motion
- Custom Intro Bumper & Outro Closing video concatenation
- Opacity slider, Font size picker, Dynamic badge styling
- Instant 1-second Live Sample Preview generator
"""

import os
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import db
from core.state_manager import set_user_state, get_user_state, clear_user_state
from core.watermark_engine import generate_watermark_preview, generate_delogo_preview

# Ensure branding asset directory exists
BRANDING_DIR = Path("downloads") / "branding"
BRANDING_DIR.mkdir(parents=True, exist_ok=True)

POS_LABELS = {
    "bottom_right": "↘️ Bottom Right",
    "bottom_left": "↙️ Bottom Left",
    "top_right": "↗️ Top Right",
    "top_left": "↖️ Top Left",
    "center": "⏺️ Center Screen",
    "moving": "🔄 Dynamic Anti-Crop Moving (এদিক-ওদিক যাবে)",
    "floating": "🔄 Dynamic Anti-Crop Moving (এদিক-ওদিক যাবে)",
}

BOUNCE_SPEED_LABELS = {
    1: "🦥 1x Slow Drift",
    2: "🐢 2x Relaxed",
    3: "⚡ 3x Normal (Default)",
    4: "🚀 4x Fast Bounce",
    5: "🌪️ 5x Ultra Turbo",
}

DELOGO_POS_LABELS = {
    "top_right": "↗️ Top Right (উপরে ডানে)",
    "top_left": "↖️ Top Left (উপরে বামে)",
    "bottom_right": "↘️ Bottom Right (নিচে ডানে)",
    "bottom_left": "↙️ Bottom Left (নিচে বামে)",
    "center": "⏺️ Center (মাঝখানে)",
}

DELOGO_SIZE_LABELS = {
    "small": "🔹 Small (180x60)",
    "medium": "🔷 Medium (240x80)",
    "large": "🔶 Large (320x110)",
    "xlarge": "🛑 Extra Large (420x150)",
}


async def render_watermark_dashboard(user_id: int):
    """Generates the world-class watermark dashboard text and inline keyboard."""
    can_wm, _ = await db.can_user_access_feature(user_id, "custom_wm")
    if not can_wm:
        global_cfg = await db.get_global_watermark_config()
        brand_name = global_cfg.get("watermark_text", "@TgPremiumDownloader_bot")
        text = (
            "🎬 **VIDEO WATERMARK & BRANDING ENGINE**\n\n"
            f"• **Current Tier:** Free Tier\n"
            f"• **Default Branding:** `{brand_name}` (Burned on all free downloads)\n\n"
            "💎 **Upgrade to VIP Premium to Unlock:**\n"
            "✅ **100% Watermark Removal:** Get completely clean original videos!\n"
            "✅ **Custom Watermark Text:** Burn your own channel/brand name onto videos!\n"
            "✅ **Lecture Headline Banners:** Add professional top title banners!\n"
            "✅ **Custom Logo Overlays:** Burn transparent PNG/JPG badges!\n"
            "✅ **Intro & Outro Bumper Clips:** Add channel intro & outro videos!\n"
            "✅ **Anti-Crop Dynamic Moving Mode:** Watermark floats to defeat crop bots!\n"
            "✅ **Bounce Speed Control:** Choose 1x Slow to 5x Turbo bounce speed!\n\n"
            "👉 Tap below to upgrade to VIP or return to the main menu:"
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("💎 Upgrade to VIP (Custom Watermark)", callback_data="user_view_premium"),
                ],
                [
                    InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main"),
                ]
            ]
        )
        return text, markup

    # VIP Premium User
    wm_settings = await db.get_watermark_settings(user_id)
    enabled = bool(wm_settings.get("enabled", 0))
    delogo_enabled = bool(wm_settings.get("delogo_enabled", 0))
    delogo_pos = wm_settings.get("delogo_position", "top_right")
    delogo_size = wm_settings.get("delogo_size", "medium")
    delogo_pos_str = DELOGO_POS_LABELS.get(delogo_pos, delogo_pos)
    delogo_size_str = DELOGO_SIZE_LABELS.get(delogo_size, delogo_size)

    status_str = "🟢 ACTIVE (Burning Brand)" if enabled else "🔴 DISABLED (⚡ Turbo Pass — Clean Video)"
    delogo_status_str = f"🟢 ACTIVE ({delogo_pos_str})" if delogo_enabled else "🔴 DISABLED"
    pipeline_str = "🎬 High-Definition Hardware Encoder" if (enabled or delogo_enabled) else "⚡ Ultra Turbo Pass (0-Second Delay / Clean Video)"

    wm_text = wm_settings.get("watermark_text") or "_None_"
    hl_text = wm_settings.get("headline_text") or "_None_"
    logo_path = wm_settings.get("logo_path", "")
    intro_path = wm_settings.get("intro_clip_path", "")
    outro_path = wm_settings.get("outro_clip_path", "")
    pos = wm_settings.get("position", "bottom_right")
    font_size = wm_settings.get("font_size", 24)
    opacity_pct = int(float(wm_settings.get("opacity", 0.8)) * 100)
    style = str(wm_settings.get("style", "pill")).capitalize()
    bounce_speed = int(wm_settings.get("bounce_speed", 3))

    bg_color = wm_settings.get("bg_color", "black")
    bg_op = float(wm_settings.get("bg_opacity", 0.75))
    bg_opacity_pct = int(bg_op * 100)
    text_color = wm_settings.get("text_color", "white").capitalize()

    BG_LABELS = {
        "black": "⬛ Midnight Black",
        "navy": "🟦 Deep Navy",
        "red": "🟥 Crimson Red",
        "purple": "🟪 Deep Purple",
        "green": "🟩 Emerald Green",
        "gold": "🟨 Amber Gold",
        "white": "⚪ Frost White",
        "none": "🚫 Transparent (No Box)",
        "transparent": "🚫 Transparent (No Box)",
    }
    bg_display = BG_LABELS.get(bg_color, bg_color.capitalize())

    pos_str = POS_LABELS.get(pos, pos)
    speed_str = BOUNCE_SPEED_LABELS.get(bounce_speed, f"{bounce_speed}x")

    active_modes = []
    if wm_text and wm_text != "_None_":
        active_modes.append("Text Badge")
    if hl_text and hl_text != "_None_":
        active_modes.append("Headline Bar")
    if logo_path and os.path.exists(logo_path):
        active_modes.append("PNG Logo")
    if intro_path and os.path.exists(intro_path):
        active_modes.append("Intro Clip")
    if outro_path and os.path.exists(outro_path):
        active_modes.append("Outro Clip")
    if delogo_enabled:
        active_modes.append("🧹 Watermark Remover")
    mode_str = " + ".join(active_modes) if active_modes else "Standard"

    is_raw_mode = await db.get_raw_mode()
    raw_notice = (
        "⚡ **NOTICE: Ultra-Fast Pure Raw Mode is ACTIVE by Admin** ⚡\n"
        "All media is delivered directly in pure 1:1 original format with 0 delay.\n"
        "Custom watermarks are temporarily bypassed, but your settings remain safely saved.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    ) if is_raw_mode else ""

    text = (
        raw_notice +
        "🎬 **ENTERPRISE VIDEO BRANDING STUDIO PRO** 🎬\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **DYNAMIC WATERMARK & BRANDING ENGINE**\n\n"
        "┌── 🎛️ **STUDIO ENGINE STATE** ────────┐\n"
        f"│ • Bot Watermark: `{status_str}`\n"
        f"│ • 🧹 Watermark Remover: `{delogo_status_str}`\n"
        f"│ • Video Pipeline: `{pipeline_str}`\n"
        f"│ • Active Elements: `🎨 {mode_str if (enabled or delogo_enabled) else '⚪ None (Bypassed)'}`\n"
        f"│ • Badge Styling: `✨ {style if enabled else '⚡ Clean Original Pass'}`\n"
        "└──────────────────────────────────────┘\n\n"
        "📐 **ACTIVE BRANDING MATRIX:**\n"
        f"• 🧹 **100% Watermark Removal:** {'🟢 Active [' + delogo_pos_str + ' | ' + delogo_size_str + ']' if delogo_enabled else '⚪ Disabled'}\n"
        f"• ✏️ **Brand Text:** `{wm_text}`\n"
        f"• 🔲 **Text Background:** `{bg_display}` ({bg_opacity_pct}% Box Opacity)\n"
        f"• 🎨 **Text Color:** `{text_color}`\n"
        f"• 📰 **Top Headline:** `{hl_text}`\n"
        f"• 🖼️ **Brand Logo:** {'🟢 Active PNG' if logo_path and os.path.exists(logo_path) else '⚪ None'}\n"
        f"• 🎬 **Intro Bumper:** {'🟢 Attached Video' if intro_path and os.path.exists(intro_path) else '⚪ None'}\n"
        f"• 🏁 **Outro Closing:** {'🟢 Attached Video' if outro_path and os.path.exists(outro_path) else '⚪ None'}\n"
        f"• 📍 **Placement:** `{pos_str}`\n"
        f"• 🏃 **Bounce Speed:** `{speed_str}`\n"
        f"• 🔅 **Transparency:** `{opacity_pct}%` | 📐 **Font Scale:** `{font_size}px`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 _Tip: ওয়াটারমার্ক OFF রাখলে ১০০% ক্লিন ওরিজিনাল ভিডিও পাবেন। আর ভিডিওর আগের লোগো মুছতে নিচের 🧹 Watermark Removal বাটনে চাপুন!_"
    )

    toggle_btn = (
        InlineKeyboardButton("🟢 Bot Watermark: ON (Tap to Turn OFF ⚡)", callback_data="wm_toggle_status")
        if enabled
        else InlineKeyboardButton("🔴 Bot Watermark: OFF (⚡ Clean Original)", callback_data="wm_toggle_status")
    )

    delogo_btn = (
        InlineKeyboardButton(
            f"🧹 100% Watermark Removal: {'🟢 ACTIVE' if delogo_enabled else '🔴 OFF'} (Config)",
            callback_data="wm_view_delogo",
        )
    )

    markup = InlineKeyboardMarkup(
        [
            [
                toggle_btn,
            ],
            [
                delogo_btn,
            ],
            [
                InlineKeyboardButton("✏️ Text", callback_data="wm_prompt_text"),
                InlineKeyboardButton("📰 Headline", callback_data="wm_prompt_headline"),
                InlineKeyboardButton("🖼️ Logo", callback_data="wm_prompt_logo"),
            ],
            [
                InlineKeyboardButton("🔲 Text Background (বক্স)", callback_data="wm_change_bg"),
                InlineKeyboardButton("🎨 Text Color (রং)", callback_data="wm_change_textcolor"),
            ],
            [
                InlineKeyboardButton("🎬 Intro Clip", callback_data="wm_prompt_intro"),
                InlineKeyboardButton("🏁 Outro Clip", callback_data="wm_prompt_outro"),
                InlineKeyboardButton("📍 Position", callback_data="wm_change_pos"),
            ],
            [
                InlineKeyboardButton("🏃 Bounce Speed (গতি বাড়াও/কমাও)", callback_data="wm_change_speed"),
            ],
            [
                InlineKeyboardButton("🔅 Opacity", callback_data="wm_change_opacity"),
                InlineKeyboardButton("📐 Scale", callback_data="wm_change_size"),
                InlineKeyboardButton("🎨 Style Preset", callback_data="wm_change_style"),
            ],
            [
                InlineKeyboardButton("👁️ Generate Live Preview Sample (HD)", callback_data="wm_live_preview"),
            ],
            [
                InlineKeyboardButton("🗑️ Clear All", callback_data="wm_clear_all"),
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return text, markup


async def render_delogo_dashboard(user_id: int):
    """Renders the dedicated 100% Watermark Removal & Video Delogo Studio."""
    can_clean, _ = await db.can_user_access_feature(user_id, "clean_video")
    is_prem = await db.is_user_premium(user_id)
    if not (is_prem or can_clean):
        text = (
            "🧹 **100% WATERMARK REMOVAL & VIDEO DELOGO STUDIO**\n\n"
            "💎 **This is a VIP Premium Exclusive Feature!**\n\n"
            "যেকোনো ভিডিও থেকে আগের চ্যানেল নেম, লোগো, বা ওয়াটারমার্ক সম্পূর্ণ মুছে ফেলে ফ্রেশ এবং ক্লিয়ার ওরিজিনাল ভিডিও পেতে VIP আপগ্রেড করুন।"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")],
            [InlineKeyboardButton("🔙 Back to Studio", callback_data="wm_back_to_studio")],
        ])
        return text, markup

    wm_settings = await db.get_watermark_settings(user_id)
    delogo_enabled = bool(wm_settings.get("delogo_enabled", 0))
    delogo_pos = wm_settings.get("delogo_position", "top_right")
    delogo_size = wm_settings.get("delogo_size", "medium")

    pos_display = DELOGO_POS_LABELS.get(delogo_pos, delogo_pos)
    size_display = DELOGO_SIZE_LABELS.get(delogo_size, delogo_size)
    status_display = "🟢 ACTIVE (Erasing Watermarks)" if delogo_enabled else "🔴 DISABLED (No Removal)"

    text = (
        "🧹 **100% WATERMARK REMOVAL & VIDEO DELOGO STUDIO** 🧹\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ভিডিওর মধ্যে থাকা আগের লোগো, চ্যানেল আইডি বা টিচারের ওয়াটারমার্ক স্মার্ট Delogo ইন্টারপোলেশন অ্যালগরিদমে সম্পূর্ণ মুছে ফেলুন।\n\n"
        "┌── 🎛️ **REMOVER ENGINE CONFIG** ──────┐\n"
        f"│ • Remover Status: `{status_display}`\n"
        f"│ • Target Erase Area: `{pos_display}`\n"
        f"│ • Eraser Box Size: `{size_display}`\n"
        f"│ • Audio Quality: `⚡ 1:1 Direct Stream Copy (No Loss)`\n"
        "└──────────────────────────────────────┘\n\n"
        "🎯 **পজিশন ও সাইজ কীভাবে নির্বাচন করবেন:**\n"
        "1️⃣ **পজিশন সিলেক্ট করুন:** ভিডিওর যে কোণায় লোগোটি আছে সেটি সিলেক্ট করুন (যেমন: ↗️ Top Right)।\n"
        "2️⃣ **সাইজ পরিবর্তন করুন:** লোগো অনুযায়ী `Small`, `Medium`, `Large` বা `Extra Large` সিলেক্ট করুন।\n"
        "3️⃣ **লাইভ টেস্ট করুন:** নিচে `👁️ Test Delogo Live Preview` তে ক্লিক করে ৩-সেকেন্ডের ডেমো ভিডিও দেখে নিন!\n\n"
        "💡 _টিপ: বট ওয়াটারমার্ক OFF থাকলে এবং রিমুভার ON থাকলে ভিডিও সম্পূর্ণ ফ্রেশ ও ক্লিয়ার হবে!_"
    )

    toggle_btn = (
        InlineKeyboardButton("🟢 Watermark Remover: ON (Tap to Turn OFF)", callback_data="wm_toggle_delogo")
        if delogo_enabled
        else InlineKeyboardButton("🔴 Watermark Remover: OFF (Tap to Turn ON)", callback_data="wm_toggle_delogo")
    )

    p_tl = "✅ ↖️ Top Left" if delogo_pos == "top_left" else "↖️ Top Left"
    p_tr = "✅ ↗️ Top Right" if delogo_pos == "top_right" else "↗️ Top Right"
    p_bl = "✅ ↙️ Bottom Left" if delogo_pos == "bottom_left" else "↙️ Bottom Left"
    p_br = "✅ ↘️ Bottom Right" if delogo_pos == "bottom_right" else "↘️ Bottom Right"
    p_ce = "✅ ⏺️ Center" if delogo_pos == "center" else "⏺️ Center"

    markup = InlineKeyboardMarkup([
        [toggle_btn],
        [
            InlineKeyboardButton(p_tl, callback_data="wm_set_delogo_pos:top_left"),
            InlineKeyboardButton(p_tr, callback_data="wm_set_delogo_pos:top_right"),
        ],
        [
            InlineKeyboardButton(p_bl, callback_data="wm_set_delogo_pos:bottom_left"),
            InlineKeyboardButton(p_br, callback_data="wm_set_delogo_pos:bottom_right"),
        ],
        [
            InlineKeyboardButton(p_ce, callback_data="wm_set_delogo_pos:center"),
        ],
        [
            InlineKeyboardButton(f"📐 Eraser Size: {size_display} 🔄", callback_data="wm_cycle_delogo_size"),
        ],
        [
            InlineKeyboardButton("👁️ Test Delogo Live Preview (3s Sample)", callback_data="wm_delogo_preview"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Branding Studio", callback_data="wm_back_to_studio"),
        ],
    ])
    return text, markup


@Client.on_message(filters.command(["setup", "watermark"]) & filters.private)
async def setup_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    text, markup = await render_watermark_dashboard(user_id)
    if hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except Exception:
            pass
    await message.reply_text(text, reply_markup=markup)


# =========================================================================
# 1. TEXT & HEADLINE PROMPTS
# =========================================================================

@Client.on_callback_query(filters.regex(r"^wm_prompt_text$"))
async def wm_prompt_text_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    set_user_state(user_id, "waiting_user_wm")

    text = (
        "✏️ **ENTER CUSTOM WATERMARK TEXT**\n\n"
        "Send the text you want burned into your downloaded videos.\n\n"
        "**Examples:**\n"
        "• `@MyTelegramChannel`\n"
        "• `ACS Class Vault`\n"
        "• `Unlocked by John`\n\n"
        "👉 _Send your text now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_prompt_headline$"))
async def wm_prompt_headline_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    set_user_state(user_id, "waiting_user_hl")

    text = (
        "📰 **ENTER TOP LECTURE HEADLINE BANNER**\n\n"
        "Send the lecture title or headline to display at the top of the video.\n\n"
        "**Examples:**\n"
        "• `Chemistry 2nd Paper - Chapter 3`\n"
        "• `Higher Math Calculus Masterclass`\n\n"
        "👉 _Send your headline text now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Remove Headline", callback_data="wm_remove_headline"),
                InlineKeyboardButton("❌ Cancel", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_remove_headline$"))
async def wm_remove_headline_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await db.update_watermark_settings(user_id, headline_text="")
    await callback_query.answer("Headline banner removed!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


# =========================================================================
# 2. LOGO UPLOADER & MANAGEMENT
# =========================================================================

@Client.on_callback_query(filters.regex(r"^wm_prompt_logo$"))
async def wm_prompt_logo_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    set_user_state(user_id, "waiting_user_logo")

    wm = await db.get_watermark_settings(user_id)
    has_logo = bool(wm.get("logo_path") and os.path.exists(wm.get("logo_path")))

    buttons = []
    if has_logo:
        buttons.append([InlineKeyboardButton("🗑️ Remove Current Logo", callback_data="wm_remove_logo")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="user_view_watermark")])

    text = (
        "🖼️ **UPLOAD CHANNEL LOGO (PNG/JPG)**\n\n"
        "Send your channel logo as a **Photo** or **Document (PNG with transparency recommended)**.\n\n"
        "• **Auto-Scale:** The engine automatically resizes your logo to fit perfectly in the corner without blocking the video!\n"
        "• **Opacity & Position:** You can adjust transparency and position anytime from the menu.\n\n"
        "👉 _Send your logo image now, or tap Cancel:_"
    )
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex(r"^wm_remove_logo$"))
async def wm_remove_logo_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    wm = await db.get_watermark_settings(user_id)
    old_logo = wm.get("logo_path")
    if old_logo and os.path.exists(old_logo):
        try:
            os.remove(old_logo)
        except Exception:
            pass
    await db.update_watermark_settings(user_id, logo_path="")
    await callback_query.answer("Logo removed!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


# =========================================================================
# 3. INTRO & OUTRO BUMPER VIDEO CLIPS
# =========================================================================

@Client.on_callback_query(filters.regex(r"^wm_prompt_intro$"))
async def wm_prompt_intro_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    set_user_state(user_id, "waiting_user_intro")

    wm = await db.get_watermark_settings(user_id)
    has_intro = bool(wm.get("intro_clip_path") and os.path.exists(wm.get("intro_clip_path")))

    buttons = []
    if has_intro:
        buttons.append([InlineKeyboardButton("🗑️ Remove Intro Clip", callback_data="wm_remove_intro")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="user_view_watermark")])

    text = (
        "🎬 **ATTACH CHANNEL INTRO CLIP**\n\n"
        "Send a short video clip (3 to 10 seconds, under 25MB).\n"
        "The engine will automatically prepend this intro to the start of all your downloaded videos!\n\n"
        "• **Smart Standardization:** Whatever resolution your downloaded videos are in, the intro will automatically scale and match perfectly.\n\n"
        "👉 _Send your intro video clip now, or tap Cancel:_"
    )
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex(r"^wm_remove_intro$"))
async def wm_remove_intro_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    wm = await db.get_watermark_settings(user_id)
    old_clip = wm.get("intro_clip_path")
    if old_clip and os.path.exists(old_clip):
        try:
            os.remove(old_clip)
        except Exception:
            pass
    await db.update_watermark_settings(user_id, intro_clip_path="")
    await callback_query.answer("Intro clip removed!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_prompt_outro$"))
async def wm_prompt_outro_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    set_user_state(user_id, "waiting_user_outro")

    wm = await db.get_watermark_settings(user_id)
    has_outro = bool(wm.get("outro_clip_path") and os.path.exists(wm.get("outro_clip_path")))

    buttons = []
    if has_outro:
        buttons.append([InlineKeyboardButton("🗑️ Remove Outro Clip", callback_data="wm_remove_outro")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="user_view_watermark")])

    text = (
        "🏁 **ATTACH CHANNEL OUTRO CLIP**\n\n"
        "Send a short closing video clip (e.g. Subscribe to channel / Join VIP, under 25MB).\n"
        "The engine will automatically append this outro to the very end of your videos!\n\n"
        "👉 _Send your outro video clip now, or tap Cancel:_"
    )
    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex(r"^wm_remove_outro$"))
async def wm_remove_outro_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    wm = await db.get_watermark_settings(user_id)
    old_clip = wm.get("outro_clip_path")
    if old_clip and os.path.exists(old_clip):
        try:
            os.remove(old_clip)
        except Exception:
            pass
    await db.update_watermark_settings(user_id, outro_clip_path="")
    await callback_query.answer("Outro clip removed!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


# =========================================================================
# 4. POSITION, OPACITY, SIZE, AND BADGE STYLES
# =========================================================================

@Client.on_callback_query(filters.regex(r"^wm_change_pos$"))
async def wm_change_pos_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    text = (
        "📍 **SELECT WATERMARK BADGE POSITION**\n\n"
        "• **Corner / Center:** Fixed position on the video.\n"
        "• **🔄 Dynamic Anti-Crop Moving:** The watermark smoothly moves and bounces across the entire screen, making it impossible for anyone to crop or blur out your brand!\n\n"
        "🏃 _Tip: After choosing Moving, you can control the bounce speed (Slow/Normal/Fast/Turbo) anytime from the Bounce Speed menu!_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Dynamic Anti-Crop Moving (এদিক-ওদিক যাবে)", callback_data="wm_set_pos:moving"),
            ],
            [
                InlineKeyboardButton("🏃 Bounce Speed Control (গতি নিয়ন্ত্রণ)", callback_data="wm_change_speed"),
            ],
            [
                InlineKeyboardButton("↘️ Bottom Right", callback_data="wm_set_pos:bottom_right"),
                InlineKeyboardButton("↙️ Bottom Left", callback_data="wm_set_pos:bottom_left"),
            ],
            [
                InlineKeyboardButton("↗️ Top Right", callback_data="wm_set_pos:top_right"),
                InlineKeyboardButton("↖️ Top Left", callback_data="wm_set_pos:top_left"),
            ],
            [
                InlineKeyboardButton("⏺️ Center Screen", callback_data="wm_set_pos:center"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Watermark Setup", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_set_pos:(.+)"))
async def wm_set_pos_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    new_pos = callback_query.matches[0].group(1)
    await db.update_watermark_settings(user_id, position=new_pos, enabled=1)
    pos_display = POS_LABELS.get(new_pos, new_pos)
    await callback_query.answer(f"Position set to: {pos_display}", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


# =========================================================================
# 4.1 BOUNCE SPEED CONTROLS (SPEED UP / SLOW DOWN)
# =========================================================================

@Client.on_callback_query(filters.regex(r"^wm_change_speed$"))
async def wm_change_speed_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()

    wm_settings = await db.get_watermark_settings(user_id)
    current_speed = int(wm_settings.get("bounce_speed", 3))

    def mark(lvl: int, label: str):
        return f"🔘 {label}" if current_speed == lvl else label

    text = (
        "🏃 **DYNAMIC WATERMARK BOUNCE SPEED CONTROL**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ওয়াটারমার্ক স্ক্রিনের এদিক-ওদিক ভেসে যাওয়ার স্পিড এখান থেকে বাড়াতে বা কমাতে পারেন:\n\n"
        f"• **Active Bounce Speed:** `{BOUNCE_SPEED_LABELS.get(current_speed, f'{current_speed}x')}`\n\n"
        "💡 **Speed Descriptions:**\n"
        "• **🦥 1x Slow Drift:** একদম ধীরেসুস্থে শান্তভাবে ভেসে চলবে (24s cycle)\n"
        "• **🐢 2x Relaxed:** মসৃণ আরামদায়ক গতি (18s cycle)\n"
        "• **⚡ 3x Normal:** স্ট্যান্ডার্ড অপটিমাল ব্যালেন্স (12s cycle - Default)\n"
        "• **🚀 4x Fast Bounce:** দ্রুত বাউন্স করবে, অ্যান্টি-ক্রপ সিকিউরিটি (7s cycle)\n"
        "• **🌪️ 5x Ultra Turbo:** সুপার ফাস্ট বাউন্স (4s cycle - Anti-Theft Leak Shield)\n\n"
        "👉 নিচের যেকোনো স্পিড বাটনে ট্যাপ করে গতি সেট করুন:"
    )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(mark(1, "🦥 1x Slow Drift"), callback_data="wm_set_speed:1"),
                InlineKeyboardButton(mark(2, "🐢 2x Relaxed"), callback_data="wm_set_speed:2"),
            ],
            [
                InlineKeyboardButton(mark(3, "⚡ 3x Normal (Default)"), callback_data="wm_set_speed:3"),
            ],
            [
                InlineKeyboardButton(mark(4, "🚀 4x Fast Bounce"), callback_data="wm_set_speed:4"),
                InlineKeyboardButton(mark(5, "🌪️ 5x Ultra Turbo"), callback_data="wm_set_speed:5"),
            ],
            [
                InlineKeyboardButton("🔄 Set Position: Moving", callback_data="wm_set_pos:moving"),
                InlineKeyboardButton("👁️ Live Preview (HD)", callback_data="wm_live_preview"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Studio", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_set_speed:(\d+)$"))
async def wm_set_speed_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return

    speed_val = int(callback_query.matches[0].group(1))
    speed_val = max(1, min(5, speed_val))

    # Automatically set position to moving and enable watermark when adjusting bounce speed
    await db.update_watermark_settings(user_id, bounce_speed=speed_val, position="moving", enabled=1)

    speed_name = BOUNCE_SPEED_LABELS.get(speed_val, f"{speed_val}x")
    await callback_query.answer(f"✅ Bounce Speed set to: {speed_name}!", show_alert=True)

    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_change_opacity$"))
async def wm_change_opacity_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    text = (
        "🔅 **SELECT WATERMARK & LOGO OPACITY (TRANSPARENCY)**\n\n"
        "Select how transparent or solid your watermark and logo should appear:\n\n"
        "• **100%:** Completely solid, highly visible.\n"
        "• **85%:** Recommended optimal clarity without distraction.\n"
        "• **50%:** Semi-transparent, subtle watermark watermark.\n"
        "• **30%:** Very light, faint security background stamp."
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("100% (Solid)", callback_data="wm_set_op:1.0"),
                InlineKeyboardButton("85% (Optimal ⭐)", callback_data="wm_set_op:0.85"),
            ],
            [
                InlineKeyboardButton("70% (Balanced)", callback_data="wm_set_op:0.70"),
                InlineKeyboardButton("50% (Semi-Transparent)", callback_data="wm_set_op:0.50"),
            ],
            [
                InlineKeyboardButton("30% (Faint Stamp)", callback_data="wm_set_op:0.30"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Setup", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_set_op:([\d\.]+)"))
async def wm_set_op_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    val = float(callback_query.matches[0].group(1))
    await db.update_watermark_settings(user_id, opacity=val, enabled=1)
    await callback_query.answer(f"Opacity set to {int(val * 100)}%!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_change_size$"))
async def wm_change_size_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    text = (
        "📐 **SELECT WATERMARK FONT SIZE**\n\n"
        "Choose the badge text size for your videos:"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("18px (Small)", callback_data="wm_set_size:18"),
                InlineKeyboardButton("24px (Normal ⭐)", callback_data="wm_set_size:24"),
            ],
            [
                InlineKeyboardButton("30px (Medium)", callback_data="wm_set_size:30"),
                InlineKeyboardButton("38px (Large)", callback_data="wm_set_size:38"),
            ],
            [
                InlineKeyboardButton("46px (Extra Large)", callback_data="wm_set_size:46"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Setup", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_set_size:(\d+)"))
async def wm_set_size_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    size = int(callback_query.matches[0].group(1))
    await db.update_watermark_settings(user_id, font_size=size, enabled=1)
    await callback_query.answer(f"Font size set to {size}px!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_change_style$"))
async def wm_change_style_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    text = (
        "🎨 **SELECT BADGE DESIGN & COLOR STYLE**\n\n"
        "Choose the visual aesthetic for your watermark badge:\n\n"
        "• **💊 Modern Pill:** Rounded dark translucent box with crisp white text.\n"
        "• **💡 Neon Cyan:** Cyberpunk neon cyan glow badge.\n"
        "• **👑 Luxury Gold:** Premium metallic gold text badge.\n"
        "• **✨ Minimal Shadow:** Text with deep drop-shadow (no background box)."
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💊 Modern Pill Badge", callback_data="wm_set_style:pill"),
                InlineKeyboardButton("💡 Neon Cyan", callback_data="wm_set_style:neon"),
            ],
            [
                InlineKeyboardButton("👑 Luxury Gold", callback_data="wm_set_style:golden"),
                InlineKeyboardButton("✨ Minimal Shadow", callback_data="wm_set_style:minimal"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Setup", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_set_style:(.+)"))
async def wm_set_style_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    style_key = callback_query.matches[0].group(1)
    await db.update_watermark_settings(user_id, style=style_key, enabled=1)
    await callback_query.answer(f"Badge style set to {style_key.title()}!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


# =========================================================================
# 4.1 TEXT BACKGROUND & TEXT COLOR CUSTOMIZATION
# =========================================================================

@Client.on_callback_query(filters.regex(r"^wm_change_bg$"))
async def wm_change_bg_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    wm_settings = await db.get_watermark_settings(user_id)
    cur_bg = wm_settings.get("bg_color", "black")
    bg_op = int(float(wm_settings.get("bg_opacity", 0.75)) * 100)

    text = (
        "🔲 **SELECT WATERMARK TEXT BACKGROUND BOX** 🔲\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Choose the background badge box color behind your text:\n\n"
        f"• **Current Box:** `{cur_bg.upper()}` ({bg_op}% Opacity)\n\n"
        "• ⬛ **Midnight Black:** High contrast, reads clearly on any video frame\n"
        "• 🟦 **Deep Navy:** Dark corporate cinematic badge\n"
        "• 🟥 **Crimson Red:** Bold, high-energy badge\n"
        "• 🟪 **Deep Purple:** Modern luxury neon aesthetic\n"
        "• 🟩 **Emerald Green:** Cyber / Matrix tech look\n"
        "• 🟨 **Amber Gold:** Elite VIP metallic badge\n"
        "• ⚪ **Frost White:** Semi-translucent light plate\n"
        "• 🚫 **Transparent:** No background box (Text with outline & drop-shadow only)\n\n"
        "👇 _Tap below to pick your text background:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"{'✅ ' if cur_bg=='black' else ''}⬛ Black", callback_data="wm_set_bg:black"),
                InlineKeyboardButton(f"{'✅ ' if cur_bg=='navy' else ''}🟦 Navy", callback_data="wm_set_bg:navy"),
                InlineKeyboardButton(f"{'✅ ' if cur_bg=='red' else ''}🟥 Red", callback_data="wm_set_bg:red"),
            ],
            [
                InlineKeyboardButton(f"{'✅ ' if cur_bg=='purple' else ''}🟪 Purple", callback_data="wm_set_bg:purple"),
                InlineKeyboardButton(f"{'✅ ' if cur_bg=='green' else ''}🟩 Green", callback_data="wm_set_bg:green"),
                InlineKeyboardButton(f"{'✅ ' if cur_bg=='gold' else ''}🟨 Gold", callback_data="wm_set_bg:gold"),
            ],
            [
                InlineKeyboardButton(f"{'✅ ' if cur_bg=='white' else ''}⚪ White", callback_data="wm_set_bg:white"),
                InlineKeyboardButton(f"{'✅ ' if cur_bg in ('none', 'transparent') else ''}🚫 Transparent (No Box)", callback_data="wm_set_bg:none"),
            ],
            [
                InlineKeyboardButton(f"📊 Box Opacity: {bg_op}% (ঘনত্ব)", callback_data="wm_change_bg_opacity"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Studio", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_set_bg:(.+)"))
async def wm_set_bg_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    bg_key = callback_query.matches[0].group(1).lower()
    new_style = "minimal" if bg_key in ("none", "transparent") else "pill"
    await db.update_watermark_settings(user_id, bg_color=bg_key, style=new_style, enabled=1)
    label = "Transparent (No Box)" if bg_key in ("none", "transparent") else bg_key.title()
    await callback_query.answer(f"Text Background set to {label}!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_change_bg_opacity$"))
async def wm_change_bg_opacity_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    text = (
        "📊 **SELECT BACKGROUND BOX OPACITY**\n\n"
        "Control how transparent or solid the background badge box is behind your text:"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("100% (Solid)", callback_data="wm_set_bg_op:1.0"),
                InlineKeyboardButton("85% (Strong)", callback_data="wm_set_bg_op:0.85"),
            ],
            [
                InlineKeyboardButton("75% (Balanced ⭐)", callback_data="wm_set_bg_op:0.75"),
                InlineKeyboardButton("50% (Frosted Glass)", callback_data="wm_set_bg_op:0.50"),
            ],
            [
                InlineKeyboardButton("25% (Subtle)", callback_data="wm_set_bg_op:0.25"),
                InlineKeyboardButton("0% (Invisible / None)", callback_data="wm_set_bg_op:0.0"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Background Menu", callback_data="wm_change_bg"),
                InlineKeyboardButton("🔙 Studio Setup", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_set_bg_op:([\d\.]+)"))
async def wm_set_bg_op_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    val = float(callback_query.matches[0].group(1))
    await db.update_watermark_settings(user_id, bg_opacity=val, enabled=1)
    await callback_query.answer(f"Box Opacity set to {int(val * 100)}%!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_change_textcolor$"))
async def wm_change_textcolor_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer()
    wm_settings = await db.get_watermark_settings(user_id)
    cur_tc = wm_settings.get("text_color", "white").lower()

    text = (
        "🎨 **SELECT WATERMARK TEXT COLOR**\n\n"
        "Choose the font color for your watermark text:"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"{'✅ ' if cur_tc=='white' else ''}⚪ Crisp White", callback_data="wm_set_tc:white"),
                InlineKeyboardButton(f"{'✅ ' if cur_tc in ('yellow', 'gold') else ''}🟡 Amber Gold", callback_data="wm_set_tc:yellow"),
            ],
            [
                InlineKeyboardButton(f"{'✅ ' if cur_tc in ('cyan', 'neon') else ''}🔵 Neon Cyan", callback_data="wm_set_tc:cyan"),
                InlineKeyboardButton(f"{'✅ ' if cur_tc=='green' else ''}🟢 Matrix Green", callback_data="wm_set_tc:green"),
            ],
            [
                InlineKeyboardButton(f"{'✅ ' if cur_tc=='red' else ''}🔴 Coral Red", callback_data="wm_set_tc:red"),
                InlineKeyboardButton(f"{'✅ ' if cur_tc=='pink' else ''}🟣 Electric Pink", callback_data="wm_set_tc:pink"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Studio", callback_data="user_view_watermark"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_set_tc:(.+)"))
async def wm_set_tc_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    tc_key = callback_query.matches[0].group(1).lower()
    await db.update_watermark_settings(user_id, text_color=tc_key, enabled=1)
    await callback_query.answer(f"Text Color set to {tc_key.title()}!", show_alert=False)
    text, markup = await render_watermark_dashboard(user_id)
    await callback_query.message.edit_text(text, reply_markup=markup)


# =========================================================================
# DIRECT COMMAND HANDLERS (/setwm, /setwmbg, /setwmcolor, /clearwm, /wm)
# =========================================================================

@Client.on_message(filters.command(["setup", "wm", "watermark", "branding"]) & filters.private)
async def wm_command_alias_handler(client: Client, message: Message):
    user_id = message.from_user.id
    text, markup = await render_watermark_dashboard(user_id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command(["setwm", "setwatermark"]) & filters.private)
async def set_wm_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    can_wm, reason = await db.can_user_access_feature(user_id, "custom_wm")
    if not can_wm:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    if len(message.command) < 2:
        await message.reply_text(
            "✏️ **Set Custom Video Watermark**\n\n"
            "**Usage:**\n"
            "• Simple text: `/setwm @MyChannel`\n"
            "• Background box: `/setwmbg navy`\n"
            "• Text color: `/setwmcolor gold`\n\n"
            "👉 Open Visual Studio: `/watermark`"
        )
        return

    wm_text = message.text.split(None, 1)[1].strip()
    await db.update_watermark_settings(user_id, watermark_text=wm_text, enabled=1)
    await message.reply_text(
        f"✅ **Watermark Saved & Activated!**\n\n"
        f"• **Text:** `{wm_text}`\n"
        f"• **Status:** Active on all video downloads 🟢\n\n"
        f"_Use `/watermark` to change background box, font size, or position._"
    )


@Client.on_message(filters.command(["setwmbg", "wmbg"]) & filters.private)
async def set_wm_bg_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    can_wm, reason = await db.can_user_access_feature(user_id, "custom_wm")
    if not can_wm:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    if len(message.command) < 2:
        await message.reply_text(
            "🔲 **Set Watermark Text Background**\n\n"
            "**Usage:** `/setwmbg <color>`\n\n"
            "**Available Colors:**\n"
            "• `black` - Midnight black (high contrast)\n"
            "• `navy` - Deep navy blue\n"
            "• `red` - Crimson bold red\n"
            "• `purple` - Luxury deep purple\n"
            "• `green` - Emerald green\n"
            "• `gold` - Amber gold\n"
            "• `white` - Frost white\n"
            "• `transparent` - No background box (transparent)\n\n"
            "Example: `/setwmbg navy`"
        )
        return

    bg_arg = message.command[1].strip().lower()
    valid_bgs = {"black", "navy", "red", "purple", "green", "gold", "white", "transparent", "none"}
    if bg_arg not in valid_bgs:
        await message.reply_text(f"❌ Invalid color. Choose from: `{', '.join(sorted(valid_bgs))}`")
        return

    new_style = "minimal" if bg_arg in ("none", "transparent") else "pill"
    await db.update_watermark_settings(user_id, bg_color=bg_arg, style=new_style, enabled=1)
    label = "Transparent (No Box)" if bg_arg in ("none", "transparent") else bg_arg.title()
    await message.reply_text(f"✅ Watermark Text Background set to: **{label}**")


@Client.on_message(filters.command(["setwmcolor", "wmcolor"]) & filters.private)
async def set_wm_color_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    can_wm, reason = await db.can_user_access_feature(user_id, "custom_wm")
    if not can_wm:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    if len(message.command) < 2:
        await message.reply_text(
            "🎨 **Set Watermark Text Color**\n\n"
            "**Usage:** `/setwmcolor <color>`\n"
            "Colors: `white`, `yellow`, `gold`, `cyan`, `green`, `red`, `pink`\n\n"
            "Example: `/setwmcolor gold`"
        )
        return

    tc_arg = message.command[1].strip().lower()
    await db.update_watermark_settings(user_id, text_color=tc_arg, enabled=1)
    await message.reply_text(f"✅ Watermark Text Color set to: **{tc_arg.title()}**")


@Client.on_message(filters.command(["clearwm", "delwm", "removewm"]) & filters.private)
async def clear_wm_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    await db.update_watermark_settings(user_id, watermark_text="", enabled=0)
    await message.reply_text("🗑️ **Watermark cleared and deactivated.**\n\n_ভিডিও এখন ফুল স্পিডে কোনো ওয়াটারমার্ক ছাড়া ডাউনলোড হবে।_")


@Client.on_message(filters.command(["wmon", "enablewm"]) & filters.private)
async def wm_on_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    can_wm, reason = await db.can_user_access_feature(user_id, "custom_wm")
    if not can_wm:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    await db.update_watermark_settings(user_id, enabled=1)
    await message.reply_text(
        "🟢 **Video Watermark Activated (ON)**\n\n"
        "• আপনার কাস্টম ওয়াটারমার্ক এখন সব ভিডিও ডাউনলোড/ক্লোনিংয়ে বার্ন হবে।\n"
        "• ওয়াটারমার্ক স্টুডিও: `/watermark`\n"
        "• সুপার ফাস্ট স্পিডের জন্য ওয়াটারমার্ক বন্ধ করতে: `/wmoff`"
    )


@Client.on_message(filters.command(["wmoff", "disablewm"]) & filters.private)
async def wm_off_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    can_wm, reason = await db.can_user_access_feature(user_id, "custom_wm")
    if not can_wm:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    await db.update_watermark_settings(user_id, enabled=0)
    await message.reply_text(
        "🔴 **Video Watermark Deactivated (OFF) — ⚡ Ultra Turbo Speed Activated**\n\n"
        "• **Zero-FFmpeg Bypass:** কোনো রিকোড বা ওয়াটারমার্কিং প্রসেস হবে না, সরাসরি অরিজিনাল কোয়ালিটিতে সুপার ফাস্ট ডাউনলোড হবে।\n"
        "• **Zero-Second Cloud Delivery:** অলরেডি ক্যাশে থাকা ভিডিও ০ সেকেন্ডেই ইনস্ট্যান্ট সেন্ড হবে!\n"
        "• পুনরায় ওয়াটারমার্ক চালু করতে: `/wmon`\n"
        "• ওয়াটারমার্ক স্টুডিও: `/watermark`"
    )


@Client.on_message(filters.command(["wmtoggle", "togglewm"]) & filters.private)
async def wm_toggle_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    can_wm, reason = await db.can_user_access_feature(user_id, "custom_wm")
    if not can_wm:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")]])
        await message.reply_text(reason, reply_markup=markup)
        return

    current = await db.get_watermark_settings(user_id)
    new_state = 0 if current.get("enabled", 0) else 1
    await db.update_watermark_settings(user_id, enabled=new_state)

    if new_state:
        await message.reply_text("🟢 **Watermark Enabled (ON)**\n\nভিডিওতে কাস্টম ওয়াটারমার্ক বার্ন হবে। বন্ধ করতে: `/wmoff`")
    else:
        await message.reply_text("🔴 **Watermark Disabled (OFF) — ⚡ Ultra Turbo Speed Pass**\n\nভিডিও কোনো ডিলে ছাড়া সুপার ফাস্ট স্পিডে ডাউনলোড হবে। চালু করতে: `/wmon`")


# =========================================================================
# 5. LIVE PREVIEW SAMPLE GENERATOR
# =========================================================================

@Client.on_callback_query(filters.regex(r"^wm_live_preview$"))
async def wm_live_preview_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return
    await callback_query.answer("⚡ Generating high-speed live preview sample...", show_alert=False)

    wm_settings = await db.get_watermark_settings(user_id)
    preview_target = str(BRANDING_DIR / f"preview_{user_id}.mp4")

    # Generate 3-second sample
    preview_path = await generate_watermark_preview(user_id, wm_settings, preview_target)

    if preview_path and os.path.exists(preview_path):
        caption = (
            "👁️ **LIVE WATERMARK PREVIEW SAMPLE (3s HD)**\n\n"
            f"• Position: `{wm_settings.get('position', 'bottom_right')}`\n"
            f"• Opacity: `{int(float(wm_settings.get('opacity', 0.85)) * 100)}%`\n"
            f"• Font Size: `{wm_settings.get('font_size', 24)}px`\n"
            f"• Style: `{str(wm_settings.get('style', 'pill')).title()}`\n\n"
            "👉 _Your downloaded videos will look exactly like this!_"
        )
        try:
            await client.send_video(
                chat_id=user_id,
                video=preview_path,
                caption=caption,
            )
            # Remove preview sample after sending
            os.remove(preview_path)
        except Exception as e:
            await callback_query.message.reply_text(f"❌ Failed to send preview: {e}")
    else:
        await callback_query.message.reply_text("❌ Could not generate sample preview. Please ensure FFmpeg is functioning.")


# =========================================================================
# 6. TOGGLE STATUS & CLEAR ALL
# =========================================================================

@Client.on_callback_query(filters.regex(r"^wm_toggle_status$"))
async def wm_toggle_status_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_user_premium(user_id):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return

    current = await db.get_watermark_settings(user_id)
    new_state = 0 if current.get("enabled", 0) else 1
    await db.update_watermark_settings(user_id, enabled=new_state)

    if new_state:
        state_str = "🟢 Watermark Activated (ON)! Videos will now be branded."
    else:
        state_str = "🔴 Watermark Deactivated (OFF)! ⚡ Ultra Turbo Speed Pass active (Zero Delay & Clean Video)."
    await callback_query.answer(state_str, show_alert=True)

    text, markup = await render_watermark_dashboard(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_clear_all$"))
async def wm_clear_all_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await db.clear_watermark_settings(user_id)
    await callback_query.answer("Watermark reset! Videos will now be 100% clean original.", show_alert=True)
    text, markup = await render_watermark_dashboard(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


# =========================================================================
# 6.5 DELOGO & 100% WATERMARK REMOVAL CONTROLS
# =========================================================================

@Client.on_callback_query(filters.regex(r"^wm_view_delogo$"))
async def wm_view_delogo_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    text, markup = await render_delogo_dashboard(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_back_to_studio$"))
async def wm_back_to_studio_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    text, markup = await render_watermark_dashboard(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_toggle_delogo$"))
async def wm_toggle_delogo_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    can_clean, _ = await db.can_user_access_feature(user_id, "clean_video")
    if not (await db.is_user_premium(user_id) or can_clean):
        await callback_query.answer("VIP only feature.", show_alert=True)
        return

    current = await db.get_watermark_settings(user_id)
    new_state = 0 if current.get("delogo_enabled", 0) else 1
    await db.update_watermark_settings(user_id, delogo_enabled=new_state)

    if new_state:
        state_str = "🟢 100% Watermark Remover ON! Source logos will be erased."
    else:
        state_str = "🔴 Watermark Remover OFF! Videos processed normally."
    await callback_query.answer(state_str, show_alert=True)

    text, markup = await render_delogo_dashboard(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_set_delogo_pos:(.+)"))
async def wm_set_delogo_pos_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    pos = callback_query.matches[0].group(1)
    await db.update_watermark_settings(user_id, delogo_position=pos)
    pos_lbl = DELOGO_POS_LABELS.get(pos, pos)
    await callback_query.answer(f"Erase Position: {pos_lbl}")

    text, markup = await render_delogo_dashboard(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_cycle_delogo_size$"))
async def wm_cycle_delogo_size_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    current = await db.get_watermark_settings(user_id)
    curr_size = current.get("delogo_size", "medium")
    cycle_order = ["small", "medium", "large", "xlarge"]
    idx = cycle_order.index(curr_size) if curr_size in cycle_order else 1
    next_size = cycle_order[(idx + 1) % len(cycle_order)]
    await db.update_watermark_settings(user_id, delogo_size=next_size)

    size_lbl = DELOGO_SIZE_LABELS.get(next_size, next_size)
    await callback_query.answer(f"Eraser Box Size: {size_lbl}")

    text, markup = await render_delogo_dashboard(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^wm_delogo_preview$"))
async def wm_delogo_preview_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer("Generating 3-Second Live Delogo HD Preview... ⏳", show_alert=False)

    import time
    wm_settings = await db.get_watermark_settings(user_id)
    preview_path = str(BRANDING_DIR / f"delogo_prev_{user_id}_{int(time.time())}.mp4")

    # Force delogo to be enabled in preview config so user sees removal action
    test_cfg = dict(wm_settings)
    test_cfg["delogo_enabled"] = 1

    out_file = await generate_delogo_preview(preview_path, test_cfg)
    if out_file and os.path.exists(out_file) and os.path.getsize(out_file) > 0:
        pos_lbl = DELOGO_POS_LABELS.get(test_cfg.get("delogo_position", "top_right"))
        size_lbl = DELOGO_SIZE_LABELS.get(test_cfg.get("delogo_size", "medium"))
        cap = (
            "🧹 **100% WATERMARK REMOVAL LIVE PREVIEW (3s SAMPLE)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Erase Target:** `{pos_lbl}`\n"
            f"• **Box Dimension:** `{size_lbl}`\n"
            "• **Status:** Cleanly Erased & Inpainted!\n\n"
            "💡 _ভিডিওর আসল লোগোর মাপ বড় বা ছোট হলে স্টুডিও থেকে সাইজ পরিবর্তন করতে পারবেন।_"
        )
        try:
            await client.send_video(
                chat_id=user_id,
                video=out_file,
                caption=cap,
            )
            try:
                os.remove(out_file)
            except Exception:
                pass
        except Exception as e:
            await callback_query.message.reply_text(f"❌ Failed to send preview: {e}")
    else:
        await callback_query.message.reply_text("❌ Could not render delogo preview. Please try again.")


# =========================================================================
# 7. INCOMING MESSAGE INTERCEPTORS (TEXT, PHOTO, VIDEO)
# =========================================================================

@Client.on_message(filters.text & filters.private, group=-1)
async def state_input_interceptor(client: Client, message: Message):
    user_id = message.from_user.id
    state_info = get_user_state(user_id)
    if not state_info:
        return

    state = state_info.get("state")
    user_text = message.text.strip() if message.text else ""

    # Command escape
    if user_text.startswith("/"):
        clear_user_state(user_id)
        if user_text.lower() in ("/cancel", "/cancel@tgpremiumdownlaoder_bot"):
            await message.reply_text("❌ Action cancelled.")
            text, markup = await render_watermark_dashboard(user_id)
            await message.reply_text(text, reply_markup=markup)
            message.stop_propagation()
            return
        return

    if user_text.lower() == "cancel":
        clear_user_state(user_id)
        await message.reply_text("❌ Action cancelled.")
        text, markup = await render_watermark_dashboard(user_id)
        await message.reply_text(text, reply_markup=markup)
        message.stop_propagation()
        return

    # Handle User Custom Watermark Text
    if state == "waiting_user_wm":
        clear_user_state(user_id)
        await db.update_watermark_settings(user_id, watermark_text=user_text, enabled=1)
        await message.reply_text(f"✅ **Watermark Text Saved!**\nNew text: `{user_text}`\nWatermarking is now **Enabled**.")
        text, markup = await render_watermark_dashboard(user_id)
        await message.reply_text(text, reply_markup=markup)
        message.stop_propagation()
        return

    # Handle User Top Lecture Headline Banner
    if state == "waiting_user_hl":
        clear_user_state(user_id)
        await db.update_watermark_settings(user_id, headline_text=user_text, enabled=1)
        await message.reply_text(f"✅ **Lecture Headline Saved!**\nNew banner: `{user_text}`\nWatermarking is now **Enabled**.")
        text, markup = await render_watermark_dashboard(user_id)
        await message.reply_text(text, reply_markup=markup)
        message.stop_propagation()
        return


@Client.on_message((filters.photo | filters.document) & filters.private, group=-1)
async def logo_media_interceptor(client: Client, message: Message):
    """Captures uploaded PNG/JPG logos when in waiting_user_logo state."""
    if not message.from_user:
        message.continue_propagation()
        return
    user_id = message.from_user.id
    state_info = get_user_state(user_id)
    if not state_info or state_info.get("state") != "waiting_user_logo":
        message.continue_propagation()
        return

    clear_user_state(user_id)
    status_msg = await message.reply_text("📥 Saving channel logo...")

    target_logo_path = str(BRANDING_DIR / f"{user_id}_logo.png")

    try:
        downloaded = await client.download_media(message, file_name=target_logo_path)
        if downloaded and os.path.exists(downloaded):
            await db.update_watermark_settings(user_id, logo_path=downloaded, enabled=1)
            await status_msg.edit_text("✅ **Channel Logo Saved & Activated!**\nYour logo will now appear in your chosen position.")
        else:
            await status_msg.edit_text("❌ Failed to download logo image.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Error saving logo: {e}")

    text, markup = await render_watermark_dashboard(user_id)
    await message.reply_text(text, reply_markup=markup)
    message.stop_propagation()


@Client.on_message((filters.video | filters.document | filters.animation) & filters.private, group=-1)
async def intro_outro_media_interceptor(client: Client, message: Message):
    """Captures uploaded Intro & Outro bumper video clips."""
    if not message.from_user:
        message.continue_propagation()
        return
    user_id = message.from_user.id
    state_info = get_user_state(user_id)
    if not state_info:
        message.continue_propagation()
        return

    state = state_info.get("state")
    if state not in ("waiting_user_intro", "waiting_user_outro"):
        message.continue_propagation()
        return

    clear_user_state(user_id)

    is_intro = state == "waiting_user_intro"
    action_label = "Intro Bumper Clip" if is_intro else "Outro Closing Clip"
    filename = f"{user_id}_intro.mp4" if is_intro else f"{user_id}_outro.mp4"
    target_path = str(BRANDING_DIR / filename)

    status_msg = await message.reply_text(f"📥 Downloading and saving {action_label}...")

    try:
        downloaded = await client.download_media(message, file_name=target_path)
        if downloaded and os.path.exists(downloaded):
            if is_intro:
                await db.update_watermark_settings(user_id, intro_clip_path=downloaded, enabled=1)
            else:
                await db.update_watermark_settings(user_id, outro_clip_path=downloaded, enabled=1)
            await status_msg.edit_text(f"✅ **{action_label} Saved & Activated!**\nIt will now be automatically added to all your videos.")
        else:
            await status_msg.edit_text(f"❌ Failed to download video clip.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Error saving {action_label}: {e}")

    text, markup = await render_watermark_dashboard(user_id)
    await message.reply_text(text, reply_markup=markup)
    message.stop_propagation()


# =========================================================================
# 8. DIRECT COMMAND SHORTCUTS
# =========================================================================

@Client.on_message(filters.command("setwatermark") & filters.private)
async def set_watermark_text_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not await db.is_user_premium(user_id):
        await message.reply_text("💎 Custom watermarking is a VIP feature. Use `/premium` to upgrade!")
        return

    if len(message.command) < 2:
        await message.reply_text("Usage: `/setwatermark @YourChannel`")
        return

    text_to_set = message.text.split(None, 1)[1].strip()
    await db.update_watermark_settings(user_id, watermark_text=text_to_set, enabled=1)
    await message.reply_text(f"✅ Watermark text set to: `{text_to_set}` (Watermarking Enabled)")


@Client.on_message(filters.command("setheadline") & filters.private)
async def set_headline_text_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not await db.is_user_premium(user_id):
        await message.reply_text("💎 Lecture headline banner is a VIP feature. Use `/premium` to upgrade!")
        return

    if len(message.command) < 2:
        await message.reply_text("Usage: `/setheadline Biology 1st Paper - By ACS`")
        return

    text_to_set = message.text.split(None, 1)[1].strip()
    await db.update_watermark_settings(user_id, headline_text=text_to_set, enabled=1)
    await message.reply_text(f"✅ Top lecture headline set to: `{text_to_set}` (Watermarking Enabled)")


@Client.on_message(filters.command("togglewm") & filters.private)
async def toggle_watermark_status_command(client: Client, message: Message):
    user_id = message.from_user.id
    current = await db.get_watermark_settings(user_id)
    new_state = 0 if current.get("enabled", 0) else 1
    await db.update_watermark_settings(user_id, enabled=new_state)
    state_str = "🟢 **Enabled**" if new_state else "🔴 **Disabled**"
    await message.reply_text(f"Watermark status: {state_str}")
