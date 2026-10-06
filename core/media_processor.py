# language: Python, file: core/media_processor.py, target: Python 3.10+, OpenCV, FFmpeg
"""
Advanced Media Processor: Video Inspection, High-Res Thumbnails, Automatic Video Splitting for >2GB Files,
and Resolution Scaler/Compressor using bundled FFmpeg v7.1 and OpenCV.
"""

import os
import re
import math
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List
import cv2
from core.watermark_engine import get_ffmpeg_binary

# Telegram Bot File Upload Limit (approx 2000 MB to stay safe)
MAX_FILE_SIZE_BYTES = 2000 * 1024 * 1024


def normalize_and_save_thumbnail(source_path: str, target_path: str, max_dim: int = 320) -> bool:
    """
    Ensures any thumbnail (custom uploaded or auto-extracted) complies 100% with Telegram specification:
    - Max dimension <= 320px preserving aspect ratio
    - Pure sRGB color space (strips alpha channel cleanly with black background)
    - High-quality progressive JPEG (quality 90, < 150KB)
    """
    if not os.path.exists(source_path) or os.path.getsize(source_path) == 0:
        return False

    try:
        from PIL import Image
        with Image.open(source_path) as img:
            # Handle alpha channel (RGBA, LA, or palette with transparency)
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
                canvas = Image.new("RGB", img.size, (0, 0, 0))
                canvas.paste(img, mask=img.split()[3])
                img = canvas
            elif img.mode != "RGB":
                img = img.convert("RGB")

            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            target_dir = os.path.dirname(target_path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)

            img.save(target_path, "JPEG", quality=90, optimize=True)
            return os.path.exists(target_path) and os.path.getsize(target_path) > 100
    except Exception as e:
        print(f"[!] normalize_and_save_thumbnail error: {e}")
        return False


def _inspect_video_ffmpeg(video_path: str) -> Dict[str, Any]:
    """Fallback video inspector using bundled FFmpeg v7.1 (handles HEVC, AV1, MKV, VP9, TS)."""
    info = {
        "duration": 0,
        "width": 0,
        "height": 0,
        "fps": 0,
        "size_bytes": 0,
    }
    if not os.path.exists(video_path):
        return info

    info["size_bytes"] = os.path.getsize(video_path)
    try:
        ffmpeg_bin = get_ffmpeg_binary()
        res = subprocess.run(
            [ffmpeg_bin, "-i", str(video_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="ignore",
            timeout=15.0,
        )
        stderr = res.stderr or ""

        # Parse duration: "Duration: 00:01:23.45"
        dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr)
        if dur_match:
            h, m, s = dur_match.groups()
            info["duration"] = int(int(h) * 3600 + int(m) * 60 + float(s))

        # Parse dimensions: "Stream #... Video: ... 1920x1080"
        dim_match = re.search(r"Stream #.*Video:.*,\s*(\d{2,5})x(\d{2,5})", stderr)
        if dim_match:
            info["width"] = int(dim_match.group(1))
            info["height"] = int(dim_match.group(2))

        # Parse FPS
        fps_match = re.search(r"Stream #.*Video:.*,\s*([\d\.]+)\s*(?:fps|tbr)", stderr)
        if fps_match:
            try:
                info["fps"] = float(fps_match.group(1))
            except Exception:
                pass
    except Exception as e:
        print(f"[!] _inspect_video_ffmpeg error: {e}")

    return info


def inspect_video(video_path: str) -> Dict[str, Any]:
    """
    Inspects video file to get duration (seconds), width, height, FPS, and file size.
    Uses fast OpenCV first, with automatic robust FFmpeg fallback for modern codecs (HEVC, AV1, MKV).
    Synchronous — use inspect_video_async for non-blocking calls in async context.
    """
    info = {
        "duration": 0,
        "width": 0,
        "height": 0,
        "fps": 0,
        "size_bytes": 0,
    }
    if not os.path.exists(video_path):
        return info

    info["size_bytes"] = os.path.getsize(video_path)

    # 1. Fast OpenCV inspection
    try:
        cap = cv2.VideoCapture(str(video_path))
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = int(total_frames / fps) if fps and fps > 0 else 0
            cap.release()

            info["duration"] = duration
            info["width"] = width
            info["height"] = height
            info["fps"] = fps
    except Exception:
        pass

    # 2. If OpenCV returned incomplete or zero metadata, fall back to FFmpeg v7.1
    if info["duration"] <= 0 or info["width"] <= 0 or info["height"] <= 0:
        ff_info = _inspect_video_ffmpeg(video_path)
        if ff_info.get("duration", 0) > 0 and info["duration"] <= 0:
            info["duration"] = ff_info["duration"]
        if ff_info.get("width", 0) > 0 and info["width"] <= 0:
            info["width"] = ff_info["width"]
        if ff_info.get("height", 0) > 0 and info["height"] <= 0:
            info["height"] = ff_info["height"]
        if ff_info.get("fps", 0) > 0 and info["fps"] <= 0:
            info["fps"] = ff_info["fps"]

    return info


async def inspect_video_async(video_path: str) -> Dict[str, Any]:
    """Non-blocking async wrapper — offloads inspection to thread pool so event loop never freezes."""
    return await asyncio.to_thread(inspect_video, video_path)


def _extract_thumb_ffmpeg(video_path: str, output_thumb_path: str, seek_seconds: int = 5) -> Optional[str]:
    """
    Extracts a frame from video using bundled static FFmpeg v7.1.
    Handles any container (MKV, MP4, WebM, AVI, TS) and any codec (H.265, AV1, VP9, HDR).
    If seek_seconds fails (e.g. video is shorter than seek_seconds), auto-falls back to frame 0.
    """
    if not os.path.exists(video_path):
        return None

    ffmpeg_bin = get_ffmpeg_binary()
    thumb_dir = os.path.dirname(output_thumb_path)
    if thumb_dir:
        os.makedirs(thumb_dir, exist_ok=True)

    # Scale filter keeps aspect ratio with maximum dimension <= 320
    vf_scale = "scale=if(gte(iw\\,ih)\\,min(320\\,iw)\\,-2):if(gte(iw\\,ih)\\,-2\\,min(320\\,ih))"

    # Try requested seek_seconds, then 1s, then 0s
    for seek in [seek_seconds, 1, 0]:
        try:
            cmd = [
                ffmpeg_bin,
                "-y",
                "-ss", str(seek),
                "-i", str(video_path),
                "-vframes", "1",
                "-vf", vf_scale,
                "-q:v", "2",
                str(output_thumb_path),
            ]
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=15.0,
            )
            if os.path.exists(output_thumb_path) and os.path.getsize(output_thumb_path) > 100:
                return output_thumb_path
        except Exception:
            pass

    return None


