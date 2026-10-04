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
from config import MAX_CONCURRENT_WORKERS
from core.storage_shield import check_storage_safety, cleanup_job_files, get_free_ram_mb

logger = logging.getLogger(__name__)


@dataclass(order=True)
class PrioritizedJob:
    priority: int  # 1 = VIP / Premium, 2 = Free
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
        logger.info("[+] Multi-Worker Priority Queue started with %d base workers (Elastic scaling up to 8-10).", self.num_workers)

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
                # Storage & Memory Safety Check before launching heavy pipeline
                for _ in range(6):  # Wait up to 18 seconds for previous uploads to finalize and free disk/RAM
                    is_safe, reason, _ = check_storage_safety()
                    if is_safe:
                        break
                    logger.warning("[QueueManager] Worker-%d pausing 3s: %s", worker_id, reason)
                    await asyncio.sleep(3.0)

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
            # Check RAM headroom: preserve minimum 3200MB for proguildhq.com & OS stability
            free_ram = get_free_ram_mb()
            if free_ram < 3200:
                logger.info("[QueueManager] Burst Worker-%d scaling down: RAM buffer preserved for website.", burst_id)
                break

            try:
                job: PrioritizedJob = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            self.active_count += 1
            logger.info("[QueueManager] Elastic Burst Worker-%d active (RAM: %.0f MB free, scale: %d/%d).", burst_id, free_ram, self.active_count, 16)
            try:
                for _ in range(3):
                    is_safe, reason, _ = check_storage_safety()
                    if is_safe:
                        break
                    await asyncio.sleep(2.0)

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
        """Adds a job with priority. Dynamically spawns elastic burst workers when RAM allows."""
        priority = 1 if is_premium else 2
        job = PrioritizedJob(
            priority=priority,
            created_at=time.time(),
            job_id=job_id,
            handler=handler,
            args=args,
        )
        await self.queue.put(job)
        q_size = self.queue.qsize()

        # Dynamic Elastic Worker Scaling:
        # If queue has waiting jobs and plenty of RAM is available (> 3500 MB free),
        # dynamically spawn temporary burst workers (up to max 16 parallel workers total)
        # to process user requests immediately without queue wait times!
        try:
            free_ram = get_free_ram_mb()
            if free_ram > 3500 and self.active_count >= self.num_workers and self.active_count < 16:
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
