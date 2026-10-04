# language: Python, file: core/storage_shield.py, target: Python 3.10+
"""
Automated Storage & Memory Shield Engine:
1. Instant Post-Delivery Media Purger (Deletes files in milliseconds after Telegram delivery).
2. ProGuild HQ Website Protection Gate (Enforces 5GB minimum free disk & RAM buffer).
3. 24/7 Automated Background Scavenger Daemon (Wipes orphan/temporary files every 30s).
"""

import os
import gc
import time
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple

from config import (
    TEMP_DOWNLOAD_DIR,
    MIN_FREE_DISK_GB,
    MIN_FREE_RAM_MB,
    AUTO_CLEAN_FILE_MAX_AGE_SEC,
)

logger = logging.getLogger(__name__)


def cleanup_job_files(job_id: str, primary_file: Optional[str] = None) -> int:
    """
    Instantly and thoroughly removes all disk files associated with job_id.
    Deletes the primary file, parts, thumbnails, scaled/ghost copies, and .temp files.
    Returns the number of files deleted.
    """
    deleted_count = 0
    cleaned_paths = set()

    # 1. Delete primary file if explicitly specified
    if primary_file:
        try:
            if os.path.exists(primary_file):
                os.remove(primary_file)
                cleaned_paths.add(os.path.abspath(primary_file))
                deleted_count += 1
        except Exception as e:
            logger.debug("[StorageShield] Failed to remove primary file %s: %e", primary_file, e)

    # 2. Sweep TEMP_DOWNLOAD_DIR for any file containing job_id
    try:
        download_path = Path(TEMP_DOWNLOAD_DIR)
        if download_path.exists():
            for item in download_path.glob(f"*{job_id}*"):
                try:
                    abs_p = str(item.resolve())
                    if abs_p not in cleaned_paths and item.is_file():
                        item.unlink(missing_ok=True)
                        cleaned_paths.add(abs_p)
                        deleted_count += 1
                except Exception:
                    pass
    except Exception as e:
        logger.debug("[StorageShield] Glob cleanup error for job %s: %e", job_id, e)

    # 3. Check /tmp for any temporary ffmpeg / web / python artifacts for this job
    try:
        tmp_dir = Path("/tmp")
        if tmp_dir.exists():
            for item in tmp_dir.glob(f"*{job_id}*"):
                try:
                    if item.is_file():
                        item.unlink(missing_ok=True)
                        deleted_count += 1
                except Exception:
                    pass
    except Exception:
        pass

    # 4. Immediate Garbage Collection to free RAM buffers
    gc.collect()

    if deleted_count > 0:
        logger.info("[StorageShield] Instantly purged %d file(s) for delivered job [%s]", deleted_count, job_id)

    return deleted_count


def get_free_disk_gb() -> float:
    """Returns available free disk space in Gigabytes."""
    try:
        target = str(TEMP_DOWNLOAD_DIR) if os.path.exists(TEMP_DOWNLOAD_DIR) else "/"
        total, used, free = shutil.disk_usage(target)
        return free / (1024 ** 3)
    except Exception:
        return 999.0


def get_free_ram_mb() -> float:
    """Returns available free RAM in Megabytes."""
    try:
        # Linux /proc/meminfo parsing
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        return int(parts[1]) / 1024  # kB to MB
        # Fallback if psutil is available
        import psutil
        return psutil.virtual_memory().available / (1024 ** 2)
    except Exception:
        return 9999.0


def emergency_disk_purge() -> int:
    """
    Emergency disk cleaner: Wipes all orphaned, dangling, or temporary files
    in TEMP_DOWNLOAD_DIR that do not belong to an active running job.
    """
    purged = 0
    from core.download_engine import active_jobs

    active_job_ids = set(active_jobs.keys())

    try:
        download_path = Path(TEMP_DOWNLOAD_DIR)
        if download_path.exists():
            now = time.time()
            for item in download_path.iterdir():
                if not item.is_file():
                    continue

                fname = item.name
                # Check if this file belongs to an active job
                is_active = any(jid in fname for jid in active_job_ids)

                # If not active or older than 5 minutes, purge immediately
                file_age = now - item.stat().st_mtime
                if not is_active or file_age > 300:
                    try:
                        item.unlink(missing_ok=True)
                        purged += 1
                    except Exception:
                        pass
    except Exception as e:
        logger.error("[StorageShield] Emergency purge error: %s", e)

    gc.collect()
    return purged


def check_storage_safety() -> Tuple[bool, str, float]:
    """
    Evaluates whether the system has safe disk and RAM headroom
    to accept and process a new media download.
    Protects both the VPS OS and the co-hosted ProGuild HQ website.
    Returns: (is_safe, reason, free_metric)
    """
    free_disk = get_free_disk_gb()
    if free_disk < MIN_FREE_DISK_GB:
        # Attempt emergency purge first
        emergency_disk_purge()
        free_disk = get_free_disk_gb()
        if free_disk < MIN_FREE_DISK_GB:
            return False, f"Disk space low ({free_disk:.1f} GB free, minimum {MIN_FREE_DISK_GB} GB required for website safety)", free_disk

    free_ram = get_free_ram_mb()
    if free_ram < MIN_FREE_RAM_MB:
        gc.collect()
        free_ram = get_free_ram_mb()
        if free_ram < MIN_FREE_RAM_MB:
            return False, f"RAM low ({free_ram:.0f} MB available, minimum {MIN_FREE_RAM_MB} MB required)", free_ram

    return True, "Storage and memory healthy", free_disk


async def start_storage_scavenger_daemon(interval_sec: int = 30):
    """
    24/7 Background daemon that runs every 30 seconds.
    Ensures 0 residual video files linger on the VPS after delivery.
    """
    logger.info("[StorageShield] 24/7 Disk Scavenger Daemon launched (Scan interval: %ds).", interval_sec)
    
    while True:
        try:
            await asyncio.sleep(interval_sec)
            from core.download_engine import active_jobs
            active_ids = set(active_jobs.keys())

            download_path = Path(TEMP_DOWNLOAD_DIR)
            if not download_path.exists():
                continue

            now = time.time()
            deleted = 0
            reclaimed_bytes = 0

            for item in download_path.iterdir():
                if not item.is_file():
                    continue

                fname = item.name
                stat = item.stat()
                file_age = now - stat.st_mtime

                # Determine if actively associated with a job
                is_active = any(jid in fname for jid in active_ids)

                # Delete if:
                # 1. Not in active jobs and age > 60 seconds
                # 2. Or file age > AUTO_CLEAN_FILE_MAX_AGE_SEC (120 seconds)
                # 3. Or ends in .temp / .part and age > 90 seconds
                should_delete = False
                if not is_active and file_age > 60:
                    should_delete = True
                elif file_age > AUTO_CLEAN_FILE_MAX_AGE_SEC:
                    should_delete = True
                elif fname.endswith((".temp", ".part", "_delogo", "_wm")) and file_age > 90:
                    should_delete = True

                if should_delete:
                    sz = stat.st_size
                    try:
                        item.unlink(missing_ok=True)
                        deleted += 1
                        reclaimed_bytes += sz
                    except Exception:
                        pass

            if deleted > 0:
                mb_reclaimed = reclaimed_bytes / (1024 * 1024)
                logger.info(
                    "[StorageShield] Auto-scavenged %d orphan/expired file(s) — Reclaimed %.1f MB disk space.",
                    deleted, mb_reclaimed
                )

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("[StorageShield] Scavenger loop tick error: %s", e)
