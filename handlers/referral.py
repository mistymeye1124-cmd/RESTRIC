# language: Python, file: handlers/referral.py, target: Python 3.10+, Pyrogram
"""
Viral Referral & Affiliate Rewards Engine:
Generates personal deep-links, tracks invites, displays reward milestones,
and allows instant 1-click sharing to Telegram groups.
"""

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import db
from core.progress import generate_blocks
from core.emojis import apply_custom_emojis


async def render_referral_card(client: Client, user_id: int):
    """Generates the high-converting viral referral card and action buttons."""
    stats = await db.get_referral_stats(user_id)
    total_invites = stats.get("total_invites", 0)
    points = stats.get("points", 0)

    cfg = await db.get_referral_config()
    pts_per = cfg["points_per_invite"]
    redeem_pts = cfg["redeem_points"]
    redeem_days = cfg["redeem_days"]
    purch_days = cfg["purchase_reward_days"]

    plans = await db.get_referral_plans()

    # Bot username for deep link
    bot_user = client.me.username if getattr(client, "me", None) and client.me.username else "TgPremiumDownlaoder_bot"
    invite_link = f"https://t.me/{bot_user}?start=ref_{user_id}"

    # Next milestone calculation based on active plans
    next_plan = None
    for p in plans:
        if p["invites"] > total_invites:
            next_plan = p
            break

    if next_plan:
        target_inv = next_plan["invites"]
        rew_d = next_plan["days"]
        pct = (total_invites / float(target_inv)) * 100.0
        bar = generate_blocks(pct, total_blocks=6, filled_char="🟧", empty_char="⬜")
        milestone_text = f"• Next VIP Milestone: **{bar} {total_invites}/{target_inv}** (Reward: **+{rew_d} Days VIP**)"
    elif plans:
        max_p = max(plans, key=lambda x: x["invites"])
        max_inv = max_p["invites"]
        cur_prog = total_invites % max_inv
        pct = (cur_prog / float(max_inv)) * 100.0 if max_inv else 100.0
        bar = generate_blocks(pct, total_blocks=6, filled_char="🟧", empty_char="⬜")
        milestone_text = f"• Next VIP Milestone: **{bar} {cur_prog}/{max_inv}** (All Tiers Completed! Total: **{total_invites}**)"
    else:
        milestone_text = f"• Total Friends Invited: **{total_invites} Members**"

    # Pre-filled share URL
    share_text = (
        "🚀 Unlock and download any private or restricted Telegram channel lectures, videos, and PDFs instantly! "
        "Try this bot for free:"
    )
    share_url = f"https://t.me/share/url?url={invite_link}&text={share_text.replace(' ', '%20')}"

    # Dynamic Reward Repertoire list from database
    repertoire_lines = [
        f" • **Each Verified Invite** ➔ **+{pts_per} Points Earned!**"
    ]
    if plans:
        for p in plans:
            repertoire_lines.append(f" • **{p['invites']} Friends Invited** ➔ **+{p['days']} Days Free VIP!**")
    else:
        repertoire_lines.append(" • _No milestone plans configured currently._")
    repertoire_lines.append(f" • **Friend Purchases VIP** ➔ **+{purch_days} Days Bonus VIP!**")
    repertoire_lines.append(f" • **{redeem_pts} Points** ➔ Redeemable for **+{redeem_days} Days VIP!**")
    repertoire_block = "\n".join(repertoire_lines)

    text = (
        "👥 **VIRAL REFERRAL & REWARDS DASHBOARD** 👥\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 **INVITE FRIENDS & EARN FREE VIP ACCESS**\n\n"
        "Share your personal invite link with friends, study groups, or admission channels. "
        "Every time a new user joins with your link, you earn bonus points and free VIP access!\n\n"
        "┌── 🔗 **YOUR PERSONAL INVITE LINK** ──┐\n"
        f"│ `{invite_link}`\n"
        "└────────────────────────────────────┘\n\n"
        "┌── 📊 **YOUR NETWORK METRICS** ───────┐\n"
        f" • Total Friends Invited: **{total_invites} Members**\n"
        f" • Accumulated Points: **{points} Pts**\n"
        f" {milestone_text}\n"
        "└────────────────────────────────────┘\n\n"
        "┌── 💎 **REWARD REPERTOIRE** ──────────┐\n"
        f"{repertoire_block}\n"
        "└────────────────────────────────────┘\n\n"
        "👇 _Tap below to copy your link or share directly to your groups:_"
    )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📢 Share to Friends & Groups", url=share_url),
            ],
            [
                InlineKeyboardButton("🎁 Redeem Points for VIP", callback_data="claim_referral_reward"),
                InlineKeyboardButton("🔄 Refresh Stats", callback_data="refresh_referral_stats"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main"),
            ],
        ]
    )

    return apply_custom_emojis(text), markup


