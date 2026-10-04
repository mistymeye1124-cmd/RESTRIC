# language: Python, file: handlers/channel_watcher.py, target: Python 3.10+, Pyrogram
"""
Telegram Real-Time Channel Auto-Forwarder & Mirror Cockpit:
Provides interactive UI, channel listener, state wizard, and management controls
for 24/7 automated channel-to-channel content replication.
"""

import re
import asyncio
from typing import Optional, Any, Tuple
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import db
from core.channel_watcher import mirror_post_to_destination
from core.state_manager import set_user_state, get_user_state, clear_user_state
from handlers.admin import is_admin


def _parse_chat_identifier(raw: str) -> Optional[Any]:
    """Extracts numeric chat ID or username from text, username, or t.me link."""
    cleaned = raw.strip()
    if cleaned.startswith("-100") and cleaned[4:].isdigit():
        return int(cleaned)
    if cleaned.lstrip("-").isdigit():
        return int(cleaned)
    if cleaned.startswith("@"):
        return cleaned
    # Links like https://t.me/c/2459862936/10
    m_priv = re.search(r"t\.me/c/(\d+)", cleaned)
    if m_priv:
        return int(f"-100{m_priv.group(1)}")
    m_pub = re.search(r"t\.me/([a-zA-Z0-9_]{4,})", cleaned)
    if m_pub:
        return f"@{m_pub.group(1)}"
    return None


async def _resolve_channel(client: Client, raw_id: Any) -> Tuple[Optional[int], str]:
    """
    Resolves raw identifier (numeric ID or @username/link) to:
    (numeric_chat_id, display_title).
    Guarantees numeric_chat_id is valid for event filtering.
    """
    chat_id: Optional[int] = None
    title: str = str(raw_id)

    if isinstance(raw_id, int):
        chat_id = raw_id
        try:
            c = await client.get_chat(raw_id)
            if c:
                title = c.title or c.first_name or str(raw_id)
        except Exception:
            pass
        return chat_id, title

    if isinstance(raw_id, str):
        try:
            c = await client.get_chat(raw_id)
            if c:
                chat_id = c.id
                title = c.title or c.first_name or raw_id
                return chat_id, title
        except Exception:
            pass

    return None, title


# -------------------------------------------------------------
# 1. Real-Time Channel Post Listener (Sub-second dispatch)
# -------------------------------------------------------------
@Client.on_message(filters.channel & ~filters.private, group=10)
async def on_channel_post_listener(client: Client, message: Message):
    """
    Sub-second event trigger: Whenever any post arrives in a channel where the bot
    is present, this instantly dispatches mirror tasks to all configured destination channels.
    """
    try:
        source_chat_id = message.chat.id
        active_monitors = await db.get_active_monitors_for_source(source_chat_id)
        if not active_monitors:
            return

        for mon in active_monitors:
            asyncio.create_task(
                mirror_post_to_destination(
                    bot_client=client,
                    monitor=mon,
                    source_msg=message,
                    source_msg_id=message.id,
                )
            )
    except Exception:
        # Never crash main event dispatcher
        pass


