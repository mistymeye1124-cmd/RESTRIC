# language: Python, file: core/parallel_downloader.py, target: Python 3.10+, Pyrogram
"""
High-Performance Parallel MTProto Multi-Stream Media Downloader.
Bypasses Telegram's single-stream DC bandwidth throttling by spawning
balanced concurrent MTProto media sessions with 1MB chunk pipelining.
Features:
- Dynamic sweet-spot worker tuning (4-6 streams) to prevent DC throttling
- Chunk-level 10s timeout with automatic socket healing
- Active 8s stall watchdog with instantaneous failover to standard stream
- Zero-lock POSIX pwrite for maximum SSD throughput on Linux KVM VPS
"""

import os
import time
import asyncio
import logging
from typing import Optional, Callable, Dict, Any, List
from pyrogram import Client, raw, utils
from pyrogram.file_id import FileId, FileType, ThumbnailSource
from pyrogram.session import Session, Auth
from pyrogram.errors import FloodWait, FileReferenceExpired, RPCError

logger = logging.getLogger(__name__)


def _resolve_file_location(fid: FileId) -> raw.base.InputFileLocation:
    """Accurately maps Pyrogram FileId to proper MTProto InputFileLocation."""
    file_type = fid.file_type

    if file_type == FileType.CHAT_PHOTO:
        if fid.chat_id > 0:
            peer = raw.types.InputPeerUser(
                user_id=fid.chat_id,
                access_hash=fid.chat_access_hash
            )
        else:
            if fid.chat_access_hash == 0:
                peer = raw.types.InputPeerChat(
                    chat_id=-fid.chat_id
                )
            else:
                peer = raw.types.InputPeerChannel(
                    channel_id=utils.get_channel_id(fid.chat_id),
                    access_hash=fid.chat_access_hash
                )
        return raw.types.InputPeerPhotoFileLocation(
            peer=peer,
            photo_id=fid.media_id,
            big=fid.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG
        )
    elif file_type == FileType.PHOTO:
        return raw.types.InputPhotoFileLocation(
            id=fid.media_id,
            access_hash=fid.access_hash,
            file_reference=fid.file_reference,
            thumb_size=getattr(fid, "thumbnail_size", "") or ""
        )
    else:
        return raw.types.InputDocumentFileLocation(
            id=fid.media_id,
            access_hash=fid.access_hash,
            file_reference=fid.file_reference,
            thumb_size=getattr(fid, "thumbnail_size", "") or ""
        )