@Client.on_message(filters.command(["ref", "referral", "invite"]) & filters.private)
async def referral_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    text, markup = await render_referral_card(client, user_id)
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^user_view_referral$"))
async def callback_view_referral(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    text, markup = await render_referral_card(client, user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
    await query.answer()


@Client.on_callback_query(filters.regex(r"^refresh_referral_stats$"))
async def callback_refresh_referral(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    text, markup = await render_referral_card(client, user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass
    await query.answer("✅ Stats updated!", show_alert=False)


@Client.on_callback_query(filters.regex(r"^claim_referral_reward$"))
async def callback_claim_reward(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    stats = await db.get_referral_stats(user_id)
    pts = stats.get("points", 0)

    cfg = await db.get_referral_config()
    redeem_pts = cfg["redeem_points"]
    redeem_days = cfg["redeem_days"]

    if pts < redeem_pts:
        needed = redeem_pts - pts
        await query.answer(
            f"⚠️ You have {pts} points. You need {needed} more points ({redeem_pts} points = +{redeem_days} Days VIP)!",
            show_alert=True,
        )
        return

    # Deduct configured points and grant configured VIP days
    await db.deduct_referral_points(user_id, redeem_pts)
    await db.add_premium(user_id, redeem_days)
    await query.answer(f"🎉 Congratulations! +{redeem_days} Days VIP Premium unlocked!", show_alert=True)
    text, markup = await render_referral_card(client, user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


# =========================================================================
# ADMIN REFERRAL REWARDS CONFIGURATION COMMANDS
# =========================================================================

def _is_admin(user_id: int) -> bool:
    from config import ADMIN_IDS
    return user_id in ADMIN_IDS


@Client.on_message(filters.command(["refplans", "referralplans"]) & filters.private)
async def admin_view_ref_plans_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not _is_admin(user_id):
        return
    plans = await db.get_referral_plans()
    cfg = await db.get_referral_config()

    plan_lines = []
    for i, p in enumerate(plans, 1):
        plan_lines.append(f"• **Tier {i}:** `{p['invites']} Friends Invited` ➔ `+{p['days']} Days VIP` (Delete: `/delref {p['invites']}`)")

    text = (
        "📋 **ACTIVE REFERRAL MILESTONE PLANS** 📋\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(plan_lines) + "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• Points Award: `+{cfg['points_per_invite']} pts` per invite\n"
        f"• Points Redeem: `{cfg['redeem_points']} pts` ➔ `+{cfg['redeem_days']} Days VIP`\n"
        f"• Friend VIP Purchase: `+{cfg['purchase_reward_days']} Days VIP`\n\n"
        "┌── 🛠️ **MANAGE PLANS** ────────────────┐\n"
        "│ • Add a plan: `/addref <invites> <days>`\n"
        "│ • Delete a plan: `/delref <invites>`\n"
        "│ • Reset all: `/resetref`\n"
        "└──────────────────────────────────────┘"
    )
    await message.reply_text(text)


@Client.on_message(filters.command(["addref", "addrefplan", "setref", "setreferral"]) & filters.private)
async def admin_add_ref_plan_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not _is_admin(user_id):
        return

    if len(message.command) < 3:
        await admin_view_ref_plans_command(client, message)
        return

    try:
        t_inv = int(message.command[1])
        rew_days = int(message.command[2])
        if t_inv < 1 or rew_days < 1:
            await message.reply_text("❌ Target invites and VIP days must be positive numbers (e.g. `5 7`).")
            return

        await db.add_referral_plan(t_inv, rew_days)
        await db.set_referral_config(target_invites=t_inv, reward_days=rew_days)
        await message.reply_text(
            "✅ **Referral VIP Plan Added Successfully!**\n\n"
            f"👥 **Milestone:** Every **{t_inv} Friends Invited**\n"
            f"🎁 **Reward:** **+{rew_days} Days Free VIP!**\n\n"
            "This plan is now live on all user `/ref` dashboards under 'Reward Repertoire'!"
        )
    except ValueError:
        await message.reply_text("❌ Invalid format. Please send numbers, e.g.: `/addref 5 7`")


@Client.on_message(filters.command(["delref", "delrefplan", "removeref"]) & filters.private)
async def admin_del_ref_plan_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not _is_admin(user_id):
        return

    if len(message.command) < 2:
        await message.reply_text("⚠️ Send invite count to delete, e.g.: `/delref 3`")
        return

    try:
        t_inv = int(message.command[1])
        deleted = await db.delete_referral_plan(t_inv)
        if deleted:
            await message.reply_text(
                f"🗑️ **Referral Plan Deleted!**\n\n"
                f"Tier `{t_inv} Invites` has been removed from all user `/ref` dashboards."
            )
        else:
            await message.reply_text(f"⚠️ No referral plan found with `{t_inv}` invites. Use `/refplans` to view active plans.")
    except ValueError:
        await message.reply_text("❌ Send a number, e.g.: `/delref 3`")


@Client.on_message(filters.command(["resetref", "resetreferral"]) & filters.private)
async def admin_reset_ref_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not _is_admin(user_id):
        return

    await db.reset_referral_plans()
    await db.set_referral_config(target_invites=3, reward_days=3)
    await message.reply_text("🔄 **Referral plans reset to default:** `3 Friends Invited = +3 Days VIP`.")


@Client.on_message(filters.command(["setrefpoints"]) & filters.private)
async def admin_set_ref_points_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not _is_admin(user_id):
        return

    if len(message.command) < 4:
        await message.reply_text(
            "⚙️ **Set Referral Points & Redemption**\n\n"
            "**Format:** `/setrefpoints <points_per_invite> <redeem_pts> <redeem_days>`\n"
            "**Example:** `/setrefpoints 5 15 3`\n"
            "_(Means: 5 points per invite, and 15 points can be redeemed for 3 days VIP)_"
        )
        return

    try:
        pts = int(message.command[1])
        r_pts = int(message.command[2])
        r_days = int(message.command[3])
        await db.set_referral_config(
            points_per_invite=pts,
            redeem_points=r_pts,
            redeem_days=r_days,
        )
        await message.reply_text(
            f"✅ **Referral Points Updated!**\n\n"
            f"• Points per Invite: `+{pts} pts`\n"
            f"• Redeem Requirement: `{r_pts} pts` ➔ `+{r_days} Days VIP`"
        )
    except ValueError:
        await message.reply_text("❌ Invalid numbers. Example: `/setrefpoints 5 15 3`")


def aiosqlite_connect(db_file):
    import aiosqlite
    return aiosqlite.connect(db_file)
