# language: Python, file: handlers/start.py, target: Python 3.10+, Pyrogram
"""
Start and Help command handlers with Force-Subscribe, user registration, and membership status.
All callbacks use callback_query.from_user.id — never callback_query.message.from_user
(the bot's own user object).
"""

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import UserNotParticipant
from config import ADMIN_IDS, WEB_DASHBOARD_URL
from database import db
from core.i18n import t, get_lang_display
from core.emojis import apply_custom_emojis


import re
import time

# In-memory TTL cache for force-sub: {user_id: timestamp_valid_until}
# Capped at 10_000 entries; oldest 500 are evicted when the cap is hit.
_fsub_cache: dict[int, float] = {}
_FSUB_CACHE_MAX = 10_000
_FSUB_CACHE_EVICT = 500
_pending_claims: dict[int, str] = {}


def _fsub_cache_set(user_id: int, value: float) -> None:
    global _fsub_cache
    if len(_fsub_cache) >= _FSUB_CACHE_MAX:
        # Evict the _FSUB_CACHE_EVICT smallest-valued (i.e., earliest-expiring) entries
        evict_keys = sorted(_fsub_cache, key=lambda k: _fsub_cache[k])[:_FSUB_CACHE_EVICT]
        for k in evict_keys:
            _fsub_cache.pop(k, None)
    _fsub_cache[user_id] = value


async def check_force_sub(client: Client, user_id: int) -> bool:
    """Checks if user has joined the required channel with 15-minute in-memory cache."""
    if user_id in ADMIN_IDS:
        return True

    now = time.time()
    if user_id in _fsub_cache and _fsub_cache[user_id] > now:
        return True

    fsub = await db.get_force_sub_channel()
    if not fsub:
        _fsub_cache_set(user_id, now + 900)
        return True

    try:
        raw = str(fsub).strip()
        chat_target = int(raw) if raw.lstrip("-").isdigit() else raw
        member = await client.get_chat_member(chat_target, user_id)
        is_member = member.status not in ("kicked", "left")
        if is_member:
            _fsub_cache_set(user_id, now + 900)  # 15 minutes cache
        return is_member
    except UserNotParticipant:
        _fsub_cache.pop(user_id, None)
        return False
    except Exception:
        return True


async def credit_verified_referral(client: Client, inviter_id: int, user_id: int, first_name: str, username: str):
    """
    Credits a referral after user has passed anti-bot & human verification.
    """
    added, note, count = await db.add_referral(inviter_id, user_id)
    if added:
        try:
            u_display = f"@{username}" if username else first_name
            ref_cfg = await db.get_referral_config()
            pts_awarded = ref_cfg["points_per_invite"]
            inviter_msg = (
                "🎉 **NEW REFERRAL VERIFIED!** 🎉\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Friend: **{first_name}** ({u_display})\n"
                f"🛡️ Security Status: **Verified Human & Active 🟢**\n"
                f"🎁 You earned: **+{pts_awarded} Bonus Points!**\n"
                f"📊 Total Network: **{count} Invited**\n"
            )
            if note:
                inviter_msg += f"\n{note}\n"
            inviter_msg += "\n👉 Check your reward balance anytime with `/ref`!"
            await client.send_message(chat_id=inviter_id, text=inviter_msg)
        except Exception as notify_err:
            print(f"[!] Referral notification to {inviter_id} failed: {notify_err}")


