import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import asyncio
import time
import sqlite3
from pyrogram import Client
from pyrogram.errors import RPCError
import config

sys.stdout.reconfigure(encoding='utf-8')

async def main():
    con = sqlite3.connect('bot_database.db')
    cur = con.cursor()
    cur.execute('SELECT string_session FROM users WHERE user_id = 8965121030')
    row = cur.fetchone()
    con.close()
    if not row or not row[0]:
        print("No session for user 8965121030")
        return

    session_str = row[0]
    print(f"[*] Found session string (length {len(session_str)})")

    client = Client(
        name="debug_user_client",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=session_str,
        in_memory=True,
    )

    t0 = time.time()
    print("[*] Connecting user client...")
    async with client:
        t_conn = time.time()
        print(f"[+] Connected in {t_conn - t0:.2f}s")
        me = await client.get_me()
        print(f"[+] Logged in as: {me.first_name} (@{me.username}) ID: {me.id}")

        chan_id = -1003344250560
        msg_id = 28
        print(f"[*] Attempting to fetch message {msg_id} from {chan_id}...")

        t1 = time.time()
        try:
            msg = await client.get_messages(chat_id=chan_id, message_ids=msg_id)
            print(f"[+] get_messages returned in {time.time() - t1:.2f}s: media={msg.media}")
            if msg.video:
                print(f"[+] Video file_name: {msg.video.file_name}, size: {msg.video.file_size / (1024*1024):.2f} MB")
            elif msg.document:
                print(f"[+] Document file_name: {msg.document.file_name}, size: {msg.document.file_size / (1024*1024):.2f} MB")
        except Exception as e:
            print(f"[-] get_messages failed: {type(e).__name__}: {e}")
            return

        print("[*] Starting test download...")
        t2 = time.time()
        last_t = t2
        last_b = 0

        async def prog(current, total):
            nonlocal last_t, last_b
            now = time.time()
            if now - last_t >= 1.0 or current == total:
                spd = (current - last_b) / (now - last_t) if (now - last_t) > 0 else 0
                pct = current / total * 100 if total else 0
                print(f"  • Progress: {pct:.1f}% ({current/(1024*1024):.2f}/{total/(1024*1024):.2f} MB) - Speed: {spd/(1024*1024):.2f} MB/s")
                last_t = now
                last_b = current

        try:
            target_path = Path("downloads") / "debug_test.mp4"
            dl_file = await asyncio.wait_for(
                client.download_media(message=msg, file_name=str(target_path), progress=prog),
                timeout=45.0
            )
            print(f"[+] Download complete: {dl_file} in {time.time() - t2:.2f}s")
        except asyncio.TimeoutError:
            print(f"[-] Download TIMED OUT after 45s!")
        except Exception as e:
            print(f"[-] Download failed: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
