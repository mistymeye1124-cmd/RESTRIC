# language: Python, file: handlers/premium.py, target: Python 3.10+, Pyrogram
"""
Monetization, Subscription, and Payment Processing Handler.
Supports bKash, Nagad, Rocket, Binance Pay, and one-click Admin approval buttons.
"""

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import PAYMENT_METHODS, PREMIUM_PLANS, ADMIN_IDS
from database import db
from core.emojis import apply_custom_emojis


async def render_premium_card(user_id: int):
    """Returns (text, markup) for the premium/VIP plans page. Safe to call from any context."""
    is_prem = await db.is_user_premium(user_id)
    user = await db.get_user(user_id)

    status_str = "💎 Active VIP Premium Member" if is_prem else "⚪ Standard Free Tier"
    expiry_str = (user.get("premium_expiry") or "Lifetime Access") if is_prem else "N/A"

    plans = await db.get_vip_plans()
    plan_lines = []
    buy_buttons = []
    btn_row = []
    for k, p in plans.items():
        plan_lines.append(f"• {p['badge']} **{p['name']}:** `{p['price_bdt']} BDT`")
        btn = InlineKeyboardButton(f"{p['badge']} {p['name']} ({p['price_bdt']}৳)", callback_data=f"buy_plan:{k}")
        btn_row.append(btn)
        if len(btn_row) == 2:
            buy_buttons.append(btn_row)
            btn_row = []
    if btn_row:
        buy_buttons.append(btn_row)

    plans_block = "\n".join(plan_lines) if plan_lines else "• _No VIP passes configured._"

    support_link = await db.get_support_contact()
    if not support_link.startswith("http"):
        support_link = f"https://t.me/{support_link.lstrip('@')}"

    text = (
        "💎 **VIP PREMIUM MEMBERSHIP PASS** 💎\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **ACCELERATE YOUR CLOUD HARVESTING WORKFLOW**\n"
        "Unrestricted downloads, high-speed multi-threaded servers, custom video branding, and bulk course cloning.\n\n"
        "┌── 👤 **CURRENT MEMBERSHIP STATUS** ──┐\n"
        f"│ • Level: `{status_str}`\n"
        f"│ • Access Expiry: `{expiry_str}`\n"
        "│ • Server Priority: `⚡ VIP Turbo Zero-Wait Queue`\n"
        "└──────────────────────────────────────┘\n\n"
        "✨ **EXCLUSIVE VIP PRIVILEGES:**\n"
        "✦ ⚡ **Unlimited Daily Downloads:** No daily quota restrictions\n"
        "✦ 🚀 **VIP High-Speed Turbo Servers:** Zero waiting in queue\n"
        "✦ 📑 **Bulk Serial Cloner:** Up to 200 links/range per single job\n"
        "✦ 👥 **Topic & Forum Cloner:** 1-click clone entire topic streams\n"
        "✦ 🎬 **Watermark Studio Pro:** Custom text, transparent logos, intro/outro\n"
        "✦ ✨ **100% Clean Original Video:** Zero forced bot branding\n"
        "✦ 📢 **Auto-Forward to Cloud:** Direct mirroring to private backup channels\n"
        "✦ 🌐 **Web Video Harvester:** YouTube, Facebook, Drive & m3u8 streams\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💰 **SUBSCRIPTION PASSES:**\n"
        f"{plans_block}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📲 **AUTOMATED PAYMENT ACCOUNTS:**\n"
    )
    active_methods = await db.get_active_payment_methods()
    if not active_methods:
        active_methods = PAYMENT_METHODS
    if active_methods:
        for method, number in active_methods.items():
            text += f"• 💳 **{method}:** `{number}`\n"
    else:
        text += "• _No payment accounts currently active. Please contact support._\n"

    instructions = await db.get_payment_instructions()
    text += f"\n{instructions}"

    buy_buttons.append([
        InlineKeyboardButton("📊 Compare Free vs VIP", callback_data="user_view_features"),
        InlineKeyboardButton("📞 Admin Support", url=support_link),
    ])
    buy_buttons.append([
        InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main"),
    ])

    return apply_custom_emojis(text), InlineKeyboardMarkup(buy_buttons)


