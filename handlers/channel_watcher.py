# language: Python, file: handlers/channel_watcher.py, target: Python 3.10+, Pyrogram
"""
Telegram Real-Time Channel Auto-Forwarder & Mirror Cockpit:
Provides interactive UI, channel listener, and management controls
for 24/7 automated channel-to-channel content replication.
"""

import re
import asyncio
from typing import Optional, Any
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import db
from core.channel_watcher import mirror_post_to_destination


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
    except Exception as e:
        # Never crash main event dispatcher
        pass


# -------------------------------------------------------------
# 2. Interactive UI Dashboard Commands
# -------------------------------------------------------------
@Client.on_message(filters.command(["watcher", "autoforward", "mirror", "monitors"]) & filters.private)
async def channel_watcher_dashboard_command(client: Client, message: Message):
    """Displays the Live Channel Auto-Forwarder Cockpit."""
    user_id = message.from_user.id
    from config import ADMIN_IDS
    is_admin = user_id in ADMIN_IDS
    is_vip = await db.is_user_premium(user_id)

    if not is_admin and not is_vip:
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

    text, markup = await _render_watcher_dashboard(user_id, is_admin)
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command(["addwatcher", "addmirror", "addchannel"]) & filters.private)
async def add_watcher_command(client: Client, message: Message):
    """Quick setup command: /addwatcher <source_channel> <destination_channel>"""
    user_id = message.from_user.id
    from config import ADMIN_IDS
    is_admin = user_id in ADMIN_IDS
    is_vip = await db.is_user_premium(user_id)

    if not is_admin and not is_vip:
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

    src_id = _parse_chat_identifier(raw_src)
    dst_id = user_id if raw_dst.lower() in ("me", "dm", "here") else _parse_chat_identifier(raw_dst)

    if not src_id or not dst_id:
        await message.reply_text("❌ Invalid source or destination channel format. Please provide valid channel IDs or usernames.")
        return

    # Check anti-leech protected VIP channel
    if not is_admin and await db.is_channel_protected(src_id):
        await message.reply_text("🔒 **Error:** This source channel is locked by the owner. Auto-forwarding from it is not permitted.")
        return

    # Try resolving chat titles
    src_title = str(src_id)
    dst_title = str(dst_id)
    try:
        if isinstance(src_id, (int, str)) and not str(src_id).startswith("-100"):
            c_src = await client.get_chat(src_id)
            if c_src:
                src_title = c_src.title or c_src.first_name or src_title
    except Exception:
        pass

    try:
        if dst_id != user_id and not str(dst_id).startswith("-100"):
            c_dst = await client.get_chat(dst_id)
            if c_dst:
                dst_title = c_dst.title or c_dst.first_name or dst_title
    except Exception:
        pass

    # Save to database
    monitor_id = await db.add_channel_monitor(
        user_id=user_id,
        source_chat_id=src_id if isinstance(src_id, int) else 0,
        source_title=src_title,
        dest_chat_id=dst_id if isinstance(dst_id, int) else 0,
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
    from config import ADMIN_IDS
    is_admin = user_id in ADMIN_IDS

    deleted = await db.delete_channel_monitor(mon_id, user_id=None if is_admin else user_id)
    if deleted:
        await message.reply_text(f"✅ Channel monitor `#{mon_id}` removed successfully.")
    else:
        await message.reply_text(f"❌ Monitor `#{mon_id}` not found or you don't have permission to remove it.")


# -------------------------------------------------------------
# 3. Interactive Callbacks & Rendering Engine
# -------------------------------------------------------------
async def _render_watcher_dashboard(user_id: int, is_admin: bool) -> tuple[str, InlineKeyboardMarkup]:
    """Generates the main Live Channel Auto-Forwarder Cockpit view."""
    monitors = await db.get_channel_monitors(user_id=None if is_admin else user_id)

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
            "👉 Tap **➕ Add Channel Monitor** below or send:\n"
            "`/addwatcher <source_channel> <destination_channel>`"
        )
        buttons = [
            [InlineKeyboardButton("➕ Add Channel Monitor", callback_data="watcher_add_help")],
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

        # Truncate titles if too long
        s_short = (s_title[:12] + "..") if len(s_title) > 12 else s_title
        d_short = (d_title[:12] + "..") if len(d_title) > 12 else d_title

        text += f"• `{m_id}.` {status_icon} **{s_short}** ➔ **{d_short}** (`{fwd_cnt}` posts)\n"

        toggle_label = "⏸️ Pause" if mon.get("is_active", 1) == 1 else "▶️ Resume"
        buttons.append([
            InlineKeyboardButton(f"#{m_id} {s_short} ➔ {d_short}", callback_data=f"watcher_details:{m_id}"),
            InlineKeyboardButton(toggle_label, callback_data=f"watcher_toggle:{m_id}"),
            InlineKeyboardButton("🗑️", callback_data=f"watcher_del:{m_id}"),
        ])

    buttons.append([InlineKeyboardButton("➕ Add New Channel Monitor", callback_data="watcher_add_help")])
    buttons.append([
        InlineKeyboardButton("🔄 Refresh Status", callback_data="watcher_menu"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
    ])

    return text, InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex(r"^watcher_menu$"))
async def watcher_menu_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    from config import ADMIN_IDS
    is_admin = user_id in ADMIN_IDS
    text, markup = await _render_watcher_dashboard(user_id, is_admin)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^watcher_toggle:(\d+)$"))
async def watcher_toggle_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    mon_id = int(query.matches[0].group(1))
    from config import ADMIN_IDS
    is_admin = user_id in ADMIN_IDS

    new_st = await db.toggle_channel_monitor(mon_id, user_id=None if is_admin else user_id)
    if new_st is not None:
        state_str = "🟢 Resumed" if new_st == 1 else "⏸️ Paused"
        await query.answer(f"Monitor #{mon_id} is now {state_str}!", show_alert=False)
    else:
        await query.answer("Monitor not found.", show_alert=True)

    text, markup = await _render_watcher_dashboard(user_id, is_admin)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^watcher_del:(\d+)$"))
async def watcher_del_callback(client: Client, query: CallbackQuery):
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
        )
    except Exception:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^watcher_del_confirm:(\d+)$"))