# -------------------------------------------------------------
# 2. Interactive UI Dashboard Commands
# -------------------------------------------------------------
@Client.on_message(filters.command(["watcher", "autoforward", "mirror", "monitors"]) & filters.private)
async def channel_watcher_dashboard_command(client: Client, message: Message):
    """Displays the Live Channel Auto-Forwarder Cockpit."""
    user_id = message.from_user.id
    user_is_admin = is_admin(user_id)
    is_vip = await db.is_user_premium(user_id)

    if not user_is_admin and not is_vip:
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")],
        ])
        await message.reply_text(
            "👑 **Live Channel Auto-Forwarder (VIP & Admin Feature)**\n\n"
            "This feature runs 24/7 in the background, listening to your designated source channels "
            "and automatically forwarding every new post directly to your destination channel in real time.\n\n"
            "💎 **Upgrade to VIP via `/premium` or contact Admin to unlock!**",
            reply_markup=markup,
        )
        return

    text, markup = await _render_watcher_dashboard(user_id, user_is_admin)
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_message(filters.command(["addwatcher", "addmirror", "addchannel"]) & filters.private)
async def add_watcher_command(client: Client, message: Message):
    """Quick setup command: /addwatcher <source_channel> <destination_channel>"""
    user_id = message.from_user.id
    user_is_admin = is_admin(user_id)
    is_vip = await db.is_user_premium(user_id)

    if not user_is_admin and not is_vip:
        await message.reply_text("💎 This feature is reserved for VIP members and Admins. Upgrade via `/premium`.")
        return

    cmd = message.command
    if len(cmd) < 3:
        help_text = (
            "📡 **ADD LIVE CHANNEL AUTO-FORWARDER**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Whenever a new message or video is posted in the source channel, the bot will automatically "
            "copy/mirror it to your destination channel in real time.\n\n"
            "📌 **Command Syntax:**\n"
            "`/addwatcher <source_channel> <destination_channel>`\n\n"
            "💡 **Examples:**\n"
            "• `/addwatcher @source_channel -1002459862936`\n"
            "• `/addwatcher https://t.me/c/1234567890/1 -1009876543210`\n"
            "• `/addwatcher -1001112223334 me` (to send directly to your inbox)\n\n"
            "⚠️ _Note: Ensure the bot is an **Admin** in the destination channel with **Post Messages** permission._"
        )
        await message.reply_text(help_text)
        return

    raw_src = cmd[1]
    raw_dst = cmd[2]

    src_parsed = _parse_chat_identifier(raw_src)
    dst_parsed = user_id if raw_dst.lower() in ("me", "dm", "here") else _parse_chat_identifier(raw_dst)

    if not src_parsed or not dst_parsed:
        await message.reply_text("❌ Invalid source or destination channel format. Please provide valid channel IDs or usernames.")
        return

    # Check anti-leech protected VIP channel
    if not user_is_admin and await db.is_channel_protected(src_parsed):
        await message.reply_text("🔒 **Error:** This source channel is locked by the owner. Auto-forwarding from it is not permitted.")
        return

    # Resolve source channel
    src_id, src_title = await _resolve_channel(client, src_parsed)
    if not src_id:
        if isinstance(src_parsed, int):
            src_id = src_parsed
        else:
            await message.reply_text(f"⚠️ Could not resolve source channel `{raw_src}`. Please provide its `-100...` numeric ID.")
            return

    # Resolve destination channel
    if dst_parsed == user_id:
        dst_id = user_id
        dst_title = f"{message.from_user.first_name} (Private DM)"
    else:
        dst_id, dst_title = await _resolve_channel(client, dst_parsed)
        if not dst_id:
            if isinstance(dst_parsed, int):
                dst_id = dst_parsed
            else:
                await message.reply_text(f"⚠️ Could not resolve destination channel `{raw_dst}`. Please provide its `-100...` numeric ID.")
                return

    # Save to database
    monitor_id = await db.add_channel_monitor(
        user_id=user_id,
        source_chat_id=src_id,
        source_title=src_title,
        dest_chat_id=dst_id,
        dest_title=dst_title,
        clean_ads=1,
        custom_caption="",
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 View All Monitors", callback_data="watcher_menu")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")],
    ])

    await message.reply_text(
        f"✅ **LIVE CHANNEL AUTO-FORWARDER CONFIGURED!**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Monitor ID:** `#{monitor_id}`\n"
        f"📥 **Source Channel:** `{src_title}` (`{src_id}`)\n"
        f"📤 **Destination:** `{dst_title}` (`{dst_id}`)\n"
        f"🛡️ **Status:** 🟢 **ACTIVE & LISTENING (24/7)**\n"
        f"🧹 **Ad Cleaner:** Enabled (Removes promo links)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Every new post in the source channel will now automatically mirror to the destination channel in real time!",
        reply_markup=markup,
    )