@Client.on_message(filters.command(["premium", "buy", "plans"]) & filters.private)
async def premium_plans_handler(client: Client, message: Message):
    text, markup = await render_premium_card(message.from_user.id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^buy_plan:(.+)"))
async def buy_plan_callback(client: Client, callback_query: CallbackQuery):
    plan_key = callback_query.matches[0].group(1)
    plan = await db.get_vip_plan(plan_key)
    if not plan:
        plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        await callback_query.answer("Invalid plan selected.", show_alert=True)
        return

    text = (
        f"💳 **Pay for {plan['name']} ({plan['price_bdt']} BDT)**\n\n"
        "Please send the exact amount to any of these accounts:\n\n"
    )
    active_methods = await db.get_active_payment_methods()
    if not active_methods:
        active_methods = PAYMENT_METHODS
    if active_methods:
        for method, number in active_methods.items():
            text += f"• **{method}:** `{number}`\n"
    else:
        text += "• _No payment accounts currently active. Please contact support._\n"

    instructions = await db.get_payment_instructions()
    text += f"\n{instructions}\n\nSelected Plan: `{plan['name']}` (Use code: `{plan_key}`)"
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔙 Back to Plans", callback_data="user_view_premium"),
                InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    await callback_query.answer()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command("pay") & filters.private)
async def submit_payment_handler(client: Client, message: Message):
    user_id = message.from_user.id
    args = message.command[1:]

    if len(args) < 3:
        await message.reply_text(
            "⚠️ **Format Error!**\n\n"
            "Correct format:\n"
            "`/pay <plan> <TrxID> <YourSenderNumber>`\n\n"
            "Valid plans: `7_days`, `30_days`, `lifetime`\n"
            "Example: `/pay 30_days 9J87654321 017XXXXXXXX`"
        )
        return

    plan_key, trx_id, sender_num = args[0].lower(), args[1].upper(), args[2]
    plan = await db.get_vip_plan(plan_key)
    if not plan:
        plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        await message.reply_text("❌ Invalid plan selected. Please check available plans with `/plans`.")
        return

    # Record in database
    ok = await db.record_transaction(
        user_id=user_id,
        plan_key=plan_key,
        trx_id=trx_id,
        sender_number=sender_num,
        method="Mobile Banking / Crypto",
        amount=plan["price_bdt"],
    )

    if not ok:
        await message.reply_text("⚠️ This Transaction ID (TrxID) has already been submitted or is pending verification!")
        return

    await message.reply_text(
        "✅ **Payment Submitted for Verification!**\n\n"
        f"• **Plan:** `{plan['name']}`\n"
        f"• **TrxID:** `{trx_id}`\n"
        f"• **Sender:** `{sender_num}`\n\n"
        "Our admin is reviewing your transaction. Your account will be upgraded within a few minutes!"
    )

    # Dispatch notification to all Admins with instant One-Click Approval buttons
    admin_alert = (
        "🚨 **NEW PAYMENT SUBMISSION**\n\n"
        f"• **User:** {message.from_user.mention} (`{user_id}`)\n"
        f"• **Username:** @{message.from_user.username or 'N/A'}\n"
        f"• **Plan:** `{plan['name']}` ({plan['price_bdt']} BDT)\n"
        f"• **TrxID:** `{trx_id}`\n"
        f"• **Sender Number:** `{sender_num}`"
    )
    admin_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"✅ Approve ({plan['days']}d)", callback_data=f"adm_app:{trx_id}:{user_id}:{plan['days']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej:{trx_id}:{user_id}"),
            ]
        ]
    )

    for admin_id in ADMIN_IDS:
        try:
            await client.send_message(chat_id=admin_id, text=admin_alert, reply_markup=admin_markup)
        except Exception as e:
            print(f"[!] Could not send alert to admin {admin_id}: {e}")


# --- Admin Payment Verification Callbacks ---

@Client.on_callback_query(filters.regex(r"^adm_app:(.+):(\d+):(\d+)"))
async def admin_approve_callback(client: Client, callback_query: CallbackQuery):
    if callback_query.from_user.id not in ADMIN_IDS:
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return

    trx_id = callback_query.matches[0].group(1)
    target_user_id = int(callback_query.matches[0].group(2))
    days = int(callback_query.matches[0].group(3))

    trx = await db.approve_transaction(trx_id)
    if not trx:
        await callback_query.answer("⚠️ Transaction already processed or invalid.", show_alert=True)
        return

    # Add premium to user
    await db.add_premium(target_user_id, days=days)

    # Notify User
    try:
        await client.send_message(
            chat_id=target_user_id,
            text=(
                "🎉 **PAYMENT APPROVED! VIP ACTIVATED!**\n\n"
                f"Your payment for `{trx['plan_key']}` has been verified.\n"
                f"• **VIP Duration:** `{days} days`\n"
                "• All premium limits, high-speed priority queue, and watermarking are now unlocked!\n\n"
                "Thank you for choosing our service! 🚀"
            )
        )
    except Exception:
        pass

    # Notify Inviter of Affiliate Commission Bonus
    aff = trx.get("affiliate_reward")
    if aff and aff[1] > 0:
        inv_id, b_days = aff
        try:
            await client.send_message(
                chat_id=inv_id,
                text=(
                    "🎉 **AFFILIATE COMMISSION EARNED!** 🎉\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "A friend you invited has just upgraded to VIP Premium!\n"
                    f"🎁 You received: **+{b_days} Days Free VIP Access!**\n\n"
                    "Check your status anytime with `/ref`!"
                )
            )
        except Exception:
            pass

    await callback_query.message.edit_text(
        f"✅ **Approved by Admin {callback_query.from_user.first_name}**\n\n"
        f"• TrxID: `{trx_id}`\n"
        f"• User: `{target_user_id}`\n"
        f"• Added: `{days} days`"
    )
    await callback_query.answer("Transaction approved and user upgraded!")


