# language: Python, file: handlers/deep_tester.py, target: Python 3.10+, Pyrogram
"""
Deep Inspection & 100% White-Label Test Suite:
Provides commands for live inspection, single-post deep sanitization,
batch cloning (e.g., last 100 posts), and custom clean words management.
Default channels:
  Source: -1001883004189
  Destination: -1003501797635
"""

import os
import re
from typing import Optional
from pyrogram import Client, filters
from pyrogram.types import Message

from database import db
from core.client_manager import get_user_client
from core.download_engine import download_restricted_media, active_jobs
from core.upload_engine import upload_unlocked_media
from core.deep_sanitizer import deep_inspect_and_sanitize
from core.caption_cleaner import strip_competitor_ads

DEFAULT_SOURCE_CHANNEL = -1001883004189
DEFAULT_DEST_CHANNEL = -1003501797635


@Client.on_message(filters.command(["antivirus", "toggle_antivirus"]) & filters.private)
async def cmd_toggle_antivirus(client: Client, message: Message):
    """Toggles the Anti-Virus Shield & Dropper Purger ON/OFF."""
    user_id = message.from_user.id
    new_state = await db.toggle_antivirus_scan(user_id)
    if new_state:
        await message.reply_text(
            "🛡️ **Anti-Virus Shield: [ ✅ ON ]**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• সব ফাইলে রিয়েল-টাইম অ্যান্টিভাইরাস স্ক্যান চালু হয়েছে।\n"
            "• জিপ/রার আর্কাইভের ভেতরে থাকা ক্ষতিকর `.exe`, `.bat`, `.vbs`, `.lnk` ড্রপার স্বয়ংক্রিয়ভাবে মুছে ফেলা হবে।\n"
            "• কোনো ক্ষতিকর ম্যালওয়্যার পেলে ফাইলটি ডেস্টিনেশনে আপলোড বন্ধ করে দেওয়া হবে।"
        )
    else:
        await message.reply_text(
            "🛡️ **Anti-Virus Shield: [ ❌ OFF ]**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• অ্যান্টিভাইরাস ফিল্টার বন্ধ করা হয়েছে।\n"
            "• সব ফাইল ও সফটওয়্যার যেমন আছে অবিকল ডেলিভার করা হবে।"
        )


@Client.on_message(filters.command(["addclean"]) & filters.private)
async def cmd_add_clean_word(client: Client, message: Message):
    """Adds words, usernames, or links to the user's permanent purge list."""
    user_id = message.from_user.id
    cmd = message.command
    if len(cmd) < 2:
        await message.reply_text(
            "⚠️ **Usage:** `/addclean <word বা link বা @handle>`\n\n"
            "উদাহরণ:\n"
            "• `/addclean @channel_name`\n"
            "• `/addclean t.me/badlink`\n"
            "• `/addclean Competitor Brand`\n\n"
            "একাধিক একসাথে দিতে কমা (,) ব্যবহার করতে পারো:\n"
            "• `/addclean @spammer, t.me/leaks, SecretBrand`"
        )
        return

    raw_args = message.text.split(None, 1)[1]
    items = [x.strip() for x in raw_args.split(",") if x.strip()]
    current = []
    for item in items:
        current = await db.add_clean_word(user_id, item)

    await message.reply_text(
        f"✅ **যোগ করা হয়েছে!**\n"
        f"মোট `{len(current)}` টি কাস্টম শব্দ/লিংক এখন সব ফাইলের নাম, টেক্সট এবং ভেতর থেকে অল-টাইম ডিলিট হবে।\n\n"
        f"📋 বর্তমান লিস্ট দেখতে: `/cleanwords`"
    )


@Client.on_message(filters.command(["delclean"]) & filters.private)
async def cmd_del_clean_word(client: Client, message: Message):
    """Removes a word from the purge list."""
    user_id = message.from_user.id
    cmd = message.command
    if len(cmd) < 2:
        await message.reply_text("⚠️ **Usage:** `/delclean <word>`")
        return

    word = message.text.split(None, 1)[1].strip()
    updated = await db.remove_clean_word(user_id, word)
    await message.reply_text(f"🗑️ `{word}` ডিলিট লিস্ট থেকে বাদ দেওয়া হয়েছে। বর্তমান শব্দ সংখ্যা: `{len(updated)}`")


