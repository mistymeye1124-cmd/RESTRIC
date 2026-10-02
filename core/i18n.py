# language: Python, file: core/i18n.py, target: Python 3.10+
"""
Internationalization (i18n) Engine for Multi-Language Support:
Supported Languages:
- English (en) [Default]
- Bengali / বাংলা (bn)
- Hindi / हिन्दी (hi)
- Urdu / اردو (ur - Pakistan)

Features:
- Instant in-memory string lookup
- Dynamic fallback to English
- Auto-sync engine: if English is edited, translations are automatically updated across all languages!
- Interactive inline keyboard generation
"""

import os
import json
import logging
import hashlib
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

LOCALES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locales", "strings.json")

SUPPORTED_LANGUAGES = {
    "en": {"code": "en", "name": "English", "native": "English", "flag": "🇺🇸"},
    "bn": {"code": "bn", "name": "Bangla", "native": "বাংলা", "flag": "🇧🇩"},
    "hi": {"code": "hi", "name": "Hindi", "native": "हिन्दी", "flag": "🇮🇳"},
    "ur": {"code": "ur", "name": "Urdu", "native": "اردو", "flag": "🇵🇰"},
}

_STRINGS_CACHE: Dict[str, Dict[str, str]] = {}


def load_strings() -> Dict[str, Dict[str, str]]:
    """Loads localized strings from strings.json into memory."""
    global _STRINGS_CACHE
    if os.path.exists(LOCALES_FILE):
        try:
            with open(LOCALES_FILE, "r", encoding="utf-8") as f:
                _STRINGS_CACHE = json.load(f)
        except Exception as e:
            logger.error(f"[i18n] Failed to load strings.json: {e}")
    return _STRINGS_CACHE


def save_strings(data: Dict[str, Dict[str, str]]) -> bool:
    """Saves updated localization strings back to strings.json."""
    global _STRINGS_CACHE
    _STRINGS_CACHE = data
    try:
        os.makedirs(os.path.dirname(LOCALES_FILE), exist_ok=True)
        with open(LOCALES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"[i18n] Failed to save strings.json: {e}")
        return False


# Initial load
load_strings()


def auto_translate(text: str, target_lang: str) -> str:
    """Translates text from English to target_lang using Google Translate GTX endpoint."""
    if target_lang == "en" or not text or not text.strip():
        return text
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl={target_lang}&dt=t&q={urllib.parse.quote(text)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            translated = "".join(part[0] for part in data[0] if part and part[0])
            return translated if translated else text
    except Exception as e:
        logger.debug(f"[i18n] Auto-translate error for {target_lang}: {e}")
        return text


def t(key: str, lang: str = "en", **kwargs) -> str:
    """
    Translates a key into the requested language, with formatting variables.
    Falls back to English if the key is missing in the target language.
    """
    global _STRINGS_CACHE
    if not _STRINGS_CACHE:
        load_strings()

    target_lang = lang if lang in SUPPORTED_LANGUAGES else "en"
    key_dict = _STRINGS_CACHE.get(key, {})

    # 1. Direct translation
    translated = key_dict.get(target_lang)
    
    # 2. Fallback to English
    if not translated:
        translated = key_dict.get("en", key)

    # 3. Apply format variables
    if kwargs and isinstance(translated, str):
        try:
            return translated.format(**kwargs)
        except Exception:
            return translated

    return translated


def get_lang_display(lang_code: str) -> str:
    """Returns human-readable language badge (e.g. '🇧🇩 বাংলা' or '🇺🇸 English')."""
    info = SUPPORTED_LANGUAGES.get(lang_code, SUPPORTED_LANGUAGES["en"])
    return f"{info['flag']} {info['native']}"


def get_language_keyboard(current_lang: str = "en", back_callback: str = "back_to_main") -> InlineKeyboardMarkup:
    """Builds inline keyboard for language switching with checkmark on the active one."""
    current = current_lang if current_lang in SUPPORTED_LANGUAGES else "en"

    buttons = []
    row1 = []
    for code in ("en", "bn"):
        info = SUPPORTED_LANGUAGES[code]
        mark = " ✅" if code == current else ""
        text = f"{info['flag']} {info['native']}{mark}"
        row1.append(InlineKeyboardButton(text, callback_data=f"set_lang:{code}"))
    buttons.append(row1)

    row2 = []
    for code in ("hi", "ur"):
        info = SUPPORTED_LANGUAGES[code]
        mark = " ✅" if code == current else ""
        text = f"{info['flag']} {info['native']}{mark}"
        row2.append(InlineKeyboardButton(text, callback_data=f"set_lang:{code}"))
    buttons.append(row2)

    buttons.append([InlineKeyboardButton(t("btn_back_main", current), callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)


def _compute_hash(text: str) -> str:
    """Computes a short MD5 hash of text to track whether it changed."""
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()[:10]


def sync_all_translations(force: bool = False) -> int:
    """
    Scans strings.json.
    - If AN0N edited English text (detected via hash difference), auto-translates to bn, hi, ur.
    - If any target language is missing, auto-translates from English.
    - If force=True, re-translates all keys from English.
    Returns the number of keys synchronized.
    """
    data = load_strings()
    updated_count = 0

    for key, lang_map in data.items():
        en_text = lang_map.get("en", "")
        if not en_text or not en_text.strip():
            continue

        current_hash = _compute_hash(en_text)
        stored_hash = lang_map.get("_src_hash")
        en_was_edited = force or (stored_hash is not None and stored_hash != current_hash)

        needs_save = False

        for target_code in ("bn", "hi", "ur"):
            # Translate if: forced, English was edited, or translation is missing/empty
            if en_was_edited or target_code not in lang_map or not lang_map[target_code]:
                print(f"[i18n] Auto-syncing '{key}' -> {target_code}...")
                translated = auto_translate(en_text, target_code)
                lang_map[target_code] = translated
                needs_save = True

        if needs_save or stored_hash != current_hash:
            lang_map["_src_hash"] = current_hash
            updated_count += 1

    if updated_count > 0:
        save_strings(data)
        print(f"[+] Successfully auto-synced {updated_count} translation entries!")
    else:
        print("[+] All translations are already 100% up to date.")
    return updated_count
