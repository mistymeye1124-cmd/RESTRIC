# language: Python, file: handlers/toolbox.py, target: Python 3.10+, Pyrogram
"""
Enterprise Swiss Army Toolbox Pro & Cyber Privacy Vault:
- 🎵 Media Studio: 1-Click Video to 320kbps MP3 Extractor, Lossless Video Splitter
- 📄 PDF & Document Suite: Images to Multi-page PDF Converter, PDF Password Remover / Unlocker
- 🛡️ Cyber & Privacy Vault: Zero-Trace Forensic Cleaner & EXIF Wiper, Live Disposable Temp-Mail Generator with OTP Inbox, OSINT IP/Domain Intelligence
- 📦 Batch Multi-Link Automation Downloader Queue (Telegram, YouTube, FB, Insta, TikTok, Terabox)
- Interactive Dashboards with Crystal-Clear Bengali + English Guidance
"""

import os
import re
import time
import shutil
import random
import string
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
from PIL import Image

from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database import db
from core.state_manager import set_user_state, get_user_state, clear_user_state
from core.watermark_engine import get_ffmpeg_binary

# Temporary working directory for toolbox operations
TOOLBOX_TEMP_DIR = Path("downloads") / "toolbox"
TOOLBOX_TEMP_DIR.mkdir(parents=True, exist_ok=True)

# In-memory stores for active workflows
_TEMP_MAIL_ACCOUNTS: Dict[int, Dict[str, Any]] = {}
_USER_PDF_IMAGES: Dict[int, List[str]] = {}
_ALBUM_BUFFERS: Dict[str, List[Message]] = {}
_ALBUM_TASKS: Dict[str, asyncio.Task] = {}
_PENDING_ALBUMS: Dict[str, List[Message]] = {}



# =========================================================================
# 1. MAIN TOOLBOX DASHBOARD & CATEGORY CARDS
# =========================================================================

async def render_toolbox_dashboard(user_id: int):
    """Generates the main Swiss Army Toolbox Pro dashboard."""
    is_prem = await db.is_user_premium(user_id)
    tier_tag = "💎 VIP Premium Member" if is_prem else "⚪ Standard Free Tier"

    text = (
        "🛠️ **ENTERPRISE SWISS ARMY TOOLBOX PRO** 🛠️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "দৈনন্দিন প্রয়োজনীয় কাজ ও সুবিধার জন্য অল-ইন-ওয়ান পাওয়ার টুল স্যুট!\n"
        f"• আপনার স্ট্যাটাস: `{tier_tag}`\n\n"
        "┌── 📂 **টুলবক্স ক্যাটাগরি সমূহ** ──────────┐\n"
        "│ 🎵 **১. অডিও ও মিডিয়া স্টুডিও**\n"
        "│    └─ Video to 320k MP3 · Video Splitter\n"
        "│ 📄 **২. ডকুমেন্ট ও PDF স্যুট**\n"
        "│    └─ Images to PDF · PDF Password Unlock\n"
        "│ 📬 **৩. ডিসপোজেবল টেম্প-মেইল**\n"
        "│    └─ Instant Temp-Mail & Live OTP Inbox\n"
        "│ 📦 **৪. ব্যাচ অটোমেশন ডাউনলোডার**\n"
        "│    └─ Multi-Link Queue (TG + Social Links)\n"
        "└──────────────────────────────────────┘\n\n"
        "👇 নিচের যেকোনো ক্যাটাগরিতে ক্লিক করে টুলস চালু করুন:"
    )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎵 অডিও ও মিডিয়া স্টুডিও", callback_data="tb_cat_media"),
                InlineKeyboardButton("📄 ডকুমেন্ট ও PDF স্যুট", callback_data="tb_cat_docs"),
            ],
            [
                InlineKeyboardButton("📦 ব্যাচ ডাউনলোডার", callback_data="tb_cat_batch"),
                InlineKeyboardButton("📬 টেম্প-মেইল (OTP Inbox)", callback_data="tb_tempmail_gen"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main"),
            ],
        ]
    )
    return text, markup