@Client.on_message(filters.command(["start", "help"]) & filters.private)
async def start_handler(client: Client, message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "User"
    username = message.from_user.username or ""

    # 1. Anti-Fake: Reject automated bot accounts or telegram-flagged fake/scam accounts
    if getattr(message.from_user, "is_bot", False):
        return
    if getattr(message.from_user, "is_fake", False) or getattr(message.from_user, "is_scam", False):
        return

    if await db.is_user_banned(user_id):
        await message.reply_text(
            "⛔ **Account Suspended**\n\nYour account has been suspended from using this bot by the administration."
        )
        return

    if await db.get_maintenance_mode() and user_id not in ADMIN_IDS:
        up_url = await db.get_official_channel()
        if not up_url.startswith("http"):
            up_url = f"https://t.me/{up_url.lstrip('@')}"
        await message.reply_text(
            "🛠️ **System Maintenance In Progress**\n\n"
            "The bot is currently undergoing scheduled maintenance.\n"
            "Normal service will resume shortly. Thank you for your patience!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📢 Updates Channel", url=up_url)]]
            ),
        )
        return

    # 2. Anti-Fake: Check if user already exists in database BEFORE registering
    existing_user = await db.get_user(user_id)
    is_brand_new_user = (existing_user is None)

    await db.register_user(user_id, first_name, username)

    # 3. Process 1-Click Auto Claim or Viral Referral Parameter
    cmd = message.command
    has_ref_param = False
    inviter_id = None
    claim_code = None
    if cmd and len(cmd) > 1:
        param = cmd[1].strip()
        if param.lower().startswith(("claim_", "redeem_", "code_")):
            claim_code = re.sub(r"^(?:claim_|redeem_|code_)", "", param, flags=re.IGNORECASE).strip()
        elif is_brand_new_user and param.startswith("ref_"):
            try:
                candidate_inviter = int(param.split("ref_")[1])
                if candidate_inviter != user_id:
                    inviter_id = candidate_inviter
                    has_ref_param = True
            except Exception:
                pass

    # 4. Check Force-Subscribe Channel
    is_joined = await check_force_sub(client, user_id)
    if not is_joined:
        if claim_code:
            _pending_claims[user_id] = claim_code
        if has_ref_param and inviter_id:
            # Hold referral as pending until user verifies channel membership!
            await db.add_pending_referral(user_id, inviter_id)

        fsub_str = await db.get_force_sub_channel()
        fsub_invite = await db.get_force_sub_invite_link()
        if fsub_invite:
            join_url = fsub_invite
        elif str(fsub_str).startswith("http"):
            join_url = fsub_str
        elif str(fsub_str).startswith("@"):
            join_url = f"https://t.me/{str(fsub_str).lstrip('@')}"
        else:
            join_url = f"https://t.me/{fsub_str}"

        await message.reply_text(
            f"👋 Hello **{first_name}**!\n\n"
            "To use this bot, please join our official updates channel first.\n"
            "After joining, click **Verify Membership** below.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📢 Join Updates Channel", url=join_url)],
                    [InlineKeyboardButton("🔄 Verify Membership", callback_data="verify_fsub")],
                ]
            ),
        )
        return

    # 5. Anti-Headless Bot Gate: If user came via referral link without Force-Sub active
    if has_ref_param and inviter_id:
        fsub_channel = await db.get_force_sub_channel()
        if fsub_channel:
            # Already passed official channel verification!
            await credit_verified_referral(client, inviter_id, user_id, first_name, username)
        else:
            # Force-sub channel not active: Require 1-tap Human verification button
            await db.add_pending_referral(user_id, inviter_id)
            await message.reply_text(
                f"👋 Welcome, **{first_name}**!\n\n"
                "🛡️ **Anti-Bot Human Verification**\n"
                "To ensure legitimate user traffic and prevent automated scripts, "
                "please tap the button below to verify your account and unlock access:",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🛡️ I am Human - Unlock Free Access 🚀", callback_data="verify_human_ref")],
                    ]
                ),
            )
            return

    # 6. Auto-Claim 1-Click Code if arrived via deep link
    if claim_code:
        _pending_claims.pop(user_id, None)
        success, reply = await db.redeem_coupon(user_id, claim_code)
        await message.reply_text(
            f"🎟️ **AUTO-CLAIM VIP CODE** 🎁\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{reply}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👉 Send any restricted link anytime to download!"
        )
        if success:
            return

    text, markup = await render_start_card(client, user_id, first_name)
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


