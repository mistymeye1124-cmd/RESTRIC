# language: Python, file: sync_locales.py, target: Python 3.10+
"""
Automated Language Synchronization Tool:
Allows AN0N to edit any English text in 'locales/strings.json', then run:
    python sync_locales.py
Or force refresh everything:
    python sync_locales.py --force

This script automatically detects which English texts were edited (or newly added)
and seamlessly translates them across all languages:
- Bangla (bn)
- Hindi (hi)
- Urdu / Pakistan (ur)

Everything is saved directly to 'locales/strings.json'!
"""

import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(__file__))

from core.i18n import sync_all_translations, SUPPORTED_LANGUAGES

if __name__ == "__main__":
    force = "--force" in sys.argv or "-f" in sys.argv
    print("=" * 65)
    print("[*] MULTI-LANGUAGE AUTO-TRANSLATION SYNC ENGINE")
    print("Supported Languages:")
    for code, info in SUPPORTED_LANGUAGES.items():
        print(f"  * [{code.upper()}] {info['name']} - {info['native']}")
    print("=" * 65)
    if force:
        print("[!] Mode: FORCE SYNC (Translating all keys from English)")
    else:
        print("[*] Mode: SMART SYNC (Detecting newly added or modified English texts)")

    updated = sync_all_translations(force=force)
    print("=" * 65)
    if updated > 0:
        print(f"[OK] SUCCESS: {updated} text keys were synchronized across all languages!")
    else:
        print("[OK] UP-TO-DATE: All languages are already synchronized with English!")
    print("=" * 65)
