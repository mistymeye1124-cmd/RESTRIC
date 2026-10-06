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
        "system_version": "Windows 11 Pro 23H2",
        "app_version": "5.8.3 x64",
        "lang_code": "en",
    },
    {
        "device_model": "HP Spectre x360 14",
        "system_version": "Windows 11 Home 23H2",
        "app_version": "5.9.0 x64",
        "lang_code": "en",
    },
    {
        "device_model": "Custom Desktop PC (MSI Z790)",
        "system_version": "Windows 11 Pro 23H2",
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
    {
        "device_model": "Acer Swift Go 14",
        "system_version": "Windows 10 Pro 22H2",
        "app_version": "5.8.3 x64",
        "lang_code": "en",
    },
    # --- Apple macOS (Official Telegram Desktop App) ---
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
    {
        "device_model": "Mac Studio (M2 Ultra)",
        "system_version": "macOS 14.6",
        "app_version": "10.15.1",
        "lang_code": "en",
    },
    # --- Linux Desktop ---
    {
        "device_model": "PC 64bit",
        "system_version": "Ubuntu 24.04 LTS x86_64",
        "app_version": "5.9.0 x64",
        "lang_code": "en",
    },
    # --- Official Telegram Android (Flagship Mobile) ---
    {
        "device_model": "Samsung Galaxy S24 Ultra",
        "system_version": "Android 14 (OneUI 6.1)",
        "app_version": "11.1.3 (5249)",
        "lang_code": "en",
    },
    {
        "device_model": "Google Pixel 8 Pro",
        "system_version": "Android 14 (AP2A.240805.005)",
        "app_version": "11.1.3 (5249)",
        "lang_code": "en",
    },
    {
        "device_model": "Xiaomi 14 Ultra",
        "system_version": "Android 14 (HyperOS 1.0.12)",
        "app_version": "11.1.3 (5249)",
        "lang_code": "en",
    },
    {
        "device_model": "OnePlus 12",
        "system_version": "Android 14 (OxygenOS 14.0)",
        "app_version": "11.1.3 (5249)",
        "lang_code": "en",
    },
    # --- Official Telegram iOS (iPhone & iPad) ---
    {
        "device_model": "iPhone 15 Pro Max",
        "system_version": "iOS 17.6.1",
        "app_version": "10.16.0 (2912)",
        "lang_code": "en",
    },
    {
        "device_model": "iPhone 14 Pro",
        "system_version": "iOS 17.5.1",
        "app_version": "10.15.2 (2890)",
        "lang_code": "en",
    },
    {
        "device_model": "iPad Pro 12.9-inch (6th Gen)",
        "system_version": "iPadOS 17.6",
        "app_version": "10.16.0 (2912)",
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