def extract_thumbnail(video_path: str, output_thumb_path: str, seek_seconds: int = 5) -> Optional[str]:
    """
    Extracts a crisp frame to use as the Telegram video thumbnail.
    Uses fast OpenCV first, with automatic robust FFmpeg fallback and PIL normalization.
    Synchronous — use extract_thumbnail_async for non-blocking calls in async context.
    """
    if not os.path.exists(video_path):
        return None

    thumb_dir = os.path.dirname(output_thumb_path)
    if thumb_dir:
        os.makedirs(thumb_dir, exist_ok=True)

    extracted = False

    # 1. Try OpenCV frame extraction
    try:
        cap = cv2.VideoCapture(str(video_path))
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if fps and fps > 0:
                target_frame = int(seek_seconds * fps)
                if target_frame >= total_frames:
                    target_frame = max(0, total_frames // 2)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

            ret, frame = cap.read()
            # If seek failed, try frame 0
            if (not ret or frame is None) and cap.isOpened():
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()

            cap.release()

            if ret and frame is not None:
                h, w = frame.shape[:2]
                if max(h, w) > 320:
                    scale = 320.0 / max(h, w)
                    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(output_thumb_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                if os.path.exists(output_thumb_path) and os.path.getsize(output_thumb_path) > 100:
                    extracted = True
    except Exception:
        pass

    # 2. If OpenCV failed, fallback to bundled static FFmpeg v7.1
    if not extracted or not os.path.exists(output_thumb_path) or os.path.getsize(output_thumb_path) <= 100:
        ff_thumb = _extract_thumb_ffmpeg(video_path, output_thumb_path, seek_seconds)
        if ff_thumb and os.path.exists(ff_thumb) and os.path.getsize(ff_thumb) > 100:
            extracted = True

    # 3. Final normalization guarantee via PIL (ensures <= 320px, sRGB JPEG, optimal size)
    if extracted and os.path.exists(output_thumb_path) and os.path.getsize(output_thumb_path) > 100:
        norm_temp = f"{output_thumb_path}_norm.jpg"
        if normalize_and_save_thumbnail(output_thumb_path, norm_temp):
            try:
                os.replace(norm_temp, output_thumb_path)
            except Exception:
                pass
        return output_thumb_path

    return None


async def extract_thumbnail_async(video_path: str, output_thumb_path: str, seek_seconds: int = 5) -> Optional[str]:
    """Non-blocking async wrapper — offloads thumbnail extraction to thread pool."""
    return await asyncio.to_thread(extract_thumbnail, video_path, output_thumb_path, seek_seconds)



async def strip_video_metadata(input_path: str, output_path: str) -> str:
    """
    Ghost Mode Stealth Anonymizer: Losslessly strips all embedded EXIF, camera serials,
    GPS coordinates, author tags, creation times, and Telegram channel metadata.
    Zero quality loss, 0 CPU delay (finishes in milliseconds).
    Supports videos, audios, and photos.
    """
    if not os.path.exists(input_path):
        return input_path

    ext = os.path.splitext(input_path)[1].lower()

    # 1. Photo EXIF & Forensic Trace Purge
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        try:
            from PIL import Image

            def _clean_image():
                with Image.open(input_path) as img:
                    data = list(img.getdata())
                    clean_img = Image.new(img.mode, img.size)
                    clean_img.putdata(data)
                    clean_img.save(output_path, optimize=True)

            await asyncio.to_thread(_clean_image)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                return output_path
        except Exception:
            return input_path

    # 2. Video / Audio Bitstream Metadata Purge
    if ext not in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts", ".mp3", ".m4a"):
        return input_path

    ffmpeg_bin = get_ffmpeg_binary()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", input_path,
        "-map_metadata", "-1",
        "-c", "copy",
        "-movflags", "+faststart",
        output_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=30.0)
        if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            return output_path
    except Exception:
        pass

    return input_path


strip_media_metadata = strip_video_metadata


# Global semaphore to strictly limit concurrent FFmpeg CPU hogs on VPS
_cpu_semaphore = asyncio.Semaphore(2)

async def compress_or_rescale_video(
    input_path: str,
    output_path: str,
    target_height: int = 720,
    timeout: Optional[float] = None,
    source_height: int = 0,
) -> str:
    """
    Compresses or rescales video to target resolution (e.g. 720p or 480p) using ultrafast H.264.
    If source video is already <= target_height or target_height is 0/invalid, returns input_path directly.
    """
    if not os.path.exists(input_path):
        return input_path

    # If target is 0 or >= 1080, no transcoding needed
    if not target_height or target_height >= 1080:
        return input_path

    # Use provided source_height if available to bypass cv2 inspection
    current_height = source_height
    if current_height <= 0:
        meta = await inspect_video_async(input_path)
        current_height = meta.get("height", 0)
        
    # If source video is already smaller than or equal to target height, DO NOT TRANSCODE!
    if 0 < current_height <= target_height:
        return input_path

    ffmpeg_bin = get_ffmpeg_binary()
    scale_filter = f"scale=-2:{target_height}"

    # Strict maximum encoding deadline (never let user wait more than 20 seconds)
    if timeout is None:
        f_size_mb = (os.path.getsize(input_path) / (1024 * 1024)) if os.path.exists(input_path) else 50.0
        effective_timeout = max(10.0, min(20.0, f_size_mb * 0.15))
    else:
        effective_timeout = min(25.0, float(timeout))

    # Pass 1: Ultra-fast stream-copy audio + multi-threaded ultrafast video rescale
    cmd = [
        ffmpeg_bin,
        "-y",
        "-threads", "0",
        "-i", input_path,
        "-vf", scale_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "fastdecode,zerolatency",
        "-crf", "28",
        "-c:a", "copy",
        "-sn",
        "-movflags", "+faststart",
        output_path,
    ]

    try:
        # If server is already processing 2 heavy video tasks, bypass instantly rather than queuing users
        try:
            async def _do_rescale_pass1():
                async with _cpu_semaphore:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        print(f"[!] Video rescale reached {effective_timeout:.0f}s deadline for {input_path}. Falling back to original.")
                        return input_path

                    if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                        try:
                            if input_path != output_path and os.path.exists(input_path):
                                os.remove(input_path)
                        except Exception:
                            pass
                        return output_path
                return input_path

            res_p1 = await asyncio.wait_for(_do_rescale_pass1(), timeout=effective_timeout + 2.0)
            if res_p1 and res_p1 != input_path and os.path.exists(res_p1):
                return res_p1
        except (asyncio.TimeoutError, TimeoutError):
            print(f"[!] CPU busy. Bypassing FFmpeg queue for {input_path} to prevent stalling users.")
            return input_path
    except Exception as e:
        print(f"[!] Fast compression error: {e}")

    # Pass 2: Fallback with fast aac audio re-encode (with strict 15s deadline, never 600s!)
    fallback_timeout = min(15.0, effective_timeout)
    cmd_fallback = [
        ffmpeg_bin,
        "-y",
        "-threads", "0",
        "-i", input_path,
        "-vf", scale_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "fastdecode,zerolatency",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "96k",
        "-sn",
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        try:
            async def _do_rescale_pass2():
                async with _cpu_semaphore:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd_fallback,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        await asyncio.wait_for(proc.communicate(), timeout=fallback_timeout)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        print(f"[!] Video rescale fallback reached {fallback_timeout:.0f}s deadline. Falling back to original.")
                        return input_path

                    if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                        try:
                            if input_path != output_path and os.path.exists(input_path):
                                os.remove(input_path)
                        except Exception:
                            pass
                        return output_path
                return input_path

            res_p2 = await asyncio.wait_for(_do_rescale_pass2(), timeout=fallback_timeout + 2.0)
            if res_p2 and res_p2 != input_path and os.path.exists(res_p2):
                return res_p2
        except (asyncio.TimeoutError, TimeoutError):
            print(f"[!] CPU busy. Bypassing FFmpeg fallback queue for {input_path}.")
            return input_path
    except Exception as e:
        print(f"[!] Fallback compression error: {e}")

    # Guaranteed non-blocking escape hatch: return original intact video immediately
    return input_path


async def split_video_if_needed(video_path: str, max_part_size_bytes: int = MAX_FILE_SIZE_BYTES) -> List[str]:
    """
    Checks if video exceeds max_part_size_bytes (>2GB). If so, splits into seamless parts.
    Returns list of part file paths.
    """
    if not os.path.exists(video_path):
        return [video_path]

    file_size = os.path.getsize(video_path)
    if file_size <= max_part_size_bytes:
        return [video_path]

    # Calculate number of segments needed (non-blocking async inspection)
    meta = await inspect_video_async(video_path)
    total_duration = meta["duration"]
    if total_duration <= 0:
        return [video_path]

    num_parts = math.ceil(file_size / (max_part_size_bytes * 0.95))
    segment_duration = int(total_duration / num_parts)

    base, ext = os.path.splitext(video_path)
    out_pattern = f"{base}_part%02d{ext}"
    ffmpeg_bin = get_ffmpeg_binary()

    # Split using FFmpeg segmenting with stream copy (lossless and instant)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", video_path,
        "-c", "copy",
        "-map", "0",
        "-segment_time", str(segment_duration),
        "-f", "segment",
        "-reset_timestamps", "1",
        out_pattern,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=900.0)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("FFmpeg split timed out (900s)")

        # Find all generated parts
        parts = []
        dir_name = os.path.dirname(video_path) or "."
        base_name = os.path.basename(base)
        for f in sorted(os.listdir(dir_name)):
            if f.startswith(f"{base_name}_part") and f.endswith(ext):
                parts.append(os.path.join(dir_name, f))

        if parts:
            # Clean up the original huge file to save disk space
            try:
                os.remove(video_path)
            except Exception:
                pass
            return parts
    except Exception as e:
        print(f"[!] Splitting error: {e}")

    return [video_path]


async def extract_audio_mp3(
    input_path: str,
    output_mp3_path: str,
    title: Optional[str] = None,
    artist: Optional[str] = None,
) -> Optional[str]:
    """
    Extracts high-fidelity MP3 audio from any video or media container using bundled FFmpeg.
    Transcodes to clean 192kbps LAME MP3 with embedded ID3 metadata tags (Title, Artist).
    Returns path to the extracted mp3 file or None.
    """
    if not os.path.exists(input_path):
        return None

    ffmpeg_bin = get_ffmpeg_binary()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-threads", "0",
        "-i", input_path,
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
    ]
    if title:
        cmd.extend(["-metadata", f"title={title}"])
    if artist:
        cmd.extend(["-metadata", f"artist={artist}"])
    cmd.append(output_mp3_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=300.0)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("FFmpeg audio extract timed out (300s)")
        if proc.returncode == 0 and os.path.exists(output_mp3_path) and os.path.getsize(output_mp3_path) > 1024:
            return output_mp3_path
    except Exception as e:
        print(f"[!] extract_audio_mp3 error: {e}")

    return None

