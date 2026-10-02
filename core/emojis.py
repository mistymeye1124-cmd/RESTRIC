# language: Python, file: core/emojis.py, target: Python 3.10+, Pyrogram
"""
Enterprise Custom Emoji Hub for Telegram Premium Animated Icons.
Maps bot icons to Telegram Premium custom_emoji_id values with 100% resilient
fallback to standard Unicode emojis.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional
from config import BASE_DIR

EMOJI_FILE = BASE_DIR / "custom_emojis.json"

# Master catalog of fallback standard Unicode emojis
FALLBACK_MAP: Dict[str, str] = {
    # Brand & Badges
    "diamond": "💎",
    "lightning": "⚡",
    "rocket": "🚀",
    "crown": "👑",
    "star": "⭐",
    "fire": "🔥",
    "trophy": "🏆",
    "shield": "🛡️",
    "sparkles": "✨",

    # Status Indicators
    "check": "✅",
    "cross": "❌",
    "warning": "⚠️",
    "circle_green": "🟢",
    "circle_white": "⚪",
    "circle_red": "🔴",

    # Actions, Tools & Navigation
    "gear": "⚙️",
    "video": "🎬",
    "audio": "🎵",
    "folder": "📁",
    "scissor": "✂️",
    "target": "🎯",
    "link": "🔗",
    "book": "📖",
    "users": "👥",
    "image": "🖼️",
    "speaker": "📢",
    "key": "🔐",
    "card": "💳",
    "globe": "🌐",
    "download": "⬇️",
    "upload": "⬆️",
    "bulb": "💡",
    "chart": "📊",
    "tv": "📺",
}

_CACHE: Dict[str, str] = {}


def load_custom_emojis() -> Dict[str, str]:
    """Loads custom emoji IDs from custom_emojis.json with fallback caching."""
    global _CACHE
    if not EMOJI_FILE.exists():
        _CACHE = {k: "" for k in FALLBACK_MAP}
        save_custom_emojis(_CACHE)
        return _CACHE

    try:
        with open(EMOJI_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            _CACHE = {k: str(v).strip() for k, v in data.items() if str(v).strip()}
    except Exception as e:
        print(f"[!] Error loading custom_emojis.json: {e}")
        _CACHE = {}

    return _CACHE


def save_custom_emojis(data: Dict[str, str]):
    """Saves updated emoji map to custom_emojis.json and refreshes cache."""
    global _CACHE
    try:
        # Merge with existing
        full_map = {k: "" for k in FALLBACK_MAP}
        full_map.update(data)
        with open(EMOJI_FILE, "w", encoding="utf-8") as f:
            json.dump(full_map, f, indent=2, ensure_ascii=False)
        _CACHE = {k: str(v).strip() for k, v in full_map.items() if str(v).strip()}
    except Exception as e:
        print(f"[!] Error saving custom_emojis.json: {e}")


def get_emoji(name: str) -> str:
    """
    Returns Telegram Markdown Custom Emoji link if custom ID is configured,
    e.g. [💎](tg://emoji?id=5434149870817042070).
    Otherwise returns clean fallback Unicode character (e.g. 💎).
    """
    global _CACHE
    if not _CACHE:
        load_custom_emojis()

    fallback = FALLBACK_MAP.get(name, "•")
    custom_id = _CACHE.get(name, "").strip()

    if custom_id and custom_id.isdigit():
        return f"[{fallback}](tg://emoji?id={custom_id})"

    return fallback


# Shorthand alias
e = get_emoji


import re


def apply_custom_emojis(text: str) -> str:
    """
    Transforms all standard emojis in text into Telegram Premium Custom Emojis
    using tg://emoji?id=<custom_emoji_id> formatting.
    Guarantees no double-replacement.
    """
    if not text:
        return text

    global _CACHE
    if not _CACHE:
        load_custom_emojis()

    # Pre-compiled replacement list sorted by character length descending
    for name, fallback in sorted(FALLBACK_MAP.items(), key=lambda x: len(x[1]), reverse=True):
        cid = _CACHE.get(name)
        if not cid:
            continue

        # Variations with and without variation selector \ufe0f
        variants = [fallback]
        if "\ufe0f" in fallback:
            variants.append(fallback.replace("\ufe0f", ""))
        else:
            variants.append(fallback + "\ufe0f")

        replacement = f"[{fallback}](tg://emoji?id={cid})"

        for v in variants:
            # Pattern matching v ONLY if not already followed by ](tg://emoji
            pattern = re.escape(v) + r"(?!\]\(tg://emoji)"
            text = re.sub(pattern, replacement, text)

    return text


def set_custom_emoji_id(name: str, emoji_id: str):
    """Sets a single custom emoji ID and updates store."""
    current = load_custom_emojis()
    current[name] = str(emoji_id).strip()
    save_custom_emojis(current)


# Initialize cache at import time
load_custom_emojis()

