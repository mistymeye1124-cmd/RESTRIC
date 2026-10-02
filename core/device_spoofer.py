# language: Python, file: core/device_spoofer.py, target: Python 3.10+, Pyrogram
"""
Enterprise Anti-Ban Device & Fingerprint Engine.
Generates genuine, trusted official Telegram client fingerprints:
- Official Telegram Desktop (Windows 11 / Windows 10 / macOS Sonoma)
- Official Telegram Android (Samsung Galaxy S24 Ultra, Google Pixel 8 Pro, Xiaomi 14)
- Official Telegram iOS (iPhone 15 Pro, iPhone 14 Pro Max)

Prevents Telegram Datacenter session-flagging, heuristic anti-bot bans, and device mismatches.
"""

import random
from typing import Dict

_OFFICIAL_PROFILES = [
    # --- Telegram Desktop (Windows 11 / 10 64bit) ---
    {
        "device_model": "PC 64bit",
        "system_version": "Windows 11 Pro 23H2",
        "app_version": "5.9.0 x64",
        "lang_code": "en",
    },
    {
        "device_model": "Desktop",
        "system_version": "Windows 10 Enterprise",
        "app_version": "5.8.3 x64",
        "lang_code": "en",
    },
    # --- Telegram Desktop (macOS Sonoma / Sequoia) ---
    {
        "device_model": "MacBook Pro M3 Max",
        "system_version": "macOS 14.6.1",
        "app_version": "10.15.2",
        "lang_code": "en",
    },
    # --- Telegram Android (Official Samsung Flagship) ---
    {
        "device_model": "Samsung SM-S928B (Galaxy S24 Ultra)",
        "system_version": "SDK 34 (Android 14)",
        "app_version": "11.1.3 (5182)",
        "lang_code": "en",
    },
    {
        "device_model": "Google Pixel 9 Pro XL",
        "system_version": "SDK 35 (Android 15)",
        "app_version": "11.2.0 (5200)",
        "lang_code": "en",
    },
    {
        "device_model": "Xiaomi 14 Ultra (24030PN60G)",
        "system_version": "SDK 34 (HyperOS 1.0)",
        "app_version": "11.1.0 (5170)",
        "lang_code": "en",
    },
    # --- Telegram iOS (Apple Flagship Official) ---
    {
        "device_model": "iPhone 16 Pro Max",
        "system_version": "iOS 18.0.1",
        "app_version": "11.2.0",
        "lang_code": "en",
    },
    {
        "device_model": "iPhone 15 Pro",
        "system_version": "iOS 17.6.1",
        "app_version": "11.1.2",
        "lang_code": "en",
    }
]


def get_desktop_fingerprint(seed: int = None) -> Dict[str, str]:
    """
    Returns a realistic Telegram client fingerprint dict for Pyrogram Client kwargs.
    """
    if seed is not None:
        rng = random.Random(seed)
        profile = rng.choice(_OFFICIAL_PROFILES)
    else:
        profile = random.choice(_OFFICIAL_PROFILES)
    return dict(profile)


def get_fingerprint_for_user(user_id: int) -> Dict[str, str]:
    """
    Deterministically assigns a stable device fingerprint to a given user_id.
    The same user always gets the exact same device identity across sessions.
    """
    return get_desktop_fingerprint(seed=user_id)


def get_random_fingerprint() -> Dict[str, str]:
    """
    Returns a random realistic fingerprint — used for admin pool and worker sessions.
    """
    return get_desktop_fingerprint()
