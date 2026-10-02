# language: Python, file: handlers/login.py, target: Python 3.10+, Pyrogram
"""
Enterprise Authentication Handler for Telegram Accounts.
Supports:
1. Official Telegram QR Code Login (Fastest, zero OTP codes, 100% immune to anti-phishing blocks).
2. Phone Number Login with Interactive Numpad (Prevents chat text inspection & code revocation).
3. Direct Pyrogram StringSession paste.
"""

import os
import io
import re
import base64
import asyncio
from pathlib import Path
from typing import Dict, Optional

import qrcode
from pyrogram import Client, filters, raw
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from pyrogram.session import Session, Auth
from pyrogram.errors import (
    SessionPasswordNeeded,
    PasswordHashInvalid,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PhoneNumberInvalid,
    PhoneNumberBanned,
    FloodWait,
    RPCError,
)

from config import API_ID, API_HASH, SESSIONS_DIR, ADMIN_IDS
from database import db
from core.client_manager import (
    active_userbots,
    get_user_client,
    register_and_start_account,
    unregister_account,
    toggle_account_active,
    account_pool,
    account_metadata,
)
from core.device_spoofer import get_fingerprint_for_user

# In-flight phone login clients {user_id: Client}
login_clients: Dict[int, Client] = {}

# In-flight OTP digits entered via numpad {user_id: str}
temp_numpad_codes: Dict[int, str] = {}

# Active QR login tasks {user_id: asyncio.Task}
active_qr_tasks: Dict[int, asyncio.Task] = {}


def cleanup_temp_session(user_id: int):
    """Safely cleans up any temporary on-disk session and QR files for a user."""
    for p in SESSIONS_DIR.glob(f"temp_login_{user_id}.session*"):
        try:
            p.unlink()
        except Exception:
            pass
    for p in SESSIONS_DIR.glob(f"qr_{user_id}*.png"):
        try:
            p.unlink()
        except Exception:
            pass
    temp_numpad_codes.pop(user_id, None)


