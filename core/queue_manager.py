# language: Python, file: core/queue_manager.py, target: Python 3.10+, Asyncio
"""
Concurrent Multi-Worker Priority Queue for High-Load Commercial Telegram Bots.
Ensures VIP Premium users get prioritized bandwidth and downloads execute without server choking.
"""

import asyncio
import time
from typing import Dict, Any, Callable
from dataclasses import dataclass, field
from config import MAX_CONCURRENT_WORKERS


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

    async def start(self):
        """Starts worker tasks in the background."""
        if self.is_running:
            return
        self.is_running = True
        for i in range(self.num_workers):
            task = asyncio.create_task(self._worker_loop(i))
            self.workers.append(task)
        print(f"[+] Multi-Worker Priority Queue started with {self.num_workers} parallel workers.")

    async def _worker_loop(self, worker_id: int):
        while self.is_running:
            try:
                job: PrioritizedJob = await self.queue.get()
            except asyncio.CancelledError:
                break
            except Exception:
                break

            try:
                # Execute job async handler
                await job.handler(*job.args)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[!] Worker-{worker_id} job {job.job_id} encountered error: {e}")
            finally:
                try:
                    from core.download_engine import active_jobs
                    active_jobs.pop(job.job_id, None)
                except Exception:
                    pass
                self.queue.task_done()

    async def add_job(self, job_id: str, is_premium: bool, handler: Callable, *args):
        """Adds a job with priority (Priority 1 for VIP, Priority 2 for Free)."""
        priority = 1 if is_premium else 2
        job = PrioritizedJob(
            priority=priority,
            created_at=time.time(),
            job_id=job_id,
            handler=handler,
            args=args,
        )
        await self.queue.put(job)
        return self.queue.qsize()

    async def stop(self):
        self.is_running = False
        # Give in-flight jobs up to 3s to finish before hard cancel
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