@Client.on_message(filters.command(["cleanwords"]) & filters.private)
async def cmd_list_clean_words(client: Client, message: Message):
    """Shows all custom words currently set to be purged."""
    user_id = message.from_user.id
    words = await db.get_clean_words(user_id)
    if not words:
        await message.reply_text(
            "ℹ️ তোমার কোনো কাস্টম ডিলিট শব্দ সেট করা নেই।\n"
            "নতুন শব্দ যোগ করতে: `/addclean <word>`"
        )
        return

    text = "🛡️ **তোমার অল-টাইম কাস্টম ডিলিট লিস্ট:**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, w in enumerate(words, 1):
        text += f"{i}. `{w}`\n"
    text += "\n💡 বাদ দিতে: `/delclean <word>`\nসব মুছতে: `/clearclean`"
    await message.reply_text(text)


@Client.on_message(filters.command(["clearclean"]) & filters.private)
async def cmd_clear_clean_words(client: Client, message: Message):
    """Clears all custom clean words."""
    user_id = message.from_user.id
    await db.clear_clean_words(user_id)
    await message.reply_text("🧹 তোমার সব কাস্টম ডিলিট শব্দ ক্লিয়ার করা হয়েছে।")


def _parse_message_link(raw_str: str) -> Optional[tuple]:
    """Extracts (chat_id, message_id) from raw message link or ID."""
    cleaned = raw_str.strip()
    # Pattern: https://t.me/c/1883004189/123
    m_priv = re.search(r"t\.me/c/(\d+)/(\d+)", cleaned)
    if m_priv:
        return int(f"-100{m_priv.group(1)}"), int(m_priv.group(2))

    # Pattern: https://t.me/username/123
    m_pub = re.search(r"t\.me/([a-zA-Z0-9_]{3,})/(\d+)", cleaned)
    if m_pub:
        return f"@{m_pub.group(1)}", int(m_pub.group(2))

    # Just an integer message ID
    if cleaned.isdigit():
        return DEFAULT_SOURCE_CHANNEL, int(cleaned)

    return None