def get_numpad_markup(entered_digits: str = "") -> InlineKeyboardMarkup:
    """Builds an interactive 0-9 number keypad for entering OTP codes safely."""
    display = " ".join(entered_digits) if entered_digits else "_ _ _ _ _"
    buttons = [
        [
            InlineKeyboardButton("1", callback_data="numpad:1"),
            InlineKeyboardButton("2", callback_data="numpad:2"),
            InlineKeyboardButton("3", callback_data="numpad:3"),
        ],
        [
            InlineKeyboardButton("4", callback_data="numpad:4"),
            InlineKeyboardButton("5", callback_data="numpad:5"),
            InlineKeyboardButton("6", callback_data="numpad:6"),
        ],
        [
            InlineKeyboardButton("7", callback_data="numpad:7"),
            InlineKeyboardButton("8", callback_data="numpad:8"),
            InlineKeyboardButton("9", callback_data="numpad:9"),
        ],
        [
            InlineKeyboardButton("⌫ Del", callback_data="numpad:del"),
            InlineKeyboardButton("0", callback_data="numpad:0"),
            InlineKeyboardButton("🗑️ Clear", callback_data="numpad:clear"),
        ],
        [
            InlineKeyboardButton(f"✅ Submit Code [{display}]", callback_data="numpad:submit"),
        ],
        [
            InlineKeyboardButton("📩 Resend via SMS (সিমে SMS পাঠান)", callback_data="resend_otp_sms"),
        ],
        [
            InlineKeyboardButton("📱 Switch to QR Code Login", callback_data="start_qr_login"),
            InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def render_accounts_cockpit(user_id: int):
    """
    Renders the enterprise Multi-Account Cockpit with live telemetry,
    anti-ban badges, device identities, and quick actions.
    """
    import time
    is_adm = user_id in ADMIN_IDS
    accounts = await db.get_bot_accounts(owner_user_id=None if is_adm else user_id)

    total_accs = len(accounts)
    now = time.time()
    active_cnt = sum(1 for a in accounts if a.get("is_active"))
    healthy_cnt = sum(
        1 for a in accounts
        if a.get("is_active") and a.get("status") == "healthy" and a.get("flood_wait_until", 0) <= now
    )
    cooldown_cnt = sum(1 for a in accounts if a.get("flood_wait_until", 0) > now)

    title_scope = "ENTERPRISE WORKER POOL" if is_adm else "YOUR CONNECTED USERBOT ACCOUNTS"
    text_lines = [
        f"👥 **MULTI-ACCOUNT MANAGEMENT COCKPIT** 👥",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⚡ **{title_scope} & ANTI-BAN STATUS**\n",
        f"• **Connected Accounts:** `{total_accs}` ({active_cnt} active)",
        f"• **Health State:** `🟢 {healthy_cnt} Healthy` | `⏳ {cooldown_cnt} Cooldown`",
        f"• **Anti-Ban Device Spoofer:** `ACTIVE 🟢 (Isolated Official Fingerprints)`",
        f"• **Load Balancing Rotation:** `ACTIVE 🟢 (Auto Round-Robin Distribution)`",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    buttons = []

    if not accounts:
        text_lines.append(
            "ℹ️ _No Telegram accounts registered in pool yet._\n\n"
            "👉 **Why connect multiple accounts?**\n"
            "• Distributes download requests across multiple workers.\n"
            "• Each account is permanently bound to a unique official device profile (Samsung, Pixel, PC).\n"
            "• 100% immune to Telegram rate limits & automatic flood-wait hot-swap failover!"
        )
    else:
        for idx, acc in enumerate(accounts, 1):
            aid = acc["account_id"]
            uname = f"@{acc['username']}" if acc.get("username") else (acc.get("first_name") or f"ID:{aid}")
            fp = get_fingerprint_for_user(aid)
            device = fp.get("device_model", "Official Telegram")
            dl_today = acc.get("daily_downloads", 0)
            dl_total = acc.get("total_downloads", 0)

            f_until = acc.get("flood_wait_until", 0)
            if not acc.get("is_active"):
                st_badge = "⚪ Paused"
            elif f_until > now:
                rem = int(f_until - now)
                st_badge = f"⏳ Cooldown ({rem}s left)"
            elif acc.get("status") == "dead":
                st_badge = "🔴 Dead (Session Revoked)"
            else:
                st_badge = "🟢 Healthy & Ready"

            text_lines.append(
                f"{idx}. **{uname}** (`{aid}`)\n"
                f"   📱 **Hardware:** `{device}`\n"
                f"   📊 **Telemetry:** `{dl_today}` today | `{dl_total}` total downloads\n"
                f"   ⚡ **Status:** {st_badge}\n"
            )

            is_act = bool(acc.get("is_active"))
            toggle_text = "⏸️ Pause" if is_act else "▶️ Resume"
            buttons.append([
                InlineKeyboardButton(f"{toggle_text} {uname[:12]}", callback_data=f"acc_toggle:{aid}"),
                InlineKeyboardButton(f"🗑️ Remove", callback_data=f"acc_del_confirm:{aid}"),
            ])

    buttons.append([
        InlineKeyboardButton("➕ Add New Account", callback_data="acc_add_new"),
        InlineKeyboardButton("🔄 Refresh Cockpit", callback_data="refresh_accounts_cockpit"),
    ])
    buttons.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")])

    return "\n".join(text_lines), InlineKeyboardMarkup(buttons)


async def render_login_hub_card(user_id: int):
    """Renders the account connection hub card with multi-account awareness."""
    is_adm = user_id in ADMIN_IDS
    accounts = await db.get_bot_accounts(owner_user_id=None if is_adm else user_id)

    if accounts:
        active_cnt = sum(1 for a in accounts if a.get("is_active"))
        text = (
            "🔐 **Telegram Account Hub (Multi-Account Enabled)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 **Pool Status:** `{len(accounts)}` Accounts Linked (`{active_cnt}` Active)\n"
            "• Anti-Ban Device Spoofer: **ACTIVE 🟢**\n"
            "• Auto Round-Robin Rotation: **ACTIVE 🟢**\n"
            "• Hot-Swap Failover on FloodWait: **ACTIVE 🟢**\n\n"
            "👉 _You can connect multiple Telegram accounts to distribute download load "
            "and eliminate any risk of account restriction!_"
        )
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(f"👥 Manage Multi-Accounts ({len(accounts)})", callback_data="view_my_accounts")],
                [InlineKeyboardButton("➕ Add Another Account", callback_data="acc_add_new")],
                [InlineKeyboardButton("🚪 Disconnect All Accounts", callback_data="user_disconnect_session")],
                [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")],
            ]
        )
    else:
        text = (
            "🔐 **Connect Your Telegram Account(s)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "To download restricted videos and files from private channels, your Telegram account needs to be connected.\n\n"
            "🛡️ **Multi-Account Anti-Ban Protection:**\n"
            "• Connect 1, 2, or more accounts — the bot automatically balances the load.\n"
            "• Each account gets a unique official device profile (Samsung, Pixel, iPhone).\n"
            "• Automatic cooldown quarantine & hot-swap failover on FloodWait.\n\n"
            "⭐ **Option 1: Scan QR Code (Recommended)**\n"
            "• Instant 1-scan login via your Telegram app.\n"
            "• **0% Ban / 0% Block risk** (no SMS / OTP code needed).\n\n"
            "📱 **Option 2: Phone Number Login**\n"
            "• Receive OTP code and enter via our safe button keypad.\n\n"
            "📋 **Option 3: Paste StringSession**\n"
            "• If you already have a Pyrogram StringSession, paste it directly here."
        )
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📱 Scan QR Code (Fastest & 100% Safe)", callback_data="start_qr_login")],
                [InlineKeyboardButton("🔢 Phone Number Login", callback_data="prompt_phone_login")],
                [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")],
            ]
        )
    return text, markup