async def render_start_card(client: Client, user_id: int, first_name: str):
    from core.progress import generate_blocks
    sim_mode = await db.get_simulated_mode(user_id) if user_id in ADMIN_IDS else "normal"
    is_prem = await db.is_user_premium(user_id)
    session = await db.get_session(user_id)
    login_status = "🟢 Linked & Verified" if session else "⚪ Not Connected (`/login`)"
    free_limit = await db.get_free_daily_limit()

    if sim_mode == "free":
        user_info = await db.get_user(user_id)
        used = user_info.get("daily_downloads_used", 0) if user_info else 0
        remaining = max(0, free_limit - used)
        pct = (remaining / free_limit * 100) if free_limit > 0 else 0
        q_bar = generate_blocks(pct, total_blocks=8, filled_char="🟧", empty_char="⬜")
        status_banner = (
            "╭── 🧪 **[ARM SQUAD] TEST SIMULATION** ─────╮\n"
            f"│ • Squad Clearance : `Standard Operative (Sim)`\n"
            f"│ • Daily Energy    : `{q_bar} {remaining}/{free_limit} Left`\n"
            f"│ • Cloud Uplink    : `{login_status}`\n"
            f"│ • Stream Engine   : `Direct Zero-Loss Stream`\n"
            "╰── _(Testing Free user limits. Revert: `/mode admin`)_ ──╯"
        )
        action_btn = InlineKeyboardButton("💎 Upgrade to VIP Elite Pass", callback_data="user_view_premium")
    elif sim_mode == "vip":
        status_banner = (
            "╭── 🧪 **[ARM SQUAD] VIP SIMULATION** ──────╮\n"
            "│ • Squad Clearance : `VIP Elite Commander (Sim)`\n"
            "│ • Daily Energy    : `🟧🟧🟧🟧🟧🟧🟧🟧 100% Unlimited ⚡`\n"
            f"│ • Engine Speed    : `⚡ Turbo VIP (0 Queue Latency)`\n"
            f"│ • Cloud Uplink    : `{login_status}`\n"
            "╰── _(Testing VIP user perks. Revert: `/mode admin`)_ ──╯"
        )
        action_btn = InlineKeyboardButton("🧪 Switch Test Mode", callback_data="adm_view_mode_menu")
    elif user_id in ADMIN_IDS:
        status_banner = (
            "╭── 👑 **[ARM SQUAD] SUPREME COMMANDER** ───╮\n"
            "│ • Clearance Level : `Master Architect (God Mode)`\n"
            "│ • Daily Quota     : `🟧🟧🟧🟧🟧🟧🟧🟧 Unrestricted ⚡`\n"
            f"│ • Cloud Uplink    : `{login_status}`\n"
            "│ • Engine Core     : `🟢 36 Assault Workers Online`\n"
            "╰───────────────────────────────────────────╯"
        )
        action_btn = InlineKeyboardButton("👑 Master Admin Command Center", callback_data="adm_open_panel")
    elif is_prem:
        user_info = await db.get_user(user_id)
        expiry = user_info.get("premium_expiry") or "Lifetime Access" if user_info else "Lifetime Access"
        status_banner = (
            "╭── 💎 **[ARM SQUAD] VIP ELITE SQUADRON** ──╮\n"
            "│ • Squad Clearance : `VIP Elite Commander`\n"
            f"│ • Access Pass     : `{expiry}`\n"
            "│ • Daily Energy    : `🟧🟧🟧🟧🟧🟧🟧🟧 100% Unlimited ⚡`\n"
            f"│ • Engine Priority : `⚡ Turbo VIP (0 Queue Latency)`\n"
            f"│ • Cloud Uplink    : `{login_status}`\n"
            "╰───────────────────────────────────────────╯"
        )
        action_btn = InlineKeyboardButton("💎 VIP Elite Member Dashboard", callback_data="user_view_premium")
    else:
        user_info = await db.get_user(user_id)
        used = user_info.get("daily_downloads_used", 0) if user_info else 0
        remaining = max(0, free_limit - used)
        pct = (remaining / free_limit * 100) if free_limit > 0 else 0
        q_bar = generate_blocks(pct, total_blocks=8, filled_char="🟧", empty_char="⬜")
        status_banner = (
            "╭── ⚔️ **[ARM SQUAD] OPERATIVE STATUS** ────╮\n"
            f"│ • Squad Clearance : `Standard Operative`\n"
            f"│ • Daily Energy    : `{q_bar} {remaining}/{free_limit} Left Today`\n"
            f"│ • Cloud Uplink    : `{login_status}`\n"
            f"│ • Stream Engine   : `⚡ Direct Zero-Loss Stream`\n"
            "│ • Tactical Perk   : `Unlock 30x Batch with /premium`\n"
            "╰───────────────────────────────────────────╯"
        )
        action_btn = InlineKeyboardButton("💎 Upgrade to VIP Elite Pass", callback_data="user_view_premium")

    lang = await db.get_user_language(user_id)
    lang_display = get_lang_display(lang)

    text = t(
        "start_welcome",
        lang,
        first_name=first_name,
        status_banner=status_banner,
        login_status=login_status,
        lang_display=lang_display,
    )

    markup_buttons = [
        [
            action_btn,
        ],
        [
            InlineKeyboardButton("⚡ Quick Strike (Download)", callback_data="wizard_start_download"),
            InlineKeyboardButton("🔐 Multi-Accounts (QR)", callback_data="user_view_login"),
        ],
        [
            InlineKeyboardButton("🎬 Brand Studio", callback_data="user_view_watermark"),
            InlineKeyboardButton("✂️ Caption Studio", callback_data="user_view_caption_studio"),
        ],
        [
            InlineKeyboardButton("🖼️ Custom Thumbnail", callback_data="user_view_thumbnail"),
            InlineKeyboardButton("🛠️ Tactical Armory", callback_data="user_view_toolbox"),
        ],
        [
            InlineKeyboardButton("📺 Stream Quality", callback_data="user_view_resolution"),
            InlineKeyboardButton("⚙️ Squad Settings", callback_data="user_view_settings"),
        ],
        [
            InlineKeyboardButton("👥 Squad Referral", callback_data="user_view_referral"),
            InlineKeyboardButton("📊 Tier Comparison", callback_data="user_view_features"),
        ],
        [
            InlineKeyboardButton("📖 Tactical Manual", callback_data="user_view_guide"),
            InlineKeyboardButton(f"🌐 {lang_display}", callback_data="user_view_language"),
        ],
    ]

    if user_id in ADMIN_IDS:
        markup_buttons.append([
            InlineKeyboardButton("⚡ 👥 Worker Accounts", callback_data="view_my_accounts"),
            InlineKeyboardButton("👑 Master Admin Panel", callback_data="adm_open_panel"),
        ])
        markup_buttons.append([
            InlineKeyboardButton("🔄 Switch Test Mode", callback_data="adm_view_mode_menu"),
        ])

    web_studio_url = await db.get_web_studio_url()
    official_channel_url = await db.get_official_channel()
    if not official_channel_url.startswith("http"):
        official_channel_url = f"https://t.me/{official_channel_url.lstrip('@')}"

    banner = await db.get_custom_start_banner()
    if banner:
        text = f"📢 **ANNOUNCEMENT:**\n{banner}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + text

    markup_buttons.append([
        InlineKeyboardButton("🌐 Web Studio UI Cockpit", url=web_studio_url),
        InlineKeyboardButton("📢 Official Channel", url=official_channel_url),
    ])

    return apply_custom_emojis(text), InlineKeyboardMarkup(markup_buttons)


