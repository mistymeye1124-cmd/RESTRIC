import sys
from pathlib import Path
sys.path.insert(0, '.')
import sqlite3
import asyncio
import time
import os
from pyrogram import Client, raw
from pyrogram.file_id import FileId
from pyrogram.session import Session, Auth
import config

sys.stdout.reconfigure(encoding='utf-8')

async def fast_parallel_download(client: Client, msg, out_path: str, num_workers: int = 6, chunk_size: int = 512 * 1024):
    target = msg.video or msg.document or msg.audio
    if not target:
        raise ValueError("No supported media in message")

    fid = FileId.decode(target.file_id)
    total_size = target.file_size
    dc_id = fid.dc_id
    
    print(f"[*] Fast Turbo Downloader: File Size = {total_size / (1024*1024):.2f} MB, DC = {dc_id}, Workers = {num_workers}, Chunk = {chunk_size//1024} KB")

    # Pre-allocate output file
    with open(out_path, "wb") as f:
        f.seek(total_size - 1)
        f.write(b"\0")

    loc = raw.types.InputDocumentFileLocation(
        id=fid.media_id,
        access_hash=fid.access_hash,
        file_reference=fid.file_reference,
        thumb_size=fid.thumbnail_size
    )

    auth_key = await client.storage.auth_key() if dc_id == await client.storage.dc_id() else await Auth(client, dc_id, await client.storage.test_mode()).create()
    test_mode = await client.storage.test_mode()

    # Create worker sessions
    sessions = []
    for i in range(num_workers):
        s = Session(client, dc_id, auth_key, test_mode, is_media=True)
        await s.start()
        sessions.append(s)

    print(f"[+] All {num_workers} parallel MTProto media sessions connected!")

    # Calculate all chunk offsets
    offsets = list(range(0, total_size, chunk_size))
    total_chunks = len(offsets)
    queue = asyncio.Queue()
    for o in offsets:
        queue.put_nowait(o)

    downloaded_bytes = 0
    t_start = time.time()
    last_print = t_start

    # Thread-safe file writer lock
    file_handle = open(out_path, "r+b")

    async def worker(worker_id: int, session: Session):
        nonlocal downloaded_bytes, last_print
        while not queue.empty():
            try:
                offset = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            limit = min(chunk_size, total_size - offset)
            success = False
            for retry in range(4):
                try:
                    r = await asyncio.wait_for(
                        session.invoke(
                            raw.functions.upload.GetFile(
                                location=loc,
                                offset=offset,
                                limit=limit
                            )
                        ),
                        timeout=12.0
                    )
                    chunk_bytes = r.bytes
                    file_handle.seek(offset)
                    file_handle.write(chunk_bytes)
                    downloaded_bytes += len(chunk_bytes)
                    success = True

                    now = time.time()
                    if now - last_print >= 1.0 or downloaded_bytes >= total_size:
                        speed = downloaded_bytes / (now - t_start)
                        pct = (downloaded_bytes / total_size) * 100
                        eta = (total_size - downloaded_bytes) / speed if speed > 0 else 0
                        print(f"  ⚡ [{pct:.1f}%] {downloaded_bytes/(1024*1024):.2f}/{total_size/(1024*1024):.2f} MB | Speed: {speed/(1024*1024):.2f} MB/s | ETA: {eta:.1f}s")
                        last_print = now
                    break
                except Exception as e:
                    if retry == 3:
                        print(f"[-] Worker {worker_id} failed on offset {offset} after 4 retries: {e}")
                    await asyncio.sleep(0.5)

            if not success:
                # Put back in queue to try with another worker
                await queue.put(offset)
            queue.task_done()

    workers = [asyncio.create_task(worker(i, s)) for i, s in enumerate(sessions)]
    await asyncio.gather(*workers)

    file_handle.close()

    for s in sessions:
        try:
            await s.stop()
        except Exception:
            pass

    duration = time.time() - t_start
    final_speed = (total_size / (1024*1024)) / duration if duration > 0 else 0
    print(f"\n[🚀 TURBO SUCCESS] Downloaded {total_size/(1024*1024):.2f} MB in {duration:.2f}s! Average Speed: {final_speed:.2f} MB/s!")
    return out_path


async def main():
    con = sqlite3.connect('bot_database.db')
    cur = con.cursor()
    cur.execute('SELECT string_session FROM users WHERE user_id = 8965121030')
    row = cur.fetchone()
    con.close()

    async with Client('fast_turbo_client', api_id=config.API_ID, api_hash=config.API_HASH, session_string=row[0], in_memory=True) as c:
        msg = await c.get_messages(-1003344250560, 28)
        out_file = "downloads/turbo_test_video.mp4"
        await fast_parallel_download(c, msg, out_file, num_workers=6, chunk_size=512*1024)

if __name__ == '__main__':
    asyncio.run(main())