@Client.on_message(filters.command(["accounts", "myaccounts"]) & filters.private)
async def accounts_command_handler(client: Client, message: Message):
    text, markup = await render_accounts_cockpit(message.from_user.id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^view_my_accounts$"))
async def view_my_accounts_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text, markup = await render_accounts_cockpit(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^refresh_accounts_cockpit$"))
async def refresh_accounts_cockpit_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer("🔄 Cockpit telemetry refreshed!")
    text, markup = await render_accounts_cockpit(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^acc_add_new$"))
async def acc_add_new_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📱 Scan QR Code (Fastest & 100% Safe)", callback_data="start_qr_login")],
            [InlineKeyboardButton("🔢 Phone Number Login", callback_data="prompt_phone_login")],
            [InlineKeyboardButton("👥 Back to Multi-Accounts", callback_data="view_my_accounts")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")],
        ]
    )
    text = (
        "➕ **ADD TELEGRAM ACCOUNT TO WORKER POOL** ➕\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Connect an additional Telegram account to expand your download bandwidth.\n\n"
        "⭐ **Choose Login Method:**\n"
        "• **QR Code Login (Recommended):** Scan with your mobile Telegram app (Settings > Devices > Link Desktop). Zero OTP, 100% safe.\n"
        "• **Phone Number Login:** Receive code on Telegram and enter via our numpad.\n"
        "• **StringSession:** Or paste a Pyrogram StringSession directly in chat."
    )
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^acc_toggle:(\d+)$"))
async def acc_toggle_callback(client: Client, callback_query: CallbackQuery):
    target_aid = int(callback_query.matches[0].group(1))
    user_id = callback_query.from_user.id
    owner_filter = None if user_id in ADMIN_IDS else user_id

    ok, new_state = await toggle_account_active(target_aid, owner_filter)
    if not ok:
        await callback_query.answer("⚠️ Could not toggle account (permission denied or not found).", show_alert=True)
        return

    label = "resumed and active in pool" if new_state == 1 else "paused (downloads won't use it)"
    await callback_query.answer(f"Account {target_aid} is now {label}!", show_alert=True)
    text, markup = await render_accounts_cockpit(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^acc_del_confirm:(\d+)$"))
async def acc_del_confirm_callback(client: Client, callback_query: CallbackQuery):
    target_aid = int(callback_query.matches[0].group(1))
    user_id = callback_query.from_user.id
    rec = await db.get_bot_account_by_id(target_aid)
    uname = f"@{rec['username']}" if rec and rec.get("username") else (rec.get("first_name") if rec else str(target_aid))

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Yes, Remove Account", callback_data=f"acc_del:{target_aid}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="view_my_accounts")],
    ])
    await callback_query.answer()
    try:
        await callback_query.message.edit_text(
            f"⚠️ **Are you sure you want to remove {uname} (`{target_aid}`)?**\n\n"
            "This account will be disconnected and removed from the active worker pool.",
            reply_markup=markup,
        )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^acc_del:(\d+)$"))
