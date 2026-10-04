# language: Python, file: core/progress.py, target: Python 3.10+
"""
Real-time progress tracker and high-aesthetic telemetry card generator
for Telegram download & upload operations.
Engineered for ultra-smooth UI feedback, low flood-wait footprint, and world-class aesthetics.
"""

import time
import math
import asyncio
from typing import Tuple, Optional
from contextlib import asynccontextmanager
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import PROGRESS_UPDATE_INTERVAL as _PROG_INTERVAL


def human_readable_size(size_bytes: float) -> str:
    """Formats bytes to B, KB, MB, GB."""
    if size_bytes <= 0:
        return "0.0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2 if i >= 2 else 1)
    return f"{s} {units[i]}"


def format_duration(seconds: float) -> str:
    """Formats seconds to M:SS or H:MM:SS."""
    if seconds <= 0 or math.isinf(seconds) or math.isnan(seconds):
        return "00:00"
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def generate_blocks(percentage: float, total_blocks: int = 10, filled_char: str = "🟧", empty_char: str = "⬜") -> str:
    """Generates visual square progress bar: e.g. 🟧🟧🟧🟧🟧🟧🟧🟧🟧⬜"""
    filled = int(round((percentage / 100.0) * total_blocks))
    filled = max(0, min(total_blocks, filled))
    empty = total_blocks - filled
    return (filled_char * filled) + (empty_char * empty)


def format_progress_line(percentage: float, show_remaining: bool = True, anim_frame: str = "") -> str:
    """
    Renders user-requested format:
    🟧🟧🟧🟧🟧🟧🟧🟧🟧⬜  91%  (Remaining: 9%) ⚡
    When 100%:
    🟧🟧🟧🟧🟧🟧🟧🟧🟧🟧  100% Complete ✅
    """
    pct = max(0.0, min(100.0, percentage))
    bar = generate_blocks(pct, total_blocks=10, filled_char="🟧", empty_char="⬜")
    if pct >= 100.0:
        return f"{bar}  100% Complete ✅"

    rem_pct = max(0.0, 100.0 - pct)
    spin = f" {anim_frame}" if anim_frame else ""
    if show_remaining:
        return f"{bar}  {pct:.0f}%  (Remaining: {rem_pct:.0f}%){spin}"
    return f"{bar}  {pct:.0f}%{spin}"


def get_progress_markup(job_id: str, res_pref: str = "original") -> InlineKeyboardMarkup:
    """Inline keyboard with '🔄 Force Complete / Refresh', '📊 Live Stats', '⚙️ Quality', and '🛑 Cancel Task'."""
    res_label = "⚡ Original" if res_pref == "original" else f"📺 {res_pref}p"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Force Complete / Refresh ⚡", callback_data=f"force_complete:{job_id}"),
            ],
            [
                InlineKeyboardButton("📊 Live Telemetry", callback_data=f"prog:{job_id}"),
                InlineKeyboardButton(f"⚙️ {res_label}", callback_data=f"quick_res:{job_id}"),
            ],
            [
                InlineKeyboardButton("🛑 Cancel Operation", callback_data=f"cancel:{job_id}"),
            ]
        ]
    )