@Client.on_callback_query(filters.regex(r"^adm_rej:(.+):(\d+)"))
async def admin_reject_callback(client: Client, callback_query: CallbackQuery):
    if callback_query.from_user.id not in ADMIN_IDS:
        await callback_query.answer("⛔ Admin access only.", show_alert=True)
        return

    trx_id = callback_query.matches[0].group(1)
    target_user_id = int(callback_query.matches[0].group(2))

    trx = await db.reject_transaction(trx_id)
    if not trx:
        await callback_query.answer("⚠️ Transaction already processed or invalid.", show_alert=True)
        return

    # Notify User
    try:
        supp = await db.get_support_contact()
        await client.send_message(
            chat_id=target_user_id,
            text=(
                "❌ **Payment Rejected**\n\n"
                f"Your payment with TrxID `{trx_id}` could not be verified.\n"
                f"Please verify your payment details or contact support: {supp}"
            )
        )
    except Exception:
        pass

    await callback_query.message.edit_text(
        f"❌ **Rejected by Admin {callback_query.from_user.first_name}**\n\n"
        f"• TrxID: `{trx_id}`\n"
        f"• User: `{target_user_id}`"
    )
    await callback_query.answer("Transaction rejected.")


@Client.on_message(filters.command("approve") & filters.private)
async def manual_approve_trx_command(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/approve <trx_id>`\nExample: `/approve BKA12345678`")
        return
    trx_id = message.command[1].strip().upper()
    trx = await db.approve_transaction(trx_id)
    if not trx:
        await message.reply_text(f"❌ Transaction `{trx_id}` not found or already processed.")
        return
    plan_key = trx.get("plan_key", "30_days")
    plan_obj = await db.get_vip_plan(plan_key)
    days = plan_obj["days"] if plan_obj else PREMIUM_PLANS.get(plan_key, {}).get("days", 30)
    target_user_id = trx["user_id"]
    await db.add_premium(target_user_id, days=days)
    try:
        await client.send_message(
            chat_id=target_user_id,
            text=(
                "🎉 **PAYMENT APPROVED! VIP ACTIVATED!**\n\n"
                f"Your payment for `{plan_key}` has been verified.\n"
                f"• **VIP Duration:** `{days} days`\n"
                "• All premium limits, high-speed priority queue, and watermarking are now unlocked!\n\n"
                "Thank you for choosing our service! 🚀"
            )
        )
    except Exception:
        pass

    # Notify Inviter of Affiliate Commission Bonus
    aff = trx.get("affiliate_reward")
    if aff and aff[1] > 0:
        inv_id, b_days = aff
        try:
            await client.send_message(
                chat_id=inv_id,
                text=(
                    "🎉 **AFFILIATE COMMISSION EARNED!** 🎉\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "A friend you invited has just upgraded to VIP Premium!\n"
                    f"🎁 You received: **+{b_days} Days Free VIP Access!**\n\n"
                    "Check your status anytime with `/ref`!"
                )
            )
        except Exception:
            pass

    await message.reply_text(f"✅ Transaction `{trx_id}` approved! Granted `{days}` days VIP to user `{target_user_id}`.")


@Client.on_message(filters.command("reject") & filters.private)
async def manual_reject_trx_command(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: `/reject <trx_id>`\nExample: `/reject BKA12345678`")
        return
    trx_id = message.command[1].strip().upper()
    trx = await db.reject_transaction(trx_id)
    if not trx:
        await message.reply_text(f"❌ Transaction `{trx_id}` not found or already processed.")
        return
    target_user_id = trx["user_id"]
    try:
        supp = await db.get_support_contact()
        await client.send_message(
            chat_id=target_user_id,
            text=(
                "❌ **Payment Rejected**\n\n"
                f"Your payment with TrxID `{trx_id}` could not be verified.\n"
                f"Please check your transaction details or contact support: {supp}"
            )
        )
    except Exception:
        pass
    await message.reply_text(f"❌ Transaction `{trx_id}` rejected.")