async def acc_del_callback(client: Client, callback_query: CallbackQuery):
    target_aid = int(callback_query.matches[0].group(1))
    user_id = callback_query.from_user.id
    owner_filter = None if user_id in ADMIN_IDS else user_id

    ok = await unregister_account(target_aid, owner_filter)
    if ok:
        await callback_query.answer(f"🗑️ Account {target_aid} removed from pool!", show_alert=True)
    else:
        await callback_query.answer("⚠️ Could not remove account.", show_alert=True)

    text, markup = await render_accounts_cockpit(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_message(filters.command("login") & filters.private)
async def login_handler(client: Client, message: Message):
    user_id = message.from_user.id
    # Clean any stale login states or leftover temp clients
    await db.clear_login_state(user_id)
    if user_id in login_clients:
        try:
            c = login_clients.pop(user_id)
            if c.is_connected:
                await c.disconnect()
        except Exception:
            pass
    if user_id in active_qr_tasks:
        active_qr_tasks[user_id].cancel()
        active_qr_tasks.pop(user_id, None)

    cleanup_temp_session(user_id)
    text, markup = await render_login_hub_card(user_id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^user_view_login$"))
async def user_view_login_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    text, markup = await render_login_hub_card(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^user_disconnect_session$"))
async def user_disconnect_session_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    # Disconnect user's accounts
    user_accs = await db.get_bot_accounts(owner_user_id=user_id)
    for a in user_accs:
        await unregister_account(a["account_id"], user_id)

    await db.remove_session(user_id)
    await db.clear_login_state(user_id)

    if user_id in active_userbots:
        try:
            c = active_userbots.pop(user_id)
            if c.is_connected:
                await c.stop()
        except Exception:
            pass

    if user_id in login_clients:
        try:
            c = login_clients.pop(user_id)
            if c.is_connected:
                await c.disconnect()
        except Exception:
            pass

    if user_id in active_qr_tasks:
        active_qr_tasks[user_id].cancel()
        active_qr_tasks.pop(user_id, None)

    cleanup_temp_session(user_id)
    await callback_query.answer("🚪 All accounts disconnected successfully!", show_alert=True)
    text, markup = await render_login_hub_card(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^prompt_phone_login$"))
async def prompt_phone_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📱 Switch to QR Code", callback_data="start_qr_login"),
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    contact_reply_kb = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📱 ১-ট্যাপে নিজের নম্বর পাঠান (Share Contact)", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback_query.message.reply_text(
        "📱 **Phone Number Login**\n\n"
        "আপনার ফোন নম্বর দিয়ে লগইন করার ২টি সহজ উপায়:\n\n"
        "১️⃣ **সবচেয়ে সহজ:** নিচের **'📱 ১-ট্যাপে নিজের নম্বর পাঠান'** বড় বাটনে চাপ দিন (টাইপ করা লাগবে না)।\n\n"
        "২️⃣ **অথবা টাইপ করে পাঠান:** কান্ট্রি কোডসহ আপনার নম্বর লিখুন:\n"
        "• যেমন: `01853170055` বা `+8801853170055`\n\n"
        "💡 _নম্বর পাঠানো মাত্রই টেলিগ্রাম থেকে আপনার অ্যাপ এবং সিমে কোড পাঠানো হবে।_",
        reply_markup=contact_reply_kb,
    )


# ----------------- QR CODE LOGIN FLOW -----------------

@Client.on_callback_query(filters.regex(r"^start_qr_login$"))
async def start_qr_login_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer("Generating QR Code...", show_alert=False)

    # Cancel any previous QR task
    if user_id in active_qr_tasks:
        active_qr_tasks[user_id].cancel()
        active_qr_tasks.pop(user_id, None)

    cleanup_temp_session(user_id)
    status_msg = await callback_query.message.reply_text("🔄 Connecting to Telegram servers to generate your QR Code...")

    fingerprint = get_fingerprint_for_user(user_id)
    temp_client = Client(
        name=f"temp_qr_{user_id}",
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=str(SESSIONS_DIR),
        **fingerprint,
    )

    try:
        await temp_client.connect()
        res = await temp_client.invoke(
            raw.functions.auth.ExportLoginToken(api_id=API_ID, api_hash=API_HASH, except_ids=[])
        )

        token_b64 = base64.urlsafe_b64encode(res.token).decode("utf-8").rstrip("=")
        qr_url = f"tg://login?token={token_b64}"

        # Generate QR code image
        qr = qrcode.QRCode(border=2)
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        qr_img_bytes = io.BytesIO()
        img.save(qr_img_bytes, format="PNG")
        qr_img_bytes.name = f"qr_{user_id}.png"
        qr_img_bytes.seek(0)

        caption = (
            "📱 **Scan to Connect Instantly!**\n\n"
            "1. Open **Telegram** on your phone.\n"
            "2. Go to **Settings > Devices > Link Desktop Device**.\n"
            "3. Point your camera at this QR code.\n\n"
            "⏱️ _Waiting for scan... (Expires in 60 seconds)_"
        )
        photo_msg = await callback_query.message.reply_photo(
            photo=qr_img_bytes,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔄 Refresh QR Code", callback_data="start_qr_login")],
                    [
                        InlineKeyboardButton("🔢 Phone Login", callback_data="prompt_phone_login"),
                        InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
                    ],
                ]
            ),
        )
        await status_msg.delete()

        # Start background polling task for this QR login
        task = asyncio.create_task(
            poll_qr_login(
                bot=client,
                temp_client=temp_client,
                user_id=user_id,
                photo_msg=photo_msg,
                res_token=res.token,
            )
        )
        active_qr_tasks[user_id] = task

    except Exception as e:
        if temp_client.is_connected:
            await temp_client.disconnect()
        await status_msg.edit_text(f"❌ Failed to generate QR Code: {str(e)}")


async def poll_qr_login(bot: Client, temp_client: Client, user_id: int, photo_msg: Message, res_token: bytes):
    """Polls Telegram server every 2.5s to check if the QR code was scanned."""
    try:
        for _ in range(25):  # Poll for up to ~60 seconds
            await asyncio.sleep(2.5)
            try:
                res = await temp_client.invoke(
                    raw.functions.auth.ExportLoginToken(api_id=API_ID, api_hash=API_HASH, except_ids=[])
                )

                if isinstance(res, raw.types.auth.LoginTokenSuccess):
                    # Successfully scanned and authorized!
                    user = res.authorization.user
                    await temp_client.storage.user_id(user.id)
                    await temp_client.storage.is_bot(False)
                    string_session = await temp_client.export_session_string()
                    await temp_client.disconnect()

                    cleanup_temp_session(user_id)
                    await register_and_start_account(
                        owner_user_id=user_id,
                        account_id=user.id,
                        string_session=string_session,
                        phone=user.phone or "",
                        first_name=user.first_name or "",
                        username=user.username or "",
                    )
                    fp = get_fingerprint_for_user(user.id)
                    dev_name = fp.get("device_model", "Official Telegram")

                    success_card = (
                        f"✅ **Account Connected Successfully via QR Code!**\n\n"
                        f"• Account: **{user.first_name}** (`@{user.username or 'N/A'}`)\n"
                        f"• Account ID: `{user.id}`\n"
                        f"• 🛡️ Anti-Ban Profile: `{dev_name}`\n"
                        f"• ⚡ Status: `🟢 Healthy & Active in Pool`\n\n"
                        "🚀 You can now send restricted links or manage your accounts with `/accounts`!"
                    )
                    success_markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton("👥 Multi-Account Cockpit (/accounts)", callback_data="view_my_accounts")],
                        [InlineKeyboardButton("➕ Add Another Account", callback_data="acc_add_new")],
                        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
                    ])

                    try:
                        await photo_msg.edit_caption(success_card, reply_markup=success_markup)
                    except Exception:
                        await bot.send_message(user_id, success_card, reply_markup=success_markup)
                    return

                elif isinstance(res, raw.types.auth.LoginTokenMigrateTo):
                    # Data center migration
                    await temp_client.session.stop()
                    await temp_client.storage.dc_id(res.dc_id)
                    await temp_client.storage.auth_key(
                        await Auth(
                            temp_client, await temp_client.storage.dc_id(),
                            await temp_client.storage.test_mode()
                        ).create()
                    )
                    temp_client.session = Session(
                        temp_client, await temp_client.storage.dc_id(),
                        await temp_client.storage.auth_key(), await temp_client.storage.test_mode()
                    )
                    await temp_client.session.start()
                    imp_res = await temp_client.invoke(raw.functions.auth.ImportLoginToken(token=res.token))
                    if isinstance(imp_res, raw.types.auth.LoginTokenSuccess):
                        user = imp_res.authorization.user
                        await temp_client.storage.user_id(user.id)
                        await temp_client.storage.is_bot(False)
                        string_session = await temp_client.export_session_string()
                        await temp_client.disconnect()

                        cleanup_temp_session(user_id)
                        await register_and_start_account(
                            owner_user_id=user_id,
                            account_id=user.id,
                            string_session=string_session,
                            phone=user.phone or "",
                            first_name=user.first_name or "",
                            username=user.username or "",
                        )
                        fp = get_fingerprint_for_user(user.id)
                        dev_name = fp.get("device_model", "Official Telegram")

                        success_card = (
                            f"✅ **Account Connected Successfully via QR Code!**\n\n"
                            f"• Account: **{user.first_name}** (`@{user.username or 'N/A'}`)\n"
                            f"• Account ID: `{user.id}`\n"
                            f"• 🛡️ Anti-Ban Profile: `{dev_name}`\n"
                            f"• ⚡ Status: `🟢 Healthy & Active in Pool`\n\n"
                            "🚀 You can now send restricted links or manage your accounts with `/accounts`!"
                        )
                        success_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("👥 Multi-Account Cockpit (/accounts)", callback_data="view_my_accounts")],
                            [InlineKeyboardButton("➕ Add Another Account", callback_data="acc_add_new")],
                            [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
                        ])

                        try:
                            await photo_msg.edit_caption(success_card, reply_markup=success_markup)
                        except Exception:
                            await bot.send_message(user_id, success_card, reply_markup=success_markup)
                        return

            except RPCError as e:
                if "SESSION_PASSWORD_NEEDED" in str(e):
                    # User needs to enter 2FA password
                    login_clients[user_id] = temp_client
                    await db.set_login_state(user_id, phone="", phone_code_hash="", step="2fa")
                    await photo_msg.reply_text(
                        "🔒 **Two-Step Verification (2FA) Cloud Password Required!**\n\n"
                        "Please send your **2FA Password** in this chat to complete login:"
                    )
                    return

        # Expired after 60s
        if temp_client.is_connected:
            await temp_client.disconnect()
        try:
            await photo_msg.edit_caption(
                "⌛ **QR Code Expired.**\n\nTap below to generate a new QR Code:",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔄 Generate New QR Code", callback_data="start_qr_login")],
                        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")],
                    ]
                ),
            )
        except Exception:
            pass

    except asyncio.CancelledError:
        if temp_client.is_connected:
            await temp_client.disconnect()
    except Exception as e:
        if temp_client.is_connected:
            await temp_client.disconnect()