@Client.on_message(filters.command(["delwatcher", "delmirror"]) & filters.private)
async def delete_watcher_command(client: Client, message: Message):
    """Deletes a channel monitor by ID: /delwatcher <id>"""
    user_id = message.from_user.id
    cmd = message.command
    if len(cmd) < 2 or not cmd[1].isdigit():
        await message.reply_text("Usage: `/delwatcher <monitor_id>`\nExample: `/delwatcher 1`")
        return

    mon_id = int(cmd[1])
    user_is_admin = is_admin(user_id)

    deleted = await db.delete_channel_monitor(mon_id, user_id=None if user_is_admin else user_id)
    if deleted:
        await message.reply_text(f"✅ Channel monitor `#{mon_id}` removed successfully.")
    else:
        await message.reply_text(f"❌ Monitor `#{mon_id}` not found or you don't have permission to remove it.")


# -------------------------------------------------------------
# 3. Interactive Callbacks & Rendering Engine
# -------------------------------------------------------------
async def _render_watcher_dashboard(user_id: int, user_is_admin: bool) -> tuple[str, InlineKeyboardMarkup]:
    """Generates the main Live Channel Auto-Forwarder Cockpit view."""
    monitors = await db.get_channel_monitors(user_id=None if user_is_admin else user_id)

    total_monitors = len(monitors)
    active_monitors = sum(1 for m in monitors if m.get("is_active", 1) == 1)
    total_forwarded = sum(m.get("total_forwarded", 0) for m in monitors)

    text = (
        f"📡 **LIVE CHANNEL AUTO-FORWARDER COCKPIT**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔄 **24/7 Real-Time Channel Replication Engine**\n\n"
        f"📊 **Telemetry Overview:**\n"
        f"• Total Monitors: `{total_monitors}`\n"
        f"• Active & Listening: `🟢 {active_monitors}`\n"
        f"• Total Posts Mirrored: `📦 {total_forwarded}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if not monitors:
        text += (
            "ℹ️ _No channel monitors configured yet._\n\n"
            "👉 Tap **➕ Add Channel Monitor** below for step-by-step setup, or send:\n"
            "`/addwatcher <source_channel> <destination_channel>`"
        )
        buttons = [
            [InlineKeyboardButton("➕ Add Channel Monitor", callback_data="watcher_interactive_add")],
            [InlineKeyboardButton("📖 Manual Guide (/addwatcher)", callback_data="watcher_add_help")],
            [InlineKeyboardButton("🔄 Refresh Status", callback_data="watcher_menu")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")],
        ]
        return text, InlineKeyboardMarkup(buttons)

    text += "📋 **Configured Channel Monitors:**\n"
    buttons = []

    for mon in monitors[:8]:  # Show top 8 on page
        m_id = mon["id"]
        status_icon = "🟢" if mon.get("is_active", 1) == 1 else "⏸️"
        s_title = mon.get("source_title") or str(mon.get("source_chat_id"))
        d_title = mon.get("dest_title") or str(mon.get("dest_chat_id"))
        fwd_cnt = mon.get("total_forwarded", 0)

        # Sanitize markdown characters in channel titles
        s_clean = re.sub(r"[*_`\[\]]", "", s_title)
        d_clean = re.sub(r"[*_`\[\]]", "", d_title)

        # Truncate titles if too long
        s_short = (s_clean[:12] + "..") if len(s_clean) > 12 else s_clean
        d_short = (d_clean[:12] + "..") if len(d_clean) > 12 else d_clean

        text += f"• `{m_id}.` {status_icon} **{s_short}** ➔ **{d_short}** (`{fwd_cnt}` posts)\n"

        toggle_label = "⏸️ Pause" if mon.get("is_active", 1) == 1 else "▶️ Resume"
        buttons.append([
            InlineKeyboardButton(f"#{m_id} {s_short} ➔ {d_short}", callback_data=f"watcher_details:{m_id}"),
            InlineKeyboardButton(toggle_label, callback_data=f"watcher_toggle:{m_id}"),
            InlineKeyboardButton("🗑️", callback_data=f"watcher_del:{m_id}"),
        ])

    buttons.append([
        InlineKeyboardButton("➕ Add Channel Monitor", callback_data="watcher_interactive_add"),
        InlineKeyboardButton("📖 Manual Guide", callback_data="watcher_add_help"),
    ])
    buttons.append([
        InlineKeyboardButton("🔄 Refresh Status", callback_data="watcher_menu"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
    ])

    return text, InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex(r"^watcher_menu$"))
async def watcher_menu_callback(client: Client, query: CallbackQuery):
    await query.answer()
    user_id = query.from_user.id
    user_is_admin = is_admin(user_id)
    user_is_vip = await db.is_user_premium(user_id)

    if not user_is_admin and not user_is_vip:
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 Upgrade to VIP", callback_data="user_view_premium")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")],
        ])
        text = (
            "👑 **LIVE CHANNEL AUTO-FORWARDER (VIP & ADMIN FEATURE)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔄 **24/7 Real-Time Automated Channel Mirroring**\n\n"
            "⚡ **Key Capabilities:**\n"
            "• Listens to designated source channels 24/7 in real time.\n"
            "• Automatically clones every new post, photo, video, or doc instantly to your target channel.\n"
            "• Ad-Cleaning Engine: Strips competitor promo links & credits.\n"
            "• Zero Disk Latency: Direct cloud-to-cloud transmission.\n\n"
            "💎 **Upgrade to VIP via `/premium` or contact Admin to activate!**"
        )
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            try:
                await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
            except Exception:
                pass
        return

    text, markup = await _render_watcher_dashboard(user_id, user_is_admin)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^watcher_interactive_add$"))
