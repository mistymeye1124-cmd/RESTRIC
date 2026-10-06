# language: Python, file: core/rate_limiter.py, target: Python 3.10+, asyncio
"""
Per-Session Async Rate Limiter with Jitter.
Enforces a maximum request rate per userbot session to mimic human pacing.
Exponential back-off on FLOOD_WAIT / PEER_FLOOD / SESSION errors.
Session health tracking — auto-quarantines dead or flood-locked sessions.
"""

import asyncio
import time
import random
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SessionRateLimiter:
    """
    Per-session leaky bucket rate limiter with exponential flood backoff,
    per-session download counter, and human-pacing auto-rest.
    """

    # Minimum gap between successive API calls from the same session (seconds)
    # Tuned: 0.35s is human-paced enough to avoid bans, but 2.5x faster throughput
    MIN_INTERVAL: float = 0.35

    # Maximum extra random jitter added on top of MIN_INTERVAL
    JITTER_MAX: float = 0.2

    # After QUARANTINE_THRESHOLD PEER_FLOODs, session is quarantined for QUARANTINE_SECONDS
    QUARANTINE_THRESHOLD: int = 3
    QUARANTINE_SECONDS: int = 900      # 15 minutes

    # Per-session download counter limits
    CONSECUTIVE_DOWNLOAD_REST_AFTER: int = 150   # high threshold for high-volume commercial throughput
    CONSECUTIVE_DOWNLOAD_REST_SECONDS: float = 0.5  # brief 0.5s sub-second breather
    MAX_DAILY_DOWNLOADS: int = 10000     # high ceiling for enterprise throughput

    def __init__(self, session_key: str):
        self.session_key = session_key
        self._last_call_at: float = 0.0

        # Health tracking
        self._peer_flood_count: int = 0
        self._quarantined_until: float = 0.0
        self._total_requests: int = 0
        self._total_flood_waits: int = 0
        self._flood_backoff_multiplier: float = 1.0  # exponential backoff multiplier

        # Download pacing
        self._consecutive_downloads: int = 0
        self._daily_downloads: int = 0
        self._daily_reset_date: str = ""

    @property
    def is_quarantined(self) -> bool:
        return time.monotonic() < self._quarantined_until

    @property
    def quarantine_remaining(self) -> float:
        remaining = self._quarantined_until - time.monotonic()
        return max(0.0, remaining)

    async def wait(self):
        """
        Awaits the minimum interval + jitter before allowing the next request.
        Blocks if the session is quarantined.
        """
        # Block if quarantined
        if self.is_quarantined:
            wait_sec = self.quarantine_remaining
            logger.warning(
                "[RateLimit] Session %s quarantined — waiting %.0fs",
                self.session_key, wait_sec
            )
            await asyncio.sleep(wait_sec)

        now = time.monotonic()
        elapsed = now - self._last_call_at
        jitter = random.uniform(0.02, 0.08)  # minimal jitter — looks human, stays fast
        required = self.MIN_INTERVAL + jitter

        if elapsed < required:
            sleep_for = required - elapsed
            await asyncio.sleep(sleep_for)

        self._last_call_at = time.monotonic()
        self._total_requests += 1

    async def on_download_start(self):
        """
        Called before each download_media call.
        Enforces clean pacing without multi-second or minute-long delays.
        """
        import datetime
        today = datetime.date.today().isoformat()
        if today != self._daily_reset_date:
            self._daily_downloads = 0
            self._daily_reset_date = today
            self._consecutive_downloads = 0

        # Daily threshold counter reset without blocking worker
        if self._daily_downloads >= self.MAX_DAILY_DOWNLOADS:
            self._daily_downloads = 0

        # Human-pacing: brief 0.5s breather only after 150 consecutive downloads
        self._consecutive_downloads += 1
        self._daily_downloads += 1

        if self._consecutive_downloads >= self.CONSECUTIVE_DOWNLOAD_REST_AFTER:
            await asyncio.sleep(self.CONSECUTIVE_DOWNLOAD_REST_SECONDS)
            self._consecutive_downloads = 0

    def on_flood_wait(self, seconds: int):
        """
        Called when Telegram returns a FLOOD_WAIT error.
        Applies exponential backoff multiplier — each successive flood waits longer.
        """
        self._total_flood_waits += 1
        # Exponential backoff: each flood wait compounds (1x → 1.5x → 2.25x → max 4x)
        effective_wait = min(int(seconds * self._flood_backoff_multiplier), seconds * 4)
        self._quarantined_until = time.monotonic() + effective_wait
        self._flood_backoff_multiplier = min(self._flood_backoff_multiplier * 1.5, 4.0)
        logger.warning(
            "[RateLimit] Session %s got FLOOD_WAIT %ds → effective %.0fs (backoff x%.1f, total: %d)",
            self.session_key, seconds, effective_wait, self._flood_backoff_multiplier, self._total_flood_waits
        )

    def on_peer_flood(self):
        """
        Called when Telegram returns a PEER_FLOOD error.
        Increments counter; quarantines session after threshold.
        """
        self._peer_flood_count += 1
        if self._peer_flood_count >= self.QUARANTINE_THRESHOLD:
            self._quarantined_until = time.monotonic() + self.QUARANTINE_SECONDS
            logger.error(
                "[RateLimit] Session %s QUARANTINED for %.0f minutes after %d PEER_FLOODs",
                self.session_key,
                self.QUARANTINE_SECONDS / 60,
                self._peer_flood_count,
            )
            self._peer_flood_count = 0   # reset counter after quarantine
        else:
            # Short back-off even before quarantine threshold
            self._last_call_at = time.monotonic() + 60
            logger.warning(
                "[RateLimit] Session %s PEER_FLOOD #%d — 60s back-off",
                self.session_key, self._peer_flood_count
            )

    def on_success(self):
        """Reset peer flood counter and backoff on a clean request."""
        if self._peer_flood_count > 0:
            self._peer_flood_count = max(0, self._peer_flood_count - 1)
        # Gradually recover backoff multiplier on success
        if self._flood_backoff_multiplier > 1.0:
            self._flood_backoff_multiplier = max(1.0, self._flood_backoff_multiplier * 0.9)

    def stats(self) -> dict:
        return {
            "session": self.session_key,
            "total_requests": self._total_requests,
            "total_flood_waits": self._total_flood_waits,
            "flood_backoff_multiplier": round(self._flood_backoff_multiplier, 2),
            "peer_flood_count": self._peer_flood_count,
            "is_quarantined": self.is_quarantined,
            "quarantine_remaining_s": round(self.quarantine_remaining),
            "daily_downloads": self._daily_downloads,
            "consecutive_downloads": self._consecutive_downloads,
        }


class GlobalRateLimiterRegistry:
    """
    Singleton registry — one SessionRateLimiter per active session key.
    Thread-safe via asyncio.Lock.
    """

    def __init__(self):
        self._limiters: Dict[str, SessionRateLimiter] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_key: str) -> SessionRateLimiter:
        async with self._lock:
            if session_key not in self._limiters:
                self._limiters[session_key] = SessionRateLimiter(session_key)
            return self._limiters[session_key]

    def get_sync(self, session_key: str) -> SessionRateLimiter:
        """Non-async getter — creates if missing. Safe for sync contexts."""
        if session_key not in self._limiters:
            self._limiters[session_key] = SessionRateLimiter(session_key)
        return self._limiters[session_key]

    def all_stats(self) -> list:
        return [lim.stats() for lim in self._limiters.values()]


# Singleton — import and use directly
rate_registry = GlobalRateLimiterRegistry()