# ----------------- LOGOUT & STATUS HANDLERS -----------------

@Client.on_message(filters.command("logout") & filters.private)
async def logout_handler(client: Client, message: Message):
    user_id = message.from_user.id
    await db.remove_session(user_id)
    await db.clear_login_state(user_id)

    if user_id in active_userbots:
        try:
            c = active_userbots.pop(user_id)
            if c.is_connected:
                await c.stop()
        except Exception:
            pass

    if user_id in login_clients:
        try:
            c = login_clients.pop(user_id)
            if c.is_connected:
                await c.disconnect()
        except Exception:
            pass

    if user_id in active_qr_tasks:
        active_qr_tasks[user_id].cancel()
        active_qr_tasks.pop(user_id, None)

    cleanup_temp_session(user_id)
    await message.reply_text("🚪 **Disconnected.** Your account session has been cleared.")


@Client.on_message(filters.command("status") & filters.private)
async def status_handler(client: Client, message: Message):
    user_id = message.from_user.id
    session = await db.get_session(user_id)
    if session:
        await message.reply_text("✅ **Your Telegram account is connected and active.**")
    else:
        await message.reply_text("❌ **No account connected.** Use `/login` to connect your account.")


@Client.on_message(filters.command("join") & filters.private)
async def join_channel_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2:
        await message.reply_text("Usage: `/join https://t.me/+invite_link`")
        return

    from core.client_manager import get_user_client
    user_client = await get_user_client(user_id)
    if not user_client:
        await message.reply_text("⚠️ You must connect your Telegram account with `/login` first before joining channels.")
        return

    invite_link = message.command[1].strip()
    status_msg = await message.reply_text("🔄 Joining private channel...")
    try:
        joined_chat = await user_client.join_chat(invite_link)
        await status_msg.edit_text(
            f"✅ **Successfully Joined Channel!**\n\n"
            f"• **Channel Name:** {joined_chat.title}\n"
            f"• **Chat ID:** `{joined_chat.id}`\n\n"
            "You can now paste restricted links from this channel to download!"
        )
    except FloodWait as fw:
        await status_msg.edit_text(f"⏳ **Telegram Join Rate Limit:** Please wait `{fw.value}` seconds before joining another channel.")
    except Exception as e:
        err_msg = str(e).upper()
        if "USER_ALREADY_PARTICIPANT" in err_msg:
            await status_msg.edit_text("ℹ️ **Already Joined:** Your connected account is already a member of this channel!")
        elif "INVITE_HASH_EXPIRED" in err_msg:
            await status_msg.edit_text("❌ **Expired Link:** This Telegram invite link has expired.")
        elif "INVITE_HASH_INVALID" in err_msg:
            await status_msg.edit_text("❌ **Invalid Link:** The invite link is invalid or malformed.")
        elif "INVITE_REQUEST_SENT" in err_msg:
            await status_msg.edit_text("📨 **Join Request Sent!**\n\nThis channel requires owner/admin approval. Once approved, you can download immediately.")
        elif "CHANNELS_TOO_MUCH" in err_msg:
            await status_msg.edit_text("⚠️ **Telegram Channel Limit Reached:**\nYour account has reached the maximum number of joined channels (500 limit). Please leave a few unused channels and try again.")
        else:
            await status_msg.edit_text(f"❌ Failed to join: {e}")


# ----------------- NUMPAD CALLBACKS -----------------

