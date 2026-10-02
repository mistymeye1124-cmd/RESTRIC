import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pyrogram
import config

async def check():
    app = pyrogram.Client(
        "test_ping",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        in_memory=True
    )
    try:
        await app.start()
        me = await app.get_me()
        print(f"SUCCESS: Bot Connected as @{me.username} (ID: {me.id}, Name: {me.first_name})")
        await app.stop()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(check())
