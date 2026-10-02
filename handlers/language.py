# language: Python, file: handlers/language.py, target: Python 3.10+, Pyrogram
"""
Language Switcher Handler:
Supports English (en), Bengali (bn), Hindi (hi), and Urdu (ur).
"""

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from database import db
from core.i18n import t, get_language_keyboard, get_lang_display, SUPPORTED_LANGUAGES


@Client.on_message(filters.command(["language", "lang", "bhasha"]) & filters.private)
async def language_command_handler(client: Client, message: Message):
    user_id = message.from_user.id
    lang = await db.get_user_language(user_id)
    text = t("lang_menu_title", lang)
    markup = get_language_keyboard(current_lang=lang, back_callback="back_to_main")
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^user_view_language$"))
async def user_view_language_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    lang = await db.get_user_language(user_id)
    text = t("lang_menu_title", lang)
    markup = get_language_keyboard(current_lang=lang, back_callback="back_to_main")
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback_query.message.reply_text(text, reply_markup=markup)
    await callback_query.answer()


@Client.on_callback_query(filters.regex(r"^set_lang:(.+)"))
async def set_language_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    new_lang = callback_query.matches[0].group(1).lower()

    if new_lang not in SUPPORTED_LANGUAGES:
        await callback_query.answer("Invalid language selection!", show_alert=True)
        return

    await db.set_user_language(user_id, new_lang)
    alert = t("lang_changed_alert", new_lang)
    await callback_query.answer(alert, show_alert=True)

    text = t("lang_menu_title", new_lang)
    markup = get_language_keyboard(current_lang=new_lang, back_callback="back_to_main")
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