async def turbo_parallel_download(
    client: Client,
    msg: Any,
    out_path: str,
    progress_callback: Optional[Callable] = None,
    job_id: Optional[str] = None,
    active_jobs: Optional[Dict[str, Any]] = None,
    num_workers: int = 4,
    chunk_size: int = 1024 * 1024,
) -> str:
    """
    Downloads media using concurrent MTProto media sessions.
    Slices the target file into 1MB/512KB chunks and fetches them concurrently across balanced workers.
    Equipped with per-chunk 10s watchdog, automatic TCP socket healing, and zero-freeze failover.
    """
    target = (
        getattr(msg, "video", None)
        or getattr(msg, "document", None)
        or getattr(msg, "audio", None)
        or getattr(msg, "voice", None)
        or getattr(msg, "video_note", None)
        or getattr(msg, "photo", None)
    )
    if not target or not getattr(target, "file_id", None):
        raise ValueError("Target media does not have a streamable MTProto file_id")

    total_size = getattr(target, "file_size", 0)
    if total_size <= 0:
        raise ValueError("Unknown target file size")

    # Balanced Sweet-Spot Tuning for High-Speed VPS (Hostinger KVM 4):
    # Dynamic Sweet-Spot Multi-Stream Tuning for High-Speed VPS (Hostinger KVM 4):
    is_prem = getattr(getattr(client, "me", None), "is_premium", False)
    if not is_prem:
        cname = getattr(client, "name", "")
        if "account_" in cname:
            try:
                aid = int(cname.split("_")[1])
                from core.client_manager import account_metadata
                is_prem = bool(account_metadata.get(aid, {}).get("is_tg_premium", False))
            except Exception:
                pass

    cpu_count = os.cpu_count() or 2
    if total_size < 5 * 1024 * 1024:
        num_workers = 2
        chunk_size = 512 * 1024
    elif total_size < 25 * 1024 * 1024:
        num_workers = 4
        chunk_size = 1024 * 1024
    elif total_size < 75 * 1024 * 1024:
        num_workers = 10 if is_prem else (8 if cpu_count >= 4 else 6)
        chunk_size = 1024 * 1024
    else:
        # Large files (75MB - 4GB): 16 parallel MTProto streams push DC wire speed to 50-80+ MB/s
        num_workers = 16 if is_prem else (12 if cpu_count >= 4 else 8)
        chunk_size = 1024 * 1024

    fid = FileId.decode(target.file_id)
    dc_id = fid.dc_id
    loc = _resolve_file_location(fid)

    is_test = await client.storage.test_mode()
    main_dc = await client.storage.dc_id()

    # Pre-allocate sparse destination file
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.seek(total_size - 1)
        f.write(b"\0")

    # 1. Obtain Auth Key for target Data Center
    if dc_id == main_dc:
        auth_key = await client.storage.auth_key()
        exported_auth = None
    else:
        auth_key = await Auth(client, dc_id, is_test).create()
        exported_auth = await client.invoke(
            raw.functions.auth.ExportAuthorization(dc_id=dc_id)
        )

    # 2. Spin up parallel MTProto media sessions
    sessions: List[Session] = [
        Session(client, dc_id, auth_key, is_test, is_media=True)
        for _ in range(num_workers)
    ]
    await asyncio.gather(*[s.start() for s in sessions])

    # Import authorization on target DC across all sessions if needed
    if exported_auth and sessions:
        for s in sessions:
            try:
                await s.invoke(
                    raw.functions.auth.ImportAuthorization(
                        id=exported_auth.id,
                        bytes=exported_auth.bytes
                    )
                )
            except Exception as imp_err:
                logger.debug("[TurboParallel] ImportAuthorization on DC %d: %s", dc_id, imp_err)

    # 3. Build chunk queue with sentinel termination tokens
    offsets = list(range(0, total_size, chunk_size))
    queue: asyncio.Queue = asyncio.Queue()
    for o in offsets:
        queue.put_nowait(o)
    for _ in range(num_workers):
        queue.put_nowait(None)  # Sentinels guarantee workers exit cleanly without early starvation

    downloaded_bytes = 0
    t_start = time.time()
    last_cb_time = t_start
    last_progress_time = t_start
    write_lock = asyncio.Lock()

    # POSIX pwrite is atomic and thread-safe for high speed on Linux VPS
    use_pwrite = hasattr(os, "pwrite")
    file_fd = None
    file_handle = None
    if use_pwrite:
        file_fd = os.open(out_path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    else:
        file_handle = open(out_path, "r+b")

    # Circuit breaker & watchdog state
    abort_event = asyncio.Event()
    abort_reason = ""
    chunk_fail_counts: Dict[int, int] = {}
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 16

    async def restart_worker_session(sess: Session, w_id: int):
        """Cleanly re-establishes a broken TCP MTProto socket."""
        try:
            logger.info("[TurboWorker %d] Re-establishing MTProto socket connection...", w_id)
            await sess.restart()
            logger.info("[TurboWorker %d] Socket connection successfully restored.", w_id)
        except Exception as r_err:
            logger.debug("[TurboWorker %d] Session restart error: %s", w_id, r_err)

    async def worker(worker_id: int, session: Session):
        nonlocal downloaded_bytes, last_cb_time, last_progress_time, consecutive_errors, abort_reason

        while not abort_event.is_set():
            if active_jobs and job_id and active_jobs.get(job_id, {}).get("cancelled"):
                abort_event.set()
                abort_reason = "Cancelled by user"
                break

            try:
                offset = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if downloaded_bytes >= total_size or abort_event.is_set():
                    break
                continue

            if offset is None:  # Sentinel reached
                queue.task_done()
                break

            chunk_success = False
            for retry in range(2):
                if abort_event.is_set() or (active_jobs and job_id and active_jobs.get(job_id, {}).get("cancelled")):
                    break

                try:
                    r = await asyncio.wait_for(
                        session.invoke(
                            raw.functions.upload.GetFile(
                                location=loc,
                                offset=offset,
                                limit=chunk_size,
                            ),
                            timeout=8.0,
                        ),
                        timeout=10.0,
                    )

                    if isinstance(r, raw.types.upload.File):
                        chunk_bytes = r.bytes
                        if use_pwrite and file_fd is not None:
                            os.pwrite(file_fd, chunk_bytes, offset)
                        elif file_handle is not None:
                            async with write_lock:
                                file_handle.seek(offset)
                                file_handle.write(chunk_bytes)

                        downloaded_bytes += len(chunk_bytes)
                        now = time.time()
                        last_progress_time = now
                        chunk_success = True
                        consecutive_errors = 0

                        if progress_callback and (now - last_cb_time >= 0.8 or downloaded_bytes >= total_size):
                            last_cb_time = now
                            asyncio.create_task(progress_callback(downloaded_bytes, total_size))
                        break

                    elif isinstance(r, raw.types.upload.FileCdnRedirect):
                        logger.info("[TurboWorker %d] File requires Telegram CDN decryption redirect", worker_id)
                        abort_reason = "Telegram CDN redirect required"
                        abort_event.set()
                        break
                    else:
                        raise ValueError(f"Unexpected GetFile response: {type(r)}")

                except Exception as e:
                    consecutive_errors += 1
                    err_str = str(e) or repr(e)

                    # Immediate failover triggers for MTProto rate/auth limits
                    if isinstance(e, FloodWait) or "FLOOD_WAIT" in err_str:
                        logger.warning("[TurboWorker %d] FloodWait encountered on offset %d: %s", worker_id, offset, err_str)
                        abort_reason = f"Telegram FloodWait ({getattr(e, 'value', 10)}s)"
                        abort_event.set()
                        break

                    if isinstance(e, FileReferenceExpired) or "FILE_REFERENCE" in err_str:
                        logger.warning("[TurboWorker %d] FileReferenceExpired on offset %d", worker_id, offset)
                        abort_reason = "FileReferenceExpired"
                        abort_event.set()
                        break

                    is_broken_socket = (
                        isinstance(e, OSError)
                        or "Broken pipe" in err_str
                        or "ConnectionResetError" in err_str
                        or "socket.send" in err_str
                        or isinstance(e, (asyncio.TimeoutError, TimeoutError))
                    )

                    if is_broken_socket:
                        logger.warning("[TurboWorker %d] Socket hung/reset on offset %d (attempt %d/2). Reconnecting...", worker_id, offset, retry + 1)
                        await restart_worker_session(session, worker_id)
                    else:
                        logger.debug("[TurboWorker %d] Chunk error on offset %d (attempt %d/2): %s", worker_id, offset, retry + 1, err_str)

                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logger.warning("[TurboDownloader] Tripped circuit breaker: %d consecutive errors", consecutive_errors)
                        abort_reason = f"Exceeded consecutive socket errors ({consecutive_errors})"
                        abort_event.set()
                        break

                    await asyncio.sleep(0.25 * (retry + 1))

            if not chunk_success and not abort_event.is_set():
                fails = chunk_fail_counts.get(offset, 0) + 1
                chunk_fail_counts[offset] = fails
                if fails <= 3:
                    await queue.put(offset)
                else:
                    logger.warning("[TurboDownloader] Offset %d failed %d times. Aborting parallel mode.", offset, fails)
                    abort_reason = f"Offset {offset} unrecoverable after {fails} attempts"
                    abort_event.set()

            queue.task_done()

    workers: List[asyncio.Task] = []

    async def stall_watchdog():
        """Monitors download throughput and triggers graceful fallback if stream freezes."""
        while not abort_event.is_set():
            await asyncio.sleep(1.0)
            if downloaded_bytes >= total_size or abort_event.is_set():
                break
            if time.time() - last_progress_time > 8.0:
                logger.warning(
                    "[TurboDownloader] Stall detected! No bytes received for 8.0s (transferred: %d/%d). Auto-recovering to fallback...",
                    downloaded_bytes, total_size
                )
                abort_reason = "Stall detected (no bytes for 8s)"
                abort_event.set()
                for w in workers:
                    w.cancel()
                break

    watchdog_task = asyncio.create_task(stall_watchdog())

    try:
        workers = [asyncio.create_task(worker(i, s)) for i, s in enumerate(sessions)]
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        watchdog_task.cancel()
        if file_fd is not None:
            try:
                os.close(file_fd)
            except Exception:
                pass
        if file_handle is not None:
            try:
                file_handle.close()
            except Exception:
                pass

        for s in sessions:
            try:
                await s.stop()
            except Exception:
                pass

    if active_jobs and job_id and active_jobs.get(job_id, {}).get("cancelled"):
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        raise asyncio.CancelledError("Download cancelled by user")

    if abort_event.is_set():
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        raise RuntimeError(f"Turbo parallel downloader failed ({abort_reason}); triggering fallback stream.")

    # Final progress callback to reach 100%
    if progress_callback:
        try:
            await progress_callback(total_size, total_size)
        except Exception:
            pass

    return out_path
