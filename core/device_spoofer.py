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
    # --- Windows 11 Official Desktop PC ---
    {
        "device_model": "Dell XPS 15 9530",
        "system_version": "Windows 11 Pro 23H2",
        "app_version": "5.9.0 x64",
        "lang_code": "en",
    },
    {
        "device_model": "ASUS ROG Zephyrus G14",
        "system_version": "Windows 11 Home",
        "app_version": "5.9.0 x64",
        "lang_code": "en",
    },
    {
        "device_model": "Lenovo ThinkPad X1 Carbon Gen 11",
        "system_version": "Windows 11 Pro",
        "app_version": "5.8.3 x64",
        "lang_code": "en",
    },
    {
        "device_model": "HP Spectre x360 14",
        "system_version": "Windows 11 Home",
        "app_version": "5.9.0 x64",
        "lang_code": "en",
    },
    # --- Windows 10 Official Desktop ---
    {
        "device_model": "Custom Desktop PC",
        "system_version": "Windows 10 Enterprise 22H2",
        "app_version": "5.8.3 x64",
        "lang_code": "en",
    },
    # --- Apple macOS (Desktop App) ---
    {
        "device_model": "MacBook Pro 16-inch M3 Max",
        "system_version": "macOS 14.6.1",
        "app_version": "10.15.2",
        "lang_code": "en",
    },
    {
        "device_model": "MacBook Air 15-inch M2",
        "system_version": "macOS 14.5",
        "app_version": "10.14.0",
        "lang_code": "en",
    },
    # --- Official Telegram Android ---
    {
        "device_model": "Samsung Galaxy S24 Ultra (SM-S928B)",
        "system_version": "SDK 34 (Android 14, OneUI 6.1)",
        "app_version": "10.14.5 (4982)",
        "lang_code": "en",
    },
    {
        "device_model": "Google Pixel 8 Pro (husky)",
        "system_version": "SDK 34 (Android 14)",
        "app_version": "10.14.5 (4982)",
        "lang_code": "en",
    },
    {
        "device_model": "Xiaomi 14 Ultra (aurora)",
        "system_version": "SDK 34 (HyperOS 1.0)",
        "app_version": "10.13.1 (4890)",
        "lang_code": "en",
    },
    {
        "device_model": "OnePlus 12 (CPH2573)",
        "system_version": "SDK 34 (OxygenOS 14)",
        "app_version": "10.14.0 (4932)",
        "lang_code": "en",
    },
    # --- Official Telegram iOS ---
    {
        "device_model": "iPhone 15 Pro Max (A3106)",
        "system_version": "iOS 17.6.1",
        "app_version": "10.14.1",
        "lang_code": "en",
    },
    {
        "device_model": "iPhone 14 Pro (A2890)",
        "system_version": "iOS 17.5.1",
        "app_version": "10.13.0",
        "lang_code": "en",
    },
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