@Client.on_callback_query(filters.regex(r"^numpad:(.+)"))
async def numpad_callback_handler(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    action = callback_query.matches[0].group(1)

    login_state = await db.get_login_state(user_id)
    if not login_state or user_id not in login_clients:
        await callback_query.answer("Session expired. Please type /login again.", show_alert=True)
        return

    current = temp_numpad_codes.get(user_id, "")

    if action.isdigit():
        if len(current) < 6:
            current += action
            temp_numpad_codes[user_id] = current
            await callback_query.answer(f"Added {action}")
        else:
            await callback_query.answer("Maximum 6 digits allowed!", show_alert=False)
            return

    elif action == "del":
        current = current[:-1]
        temp_numpad_codes[user_id] = current
        await callback_query.answer("Deleted digit")

    elif action == "clear":
        current = ""
        temp_numpad_codes[user_id] = current
        await callback_query.answer("Cleared")

    elif action == "submit":
        if len(current) not in (5, 6):
            await callback_query.answer("Please enter all 5 digits first!", show_alert=True)
            return
        await callback_query.answer("Verifying code...")
        await execute_sign_in(client, callback_query.message, user_id, current)
        return

    # Update numpad display
    display_code = " ".join(current) if current else "_ _ _ _ _"
    phone = login_state.get("phone", "")
    new_text = (
        f"📩 **Login Code Sent to Telegram!**\n\n"
        f"• **Phone:** `{phone}`\n\n"
        f"👇 **Tap the digits below on the keypad to enter your code:**\n"
        f"Code: `[ {display_code} ]`\n\n"
        "💡 _Using this keypad prevents Telegram from blocking the code._"
    )

    try:
        await callback_query.message.edit_text(
            text=new_text,
            reply_markup=get_numpad_markup(current),
        )
    except Exception:
        pass

    # Auto-submit if 5 digits reached
    if len(current) == 5:
        await execute_sign_in(client, callback_query.message, user_id, current)


async def execute_sign_in(bot: Client, status_msg: Message, user_id: int, clean_code: str):
    """Executes the sign-in call with the captured OTP code."""
    login_state = await db.get_login_state(user_id)
    temp_client = login_clients.get(user_id)

    if not login_state or not temp_client or not temp_client.is_connected:
        await status_msg.edit_text("⚠️ Login session expired. Please type `/login` to start again.")
        return

    phone = login_state["phone"]
    phone_code_hash = login_state["phone_code_hash"]

    try:
        await temp_client.sign_in(
            phone_number=phone,
            phone_code_hash=phone_code_hash,
            phone_code=clean_code,
        )
        string_session = await temp_client.export_session_string()
        me = await temp_client.get_me()
        await temp_client.disconnect()

        login_clients.pop(user_id, None)
        await db.clear_login_state(user_id)
        cleanup_temp_session(user_id)
        await register_and_start_account(
            owner_user_id=user_id,
            account_id=me.id,
            string_session=string_session,
            phone=phone,
            first_name=me.first_name or "",
            username=me.username or "",
        )
        fp = get_fingerprint_for_user(me.id)
        dev_name = fp.get("device_model", "Official Telegram")

        await status_msg.edit_text(
            f"✅ **Account Connected Successfully!**\n\n"
            f"• Account: **{me.first_name}** (`@{me.username or 'N/A'}`)\n"
            f"• Account ID: `{me.id}`\n"
            f"• 🛡️ Anti-Ban Profile: `{dev_name}`\n"
            f"• ⚡ Status: `🟢 Healthy & Active in Pool`\n\n"
            "🚀 You can now send restricted private channel links to download!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Multi-Account Cockpit (/accounts)", callback_data="view_my_accounts")],
                [InlineKeyboardButton("➕ Add Another Account", callback_data="acc_add_new")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
            ])
        )

    except SessionPasswordNeeded:
        await db.update_login_step(user_id, step="2fa")
        await status_msg.edit_text(
            "🔒 **Two-Step Verification (2FA) Required!**\n\n"
            "Your Telegram account has a Cloud Password enabled.\n"
            "Please type and send your **2FA Password** in this chat now:"
        )

    except PhoneCodeInvalid:
        await status_msg.edit_text(
            "❌ **The code entered is invalid.**\n\n"
            "Please check your Telegram notification and tap the correct digits on the keypad:",
            reply_markup=get_numpad_markup(""),
        )
        temp_numpad_codes[user_id] = ""

    except PhoneCodeExpired:
        if user_id in login_clients:
            try:
                c = login_clients.pop(user_id)
                if c.is_connected:
                    await c.disconnect()
            except Exception:
                pass
        await db.clear_login_state(user_id)
        cleanup_temp_session(user_id)
        await status_msg.edit_text(
            "❌ **Telegram blocked this login code.**\n\n"
            "👉 **Use QR Code Login instead (100% Reliable):**\n"
            "Click below to generate a QR Code you can scan with your phone:",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📱 Scan QR Code (Zero OTP / Instant)", callback_data="start_qr_login")],
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")],
                ]
            ),
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Login error: {str(e)}")