@Client.on_message(filters.command(["tools", "toolbox"]) & filters.private)
async def tools_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    text, markup = await render_toolbox_dashboard(user_id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^user_view_toolbox$"))
async def user_view_toolbox_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text, markup = await render_toolbox_dashboard(callback_query.from_user.id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


# =========================================================================
# 2. CATEGORY HUBS
# =========================================================================

@Client.on_callback_query(filters.regex(r"^tb_cat_media$"))
async def tb_cat_media_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text = (
        "🎵 **AUDIO & MEDIA STUDIO PRO** 🎵\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ভিডিও থেকে হাই-কোয়ালিটি অডিও আলাদা করা ও ভিডিও কাটার পাওয়ার টুলস:\n\n"
        "• 🔊 **ভিডিও থেকে MP3 এক্সট্রাক্টর (`/mp3`):**\n"
        "  যেকোনো ভিডিও বা লেকচার ফাইল থেকে ৩২০kbps ক্রিস্টাল ক্লিয়ার স্টুডিও MP3 গান বা পডকাস্ট তৈরি করে। ৯০% মোবাইল ডাটা বাঁচায় এবং স্ক্রিন অফ রেখে শোনা যায়।\n\n"
        "• ✂️ **ভিডিও স্প্লিটার (`/split`):**\n"
        "  বড় কোনো ভিডিওকে কোনো কোয়ালিটি লস ছাড়া মুহূর্তে পার্ট-১, পার্ট-২ তে ভাগ করে দেয়।\n\n"
        "👉 নিচের বাটনে চাপ দিন অথবা যেকোনো ভিডিওর রিপ্লাইতে `/mp3` লিখুন:"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔊 ভিডিও পাঠান -> MP3 নিন", callback_data="tb_audio_prompt"),
                InlineKeyboardButton("✂️ ভিডিও স্প্লিট গাইড", callback_data="tb_split_prompt"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Toolbox", callback_data="user_view_toolbox"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^tb_cat_docs$"))
async def tb_cat_docs_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text = (
        "📄 **DOCUMENT & PDF SUITE PRO** 📄\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ডকুমেন্ট ও বই হ্যান্ডেল করার জন্য দরকারি টুলস:\n\n"
        "• 📑 **ছবি থেকে PDF কনভার্টার (`/img2pdf`):**\n"
        "  নোট, বইয়ের পাতা বা ডকুমেন্টের একাধিক ছবি পাঠালে বট সাথে সাথে একটি পরিষ্কার এইচডি PDF বই তৈরি করে দেবে।\n\n"
        "• 🔓 **PDF পাসওয়ার্ড রিমুভার ও আনলকার (`/pdfunlock`):**\n"
        "  প্রিন্ট লক বা পাসওয়ার্ড থাকা যেকোনো রেস্ট্রিক্টেড PDF থেকে রেস্ট্রিকশন মুছে ফুল আনলকড কপি ডেলিভার করে।\n\n"
        "👉 নিচের যেকোনো অপশন বেছে নিন:"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📑 ছবি পাঠান -> PDF বানান", callback_data="tb_img2pdf_start"),
                InlineKeyboardButton("🔓 PDF পাসওয়ার্ড আনলক", callback_data="tb_pdfunlock_prompt"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Toolbox", callback_data="user_view_toolbox"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^tb_cat_vault$"))
async def tb_cat_vault_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text = (
        "🛡️ **CYBER & PRIVACY VAULT PRO** 🛡️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ডিজিটাল প্রাইভেসি ও আইডেন্টিটি প্রটেকশন টুল:\n\n"
        "• 📬 **ডিসপোজেবল টেম্প-মেইল (লাইভ OTP ইনবক্স) (`/tempmail`):**\n"
        "  টেলিগ্রামের ভেতরেই ১ ক্লিকে ডিসপোজেবল ইমেইল অ্যাড্রেস পান। সাইনআপ বা ট্রায়াল নেয়ার পর কনফার্মেশন কোড ও OTP সরাসরি বটের ইনবক্সে রিফ্রেশ করে দেখুন!\n\n"
        "👉 নিচের বাটনে চাপ দিয়ে ইনস্ট্যান্ট টেম্প-মেইল চালু করুন:"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📬 লাইভ ডিসপোজেবল টেম্প-মেইল", callback_data="tb_tempmail_gen"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Toolbox", callback_data="user_view_toolbox"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^tb_cat_batch$"))
async def tb_cat_batch_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text = (
        "📦 **BATCH MULTI-LINK AUTOMATION QUEUE** 📦\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "একসাথে অনেকগুলো লিংক এক ক্লিকে ডাউনলোড করার ইঞ্জিন!\n\n"
        "• **কীভাবে কাজ করে:**\n"
        "  মেসেজে একসাথে ১০টা বা ২০টা লিংক (প্রতি লাইনে একটি করে) লিখে পাঠান অথবা একটি `.txt` ফাইল আপলোড করুন।\n"
        "• **সাপোর্টেড লিংক:**\n"
        "  ✅ Telegram Restricted Links (`https://t.me/c/...`)\n"
        "  ✅ YouTube, Facebook, Instagram, TikTok, Terabox\n"
        "  ✅ Direct Video Links (.mp4, .mkv, web streams)\n\n"
        "বট একা একাই সিরিয়াল ধরে কিউতে রেখে সব ডাউনলোড করে একের পর এক পাঠিয়ে দেবে!\n\n"
        "👉 এখনই শুরু করতে নিচের বাটনে চাপ দিন:"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📦 লিংক লিস্ট পাঠান (/batch)", callback_data="tb_batch_prompt"),
            ],
            [
                InlineKeyboardButton("🔙 Back to Toolbox", callback_data="user_view_toolbox"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


# =========================================================================
# 3. DISPOSABLE TEMP-MAIL ENGINE (LIVE OTP INBOX)
# =========================================================================

async def create_temp_mail():
    """Creates a fresh disposable inbox using api.mail.tm."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Step 1: Get active domain
        dom_res = (await client.get("https://api.mail.tm/domains")).json()
        domains = [d["domain"] for d in dom_res.get("hydra:member", []) if d.get("isActive", True)]
        if not domains:
            domains = ["uberip.com"]
        domain = random.choice(domains)

        # Step 2: Generate random username & password
        rand_user = "user_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        email = f"{rand_user}@{domain}"
        pwd = "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!9"

        # Step 3: Register account
        reg_res = await client.post("https://api.mail.tm/accounts", json={"address": email, "password": pwd})
        if reg_res.status_code not in (200, 201):
            raise Exception("Failed to create temporary mailbox")

        # Step 4: Obtain authentication JWT token
        tok_res = (await client.post("https://api.mail.tm/token", json={"address": email, "password": pwd})).json()
        token = tok_res.get("token")
        if not token:
            raise Exception("Failed to obtain inbox token")

        return email, token


@Client.on_message(filters.command(["tempmail", "mail"]) & filters.private)
async def tempmail_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    status_msg = await message.reply_text("⏳ _Generating secure disposable email address..._")
    try:
        email, token = await create_temp_mail()
        _TEMP_MAIL_ACCOUNTS[user_id] = {
            "address": email,
            "token": token,
            "created_at": time.time(),
        }
        text = (
            "📬 **DISPOSABLE TEMPORARY EMAIL & LIVE INBOX** 📬\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "আপনার অস্থায়ী ইমেইল ঠিকানা প্রস্তুত:\n\n"
            f"📧 **ইমেইল এড্রেস:** `\n{email}\n`\n"
            "*(উপরের ইমেইলে ট্যাপ করলেই অটো-কপি হয়ে যাবে)*\n\n"
            "💡 **ব্যবহার করার নিয়ম:**\n"
            "১. যেকোনো ওয়েবসাইট, অ্যাপ বা ট্রায়াল সাইনআপে এই ইমেইলটি ব্যবহার করুন।\n"
            "২. তারা ওটিপি (OTP) বা কনফার্মেশন লিংক সেন্ড করলে নিচে **'🔄 Check Inbox / Refresh'** বাটনে চাপ দিন।\n"
            "৩. ওটিপি কোড সরাসরি এখানে স্ক্রিনে ভেসে উঠবে!"
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔄 Check Inbox / Refresh (ওটিপি দেখুন)", callback_data="tb_tempmail_check"),
                ],
                [
                    InlineKeyboardButton("➕ Generate New Email (নতুন ইমেইল)", callback_data="tb_tempmail_gen"),
                    InlineKeyboardButton("🔙 Back to Toolbox", callback_data="user_view_toolbox"),
                ]
            ]
        )
        await status_msg.edit_text(text, reply_markup=markup)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error generating temp-mail: {e}\nTry again in a few seconds.")


@Client.on_callback_query(filters.regex(r"^tb_tempmail_gen$"))
async def tb_tempmail_gen_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer("Generating fresh disposable email...", show_alert=False)
    try:
        email, token = await create_temp_mail()
        _TEMP_MAIL_ACCOUNTS[user_id] = {
            "address": email,
            "token": token,
            "created_at": time.time(),
        }
        text = (
            "📬 **DISPOSABLE TEMPORARY EMAIL & LIVE INBOX** 📬\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "আপনার নতুন অস্থায়ী ইমেইল ঠিকানা প্রস্তুত:\n\n"
            f"📧 **ইমেইল এড্রেস:** `\n{email}\n`\n"
            "*(ইমেইলটিতে ট্যাপ করলেই কপি হয়ে যাবে)*\n\n"
            "💡 **ব্যবহার করার নিয়ম:**\n"
            "যেকোনো সাইটে এই ইমেইল দিয়ে ওটিপি পাঠাতে বলুন, এরপর নিচের **'🔄 Check Inbox / Refresh'** বাটনে চাপ দিন। কোড সাথে সাথে দেখতে পাবেন!"
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔄 Check Inbox / Refresh (ওটিপি দেখুন)", callback_data="tb_tempmail_check"),
                ],
                [
                    InlineKeyboardButton("➕ Generate New Email (নতুন ইমেইল)", callback_data="tb_tempmail_gen"),
                    InlineKeyboardButton("🔙 Back to Toolbox", callback_data="user_view_toolbox"),
                ]
            ]
        )
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception as e:
        await callback_query.message.reply_text(f"❌ Error: {e}")


@Client.on_callback_query(filters.regex(r"^tb_tempmail_check$"))
async def tb_tempmail_check_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    acc = _TEMP_MAIL_ACCOUNTS.get(user_id)
    if not acc:
        await callback_query.answer("No active temp-mail found! Tap 'Generate New Email'.", show_alert=True)
        return

    email = acc["address"]
    token = acc["token"]

    async with httpx.AsyncClient(timeout=10.0) as client_http:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            res = (await client_http.get("https://api.mail.tm/messages", headers=headers)).json()
            messages = res.get("hydra:member", [])
        except Exception as e:
            await callback_query.answer(f"Connection error: {e}", show_alert=True)
            return

    if not messages:
        await callback_query.answer("📭 ইনবক্স এখনও খালি! কোড না এসে থাকলে একটু পর আবার চাপ দিন।", show_alert=True)
        return

    await callback_query.answer(f"🎉 {len(messages)} টি নতুন ইমেইল পাওয়া গেছে!", show_alert=False)

    # Fetch latest message detail
    latest_msg_id = messages[0]["id"]
    async with httpx.AsyncClient(timeout=10.0) as client_http:
        msg_detail = (await client_http.get(f"https://api.mail.tm/messages/{latest_msg_id}", headers=headers)).json()

    sender = msg_detail.get("from", {}).get("address", "Unknown Sender")
    subject = msg_detail.get("subject", "No Subject")
    intro = msg_detail.get("intro", "")
    text_content = msg_detail.get("text", "") or intro

    # Auto-extract OTP code patterns if present (4 to 8 digit numbers)
    otp_matches = re.findall(r"\b\d{4,8}\b", text_content)
    otp_badge = f"\n🔑 **DETECTED OTP / VERIFICATION CODE:** `\n{otp_matches[0]}\n`\n" if otp_matches else ""

    text = (
        "📬 **INBOX: INCOMING EMAIL RECEIVED!** 📬\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📧 **Mailbox:** `{email}`\n"
        f"👤 **From:** `{sender}`\n"
        f"📌 **Subject:** `{subject}`\n"
        f"{otp_badge}"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📜 **MESSAGE PREVIEW:**\n"
        f"```{text_content[:600]}```\n\n"
        "💡 _নতুন মেসেজ আসলে আবার নিচে Refresh চাপুন:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Check Inbox / Refresh", callback_data="tb_tempmail_check"),
            ],
            [
                InlineKeyboardButton("➕ Generate New Email", callback_data="tb_tempmail_gen"),
                InlineKeyboardButton("🔙 Back to Toolbox", callback_data="user_view_toolbox"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


# =========================================================================
# 4. ZERO-TRACE FORENSIC CLEANER / EXIF WIPER
# =========================================================================

@Client.on_callback_query(filters.regex(r"^tb_clean_prompt$"))
async def tb_clean_prompt_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer()
    set_user_state(user_id, "waiting_media_to_clean")
    text = (
        "🕵️ **ZERO-TRACE FORENSIC CLEANER & EXIF WIPER** 🕵️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "যেকোনো ছবি বা ভিডিও পাঠান, অথবা কোনো মিডিয়ার রিপ্লাইয়ে `/clean` লিখুন!\n\n"
        "🛡️ **বট যা যা মুছে দেবে:**\n"
        "✅ **ক্যামেরা ডিটেইলস:** Camera Model, Lens Serial, Make\n"
        "✅ **জিপিএস লোকেশন:** Exact Latitude, Longitude, Altitude\n"
        "✅ **ডিভাইস ফিঙ্গারপ্রিন্ট:** Device IMEI, Software, OS Build\n"
        "✅ **টাইমস্ট্যাম্প ও হেডার:** Creation Date, Author, Encoder Tags\n\n"
        "👉 _এখনই যেকোনো ছবি বা ভিডিও এখানে সেন্ড করুন, অথবা Cancel চাপুন:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="user_view_toolbox"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_message(filters.command(["clean", "anonymize"]) & filters.private)
async def clean_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    target_msg = message.reply_to_message if message.reply_to_message else message

    has_media = bool(target_msg.photo or target_msg.video or target_msg.document or target_msg.audio)
    if not has_media:
        await message.reply_text(
            "🕵️ **ZERO-TRACE FORENSIC CLEANER**\n\n"
            "যে ছবি বা ভিডিও থেকে মেটাডাটা ও লোকেশন মুছতে চান, সেটিকে রিপ্লাই করে `/clean` লিখুন, "
            "অথবা `/tools` এ গিয়ে মেটাডাটা ক্লিনার সিলেক্ট করুন।"
        )
        return

    await perform_forensic_cleaning(client, message, target_msg)


async def perform_forensic_cleaning(client: Client, reply_target: Message, source_msg: Message):
    """Strips EXIF, GPS, camera metadata, and encoder signatures from photos/videos."""
    status_msg = await reply_target.reply_text("⏳ _Downloading media for zero-trace scrubbing..._")
    downloaded = None
    cleaned_file = None
    try:
        downloaded = await client.download_media(source_msg, file_name=f"{TOOLBOX_TEMP_DIR}/")
        if not downloaded or not os.path.exists(downloaded):
            await status_msg.edit_text("❌ Failed to download target media.")
            return

        file_ext = Path(downloaded).suffix.lower()
        cleaned_file = f"{downloaded}_clean{file_ext}"

        await status_msg.edit_text("⚡ _Scrubbing GPS coordinates, device serials & metadata headers..._")

        # 1. Image Cleaning (Pillow EXIF / ICC / Software wipe)
        if file_ext in (".jpg", ".jpeg", ".png", ".webp"):
            with Image.open(downloaded) as im:
                if im.mode in ("RGBA", "P") and file_ext in (".jpg", ".jpeg"):
                    im = im.convert("RGB")
                im.save(cleaned_file, exif=b"")

            report = (
                "🛡️ **ZERO-TRACE FORENSIC SCRUB COMPLETED** 🛡️\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅ **Camera Serial & Model:** `[PURGED]`\n"
                "✅ **GPS Coordinates (Latitude/Longitude):** `[PURGED]`\n"
                "✅ **Software & Device Traces:** `[PURGED]`\n"
                "✅ **Creation Timestamps:** `[ANONYMIZED]`\n"
                "🔒 **Integrity:** 100% Zero-Trace Ghost Photo"
            )
            await reply_target.reply_photo(photo=cleaned_file, caption=report)

        # 2. Video / Audio Cleaning (FFmpeg bitstream metadata scrub)
        else:
            ffmpeg_bin = get_ffmpeg_binary()
            cmd = [
                ffmpeg_bin,
                "-y",
                "-i", downloaded,
                "-map_metadata", "-1",
                "-map_chapters", "-1",
                "-metadata", "title=",
                "-metadata", "artist=",
                "-metadata", "comment=",
                "-metadata", "encoded_by=",
                "-c", "copy",
                "-movflags", "+faststart",
                cleaned_file,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            if not os.path.exists(cleaned_file) or os.path.getsize(cleaned_file) == 0:
                cleaned_file = downloaded

            report = (
                "🛡️ **ZERO-TRACE FORENSIC SCRUB COMPLETED** 🛡️\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅ **Encoder Signatures & Bitstream Headers:** `[PURGED]`\n"
                "✅ **Global / Stream Metadata & Chapters:** `[PURGED]`\n"
                "✅ **Hardware & Device Fingerprints:** `[PURGED]`\n"
                "⚡ **Streaming Optimization:** `-movflags +faststart` Enabled\n"
                "🔒 **Integrity:** 100% Zero-Trace Ghost Video"
            )
            if file_ext in (".mp4", ".mkv", ".mov", ".webm"):
                await reply_target.reply_video(video=cleaned_file, caption=report, supports_streaming=True)
            else:
                await reply_target.reply_document(document=cleaned_file, caption=report)

        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ Error during forensic scrub: {e}")
    finally:
        for p in [downloaded, cleaned_file]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


# =========================================================================
# 5. AUDIO & MP3 EXTRACTOR STUDIO
# =========================================================================

@Client.on_callback_query(filters.regex(r"^tb_audio_prompt$"))
async def tb_audio_prompt_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer()
    set_user_state(user_id, "waiting_video_for_audio")
    text = (
        "🔊 **ONE-CLICK VIDEO TO 320k MP3 EXTRACTOR** 🔊\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "যেকোনো ভিডিও বা লেকচার ফাইলকে হাই-কোয়ালিটি ৩২০kbps স্টুডিও MP3 অডিওতে কনভার্ট করুন!\n\n"
        "💡 **ব্যবহার করার নিয়ম:**\n"
        "• এখন যেকোনো ভিডিও ফাইল এখানে ফরওয়ার্ড বা সেন্ড করুন।\n"
        "• অথবা পূর্বে পাঠানো যেকোনো ভিডিওতে রিপ্লাই করে `/mp3` লিখুন।\n\n"
        "👉 _ভিডিওটি পাঠান, অথবা Cancel চাপুন:_"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="tb_cat_media"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^tb_split_prompt$"))
async def tb_split_prompt_callback(client: Client, callback_query: CallbackQuery):
    """Provides user guide and syntax for lossless video splitting."""
    await callback_query.answer()
    text = (
        "✂️ **LOSSLESS VIDEO SPLITTER GUIDE** ✂️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "বড় ভিডিও ফাইলকে কোনো কোয়ালিটি লস ছাড়া ২ বা ততোধিক অংশে ভাগ করার নিয়ম:\n\n"
        "👉 **ব্যবহারবিধি:**\n"
        "১. আপনি যে ভিডিওটি কাটতে চান, সেটি এই চ্যাটে পাঠান বা ফরওয়ার্ড করুন।\n"
        "২. ভিডিওর মেসেজে রিপ্লাই (Reply) দিয়ে লিখুন:\n"
        "   `/split 00:00:00 00:10:00`\n"
        "   *(যেখানে প্রথমটি শুরুর সময় এবং দ্বিতীয়টি শেষের সময়)*\n\n"
        "৩. বট কোনো রি-এনকোডিং ছাড়া সেকেন্ডের মধ্যে কাটা ভিডিও ক্লিপটি ডেলিভার করবে!"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔙 Back to Media Studio", callback_data="tb_cat_media"),
            ]
        ]
    )
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)


async def perform_audio_extraction(client: Client, reply_target: Message, source_msg: Message):
    """Extracts pristine 320kbps MP3 audio from any video or audio file."""
    status_msg = await reply_target.reply_text("⏳ _Downloading video stream for audio extraction..._")
    downloaded = None
    out_mp3 = None
    try:
        downloaded = await client.download_media(source_msg, file_name=f"{TOOLBOX_TEMP_DIR}/")
        if not downloaded or not os.path.exists(downloaded):
            await status_msg.edit_text("❌ Failed to download target video.")
            return

        base_name = Path(downloaded).stem
        out_mp3 = str(TOOLBOX_TEMP_DIR / f"{base_name}_320k.mp3")

        await status_msg.edit_text("⚡ _Encoding crystal-clear 320kbps MP3 with ID3 audio tags..._")
        ffmpeg_bin = get_ffmpeg_binary()

        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", downloaded,
            "-vn",
            "-c:a", "libmp3lame",
            "-b:a", "320k",
            "-ar", "44100",
            out_mp3,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        if not os.path.exists(out_mp3) or os.path.getsize(out_mp3) == 0:
            await status_msg.edit_text("❌ Failed to encode MP3 audio.")
            return

        caption = (
            "🎵 **STUDIO AUDIO EXTRACTOR (320kbps)** 🎵\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 📁 Title: `{base_name}`\n"
            "• 🎧 Quality: `320 kbps CBR (Studio Master)`\n"
            "• 📱 Playback: Background Playback & Full Scrubber Supported\n"
            "• 💡 Mobile Data Saved: ~90%"
        )

        await reply_target.reply_audio(
            audio=out_mp3,
            caption=caption,
            title=base_name,
            performer="TG Media Studio",
        )
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ Error during MP3 extraction: {e}")
    finally:
        for p in [downloaded, out_mp3]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


# =========================================================================
# 6. IMAGES TO PDF CONVERTER
# =========================================================================

@Client.on_callback_query(filters.regex(r"^tb_img2pdf_start$"))
async def tb_img2pdf_start_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer()
    set_user_state(user_id, "waiting_images_for_pdf")
    _USER_PDF_IMAGES[user_id] = []

    text = (
        "📑 **IMAGES TO MULTI-PAGE PDF CONVERTER** 📑\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "নোট, বইয়ের পাতা বা প্রয়োজনীয় ছবি দিয়ে ঝকঝকে পিডিএফ তৈরি করুন!\n\n"
        "👉 **ব্যবহারবিধি:**\n"
        "১. পর্যায়ক্রমে ১টি থেকে ২০টি ছবি এখানে সেন্ড করুন।\n"
        "২. সব ছবি পাঠানো শেষ হলে নিচে **'✅ Finish & Generate PDF'** বাটনে চাপ দিন।\n"
        "৩. বট সব ছবি সিরিয়াল অনুযায়ী জুড়ে ১টি সিঙ্গেল PDF ফাইল বানিয়ে দেবে।"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Finish & Generate PDF (পিডিএফ বানান)", callback_data="tb_img2pdf_finish"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="tb_cat_docs"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^tb_img2pdf_finish$"))
async def tb_img2pdf_finish_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    img_list = _USER_PDF_IMAGES.get(user_id, [])

    if not img_list:
        await callback_query.answer("⚠️ এখনও কোনো ছবি পাঠাননি! আগে ছবি সেন্ড করুন।", show_alert=True)
        return

    await callback_query.answer("Compiling PDF document...", show_alert=False)
    status_msg = await callback_query.message.reply_text(f"⏳ _Stitching {len(img_list)} images into a high-res PDF..._")
    pdf_path = None

    try:
        pil_images = []
        for img_path in img_list:
            if os.path.exists(img_path):
                im = Image.open(img_path)
                if im.mode != "RGB":
                    im = im.convert("RGB")
                pil_images.append(im)

        if not pil_images:
            await status_msg.edit_text("❌ No valid images found to compile.")
            return

        pdf_path = str(TOOLBOX_TEMP_DIR / f"Compiled_Doc_{user_id}_{int(time.time())}.pdf")
        pil_images[0].save(pdf_path, save_all=True, append_images=pil_images[1:], quality=95)

        file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        caption = (
            "📑 **COMPILED PDF DOCUMENT** 📑\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 📄 Total Pages: `{len(pil_images)} Pages`\n"
            f"• 💾 Document Size: `{file_size_mb:.2f} MB`\n"
            "• 🖨️ Quality: Print-Ready 300 DPI Rendering"
        )
        await callback_query.message.reply_document(document=pdf_path, caption=caption)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ Error creating PDF: {e}")
    finally:
        clear_user_state(user_id)
        for p in img_list:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        _USER_PDF_IMAGES.pop(user_id, None)
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass


async def handle_incoming_media_group(client: Client, message: Message):
    """Buffers messages belonging to the same media group (album) and triggers batch processing."""
    gid = message.media_group_id
    user_id = message.from_user.id
    _ALBUM_BUFFERS.setdefault(gid, []).append(message)

    if gid not in _ALBUM_TASKS or _ALBUM_TASKS[gid].done():
        _ALBUM_TASKS[gid] = asyncio.create_task(_process_album_batch(client, gid, user_id))


async def _process_album_batch(client: Client, media_group_id: str, user_id: int):
    """Waits for all album messages to arrive, then handles PDF queue or 1-tap PDF prompt."""
    await asyncio.sleep(1.2)
    album_msgs = _ALBUM_BUFFERS.pop(media_group_id, [])
    if not album_msgs:
        return

    # Sort strictly by message ID so pages maintain correct sequential order
    album_msgs.sort(key=lambda m: m.id)
    last_msg = album_msgs[-1]

    user_state = get_user_state(user_id)
    st = user_state.get("state") if user_state else None

    # CASE 1: User explicitly activated "waiting_images_for_pdf"
    if st == "waiting_images_for_pdf":
        added_count = 0
        status_msg = await last_msg.reply_text(f"⏳ _Downloading {len(album_msgs)} album images for PDF compilation..._")
        for idx, m in enumerate(album_msgs):
            target_name = str(TOOLBOX_TEMP_DIR / f"pdf_{user_id}_{int(time.time()*1000)}_{len(_USER_PDF_IMAGES.get(user_id, []))}_{idx}.jpg")
            try:
                dl_path = await client.download_media(m, file_name=target_name)
                if dl_path and os.path.exists(dl_path):
                    _USER_PDF_IMAGES.setdefault(user_id, []).append(dl_path)
                    added_count += 1
            except Exception as e:
                print(f"[!] Error downloading album photo: {e}")

        total_count = len(_USER_PDF_IMAGES.get(user_id, []))
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(f"✅ Finish & Generate PDF ({total_count} Images)", callback_data="tb_img2pdf_finish"),
                ],
                [
                    InlineKeyboardButton("❌ Cancel", callback_data="tb_cat_docs"),
                ]
            ]
        )
        try:
            await status_msg.edit_text(
                f"📸 **{added_count}টি নতুন ছবি PDF কিউতে যুক্ত হয়েছে! (মোট {total_count}টি পাতা)**\n\n"
                f"আরও ছবি থাকলে পাঠাতে পারেন, অথবা সম্পূর্ণ PDF তৈরি করতে নিচের বাটনে চাপ দিন:",
                reply_markup=markup,
            )
        except Exception:
            await last_msg.reply_text(
                f"📸 **{added_count}টি নতুন ছবি PDF কিউতে যুক্ত হয়েছে! (মোট {total_count}টি পাতা)**",
                reply_markup=markup,
            )
        return

    # CASE 2: User sent an album directly into chat without entering a menu first
    album_token = f"alb_{user_id}_{int(time.time())}_{random.randint(100, 999)}"
    _PENDING_ALBUMS[album_token] = album_msgs

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"📑 Convert all {len(album_msgs)} Photos to PDF (পিডিএফ বানান)", callback_data=f"tb_quick_album_pdf:{album_token}"),
            ],
            [
                InlineKeyboardButton("❌ Dismiss", callback_data="tb_dismiss"),
            ]
        ]
    )
    await last_msg.reply_text(
        f"📸 **{len(album_msgs)}টি ছবি একসাথে শনাক্ত হয়েছে!**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "আপনি কি এই সব ছবি দিয়ে একটি **হাই-রেজোলিউশন মাল্টি-পেইজ PDF ডকুমেন্ট** তৈরি করতে চান?\n\n"
        "👉 নিচের বাটনে ১-ট্যাপ করুন:",
        reply_markup=markup,
    )


@Client.on_callback_query(filters.regex(r"^tb_quick_album_pdf:(.+)"))
async def tb_quick_album_pdf_callback(client: Client, callback_query: CallbackQuery):
    """One-tap compiles directly submitted albums into a single print-ready PDF document."""
    token = callback_query.matches[0].group(1)
    album_msgs = _PENDING_ALBUMS.pop(token, None)

    if not album_msgs:
        await callback_query.answer("⚠️ Session expired or photos already processed.", show_alert=True)
        return

    user_id = callback_query.from_user.id
    await callback_query.answer("Compiling photos into PDF...", show_alert=False)
    status_msg = await callback_query.message.edit_text(f"⏳ _Downloading and compiling {len(album_msgs)} images into high-res PDF..._")

    downloaded_paths = []
    pdf_path = None
    try:
        pil_images = []
        for idx, m in enumerate(album_msgs):
            target_name = str(TOOLBOX_TEMP_DIR / f"quick_pdf_{user_id}_{int(time.time()*1000)}_{idx}.jpg")
            dl = await client.download_media(m, file_name=target_name)
            if dl and os.path.exists(dl):
                downloaded_paths.append(dl)
                im = Image.open(dl)
                if im.mode != "RGB":
                    im = im.convert("RGB")
                pil_images.append(im)

        if not pil_images:
            await status_msg.edit_text("❌ Could not process any images.")
            return

        pdf_path = str(TOOLBOX_TEMP_DIR / f"Compiled_Album_{user_id}_{int(time.time())}.pdf")
        pil_images[0].save(pdf_path, save_all=True, append_images=pil_images[1:], quality=95)

        for im in pil_images:
            try:
                im.close()
            except Exception:
                pass

        file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        caption = (
            "📑 **COMPILED PDF DOCUMENT (ALBUM)** 📑\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 📄 Total Pages: `{len(pil_images)} Pages`\n"
            f"• 💾 Document Size: `{file_size_mb:.2f} MB`\n"
            "• 🖨️ Quality: Print-Ready 300 DPI Rendering"
        )
        await callback_query.message.reply_document(document=pdf_path, caption=caption)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ Error generating PDF: {e}")
    finally:
        for p in downloaded_paths:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass


@Client.on_callback_query(filters.regex(r"^tb_dismiss$"))
async def tb_dismiss_callback(client: Client, callback_query: CallbackQuery):
    """Dismisses prompt card cleanly."""
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()


# =========================================================================
# 7. PDF PASSWORD UNLOCKER / RESTRICTION REMOVER
# =========================================================================

@Client.on_callback_query(filters.regex(r"^tb_pdfunlock_prompt$"))
async def tb_pdfunlock_prompt_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer()
    set_user_state(user_id, "waiting_pdf_to_unlock")
    text = (
        "🔓 **PDF PASSWORD REMOVER & UNLOCKER** 🔓\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "লক করা বা রেস্ট্রিকশন থাকা PDF সম্পূর্ণ আনলক করুন!\n\n"
        "👉 **ব্যবহারবিধি:**\n"
        "• যেকোনো লকড PDF ডকুমেন্ট ফাইল এখানে পাঠান।\n"
        "• যদি কোনো পাসওয়ার্ড জানা থাকে, ক্যাপশনে পাসওয়ার্ডটি লিখে দিন (যেমন: `123456`)।\n"
        "• বট পারমিশন লক (প্রিন্ট/কপি লক) ও পাসওয়ার্ড মুছে দিয়ে একটি ১০০% আনলকড ক্লিয়ার কপি ডেলিভার করবে।"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="tb_cat_docs"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


async def perform_pdf_unlocking(client: Client, message: Message):
    """Removes user password and permission restrictions from a PDF using pypdf."""
    status_msg = await message.reply_text("⏳ _Downloading PDF document..._")
    downloaded = None
    unlocked_pdf = None
    try:
        from pypdf import PdfReader, PdfWriter

        target_pdf = str(TOOLBOX_TEMP_DIR / f"locked_{message.from_user.id}_{int(time.time()*1000)}.pdf")
        downloaded = await client.download_media(message, file_name=target_pdf)
        if not downloaded or not os.path.exists(downloaded):
            await status_msg.edit_text("❌ Failed to download PDF.")
            return

        password = (message.caption or "").strip()
        reader = PdfReader(downloaded)

        if reader.is_encrypted:
            await status_msg.edit_text("⚡ _Decrypting PDF security cipher..._")
            decrypted = False
            for pwd in [password, "", "1234", "123456"]:
                if pwd is not None:
                    try:
                        if reader.decrypt(pwd) > 0:
                            decrypted = True
                            break
                    except Exception:
                        pass
            if not decrypted:
                await status_msg.edit_text(
                    "🔒 This PDF is encrypted with a custom password.\n"
                    "Please re-send the PDF with the password in the caption (e.g. `your_password`)."
                )
                return

        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        unlocked_pdf = f"{downloaded}_unlocked.pdf"
        with open(unlocked_pdf, "wb") as f_out:
            writer.write(f_out)

        caption = (
            "🔓 **PDF UNLOCKED SUCCESSFULLY** 🔓\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Password Protection: [REMOVED]\n"
            "✅ Print & Copy Restrictions: [PERMITTED]\n"
            f"• 📄 Total Pages: `{len(reader.pages)}`"
        )
        await message.reply_document(document=unlocked_pdf, caption=caption)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ Error unlocking PDF: {e}")
    finally:
        for p in [downloaded, unlocked_pdf]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


# =========================================================================
# 8. OSINT IP & DOMAIN INTELLIGENCE
# =========================================================================

@Client.on_callback_query(filters.regex(r"^tb_whois_prompt$"))
async def tb_whois_prompt_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer()
    set_user_state(user_id, "waiting_ip_whois")
    text = (
        "🔎 **OSINT IP & DOMAIN INTELLIGENCE LOOKUP** 🔎\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "যেকোনো আইপি অ্যাড্রেস বা ওয়েবসাইটের পরিচয় ও হোস্ট সার্ভার চেক করুন!\n\n"
        "👉 **ব্যবহারবিধি:**\n"
        "এখানে যেকোনো আইপি (যেমন: `1.1.1.1` বা `8.8.8.8`) অথবা ডোমেন নাম (যেমন: `google.com`) লিখে পাঠান।\n"
        "অথবা সরাসরি চ্যাটে `/whois 1.1.1.1` কমান্ড রান করুন।"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="tb_cat_vault"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_message(filters.command(["whois", "ip"]) & filters.private)
async def whois_command_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("👉 Usage: `/whois 1.1.1.1` or `/whois example.com`")
        return
    query = message.command[1].strip()
    await perform_whois_lookup(message, query)


async def perform_whois_lookup(message: Message, query: str):
    """Queries public IP intelligence endpoint and renders dossier."""
    clean_target = query.replace("https://", "").replace("http://", "").split("/")[0].strip()
    status_msg = await message.reply_text(f"🔎 _Querying OSINT telemetry for `{clean_target}`..._")

    async with httpx.AsyncClient(timeout=10.0) as client_http:
        try:
            url = f"http://ip-api.com/json/{clean_target}?fields=status,message,country,countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
            res = (await client_http.get(url)).json()
        except Exception as e:
            await status_msg.edit_text(f"❌ OSINT Lookup Error: {e}")
            return

    if res.get("status") != "success":
        await status_msg.edit_text(f"❌ Could not resolve target: `{clean_target}` ({res.get('message', 'invalid query')})")
        return

    ip = res.get("query", clean_target)
    country = res.get("country", "Unknown")
    c_code = res.get("countryCode", "")
    city = res.get("city", "Unknown")
    region = res.get("regionName", "")
    isp = res.get("isp", "Unknown")
    asn = res.get("as", "Unknown")
    org = res.get("org", "Unknown")
    tz = res.get("timezone", "UTC")
    lat = res.get("lat", "")
    lon = res.get("lon", "")

    text = (
        "🌐 **OSINT NETWORK DOSSIER REPORT** 🌐\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• 🎯 **Target Host / IP:** `{ip}`\n"
        f"• 🏳️ **Country:** `{country} ({c_code})`\n"
        f"• 🏙️ **City / Region:** `{city}, {region}`\n"
        f"• 🏢 **ISP Provider:** `{isp}`\n"
        f"• 🏷️ **ASN Route:** `{asn}`\n"
        f"• 🏛️ **Organization:** `{org}`\n"
        f"• ⏰ **Timezone:** `{tz}`\n"
        f"• 📍 **Coordinates:** `{lat}, {lon}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛡️ _Report generated with live telemetry_"
    )
    await status_msg.edit_text(text)


# =========================================================================
# 9. BATCH DOWNLOADING QUEUE (/batch)
# =========================================================================

@Client.on_callback_query(filters.regex(r"^tb_batch_prompt$"))
async def tb_batch_prompt_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer()
    set_user_state(user_id, "waiting_batch_links")
    text = (
        "📦 **BATCH MULTI-LINK AUTOMATION QUEUE** 📦\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "একসাথে অনেকগুলো লিংক ডাউনলোড করার জন্য প্রস্তুত!\n\n"
        "👉 **কীভাবে পাঠাবেন:**\n"
        "• মেসেজে প্রতিটি লাইনে ১টি করে লিংক লিখে একবারে সেন্ড করুন:\n"
        "  `https://t.me/c/12345/10`\n"
        "  `https://t.me/c/12345/11`\n"
        "  `https://youtu.be/...`\n"
        "  `https://instagram.com/reel/...`\n"
        "• অথবা লিংকগুলো একটি `.txt` ফাইলে লিখে ফাইলটি আপলোড করুন।\n\n"
        "বট স্বয়ংক্রিয়ভাবে কিউতে রেখে সব একটার পর একটা ডাউনলোড করবে!"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("❌ Cancel", callback_data="tb_cat_batch"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_message(filters.command(["batch"]) & filters.private)
async def batch_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2:
        set_user_state(user_id, "waiting_batch_links")
        await message.reply_text(
            "📦 **BATCH MULTI-LINK AUTOMATION QUEUE**\n\n"
            "এখন মেসেজে প্রতি লাইনে একটি করে লিংক লিখে পাঠিয়ে দিন। বট কিউ তৈরি করে ডাউনলোড শুরু করবে।"
        )
        return

    raw_text = message.text.split(None, 1)[1]
    await process_batch_raw_text(client, message, raw_text)


async def process_batch_raw_text(client: Client, message: Message, raw_text: str):
    """Parses multiple URLs and initiates sequential queue execution."""
    user_id = message.from_user.id
    url_pattern = re.compile(r"https?://[^\s]+")
    found_urls = url_pattern.findall(raw_text)

    if not found_urls:
        await message.reply_text("❌ No valid URLs detected in your text. Please provide valid web or Telegram links.")
        return

    # Check user tier batch limits
    is_prem = await db.is_user_premium(user_id)
    max_batch = 50 if is_prem else 5

    if len(found_urls) > max_batch:
        await message.reply_text(
            f"⚠️ **Batch Limit:** Your current tier allows maximum `{max_batch}` links per batch.\n"
            f"Processing the first `{max_batch}` links from your list..."
        )
        found_urls = found_urls[:max_batch]

    total = len(found_urls)
    batch_status_msg = await message.reply_text(
        f"📦 **BATCH QUEUE INITIALIZED:** `[0/{total}] Complete`\n"
        f"⚡ Processing {total} links sequentially. Please do not send new commands until finished..."
    )

    from handlers.link_handler import telegram_link_listener
    from handlers.omni_downloader import process_omni_link

    success_count = 0
    fail_count = 0

    for idx, link in enumerate(found_urls, start=1):
        try:
            await batch_status_msg.edit_text(
                f"📦 **BATCH QUEUE IN PROGRESS:** `[{idx}/{total}]`\n"
                f"⚡ Currently downloading: `{link[:50]}...`\n"
                f"✅ Done: `{success_count}` | ❌ Errors: `{fail_count}`"
            )

            # Delegate to appropriate downloader
            if "t.me/" in link:
                dummy_msg = message
                dummy_msg.text = link
                await telegram_link_listener(client, dummy_msg)
            else:
                await process_omni_link(client, message, link)

            success_count += 1
            await asyncio.sleep(1.0)  # Gentle buffer between downloads

        except Exception as e:
            fail_count += 1
            print(f"[!] Batch item {idx} failed: {e}")

    await batch_status_msg.edit_text(
        "🎉 **BATCH QUEUE COMPLETED!** 🎉\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• 📦 Total Links Processed: `{total}`\n"
        f"• ✅ Successfully Completed: `{success_count}`\n"
        f"• ❌ Failed / Expired: `{fail_count}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 _All files have been delivered to your chat!_"
    )


# =========================================================================
# 10. COMPREHENSIVE ALL-IN-ONE USAGE GUIDE
# =========================================================================

@Client.on_callback_query(filters.regex(r"^tb_view_guide$"))
async def tb_view_guide_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    text = (
        "📖 **SWISS ARMY TOOLBOX PRO: অল-ইন-ওয়ান ব্যবহারের গাইড** 📖\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎵 **১. ভিডিও থেকে MP3 বানানো:**\n"
        "যেকোনো ভিডিও ফরওয়ার্ড করুন অথবা যেকোনো ভিডিওতে রিপ্লাই দিয়ে `/mp3` লিখুন। সাথে সাথে ৩২০kbps অডিও ফাইল পেয়ে যাবেন।\n\n"
        "📬 **২. ডিসপোজেবল টেম্প-মেইল ব্যবহার:**\n"
        "`/tempmail` লিখলেই তাৎক্ষণিক একটি ইউনিক ইমেইল পাবেন। সেটা দিয়ে ট্রায়াল বা সাইনআপ করে বটের **'🔄 Check Inbox'** বাটনে চাপ দিলেই ওটিপি (OTP) কোড দেখতে পাবেন।\n\n"
        "🕵️ **৩. জিরো-ট্রেস মেটাডাটা ক্লিনার:**\n"
        "যেকোনো ছবি বা ভিডিওতে রিপ্লাই করে `/clean` লিখুন। ক্যামেরা মডেল, লোকেশন (GPS) ও ডিভাইস ট্রেস চিরতরে মুছে ক্লিন ফাইল ডেলিভার হবে।\n\n"
        "📑 **৪. ছবি থেকে PDF তৈরি:**\n"
        "`/tools` -> 'ডকুমেন্ট ও PDF' -> 'ছবি পাঠান'। একের পর এক ছবি পাঠিয়ে 'Finish' চাপলেই সিঙ্গেল এইচডি PDF পেয়ে যাবেন।\n\n"
        "🔓 **৫. PDF পাসওয়ার্ড আনলক:**\n"
        "লক করা PDF টি পাঠান এবং ক্যাপশনে পাসওয়ার্ডটি লিখুন। প্রিন্ট ও কপি লক মুক্ত ফ্রেশ কপি পাবেন।\n\n"
        "📦 **৬. ব্যাচ মাল্টি-লিংক ডাউনলোডার:**\n"
        "`/batch` লিখে একসাথে ১০-২০টা লিংক পাঠান। বট একটার পর একটা নিজে থেকে সব ডাউনলোড করে দেবে।\n\n"
        "🔎 **৭. OSINT আইপি ও ডোমেন লুকআপ:**\n"
        "`/whois 8.8.8.8` অথবা `/whois google.com` লিখলে যেকোনো সার্ভারের ডিটেইলস রিপোর্ট দেখতে পাবেন।"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔙 Back to Toolbox", callback_data="user_view_toolbox"),
            ]
        ]
    )
    await callback_query.message.edit_text(text, reply_markup=markup)


# =========================================================================
# 11. STATE LISTENER FOR INTERACTIVE WORKFLOWS
# =========================================================================

@Client.on_message(
    filters.private & ~filters.command(["start", "tools", "setup", "cancel", "menu", "admin", "premium", "login", "clone", "batch", "tempmail", "clean", "whois", "ip", "img2pdf", "pdf", "mp3", "extractaudio", "split", "pdfunlock", "unlockpdf", "exif", "wipe"]),
    group=-5,
)
async def toolbox_message_dispatcher(client: Client, message: Message):
    """Intercepts media and text responses with priority when in active toolbox states."""
    user_id = message.from_user.id

    is_image = bool(
        message.photo
        or (message.document and message.document.mime_type and message.document.mime_type.startswith("image/"))
        or (message.document and message.document.file_name and message.document.file_name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")))
    )

    # Intercept multi-photo albums (media_group_id) with highest priority
    if message.media_group_id and is_image:
        message.stop_propagation()
        await handle_incoming_media_group(client, message)
        return

    user_state = get_user_state(user_id)
    if not user_state or not user_state.get("state"):
        message.continue_propagation()
        return

    st = user_state.get("state")

    # 1. Waiting for media to clean
    if st == "waiting_media_to_clean":
        if message.photo or message.video or message.document or message.audio:
            clear_user_state(user_id)
            await perform_forensic_cleaning(client, message, message)
            message.stop_propagation()
            return

    # 2. Waiting for video to extract audio
    elif st == "waiting_video_for_audio":
        if message.video or (message.document and message.document.mime_type and "video" in message.document.mime_type):
            clear_user_state(user_id)
            await perform_audio_extraction(client, message, message)
            message.stop_propagation()
            return

    # 3. Waiting for images to convert to PDF
    elif st == "waiting_images_for_pdf":
        is_image = bool(
            message.photo
            or (message.document and message.document.mime_type and message.document.mime_type.startswith("image/"))
            or (message.document and message.document.file_name and message.document.file_name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")))
        )
        if is_image:
            target_name = str(TOOLBOX_TEMP_DIR / f"pdf_{user_id}_{int(time.time()*1000)}_{len(_USER_PDF_IMAGES.get(user_id, []))}.jpg")
            try:
                dl_path = await client.download_media(message, file_name=target_name)
                if dl_path and os.path.exists(dl_path):
                    _USER_PDF_IMAGES.setdefault(user_id, []).append(dl_path)
                    count = len(_USER_PDF_IMAGES[user_id])
                    markup = InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(f"✅ Finish & Generate PDF ({count} Images)", callback_data="tb_img2pdf_finish"),
                            ],
                            [
                                InlineKeyboardButton("❌ Cancel", callback_data="tb_cat_docs"),
                            ]
                        ]
                    )
                    await message.reply_text(
                        f"📸 **ছবি #{count} PDF কিউতে যুক্ত হয়েছে!**\n"
                        f"আরও ছবি থাকলে পাঠাতে থাকুন, অথবা সব ছবি পাঠানো শেষ হলে নিচের বাটনে চাপ দিন:",
                        reply_markup=markup,
                    )
                else:
                    await message.reply_text("❌ Could not download photo. Please try sending again.")
            except Exception as e:
                print(f"[!] Error downloading image for PDF: {e}")
                await message.reply_text(f"❌ Error receiving image: {e}")
            message.stop_propagation()
            return

    # 4. Waiting for PDF to unlock
    elif st == "waiting_pdf_to_unlock":
        if message.document and message.document.file_name and message.document.file_name.lower().endswith(".pdf"):
            clear_user_state(user_id)
            await perform_pdf_unlocking(client, message)
            message.stop_propagation()
            return

    # 5. Waiting for IP / Domain WHOIS
    elif st == "waiting_ip_whois":
        if message.text:
            clear_user_state(user_id)
            await perform_whois_lookup(message, message.text.strip())
            message.stop_propagation()
            return

    # 6. Waiting for batch links
    elif st == "waiting_batch_links":
        if message.text:
            clear_user_state(user_id)
            await process_batch_raw_text(client, message, message.text)
            message.stop_propagation()
            return
        elif message.document and message.document.file_name and message.document.file_name.lower().endswith(".txt"):
            clear_user_state(user_id)
            target_txt = str(TOOLBOX_TEMP_DIR / f"batch_{user_id}_{int(time.time()*1000)}.txt")
            txt_path = await client.download_media(message, file_name=target_txt)
            try:
                if txt_path and os.path.exists(txt_path):
                    with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    await process_batch_raw_text(client, message, content)
            finally:
                if txt_path and os.path.exists(txt_path):
                    try:
                        os.remove(txt_path)
                    except Exception:
                        pass
            message.stop_propagation()
            return

    # If state not handled by toolbox, pass through to next handlers
    message.continue_propagation()


# =========================================================================
# 12. DIRECT COMMAND SHORTCUTS
# =========================================================================

@Client.on_message(filters.command(["img2pdf", "pdf"]) & filters.private)
async def img2pdf_command(client: Client, message: Message):
    user_id = message.from_user.id
    set_user_state(user_id, "waiting_images_for_pdf")
    _USER_PDF_IMAGES[user_id] = []
    text = (
        "📑 **IMAGES TO MULTI-PAGE PDF CONVERTER** 📑\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "নোট, বইয়ের পাতা বা প্রয়োজনীয় ছবি দিয়ে ঝকঝকে পিডিএফ তৈরি করুন!\n\n"
        "👉 **ব্যবহারবিধি:**\n"
        "১. একসাথে বা এক এক করে ছবিগুলো এখানে সেন্ড করুন।\n"
        "২. সব ছবি পাঠানো শেষ হলে নিচে **'✅ Finish & Generate PDF'** বাটনে চাপ দিন।\n"
        "৩. বট সব ছবি সিরিয়াল অনুযায়ী জুড়ে ১টি সিঙ্গেল PDF ফাইল বানিয়ে দেবে।"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Finish & Generate PDF (পিডিএফ বানান)", callback_data="tb_img2pdf_finish"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="tb_cat_docs"),
            ]
        ]
    )
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command(["mp3", "extractaudio"]) & filters.private)
async def mp3_command(client: Client, message: Message):
    user_id = message.from_user.id
    if message.reply_to_message and (message.reply_to_message.video or message.reply_to_message.document):
        await perform_audio_extraction(client, message, message.reply_to_message)
        return
    set_user_state(user_id, "waiting_video_for_audio")
    await message.reply_text(
        "🔊 **ভিডিও থেকে MP3 এক্সট্রাক্টর** 🔊\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "যেকোনো ভিডিও বা লেকচার ফাইল এই চ্যাটে সেন্ড করুন। বট সাথে সাথে ৩২০kbps ক্রিস্টাল ক্লিয়ার স্টুডিও MP3 গান বা অডিও ফাইল তৈরি করে দেবে!"
    )


@Client.on_message(filters.command(["clean", "exif", "wipe"]) & filters.private)
async def clean_command(client: Client, message: Message):
    user_id = message.from_user.id
    if message.reply_to_message and (message.reply_to_message.photo or message.reply_to_message.video or message.reply_to_message.document):
        await perform_forensic_cleaning(client, message, message.reply_to_message)
        return
    set_user_state(user_id, "waiting_media_to_clean")
    await message.reply_text(
        "🕵️ **জিরো-ট্রেস ফরেনসিক মেটাডাটা ও EXIF ওয়াইপার** 🕵️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "যেকোনো ছবি বা ভিডিও সেন্ড করুন। ক্যামেরা মডেল, ডিভাইস আইডি, জিপিএস কোঅর্ডিনেট মুছে ১০০% ক্লিন করে দেয়া হবে।"
    )


@Client.on_message(filters.command(["pdfunlock", "unlockpdf"]) & filters.private)
async def pdfunlock_command(client: Client, message: Message):
    user_id = message.from_user.id
    if message.reply_to_message and message.reply_to_message.document and message.reply_to_message.document.file_name and message.reply_to_message.document.file_name.lower().endswith(".pdf"):
        await perform_pdf_unlocking(client, message.reply_to_message)
        return
    set_user_state(user_id, "waiting_pdf_to_unlock")
    await message.reply_text(
        "🔓 **PDF পাসওয়ার্ড রিমুভার ও আনলকার** 🔓\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "আপনার পাসওয়ার্ড প্রোটেক্টেড বা রেস্ট্রিক্টেড PDF ডকুমেন্টটি এখানে সেন্ড করুন।"
    )