async def watcher_del_confirm_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    mon_id = int(query.matches[0].group(1))
    from config import ADMIN_IDS
    is_admin = user_id in ADMIN_IDS

    await db.delete_channel_monitor(mon_id, user_id=None if is_admin else user_id)
    await query.answer(f"Channel Monitor #{mon_id} deleted.", show_alert=True)

    text, markup = await _render_watcher_dashboard(user_id, is_admin)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^watcher_details:(\d+)$"))
async def watcher_details_callback(client: Client, query: CallbackQuery):
    mon_id = int(query.matches[0].group(1))
    mon = await db.get_channel_monitor_by_id(mon_id)
    if not mon:
        await query.answer("Monitor not found.", show_alert=True)
        return

    status_str = "🟢 Active & Listening" if mon.get("is_active") == 1 else "⏸️ Paused"
    clean_ads_str = "✅ Active" if mon.get("clean_ads") == 1 else "❌ Disabled"
    last_fwd = mon.get("last_forwarded_at") or "Never"

    text = (
        f"📡 **CHANNEL MONITOR DETAILS `#{mon_id}`**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 **Source Channel:** `{mon.get('source_title')}`\n"
        f"• ID: `{mon.get('source_chat_id')}`\n\n"
        f"📤 **Destination:** `{mon.get('dest_title')}`\n"
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
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^watcher_add_help$"))
async def watcher_add_help_callback(client: Client, query: CallbackQuery):
    help_text = (
        "➕ **HOW TO ADD A CHANNEL AUTO-FORWARDER**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "To set up an auto-forwarder between two channels, send this command:\n\n"
        "👉 `/addwatcher <source_channel> <destination_channel>`\n\n"
        "📌 **Examples:**\n"
        "• `/addwatcher @my_source_channel -1002459862936`\n"
        "• `/addwatcher https://t.me/c/1234567890/1 -1009876543210`\n"
        "• `/addwatcher -1001112223334 me` (delivers to your private chat)\n\n"
        "💡 **Key Checklist:**\n"
        "1. For the **Destination Channel**, make sure to add this bot as an **Administrator** with **Post Messages** permission.\n"
        "2. The bot or your connected worker account will automatically listen 24/7 and mirror any new post instantly!"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Monitors", callback_data="watcher_menu")],
    ])
    try:
        await query.message.edit_text(help_text, reply_markup=markup)
    except Exception:
        pass
    await query.answer()