async def watcher_interactive_add_callback(client: Client, query: CallbackQuery):
    """Step 1 of interactive Add Channel Monitor flow."""
    await query.answer()
    user_id = query.from_user.id
    user_is_admin = is_admin(user_id)
    user_is_vip = await db.is_user_premium(user_id)

    if not user_is_admin and not user_is_vip:
        await query.answer("💎 This feature is reserved for VIP members and Admins.", show_alert=True)
        return

    set_user_state(user_id, "waiting_watcher_src")

    text = (
        "➕ **ADD LIVE CHANNEL AUTO-FORWARDER** (Step 1 of 2)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📥 **Send the Source Channel that you want to mirror:**\n\n"
        "📌 **Accepted formats:**\n"
        "• Public username: `@ChannelUsername`\n"
        "• Public link: `https://t.me/ChannelUsername`\n"
        "• Private channel link: `https://t.me/c/1234567890/1`\n"
        "• Channel numeric ID: `-1001234567890`\n\n"
        "👉 _Send the link or username as a text message now (or tap Cancel):_"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Cancel", callback_data="watcher_menu")],
    ])
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^watcher_set_dm_dest$"))
async def watcher_set_dm_dest_callback(client: Client, query: CallbackQuery):
    """Quick 1-tap option to set current user's DM as destination."""
    await query.answer()
    user_id = query.from_user.id
    state_info = get_user_state(user_id)

    if not state_info or state_info.get("state") != "waiting_watcher_dst":
        await query.answer("Session expired. Please start over.", show_alert=True)
        user_is_admin = is_admin(user_id)
        text, markup = await _render_watcher_dashboard(user_id, user_is_admin)
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass
        return

    src_id = state_info.get("extra", {}).get("src_id")
    src_title = state_info.get("extra", {}).get("src_title", "Source Channel")
    dst_id = user_id
    first_name = query.from_user.first_name or "User"
    dst_title = f"{first_name} (Private DM)"

    clear_user_state(user_id)
    mon_id = await db.add_channel_monitor(
        user_id=user_id,
        source_chat_id=src_id,
        source_title=src_title,
        dest_chat_id=dst_id,
        dest_title=dst_title,
        clean_ads=1,
        custom_caption="",
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 View All Monitors", callback_data="watcher_menu")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")],
    ])

    text = (
        f"✅ **LIVE CHANNEL AUTO-FORWARDER CONFIGURED!**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Monitor ID:** `#{mon_id}`\n"
        f"📥 **Source Channel:** `{src_title}` (`{src_id}`)\n"
        f"📤 **Destination:** `{dst_title}` (`{dst_id}`)\n"
        f"🛡️ **Status:** 🟢 **ACTIVE & LISTENING (24/7)**\n"
        f"🧹 **Ad Cleaner:** Enabled (Removes promo links)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Every new post in the source channel will now automatically mirror to your private chat in real time!"
    )
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass


