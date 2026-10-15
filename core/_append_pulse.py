# helper script — appends live_pulse to progress.py
import os

PULSE_CODE = '''

# ---------------------------------------------------------------------------
# Live Pulse - keeps UI animated during silent CPU-bound phases (FFmpeg, etc.)
# ---------------------------------------------------------------------------

_PULSE_ANIM = ['\u26a1', '\U0001f525', '\U0001f680', '\u2728', '\U0001f4ab', '\U0001f504', '\u26a1', '\U0001f3ac']
_PULSE_DOTS = ['.', '..', '...', '....', '...', '..', '.']


@asynccontextmanager
async def live_pulse(
    status_message,
    title: str,
    subtitle: str = '',
    start_pct: float = 60.0,
    end_pct: float = 95.0,
    interval: float = 3.0,
):
    """
    Async context manager that runs an animated heartbeat task while a
    blocking FFmpeg / CPU operation awaits in the event loop.

    Usage::

        async with live_pulse(s_msg, "Applying Watermark", "Encoding..."):
            result = await apply_dual_video_watermark(...)

    Updates the message every `interval` seconds so users never see a stall.
    Bar advances from start_pct -> end_pct smoothly over 120s max.
    """
    _stopped = asyncio.Event()
    _tick = [0]
    _start = time.time()

    async def _pulse_loop():
        while not _stopped.is_set():
            try:
                elapsed = time.time() - _start
                progress_range = end_pct - start_pct
                pct = min(end_pct, start_pct + (progress_range * elapsed / 120.0))
                spin = _PULSE_ANIM[_tick[0] % len(_PULSE_ANIM)]
                dots = _PULSE_DOTS[_tick[0] % len(_PULSE_DOTS)]
                bar = generate_blocks(pct, total_blocks=10, filled_char='\U0001f7e7', empty_char='\u2b1c')
                rem = max(0.0, 100.0 - pct)
                elapsed_str = format_duration(elapsed)
                sub = subtitle or 'Processing - please wait...'

                text = (
                    f"{spin} **{title}**\\n"
                    f"\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\u2501\\n"
                    f"\\U0001f4ca **Progress:**\\n"
                    f"{bar}  **{pct:.0f}%** {spin}\\n"
                    f"\\u23f3 **Remaining:** `{rem:.0f}% Left`\\n\\n"
                    f"\\u256d\\u2500\\u2500 \\U0001f3db\\ufe0f **ENGINE STATUS** \\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\n"
                    f"\\u2502 \\u23f1\\ufe0f **Elapsed:** `{elapsed_str}` | \\U0001f504 `Active{dots}`\\n"
                    f"\\u2502 \\U0001f6e1\\ufe0f **Core:** `FFmpeg Ultra-Fast Encoder`\\n"
                    f"\\u2570\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u2500\\u256f\\n"
                    f"\\u26a1 _{sub}_"
                )
                try:
                    await status_message.edit_text(text)
                except Exception:
                    pass
                _tick[0] += 1
                await asyncio.sleep(interval)
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
'''

target = os.path.join(os.path.dirname(__file__), 'progress.py')
with open(target, 'a', encoding='utf-8') as f:
    f.write(PULSE_CODE)
print('Done - appended live_pulse to', target)
