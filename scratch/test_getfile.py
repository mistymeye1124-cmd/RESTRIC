import sys
from pathlib import Path
sys.path.insert(0, '.')
import sqlite3
import asyncio
from pyrogram import Client, raw
from pyrogram.file_id import FileId
from pyrogram.session import Session
import config

async def check():
    con = sqlite3.connect('bot_database.db')
    cur = con.cursor()
    cur.execute('SELECT string_session FROM users WHERE user_id = 8965121030')
    row = cur.fetchone()
    con.close()
    async with Client('check_media_session_2', api_id=config.API_ID, api_hash=config.API_HASH, session_string=row[0], in_memory=True) as c:
        msg = await c.get_messages(-1003344250560, 28)
        fid = FileId.decode(msg.video.file_id)
        print('[+] Got fresh message and file_id!')
        
        session = Session(c, fid.dc_id, await c.storage.auth_key(), await c.storage.test_mode(), is_media=True)
        await session.start()
        print('[+] Media session started')

        loc = raw.types.InputDocumentFileLocation(
            id=fid.media_id,
            access_hash=fid.access_hash,
            file_reference=fid.file_reference,
            thumb_size=fid.thumbnail_size
        )

        for chunk_size in [128 * 1024, 256 * 1024, 512 * 1024, 1024 * 1024]:
            print(f'[*] Testing chunk_size = {chunk_size // 1024} KB...')
            try:
                t0 = asyncio.get_event_loop().time()
                r = await asyncio.wait_for(
                    session.invoke(raw.functions.upload.GetFile(location=loc, offset=0, limit=chunk_size)),
                    timeout=10.0
                )
                dt = asyncio.get_event_loop().time() - t0
                print(f'    [SUCCESS] chunk_size {chunk_size//1024} KB returned {len(r.bytes)} bytes in {dt:.2f}s!')
                break
            except Exception as e:
                print(f'    [FAILED] {type(e).__name__}: {e}')

        await session.stop()

if __name__ == '__main__':
    asyncio.run(check())