@Client.on_message(filters.text & filters.private & ~filters.command(["start", "cancel", "login", "settings", "premium"]), group=-1)
async def watcher_state_message_handler(client: Client, message: Message):
    """Handles interactive text input for Step 1 (Source) and Step 2 (Destination)."""
    user_id = message.from_user.id
    state_info = get_user_state(user_id)
    if not state_info:
        return

    st = state_info.get("state")
    if st not in ("waiting_watcher_src", "waiting_watcher_dst"):
        return

    raw_text = message.text.strip()
    if raw_text.lower() in ("cancel", "exit", "/cancel"):
        clear_user_state(user_id)
        await message.reply_text("❌ Channel monitor setup cancelled.")
        user_is_admin = is_admin(user_id)
        text, markup = await _render_watcher_dashboard(user_id, user_is_admin)
        await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        message.stop_propagation()
        return

    # STEP 1: Process Source Channel
    if st == "waiting_watcher_src":
        parsed = _parse_chat_identifier(raw_text)
        if not parsed:
            await message.reply_text(
                "❌ **Invalid Source Channel format!**\n\n"
                "Please provide a valid channel link, username (e.g. `@channel`), or ID (e.g. `-100...`).\n"
                "Or send `/cancel` to abort."
            )
            message.stop_propagation()
            return

        user_is_admin = is_admin(user_id)
        if not user_is_admin and await db.is_channel_protected(parsed):
            await message.reply_text("🔒 **Error:** This source channel is locked by the owner. Auto-forwarding from it is not permitted.")
            clear_user_state(user_id)
            message.stop_propagation()
            return

        # Resolve channel title & numeric ID
        resolved_id, resolved_title = await _resolve_channel(client, parsed)
        if not resolved_id:
            if isinstance(parsed, int):
                resolved_id = parsed
            else:
                await message.reply_text(
                    f"⚠️ **Could not resolve `{parsed}`!**\n\n"
                    "Make sure the bot has access to this channel, or provide the numeric channel ID (e.g. `-100...`) or a private invite link (`t.me/c/...`)."
                )
                message.stop_propagation()
                return

        # Move to Step 2
        set_user_state(user_id, "waiting_watcher_dst", extra={
            "src_id": resolved_id,
            "src_title": resolved_title,
        })

        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deliver to My Private Chat (DM)", callback_data="watcher_set_dm_dest")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="watcher_menu")],
        ])

        await message.reply_text(
            f"✅ **Source Channel Selected:**\n"
            f"• Title: **{resolved_title}**\n"
            f"• ID: `{resolved_id}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📤 **STEP 2 OF 2: DESTINATION CHANNEL**\n"
            f"Where should new posts be automatically forwarded?\n\n"
            f"📌 **Options:**\n"
            f"1. Send your **Destination Channel ID** (e.g. `-1009876543210`) or username (`@MyChannel`)\n"
            f"2. Or tap **[📥 Deliver to My Private Chat (DM)]** below!\n\n"
            f"⚠️ _Note: If using a channel, make sure this bot is added as an **Admin** with **Post Messages** permission._",
            reply_markup=markup,
        )
        message.stop_propagation()
        return

    # STEP 2: Process Destination Channel
    if st == "waiting_watcher_dst":
        src_id = state_info.get("extra", {}).get("src_id")
        src_title = state_info.get("extra", {}).get("src_title", "Source Channel")

        dst_id = None
        dst_title = "Destination"

        if raw_text.lower() in ("me", "dm", "here", "private"):
            dst_id = user_id
            first_name = message.from_user.first_name or "User"
            dst_title = f"{first_name} (Private DM)"
        else:
            parsed = _parse_chat_identifier(raw_text)
            if not parsed:
                await message.reply_text(
                    "❌ **Invalid Destination Channel format!**\n\n"
                    "Please provide a channel ID (e.g. `-100...`), username (`@channel`), or tap Deliver to DM.\n"
                    "Or send `/cancel` to abort."
                )
                message.stop_propagation()
                return

            res_id, res_title = await _resolve_channel(client, parsed)
            if res_id:
                dst_id = res_id
                dst_title = res_title
            elif isinstance(parsed, int):
                dst_id = parsed
                dst_title = res_title
            else:
                await message.reply_text(
                    f"⚠️ **Could not resolve destination `{parsed}`!**\n\n"
                    "Please ensure the bot is added to the channel as an Administrator, or provide the `-100...` numeric ID."
                )
                message.stop_propagation()
                return

        # Save to database
        clear_user_state(user_id)
        mon_id = await db.add_channel_monitor(
            user_id=user_id,
            source_chat_id=src_id,
            source_title=src_title,
            dest_chat_id=dst_id,
            dest_title=dst_title,
            clean_ads=1,
            custom_caption="",
        )

        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 View All Monitors", callback_data="watcher_menu")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")],
        ])

        await message.reply_text(
            f"✅ **LIVE CHANNEL AUTO-FORWARDER CONFIGURED!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Monitor ID:** `#{mon_id}`\n"
            f"📥 **Source Channel:** `{src_title}` (`{src_id}`)\n"
            f"📤 **Destination:** `{dst_title}` (`{dst_id}`)\n"
            f"🛡️ **Status:** 🟢 **ACTIVE & LISTENING (24/7)**\n"
            f"🧹 **Ad Cleaner:** Enabled (Removes promo links)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ Every new post in the source channel will now automatically mirror to your destination in real time!",
            reply_markup=markup,
        )
        message.stop_propagation()
        return


