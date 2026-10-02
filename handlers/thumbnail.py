# language: Python, file: handlers/thumbnail.py, target: Python 3.10+, Pyrogram
"""
Custom Thumbnail Studio Handler:
Allows channel admins and content distributors to upload their bespoke thumbnail / poster,
view the live preview, or clear it. Every video delivered to this user or their auto-forward channel
will automatically carry this branding.
"""

import os
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import db
from config import BASE_DIR
from core.emojis import apply_custom_emojis
from core.state_manager import get_user_state

THUMBS_DIR = BASE_DIR / "downloads" / "thumbnails"
THUMBS_DIR.mkdir(parents=True, exist_ok=True)


async def render_thumbnail_studio_card(user_id: int):
    """Generates the Studio status card and control keyboard with ON/OFF toggle."""
    custom_thumb = await db.get_custom_thumbnail(user_id, check_enabled=False)
    has_thumb = bool(custom_thumb and os.path.exists(custom_thumb))
    settings = await db.get_settings(user_id)
    is_enabled = bool(settings.get("custom_thumb_enabled", 1))

    if not has_thumb:
        status_icon = "⚪ **Not Set (Original Auto-Extracted Frames)**"
    elif is_enabled:
        status_icon = "🟢 **ON (Applied to 100% of Videos & Documents)**"
    else:
        status_icon = "⚪ **OFF (Disabled - Using Original Video Frames)**"

    text = (
        "🖼️ **CUSTOM THUMBNAIL STUDIO PRO** 🖼️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ **CUSTOM VIDEO POSTER & BRANDING**\n\n"
        "• **ON:** Your custom thumbnail is applied to **every single video and document** "
        "(direct links, batch harvest, channel cloner, and auto-forwards)!\n"
        "• **OFF:** Custom thumbnail is completely disabled; videos use their original auto-extracted frames.\n\n"
        f"• Status: {status_icon}\n"
        f"• File Path: `{os.path.basename(custom_thumb) if has_thumb else 'None'}`\n\n"
        "┌── 📸 **HOW TO SET A CUSTOM THUMBNAIL** ─┐\n"
        "│ 1. Send any photo directly to this chat.\n"
        "│ 2. Or reply to any photo with `/setthumb`.\n"
        "│ 3. Commands: `/thumb on` or `/thumb off`\n"
        "└────────────────────────────────────────┘\n\n"
        "👇 _Manage your thumbnail studio below:_"
    )

    buttons = []
    if has_thumb:
        toggle_label = "🟢 Thumbnail: ON (Tap to Turn OFF)" if is_enabled else "⚪ Thumbnail: OFF (Tap to Turn ON)"
        buttons.append([
            InlineKeyboardButton(toggle_label, callback_data="toggle_custom_thumb"),
        ])
        buttons.append([
            InlineKeyboardButton("👁️ Preview Active Thumbnail", callback_data="preview_custom_thumb"),
            InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="delete_custom_thumb"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("📸 Send Photo to Set", callback_data="prompt_send_thumb"),
        ])

    buttons.append([
        InlineKeyboardButton("🔙 Back to Settings", callback_data="user_view_settings"),
        InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main"),
    ])

    return apply_custom_emojis(text), InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command(["thumb", "thumbnail"]) & filters.private)
async def thumbnail_studio_command(client: Client, message: Message):
    user_id = message.from_user.id
    cmd_args = message.command[1:] if len(message.command) > 1 else []
    if cmd_args:
        arg = cmd_args[0].lower().strip()
        if arg in ("on", "enable", "activate", "1", "yes", "true"):
            custom_thumb = await db.get_custom_thumbnail(user_id, check_enabled=False)
            if not custom_thumb or not os.path.exists(custom_thumb):
                await message.reply_text(
                    "⚠️ **No Custom Thumbnail Found!**\n\n"
                    "Please send a photo first or reply to a photo with `/setthumb` to set your thumbnail before enabling it."
                )
                return
            await db.set_custom_thumbnail_enabled(user_id, True)
            await message.reply_text(
                "🟢 **Custom Thumbnail ENABLED!**\n\n"
                "Now it will be applied to **all** videos, batch downloads, cloner, and auto-forwards."
            )
            return
        elif arg in ("off", "disable", "pause", "0", "no", "false"):
            await db.set_custom_thumbnail_enabled(user_id, False)
            await message.reply_text(
                "⚪ **Custom Thumbnail DISABLED!**\n\n"
                "All future videos will use their original auto-extracted frames."
            )
            return

    text, markup = await render_thumbnail_studio_card(user_id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command("setthumb") & filters.private)
async def set_thumb_command(client: Client, message: Message):
    user_id = message.from_user.id
    target_msg = message.reply_to_message if message.reply_to_message else message

    if not target_msg.photo:
        await message.reply_text(
            "⚠️ **No Photo Detected!**\n\n"
            "Please send a photo with caption `/setthumb`, or reply to an existing photo with `/setthumb`."
        )
        return

    # Download photo
    target_path = str(THUMBS_DIR / f"{user_id}.jpg")
    try:
        await client.download_media(target_msg.photo, file_name=target_path)
        await db.set_custom_thumbnail(user_id, target_path)
        await message.reply_text(
            "✅ **Custom Thumbnail Saved Successfully!**\n\n"
            "All future video downloads and auto-forwards will now feature your custom poster."
        )
    except Exception as e:
        await message.reply_text(f"❌ Failed to save custom thumbnail: {e}")


