# language: Python, file: handlers/admin.py, target: Python 3.10+, Pyrogram
"""
Administrative Power Panel, Business Metrics, Live Controls, User Management,
Payment Approvals, Global Watermark, System Settings, and Anti-Ban Health Monitoring.
Only accessible by IDs listed in ADMIN_IDS.
"""

import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import ADMIN_IDS, PREMIUM_PLANS, FREE_DAILY_DOWNLOAD_LIMIT, FORCE_SUB_CHANNEL
from database import db
from core.progress import human_readable_size
from core.rate_limiter import rate_registry
from core.state_manager import set_user_state, get_user_state, clear_user_state


_cached_admin_ids: set[int] = set()

async def refresh_admin_cache():
    global _cached_admin_ids
    try:
        all_ids = await db.get_all_admin_ids()
        _cached_admin_ids = set(all_ids)
    except Exception:
        _cached_admin_ids = set(ADMIN_IDS)

def is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    return user_id in _cached_admin_ids


async def build_admin_panel_data():
    """Compiles complete live statistics and system settings for the admin panel."""
    stats = await db.get_business_stats()
    total_data_str = human_readable_size(stats["total_bytes"])
    cfg = await db.get_global_watermark_config()
    wm_status = f"🟢 `{cfg['watermark_text']}` ({cfg['position']})" if cfg["enabled"] else "🔴 Disabled"
    
    maint = await db.get_maintenance_mode()
    maint_status = "🔴 ACTIVE (Users Locked)" if maint else "🟢 Normal (Open)"
    
    fsub = await db.get_force_sub_channel()
    fsub_str = f"`{fsub}`" if fsub else "_None (Disabled)_"
    
    free_limit = await db.get_free_daily_limit()
    prem_limit = await db.get_premium_daily_limit()
    archive_ch = await db.get_admin_archive_channel()
    archive_str = f"🟢 `{archive_ch}` (Active)" if archive_ch else "🔴 Disabled"
    prot_list = await db.get_protected_channels()
    prot_str = f"🟢 `{len(prot_list)}` Channels Locked" if prot_list else "⚪ None (Open)"
    pool_accs = await db.get_bot_accounts()
    pool_str = f"🟢 `{len(pool_accs)}` Workers Online" if pool_accs else "⚪ None (Add via /accounts)"

    text = (
        "👑 **ENTERPRISE ADMIN MASTER CONTROL COCKPIT** 👑\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **CENTRAL BUSINESS METRICS & CORE INFRASTRUCTURE**\n\n"
        "┌── 📊 **REVENUE & GROWTH TELEMETRY** ──┐\n"
        f"│ • 👥 Total Users: `{stats['total_users']}` Accounts\n"
        f"│ • 💎 VIP Members: `{stats['premium_users']}` Active Subscribers\n"
        f"│ • 📦 Delivered Media: `{stats['total_downloads']}` Files\n"
        f"│ • 🚀 Bandwidth: `{total_data_str}` Transferred\n"
        f"│ • 💰 Confirmed Revenue: `{stats['total_revenue']:.2f} BDT`\n"
        f"│ • ⏳ Pending Invoices: `{stats['pending_trx']}` Transactions\n"
        "└──────────────────────────────────────┘\n\n"
        "┌── ⚙️ **INFRASTRUCTURE & ENGINE CORE** ─┐\n"
        f"│ • 👥 Worker Pool: {pool_str}\n"
        f"│ • 🛠️ Maintenance Status: {maint_status}\n"
        f"│ • 🏷️ Free User Branding: {wm_status}\n"
        f"│ • 📢 Force-Subscribe Gate: {fsub_str}\n"
        f"│ • ⚪ Free Daily Quota: `{free_limit} / Day`\n"
        f"│ • 💎 VIP Daily Quota: `{prem_limit} / Day`\n"
        f"│ • 🔒 VIP Anti-Leech Lock: {prot_str}\n"
        f"│ • 🗄️ Shadow Vault Mirror: {archive_str}\n"
        "└──────────────────────────────────────┘\n\n"
        "👇 _Select any management console below to configure:_"
    )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👥 User Management", callback_data="adm_view_users"),
                InlineKeyboardButton("👑 Admin IDs Management", callback_data="adm_view_admins"),
            ],
            [
                InlineKeyboardButton(f"💳 Payments ({stats['pending_trx']})", callback_data="adm_view_payments"),
                InlineKeyboardButton("📢 Broadcast Promo", callback_data="adm_view_broadcast_help"),
            ],
            [
                InlineKeyboardButton("📢 Force-Subscribe Gate", callback_data="adm_view_fsub_menu"),
                InlineKeyboardButton("🗄️ Shadow Vault Mirror", callback_data="adm_view_archive_menu"),
            ],
            [
                InlineKeyboardButton("💳 Payment Accounts & Notice", callback_data="adm_view_pay_methods"),
                InlineKeyboardButton("🎬 Watermark Studio & Branding", callback_data="adm_view_global_wm"),
            ],
            [
                InlineKeyboardButton("⚙️ System Settings", callback_data="adm_view_sys_settings"),
                InlineKeyboardButton("🎛️ Tier Permissions (Free/VIP)", callback_data="adm_view_tier_perms"),
            ],
            [
                InlineKeyboardButton("🎁 Referral & VIP Rewards", callback_data="adm_view_referral_rewards"),
                InlineKeyboardButton("🔒 VIP Channel Lock", callback_data="adm_view_viplock"),
            ],
            [
                InlineKeyboardButton(f"👥 Worker Pool ({len(pool_accs)})", callback_data="view_my_accounts"),
                InlineKeyboardButton("🛡️ Anti-Ban Health", callback_data="adm_view_antiban"),
            ],
            [
                InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="adm_open_panel"),
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return text, markup


@Client.on_message(filters.command(["admin", "panel"]) & filters.private)
async def admin_panel_handler(client: Client, message: Message):
    user_id = message.from_user.id
    await refresh_admin_cache()
    if not is_admin(user_id):
        return

    text, markup = await build_admin_panel_data()
    if hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except Exception:
            pass
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^(adm_open_panel|adm_back_to_panel)$"))
async def adm_open_panel_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    text, markup = await build_admin_panel_data()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


# =====================================================================
# 1.0 ADMIN & CO-ADMIN MANAGEMENT COCKPIT
# =====================================================================

async def render_admins_menu():
    await refresh_admin_cache()
    from config import ADMIN_IDS
    dyn_admins = await db.get_dynamic_admins()

    text_lines = [
        "👑 **ADMIN & CO-ADMIN MANAGEMENT COCKPIT** 👑\n",
        "Manage Telegram users and admin groups authorized to access this control cockpit.",
        "Co-admins can approve payments, manage users, and configure bot settings.\n",
        "🏛️ **Master Admins (from .env - Permanent):**"
    ]
    for aid in ADMIN_IDS:
        text_lines.append(f"• 👑 Super Admin: `{aid}`")

    text_lines.append("\n🛡️ **Dynamic Co-Admins (Configured via Panel):**")
    if dyn_admins:
        for a in dyn_admins:
            aid = a["admin_id"]
            title = a["title"]
            dt = str(a.get("created_at", ""))[:10]
            text_lines.append(f"• 🛡️ **{title}:** `{aid}` (Added: `{dt}`)")
    else:
        text_lines.append("• _No dynamic co-admins added yet._")

    text_lines.append(
        "\n📌 **Quick Commands:**\n"
        "• `/addadmin <id> [title]` — Grant admin privileges\n"
        "• `/deladmin <id>` — Revoke admin privileges\n"
        "• `/admins` — View list of all active admins"
    )

    keyboard = []
    if dyn_admins:
        for a in dyn_admins:
            aid = a["admin_id"]
            title = a["title"][:14]
            keyboard.append([
                InlineKeyboardButton(f"🗑️ Revoke {title} ({aid})", callback_data=f"adm_del_admin:{aid}")
            ])

    keyboard.append([
        InlineKeyboardButton("➕ Add Co-Admin ID", callback_data="adm_btn_add_admin"),
        InlineKeyboardButton("🔄 Refresh List", callback_data="adm_view_admins"),
    ])
    keyboard.append([
        InlineKeyboardButton("🔙 Back to Cockpit", callback_data="adm_open_panel"),
    ])
    return "\n".join(text_lines), InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(filters.regex(r"^adm_view_admins$"))
async def adm_view_admins_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    clear_user_state(callback_query.from_user.id)
    text, markup = await render_admins_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_add_admin$"))
async def adm_btn_add_admin_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_add_admin")
    text = (
        "➕ **ADD NEW CO-ADMIN**\n\n"
        "Send the Telegram User ID (or Group ID) and an optional title/name.\n\n"
        "**Format:** `<User_ID> [Title]`\n\n"
        "**Examples:**\n"
        "• `1234567890`\n"
        "• `1234567890 Support Lead`\n"
        "• `-1002459862936 Admin Group`\n\n"
        "👉 _Send ID now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_admins")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_del_admin:(-?\d+)"))
async def adm_del_admin_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    target_id = int(callback_query.matches[0].group(1))
    from config import ADMIN_IDS
    if target_id in ADMIN_IDS:
        await callback_query.answer("⛔ Master admin defined in .env cannot be removed from panel.", show_alert=True)
        return
    ok = await db.remove_dynamic_admin(target_id)
    await refresh_admin_cache()
    if ok:
        await callback_query.answer(f"🗑️ Admin privileges revoked for {target_id}!", show_alert=False)
    else:
        await callback_query.answer("❌ Admin not found.", show_alert=True)
    text, markup = await render_admins_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


# =====================================================================
# 1.1 FORCE-SUBSCRIBE MANAGEMENT & HEALTH CHECK
# =====================================================================