@Client.on_callback_query(filters.regex(r"^watcher_toggle:(\d+)$"))
async def watcher_toggle_callback(client: Client, query: CallbackQuery):
    await query.answer()
    user_id = query.from_user.id
    mon_id = int(query.matches[0].group(1))
    user_is_admin = is_admin(user_id)

    new_st = await db.toggle_channel_monitor(mon_id, user_id=None if user_is_admin else user_id)
    if new_st is not None:
        state_str = "🟢 Resumed" if new_st == 1 else "⏸️ Paused"
        try:
            await query.answer(f"Monitor #{mon_id} is now {state_str}!", show_alert=False)
        except Exception:
            pass
    else:
        try:
            await query.answer("Monitor not found.", show_alert=True)
        except Exception:
            pass

    text, markup = await _render_watcher_dashboard(user_id, user_is_admin)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^watcher_del:(\d+)$"))
async def watcher_del_callback(client: Client, query: CallbackQuery):
    await query.answer()
    mon_id = int(query.matches[0].group(1))
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ Yes, Delete", callback_data=f"watcher_del_confirm:{mon_id}"),
            InlineKeyboardButton("🔙 Cancel", callback_data="watcher_menu"),
        ]
    ])
    try:
        await query.message.edit_text(
            f"🗑️ **Are you sure you want to delete Channel Monitor `#{mon_id}`?**\n\n"
            "This will stop automated forwarding from this channel.",
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except Exception:
        try:
            await query.message.reply_text(
                f"🗑️ **Are you sure you want to delete Channel Monitor `#{mon_id}`?**\n\n"
                "This will stop automated forwarding from this channel.",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^watcher_del_confirm:(\d+)$"))
async def watcher_del_confirm_callback(client: Client, query: CallbackQuery):
    await query.answer()
    user_id = query.from_user.id
    mon_id = int(query.matches[0].group(1))
    user_is_admin = is_admin(user_id)

    await db.delete_channel_monitor(mon_id, user_id=None if user_is_admin else user_id)
    try:
        await query.answer(f"Channel Monitor #{mon_id} deleted.", show_alert=True)
    except Exception:
        pass

    text, markup = await _render_watcher_dashboard(user_id, user_is_admin)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^watcher_details:(\d+)$"))
async def watcher_details_callback(client: Client, query: CallbackQuery):
    await query.answer()
    mon_id = int(query.matches[0].group(1))
    mon = await db.get_channel_monitor_by_id(mon_id)
    if not mon:
        try:
            await query.answer("Monitor not found.", show_alert=True)
        except Exception:
            pass
        return

    status_str = "🟢 Active & Listening" if mon.get("is_active") == 1 else "⏸️ Paused"
    clean_ads_str = "✅ Active" if mon.get("clean_ads") == 1 else "❌ Disabled"
    last_fwd = mon.get("last_forwarded_at") or "Never"

    s_clean = re.sub(r"[*_`\[\]]", "", mon.get("source_title") or str(mon.get("source_chat_id")))
    d_clean = re.sub(r"[*_`\[\]]", "", mon.get("dest_title") or str(mon.get("dest_chat_id")))

    text = (
        f"📡 **CHANNEL MONITOR DETAILS `#{mon_id}`**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 **Source Channel:** `{s_clean}`\n"
        f"• ID: `{mon.get('source_chat_id')}`\n\n"
        f"📤 **Destination:** `{d_clean}`\n"
        f"• ID: `{mon.get('dest_chat_id')}`\n\n"
        f"⚙️ **Status:** {status_str}\n"
        f"🧹 **Ad-Cleaning:** {clean_ads_str}\n"
        f"📦 **Total Mirrored:** `{mon.get('total_forwarded', 0)}` posts\n"
        f"⏰ **Last Forwarded:** `{last_fwd}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⏸️ Pause" if mon.get("is_active") == 1 else "▶️ Resume",
                callback_data=f"watcher_toggle:{mon_id}",
            ),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"watcher_del:{mon_id}"),
        ],
        [InlineKeyboardButton("🔙 Back to Monitors", callback_data="watcher_menu")],
    ])

    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^watcher_add_help$"))