class ProgressTracker:
    ANIM_FRAMES = ["⚡", "🚀", "🔄", "✨", "💫", "🔥"]

    def __init__(
        self,
        action_name: str = "Downloading Media",
        block_char: str = "🟧",
        engine_tag: str = "TITAN v7.0 Multi-Stream Core",
    ):
        self.action_name = action_name
        self.block_char = "🟧"
        self.empty_char = "⬜"
        self.engine_tag = engine_tag
        self.start_time = time.time()
        self.last_update_time = 0.0  # 0.0 forces immediate update on first chunk!
        self.last_calc_time = time.time()
        self.last_bytes = 0
        self.current_speed = 0.0
        self.total_bytes = 0
        self.current_bytes = 0
        self.percentage = 0.0
        self.is_cancelled = False
        self.finished = False
        self._update_ticks = 0

    def mark_finished(self):
        self.finished = True

    def render_card(self, current: int, total: int) -> str:
        """Renders high-aesthetic animated telemetry card."""
        now = time.time()
        self.current_bytes = current
        self.total_bytes = total if total > 0 else 1
        self.percentage = min(100.0, (self.current_bytes / self.total_bytes) * 100.0)

        spin = self.ANIM_FRAMES[self._update_ticks % len(self.ANIM_FRAMES)]
        bar = generate_blocks(self.percentage, total_blocks=10, filled_char=self.block_char, empty_char=self.empty_char)
        rem_pct = max(0.0, 100.0 - self.percentage)

        is_done = (self.percentage >= 100.0 or self.current_bytes >= self.total_bytes or self.finished)

        if is_done:
            progress_line = f"{bar}  **100% Complete ✅**"
            status_line = "│ ✅ **Status:** `Complete & Finalizing Delivery...`"
        else:
            progress_line = f"{bar}  **{self.percentage:.0f}%** {spin}\n⏳ **Remaining:** `{rem_pct:.0f}% Left`"
            rem_bytes = max(0, self.total_bytes - self.current_bytes)
            effective_speed = self.current_speed
            if effective_speed <= 0 and current > 0:
                total_elapsed = max(now - self.start_time, 0.1)
                effective_speed = current / total_elapsed
            eta_seconds = (rem_bytes / effective_speed) if effective_speed > 0 else 0
            eta_str = f"{format_duration(eta_seconds)} remaining"
            status_line = f"│ ⏱️ **Estimated:** `{eta_str}`"

        readable_cur = human_readable_size(self.current_bytes)
        readable_tot = human_readable_size(self.total_bytes)
        speed_str = f"{human_readable_size(self.current_speed)}/s"

        is_dl = "Download" in self.action_name or "HARVEST" in self.action_name.upper()
        action_title = "PRO HARVESTER TURBO" if is_dl else "PRO DISPATCHER TURBO"

        text = (
            f"⚡ **{action_title}** ⚡\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 **Operation:** `{self.action_name}`\n"
            f"📊 **Progress:**\n"
            f"{progress_line}\n\n"
            f"╭── 📡 **LIVE TELEMETRY** ───────────────\n"
            f"│ 📦 **Transferred:** `{readable_cur}` / `{readable_tot}`\n"
            f"│ 🚀 **Throughput:** `{speed_str}` (Live)\n"
            f"{status_line}\n"
            f"│ 🛡️ **Shield:** `Active Anti-Ban Stealth (Zero Trace)`\n"
            f"╰────────────────────────────────────────╯\n"
            f"⚡ _Engine: {self.engine_tag}_"
        )
        return text

    def card(self, current: int = 0, total: int = 1) -> str:
        """Renders the telemetry card on demand."""
        return self.render_card(current, total)

    def update(self, current: int, total: int) -> Tuple[bool, str]:
        """
        Updates progress calculations. Returns (should_edit_message, text).
        Throttles edits to avoid Telegram FLOOD_WAIT (every 1.8s).
        Guarantees immediate update on first chunk (0.0 init).
        """
        now = time.time()
        self._update_ticks += 1
        self.current_bytes = current
        self.total_bytes = total if total > 0 else 1
        self.percentage = min(100.0, (self.current_bytes / self.total_bytes) * 100.0)

        # Calculate speed with Exponential Moving Average (EMA) to prevent wild fluctuations
        calc_delta = now - self.last_calc_time
        if calc_delta >= 0.8:
            bytes_delta = current - self.last_bytes
            if bytes_delta > 0 and calc_delta > 0:
                instant_speed = bytes_delta / calc_delta
                if self.current_speed <= 0:
                    self.current_speed = instant_speed
                else:
                    # 70% historical smoothed speed + 30% instant delta = rock-stable live telemetry
                    self.current_speed = (0.70 * self.current_speed) + (0.30 * instant_speed)
            elif self.current_speed > 0:
                # Gradual decay while waiting for next chunk to arrive
                overall_avg = current / max(now - self.start_time, 0.1)
                self.current_speed = max(self.current_speed * 0.92, overall_avg)
            self.last_bytes = current
            self.last_calc_time = now

        # Fallback to total elapsed average if current_speed is 0
        if self.current_speed <= 0 and current > 0:
            total_elapsed = max(now - self.start_time, 0.1)
            self.current_speed = current / total_elapsed

        text = self.render_card(self.current_bytes, self.total_bytes)

        elapsed_since_edit = now - self.last_update_time
        is_first_chunk = (self.last_update_time == 0.0)
        is_done = (self.current_bytes >= self.total_bytes)

        # Anti-Flood Protection: Enforce strict 2.0s floor between edits
        should_update = (
            is_first_chunk
            or is_done
            or (elapsed_since_edit >= max(_PROG_INTERVAL, 2.0))
        )
        if should_update:
            self.last_update_time = now
            self._last_edit_pct = self.percentage
            if self.current_bytes >= self.total_bytes:
                self.finished = True
            return True, text

        return False, text

    def get_alert_summary(self) -> str:
        """Text displayed when user presses '📊 Live Telemetry' popup alert (Max 180 chars for Telegram API)."""
        running_sec = time.time() - self.start_time
        running_str = format_duration(running_sec)
        readable_cur = human_readable_size(self.current_bytes)
        readable_tot = human_readable_size(self.total_bytes) if self.total_bytes > 1 else "..."
        speed_str = f"{human_readable_size(self.current_speed)}/s"
        bar = generate_blocks(self.percentage, total_blocks=10, filled_char=self.block_char, empty_char=self.empty_char)
        rem_pct = max(0.0, 100.0 - self.percentage)

        if self.percentage >= 100.0 or self.finished:
            return (
                f"✅ {self.action_name}: 100% Complete!\n"
                f"{bar}\n"
                f"⏱️ Time: {running_str} | 🚀 {speed_str}"
            )
        return (
            f"⚡ {self.action_name}\n"
            f"{bar}  {self.percentage:.0f}%\n"
            f"⏳ Remaining: {rem_pct:.0f}% | ⏱️ {running_str} | 🚀 {speed_str}"
        )


