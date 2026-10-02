# language: Python, file: generate_session.py, target: Windows/Linux, Python 3.10+
"""
Automated Telegram Account Connector & StringSession Generator.
Connects your Telegram personal account directly and permanently to the bot database.
Bypasses all Telegram Bot API anti-phishing blocks and code expiration issues.
"""

import sys
import asyncio

# Ensure an asyncio event loop exists before Pyrogram imports for Python 3.12+ / 3.14
try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from pyrogram import Client
from config import API_ID, API_HASH
from database import db

# Force UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def main():
    print("=" * 68)
    print("🚀 TELEGRAM PERMANENT ACCOUNT CONNECTOR")
    print("=" * 68)
    print(f"[*] API_ID: {API_ID}")
    print("[*] Target Database: bot_database.db")
    print("-" * 68)
    print("Please follow the prompt below to log in directly through your terminal.")
    print("Telegram will NOT block or expire this code because it runs in your console!")
    print("-" * 68)

    app = Client(
        name="direct_account_session",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True,
    )

    try:
        async with app:
            me = await app.get_me()
            session_str = await app.export_session_string()

            # Initialize DB and save session permanently
            await db.init()
            await db.save_session(
                user_id=me.id,
                phone=me.phone_number or "",
                string_session=session_str,
            )

            print("\n" + "=" * 68)
            print("🎉 ACCOUNT PERMANENTLY CONNECTED TO YOUR BOT DATABASE!")
            print("=" * 68)
            print(f"• Name:             {me.first_name}")
            print(f"• Username:         @{me.username or 'N/A'}")
            print(f"• Telegram User ID: {me.id}")
            print(f"• Phone Number:     +{me.phone_number}")
            print("• Database Status:  SAVED & ACTIVE (Permanent)")
            print("=" * 68)
            print("\n📋 Your Session String (Saved automatically to bot_database.db):\n")
            print(session_str)
            print("\n" + "=" * 68)
            print("✅ SUCCESS: You can now download restricted videos directly from your bot!")
            print("=" * 68 + "\n")

    except Exception as e:
        print(f"\n[!] Error during login: {e}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n[!] Cancelled by user.")