async def render_features_comparison_card(user_id: int):
    """
    Renders a compact, high-aesthetic Free vs VIP comparison matrix.
    Mobile-friendly, concise format without giant ASCII blocks.
    """
    free_limit = await db.get_free_daily_limit()
    free_batch = await db.get_tier_max_batch("free")
    vip_batch = await db.get_tier_max_batch("vip")
    is_prem = await db.is_user_premium(user_id)
    lang = await db.get_user_language(user_id)

    # Dynamic feature toggle states from database
    f_batch = await db.get_feature_state("free", "batch")
    f_topic = await db.get_feature_state("free", "topic")
    f_chan = await db.get_feature_state("free", "channel")
    f_res = await db.get_feature_state("free", "resolution")
    f_clean = await db.get_feature_state("free", "clean_video")
    f_custom_wm = await db.get_feature_state("free", "custom_wm")
    f_fwd = await db.get_feature_state("free", "forward")

    # Dynamic VIP pricing line from database
    vip_plans = await db.get_vip_plans()
    bn_parts = []
    en_parts = []
    for p in vip_plans.values():
        bn_parts.append(f"`{p['name']}: {p['price_bdt']}৳`")
        en_parts.append(f"`{p['name']}: {p['price_bdt']}৳`")
    vip_passes_bn = " • ".join(bn_parts) if bn_parts else "`৭ দিন: ১০০৳` • `৩০ দিন: ২৫০৳` • `লাইফটাইম: ৬০০৳`"
    vip_passes_en = " • ".join(en_parts) if en_parts else "`7 Days: 100৳` • `30 Days: 250৳` • `Lifetime: 600৳`"

    if lang == "bn":
        my_status = "💎 আপনার স্ট্যাটাস: **VIP Premium Member**" if is_prem else "⚪ আপনার স্ট্যাটাস: **Standard Free Tier**"
        batch_free_str = f"সর্বোচ্চ {free_batch} টি" if f_batch else "সিঙ্গেল লিংক"
        topic_free_str = "আনলকড" if f_topic else "লকড"
        res_free_str = "1080p/720p" if f_res else "অরিজিনাল"
        wm_free_str = "কাস্টম" if f_custom_wm else ("ক্লিন" if f_clean else "ব্র্যান্ডিং ট্যাগ")
        fwd_free_str = "প্রাইভেট চ্যানেল" if f_fwd else "ডিরেক্ট চ্যাট"

        text = (
            "📊 **ফিচার তুলনা: FREE বনাম VIP** 📊\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{my_status}\n\n"
            "⚡ **স্পিড ও লিমিট:**\n"
            f"• দৈনিক কোটা: `{free_limit} টি/দিন` ➔ **VIP: আনলিমিটেড ⚡**\n"
            "• ডাউনলোডের গতি: `স্ট্যান্ডার্ড` ➔ **VIP: টার্বো ইনস্ট্যান্ট**\n"
            "• ক্লাউড ক্যাশ রিকল: `স্বাভাবিক` ➔ **VIP: ০.১ সেকেন্ডে**\n\n"
            "📑 **ব্যাচ ও কোর্স ক্লোনিং:**\n"
            f"• রেঞ্জ ডাউনলোড: `{batch_free_str}` ➔ **VIP: {vip_batch} টি একসাথে**\n"
            f"• ফোরাম টপিক ও ক্লোন: `{topic_free_str}` ➔ **VIP: সম্পূর্ণ আনলকড**\n"
            "• ফাইলের সিরিয়াল: `সাধারণ` ➔ **VIP: ১➔২➔৩ ক্রমানুসারে**\n\n"
            "🎬 **মিডিয়া স্টুডিও ও ফরওয়ার্ড:**\n"
            f"• রেজোলিউশন: `{res_free_str}` ➔ **VIP: 1080p/720p/480p**\n"
            "• অডিও কনভার্টার: `ভিডিও` ➔ **VIP: 192k MP3 পডকাস্ট**\n"
            f"• ওয়াটারমার্ক: `{wm_free_str}` ➔ **VIP: ১০০% ক্লিন / নিজস্ব লোগো**\n"
            f"• ক্লাউড ব্যাকআপ: `{fwd_free_str}` ➔ **VIP: অটো ব্যাকআপ চ্যানেল**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 **ভিআইপি প্ল্যান:** {vip_passes_bn}"
        )
    else:
        my_status = "💎 Status: **VIP Premium Member**" if is_prem else "⚪ Status: **Standard Free Tier**"
        batch_free_str = f"Max {free_batch} Links" if f_batch else "Single Link"
        topic_free_str = "Unlocked" if f_topic else "VIP Locked"
        res_free_str = "1080p/720p" if f_res else "Original Stream"
        wm_free_str = "Custom" if f_custom_wm else ("Clean" if f_clean else "Bot Branding")
        fwd_free_str = "Private Channel" if f_fwd else "Direct Chat"

        text = (
            "📊 **FEATURE MATRIX: FREE vs VIP** 📊\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{my_status}\n\n"
            "⚡ **Speed & Limits:**\n"
            f"• Daily Quota: `{free_limit}/day` ➔ **VIP: Unlimited ⚡**\n"
            "• Priority Queue: `Standard` ➔ **VIP: Instant Turbo**\n"
            "• Cloud Vault Cache: `Normal` ➔ **VIP: 0.1s Direct**\n\n"
            "📑 **Batch & Topic Harvesting:**\n"
            f"• Range Batch: `{batch_free_str}` ➔ **VIP: Up to {vip_batch} Links**\n"
            f"• Topic & Clone: `{topic_free_str}` ➔ **VIP: Full Mirror**\n"
            "• File Ordering: `Standard` ➔ **VIP: Strict 1➔2➔3 Serial**\n\n"
            "🎬 **Media Lab & Vault:**\n"
            f"• Video Resolution: `{res_free_str}` ➔ **VIP: 1080p / 720p / 480p**\n"
            "• Audio Extractor: `Original` ➔ **VIP: 192k MP3 Podcast**\n"
            f"• Video Watermark: `{wm_free_str}` ➔ **VIP: 100% Clean / Custom Logo**\n"
            f"• Cloud Mirror: `{fwd_free_str}` ➔ **VIP: Private Auto-Forward**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 **VIP Passes:** {vip_passes_en}"
        )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💎 Upgrade to VIP Now", callback_data="user_view_premium"),
                InlineKeyboardButton("📖 Official Field Guide", callback_data="user_view_guide"),
            ],
            [
                InlineKeyboardButton("👥 Referral & Earn VIP", callback_data="user_view_referral"),
                InlineKeyboardButton("⚙️ Settings Cockpit", callback_data="user_view_settings"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return apply_custom_emojis(text), markup


def render_guide_card():
    text = (
        "📖 **OFFICIAL USER MANUAL & FIELD GUIDE** 📖\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **MASTERING THE HARVESTER IN 8 SIMPLE STEPS**\n\n"
        "✦ **1️⃣ Single Post Download:**\n"
        "Send any restricted Telegram link directly to this chat.\n"
        "• _Example:_ `https://t.me/c/2459862936/1019`\n\n"
        "✦ **2️⃣ Multi-Link & Range Harvesting (Batch):**\n"
        "Download entire course modules sequentially with exact 1➔2➔3 ordering:\n"
        "• _URL Format:_ `https://t.me/c/2459862936/1019-1035`\n"
        "• _Command Format:_ `/range https://t.me/c/2459862936 1019 1035`\n\n"
        "✦ **3️⃣ Forum Topic Thread Cloning:**\n"
        "Harvest an entire subject thread from modern forum channels:\n"
        "• `/topic https://t.me/c/2459862936 2 1019 1050`\n"
        "• `/clone https://t.me/c/2459862936 1 50`\n\n"
        "✦ **4️⃣ 192kbps MP3 Audio Podcast Extractor:**\n"
        "Convert video lectures into compact, high-quality audio podcasts:\n"
        "• Open `/settings` ➔ Tap **Format: MP3 Audio**.\n"
        "• Or use `/audio` anytime to toggle mode.\n\n"
        "✦ **5️⃣ Custom Video Thumbnail Studio:**\n"
        "Set a custom poster/cover image for all video deliveries:\n"
        "• Send `/thumb` or `/setthumb` with an image to activate.\n\n"
        "✦ **6️⃣ Caption & Credit Studio (`/caption`):**\n"
        "Strip competitor promo links, channels, credits, or swap text:\n"
        "• `/caption` ➔ Open interactive Caption Cockpit\n"
        "• `/setcaption none` ➔ Remove all captions completely (Blank)\n"
        "• `/setcaption 🎬 {title}\n📢 @MyChannel` ➔ Custom branding template\n"
        "• `/replacecaption @OldChannel | @MyChannel` ➔ Swap text/channels\n"
        "• `/clearreplacements` ➔ Clear all replace rules\n\n"
        "✦ **7️⃣ Private Channel Authentication:**\n"
        "To download from private groups you have joined:\n"
        "• Send `/login` and scan the instant QR code from your Telegram app.\n\n"
        "✦ **8️⃣ Personal Cloud Backup Channel:**\n"
        "Add this bot as Admin to your private channel and configure:\n"
        "• Send: `/setchannel -1001234567890` (your channel ID)\n"
        "• All your downloads will silently mirror there automatically.\n\n"
        "✦ **9️⃣ Universal Web Video Harvester (Omni-Source):**\n"
        "Download from YouTube, Instagram Reels, Facebook, TikTok, Terabox, or Direct URLs:\n"
        "• Just paste any video URL directly here—the bot automatically extracts and sends it as a streamable video!\n\n"
        "✦ **🔟 1-Click Channel Cloner (`/clone`):**\n"
        "Mirror an entire course channel of 100+ videos directly into your backup channel:\n"
        "• `/clone <source_channel> <target_channel> [start_id] [end_id]`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💎 Upgrade to VIP Premium", callback_data="user_view_premium"),
                InlineKeyboardButton("📊 Compare Free vs VIP", callback_data="user_view_features"),
            ],
            [
                InlineKeyboardButton("🖼️ Thumbnail Studio", callback_data="user_view_thumbnail"),
                InlineKeyboardButton("⚙️ Settings & Forward", callback_data="user_view_settings"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main"),
            ]
        ]
    )
    return apply_custom_emojis(text), markup