# ---------------------------------------------------------------------------
# Live Pulse - keeps UI animated during silent CPU-bound phases (FFmpeg, etc.)
# ---------------------------------------------------------------------------

_PULSE_ANIM = ["⚡", "🔥", "🚀", "✨", "💫", "🔄", "⚡", "🎬"]
_PULSE_DOTS = [".", "..", "...", "....", "...", "..", "."]


@asynccontextmanager
async def live_pulse(
    status_message,
    title: str,
    subtitle: str = "",
    start_pct: float = 60.0,
    end_pct: float = 95.0,
    interval: float = 3.5,
    estimated_seconds: int = 60,
):
    """
    Async context manager — animated heartbeat during silent FFmpeg phases.

    - Fires IMMEDIATELY at t=0 (no gap after download 100% card)
    - Shows a visible countdown: "~45s remaining" ticking down every 3.5s
    - Bar advances from start_pct -> end_pct over estimated_seconds
    - FloodWait-immune: wraps edit in wait_for to prevent Pyrogram internal sleep

    Usage::

        async with live_pulse(s_msg, "Applying Watermark", "Encoding...",
                              estimated_seconds=60):
            result = await apply_dual_video_watermark(...)
    """
    _stopped = asyncio.Event()
    _tick = [0]
    _start = time.time()

    def _build_text(elapsed: float) -> str:
        progress_range = end_pct - start_pct
        # Bar advances over estimated_seconds; clamp at end_pct
        pct = min(end_pct, start_pct + (progress_range * elapsed / max(estimated_seconds, 1)))
        spin = _PULSE_ANIM[_tick[0] % len(_PULSE_ANIM)]
        dots = _PULSE_DOTS[_tick[0] % len(_PULSE_DOTS)]
        bar = generate_blocks(pct, total_blocks=10, filled_char="🟧", empty_char="⬜")
        elapsed_str = format_duration(elapsed)

        # Countdown: how many seconds remain before estimated completion
        countdown_s = max(0, int(estimated_seconds - elapsed))
        if countdown_s > 60:
            countdown_str = f"~{countdown_s // 60}m {countdown_s % 60}s"
        elif countdown_s > 0:
            countdown_str = f"~{countdown_s}s"
        else:
            countdown_str = "finishing..."

        sub = subtitle or "Processing - please wait..."

        return (
            f"{spin} **{title}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 **Progress:**\n"
            f"{bar}  **{pct:.0f}%** {spin}\n"
            f"⏳ **Complete in:** `{countdown_str}` {dots}\n\n"
            f"╭── 🎛️ **ENGINE STATUS** ────────────────\n"
            f"│ ⏱️ **Running:** `{elapsed_str}` | 🔄 `Active`\n"
            f"│ 🛡️ **Core:** `FFmpeg Ultra-Fast Encoder`\n"
            f"╰────────────────────────────────────────╯\n"
            f"⚡ _{sub}_"
        )

    async def _pulse_loop():
        # Fire IMMEDIATELY at tick 0 — closes the gap after download 100% card
        while not _stopped.is_set():
            try:
                elapsed = time.time() - _start
                text = _build_text(elapsed)
                try:
                    # Timeout prevents Pyrogram internal sleep_threshold from locking this coroutine
                    await asyncio.wait_for(status_message.edit_text(text), timeout=1.8)
                except Exception:
                    pass  # FloodWait / message not modified — skip silently
                _tick[0] += 1
                # Wait interval, but wake immediately if stopped
                try:
                    await asyncio.wait_for(_stopped.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                break
            except Exception:
                break

    task = asyncio.create_task(_pulse_loop())
    try:
        yield
    finally:
        _stopped.set()
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
        except Exception:
            pass