@Client.on_message(filters.command(["inspect", "testclean", "cleanpost"]) & filters.private)
async def cmd_inspect_post(client: Client, message: Message):
    """
    Downloads a single post, extracts everything, performs A-to-Z deep sanitization,
    forwards/uploads clean to destination, and replies with a full audit log.
    Usage:
      /inspect <post_link বা message_id>
    """
    user_id = message.from_user.id
    cmd = message.command

    if len(cmd) < 2:
        await message.reply_text(
            "🔍 **DEEP INSPECTION & LIVE TEST WIZARD**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "যেকোনো পোস্ট লিংক দিলে বট পুরো ফাইল ওপেন করে তল্লাশি চালিয়ে সব প্রমো মুছে ডেস্টিনেশনে পাঠিয়ে দেবে।\n\n"
            "📌 **ব্যবহার:**\n"
            "• `/inspect https://t.me/c/1883004189/123`\n"
            "• `/inspect 123` (ডিফল্ট সোর্স চ্যানেল `-1001883004189` ধরে নেবে)\n\n"
            f"📥 **সোর্স চ্যানেল:** `{DEFAULT_SOURCE_CHANNEL}`\n"
            f"📤 **টার্গেট চ্যানেল:** `{DEFAULT_DEST_CHANNEL}`"
        )
        return

    link_arg = cmd[1]
    parsed = _parse_message_link(link_arg)
    if not parsed:
        await message.reply_text("❌ অবৈধ পোস্ট লিংক বা মেসেজ আইডি।")
        return

    source_chat_id, msg_id = parsed
    dest_chat_id = DEFAULT_DEST_CHANNEL

    status_msg = await message.reply_text(
        f"⏳ **তল্লাশি শুরু হচ্ছে...**\n"
        f"📥 সোর্স: `{source_chat_id}` (ID: `{msg_id}`)\n"
        f"📡 টেলিগ্রাম থেকে ফাইল ডাউনলোড হচ্ছে..."
    )

    worker_client = await get_user_client(user_id)
    if not worker_client:
        await status_msg.edit_text("❌ সেশন বা ইউজারবট ক্লায়েন্ট পাওয়া যায়নি। `/login` চেক করো।")
        return

    try:
        # 1. Fetch the source message metadata
        try:
            src_msg = await worker_client.get_messages(source_chat_id, msg_id)
        except Exception as e:
            await status_msg.edit_text(f"❌ সোর্স পোস্ট আনতে ব্যর্থ: {e}")
            return

        if not src_msg or src_msg.empty:
            await status_msg.edit_text("❌ এই পোস্টটি ডিলিট বা খালি।")
            return

        # Extract channel branding info
        chat_title = getattr(src_msg.chat, "title", "") or ""
        chat_username = getattr(src_msg.chat, "username", "") or ""
        custom_words = await db.get_clean_words(user_id)

        await status_msg.edit_text(
            f"🔎 **সোর্স ডিটেক্টেড:** `{chat_title}` (`@{chat_username}`)\n"
            f"⚡ ফাইল স্টেজিংয়ে ডাউনলোড হচ্ছে..."
        )

        job_id = f"test_{user_id}_{msg_id}"

        # 2. Download media
        dl_res = await download_restricted_media(
            client=worker_client,
            bot_client=client,
            chat_id=source_chat_id,
            message_id=msg_id,
            status_message=None,
            job_id=job_id,
            user_id=user_id,
        )

        if not dl_res or not dl_res.get("file_path"):
            # Check if it was pure text
            if src_msg.text:
                clean_text = strip_competitor_ads(src_msg.text)
                for cw in custom_words:
                    clean_text = re.sub(re.escape(cw), "", clean_text, flags=re.IGNORECASE)
                clean_text = re.sub(re.escape(chat_title), "", clean_text, flags=re.IGNORECASE) if chat_title else clean_text

                await client.send_message(dest_chat_id, clean_text)
                await status_msg.edit_text(
                    f"✅ **টেক্সট পোস্ট সফলভাবে ক্লিন ও ডেলিভার হয়েছে!**\n"
                    f"📤 পাঠানো হয়েছে: `{dest_chat_id}`"
                )
                return

            await status_msg.edit_text("❌ কোনো ফাইল বা কন্টেন্ট ডাউনলোড করা যায়নি।")
            return

        orig_path = dl_res["file_path"]
        orig_name = os.path.basename(orig_path)

        await status_msg.edit_text(
            f"🛠️ **A to Z ডিপ ইন্সপেকশন ও ক্লিনিং চলছে...**\n"
            f"📁 ফাইল: `{orig_name}`"
        )

        # 3. Master Deep Inspection & Sanitization Gate
        antivirus_scan = await db.get_antivirus_scan(user_id)
        audit_res = await deep_inspect_and_sanitize(
            file_path=orig_path,
            channel_title=chat_title,
            channel_username=chat_username,
            custom_words=custom_words,
            antivirus_scan=antivirus_scan,
        )

        # Check if file was blocked by Anti-Virus Shield
        if audit_res.get("blocked_threat"):
            threat_name = audit_res.get("threat_name", "Unknown Threat")
            await status_msg.edit_text(
                f"🚨 **[SECURITY ALERT: THREAT BLOCKED]** 🚨\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📥 **সোর্স:** `{chat_title}` (`{source_chat_id}`)\n"
                f"📁 **ফাইল:** `{orig_name}`\n"
                f"⚠️ **সনাক্তকৃত হুমকি:** `{threat_name}`\n\n"
                f"🛡️ **ফাইলটি ডেস্টিনেশনে পাঠানো হয়নি!**\n"
                f"তোমার চ্যানেল ও সাবস্ক্রাইবারদের ডিভাইস সুরক্ষিত রাখতে এটি ব্লক ও বিনষ্ট করা হয়েছে।"
            )
            return

        clean_path = audit_res["clean_path"]
        clean_name = audit_res["clean_name"]
        audits = audit_res["audits"]

        # Update download result with cleaned path
        dl_res["file_path"] = clean_path

        # 4. Clean Caption
        orig_caption = dl_res.get("caption", "") or getattr(src_msg, "caption", "") or ""
        clean_caption = strip_competitor_ads(orig_caption)
        if chat_title:
            clean_caption = re.sub(re.escape(chat_title), "", clean_caption, flags=re.IGNORECASE)
        if chat_username:
            clean_caption = re.sub(rf"(?i)@?{re.escape(chat_username)}", "", clean_caption)
        for cw in custom_words:
            clean_caption = re.sub(re.escape(cw), "", clean_caption, flags=re.IGNORECASE)

        clean_caption = re.sub(r"\s+", " ", clean_caption).strip()
        dl_res["caption"] = clean_caption

        await status_msg.edit_text(
            f"🚀 **১০০% হোয়াইট-লেবেল ফাইল আপলোড হচ্ছে...**\n"
            f"📤 ডেস্টিনেশন: `{dest_chat_id}`"
        )

        # 5. Upload to destination channel
        await upload_unlocked_media(
            client=client,
            chat_id=dest_chat_id,
            file_info=dl_res,
            status_message=None,
            job_id=job_id,
            user_id=user_id,
        )

        # 6. Build and send audit report to AN0N
        audit_lines = "\n".join([f"• {a}" for a in audits]) if audits else "• কোনো লুকানো প্রমো বা মেটাডাটা পাওয়া যায়নি।"

        report = (
            f"🎯 **A to Z ডিপ ইন্সপেকশন অডিট রিপোর্ট**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 **সোর্স:** `{chat_title}` (`{source_chat_id}`)\n"
            f"📤 **ডেস্টিনেশন:** `{dest_chat_id}`\n\n"
            f"📁 **আসল ফাইলনেম:** `{orig_name}`\n"
            f"✨ **ক্লিন ফাইলনেম:** `{clean_name}`\n\n"
            f"🛡️ **অ্যাকশন লগ (কী কী ডিলিট হলো):**\n"
            f"{audit_lines}\n\n"
            f"✅ **ফলাফল:** ১% প্রমাণও অবশিষ্ট নেই। ফাইলটি সম্পূর্ণ নতুন হিসেবে ডেস্টিনেশনে আপলোড সম্পন্ন!"
        )

        await status_msg.edit_text(report)

    except Exception as e:
        await status_msg.edit_text(f"❌ টেস্ট চলাকালীন এরর: {e}")
    finally:
        active_jobs.pop(job_id, None)