# ─────────────────────────── CALLBACKS ──────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^(back_to_main|user_view_main)$"))
async def back_to_main_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    first_name = callback_query.from_user.first_name or "User"
    text, markup = await render_start_card(client, user_id, first_name)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^user_view_guide$"))
async def user_view_guide_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text, markup = render_guide_card()
    try:
        await callback_query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


@Client.on_message(filters.command(["guide", "manual"]) & filters.private)
async def guide_command_handler(client: Client, message: Message):
    text, markup = render_guide_card()
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_message(filters.command(["features", "tiers", "compare"]) & filters.private)
async def features_command_handler(client: Client, message: Message):
    text, markup = await render_features_comparison_card(message.from_user.id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^user_view_features$"))
async def user_view_features_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text, markup = await render_features_comparison_card(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^verify_fsub$"))
async def verify_fsub_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    first_name = callback_query.from_user.first_name or "User"
    username = callback_query.from_user.username or ""
    is_joined = await check_force_sub(client, user_id)
    if is_joined:
        # Finalize any pending referral now that user has joined the channel!
        pending_inviter = await db.get_pending_referral(user_id)
        if pending_inviter:
            await db.remove_pending_referral(user_id)
            await credit_verified_referral(client, pending_inviter, user_id, first_name, username)

        # Auto-claim any 1-Click code that was held pending channel join
        pending_code = _pending_claims.pop(user_id, None)
        if pending_code:
            success, reply = await db.redeem_coupon(user_id, pending_code)
            try:
                await callback_query.message.reply_text(
                    f"🎟️ **AUTO-CLAIM VIP CODE** 🎁\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{reply}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👉 Send any restricted link anytime to download!"
                )
            except Exception:
                pass

        await callback_query.answer("✅ Verification successful! Welcome aboard!", show_alert=True)
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        text, markup = await render_start_card(client, user_id, first_name)
        try:
            await callback_query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass
    else:
        await callback_query.answer("❌ You have not joined the channel yet! Please join first.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^verify_human_ref$"))
async def verify_human_ref_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    first_name = callback_query.from_user.first_name or "User"
    username = callback_query.from_user.username or ""

    # Finalize any pending referral now that human user clicked verify!
    pending_inviter = await db.get_pending_referral(user_id)
    if pending_inviter:
        await db.remove_pending_referral(user_id)
        await credit_verified_referral(client, pending_inviter, user_id, first_name, username)

    await callback_query.answer("✅ Human verification complete! Access unlocked.", show_alert=False)
    text, markup = await render_start_card(client, user_id, first_name)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^user_view_premium$"))
async def user_view_premium_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    from handlers.premium import render_premium_card
    text, markup = await render_premium_card(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^user_view_watermark$"))
async def user_view_watermark_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    from handlers.watermark import render_watermark_dashboard
    text, markup = await render_watermark_dashboard(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