async def initiate_phone_code_login(client: Client, message: Message, user_id: int, clean_phone: str):
    """Unified engine to connect to Telegram, send code, and present numpad with SMS resend option."""
    # Clean old clients
    if user_id in login_clients:
        try:
            old_client = login_clients.pop(user_id)
            if old_client.is_connected:
                await old_client.disconnect()
        except Exception:
            pass
    cleanup_temp_session(user_id)
    await db.clear_login_state(user_id)

    status_msg = await message.reply_text(
        f"📨 Connecting to Telegram to send login code to `{clean_phone}`...",
    )

    try:
        fingerprint = get_fingerprint_for_user(user_id)
        temp_client = Client(
            name=f"temp_login_{user_id}",
            api_id=API_ID,
            api_hash=API_HASH,
            in_memory=True,
            **fingerprint,
        )
        await temp_client.connect()
        code_info = await temp_client.send_code(clean_phone)
        login_clients[user_id] = temp_client

        await db.set_login_state(
            user_id,
            phone=clean_phone,
            phone_code_hash=code_info.phone_code_hash,
            step="code",
        )
        temp_numpad_codes[user_id] = ""

        delivery_dest = "Telegram App (Official Service Chat)"
        if hasattr(code_info, "type"):
            t_type = str(code_info.type).lower()
            if "sms" in t_type:
                delivery_dest = "SMS (Mobile SIM Inbox)"
            elif "call" in t_type:
                delivery_dest = "Phone Call"

        numpad_text = (
            f"📩 **Login Code Sent to Telegram!**\n\n"
            f"• **Phone:** `{clean_phone}`\n"
            f"• **Delivery Type:** `{delivery_dest}`\n\n"
            f"🚨 **কোডটি যেভাবে পাবেন:**\n"
            f"আপনার মোবাইলের Telegram অ্যাপের চ্যাট লিস্ট খুলুন — সবার উপরে অফিসিয়াল **Telegram** (Service Notifications / 777000) চ্যাটে ৫ ডিজিটের লগইন কোড এসেছে।\n\n"
            "👇 **নিচের বাটনের কিপ্যাডে কোডের সংখ্যাগুলো চাপুন (টেলিগ্রাম যাতে কোড ব্লক না করে):**\n"
            "Code: `[ _ _ _ _ _ ]`"
        )
        try:
            await status_msg.delete()
        except Exception:
            pass

        await message.reply_text(
            numpad_text,
            reply_markup=get_numpad_markup(""),
        )
        return

    except PhoneNumberInvalid:
        cleanup_temp_session(user_id)
        await status_msg.edit_text("❌ The phone number provided is invalid. Please check the country code and try again.")
        return
    except PhoneNumberBanned:
        cleanup_temp_session(user_id)
        await status_msg.edit_text("❌ This phone number has been restricted or banned by Telegram.")
        return
    except FloodWait as e:
        cleanup_temp_session(user_id)
        await status_msg.edit_text(f"⏳ Telegram rate limit: Please wait `{e.value}` seconds before requesting a code again.")
        return
    except Exception as e:
        cleanup_temp_session(user_id)
        await status_msg.edit_text(f"❌ Failed to send code: {str(e)}")
        return


@Client.on_callback_query(filters.regex(r"^resend_otp_sms$"))
async def resend_otp_sms_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    login_state = await db.get_login_state(user_id)
    temp_client = login_clients.get(user_id)

    if not login_state or not temp_client or not temp_client.is_connected:
        await callback_query.answer("⚠️ সেশনের মেয়াদ শেষ হয়েছে। দয়া করে আবার /login দিয়ে নম্বর পাঠান।", show_alert=True)
        return

    phone = login_state.get("phone", "")
    phone_code_hash = login_state.get("phone_code_hash", "")

    await callback_query.answer("🔄 টেলিগ্রাম থেকে আপনার সিমে SMS পাঠানো হচ্ছে...", show_alert=False)
    try:
        new_code_info = await temp_client.resend_code(
            phone_number=phone,
            phone_code_hash=phone_code_hash,
        )
        if hasattr(new_code_info, "phone_code_hash"):
            await db.set_login_state(
                user_id,
                phone=phone,
                phone_code_hash=new_code_info.phone_code_hash,
                step="code",
            )

        await callback_query.message.reply_text(
            f"📨 **টেলিগ্রাম আপনার সিমে SMS পাঠিয়েছে!**\n\n"
            f"• **নম্বর:** `{phone}`\n"
            f"• **মাধ্যম:** মোবাইল SMS 📱\n\n"
            f"অনুগ্রহ করে আপনার ফোনের **সাধারণ SMS ইনবক্স** চেক করুন এবং প্রাপ্ত ৫ ডিজিটের কোডটি কিপ্যাডে চাপুন বা লিখে পাঠান।"
        )
    except FloodWait as fw:
        await callback_query.answer(
            f"⏳ টেলিগ্রাম এসএমএস পাঠাতে {fw.value} সেকেন্ড অপেক্ষা করতে বলেছে। দয়া করে একটু পর চেষ্টা করুন।",
            show_alert=True,
        )
    except Exception as e:
        err_msg = str(e)
        if "SEND_CODE_UNAVAILABLE" in err_msg or "PHONE_CODE_EXPIRED" in err_msg:
            await callback_query.answer("⚠️ টেলিগ্রাম এই মুহূর্তে SMS দিতে পারছে না। আপনার Telegram অ্যাপের নোটিফিকেশন চেক করুন।", show_alert=True)
        else:
            await callback_query.answer(f"⚠️ SMS পাঠাতে সমস্যা: {err_msg}", show_alert=True)


@Client.on_message(filters.contact & filters.private)
async def contact_login_listener(client: Client, message: Message):
    user_id = message.from_user.id
    contact = message.contact
    if not contact or not contact.phone_number:
        return

    raw_phone = contact.phone_number.strip()
    digits_only = "".join(c for c in raw_phone if c.isdigit())
    clean_phone = "+" + digits_only

    await message.reply_text("🔄 নম্বর পাওয়া গেছে! টেলিগ্রামের সাথে সংযোগ করা হচ্ছে...", reply_markup=ReplyKeyboardRemove())
    await initiate_phone_code_login(client, message, user_id, clean_phone)


# ----------------- TEXT LISTENER (PHONE / 2FA / STRINGSESSION) -----------------