@Client.on_message(filters.command(["clonelast"]) & filters.private)
async def cmd_clone_last_n(client: Client, message: Message):
    """
    Clones the last N posts from the source channel to destination channel.
    Usage:
      /clonelast <count>
      Example: /clonelast 100
    """
    user_id = message.from_user.id
    cmd = message.command

    if len(cmd) < 2 or not cmd[1].isdigit():
        await message.reply_text(
            "📋 **CLONE LAST N POSTS WIZARD**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "সোর্স চ্যানেলের সর্বশেষ N সংখ্যক পোস্ট এক ক্লিকে ডিপ-ক্লিন করে ক্লোন করো।\n\n"
            "📌 **ব্যবহার:**\n"
            "`/clonelast 100` (সর্বশেষ ১০০টি পোস্ট ক্লোন করবে)\n"
            "`/clonelast 50`\n\n"
            f"📥 **ডিফল্ট সোর্স:** `{DEFAULT_SOURCE_CHANNEL}`\n"
            f"📤 **ডিফল্ট ডেস্টিনেশন:** `{DEFAULT_DEST_CHANNEL}`"
        )
        return

    count = int(cmd[1])
    if count <= 0:
        await message.reply_text("❌ পোস্ট সংখ্যা ১ এর বেশি হতে হবে।")
        return

    source_target = DEFAULT_SOURCE_CHANNEL
    dest_target = DEFAULT_DEST_CHANNEL

    status_msg = await message.reply_text(
        f"⏳ সোর্স চ্যানেলের সর্বশেষ মেসেজ আইডি খোঁজা হচ্ছে...\n"
        f"📥 সোর্স: `{source_target}`"
    )

    worker_client = await get_user_client(user_id)
    if not worker_client:
        await status_msg.edit_text("❌ সেশন পাওয়া যায়নি। `/login` চেক করো।")
        return

    try:
        # Find the latest message ID in source channel
        latest_msg_id = 0
        async for m in worker_client.get_chat_history(source_target, limit=1):
            if m:
                latest_msg_id = m.id
                break

        if not latest_msg_id:
            await status_msg.edit_text("❌ সোর্স চ্যানেল থেকে কোনো মেসেজ পাওয়া যায়নি।")
            return

        start_id = max(1, latest_msg_id - count + 1)
        end_id = latest_msg_id

        await status_msg.edit_text(
            f"🚀 **ক্লোন শুরু হচ্ছে!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 সোর্স: `{source_target}`\n"
            f"📤 ডেস্টিনেশন: `{dest_target}`\n"
            f"📦 রেঞ্জ: `{start_id}` থেকে `{end_id}` (মোট `{end_id - start_id + 1}` টি পোস্ট)\n"
            f"🛡️ **সব ফাইল A to Z ডিপ স্যানিটাইজার গেট হয়ে যাবে!**"
        )

        from handlers.cloner import _launch_clone_task
        import uuid
        clone_id = f"last_{uuid.uuid4().hex[:6]}"

        await _launch_clone_task(
            bot_client=client,
            message=message,
            user_id=user_id,
            source_target=source_target,
            dest_target=dest_target,
            start_id=start_id,
            end_id=end_id,
            clone_id=clone_id,
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ এরর: {e}")
