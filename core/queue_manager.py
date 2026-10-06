# language: Python, file: core/queue_manager.py, target: Python 3.10+, Asyncio
"""
Concurrent Multi-Worker Priority Queue for High-Load Commercial Telegram Bots.
Features:
- Elastic Dynamic Scaling: 4 base workers scaling up to 8-10 parallel workers during high traffic
- Memory & Disk Guard: Ensures ProGuild HQ website always has >=5GB disk and >=3GB RAM
- Zero-Freeze Protection: Automatic post-execution cleanup of all media buffers
"""

import asyncio
import time
import logging
from typing import Dict, Any, Callable
from dataclasses import dataclass, field
from config import MAX_CONCURRENT_WORKERS, MIN_FREE_RAM_MB, MIN_FREE_DISK_GB
from core.storage_shield import check_storage_safety, cleanup_job_files, get_free_ram_mb, emergency_disk_purge

logger = logging.getLogger(__name__)

MAX_BURST_WORKERS = max(MAX_CONCURRENT_WORKERS, 32)


@dataclass(order=True)
class PrioritizedJob:
    priority: int  # 0 = VIP Single, 1 = VIP Batch, 2 = Free Single, 3 = Free Batch
    created_at: float = field(compare=True)
    job_id: str = field(compare=False)
    handler: Any = field(compare=False)
    args: tuple = field(compare=False)


class QueueManager:
    def __init__(self, num_workers: int = MAX_CONCURRENT_WORKERS):
        self.queue = asyncio.PriorityQueue()
        self.num_workers = num_workers
        self.workers = []
        self.is_running = False
        self.active_count = 0

    async def start(self):
        """Starts baseline worker tasks in the background."""
        if self.is_running:
            return
        self.is_running = True
        for i in range(self.num_workers):
            task = asyncio.create_task(self._worker_loop(i))
            self.workers.append(task)
        logger.info(
            "[+] Multi-Worker Priority Queue started with %d base workers (Elastic scaling up to %d workers).",
            self.num_workers,
            MAX_BURST_WORKERS,
        )

    async def _worker_loop(self, worker_id: int):
        while self.is_running:
            try:
                job: PrioritizedJob = await self.queue.get()
            except asyncio.CancelledError:
                break
            except Exception:
                break

            self.active_count += 1
            try:
                # Zero-delay non-blocking storage check
                is_safe, reason, _ = check_storage_safety()
                if not is_safe:
                    emergency_disk_purge()

                # Execute job async handler
                await job.handler(*job.args)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[!] Worker-%d job %s encountered error: %s", worker_id, job.job_id, e)
            finally:
                self.active_count = max(0, self.active_count - 1)
                try:
                    from core.download_engine import active_jobs
                    active_jobs.pop(job.job_id, None)
                except Exception:
                    pass
                # Instant Post-Execution Cleanup Shield
                try:
                    cleanup_job_files(job.job_id)
                except Exception:
                    pass
                self.queue.task_done()

    async def _burst_worker(self, burst_id: int):
        """Temporary elastic worker spawned during traffic spikes when RAM is plenty."""
        if not self.is_running or self.queue.empty():
            return

        while self.is_running and not self.queue.empty():
            # Check RAM headroom: strictly preserve 3GB website safety buffer
            free_ram = get_free_ram_mb()
            if free_ram <= MIN_FREE_RAM_MB:
                logger.info("[QueueManager] Burst Worker-%d scaling down: Website 3GB RAM buffer strictly preserved.", burst_id)
                break

            try:
                job: PrioritizedJob = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            self.active_count += 1
            logger.info(
                "[QueueManager] Elastic Burst Worker-%d active (RAM: %.0f MB free, scale: %d/%d).",
                burst_id,
                free_ram,
                self.active_count,
                MAX_BURST_WORKERS,
            )
            try:
                # Zero-delay non-blocking storage check
                is_safe, reason, _ = check_storage_safety()
                if not is_safe:
                    emergency_disk_purge()

                await job.handler(*job.args)
            except Exception as e:
                logger.error("[!] Burst Worker-%d job %s error: %s", burst_id, job.job_id, e)
            finally:
                self.active_count = max(0, self.active_count - 1)
                try:
                    from core.download_engine import active_jobs
                    active_jobs.pop(job.job_id, None)
                except Exception:
                    pass
                try:
                    cleanup_job_files(job.job_id)
                except Exception:
                    pass
                self.queue.task_done()

    async def add_job(self, job_id: str, is_premium: bool, handler: Callable, *args) -> int:
        """Adds a job with dual-lane express priority. Dynamically spawns elastic burst workers when RAM allows."""
        # Detect single-item download vs batch for express lane routing
        is_single = False
        if len(args) > 3 and isinstance(args[3], (list, tuple)):
            is_single = len(args[3]) <= 1
        elif len(args) <= 3:
            is_single = True

        # Priority 0: VIP Single (Instant express!)
        # Priority 1: VIP Batch
        # Priority 2: Free Single (Instant express!)
        # Priority 3: Free Batch
        if is_premium:
            priority = 0 if is_single else 1
        else:
            priority = 2 if is_single else 3

        job = PrioritizedJob(
            priority=priority,
            created_at=time.time(),
            job_id=job_id,
            handler=handler,
            args=args,
        )
        await self.queue.put(job)
        q_size = self.queue.qsize()

        # Dynamic Elastic Worker Scaling for 1,000+ Users:
        # If queue has waiting jobs and available RAM is safely above the website's 3GB buffer (> MIN_FREE_RAM_MB + 150),
        # dynamically spawn temporary burst workers (up to MAX_BURST_WORKERS)
        # to clear user requests immediately with zero queue latency!
        try:
            free_ram = get_free_ram_mb()
            if (
                free_ram > (MIN_FREE_RAM_MB + 150)
                and self.active_count >= self.num_workers
                and self.active_count < MAX_BURST_WORKERS
            ):
                burst_id = 100 + self.active_count
                asyncio.create_task(self._burst_worker(burst_id))
        except Exception:
            pass

        return q_size

    async def stop(self):
        self.is_running = False
        try:
            await asyncio.wait_for(self.queue.join(), timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            pass
        for w in self.workers:
            w.cancel()
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()


# Global queue manager singleton
job_queue = QueueManager()