@Client.on_message(filters.photo & filters.private)
async def photo_listener_thumb(client: Client, message: Message):
    """If user sends a standalone photo without other command, prompt if they want it as thumbnail."""
    user_id = message.from_user.id
    state_info = get_user_state(user_id)
    if state_info and state_info.get("state"):
        message.continue_propagation()
        return

    # Never intercept multi-photo albums for single video thumbnail
    if message.media_group_id:
        message.continue_propagation()
        return

    caption = (message.caption or "").strip().lower()

    # If caption is /setthumb, handle directly
    if caption == "/setthumb":
        target_path = str(THUMBS_DIR / f"{user_id}.jpg")
        try:
            await client.download_media(message.photo, file_name=target_path)
            await db.set_custom_thumbnail(user_id, target_path)
            await message.reply_text("✅ **Custom Thumbnail Saved!**")
        except Exception as e:
            await message.reply_text(f"❌ Error: {e}")
        return

    # Or provide one-tap button to save as thumbnail
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🖼️ Set as Custom Video Thumbnail", callback_data=f"save_as_thumb:{message.id}"),
            ]
        ]
    )
    await message.reply_text(
        "📸 **Photo Received!**\nWould you like to set this image as your permanent video thumbnail?",
        reply_markup=markup,
    )


@Client.on_message(filters.command(["delthumb", "clearthumb"]) & filters.private)
async def del_thumb_command(client: Client, message: Message):
    user_id = message.from_user.id
    await db.delete_custom_thumbnail(user_id)
    await message.reply_text("🗑️ **Custom thumbnail removed!** Videos will use original auto-extracted frames.")


@Client.on_message(filters.command(["viewthumb", "showthumb"]) & filters.private)
async def view_thumb_command(client: Client, message: Message):
    user_id = message.from_user.id
    thumb = await db.get_custom_thumbnail(user_id)
    if thumb and os.path.exists(thumb):
        await message.reply_photo(photo=thumb, caption="🖼️ **Your Active Custom Video Thumbnail**")
    else:
        await message.reply_text("ℹ️ You have no custom thumbnail set. Bot will extract video frames automatically.")


# ────────────────────────── CALLBACKS ──────────────────────────

@Client.on_callback_query(filters.regex(r"^user_view_thumbnail$"))
async def callback_view_thumbnail(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    text, markup = await render_thumbnail_studio_card(user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await query.message.reply_text(text, reply_markup=markup)
    await query.answer()


@Client.on_callback_query(filters.regex(r"^preview_custom_thumb$"))
async def callback_preview_thumb(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    thumb = await db.get_custom_thumbnail(user_id)
    if thumb and os.path.exists(thumb):
        await query.message.reply_photo(photo=thumb, caption="🖼️ **Active Custom Video Thumbnail**")
        await query.answer()
    else:
        await query.answer("No custom thumbnail currently active.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^toggle_custom_thumb$"))
async def callback_toggle_thumb(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    new_state = await db.toggle_custom_thumbnail(user_id)
    if new_state:
        alert_str = "🟢 Custom Thumbnail is now ON!\nApplied to 100% of videos, cloner & forwards."
    else:
        alert_str = "⚪ Custom Thumbnail is now OFF!\nVideos will use original auto-extracted frames."
    await query.answer(alert_str, show_alert=True)
    text, markup = await render_thumbnail_studio_card(user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^delete_custom_thumb$"))
async def callback_delete_thumb(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    await db.delete_custom_thumbnail(user_id)
    await query.answer("🗑️ Custom thumbnail deleted!", show_alert=True)
    text, markup = await render_thumbnail_studio_card(user_id)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^prompt_send_thumb$"))
async def callback_prompt_thumb(client: Client, query: CallbackQuery):
    await query.answer("Please send any photo directly to this chat!", show_alert=True)


@Client.on_callback_query(filters.regex(r"^save_as_thumb:(\d+)$"))
async def callback_save_photo_as_thumb(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    msg_id = int(query.matches[0].group(1))

    try:
        source_msg = await client.get_messages(chat_id=query.message.chat.id, message_ids=msg_id)
        if source_msg and source_msg.photo:
            target_path = str(THUMBS_DIR / f"{user_id}.jpg")
            await client.download_media(source_msg.photo, file_name=target_path)
            await db.set_custom_thumbnail(user_id, target_path)
            await query.answer("✅ Saved as your Custom Thumbnail!", show_alert=True)
            try:
                await query.message.edit_text("✅ **Custom Thumbnail Activated Successfully!**")
            except Exception:
                pass
            return
    except Exception as e:
        print(f"[!] Error saving photo as thumb: {e}")

    await query.answer("❌ Could not save photo as thumbnail.", show_alert=True)