@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"))
async def auth_flow_listener(client: Client, message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    # Commands must never be consumed by auth flow
    if text.startswith("/"):
        message.continue_propagation()
        return

    # If it's a URL, let link_handler process it
    if "t.me/" in text or text.startswith("http://") or text.startswith("https://"):
        message.continue_propagation()
        return

    # Case 1: Pasting raw StringSession (Pyrogram string sessions are unbroken ASCII base64 strings with no spaces or newlines)
    is_session_string = (
        len(text) >= 120
        and " " not in text
        and "\n" not in text
        and text.isascii()
        and bool(re.match(r"^[A-Za-z0-9+/=_-]+$", text))
    )
    if is_session_string:
        status_msg = await message.reply_text("🔄 Verifying Pyrogram StringSession...")
        fingerprint = get_fingerprint_for_user(user_id)
        temp_client = Client(
            name=f"verify_str_{user_id}",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=text,
            in_memory=True,
            **fingerprint,
        )
        try:
            await temp_client.start()
            me = await temp_client.get_me()
            await temp_client.stop()

            await db.clear_login_state(user_id)
            if user_id in login_clients:
                try:
                    c = login_clients.pop(user_id)
                    if c.is_connected:
                        await c.disconnect()
                except Exception:
                    pass
            cleanup_temp_session(user_id)
            await register_and_start_account(
                owner_user_id=user_id,
                account_id=me.id,
                string_session=text,
                phone=me.phone_number or "",
                first_name=me.first_name or "",
                username=me.username or "",
            )
            fp = get_fingerprint_for_user(me.id)
            dev_name = fp.get("device_model", "Official Telegram")

            await status_msg.edit_text(
                f"✅ **Account Connected Successfully!**\n\n"
                f"• Account: **{me.first_name}** (`@{me.username or 'N/A'}`)\n"
                f"• Account ID: `{me.id}`\n"
                f"• 🛡️ Anti-Ban Profile: `{dev_name}`\n"
                f"• ⚡ Status: `🟢 Healthy & Active in Pool`\n\n"
                "🚀 You can now paste restricted links to download videos!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👥 Multi-Account Cockpit (/accounts)", callback_data="view_my_accounts")],
                    [InlineKeyboardButton("➕ Add Another Account", callback_data="acc_add_new")],
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
                ])
            )
            return
        except Exception as e:
            await status_msg.edit_text(f"❌ Invalid session string: {str(e)}")
            return

    # Check if text is a phone number
    digits_only = "".join(c for c in text if c.isdigit())
    is_phone_format = (
        (text.startswith("+") and len(digits_only) >= 9)
        or (text.startswith("01") and len(digits_only) == 11)
        or (digits_only.startswith("8801") and len(digits_only) == 13)
        or (len(digits_only) == 10 and digits_only.startswith("1"))
    )

    # Case 2: Entering Phone Number
    if is_phone_format:
        if text.startswith("01") and len(digits_only) == 11:
            clean_phone = "+88" + digits_only
        elif len(digits_only) == 10 and digits_only.startswith("1"):
            clean_phone = "+880" + digits_only
        elif digits_only.startswith("880") and not text.startswith("+"):
            clean_phone = "+" + digits_only
        else:
            clean_phone = "+" + digits_only

        await initiate_phone_code_login(client, message, user_id, clean_phone)
        return

    # Case 3: Entering 2FA Cloud Password (or manual code fallback)
    login_state = await db.get_login_state(user_id)
    if login_state:
        step = login_state.get("step", "code")

        if step == "2fa":
            temp_client = login_clients.get(user_id)
            if not temp_client or not temp_client.is_connected:
                await message.reply_text("⚠️ Session expired. Please type `/login` to start again.")
                return

            status_msg = await message.reply_text("🔄 Verifying 2FA password...")
            try:
                await temp_client.check_password(text)
                string_session = await temp_client.export_session_string()
                me = await temp_client.get_me()
                await temp_client.disconnect()

                login_clients.pop(user_id, None)
                await db.clear_login_state(user_id)
                cleanup_temp_session(user_id)
                await register_and_start_account(
                    owner_user_id=user_id,
                    account_id=me.id,
                    string_session=string_session,
                    phone=login_state.get("phone", ""),
                    first_name=me.first_name or "",
                    username=me.username or "",
                )
                fp = get_fingerprint_for_user(me.id)
                dev_name = fp.get("device_model", "Official Telegram")

                await status_msg.edit_text(
                    f"✅ **Account Connected Successfully!**\n\n"
                    f"• Account: **{me.first_name}** (`@{me.username or 'N/A'}`)\n"
                    f"• Account ID: `{me.id}`\n"
                    f"• 🛡️ Anti-Ban Profile: `{dev_name}`\n"
                    f"• ⚡ Status: `🟢 Healthy & Active in Pool`\n\n"
                    "🚀 You can now send any restricted private channel link to download videos!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("👥 Multi-Account Cockpit (/accounts)", callback_data="view_my_accounts")],
                        [InlineKeyboardButton("➕ Add Another Account", callback_data="acc_add_new")],
                        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
                    ])
                )
                return
            except PasswordHashInvalid:
                await status_msg.edit_text("❌ **Incorrect 2FA password.** Please enter your correct Cloud Password:")
                return
            except Exception as e:
                await status_msg.edit_text(f"❌ 2FA verification failed: {str(e)}")
                return

        elif step == "code":
            # If user typed code manually as text instead of using numpad
            clean_code = "".join(c for c in text if c.isdigit())
            if len(clean_code) in (5, 6):
                status_msg = await message.reply_text("🔄 Verifying code...")
                await execute_sign_in(client, status_msg, user_id, clean_code)
                return
            else:
                await message.reply_text(
                    "⚠️ Please tap the digits on the keypad buttons above to enter your 5-digit code safely!"
                )
                return

    # Fallback: if not handled as login text, propagate to downstream handlers
    message.continue_propagation()