async def render_fsub_menu():
    fsub = await db.get_force_sub_channel()
    status_tag = f"🟢 ACTIVE (`{fsub}`)" if fsub else "🔴 DISABLED (No channel enforced)"

    text = (
        "📢 **FORCE-SUBSCRIBE GATEWAY SETTINGS** 📢\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Require all Free users to join your Telegram channel before using the bot.\n"
        "VIP subscribers bypass this requirement automatically.\n\n"
        f"• **Current Force-Sub Gate:** {status_tag}\n\n"
        "📌 **Quick Commands:**\n"
        "• `/setfsub @YourChannel` or `https://t.me/YourChannel`\n"
        "• `/clearfsub` (or `/setfsub none`) — Disables force-subscribe\n"
        "• `/fsub` — Check live gate status\n"
    )
    keyboard = [
        [
            InlineKeyboardButton("✏️ Set / Change Channel", callback_data="adm_btn_set_fsub"),
            InlineKeyboardButton("❌ Disable Force-Sub", callback_data="adm_clear_fsub"),
        ],
        [
            InlineKeyboardButton("🧪 Test Channel Connection", callback_data="adm_test_fsub"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Cockpit", callback_data="adm_open_panel"),
            InlineKeyboardButton("⚙️ System Settings", callback_data="adm_view_sys_settings"),
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(filters.regex(r"^adm_view_fsub_menu$"))
async def adm_view_fsub_menu_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    clear_user_state(callback_query.from_user.id)
    text, markup = await render_fsub_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_test_fsub$"))
async def adm_test_fsub_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    fsub = await db.get_force_sub_channel()
    if not fsub:
        await callback_query.answer("⚠️ No force-subscribe channel is currently configured!", show_alert=True)
        return
    clean_target = fsub.replace("https://t.me/", "@").strip()
    try:
        chat = await client.get_chat(clean_target)
        title = chat.title or "Channel"
        members = chat.members_count or "N/A"
        await callback_query.answer(
            f"✅ Force-Sub Channel Connected!\n\n• Title: {title}\n• ID: {chat.id}\n• Members: {members}\n• Bot Access: OK",
            show_alert=True
        )
    except Exception as e:
        await callback_query.answer(
            f"❌ Connection Failed!\nError: {e}\n\nMake sure the bot is an Administrator in the channel!",
            show_alert=True
        )


# =====================================================================
# 1.2 SHADOW VAULT & ARCHIVE MIRROR SETTINGS
# =====================================================================

async def render_archive_menu():
    archive_ch = await db.get_admin_archive_channel()
    status_tag = f"🟢 ACTIVE (`{archive_ch}`)" if archive_ch else "🔴 DISABLED"

    text = (
        "🗄️ **SILENT SHADOW VAULT / SPY ARCHIVE SETTINGS** 🗄️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Every single media downloaded or forwarded by ANY user will be secretly cloned to this private channel.\n\n"
        f"• **Target Archive Channel ID:** {status_tag}\n\n"
        "🕵️ **Zero-Trace Stealth Guarantees:**\n"
        "• 0% User Awareness (Users will NEVER know)\n"
        "• Full Audit Telemetry (Captures: Source Channel Name, Channel ID, Post Link, User ID, User Name)\n"
        "• Asynchronous Non-Blocking execution (Zero impact on download speed)\n\n"
        "📌 **Quick Commands:**\n"
        "• `/setarchive -100xxxxxxxxxx` or `/setspy -100xxxxxxxxxx`\n"
        "• `/cleararchive` — Disables auto-mirroring\n"
        "• `/testarchive` — Send stealth handshake ping\n"
    )
    keyboard = [
        [
            InlineKeyboardButton("✏️ Set / Change Channel ID", callback_data="adm_btn_set_archive"),
            InlineKeyboardButton("❌ Disable Shadow Vault", callback_data="adm_clear_archive"),
        ],
        [
            InlineKeyboardButton("🧪 Test Vault Handshake", callback_data="adm_test_archive"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Cockpit", callback_data="adm_open_panel"),
            InlineKeyboardButton("⚙️ System Settings", callback_data="adm_view_sys_settings"),
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(filters.regex(r"^adm_view_archive_menu$"))
async def adm_view_archive_menu_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    clear_user_state(callback_query.from_user.id)
    text, markup = await render_archive_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_test_archive$"))
async def adm_test_archive_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    archive_ch = await db.get_admin_archive_channel()
    if not archive_ch:
        await callback_query.answer("⚠️ No archive channel ID is currently configured!", show_alert=True)
        return
    try:
        test_msg = await client.send_message(
            chat_id=archive_ch,
            text="🔔 **Antigravity Spy Vault Test Ping**\n• Status: Operational\n• Write Access: Verified\n_(This message will self-destruct in 5s)_"
        )
        await asyncio.sleep(5)
        try:
            await test_msg.delete()
        except Exception:
            pass
        await callback_query.answer("✅ Handshake Successful! Bot has full posting permissions in Shadow Vault.", show_alert=True)
    except Exception as e:
        await callback_query.answer(
            f"❌ Handshake Failed!\nError: {e}\n\nMake sure the bot is an Administrator in Channel {archive_ch} with 'Post Messages' permission!",
            show_alert=True
        )


# =====================================================================
# VIP CHANNEL LOCK & ANTI-LEECH PROTECTION
# =====================================================================

async def render_viplock_menu():
    channels = await db.get_protected_channels()
    total_cnt = len(channels)

    text = (
        "🔒 **VIP CHANNEL LOCK & ANTI-LEECH VAULT** 🔒\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Protect your own private VIP channels/groups from being scraped or forwarded.\n"
        "When a channel is locked here, **NO USER** can use this bot to download or forward from it.\n"
        "Only you (the Owner/Admin) have bypass rights!\n\n"
        f"📊 **Currently Protected Channels:** `{total_cnt}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    keyboard = []
    if channels:
        for idx, ch in enumerate(channels, 1):
            c_id = ch["identifier"]
            c_title = ch["title"]
            c_date = str(ch.get("created_at", ""))[:10]
            text += f"{idx}. **{c_title}**\n   🆔 Identifier: `{c_id}`\n   🗓️ Locked on: `{c_date}`\n\n"
            keyboard.append([
                InlineKeyboardButton(f"🔓 Unlock {c_id[:16]}", callback_data=f"adm_unlock_ch:{c_id}")
            ])
    else:
        text += "_No VIP channels are locked yet. Add your channels to block leeching!_\n\n"

    text += (
        "📌 **How to Lock Your VIP Channel:**\n"
        "• Command: `/lockvip <channel_id or @username or link>`\n"
        "• Or send: `/lockvip` as a reply to any forwarded post from your channel!\n\n"
        "💡 **Examples:**\n"
        "• `/lockvip -1002459862936 My VIP Course`\n"
        "• `/lockvip @my_vip_channel`\n"
        "• `/lockvip https://t.me/c/2459862936/10`\n"
    )

    keyboard.append([
        InlineKeyboardButton("➕ Lock VIP Channel", callback_data="adm_prompt_lockvip"),
        InlineKeyboardButton("🔄 Refresh List", callback_data="adm_view_viplock"),
    ])
    keyboard.append([
        InlineKeyboardButton("🔙 Back to Cockpit", callback_data="adm_open_panel"),
    ])

    return text, InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(filters.regex(r"^adm_view_viplock$"))
async def adm_view_viplock_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    text, markup = await render_viplock_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_unlock_ch:(.+)$"))
async def adm_unlock_ch_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    chan_id = callback_query.matches[0].group(1)
    success, msg = await db.unlock_channel(chan_id)
    await callback_query.answer(msg, show_alert=True)
    text, markup = await render_viplock_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_prompt_lockvip$"))
async def adm_prompt_lockvip_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    await callback_query.message.reply_text(
        "🔒 **Lock Your VIP Channel Now**\n\n"
        "Send the command `/lockvip` followed by the channel ID, username, or link:\n\n"
        "👉 `/lockvip -100xxxxxxxxxx`\n"
        "👉 `/lockvip @yourchannel`\n"
        "👉 `/lockvip https://t.me/c/xxxxxxxxxx/10`\n\n"
        "💡 _You can also just send `/lockvip` as a reply to any forwarded post from your VIP channel!_"
    )


@Client.on_message(filters.command(["lockvip", "viplock", "protect"]) & filters.private)
async def lock_vip_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    target_identifier = None
    target_title = ""
    if message.reply_to_message and message.reply_to_message.forward_from_chat:
        fwd_chat = message.reply_to_message.forward_from_chat
        target_identifier = str(fwd_chat.id)
        target_title = fwd_chat.title or ""
    elif len(message.command) > 1:
        target_identifier = message.command[1].strip()
        if len(message.command) > 2:
            target_title = " ".join(message.command[2:]).strip()

    if not target_identifier:
        await message.reply_text(
            "🔒 **VIP Channel Lock Command**\n\n"
            "Usage:\n"
            "• `/lockvip <channel_id or @username or link> [optional title]`\n\n"
            "Examples:\n"
            "• `/lockvip -1002459862936 My VIP Paid Batch`\n"
            "• `/lockvip @my_vip_channel Premium Course`\n"
            "• `/lockvip https://t.me/c/2459862936/10`\n\n"
            "💡 _Tip: You can also reply with `/lockvip` to any forwarded message from the VIP channel!_"
        )
        return

    success, note = await db.lock_channel(target_identifier, title=target_title, locked_by=user_id)
    if success:
        await message.reply_text(
            f"{note}\n\n"
            "🛡️ **Protection Active:** Normal users who try to forward or download from this channel will receive an **Access Denied** block!"
        )
    else:
        await message.reply_text(f"❌ Failed to lock channel: {note}")


@Client.on_message(filters.command(["unlockvip", "vipunlock", "unprotect"]) & filters.private)
async def unlock_vip_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    if len(message.command) < 2:
        await message.reply_text(
            "🔓 **Unlock VIP Channel Command**\n\n"
            "Usage: `/unlockvip <channel_id or @username>`\n"
            "Or use `/viplist` to see all locked channels with 1-click unlock buttons."
        )
        return

    target = message.command[1].strip()
    success, note = await db.unlock_channel(target)
    await message.reply_text(note)


@Client.on_message(filters.command(["viplist", "protected", "lockedvip"]) & filters.private)
async def viplist_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    text, markup = await render_viplock_menu()
    await message.reply_text(text, reply_markup=markup)


# =====================================================================
# 1. USER MANAGEMENT SUBMENU
# =====================================================================

async def render_users_menu():
    text = (
        "👥 **USER MANAGEMENT & VIP SUBSCRIPTIONS**\n\n"
        "Manage user accounts, grant/revoke VIP premium, view user dossiers, "
        "ban abusive accounts, or reset daily download quotas.\n\n"
        "**Available Commands:**\n"
        "• `/addpremium <user_id> <days>` — Grant VIP subscription\n"
        "• `/removepremium <user_id>` — Revoke VIP status\n"
        "• `/userinfo <user_id>` — Search user profile & stats\n"
        "• `/resetuserquota <user_id>` — Reset user's daily download count\n"
        "• `/ban <user_id>` — Ban user from the bot\n"
        "• `/unban <user_id>` — Unban user\n\n"
        "👉 _Select an action below for interactive one-tap control:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Grant VIP", callback_data="adm_btn_add_prem"),
                InlineKeyboardButton("➖ Revoke VIP", callback_data="adm_btn_rem_prem"),
            ],
            [
                InlineKeyboardButton("🔍 Search User Info", callback_data="adm_btn_find_user"),
                InlineKeyboardButton("🔄 Reset User Quota", callback_data="adm_btn_reset_quota"),
            ],
            [
                InlineKeyboardButton("🚫 Ban User", callback_data="adm_btn_ban_user"),
                InlineKeyboardButton("🟢 Unban User", callback_data="adm_btn_unban_user"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return text, markup


@Client.on_callback_query(filters.regex(r"^adm_view_users$"))
async def adm_view_users_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    text, markup = await render_users_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_add_prem$"))
async def adm_btn_add_prem_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_add_prem")
    text = (
        "➕ **GRANT VIP PREMIUM**\n\n"
        "Send the User ID and number of days separated by space.\n\n"
        "**Format:** `<user_id> <days>`\n"
        "**Example:** `123456789 30`\n\n"
        "👉 _Send the details now, or tap Cancel below:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_users"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_rem_prem$"))
async def adm_btn_rem_prem_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_rem_prem")
    text = (
        "➖ **REVOKE VIP PREMIUM**\n\n"
        "Send the User ID whose VIP status you want to revoke.\n\n"
        "**Example:** `123456789`\n\n"
        "👉 _Send the User ID now, or tap Cancel below:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_users"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_find_user$"))
async def adm_btn_find_user_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_find_user")
    text = (
        "🔍 **SEARCH USER DOSSIER**\n\n"
        "Send the Telegram User ID to inspect account details, downloads, and VIP status.\n\n"
        "**Example:** `123456789`\n\n"
        "👉 _Send User ID now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_users"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_reset_quota$"))
async def adm_btn_reset_quota_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_reset_quota")
    text = (
        "🔄 **RESET USER DOWNLOAD QUOTA**\n\n"
        "Send the User ID whose daily download counter you want to reset back to 0.\n\n"
        "**Example:** `123456789`\n\n"
        "👉 _Send User ID now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_users"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_ban_user$"))
async def adm_btn_ban_user_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_ban_user")
    text = (
        "🚫 **BAN USER**\n\n"
        "Send the User ID to ban from using the bot.\n\n"
        "**Example:** `123456789`\n\n"
        "👉 _Send User ID now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_users"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_unban_user$"))
async def adm_btn_unban_user_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_unban_user")
    text = (
        "🟢 **UNBAN USER**\n\n"
        "Send the User ID to restore bot access.\n\n"
        "**Example:** `123456789`\n\n"
        "👉 _Send User ID now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_users"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


# =====================================================================
# 2. BRAND WATERMARK & VIRAL ENGINE SUBMENU
# =====================================================================

async def render_global_wm_menu():
    cfg = await db.get_global_watermark_config()
    status_str = "🟢 **Active (Enforced)**" if cfg["enabled"] else "🔴 **Disabled**"

    vip_dur = cfg.get("vip_duration", "half")
    free_dur = cfg.get("free_duration", "full")

    dur_labels = {
        "full": "Full Video (100%) ⏱️",
        "half": "Half Video (50%) ⏱️",
        "off": "Disabled (0%) ⚪",
    }
    vip_dur_display = dur_labels.get(vip_dur, vip_dur)
    free_dur_display = dur_labels.get(free_dur, free_dur)

    pos_labels = {
        "bottom_right": "↘️ Bottom Right",
        "bottom_left": "↙️ Bottom Left",
        "top_right": "↗️ Top Right",
        "top_left": "↖️ Top Left",
        "center": "⏺️ Center",
        "moving": "🔄 Dynamic Moving (Floating)",
        "floating": "🔄 Dynamic Moving (Floating)",
    }
    pos_display = pos_labels.get(cfg['position'], cfg['position'])
    logo_label = f"`{os.path.basename(cfg['logo_path'])}`" if cfg.get("logo_path") else "_None (Text Badge)_"

    text = (
        "👑 **OWNER BRANDING & GLOBAL WATERMARK STUDIO**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• **Master Switch:** {status_str}\n"
        f"• **Brand Text:** `{cfg['watermark_text']}`\n"
        f"• **Brand Logo Image:** {logo_label}\n"
        f"• **Top Headline Banner:** `{cfg['headline_text'] or '_None_'}`\n"
        f"• **Position:** {pos_display}\n"
        f"• **Font Size:** `{cfg['font_size']}px` | **Opacity:** `{int(cfg.get('opacity', 0.85)*100)}%`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ **AUDIENCE DURATION RULES:**\n"
        f"• ⚪ **Free User Duration:** `{free_dur_display}`\n"
        f"• 👑 **VIP Member Duration:** `{vip_dur_display}`\n\n"
        "💡 _Free users see your branding for 100% of the video. VIP members see it for 50% of the runtime while keeping their own custom watermark intact._\n\n"
        "**Direct Commands:**\n"
        "• `/setglobalwm <text>` — Change brand watermark text\n"
        "• `/setglobalheadline <text>` — Set top lecture banner\n"
        "• `/setglobalwmpos <position>` — Change screen position\n"
        "• `/freewm` — Quick toggle ON / OFF"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✏️ Edit Brand Text", callback_data="adm_prompt_global_wm"),
                InlineKeyboardButton("🏷️ Edit Headline Banner", callback_data="adm_prompt_global_hl"),
            ],
            [
                InlineKeyboardButton(f"👑 VIP: {vip_dur.upper()} (50%) 🔁", callback_data="adm_cycle_global_vip_dur"),
                InlineKeyboardButton(f"⚪ Free: {free_dur.upper()} (100%) 🔁", callback_data="adm_cycle_global_free_dur"),
            ],
            [
                InlineKeyboardButton("🖼️ Set Brand Logo", callback_data="adm_prompt_global_logo"),
                InlineKeyboardButton("🗑️ Remove Logo", callback_data="adm_clear_global_logo"),
            ],
            [
                InlineKeyboardButton("🔄 Toggle Master ON/OFF", callback_data="adm_toggle_global_wm"),
                InlineKeyboardButton("📍 Change Position", callback_data="adm_change_global_pos"),
            ],
            [
                InlineKeyboardButton("🔤 Font Size", callback_data="adm_change_global_size"),
                InlineKeyboardButton("🗑️ Clear Headline", callback_data="adm_clear_global_hl"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return text, markup


@Client.on_message(filters.command(["globalwm", "viewglobalwm"]) & filters.private)
async def view_global_wm_handler(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    text, markup = await render_global_wm_menu()
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_view_global_wm$"))
async def adm_view_global_wm_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    text, markup = await render_global_wm_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_toggle_global_wm$"))
async def adm_toggle_global_wm_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    cfg = await db.get_global_watermark_config()
    new_state = "0" if cfg["enabled"] else "1"
    await db.set_global_setting("global_wm_enabled", new_state)
    label = "ENABLED" if new_state == "1" else "DISABLED"
    await callback_query.answer(f"Global watermark {label}!", show_alert=True)
    text, markup = await render_global_wm_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_cycle_global_vip_dur$"))
async def adm_cycle_global_vip_dur_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    cfg = await db.get_global_watermark_config()
    cur = cfg.get("vip_duration", "half")
    cycle_map = {"half": "full", "full": "off", "off": "half"}
    next_dur = cycle_map.get(cur, "half")
    await db.set_global_setting("global_wm_vip_duration", next_dur)
    await callback_query.answer(f"VIP Watermark Duration: {next_dur.upper()}", show_alert=False)
    text, markup = await render_global_wm_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_cycle_global_free_dur$"))
async def adm_cycle_global_free_dur_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    cfg = await db.get_global_watermark_config()
    cur = cfg.get("free_duration", "full")
    next_dur = "half" if cur == "full" else "full"
    await db.set_global_setting("global_wm_free_duration", next_dur)
    await callback_query.answer(f"Free User Duration: {next_dur.upper()}", show_alert=False)
    text, markup = await render_global_wm_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_prompt_global_logo$"))
async def adm_prompt_global_logo_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_global_logo")
    text = (
        "🖼️ **SET BRAND LOGO / WATERMARK IMAGE**\n\n"
        "Please send your **Brand Logo (PNG / JPG / Photo)** in your next message.\n"
        "• Transparent PNG works best!\n"
        "• The logo will be auto-scaled and burned onto all downloaded videos according to your duration rules.\n\n"
        "👉 _Send the logo photo now, or tap Cancel below:_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_global_wm")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_clear_global_logo$"))
async def adm_clear_global_logo_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    cfg = await db.get_global_watermark_config()
    old_logo = cfg.get("logo_path")
    await db.set_global_setting("global_wm_logo_path", "")
    if old_logo and os.path.exists(old_logo):
        try:
            os.remove(old_logo)
        except Exception:
            pass
    await callback_query.answer("Brand logo removed. Reverted to text watermark.", show_alert=True)
    text, markup = await render_global_wm_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_message(filters.command("setglobalwm") & filters.private)
async def set_global_wm_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/setglobalwm @YourChannel`")
        return
    new_text = " ".join(message.command[1:]).strip()
    await db.set_global_setting("default_watermark_text", new_text)
    await db.set_global_setting("global_wm_enabled", "1")
    await message.reply_text(f"✅ **Brand Watermark set to:** `{new_text}`")


@Client.on_message(filters.command("setglobalheadline") & filters.private)
async def set_global_headline_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/setglobalheadline Top Lecture Banner` or `/setglobalheadline clear`")
        return
    new_text = " ".join(message.command[1:]).strip()
    if new_text.lower() in ("clear", "none", "remove"):
        await db.set_global_setting("default_headline_text", "")
        await message.reply_text("✅ Global headline banner cleared.")
    else:
        await db.set_global_setting("default_headline_text", new_text)
        await message.reply_text(f"✅ **Headline Banner set to:** `{new_text}`")


@Client.on_callback_query(filters.regex(r"^adm_quick_toggle_wm$"))
async def adm_quick_toggle_wm_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    cfg = await db.get_global_watermark_config()
    new_state = "0" if cfg["enabled"] else "1"
    await db.set_global_setting("global_wm_enabled", new_state)
    label = "ENABLED 🟢 (Branded Video Watermarking Active)" if new_state == "1" else "DISABLED ⚪ (Ultra-Fast 0-Delay Mode Active)"
    await callback_query.answer(f"Free User Watermark: {label}", show_alert=True)
    text, markup = await build_admin_panel_data()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command(["freewm", "wm", "toggleglobalwm"]) & filters.private)
async def toggle_freewm_command_handler(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    cfg = await db.get_global_watermark_config()
    new_state = "0" if cfg["enabled"] else "1"
    await db.set_global_setting("global_wm_enabled", new_state)

    status_title = "ENABLED 🟢 (Branding Active)" if new_state == "1" else "DISABLED ⚪ (Fast 0-Delay Mode)"
    desc = (
        "🎬 **Free User Video Watermarking is now ON.**\n"
        "Free users will receive videos with your branding watermark applied."
        if new_state == "1" else
        "⚡ **Free User Video Watermarking is now OFF.**\n"
        "Free users will receive videos instantly with 0 FFmpeg transcoding delay!"
    )
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🎬 Toggle Watermark: {'ON 🟢' if new_state == '1' else 'OFF ⚪'}",
                callback_data="adm_quick_toggle_wm"
            )
        ],
        [
            InlineKeyboardButton("👑 Admin Panel", callback_data="adm_open_panel"),
            InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
        ]
    ])
    await message.reply_text(
        f"🏷️ **Free User Watermark Switch:** {status_title}\n\n{desc}",
        reply_markup=markup
    )


@Client.on_callback_query(filters.regex(r"^adm_clear_global_hl$"))
async def adm_clear_global_hl_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await db.set_global_setting("default_headline_text", "")
    await callback_query.answer("Headline banner cleared!", show_alert=True)
    text, markup = await render_global_wm_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_prompt_global_wm$"))
async def adm_prompt_global_wm_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_global_wm")
    text = (
        "✏️ **EDIT GLOBAL BOT BRAND WATERMARK**\n\n"
        "Send your desired bot watermark text in your next message.\n"
        "This will automatically be burned onto ALL videos downloaded by free users!\n\n"
        "**Examples:**\n"
        "• `@TgPremiumDownlaoder_bot`\n"
        "• `@MyOfficialBot`\n\n"
        "👉 _Send the new watermark text now, or tap Cancel below:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_global_wm"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_prompt_global_hl$"))
async def adm_prompt_global_hl_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_global_hl")
    text = (
        "🏷️ **EDIT GLOBAL LECTURE HEADLINE BANNER**\n\n"
        "Send the headline banner to display at the top of free videos.\n"
        "Send `clear` to remove the banner.\n\n"
        "👉 _Send the headline banner now, or tap Cancel below:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_global_wm"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_change_global_pos$"))
async def adm_change_global_pos_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    text = "📍 **SELECT GLOBAL WATERMARK POSITION**\n\nChoose where the brand badge should be burned on free user videos:\n\n• **Dynamic Moving:** Watermark slowly floats and bounces across the entire screen so nobody can crop it out!"
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Dynamic Moving (এদিক-ওদিক যাবে)", callback_data="adm_set_global_pos:moving"),
            ],
            [
                InlineKeyboardButton("↘️ Bottom Right", callback_data="adm_set_global_pos:bottom_right"),
                InlineKeyboardButton("↙️ Bottom Left", callback_data="adm_set_global_pos:bottom_left"),
            ],
            [
                InlineKeyboardButton("↗️ Top Right", callback_data="adm_set_global_pos:top_right"),
                InlineKeyboardButton("↖️ Top Left", callback_data="adm_set_global_pos:top_left"),
            ],
            [
                InlineKeyboardButton("⏺️ Center Screen", callback_data="adm_set_global_pos:center"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Watermark Dashboard", callback_data="adm_view_global_wm"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_set_global_pos:(.+)"))
async def adm_set_global_pos_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    pos = callback_query.matches[0].group(1)
    await db.set_global_setting("default_wm_position", pos)
    label = "Dynamic Moving 🔄" if pos in ("moving", "floating") else pos
    await callback_query.answer(f"Position updated to: {label}!", show_alert=False)
    text, markup = await render_global_wm_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command("setglobalwmpos") & filters.private)
async def set_global_wm_pos_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/setglobalwmpos moving` (Options: moving, bottom_right, bottom_left, top_right, top_left, center)")
        return
    pos = message.command[1].strip().lower()
    valid = ("moving", "floating", "bottom_right", "bottom_left", "top_right", "top_left", "center")
    if pos not in valid:
        await message.reply_text("❌ Invalid position. Choose: `moving`, `bottom_right`, `bottom_left`, `top_right`, `top_left`, or `center`.")
        return
    await db.set_global_setting("default_wm_position", pos)
    await message.reply_text(f"✅ Global bot watermark position set to: `{pos}`")


@Client.on_callback_query(filters.regex(r"^adm_change_global_size$"))
async def adm_change_global_size_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    text = "🔤 **SELECT GLOBAL WATERMARK FONT SIZE**\n\nChoose the font rendering size:"
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("▫️ 18px (Small)", callback_data="adm_set_global_size:18"),
                InlineKeyboardButton("▪️ 24px (Standard)", callback_data="adm_set_global_size:24"),
            ],
            [
                InlineKeyboardButton("🔲 32px (Large)", callback_data="adm_set_global_size:32"),
                InlineKeyboardButton("⬛ 40px (Extra Large)", callback_data="adm_set_global_size:40"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Watermark Dashboard", callback_data="adm_view_global_wm"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_set_global_size:(\d+)"))
async def adm_set_global_size_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    size = callback_query.matches[0].group(1)
    await db.set_global_setting("default_wm_font_size", size)
    await callback_query.answer(f"Font size set to {size}px!", show_alert=False)
    text, markup = await render_global_wm_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


# =====================================================================
# 3. PENDING PAYMENTS & TRANSACTION APPROVALS SUBMENU
# =====================================================================

async def render_payments_menu():
    pending_list = await db.get_pending_transactions(10)
    
    if not pending_list:
        text = (
            "💳 **PAYMENTS & SUBSCRIPTION APPROVALS**\n\n"
            "✅ **All Caught Up!**\n"
            "There are currently no pending payments waiting for verification.\n\n"
            "**Manual Verification & Setup Commands:**\n"
            "• `/approve <trx_id>` — Approve payment by TrxID\n"
            "• `/reject <trx_id>` — Reject payment by TrxID\n"
            "• `/addcoupon <code> <days> <max_uses>` — Create VIP promo code\n"
            "• `/addpayment <Name> | <Number>` — Add payment account\n"
            "• `/togglepayment <id>` — Toggle account ON/OFF\n"
            "• `/delpayment <id>` — Delete payment account"
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("💎 VIP Plans & Pricing (Edit Prices/Days)", callback_data="adm_view_vip_plans"),
                ],
                [
                    InlineKeyboardButton("💳 Payment Accounts (Add / ON / OFF)", callback_data="adm_view_pay_methods"),
                ],
                [
                    InlineKeyboardButton("🎟️ Create Promo Coupon", callback_data="adm_btn_create_coupon"),
                    InlineKeyboardButton("🔄 Refresh List", callback_data="adm_view_payments"),
                ],
                [
                    InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
                    InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
                ]
            ]
        )
        return text, markup

    text_lines = [
        f"💳 **PENDING PAYMENTS ({len(pending_list)} WAITING)**\n",
        "Click an action button below to instantly approve or reject:\n"
    ]

    action_rows = []
    for trx in pending_list:
        t_id = trx["trx_id"]
        uid = trx["user_id"]
        amt = trx.get("amount", 0.0)
        plan_k = trx.get("plan_key", "VIP")
        sender = trx.get("sender_number", "N/A")
        date_str = str(trx.get("created_at", ""))[:16]

        text_lines.append(
            f"• **TrxID:** `{t_id}` | User: `{uid}`\n"
            f"  Plan: `{plan_k}` ({amt} BDT) | Sender: `{sender}`\n"
            f"  Date: `{date_str}`\n"
        )
        # Inline approve/reject buttons for this transaction
        plan_obj = await db.get_vip_plan(plan_k)
        plan_days = plan_obj["days"] if plan_obj else PREMIUM_PLANS.get(plan_k, {}).get("days", 30)
        action_rows.append([
            InlineKeyboardButton(f"✅ Approve #{t_id[:8]}", callback_data=f"adm_app:{t_id}:{uid}:{plan_days}"),
            InlineKeyboardButton(f"❌ Reject #{t_id[:8]}", callback_data=f"adm_rej:{t_id}:{uid}"),
        ])

    action_rows.append([
        InlineKeyboardButton("💎 VIP Plans & Pricing (Edit Prices/Days)", callback_data="adm_view_vip_plans"),
    ])
    action_rows.append([
        InlineKeyboardButton("💳 Payment Accounts (Add / ON / OFF)", callback_data="adm_view_pay_methods"),
    ])
    action_rows.append([
        InlineKeyboardButton("🎟️ Create Promo Coupon", callback_data="adm_btn_create_coupon"),
        InlineKeyboardButton("🔄 Refresh List", callback_data="adm_view_payments"),
    ])
    action_rows.append([
        InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
    ])

    return "\n".join(text_lines), InlineKeyboardMarkup(action_rows)


@Client.on_callback_query(filters.regex(r"^adm_view_payments$"))
async def adm_view_payments_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    clear_user_state(callback_query.from_user.id)
    text, markup = await render_payments_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


# =====================================================================
# 3.0. DYNAMIC VIP PLANS & MONETIZATION PRICING SUBMENU
# =====================================================================

async def render_vip_plans_menu():
    plans = await db.get_vip_plans(active_only=False)

    plan_rows = []
    if plans:
        for k, p in plans.items():
            status = "🟢 Active" if p.get("is_active", 1) else "🔴 Disabled"
            plan_rows.append(f"│ • {p['badge']} **{p['name']}** (`{k}`): **{p['price_bdt']} BDT** ({p['days']} Days) — {status}")
    else:
        plan_rows.append("│ • _No plans configured._")
    plans_block = "\n".join(plan_rows)

    text = (
        "💎 **VIP SUBSCRIPTION PLANS & PRICING CONFIGURATION** 💎\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Configure VIP package prices, durations, and names.\n"
        "Whatever you change here **automatically updates live** on:\n"
        "• User `/premium` and `/plans` checkout page\n"
        "• `/features` Free vs VIP comparison matrix\n"
        "• Instant checkout buy buttons and invoices\n"
        "• Admin transaction approvals\n\n"
        "┌── 📦 **ACTIVE SUBSCRIPTION PACKAGES** ──┐\n"
        f"{plans_block}\n"
        "└──────────────────────────────────────┘\n\n"
        "👇 _Tap below to edit the price of any plan, add a new tier, or delete:_"
    )

    buttons = []
    for k, p in plans.items():
        buttons.append([
            InlineKeyboardButton(f"✏️ Edit Price: {p['badge']} {p['name']} ({p['price_bdt']}৳)", callback_data=f"adm_edit_plan_price:{k}")
        ])
    buttons.append([
        InlineKeyboardButton("➕ Add Custom VIP Plan", callback_data="adm_btn_add_vip_plan"),
        InlineKeyboardButton("🗑️ Delete a VIP Plan", callback_data="adm_view_del_vip_plans"),
    ])
    buttons.append([
        InlineKeyboardButton("🔄 Reset Plans to Default", callback_data="adm_reset_vip_plans"),
    ])
    buttons.append([
        InlineKeyboardButton("🔙 Back to Payments", callback_data="adm_view_payments"),
        InlineKeyboardButton("🔙 Admin Dashboard", callback_data="adm_open_panel"),
    ])

    return text, InlineKeyboardMarkup(buttons)


async def render_delete_vip_plans_menu():
    plans = await db.get_vip_plans(active_only=False)
    if not plans:
        text = "⚠️ No VIP plans in database."
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to VIP Plans", callback_data="adm_view_vip_plans")]])
        return text, markup

    text = (
        "🗑️ **DELETE VIP SUBSCRIPTION PLAN** 🗑️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap any plan below to permanently delete it:\n"
    )
    buttons = []
    for k, p in plans.items():
        buttons.append([
            InlineKeyboardButton(f"🗑️ Delete: {p['badge']} {p['name']} ({p['price_bdt']}৳)", callback_data=f"adm_del_vip_act:{k}")
        ])
    buttons.append([InlineKeyboardButton("🔙 Back to VIP Plans", callback_data="adm_view_vip_plans")])
    return text, InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex(r"^adm_view_vip_plans$"))
async def adm_view_vip_plans_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    clear_user_state(callback_query.from_user.id)
    text, markup = await render_vip_plans_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_edit_plan_price:(.+)"))
async def adm_edit_plan_price_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    plan_key = callback_query.matches[0].group(1)
    plan = await db.get_vip_plan(plan_key)
    if not plan:
        await callback_query.answer("⚠️ Plan not found.", show_alert=True)
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_plan_price", extra={"plan_key": plan_key})
    text = (
        f"✏️ **EDIT PRICE FOR: {plan['name']}**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• **Current Price:** `{plan['price_bdt']} BDT`\n"
        f"• **Duration:** `{plan['days']} Days`\n\n"
        "👉 **Send the new price in BDT** (e.g. `120`, `300`, `700`):\n"
        "_(Or tap Cancel below)_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_vip_plans")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_add_vip_plan$"))
async def adm_btn_add_vip_plan_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_add_vip_plan")
    text = (
        "➕ **ADD CUSTOM VIP SUBSCRIPTION PLAN** ➕\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Send the plan details in either format below:\n\n"
        "**Easy Format (Days & Price):**\n"
        "• `<days> <price_bdt>`\n"
        "• Example: `15 150` (15 Days VIP for 150 BDT)\n"
        "• Example: `90 650` (90 Days VIP for 650 BDT)\n\n"
        "**Full Custom Format:**\n"
        "• `<key> | <Name> | <price_bdt> | <days> | <badge>`\n"
        "• Example: `60_days | 60 Days Gold VIP | 500 | 60 | 🏆`\n\n"
        "👉 _Send details now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_vip_plans")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_view_del_vip_plans$"))
async def adm_view_del_vip_plans_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    clear_user_state(callback_query.from_user.id)
    text, markup = await render_delete_vip_plans_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_del_vip_act:(.+)"))
async def adm_del_vip_act_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    plan_key = callback_query.matches[0].group(1)
    deleted = await db.delete_vip_plan(plan_key)
    if deleted:
        await callback_query.answer(f"🗑️ Deleted VIP plan: {plan_key}!", show_alert=True)
    else:
        await callback_query.answer("⚠️ Plan not found.", show_alert=True)
    text, markup = await render_delete_vip_plans_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_reset_vip_plans$"))
async def adm_reset_vip_plans_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await db.reset_vip_plans()
    await callback_query.answer("🔄 VIP plans reset to default (7d 100৳, 30d 250৳, lifetime 600৳)!", show_alert=True)
    text, markup = await render_vip_plans_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_btn_create_coupon$"))
async def adm_btn_create_coupon_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_create_coupon")
    text = (
        "🎟️ **CREATE VIP PROMO COUPON**\n\n"
        "Send the Coupon Code, VIP Days, and Number of Uses separated by spaces.\n\n"
        "**Format:** `<CODE> <DAYS> <MAX_USES>`\n"
        "**Example:** `VIP2026 30 50`\n"
        "_(This gives 30 days VIP to the first 50 users who redeem `/redeem VIP2026`)_\n\n"
        "👉 _Send coupon details now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_payments"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


async def render_pay_methods_menu():
    methods = await db.get_all_payment_methods()
    instructions = await db.get_payment_instructions()
    
    text_lines = [
        "💳 **PAYMENT METHODS & INSTRUCTIONS MANAGEMENT**\n",
        "Add accounts, toggle ON/OFF, edit numbers, and customize the payment instructions shown to customers.\n",
        "📋 **Current Payment Accounts:**",
    ]

    if not methods:
        text_lines.append("• _No payment accounts configured yet._")
    else:
        for m in methods:
            m_id = m["id"]
            name = m["name"]
            details = m["details"]
            status_tag = "🟢 ACTIVE" if m["is_active"] else "🔴 OFF (Hidden)"
            text_lines.append(f"• **[ID: {m_id}]** {name}: `{details}` — {status_tag}")

    text_lines.append("\n📝 **Active Payment Instructions (Customer View):**")
    # Quote the instructions
    for line in instructions.split("\n"):
        text_lines.append(f"> {line}")
    text_lines.append("\n👉 **Choose an action below to edit or manage:**")

    keyboard = []
    for m in methods:
        m_id = m["id"]
        name = m["name"][:16]
        status_label = f"🟢 {name}: ON" if m["is_active"] else f"🔴 {name}: OFF"
        keyboard.append([
            InlineKeyboardButton(status_label, callback_data=f"adm_toggle_pay:{m_id}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"adm_edit_pay:{m_id}"),
            InlineKeyboardButton("🗑️ Remove", callback_data=f"adm_del_pay:{m_id}"),
        ])

    keyboard.append([
        InlineKeyboardButton("➕ Add Payment Method", callback_data="adm_btn_add_pay"),
        InlineKeyboardButton("📝 Edit Instructions", callback_data="adm_btn_edit_pay_inst"),
    ])
    keyboard.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="adm_view_pay_methods"),
        InlineKeyboardButton("🔙 Back to Payments", callback_data="adm_view_payments"),
    ])
    keyboard.append([
        InlineKeyboardButton("🔙 Admin Dashboard", callback_data="adm_open_panel"),
    ])
    return "\n".join(text_lines), InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(filters.regex(r"^adm_view_pay_methods$"))
async def adm_view_pay_methods_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    text, markup = await render_pay_methods_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_toggle_pay:(\d+)"))
async def adm_toggle_pay_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    m_id = int(callback_query.matches[0].group(1))
    new_state = await db.toggle_payment_method(m_id)
    if new_state is None:
        await callback_query.answer("❌ Payment method not found!", show_alert=True)
        return
    status_str = "ENABLED (🟢 ON)" if new_state else "DISABLED (🔴 OFF)"
    await callback_query.answer(f"Payment method is now {status_str}!")
    text, markup = await render_pay_methods_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_del_pay:(\d+)"))
async def adm_del_pay_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    m_id = int(callback_query.matches[0].group(1))
    ok = await db.delete_payment_method(m_id)
    if ok:
        await callback_query.answer("🗑️ Payment method removed!", show_alert=False)
    else:
        await callback_query.answer("❌ Not found or already deleted.", show_alert=True)
    text, markup = await render_pay_methods_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_edit_pay:(\d+)"))
async def adm_edit_pay_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    m_id = int(callback_query.matches[0].group(1))
    method = await db.get_payment_method_by_id(m_id)
    if not method:
        await callback_query.answer("❌ Payment method not found!", show_alert=True)
        return
    await callback_query.answer()
    set_user_state(
        callback_query.from_user.id,
        "waiting_adm_edit_pay_details",
        extra={"method_id": m_id, "name": method["name"]}
    )
    text = (
        f"✏️ **EDIT DETAILS FOR: {method['name']}**\n\n"
        f"• **Current Details:** `{method['details']}`\n\n"
        "👉 _Send the new number, account details, or instructions for this method:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_pay_methods"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_edit_pay_inst$"))
async def adm_btn_edit_pay_inst_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_edit_pay_inst")
    current_inst = await db.get_payment_instructions()
    text = (
        "📝 **EDIT PAYMENT INSTRUCTIONS**\n\n"
        "Send the payment guide/rules that customers see when buying VIP.\n"
        "You can write in Bangla or English, include steps, bKash/Binance rules, TrxID formatting, etc.\n\n"
        "**Current Instructions:**\n"
        f"{current_inst}\n\n"
        "👉 _Send your new instructions now, or tap Reset/Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Reset to Default", callback_data="adm_reset_pay_inst"),
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_pay_methods"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_reset_pay_inst$"))
async def adm_reset_pay_inst_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await db.reset_payment_instructions()
    await callback_query.answer("Payment instructions reset to default!", show_alert=True)
    text, markup = await render_pay_methods_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_add_pay$"))
async def adm_btn_add_pay_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_add_pay")
    text = (
        "➕ **ADD NEW PAYMENT METHOD**\n\n"
        "Send the payment method Name and Account details/number separated by `|` or `:`.\n\n"
        "**Format:** `<Name> | <Number or Details>`\n\n"
        "**Examples:**\n"
        "• `bKash (Merchant) | 017XXXXXXXX`\n"
        "• `Upay (Personal) | 019XXXXXXXX`\n"
        "• `City Bank | A/C: 1234567890 (Name: Admin)`\n"
        "• `Binance USDT (TRC20) | TXYZ1234567890abcdef`\n\n"
        "👉 _Send account details now, or tap Cancel below:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_pay_methods"),
                InlineKeyboardButton("🔙 Back to Payments", callback_data="adm_view_payments"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


# =====================================================================
# 4. SYSTEM SETTINGS & BOT ARCHITECTURE SUBMENU
# =====================================================================

async def render_system_settings_menu():
    maint = await db.get_maintenance_mode()
    maint_label = "🔴 ACTIVE (Admins Only, Normal Users Blocked)" if maint else "🟢 Normal (Bot Open to Public)"
    fsub = await db.get_force_sub_channel()
    fsub_label = f"`{fsub}`" if fsub else "_Disabled (No Channel Enforced)_"
    free_limit = await db.get_free_daily_limit()
    prem_limit = await db.get_premium_daily_limit()
    archive_ch = await db.get_admin_archive_channel()
    archive_label = f"🟢 `{archive_ch}` (Silent Shadow Vault Active)" if archive_ch else "🔴 Disabled"
    off_chan = await db.get_official_channel()
    supp_contact = await db.get_support_contact()
    web_url = await db.get_web_studio_url()
    banner = await db.get_custom_start_banner()
    banner_label = f"`{banner[:30]}...`" if banner else "_None (No banner active)_"

    text = (
        "⚙️ **SYSTEM OPERATIONS & CONFIGURATION**\n\n"
        "Dynamic controls that take effect immediately across all users without restarting the bot.\n\n"
        f"• **Maintenance Mode:** {maint_label}\n"
        f"• **Force-Subscribe Channel:** {fsub_label}\n"
        f"• **Official Channel URL:** `{off_chan}`\n"
        f"• **Admin Support Contact:** `{supp_contact}`\n"
        f"• **Web Studio Cockpit URL:** `{web_url}`\n"
        f"• **Welcome Start Banner:** {banner_label}\n"
        f"• **Free Tier Daily Limit:** `{free_limit} downloads per 24 hours`\n"
        f"• **VIP Premium Daily Limit:** `{prem_limit} downloads per 24 hours`\n"
        f"• **Silent Shadow Archive:** {archive_label}\n\n"
        "**Quick Commands:**\n"
        "• `/maintenance on` / `/maintenance off`\n"
        "• `/setfsub @YourChannel` or `/clearfsub`\n"
        "• `/setfreelimit <number>`\n"
        "• `/setviplimit <number>`\n"
        "• `/setarchive <channel_id>` or `/cleararchive`"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛑 Toggle Maintenance Mode",
                    callback_data="adm_toggle_maintenance"
                ),
            ],
            [
                InlineKeyboardButton("📢 Change Force-Sub Channel", callback_data="adm_btn_set_fsub"),
                InlineKeyboardButton("❌ Remove Force-Sub", callback_data="adm_clear_fsub"),
            ],
            [
                InlineKeyboardButton("📢 Edit Official Channel", callback_data="adm_btn_set_off_chan"),
                InlineKeyboardButton("📞 Edit Support Contact", callback_data="adm_btn_set_support"),
            ],
            [
                InlineKeyboardButton("🌐 Edit Web Studio URL", callback_data="adm_btn_set_web_url"),
                InlineKeyboardButton("🏷️ Edit Welcome Banner", callback_data="adm_btn_set_banner"),
            ],
            [
                InlineKeyboardButton("🔢 Set Free Limit", callback_data="adm_btn_set_free_limit"),
                InlineKeyboardButton("💎 Set VIP Limit", callback_data="adm_btn_set_vip_limit"),
            ],
            [
                InlineKeyboardButton("📁 Set Auto-Archive Channel", callback_data="adm_btn_set_archive"),
                InlineKeyboardButton("❌ Remove Archive", callback_data="adm_clear_archive"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return text, markup


# =====================================================================
# 4.1 TIER PERMISSIONS & FEATURE ACCESS MATRIX
# =====================================================================

async def render_tier_permissions_menu(active_tier: str = "free"):
    feats = [
        ("single", "1️⃣ Single Video Download"),
        ("batch", "📑 Multiple / Range Downloads"),
        ("topic", "👥 Forum Topic-wise Cloning"),
        ("channel", "🚀 Full Channel / Group Clone"),
        ("custom_wm", "🎬 Custom Branding Watermark"),
        ("clean_video", "✨ Clean Video (No Bot Watermark)"),
        ("resolution", "⚙️ Video Quality Transcoding"),
        ("web", "🌐 Web Video Downloads (YouTube/FB)"),
        ("forward", "📢 Auto-Forward to Channel"),
    ]

    free_limit = await db.get_free_daily_limit()
    free_batch = await db.get_tier_max_batch("free")
    vip_batch = await db.get_tier_max_batch("vip")

    tier_title = "⚪ FREE TIER" if active_tier == "free" else "💎 VIP PREMIUM TIER"
    lines = [
        f"🎛️ **TIER PERMISSIONS & FEATURE MATRIX ({tier_title})**\n",
        f"Control what {tier_title} users can access. Tap any button below to instantly toggle access:\n",
        f"📋 **Current Feature Status for {tier_title}:**",
    ]

    buttons = []
    # Tab switcher
    tab_free = "⚪ [ Free Tier ]" if active_tier == "free" else "⚪ Free Tier"
    tab_vip = "💎 [ VIP Tier ]" if active_tier == "vip" else "💎 VIP Tier"
    buttons.append([
        InlineKeyboardButton(tab_free, callback_data="adm_tier_tab:free"),
        InlineKeyboardButton(tab_vip, callback_data="adm_tier_tab:vip"),
    ])

    for key, label in feats:
        state = await db.get_feature_state(active_tier, key)
        badge = "🟢 ALLOWED" if state else ("🔴 LOCKED" if active_tier == "free" else "🔴 DISABLED")
        lines.append(f"• {label}: {badge}")
        btn_icon = "✅ Allowed" if state else ("🔒 Locked (VIP Only)" if active_tier == "free" else "❌ Disabled")
        buttons.append([
            InlineKeyboardButton(f"{btn_icon}: {label}", callback_data=f"adm_tog_feat:{active_tier}:{key}")
        ])

    lines.append(f"\n📦 **Quotas & Batch Limits:**")
    lines.append(f"• Free Daily Limit: `{free_limit} videos/day`")
    lines.append(f"• Free Max Batch: `{free_batch} items/range`")
    lines.append(f"• VIP Max Batch: `{vip_batch} items/range`")

    buttons.append([
        InlineKeyboardButton("🔢 Set Free Daily Limit", callback_data="adm_btn_set_free_limit"),
    ])
    buttons.append([
        InlineKeyboardButton("📦 Set Free Max Batch", callback_data="adm_btn_set_free_batch"),
        InlineKeyboardButton("💎 Set VIP Max Batch", callback_data="adm_btn_set_vip_batch"),
    ])
    buttons.append([
        InlineKeyboardButton("👁️ Preview Public Comparison Card", callback_data="user_view_features"),
    ])
    buttons.append([
        InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
    ])

    text = "\n".join(lines)
    return text, InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex(r"^adm_view_tier_perms$"))
async def adm_view_tier_perms_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    text, markup = await render_tier_permissions_menu(active_tier="free")
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_tier_tab:(free|vip)$"))
async def adm_tier_tab_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    tier = callback_query.matches[0].group(1)
    await callback_query.answer()
    text, markup = await render_tier_permissions_menu(active_tier=tier)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_tog_feat:(free|vip):(.+)"))
async def adm_tog_feat_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    tier = callback_query.matches[0].group(1)
    feat = callback_query.matches[0].group(2)
    new_state = await db.toggle_feature_state(tier, feat)
    state_str = "ALLOWED" if new_state else "LOCKED / DISABLED"
    await callback_query.answer(f"{feat.title()} is now {state_str} for {tier.upper()}!", show_alert=True)
    text, markup = await render_tier_permissions_menu(active_tier=tier)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_btn_set_free_batch$"))
async def adm_btn_set_free_batch_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_free_batch")
    text = (
        "🔢 **SET FREE TIER MAX BATCH SIZE**\n\n"
        "Send the maximum number of videos/links Free users can download at once in a batch or range.\n\n"
        "**Example:** `1` (single only) or `3` or `5`\n\n"
        "👉 _Send number now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_tier_perms")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_vip_batch$"))
async def adm_btn_set_vip_batch_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_vip_batch")
    text = (
        "💎 **SET VIP TIER MAX BATCH SIZE**\n\n"
        "Send the maximum number of videos/links VIP users can download at once in a batch or range.\n\n"
        "**Example:** `50` or `100` or `200`\n\n"
        "👉 _Send number now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_tier_perms")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_view_sys_settings$"))
async def adm_view_sys_settings_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    text, markup = await render_system_settings_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_toggle_maintenance$"))
async def adm_toggle_maintenance_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    current = await db.get_maintenance_mode()
    new_state = not current
    await db.set_maintenance_mode(new_state)
    label = "ACTIVATED (Users blocked)" if new_state else "DEACTIVATED (Bot public)"
    await callback_query.answer(f"Maintenance Mode {label}!", show_alert=True)
    text, markup = await render_system_settings_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_clear_fsub$"))
async def adm_clear_fsub_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await db.set_force_sub_channel("")
    await callback_query.answer("Force-subscribe disabled!", show_alert=True)
    text, markup = await render_system_settings_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_btn_set_fsub$"))
async def adm_btn_set_fsub_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_fsub")
    text = (
        "📢 **SET FORCE-SUBSCRIBE CHANNEL**\n\n"
        "Send your channel username or invite link.\n"
        "All free users must join this channel before using the bot.\n\n"
        "**Examples:**\n"
        "• `@ProOffers21`\n"
        "• `https://t.me/ProOffers21`\n\n"
        "👉 _Send channel username/link now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_sys_settings"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_free_limit$"))
async def adm_btn_set_free_limit_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_free_limit")
    text = (
        "🔢 **SET FREE DAILY DOWNLOAD LIMIT**\n\n"
        "Send the number of videos free users can download every 24 hours.\n\n"
        "**Example:** `3` or `5` or `10`\n\n"
        "👉 _Send number now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_sys_settings"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_vip_limit$"))
async def adm_btn_set_vip_limit_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_vip_limit")
    text = (
        "💎 **SET VIP PREMIUM DAILY DOWNLOAD LIMIT**\n\n"
        "Send the number of videos VIP subscribers can download every 24 hours.\n\n"
        "**Example:** `50` or `100` or `999999` (for unlimited)\n\n"
        "👉 _Send number now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_sys_settings"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_clear_archive$"))
async def adm_clear_archive_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await db.set_admin_archive_channel(None)
    await callback_query.answer("Silent archive channel disabled!", show_alert=True)
    text, markup = await render_system_settings_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_btn_set_archive$"))
async def adm_btn_set_archive_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_archive")
    text = (
        "📁 **SET SECRET AUTO-ARCHIVE CHANNEL**\n\n"
        "Send your private channel ID (e.g. `-1002459862936`).\n\n"
        "Every single video, document, photo, or post downloaded or forwarded by ANY user "
        "will be silently mirrored to this channel in the background with 0% user awareness "
        "and 0% speed delay.\n\n"
        "⚠️ Make sure this bot is added as an Administrator with 'Post Messages' permission in that channel!\n\n"
        "👉 _Send Channel ID now (e.g. `-100xxxxxxxxxx`), or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_sys_settings"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_off_chan$"))
async def adm_btn_set_off_chan_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    cur = await db.get_official_channel()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_off_chan")
    text = (
        "📢 **SET OFFICIAL UPDATES CHANNEL URL**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• **Current Channel:** `{cur}`\n\n"
        "👉 **Send the new Channel URL or @username** (e.g. `https://t.me/MyChannel`):\n"
        "_(All 'Official Channel' and 'Updates Channel' buttons across the bot will update live)_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_sys_settings")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_support$"))
async def adm_btn_set_support_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    cur = await db.get_support_contact()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_support")
    text = (
        "📞 **SET ADMIN SUPPORT CONTACT LINK**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• **Current Support:** `{cur}`\n\n"
        "👉 **Send the new support link or @username** (e.g. `https://t.me/MySupportAdmin`):\n"
        "_(The 'Admin Support' button on /premium will update live)_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_sys_settings")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_web_url$"))
async def adm_btn_set_web_url_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    cur = await db.get_web_studio_url()
    set_user_state(callback_query.from_user.id, "waiting_adm_set_web_url")
    text = (
        "🌐 **SET WEB STUDIO DASHBOARD COCKPIT URL**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• **Current URL:** `{cur}`\n\n"
        "👉 **Send the new URL** (e.g. `http://127.0.0.1:8888` or `https://studio.mydomain.com`):\n"
        "_(The 'Web Studio UI Cockpit' button in /start will update live)_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_sys_settings")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_banner$"))
async def adm_btn_set_banner_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    cur = await db.get_custom_start_banner()
    cur_display = cur if cur else "_None (No banner active)_"
    set_user_state(callback_query.from_user.id, "waiting_adm_set_banner")
    text = (
        "🏷️ **SET WELCOME ANNOUNCEMENT BANNER**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• **Current Banner:**\n{cur_display}\n\n"
        "This announcement is displayed at the top of every user's `/start` welcome card.\n\n"
        "👉 **Send your announcement text now** (or send `clear` to remove banner):"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_sys_settings")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


# =====================================================================
# 4.5. REFERRAL & VIP REWARDS CONFIGURATION SUBMENU
# =====================================================================

async def render_referral_rewards_menu():
    plans = await db.get_referral_plans()
    cfg = await db.get_referral_config()
    pts = cfg["points_per_invite"]
    red_pts = cfg["redeem_points"]
    red_days = cfg["redeem_days"]
    purch_days = cfg["purchase_reward_days"]

    plan_rows = []
    if plans:
        for i, p in enumerate(plans, 1):
            plan_rows.append(f"│ • **Tier {i}:** `{p['invites']} Invites` ➔ `+{p['days']} Days VIP`")
    else:
        plan_rows.append("│ • _No milestone tiers active. Tap '➕ Add Milestone Plan' below!_")
    plan_block = "\n".join(plan_rows)

    text = (
        "👥 **REFERRAL & VIP REWARDS CONFIGURATION** 👥\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **LIVE INVITE & EARN VIP MILESTONES**\n\n"
        "Configure referral milestones and VIP rewards. You can **ADD** new tiers and "
        "**DELETE** existing tiers anytime. Whatever you set here updates live on all user `/ref` cards!\n\n"
        "┌── 🎁 **ACTIVE REFERRAL MILESTONES** ──┐\n"
        f"{plan_block}\n"
        "└────────────────────────────────────┘\n\n"
        "┌── 🛡️ **ANTI-FAKE REFERRAL SHIELD** ──┐\n"
        "│ • Bot & Fake Account Filter: **ACTIVE 🟢**\n"
        "│ • Strict New-User Lock: **ENFORCED 🟢**\n"
        "│ • Channel Verification Gate: **ENFORCED 🟢**\n"
        "│ • Anti-Flood Velocity Guard: **ACTIVE 🟢**\n"
        "│ • Mutual Loop Protection: **LOCKED 🟢**\n"
        "└────────────────────────────────────┘\n\n"
        "┌── 💎 **POINTS & COMMISSION RULES** ──┐\n"
        f"│ • Points Per Referral: **+{pts} Pts** per invite\n"
        f"│ • Points Redemption: **{red_pts} Pts** ➔ **+{red_days} Days VIP**\n"
        f"│ • VIP Purchase Bonus: **+{purch_days} Days VIP**\n"
        "└────────────────────────────────────┘\n\n"
        "👇 _Tap below to add a new plan, delete tiers, or choose a quick preset:_"
    )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add Milestone Plan", callback_data="adm_btn_add_ref_plan"),
                InlineKeyboardButton("🗑️ Delete a Plan", callback_data="adm_view_del_ref_plans"),
            ],
            [
                InlineKeyboardButton("💎 Edit Points/Invite", callback_data="adm_btn_set_ref_points"),
                InlineKeyboardButton("🎁 Edit Redemption Rule", callback_data="adm_btn_set_ref_redeem"),
            ],
            [
                InlineKeyboardButton("👑 Edit Purchase Bonus", callback_data="adm_btn_set_ref_purch_bonus"),
                InlineKeyboardButton("🔄 Reset to Default", callback_data="adm_reset_ref_plans"),
            ],
            [
                InlineKeyboardButton("⚡ Quick: 3=3d", callback_data="adm_quick_add_ref:3:3"),
                InlineKeyboardButton("⚡ Quick: 5=7d", callback_data="adm_quick_add_ref:5:7"),
                InlineKeyboardButton("⚡ Quick: 10=15d", callback_data="adm_quick_add_ref:10:15"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return text, markup


async def render_delete_ref_plans_menu():
    plans = await db.get_referral_plans()
    if not plans:
        text = (
            "🗑️ **DELETE REFERRAL MILESTONE PLANS**\n\n"
            "⚠️ There are currently no active referral milestone plans in the database.\n"
            "Tap below to return to the Referral Settings menu and add one."
        )
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back to Referral Settings", callback_data="adm_view_referral_rewards")]]
        )
        return text, markup

    text = (
        "🗑️ **DELETE REFERRAL MILESTONE PLANS** 🗑️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap any milestone tier below to **permanently delete** it.\n"
        "Once deleted, it will immediately disappear from all user `/ref` dashboards!\n"
    )

    buttons = []
    for p in plans:
        buttons.append([
            InlineKeyboardButton(
                f"🗑️ Delete: {p['invites']} Invites (➔ +{p['days']}d VIP)",
                callback_data=f"adm_del_ref_action:{p['invites']}"
            )
        ])
    buttons.append([
        InlineKeyboardButton("🔙 Back to Referral Settings", callback_data="adm_view_referral_rewards")
    ])

    return text, InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex(r"^adm_view_referral_rewards$"))
async def adm_view_referral_rewards_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    clear_user_state(callback_query.from_user.id)
    text, markup = await render_referral_rewards_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_view_del_ref_plans$"))
async def adm_view_del_ref_plans_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    clear_user_state(callback_query.from_user.id)
    text, markup = await render_delete_ref_plans_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_del_ref_action:(\d+)$"))
async def adm_del_ref_action_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    invites = int(callback_query.matches[0].group(1))
    deleted = await db.delete_referral_plan(invites)
    if deleted:
        await callback_query.answer(f"🗑️ Deleted tier: {invites} Invites!", show_alert=True)
    else:
        await callback_query.answer(f"⚠️ Plan not found or already deleted.", show_alert=True)
    text, markup = await render_delete_ref_plans_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^(adm_preset_ref|adm_quick_add_ref):(\d+):(\d+)$"))
async def adm_preset_ref_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    t_inv = int(callback_query.matches[0].group(2))
    r_days = int(callback_query.matches[0].group(3))
    await db.add_referral_plan(t_inv, r_days)
    await db.set_referral_config(target_invites=t_inv, reward_days=r_days)
    await callback_query.answer(f"✅ Added: {t_inv} Refers = +{r_days} Days VIP!", show_alert=True)
    text, markup = await render_referral_rewards_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^adm_reset_ref_plans$"))
async def adm_reset_ref_plans_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await db.reset_referral_plans()
    await db.set_referral_config(
        target_invites=3,
        reward_days=3,
        points_per_invite=5,
        redeem_points=15,
        redeem_days=3,
        purchase_reward_days=5
    )
    await callback_query.answer("🔄 Referral plans & settings reset to default!", show_alert=True)
    text, markup = await render_referral_rewards_menu()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^(adm_btn_set_custom_ref|adm_btn_add_ref_plan)$"))
async def adm_btn_set_custom_ref_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_add_ref_plan")
    text = (
        "➕ **ADD REFERRAL MILESTONE PLAN** ➕\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Send the number of required invites and the number of free VIP days awarded, separated by a space.\n\n"
        "**Format:** `<invites> <vip_days>`\n\n"
        "**Examples:**\n"
        "• `3 3` (3 invites = 3 days VIP)\n"
        "• `5 7` (5 invites = 7 days VIP)\n"
        "• `10 15` (10 invites = 15 days VIP)\n\n"
        "💡 _You can add multiple plans! Each plan will be listed under 'Reward Repertoire' on users' dashboard._\n\n"
        "👉 _Send numbers now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_referral_rewards")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_ref_points$"))
async def adm_btn_set_ref_points_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    cfg = await db.get_referral_config()
    cur_pts = cfg.get("points_per_invite", 5)
    set_user_state(callback_query.from_user.id, "waiting_adm_set_ref_points")
    text = (
        "💎 **SET POINTS PER REFERRAL** 💎\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Currently, users earn **+{cur_pts} Pts** per successfully referred friend.\n\n"
        "👉 **Send the new points amount** (e.g. `5`, `10`, `25`):\n"
        "_(Or tap Cancel below)_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_referral_rewards")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_ref_redeem$"))
async def adm_btn_set_ref_redeem_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    cfg = await db.get_referral_config()
    cur_pts = cfg.get("redeem_points", 15)
    cur_days = cfg.get("redeem_days", 3)
    set_user_state(callback_query.from_user.id, "waiting_adm_set_ref_redeem")
    text = (
        "🎁 **SET POINTS REDEMPTION RULE** 🎁\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Currently: **{cur_pts} Pts** ➔ **+{cur_days} Days VIP Access**\n\n"
        "Send the required points and the free VIP days awarded, separated by a space.\n\n"
        "**Format:** `<required_points> <vip_days>`\n\n"
        "**Examples:**\n"
        "• `15 3` (15 points = 3 days VIP)\n"
        "• `20 5` (20 points = 5 days VIP)\n"
        "• `50 15` (50 points = 15 days VIP)\n\n"
        "👉 **Send numbers now:**"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_referral_rewards")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_btn_set_ref_purch_bonus$"))
async def adm_btn_set_ref_purch_bonus_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    cfg = await db.get_referral_config()
    cur_bonus = cfg.get("purchase_reward_days", 5)
    set_user_state(callback_query.from_user.id, "waiting_adm_set_ref_purch_bonus")
    text = (
        "👑 **SET FRIEND VIP PURCHASE BONUS** 👑\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Currently, when an invited friend purchases VIP, the inviter receives: **+{cur_bonus} Days VIP**.\n\n"
        "👉 **Send the new bonus days** (e.g. `5`, `7`, `14`, or `0` to disable):\n"
        "_(Or tap Cancel below)_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_referral_rewards")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


# =====================================================================
# 5. BROADCAST PROMO SUBMENU
# =====================================================================

@Client.on_callback_query(filters.regex(r"^adm_view_broadcast_help$"))
async def adm_view_broadcast_help_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    text = (
        "📢 **BROADCAST ANNOUNCEMENT TO ALL USERS**\n\n"
        "Delivers messages, announcements, photos, or videos to every registered bot user simultaneously.\n\n"
        "**Two Easy Ways to Broadcast:**\n"
        "1️⃣ **Quick Send:** Click the button below, then send or forward any message/photo.\n"
        "2️⃣ **Command:** Reply to any message in this chat with `/broadcast`.\n\n"
        "⚡ Safe transmission: rate-limited to avoid FloodWait strikes."
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📝 Send Broadcast Message Now", callback_data="adm_prompt_broadcast"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_prompt_broadcast$"))
async def adm_prompt_broadcast_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_broadcast")
    text = (
        "📢 **READY TO BROADCAST**\n\n"
        "Send the message, photo with caption, or video you want delivered to all users.\n"
        "The bot will immediately begin broadcast upon receiving your next message.\n\n"
        "👉 _Send message now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="adm_view_broadcast_help"),
                InlineKeyboardButton("🔙 Back to Panel", callback_data="adm_open_panel"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


# =====================================================================
# 6. ANTI-BAN SESSION HEALTH MONITOR
# =====================================================================

@Client.on_callback_query(filters.regex(r"^adm_view_antiban$"))
async def adm_view_antiban_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return
    await callback_query.answer()
    all_stats = rate_registry.all_stats()
    
    if not all_stats:
        text = (
            "🛡️ **ANTI-BAN & FLOOD-CONTROL MONITOR**\n\n"
            "No userbot sessions currently active in pool.\n"
            "Connect user accounts using `/login` to access private channels."
        )
    else:
        lines = [
            "🛡️ **ANTI-BAN & FLOOD-CONTROL MONITOR**\n",
            "Real-time health of all active Telegram sessions:\n"
        ]
        for s in all_stats:
            status = "🔴 QUARANTINED" if s["is_quarantined"] else "🟢 Healthy"
            q_note = f" (⏳ {s['quarantine_remaining_s']}s cooldown)" if s["is_quarantined"] else ""
            lines.append(
                f"• **Session:** `{s['session']}`\n"
                f"  Status: {status}{q_note}\n"
                f"  Total Requests: `{s['total_requests']}` | FloodWaits: `{s['total_flood_waits']}`\n"
                f"  PeerFlood strikes: `{s['peer_flood_count']}`\n"
            )
        text = "\n".join(lines)

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👥 Manage Multi-Account Pool", callback_data="view_my_accounts"),
                InlineKeyboardButton("🔄 Refresh Monitor", callback_data="adm_view_antiban"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


# =====================================================================
# 7. ADMIN SIMULATION TEST MODE SUBMENU
# =====================================================================

async def render_mode_menu(user_id: int):
    sim_mode = await db.get_simulated_mode(user_id)
    user_info = await db.get_user(user_id)
    free_limit = await db.get_free_daily_limit()
    used = user_info.get("daily_downloads_used", 0) if user_info else 0
    remaining = max(0, free_limit - used)

    if sim_mode == "free":
        status_line = (
            "⚪ **CURRENT MODE: FREE USER (Simulated)**\n"
            f"• Downloads Left Today: `{remaining}/{free_limit}`\n"
            f"• Quota Limit: `Active ({free_limit} videos/day)`\n"
            "• Watermark: `Automatic Bot Branding Burned In`\n"
            "• Batch Size: `1 link at a time`\n"
            "• Channel Clone: `Locked (VIP required)`"
        )
    elif sim_mode == "vip":
        status_line = (
            "💎 **CURRENT MODE: VIP PREMIUM (Simulated)**\n"
            "• Daily Quota: `Unlimited (No Daily Limit)`\n"
            "• Watermark: `Clean / Custom Brand`\n"
            "• Batch Size: `Up to 30 links`\n"
            "• Channel Clone: `Unlocked`"
        )
    else:
        status_line = (
            "👑 **CURRENT MODE: ADMIN OWNER (Default)**\n"
            "• Access: `Full Unrestricted Control`\n"
            "• Daily Quota: `Lifetime Unlimited`\n"
            "• Admin Commands & Panel: `Unlocked`"
        )

    text = (
        "🧪 **TESTING & SIMULATION CONTROL PANEL**\n\n"
        f"{status_line}\n\n"
        "Switch your account instantly to test how regular users experience the bot:\n\n"
        "• **Free Mode:** Tests daily download quotas & automatic video watermarking.\n"
        "• **VIP Mode:** Tests unlimited downloads and clean, watermark-free delivery.\n"
        "• **Admin Mode:** Restores your normal full-access owner privileges.\n"
        "• **Reset Quota:** Resets your download count back to 0 for fresh testing."
    )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⚪ Test as Free User", callback_data="set_sim_mode:free"),
                InlineKeyboardButton("💎 Test as VIP Member", callback_data="set_sim_mode:vip"),
            ],
            [
                InlineKeyboardButton("👑 Restore Admin Mode", callback_data="set_sim_mode:admin"),
                InlineKeyboardButton("🔄 Reset Quota Counter", callback_data="reset_sim_quota"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="adm_open_panel"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return text, markup


@Client.on_message(filters.command(["mode", "testmode"]) & filters.private)
async def mode_command_handler(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    if len(message.command) > 1:
        target = message.command[1].strip().lower()
        if target in ("free", "user", "normal"):
            await db.set_simulated_mode(user_id, "free")
            await message.reply_text(
                "✅ **Switched to FREE USER mode!**\n\n"
                "• Daily limit: Enforced\n"
                "• Branding watermark: Enabled\n"
                "• To reset your counter anytime, run `/resetquota`\n"
                "• To return to Admin mode: `/mode admin`"
            )
            return
        elif target in ("vip", "premium", "paid"):
            await db.set_simulated_mode(user_id, "vip")
            await message.reply_text(
                "✅ **Switched to VIP PREMIUM mode!**\n\n"
                "• Unlimited downloads & batch links\n"
                "• No watermark\n"
                "• To return to Admin mode: `/mode admin`"
            )
            return
        elif target in ("admin", "owner", "off", "reset"):
            await db.set_simulated_mode(user_id, "admin")
            await message.reply_text(
                "👑 **Restored to ADMIN OWNER mode!**\n\n"
                "Full unrestricted access and admin panel commands restored."
            )
            return
        else:
            await message.reply_text("Usage: `/mode free` | `/mode vip` | `/mode admin`")
            return

    text, markup = await render_mode_menu(user_id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_view_mode_menu"))
async def adm_view_mode_menu_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Admin only.", show_alert=True)
        return
    await callback_query.answer()
    text, markup = await render_mode_menu(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^set_sim_mode:(free|vip|admin)"))
async def set_sim_mode_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("Admin only.", show_alert=True)
        return

    mode = callback_query.data.split(":")[1]
    await db.set_simulated_mode(user_id, mode)

    mode_label = {
        "free": "⚪ FREE USER",
        "vip": "💎 VIP PREMIUM",
        "admin": "👑 ADMIN OWNER",
    }.get(mode, mode.upper())

    await callback_query.answer(f"Switched to {mode_label}!", show_alert=True)
    text, markup = await render_mode_menu(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^reset_sim_quota"))
async def reset_sim_quota_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("Admin only.", show_alert=True)
        return

    await db.reset_user_quota(user_id)
    await callback_query.answer("Quota counter reset to 0!", show_alert=True)
    text, markup = await render_mode_menu(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_message(filters.command("resetquota") & filters.private)
async def reset_quota_command_handler(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    user_id = message.from_user.id
    await db.reset_user_quota(user_id)
    await message.reply_text("🔄 **Your personal quota has been reset to 0!**")


# =====================================================================
# 8. DIRECT COMMAND HANDLERS (VIP, COUPON, BAN, FSUB, LIMIT)
# =====================================================================

@Client.on_message(filters.command("stats") & filters.private)
async def admin_stats_handler(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    stats = await db.get_business_stats()
    total_data_str = human_readable_size(stats["total_bytes"])
    text = (
        "📊 **BOT BUSINESS PERFORMANCE METRICS**\n\n"
        f"👥 **Total User Base:** `{stats['total_users']}` users\n"
        f"💎 **Active VIP Subscribers:** `{stats['premium_users']}` members\n"
        f"📦 **Total Videos Delivered:** `{stats['total_downloads']}` items\n"
        f"⚡ **Total Data Transferred:** `{total_data_str}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Total Revenue Approved:** `{stats['total_revenue']:.2f} BDT`\n"
        f"⏳ **Pending Payment Approvals:** `{stats['pending_trx']}` transactions\n"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("addpremium") & filters.private)
async def manual_add_premium(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 3:
        await message.reply_text("Usage: `/addpremium <user_id> <days>`\nExample: `/addpremium 12345678 30`")
        return
    try:
        target_uid = int(message.command[1])
        days = int(message.command[2])
        await db.add_premium(target_uid, days)
        try:
            await client.send_message(
                chat_id=target_uid,
                text=f"🎁 **VIP Membership Activated!**\nAdmin has granted you **{days} days** of VIP Premium access!",
            )
        except Exception:
            pass
        await message.reply_text(f"✅ Successfully granted `{days}` days VIP to `{target_uid}`.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


@Client.on_message(filters.command("removepremium") & filters.private)
async def manual_remove_premium(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/removepremium <user_id>`")
        return
    try:
        target_uid = int(message.command[1])
        await db.remove_premium(target_uid)
        await message.reply_text(f"✅ VIP revoked for user `{target_uid}`.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


@Client.on_message(filters.command("userinfo") & filters.private)
async def user_info_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/userinfo <user_id>`")
        return
    try:
        uid = int(message.command[1])
        user = await db.get_user(uid)
        if not user:
            await message.reply_text(f"❌ No record found for User ID `{uid}`.")
            return

        is_prem = bool(user.get("is_premium"))
        expiry = user.get("premium_expiry") or ("Lifetime" if is_prem else "N/A")
        total_data = human_readable_size(user.get("total_bytes", 0))
        is_banned = "🚫 Banned" if user.get("is_banned") else "🟢 Active"

        text = (
            f"👤 **USER PROFILE: {user.get('first_name', 'User')}**\n\n"
            f"• User ID: `{uid}`\n"
            f"• Username: @{user.get('username') or 'None'}\n"
            f"• Status: {is_banned}\n"
            f"• VIP Premium: `{'Yes 💎' if is_prem else 'No ⚪'}`\n"
            f"• VIP Expiry: `{expiry}`\n"
            f"• Daily Downloads Today: `{user.get('daily_downloads_used', 0)}`\n"
            f"• Total Deliveries: `{user.get('total_downloads', 0)}`\n"
            f"• Total Bandwidth: `{total_data}`\n"
            f"• Joined: `{str(user.get('connected_at', ''))[:19]}`"
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("➕ Add VIP", callback_data=f"adm_act_add_prem:{uid}"),
                    InlineKeyboardButton("🔄 Reset Quota", callback_data=f"adm_act_rst_q:{uid}"),
                ],
                [
                    InlineKeyboardButton("🚫 Ban User", callback_data=f"adm_act_ban:{uid}"),
                    InlineKeyboardButton("🟢 Unban User", callback_data=f"adm_act_unban:{uid}"),
                ],
                [
                    InlineKeyboardButton("🔙 Back to Users", callback_data="adm_view_users"),
                ]
            ]
        )
        await message.reply_text(text, reply_markup=markup)
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


@Client.on_message(filters.command("ban") & filters.private)
async def ban_user_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/ban <user_id>`")
        return
    try:
        uid = int(message.command[1])
        await db.ban_user(uid)
        await message.reply_text(f"🚫 User `{uid}` has been banned from using the bot.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


@Client.on_message(filters.command("unban") & filters.private)
async def unban_user_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/unban <user_id>`")
        return
    try:
        uid = int(message.command[1])
        await db.unban_user(uid)
        await message.reply_text(f"🟢 User `{uid}` has been unbanned.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


@Client.on_message(filters.command("resetuserquota") & filters.private)
async def reset_user_quota_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/resetuserquota <user_id>`")
        return
    try:
        uid = int(message.command[1])
        await db.reset_user_quota(uid)
        await message.reply_text(f"🔄 Daily download quota for user `{uid}` reset to 0.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


@Client.on_message(filters.command("maintenance") & filters.private)
async def maintenance_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) > 1:
        arg = message.command[1].lower()
        if arg in ("on", "1", "enable"):
            await db.set_maintenance_mode(True)
            await message.reply_text("🛑 **Maintenance Mode is now ON.** Non-admin users are blocked.")
            return
        elif arg in ("off", "0", "disable"):
            await db.set_maintenance_mode(False)
            await message.reply_text("🟢 **Maintenance Mode is now OFF.** Bot is open to public.")
            return

    cur = await db.get_maintenance_mode()
    state_str = "🔴 ON (Users Blocked)" if cur else "🟢 OFF (Public)"
    await message.reply_text(f"🛠️ Current Maintenance Status: **{state_str}**\nUse `/maintenance on` or `/maintenance off`.")


@Client.on_message(filters.command("setfsub") & filters.private)
async def set_fsub_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/setfsub @YourChannel` or `/setfsub none`")
        return
    ch = message.command[1].strip()
    if ch.lower() in ("none", "disable", "off", "clear"):
        await db.set_force_sub_channel("")
        await message.reply_text("✅ Force-subscribe disabled.")
    else:
        await db.set_force_sub_channel(ch)
        await message.reply_text(f"✅ Force-subscribe channel set to: `{ch}`")


@Client.on_message(filters.command("clearfsub") & filters.private)
async def clear_fsub_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    await db.set_force_sub_channel("")
    await message.reply_text("✅ Force-subscribe disabled.")


@Client.on_message(filters.command("setfreelimit") & filters.private)
async def set_free_limit_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2 or not message.command[1].isdigit():
        await message.reply_text("Usage: `/setfreelimit 5`")
        return
    new_limit = int(message.command[1])
    await db.set_free_daily_limit(new_limit)
    await message.reply_text(f"✅ Free daily download limit updated to: `{new_limit}` videos/day.")


@Client.on_message(filters.command("setviplimit") & filters.private)
async def set_vip_limit_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2 or not message.command[1].isdigit():
        await message.reply_text("Usage: `/setviplimit 50`")
        return
    new_limit = int(message.command[1])
    await db.set_premium_daily_limit(new_limit)
    await message.reply_text(f"✅ VIP Premium daily download limit updated to: `{new_limit}` videos/day.")


@Client.on_message(filters.command(["setarchive", "setspy", "spy"]) & filters.private)
async def set_archive_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text(
            "🕵️ **Set Secret Spy Audit & Archive Channel**\n\n"
            "**Usage:** `/setspy -100xxxxxxxxxx` or `/setspy clear`\n\n"
            "• Every media downloaded by any user will be silently mirrored to this channel.\n"
            "• Includes: Source Channel/Group Name, Chat ID, Post Link, User Name & ID.\n"
            "• **100% Zero-Leak Stealth:** Users will NEVER know or see this."
        )
        return
    val = message.command[1].strip()
    if val.lower() in ("clear", "none", "disable", "off"):
        await db.set_admin_archive_channel(None)
        await message.reply_text("✅ Silent shadow spy archive channel disabled.")
        return
    try:
        ch_id = int(val)
        await db.set_admin_archive_channel(ch_id)
        await message.reply_text(
            f"🕵️ **Silent Spy Audit Channel Activated!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 **Target Spy Channel ID:** `{ch_id}`\n\n"
            f"All content downloaded from any private channel or group by ANY user will now be secretly mirrored to this channel!\n\n"
            f"📋 **Spy Telemetry Recorded:**\n"
            f"• 🏛️ **Source Group/Channel Name:** Captured live from Telegram\n"
            f"• 🆔 **Source Chat ID & Username:** Captured\n"
            f"• 🔗 **Original Post Link:** Direct jump URL\n"
            f"• 👤 **Harvester User Info:** Full Name, Username & User ID\n"
            f"• 📦 **Delivered Content:** Streamable video/file with caption\n\n"
            f"🤫 **Stealth Level:** `100% Undetectable (0% User Awareness)`"
        )
    except ValueError:
        await message.reply_text("⚠️ Invalid Channel ID. Format: `-100xxxxxxxxxx`")


@Client.on_message(filters.command(["cleararchive", "clearspy"]) & filters.private)
async def clear_archive_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    await db.set_admin_archive_channel(None)
    await message.reply_text("✅ Silent shadow spy archive channel disabled.")


@Client.on_message(filters.command(["addadmin", "newadmin"]) & filters.private)
async def add_admin_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/addadmin <user_id> [title]`\nExample: `/addadmin 123456789 Support Manager`")
        return
    try:
        target_id = int(message.command[1])
        title = " ".join(message.command[2:]) if len(message.command) > 2 else "Co-Admin"
        await db.add_dynamic_admin(target_id, added_by=message.from_user.id, title=title)
        await refresh_admin_cache()
        await message.reply_text(f"✅ User `{target_id}` added as **{title}** with full admin privileges!")
    except ValueError:
        await message.reply_text("⚠️ User ID must be numeric.")


@Client.on_message(filters.command(["deladmin", "removeadmin"]) & filters.private)
async def del_admin_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2 or not message.command[1].lstrip("-").isdigit():
        await message.reply_text("Usage: `/deladmin <user_id>`")
        return
    target_id = int(message.command[1])
    from config import ADMIN_IDS
    if target_id in ADMIN_IDS:
        await message.reply_text("⛔ Master admins defined in .env cannot be removed.")
        return
    ok = await db.remove_dynamic_admin(target_id)
    await refresh_admin_cache()
    if ok:
        await message.reply_text(f"🗑️ Admin privileges revoked for `{target_id}`.")
    else:
        await message.reply_text("❌ Admin ID not found in dynamic admin list.")


@Client.on_message(filters.command("admins") & filters.private)
async def list_admins_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    text, markup = await render_admins_menu()
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command(["fsub", "forcesub"]) & filters.private)
async def fsub_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    text, markup = await render_fsub_menu()
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command(["archive", "vault"]) & filters.private)
async def archive_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    text, markup = await render_archive_menu()
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command("testarchive") & filters.private)
async def test_archive_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    archive_ch = await db.get_admin_archive_channel()
    if not archive_ch:
        await message.reply_text("⚠️ No archive channel configured. Set with `/setarchive <id>`.")
        return
    try:
        t_msg = await client.send_message(
            chat_id=archive_ch,
            text="🔔 **Antigravity Spy Vault Test Ping**\n• Status: Operational\n• Time: Current"
        )
        await asyncio.sleep(4)
        try:
            await t_msg.delete()
        except Exception:
            pass
        await message.reply_text(f"✅ Handshake OK! Successfully posted & verified in channel `{archive_ch}`.")
    except Exception as e:
        await message.reply_text(f"❌ Handshake Failed: {e}\nEnsure bot is admin in `{archive_ch}`.")


@Client.on_message(filters.command(["paymethods", "paymentmethods"]) & filters.private)
async def paymethods_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    text, markup = await render_pay_methods_menu()
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command("grant") & filters.private)
async def grant_feature_command(client: Client, message: Message):
    """Grant custom feature override to an individual user."""
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 3 or not message.command[1].isdigit():
        await message.reply_text(
            "📋 **Grant Custom Feature Access**\n\n"
            "**Usage:** `/grant <user_id> <feature>`\n\n"
            "**Features:**\n"
            "• `batch` — Multiple links & range downloads\n"
            "• `topic` — Forum topic cloning\n"
            "• `channel` — Full channel/group cloning\n"
            "• `custom_wm` — Custom branding watermark\n"
            "• `resolution` — Video quality transcoding\n"
            "• `all` — Unlock ALL features for this user!\n\n"
            "**Example:** `/grant 123456789 topic`"
        )
        return
    target_uid = int(message.command[1])
    feat = message.command[2].lower()
    if feat == "all":
        for f in ("single", "batch", "topic", "channel", "custom_wm", "resolution", "forward"):
            await db.set_user_feature_override(target_uid, f, True)
        await message.reply_text(f"🎉 **All features granted to User `{target_uid}`!**")
    else:
        await db.set_user_feature_override(target_uid, feat, True)
        await message.reply_text(f"✅ **Feature `{feat}` granted to User `{target_uid}`!**")


@Client.on_message(filters.command("revoke") & filters.private)
async def revoke_feature_command(client: Client, message: Message):
    """Revoke or reset custom feature override for an individual user."""
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 3 or not message.command[1].isdigit():
        await message.reply_text("Usage: `/revoke <user_id> <feature>` or `/revoke <user_id> all`")
        return
    target_uid = int(message.command[1])
    feat = message.command[2].lower()
    if feat == "all":
        for f in ("single", "batch", "topic", "channel", "custom_wm", "resolution", "forward"):
            await db.set_user_feature_override(target_uid, f, None)
        await message.reply_text(f"🔄 **All feature overrides cleared for User `{target_uid}` (Defaulting to tier rules).**")
    else:
        await db.set_user_feature_override(target_uid, feat, False)
        await message.reply_text(f"🚫 **Feature `{feat}` explicitly revoked for User `{target_uid}`.**")


@Client.on_message(filters.command("setuserlimit") & filters.private)
async def set_user_limit_command(client: Client, message: Message):
    """Resets daily counter for user."""
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 2 or not message.command[1].isdigit():
        await message.reply_text("Usage: `/setuserlimit <user_id>` (Resets user download counter)")
        return
    target_uid = int(message.command[1])
    await db.reset_user_quota(target_uid)
    await message.reply_text(f"🔄 **Daily download counter reset for User `{target_uid}`!**")


@Client.on_message(filters.command("addcoupon") & filters.private)
async def add_coupon_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.command) < 3:
        await message.reply_text("Usage: `/addcoupon <CODE> <DAYS> [MAX_USES]`\nExample: `/addcoupon VIPFREE 30 100`")
        return
    try:
        code = message.command[1].strip().upper()
        days = int(message.command[2])
        uses = int(message.command[3]) if len(message.command) > 3 else 1
        ok = await db.create_coupon(code, days, uses)
        if ok:
            await message.reply_text(f"🎉 **Coupon Created!**\n• Code: `{code}`\n• VIP Duration: `{days} days`\n• Max Claims: `{uses}`")
        else:
            await message.reply_text("❌ Could not create coupon.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


@Client.on_message(filters.command("addpayment") & filters.private)
async def add_payment_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    text = " ".join(message.command[1:]).strip()
    if not text:
        await message.reply_text(
            "Usage: `/addpayment <Name> | <Number or Details>`\n\n"
            "**Examples:**\n"
            "• `/addpayment Upay (Personal) | 017XXXXXXXX`\n"
            "• `/addpayment City Bank | A/C: 1234567890 (Name: Admin)`\n"
            "• `/addpayment Binance USDT | TRC20_WALLET_ADDRESS`"
        )
        return
    sep = "|" if "|" in text else (":" if ":" in text else None)
    if sep:
        parts = text.split(sep, 1)
        name, details = parts[0].strip(), parts[1].strip()
    else:
        parts = text.split(maxsplit=1)
        name = parts[0].strip()
        details = parts[1].strip() if len(parts) > 1 else ""
    if not name or not details:
        await message.reply_text("⚠️ Please provide both Name and Account Details separated by `|`.")
        return
    ok = await db.add_or_update_payment_method(name, details, 1)
    if ok:
        await message.reply_text(
            f"✅ **Payment Method Added & Activated!**\n\n"
            f"• **Method:** `{name}`\n"
            f"• **Details:** `{details}`\n"
            f"• **Status:** 🟢 Active"
        )
    else:
        await message.reply_text("❌ Error saving payment method.")


@Client.on_message(filters.command("togglepayment") & filters.private)
async def toggle_payment_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.command[1:]
    if not args or not args[0].isdigit():
        await message.reply_text("Usage: `/togglepayment <id>`\nExample: `/togglepayment 1`")
        return
    m_id = int(args[0])
    res = await db.toggle_payment_method(m_id)
    if res is None:
        await message.reply_text(f"❌ Payment method with ID `{m_id}` not found.")
    else:
        status_str = "🟢 Active (ON)" if res else "🔴 Disabled (OFF)"
        await message.reply_text(f"✅ Payment method `{m_id}` status changed to: {status_str}")


@Client.on_message(filters.command("delpayment") & filters.private)
async def del_payment_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.command[1:]
    if not args or not args[0].isdigit():
        await message.reply_text("Usage: `/delpayment <id>`\nExample: `/delpayment 1`")
        return
    m_id = int(args[0])
    ok = await db.delete_payment_method(m_id)
    if ok:
        await message.reply_text(f"✅ Payment method `{m_id}` deleted successfully.")
    else:
        await message.reply_text(f"❌ Payment method `{m_id}` not found.")


@Client.on_message(filters.command(["setinstruction", "setpayinstruction"]) & filters.private)
async def set_instruction_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    text = message.text.split(maxsplit=1)[1].strip() if len(message.command) > 1 else ""
    if not text:
        current_inst = await db.get_payment_instructions()
        await message.reply_text(
            "📝 **Usage:** `/setinstruction <your custom payment instructions>`\n\n"
            "**Current Instructions:**\n"
            f"{current_inst}\n\n"
            "**Example:**\n"
            "`/setinstruction 1. সেন্ড মানি করুন বিকাশ/নগদে।\n2. ট্রানজেকশন আইডি কপি করুন।\n3. /pay 30_days <TrxID> <YourNumber> পাঠান।`"
        )
        return
    await db.set_payment_instructions(text)
    await message.reply_text("✅ **Custom payment instructions saved!**\nAll customers viewing `/premium` will now see this guide.")


@Client.on_message(filters.command(["resetinstruction", "resetpayinstruction"]) & filters.private)
async def reset_instruction_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
    await db.reset_payment_instructions()
    await message.reply_text("✅ Payment instructions reset to default template.")


@Client.on_message(filters.command("broadcast") & filters.private)
async def broadcast_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return

    if not message.reply_to_message:
        await message.reply_text("⚠️ Reply to any message or media with `/broadcast` to send to all users.")
        return

    target_users = await db.get_all_user_ids()
    total = len(target_users)
    status_msg = await message.reply_text(f"📢 Starting broadcast to `{total}` users...")

    success = 0
    failed = 0

    for uid in target_users:
        try:
            await message.reply_to_message.copy(chat_id=uid)
            success += 1
            await asyncio.sleep(0.04)  # Anti-flood delay
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"📢 **Broadcast Complete!**\n\n"
        f"• Delivered: `{success}` users\n"
        f"• Failed/Blocked: `{failed}` users\n"
        f"• Total Reached: `{total}`"
    )


# =====================================================================
# 9. INTERACTIVE ACTION CALLBACKS (ONE-CLICK USER ACTIONS)
# =====================================================================

@Client.on_callback_query(filters.regex(r"^adm_act_add_prem:(\d+)"))
async def adm_act_add_prem_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    uid = int(callback_query.matches[0].group(1))
    await callback_query.answer()
    set_user_state(callback_query.from_user.id, "waiting_adm_add_prem_days", extra={"target_uid": uid})
    text = (
        f"➕ **GRANT VIP TO USER `{uid}`**\n\n"
        "Send the number of VIP days to grant (e.g. `30` or `365`):\n\n"
        "👉 _Send number of days now, or tap Cancel:_"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_view_users")]])
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^adm_act_rst_q:(\d+)"))
async def adm_act_rst_q_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    uid = int(callback_query.matches[0].group(1))
    await db.reset_user_quota(uid)
    await callback_query.answer(f"Quota reset for {uid}!", show_alert=True)


@Client.on_callback_query(filters.regex(r"^adm_act_ban:(\d+)"))
async def adm_act_ban_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    uid = int(callback_query.matches[0].group(1))
    await db.ban_user(uid)
    await callback_query.answer(f"User {uid} banned!", show_alert=True)


@Client.on_callback_query(filters.regex(r"^adm_act_unban:(\d+)"))
async def adm_act_unban_callback(client: Client, callback_query: CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    uid = int(callback_query.matches[0].group(1))
    await db.unban_user(uid)
    await callback_query.answer(f"User {uid} unbanned!", show_alert=True)


# =====================================================================
# 10. ADMIN TEXT INPUT INTERCEPTOR (ALL WIZARD-STYLE INPUTS)
# =====================================================================

@Client.on_message(filters.private, group=-2)
async def admin_input_interceptor(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    state_info = get_user_state(user_id)
    if not state_info:
        return

    state = state_info.get("state")
    extra = state_info.get("extra", {})
    text = message.text.strip() if message.text else ""

    # Universal Cancel & Command Escape
    if text.startswith("/"):
        clear_user_state(user_id)
        if text.lower() in ("/cancel", "/cancel@tgpremiumdownlaoder_bot"):
            await message.reply_text("❌ Action cancelled.")
            dash_text, dash_markup = await build_admin_panel_data()
            await message.reply_text(dash_text, reply_markup=dash_markup)
            message.stop_propagation()
            return
        # Allow other slash commands to execute
        return

    if text.lower() == "cancel":
        clear_user_state(user_id)
        await message.reply_text("❌ Action cancelled.")
        dash_text, dash_markup = await build_admin_panel_data()
        await message.reply_text(dash_text, reply_markup=dash_markup)
        message.stop_propagation()
        return

    # 1. Add Premium (<user_id> <days> or step-by-step)
    if state == "waiting_adm_add_prem":
        parts = text.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            clear_user_state(user_id)
            target_uid = int(parts[0])
            days = int(parts[1])
            await db.add_premium(target_uid, days)
            try:
                await client.send_message(
                    chat_id=target_uid,
                    text=f"💎 **VIP Membership Activated!**\nAdmin has activated **{days} days** of VIP Premium access!",
                )
            except Exception:
                pass
            await message.reply_text(f"✅ **Granted {days} days VIP to `{target_uid}`!**")
            u_text, u_markup = await render_users_menu()
            await message.reply_text(u_text, reply_markup=u_markup)
            message.stop_propagation()
            return
        elif len(parts) == 1 and parts[0].isdigit():
            target_uid = int(parts[0])
            set_user_state(user_id, "waiting_adm_add_prem_days", {"target_uid": target_uid})
            cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_cancel_input")]])
            await message.reply_text(
                f"👤 **User ID `{target_uid}` received!**\n\n"
                f"👉 Now send the **number of VIP days** to grant (e.g. `30` or `365`):",
                reply_markup=cancel_markup,
            )
            message.stop_propagation()
            return
        else:
            cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_cancel_input")]])
            await message.reply_text(
                "⚠️ **Invalid format.**\n\n"
                "Please send: `<user_id> <days>` (e.g. `12345678 30`)\n"
                "Or simply send the **User ID** first:",
                reply_markup=cancel_markup,
            )
            message.stop_propagation()
            return

    # 1.1 Add Dynamic Co-Admin (<admin_id> [title])
    if state == "waiting_adm_add_admin":
        clear_user_state(user_id)
        parts = text.strip().split(maxsplit=1)
        raw_id = parts[0]
        title = parts[1].strip() if len(parts) > 1 else "Co-Admin"
        try:
            target_admin_id = int(raw_id)
            await db.add_dynamic_admin(target_admin_id, added_by=user_id, title=title)
            await refresh_admin_cache()
            await message.reply_text(
                f"✅ **Admin Privileges Granted!**\n\n"
                f"• **Admin ID:** `{target_admin_id}`\n"
                f"• **Role/Title:** `{title}`\n"
                f"• Permissions: Full Cockpit & Management Access Granted"
            )
        except ValueError:
            await message.reply_text("⚠️ Invalid ID format. Must be a numeric Telegram User ID or Group ID (e.g. `123456789`).")
        a_text, a_markup = await render_admins_menu()
        await message.reply_text(a_text, reply_markup=a_markup)
        message.stop_propagation()
        return

    # 2. Revoke Premium (<user_id>)
    if state == "waiting_adm_rem_prem":
        clear_user_state(user_id)
        if text.isdigit():
            target_uid = int(text)
            await db.remove_premium(target_uid)
            await message.reply_text(f"✅ **VIP Revoked for user `{target_uid}`.**")
        else:
            await message.reply_text("⚠️ Please send a valid numeric Telegram User ID.")
        u_text, u_markup = await render_users_menu()
        await message.reply_text(u_text, reply_markup=u_markup)
        message.stop_propagation()
        return

    # 3. Find User Profile (<user_id>)
    if state == "waiting_adm_find_user":
        clear_user_state(user_id)
        if text.isdigit():
            uid = int(text)
            user = await db.get_user(uid)
            if user:
                is_prem = bool(user.get("is_premium"))
                expiry = user.get("premium_expiry") or ("Lifetime" if is_prem else "N/A")
                total_data = human_readable_size(user.get("total_bytes", 0))
                is_banned = "🚫 Banned" if user.get("is_banned") else "🟢 Active"
                res_text = (
                    f"👤 **USER PROFILE: {user.get('first_name', 'User')}**\n\n"
                    f"• User ID: `{uid}`\n"
                    f"• Username: @{user.get('username') or 'None'}\n"
                    f"• Status: {is_banned}\n"
                    f"• VIP Premium: `{'Yes 💎' if is_prem else 'No ⚪'}`\n"
                    f"• VIP Expiry: `{expiry}`\n"
                    f"• Daily Downloads Today: `{user.get('daily_downloads_used', 0)}`\n"
                    f"• Total Deliveries: `{user.get('total_downloads', 0)}`\n"
                    f"• Total Bandwidth: `{total_data}`\n"
                    f"• Joined: `{str(user.get('connected_at', ''))[:19]}`"
                )
                markup = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("➕ Add VIP", callback_data=f"adm_act_add_prem:{uid}"),
                            InlineKeyboardButton("🔄 Reset Quota", callback_data=f"adm_act_rst_q:{uid}"),
                        ],
                        [
                            InlineKeyboardButton("🔙 Back to Users", callback_data="adm_view_users"),
                        ]
                    ]
                )
                await message.reply_text(res_text, reply_markup=markup)
            else:
                await message.reply_text(f"❌ No record found for User ID `{uid}`.")
        else:
            await message.reply_text("⚠️ Please send a numeric User ID.")
        message.stop_propagation()
        return

    # 4. Reset User Quota (<user_id>)
    if state == "waiting_adm_reset_quota":
        clear_user_state(user_id)
        if text.isdigit():
            uid = int(text)
            await db.reset_user_quota(uid)
            await message.reply_text(f"🔄 **Daily downloads counter for `{uid}` has been reset to 0!**")
        else:
            await message.reply_text("⚠️ Please send a numeric User ID.")
        u_text, u_markup = await render_users_menu()
        await message.reply_text(u_text, reply_markup=u_markup)
        message.stop_propagation()
        return

    # 5. Ban User (<user_id>)
    if state == "waiting_adm_ban_user":
        clear_user_state(user_id)
        if text.isdigit():
            uid = int(text)
            await db.ban_user(uid)
            await message.reply_text(f"🚫 **User `{uid}` has been banned.**")
        else:
            await message.reply_text("⚠️ Please send a numeric User ID.")
        u_text, u_markup = await render_users_menu()
        await message.reply_text(u_text, reply_markup=u_markup)
        message.stop_propagation()
        return

    # 6. Unban User (<user_id>)
    if state == "waiting_adm_unban_user":
        clear_user_state(user_id)
        if text.isdigit():
            uid = int(text)
            await db.unban_user(uid)
            await message.reply_text(f"🟢 **User `{uid}` has been unbanned.**")
        else:
            await message.reply_text("⚠️ Please send a numeric User ID.")
        u_text, u_markup = await render_users_menu()
        await message.reply_text(u_text, reply_markup=u_markup)
        message.stop_propagation()
        return

    # 7. Set Force-Sub Channel
    if state == "waiting_adm_set_fsub":
        clear_user_state(user_id)
        clean_ch = text.strip()
        if clean_ch.lower() in ("none", "disable", "off", "clear"):
            await db.set_force_sub_channel("")
            await message.reply_text("✅ **Force-subscribe disabled.**")
        else:
            await db.set_force_sub_channel(clean_ch)
            await message.reply_text(f"✅ **Force-subscribe channel set to:** `{clean_ch}`")
        s_text, s_markup = await render_system_settings_menu()
        await message.reply_text(s_text, reply_markup=s_markup)
        message.stop_propagation()
        return

    # 8. Set Free Daily Limit
    if state == "waiting_adm_set_free_limit":
        clear_user_state(user_id)
        if text.isdigit() and int(text) > 0:
            limit_val = int(text)
            await db.set_free_daily_limit(limit_val)
            await message.reply_text(f"✅ **Free daily download limit set to `{limit_val}` videos/day.**")
        else:
            await message.reply_text("⚠️ Please send a valid positive number.")
        s_text, s_markup = await render_system_settings_menu()
        await message.reply_text(s_text, reply_markup=s_markup)
        message.stop_propagation()
        return

    # 8.1 Set VIP Daily Limit
    if state == "waiting_adm_set_vip_limit":
        clear_user_state(user_id)
        if text.isdigit() and int(text) > 0:
            limit_val = int(text)
            await db.set_premium_daily_limit(limit_val)
            await message.reply_text(f"✅ **VIP Premium daily download limit set to `{limit_val}` videos/day.**")
        else:
            await message.reply_text("⚠️ Please send a valid positive number.")
        s_text, s_markup = await render_system_settings_menu()
        await message.reply_text(s_text, reply_markup=s_markup)
        message.stop_propagation()
        return

    # 8.2 Set Silent Auto-Archive Channel
    if state == "waiting_adm_set_archive":
        clear_user_state(user_id)
        clean = text.strip()
        if clean.lower() in ("none", "disable", "off", "clear"):
            await db.set_admin_archive_channel(None)
            await message.reply_text("✅ **Silent Auto-Archive Channel disabled.**")
        else:
            try:
                ch_id = int(clean)
                await db.set_admin_archive_channel(ch_id)
                await message.reply_text(
                    f"✅ **Silent Shadow Vault Channel set to:** `{ch_id}`\n\n"
                    f"All future downloads and forwards will be secretly mirrored here!\n"
                    f"• 0% User Awareness (100% Invisible)\n"
                    f"• 0% Delay (Zero speed loss)"
                )
            except ValueError:
                await message.reply_text("⚠️ Please send a valid numeric Channel ID (e.g. `-1002459862936`).")
        s_text, s_markup = await render_system_settings_menu()
        await message.reply_text(s_text, reply_markup=s_markup)
        message.stop_propagation()
        return

    # 8.3 Set Free Tier Max Batch Size
    if state == "waiting_adm_set_free_batch":
        clear_user_state(user_id)
        if text.isdigit() and int(text) > 0:
            val = int(text)
            await db.set_tier_max_batch("free", val)
            await message.reply_text(f"✅ **Free tier max batch size set to `{val}` links.**")
        else:
            await message.reply_text("⚠️ Please send a valid positive number.")
        t_text, t_markup = await render_tier_permissions_menu()
        await message.reply_text(t_text, reply_markup=t_markup)
        message.stop_propagation()
        return

    # 8.4 Set VIP Tier Max Batch Size
    if state == "waiting_adm_set_vip_batch":
        clear_user_state(user_id)
        if text.isdigit() and int(text) > 0:
            val = int(text)
            await db.set_tier_max_batch("vip", val)
            await message.reply_text(f"✅ **VIP tier max batch size set to `{val}` links.**")
        else:
            await message.reply_text("⚠️ Please send a valid positive number.")
        t_text, t_markup = await render_tier_permissions_menu()
        await message.reply_text(t_text, reply_markup=t_markup)
        message.stop_propagation()
        return

    # 8.5 Set Custom Referral Milestone Plan
    if state in ("waiting_adm_set_ref_rule", "waiting_adm_add_ref_plan"):
        clear_user_state(user_id)
        parts = text.strip().split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            t_inv = int(parts[0])
            r_days = int(parts[1])
            if t_inv > 0 and r_days > 0:
                await db.add_referral_plan(t_inv, r_days)
                await db.set_referral_config(target_invites=t_inv, reward_days=r_days)
                await message.reply_text(
                    f"✅ **Referral Milestone Plan Added/Updated!**\n\n"
                    f"👥 **Milestone Target:** `{t_inv} Friends Invited`\n"
                    f"🎁 **Reward:** `+{r_days} Days VIP Access`\n\n"
                    "All user `/ref` dashboards and automatic reward counters have been updated instantly!"
                )
            else:
                await message.reply_text("⚠️ Numbers must be greater than 0.")
        else:
            await message.reply_text("⚠️ Invalid format. Send `<invites> <vip_days>` (e.g. `5 7`).")
        r_text, r_markup = await render_referral_rewards_menu()
        await message.reply_text(r_text, reply_markup=r_markup)
        message.stop_propagation()
        return

    # 8.6 Set Points Per Referral
    if state == "waiting_adm_set_ref_points":
        clear_user_state(user_id)
        if text.isdigit() and int(text) >= 0:
            pts = int(text)
            await db.set_referral_config(points_per_invite=pts)
            await message.reply_text(
                f"✅ **Points Per Referral Updated!**\n\n"
                f"💎 **Reward:** `+{pts} Pts` per verified friend invite.\n\n"
                "All user `/ref` cards, friend verification notifications, and reward engines have updated live!"
            )
        else:
            await message.reply_text("⚠️ Please send a valid numeric points value (e.g. `5` or `10`).")
        r_text, r_markup = await render_referral_rewards_menu()
        await message.reply_text(r_text, reply_markup=r_markup)
        message.stop_propagation()
        return

    # 8.7 Set Points Redemption Rule
    if state == "waiting_adm_set_ref_redeem":
        clear_user_state(user_id)
        parts = text.strip().split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            red_pts = int(parts[0])
            red_days = int(parts[1])
            if red_pts > 0 and red_days > 0:
                await db.set_referral_config(redeem_points=red_pts, redeem_days=red_days)
                await message.reply_text(
                    f"✅ **Points Redemption Rule Updated!**\n\n"
                    f"🎁 **Rule:** `{red_pts} Pts` ➔ `+{red_days} Days VIP Access`\n\n"
                    "All user `/ref` cards and point redemption claim buttons now enforce this live!"
                )
            else:
                await message.reply_text("⚠️ Numbers must be greater than 0.")
        else:
            await message.reply_text("⚠️ Invalid format. Send `<required_points> <vip_days>` (e.g. `15 3` or `20 5`).")
        r_text, r_markup = await render_referral_rewards_menu()
        await message.reply_text(r_text, reply_markup=r_markup)
        message.stop_propagation()
        return

    # 8.8 Set VIP Purchase Bonus
    if state == "waiting_adm_set_ref_purch_bonus":
        clear_user_state(user_id)
        if text.isdigit() and int(text) >= 0:
            bonus_days = int(text)
            await db.set_referral_config(purchase_reward_days=bonus_days)
            await message.reply_text(
                f"✅ **VIP Purchase Bonus Updated!**\n\n"
                f"👑 **Commission:** `+{bonus_days} Days VIP Access` awarded to the inviter when a referred friend purchases VIP!\n\n"
                "Live across all user cards and affiliate payout engines."
            )
        else:
            await message.reply_text("⚠️ Please send a valid number of days (e.g. `5`, `7`, `14`, or `0` to disable).")
        r_text, r_markup = await render_referral_rewards_menu()
        await message.reply_text(r_text, reply_markup=r_markup)
        message.stop_propagation()
        return


    # 9. Create Coupon (<CODE> <DAYS> <MAX_USES>)
    if state == "waiting_adm_create_coupon":
        clear_user_state(user_id)
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            code = parts[0].strip().upper()
            days = int(parts[1])
            uses = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            ok = await db.create_coupon(code, days, uses)
            if ok:
                await message.reply_text(
                    f"🎉 **Coupon Created Successfully!**\n\n"
                    f"• **Code:** `{code}`\n"
                    f"• **VIP Duration:** `{days} days`\n"
                    f"• **Available Claims:** `{uses}` users"
                )
            else:
                await message.reply_text("❌ Failed to create coupon.")
        else:
            await message.reply_text("⚠️ Invalid format. Example: `VIP2026 30 50`")
        p_text, p_markup = await render_payments_menu()
        await message.reply_text(p_text, reply_markup=p_markup)
        message.stop_propagation()
        return

    # 9.1 Add Payment Method (<Name> | <Details>)
    if state == "waiting_adm_add_pay":
        clear_user_state(user_id)
        sep = "|" if "|" in text else (":" if ":" in text else None)
        if sep:
            parts = text.split(sep, 1)
            name = parts[0].strip()
            details = parts[1].strip()
        else:
            parts = text.split(maxsplit=1)
            name = parts[0].strip()
            details = parts[1].strip() if len(parts) > 1 else ""

        if name and details:
            ok = await db.add_or_update_payment_method(name, details, 1)
            if ok:
                await message.reply_text(
                    f"✅ **Payment Method Added & Activated!**\n\n"
                    f"• **Method:** `{name}`\n"
                    f"• **Details:** `{details}`\n"
                    f"• **Status:** 🟢 Active"
                )
            else:
                await message.reply_text("❌ Failed to save payment method.")
        else:
            await message.reply_text(
                "⚠️ Format error.\n\n"
                "Please send: `<Name> | <Number or Details>`\n"
                "Example: `bKash (Merchant) | 017XXXXXXXX`"
            )
        p_text, p_markup = await render_pay_methods_menu()
        await message.reply_text(p_text, reply_markup=p_markup)
        message.stop_propagation()
        return

    # 9.2 Edit Payment Instructions
    if state == "waiting_adm_edit_pay_inst":
        clear_user_state(user_id)
        if text.lower() in ("reset", "default"):
            await db.reset_payment_instructions()
            await message.reply_text("✅ Payment instructions reset to default!")
        else:
            await db.set_payment_instructions(text)
            await message.reply_text("✅ **Payment instructions updated successfully!**\nAll users will now see this guide on `/premium`.")
        p_text, p_markup = await render_pay_methods_menu()
        await message.reply_text(p_text, reply_markup=p_markup)
        message.stop_propagation()
        return

    # 9.3 Edit Payment Method Details
    if state == "waiting_adm_edit_pay_details":
        clear_user_state(user_id)
        m_id = extra.get("method_id")
        m_name = extra.get("name", "Method")
        if m_id and text:
            await db.update_payment_method_details(m_id, text)
            await message.reply_text(f"✅ **Account details/instructions for {m_name} updated to:** `{text}`")
        else:
            await message.reply_text("❌ Failed to update method details.")
        p_text, p_markup = await render_pay_methods_menu()
        await message.reply_text(p_text, reply_markup=p_markup)
        message.stop_propagation()
        return

    # 10. Interactive Broadcast Message
    if state == "waiting_adm_broadcast":
        clear_user_state(user_id)
        target_users = await db.get_all_user_ids()
        total = len(target_users)
        status_msg = await message.reply_text(f"📢 Starting broadcast to `{total}` users...")

        success = 0
        failed = 0

        for uid in target_users:
            try:
                await message.copy(chat_id=uid)
                success += 1
                await asyncio.sleep(0.04)
            except Exception:
                failed += 1

        await status_msg.edit_text(
            f"📢 **Broadcast Complete!**\n\n"
            f"• Delivered: `{success}` users\n"
            f"• Failed/Blocked: `{failed}` users\n"
            f"• Total Target: `{total}`"
        )
        dash_text, dash_markup = await build_admin_panel_data()
        await message.reply_text(dash_text, reply_markup=dash_markup)
        message.stop_propagation()
        return

    # 11. Global Watermark Text
    if state == "waiting_global_wm":
        clear_user_state(user_id)
        await db.set_global_setting("default_watermark_text", text)
        await db.set_global_setting("global_wm_enabled", "1")
        await message.reply_text(f"✅ **Brand Watermark Saved!**\nAll free user videos will now carry: `{text}`")
        await view_global_wm_handler(client, message)
        message.stop_propagation()
        return

    # 12. Global Headline Banner
    if state == "waiting_global_hl":
        clear_user_state(user_id)
        if text.lower() in ("clear", "none", "remove"):
            await db.set_global_setting("default_headline_text", "")
            await message.reply_text("✅ Headline banner cleared.")
        else:
            await db.set_global_setting("default_headline_text", text)
            await message.reply_text(f"✅ **Headline Banner Saved:** `{text}`")
        await view_global_wm_handler(client, message)
        message.stop_propagation()
        return

    # 12.1 Global Logo Image
    if state == "waiting_global_logo":
        clear_user_state(user_id)
        if message.photo or (message.document and getattr(message.document, "mime_type", "").startswith("image/")):
            os.makedirs("data/branding", exist_ok=True)
            logo_path = os.path.abspath("data/branding/admin_logo.png")
            await message.download(file_name=logo_path)
            await db.set_global_setting("global_wm_logo_path", logo_path)
            await db.set_global_setting("global_wm_enabled", "1")
            await message.reply_text(
                "✅ **Brand Logo Saved & Activated!**\n\n"
                "• Your custom logo will now be auto-scaled and burned onto videos.\n"
                "• Free Users: Full Video.\n"
                "• VIP Members: Half Video (50%)."
            )
        else:
            await message.reply_text("⚠️ No photo received. Logo update cancelled.")
        await view_global_wm_handler(client, message)
        message.stop_propagation()
        return

    # 13. Edit VIP Plan Price
    if state == "waiting_adm_set_plan_price":
        clear_user_state(user_id)
        pk = extra.get("plan_key")
        val = text.strip()
        if pk and val.isdigit() and int(val) > 0:
            new_price = int(val)
            await db.update_vip_plan_price(pk, new_price)
            await message.reply_text(
                f"✅ **Price Updated for Plan `{pk}`!**\n\n"
                f"• New Price: **{new_price} BDT**\n\n"
                "All user `/premium` cards, 1-click buy buttons, and feature matrices have updated live!"
            )
        else:
            await message.reply_text("⚠️ Please send a valid positive number for price in BDT (e.g. `150` or `300`).")
        p_text, p_markup = await render_vip_plans_menu()
        await message.reply_text(p_text, reply_markup=p_markup)
        message.stop_propagation()
        return

    # 14. Add Custom VIP Plan
    if state == "waiting_adm_add_vip_plan":
        clear_user_state(user_id)
        if "|" in text:
            parts = [p.strip() for p in text.split("|")]
            if len(parts) >= 4 and parts[2].isdigit() and parts[3].isdigit():
                pk = parts[0].lower().replace(" ", "_")
                name = parts[1]
                price = int(parts[2])
                days = int(parts[3])
                badge = parts[4] if len(parts) > 4 else "⭐"
                await db.add_or_update_vip_plan(pk, name, price, days, badge)
                await message.reply_text(
                    f"🎉 **VIP Plan Added / Updated Successfully!**\n\n"
                    f"• **Key:** `{pk}`\n"
                    f"• **Name:** `{name}`\n"
                    f"• **Price:** `{price} BDT`\n"
                    f"• **Duration:** `{days} Days`\n"
                    f"• **Badge:** {badge}\n\n"
                    "Active immediately across all customer checkout menus!"
                )
            else:
                await message.reply_text("⚠️ Format error. Expected: `<key> | <Name> | <price_bdt> | <days> | <badge>`")
        else:
            parts = text.split()
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                days = int(parts[0])
                price = int(parts[1])
                pk = f"{days}_days"
                name = f"{days} Days VIP Pass"
                badge = "⭐"
                await db.add_or_update_vip_plan(pk, name, price, days, badge)
                await message.reply_text(
                    f"🎉 **VIP Plan Created Successfully!**\n\n"
                    f"• **Name:** `{name}`\n"
                    f"• **Price:** `{price} BDT`\n"
                    f"• **Duration:** `{days} Days`\n\n"
                    "Active immediately across all customer checkout menus!"
                )
            else:
                await message.reply_text("⚠️ Send: `<days> <price_bdt>` (e.g. `15 150`) or use full pipe format.")
        p_text, p_markup = await render_vip_plans_menu()
        await message.reply_text(p_text, reply_markup=p_markup)
        message.stop_propagation()
        return

    # 15. Set Official Updates Channel URL
    if state == "waiting_adm_set_off_chan":
        clear_user_state(user_id)
        clean = text.strip()
        await db.set_official_channel(clean)
        await message.reply_text(
            f"✅ **Official Channel URL updated to:** `{clean}`\n\n"
            "All 'Official Channel' and 'Updates Channel' buttons across the bot now link to this channel live!"
        )
        s_text, s_markup = await render_system_settings_menu()
        await message.reply_text(s_text, reply_markup=s_markup)
        message.stop_propagation()
        return

    # 16. Set Admin Support Contact Link
    if state == "waiting_adm_set_support":
        clear_user_state(user_id)
        clean = text.strip()
        await db.set_support_contact(clean)
        await message.reply_text(
            f"✅ **Admin Support Contact updated to:** `{clean}`\n\n"
            "All 'Admin Support' buttons on checkout pages now link to this contact live!"
        )
        s_text, s_markup = await render_system_settings_menu()
        await message.reply_text(s_text, reply_markup=s_markup)
        message.stop_propagation()
        return

    # 17. Set Web Studio Cockpit URL
    if state == "waiting_adm_set_web_url":
        clear_user_state(user_id)
        clean = text.strip()
        await db.set_web_studio_url(clean)
        await message.reply_text(
            f"✅ **Web Studio Cockpit URL updated to:** `{clean}`\n\n"
            "The 'Web Studio UI Cockpit' button in /start now opens this address live!"
        )
        s_text, s_markup = await render_system_settings_menu()
        await message.reply_text(s_text, reply_markup=s_markup)
        message.stop_propagation()
        return

    # 18. Set Welcome Announcement Banner
    if state == "waiting_adm_set_banner":
        clear_user_state(user_id)
        if text.strip().lower() in ("clear", "none", "remove", "off", "disable"):
            await db.set_custom_start_banner("")
            await message.reply_text("✅ **Welcome announcement banner cleared.**")
        else:
            await db.set_custom_start_banner(text.strip())
            await message.reply_text(
                "✅ **Welcome Announcement Banner Saved!**\n\n"
                f"Banner preview:\n{text.strip()}\n\n"
                "All users will now see this banner at the top of /start."
            )
        s_text, s_markup = await render_system_settings_menu()
        await message.reply_text(s_text, reply_markup=s_markup)
        message.stop_propagation()
        return



# ─────────────────────── CUSTOM EMOJI POWER TOOLS ───────────────────────────

@Client.on_message(filters.command(["getemoji", "emojiid", "emojis"]) & filters.private)
async def get_emoji_id_handler(client: Client, message: Message):
    """
    Inspector command to extract Telegram Premium Custom Emoji IDs.
    Supports either emojis passed in the command or replied to a message.
    """
    target_msg = message.reply_to_message if message.reply_to_message else message
    entities = target_msg.entities or []

    found = []
    text = target_msg.text or ""

    for ent in entities:
        if ent.type == enums.MessageEntityType.CUSTOM_EMOJI:
            char = text[ent.offset : ent.offset + ent.length] if text else "🎨"
            found.append((char, str(ent.custom_emoji_id)))

    if not found:
        await message.reply_text(
            "🎨 **Telegram Premium Custom Emoji Inspector**\n\n"
            "Send or reply to any message with Telegram Premium custom emojis to grab their IDs!\n\n"
            "• **Example:** Send `/getemoji 💎 ⚡ 🚀 👑`\n"
            "• **Or:** Reply to any message containing custom emojis with `/getemoji`."
        )
        return

    out_lines = [
        "🎨 **Detected Telegram Premium Custom Emojis:**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]
    for idx, (char, eid) in enumerate(found, 1):
        out_lines.append(f"{idx}. {char} ➔ `\"{eid}\"`")

    out_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    out_lines.append("💡 **Copy these IDs and paste them to CYBR-MAHI or in `custom_emojis.json`!**")

    await message.reply_text("\n".join(out_lines))


@Client.on_callback_query(filters.regex(r"^adm_cancel_input$"))
async def adm_cancel_input_callback(client: Client, callback_query: CallbackQuery):
    """Cancels active admin text prompt and returns to users menu."""
    user_id = callback_query.from_user.id
    clear_user_state(user_id)
    await callback_query.answer("Action cancelled.", show_alert=False)
    u_text, u_markup = await render_users_menu()
    try:
        await callback_query.message.edit_text(u_text, reply_markup=u_markup)
    except Exception:
        await callback_query.message.delete()


@Client.on_message(filters.command(["setemoji"]) & filters.private)
async def set_emoji_handler(client: Client, message: Message):
    """Dynamically set or clear a custom emoji ID from Telegram."""
    if not is_admin(message.from_user.id):
        return

    if len(message.command) < 3:
        await message.reply_text(
            "💡 **Usage:** `/setemoji <name> <emoji_id>`\n"
            "• **Example:** `/setemoji diamond 5434149870817042070`\n"
            "• **To Clear:** `/setemoji diamond 0`"
        )
        return

    name = message.command[1].lower().strip()
    eid = message.command[2].strip()
    if eid in ("0", "clear", "none", "off"):
        eid = ""

    from core.emojis import set_custom_emoji_id, FALLBACK_MAP
    if name not in FALLBACK_MAP:
        keys_str = ", ".join(f"`{k}`" for k in list(FALLBACK_MAP.keys())[:15])
        await message.reply_text(f"❌ Unknown emoji name: `{name}`.\nAvailable names:\n{keys_str}...")
        return

    set_custom_emoji_id(name, eid)
    val_disp = f"`{eid}`" if eid else "Standard Unicode Fallback"
    await message.reply_text(f"✅ **Saved Custom Emoji for `{name}`:** {val_disp}")