async def watcher_add_help_callback(client: Client, query: CallbackQuery):
    await query.answer()
    help_text = (
        "➕ **HOW TO ADD A CHANNEL AUTO-FORWARDER**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "You can add a monitor in two ways:\n\n"
        "1️⃣ **Interactive Wizard (Recommended):**\n"
        "Tap **➕ Add Channel Monitor** from the dashboard and follow the 2-step prompt!\n\n"
        "2️⃣ **Quick Command Syntax:**\n"
        "`/addwatcher <source_channel> <destination_channel>`\n\n"
        "📌 **Command Examples:**\n"
        "• `/addwatcher @my_source_channel -1002459862936`\n"
        "• `/addwatcher https://t.me/c/1234567890/1 -1009876543210`\n"
        "• `/addwatcher -1001112223334 me` (delivers directly to your DM)\n\n"
        "💡 **Key Checklist:**\n"
        "1. For the **Destination Channel**, make sure to add this bot as an **Administrator** with **Post Messages** permission.\n"
        "2. The bot or your connected worker account will automatically listen 24/7 and mirror any new post instantly!"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Launch Interactive Wizard", callback_data="watcher_interactive_add")],
        [InlineKeyboardButton("🔙 Back to Monitors", callback_data="watcher_menu")],
    ])
    try:
        await query.message.edit_text(help_text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        try:
            await query.message.reply_text(help_text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass
