# language: Python, file: core/web_downloader.py, target: Python 3.10+, yt-dlp
"""
Omni-Source Video Downloader Engine using yt-dlp.
Supports educational portals, YouTube, Facebook private groups, Drive, and m3u8 HLS streams.
"""

import os
import re
import asyncio
import yt_dlp
from typing import Optional, Dict, Any, Callable
from config import TEMP_DOWNLOAD_DIR
from core.watermark_engine import get_ffmpeg_binary


class YtDlpProgressHook:
    def __init__(self, tracker, status_message, get_markup_fn, job_id, is_cancelled_fn, loop=None):
        self.tracker = tracker
        self.status_message = status_message
        self.get_markup_fn = get_markup_fn
        self.job_id = job_id
        self.is_cancelled_fn = is_cancelled_fn
        self._loop = loop  # asyncio event loop captured at creation time (in async context)

    def __call__(self, d):
        if self.is_cancelled_fn():
            raise Exception("Cancelled by user")

        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            downloaded = d.get("downloaded_bytes") or 0
            should_edit, card_text = self.tracker.update(downloaded, total)
            if should_edit and self._loop and self._loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.status_message.edit_text(
                            text=card_text,
                            reply_markup=self.get_markup_fn(self.job_id),
                        ),
                        self._loop,
                    )
                except Exception:
                    pass


async def download_web_video(
    url: str,
    status_message,
    job_id: str,
    tracker,
    get_markup_fn,
    is_cancelled_fn,
    cookie_file: Optional[str] = None,
    resolution: str = "720",
) -> Optional[Dict[str, Any]]:
    """
    Downloads video from web sources using yt-dlp with live progress hook.
    """
    if re.search(r"(?:youtube\.com|youtu\.be)", url, re.IGNORECASE):
        return {"error": "YouTube downloads are disabled by administration to prevent server overload."}

    out_template = os.path.join(TEMP_DOWNLOAD_DIR, f"web_{job_id}_%(title).50s.%(ext)s")
    ffmpeg_bin = get_ffmpeg_binary()

    # Format selector based on resolution
    if resolution == "original":
        format_str = "bestvideo+bestaudio/best"
    elif resolution.isdigit():
        format_str = f"bestvideo[height<={resolution}]+bestaudio/best[height<={resolution}]/best"
    else:
        format_str = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"

    loop = asyncio.get_running_loop()
    ydl_opts = {
        "format": format_str,
        "outtmpl": out_template,
        "ffmpeg_location": ffmpeg_bin,
        "merge_output_format": "mp4",
        "quiet": True,
        "concurrent_fragment_downloads": 8,
        "buffersize": 1048576,
        "http_chunk_size": 10485760,
        "retries": 10,
        "fragment_retries": 10,
        "remote_components": ["ejs:github"],
        "extractor_args": {
            "youtubepot-bgutilhttp": {
                "base_url": ["http://bgutil-provider:4416"]
            }
        },
        "progress_hooks": [
            YtDlpProgressHook(tracker, status_message, get_markup_fn, job_id, is_cancelled_fn, loop=loop)
        ],
    }

    if not cookie_file or not os.path.exists(cookie_file):
        for c_cand in [
            "/app/cookies/cookies.txt",
            "/app/data/cookies/cookies.txt",
            "data/cookies/cookies.txt",
            "cookies/cookies.txt",
            "/app/cookies/youtube_cookies.txt",
            "/app/data/cookies/youtube_cookies.txt",
            "cookies.txt",
        ]:
            if os.path.exists(c_cand) and os.path.getsize(c_cand) > 10:
                cookie_file = os.path.abspath(c_cand)
                break

    temp_cookie = None
    if cookie_file and os.path.exists(cookie_file):
        import tempfile
        import shutil
        fd, temp_cookie = tempfile.mkstemp(suffix=".txt", prefix="yt_web_cookie_")
        os.close(fd)
        shutil.copyfile(cookie_file, temp_cookie)
        ydl_opts["cookiefile"] = temp_cookie

    def _sync_download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # Ensure mp4 extension if merged
            base, _ = os.path.splitext(filename)
            mp4_file = f"{base}.mp4"
            final_file = mp4_file if os.path.exists(mp4_file) else filename
            return {
                "file_path": final_file,
                "title": info.get("title", "Web Video"),
                "duration": info.get("duration", 0),
                "width": info.get("width", 1280),
                "height": info.get("height", 720),
                "thumbnail": info.get("thumbnail"),
            }

    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, _sync_download)
        return res
    except Exception as e:
        print(f"[!] yt-dlp error: {e}")
        return {"error": str(e)}
    finally:
        if temp_cookie and os.path.exists(temp_cookie):
            try:
                os.remove(temp_cookie)
            except Exception:
                pass
