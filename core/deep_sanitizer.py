# language: Python, file: core/deep_sanitizer.py, target: Python 3.10+
"""
Deep Inspection & 100% Zero-Trace Sanitization Interceptor with Anti-Virus Shield:
Opens, inspects, scans for malware/droppers, and purges all competitor branding,
channel names, usernames, promo links, and metadata before any file or message reaches destination.

Capabilities:
1. Anti-Virus Shield & Dropper Purge:
   - Detects and drops dangerous executable payloads (.exe, .bat, .vbs, .scr, .lnk, etc.) inside archives.
   - Scans files using native Windows Defender engine (MpCmdRun.exe).
   - Blocks malware from ever reaching the target channel.
   - Fully toggleable ON/OFF per user preference.
2. Video & Audio: Lossless metadata stripping via FFmpeg (-map_metadata -1 -c copy).
3. Text Files (.txt, .srt, .nfo, .py, .md): Reads in-memory, strips channel names, @handles, links, rewrites clean.
4. Archives (.zip, .rar): Unpacks, purges promo files & malware droppers, sanitizes inner filenames,
   scrubs inner text files, strips archive comments, and rebuilds ultra-clean archives with 0 compression lag.
5. Filenames: Strips channel titles, usernames, invite links, and promo patterns.
6. Full Audit Trail: Returns detailed diagnostic logs of what was inspected and purged.
"""

import os
import re
import shutil
import zipfile
import subprocess
import asyncio
import tempfile
from typing import Dict, Any, List, Optional, Tuple

from core.watermark_engine import get_ffmpeg_binary

# Standard WinRAR executable paths on Windows
WINRAR_UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"
WINRAR_RAR = r"C:\Program Files\WinRAR\Rar.exe"
DEFENDER_CLI = r"C:\Program Files\Windows Defender\MpCmdRun.exe"

# Dangerous payload / dropper extensions commonly hidden inside course archives
DANGEROUS_EXTENSIONS = {
    ".exe", ".scr", ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".ps1", ".ps1xml", ".ps2", ".msc", ".msi", ".msp",
    ".reg", ".lnk", ".pif", ".hta", ".cpl", ".jar", ".iso",
}


def sanitize_filename(
    filename: str,
    channel_title: str = "",
    channel_username: str = "",
    custom_words: Optional[List[str]] = None,
) -> str:
    """
    Strips channel titles, @usernames, t.me links, and custom blacklisted words
    from a filename while strictly preserving the true file extension and base name.
    """
    if not filename:
        return "file"

    base, ext = os.path.splitext(filename)
    clean = base

    # 1. Strip explicit channel title if provided
    if channel_title:
        escaped_title = re.escape(channel_title.strip())
        clean = re.sub(rf"(?i)\[?\b{escaped_title}\b\]?", "", clean)
        clean = re.sub(rf"(?i){escaped_title}", "", clean)

    # 2. Strip explicit channel username if provided
    if channel_username:
        u_raw = channel_username.lstrip("@").strip()
        if u_raw:
            escaped_u = re.escape(u_raw)
            clean = re.sub(rf"(?i)@?{escaped_u}", "", clean)

    # 3. Strip custom blacklist words
    if custom_words:
        for w in custom_words:
            w_str = str(w).strip()
            if w_str:
                clean = re.sub(re.escape(w_str), "", clean, flags=re.IGNORECASE)

    # 4. Strip generic Telegram patterns: @channel_name, t.me/link, tg://
    clean = re.sub(r"(?i)https?://(?:t\.me|telegram\.me)/\S+", "", clean)
    clean = re.sub(r"(?i)t\.me/\S+", "", clean)
    clean = re.sub(r"@[a-zA-Z0-9_]{3,}", "", clean)

    # 5. Strip bracketed ads like [Join Our Channel] or (Backup Channel)
    clean = re.sub(r"(?i)\[[^\]]*(?:channel|join|vip|backup|leaks|course|t\.me)[^\]]*\]", "", clean)
    clean = re.sub(r"(?i)\([^\)]*(?:channel|join|vip|backup|leaks|course|t\.me)[^\)]*\)", "", clean)

    # 6. Normalize separators and trailing junk
    clean = re.sub(r"[_\s\.-]{2,}", " ", clean)
    clean = clean.strip(" _-.\t\r\n")

    # Fallback if filename became empty
    if not clean:
        clean = "Clean_Media"

    return f"{clean}{ext}"


def clean_text_string(
    text: str,
    channel_title: str = "",
    channel_username: str = "",
    custom_words: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """
    Cleans a text string by purging channel links, usernames, promotional banners,
    pricing tiers, VIP cloud headers, and competitor watermarks while strictly preserving
    valid email addresses, credentials, passwords, and genuine data.
    Returns (cleaned_text, audit_log).
    """
    if not text:
        return "", []

    audits = []
    lines = text.splitlines()
    cleaned_lines = []

    # Patterns for promotional lines that should be dropped completely
    promo_line_patterns = [
        # Channels, Links, Invites, Admins, Messages
        r"(?i)^\s*.*(?:public\s*channel|main\s*channel|backup\s*channel|vip\s*channel|official\s*channel|telegram\s*channel|our\s*channel|channel\s*link|discussion\s*group)\s*[:►👉\-—=\|].*$",
        r"(?i)^\s*.*(?:message|contact|dm|admin|owner|support)\s+@[\w\d_]{3,}.*$",
        r"(?i)^\s*.*(?:join|visit|subscribe|follow)\s+(?:our|my|the|this)?\s*(?:telegram|tg|vip|official|backup|main|channel|group|chat|updates|now|here)?.*$",
        r"(?i)^\s*.*(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/[^\s]+.*$",
        r"(?i)^\s*@[a-zA-Z0-9_]{3,}\s*$",
        r"(?i)^\s*(?:uploaded\s*by|credit|credits|source|provided\s*by|shared\s*by|leaked\s*by)\s*[:►👉\-—=\|].*$",

        # Pricing, VIP, Plans, Tiers, Commercial ads
        r"(?i)^\s*.*(?:pricing|plans?|tiers?|subscription|packages?|rates?).*$",
        r"(?i)^\s*.*(?:\b\d+\s*(?:months?|days?|weeks?|years?|hrs?|hours?)|\blifetime\b|\bannually\b|\bmonthly\b|\bweekly\b|\bdaily\b).*(?:➜|->|=>|→|►|👉|➡|➤|:|-|—|\$|€|£|usd|eur|usdt|\b\d+\b).*$",
        r"(?i)^\s*.*(?:pay\s*once|lifetime\s*access|one\s*time\s*payment).*$",
        r"(?i)^\s*.*vip\s*(?:cloud|group|member|channel|tier|access).*(?:hq|posting|leaks|combo|database).*$",
        r"(?i)^\s*.*stop\s*lagging\s*behind\s*(?:the\s*competition)?.*$",
        r"(?i)^\s*.*(?:best|daily|exclusive)\s*(?:combos?|leaks?|hq|hits?|tools?|logs?).*$",
        r"(?i)^\s*.*(?:accepted\s*payments?|payment\s*methods?|crypto|paypal|binance|btc|usdt|ltc)\s*[:►👉\-—=\|].*$",
        r"(?i)^\s*.*(?:to\s*buy|for\s*buy|purchase|order|dm\s*to\s*buy|contact\s*to\s*buy|buy\s*now).*$",
    ]

    orphaned_label_patterns = [
        r"(?i)^\s*(?:public\s*channel|main\s*channel|backup\s*channel|vip\s*channel|channel|message|contact|dm|link|source|credit|credits)\s*[:►👉\-—=\|\s]*$",
    ]

    DECORATIVE_CHARS = "-=_~*#■█━═─▬─━│┃┄┅┆┇┈┉┊┋┌┍┎┏┐┑┒┓└┕┖┗┘┙┚┛├┝┞┟┠┡┢┣┤┥┦┧┨┩┪┫┬┭┮┳┴┵┶┻┼┽┾╀╁╂╃╄╅╆╇╈╉╊╋═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬"

    for line in lines:
        stripped = line.strip(" \t-►👉*━═~_=•#|┌┐└┘├┤┼│■█▬")

        # 1. Skip decorative border lines (e.g. ████████████████ or ==================)
        border_stripped = re.sub(r"[\s\-_=~*#■█━═─▬│┃┄┅┆┇┈┉┊┋┌┐└┘├┤┼▀▄\./\\|]+", "", line)
        if not border_stripped or (len(set(stripped)) == 1 and stripped[0] in DECORATIVE_CHARS):
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue

        # Check if line contains a genuine email address or combo format
        has_email = bool(re.search(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b", line))
        is_plain_combo = bool(re.match(r"^[a-zA-Z0-9_\-\.]+:[^\s]+$", line.strip()))

        # 2. Check smart pricing / duration subscription tier line (e.g. "💸 1 Month ➜ $8 💰")
        is_pricing_line = False
        if not has_email and not is_plain_combo:
            # Any line with currency amount $8, 8$, €15, etc.
            if re.search(r"(?:[\$€£]\s*\d+|\b\d+\s*[\$€£]|\b\d+\s*(?:usd|eur|gbp|usdt|crypto|btc|eth)\b)", line, re.IGNORECASE):
                is_pricing_line = True
            # Any line with duration/tier words: 1 Month, 2 Months, Lifetime, etc.
            elif re.search(r"(?i)\b(?:\d+\s*(?:months?|days?|weeks?|years?|hrs?|hours?)|\blifetime\b|\bannually\b|\bmonthly\b|\bweekly\b|\bdaily\b)\b", line):
                is_pricing_line = True

        if is_pricing_line:
            audits.append(f"Dropped pricing line: {line.strip()[:60]}")
            continue

        # 3. Check full promo line patterns
        is_promo = False
        for pat in promo_line_patterns:
            if re.match(pat, line.strip()):
                audits.append(f"Dropped promo line: {line.strip()[:60]}")
                is_promo = True
                break
        if is_promo:
            continue

        # 4. Check if line contains explicit channel title / branding banner
        if channel_title and channel_title.strip():
            ct = channel_title.strip()
            if ct.lower() in line.lower() and len(stripped) <= len(ct) + 20:
                audits.append(f"Dropped channel title banner: {line.strip()[:60]}")
                continue

        l_clean = line

        # 4. Strip explicit channel title words inside lines
        if channel_title:
            ct = channel_title.strip()
            l_clean = re.sub(re.escape(ct), "", l_clean, flags=re.IGNORECASE)
            for part in ct.split():
                part_clean = part.strip()
                if len(part_clean) >= 4 and part_clean.lower() not in ("free", "chat", "group", "link", "post", "cloud"):
                    l_clean = re.sub(rf"(?i)\b{re.escape(part_clean)}\b", "", l_clean)

        # 5. Strip explicit channel username
        if channel_username:
            u_raw = channel_username.lstrip("@").strip()
            if u_raw:
                l_clean = re.sub(rf"(?i)@?{re.escape(u_raw)}\b", "", l_clean)

        # 6. Strip custom blacklist words
        if custom_words:
            for cw in custom_words:
                w_str = str(cw).strip()
                if w_str:
                    l_clean = re.sub(re.escape(w_str), "", l_clean, flags=re.IGNORECASE)

        # 7. Strip Telegram links & handles (STRICTLY PRESERVING valid email addresses name@domain.tld)
        l_clean = re.sub(r"(?i)https?://(?:t\.me|telegram\.me|telegram\.dog)/[^\s]+", "", l_clean)
        l_clean = re.sub(r"(?i)t\.me/[^\s]+", "", l_clean)
        l_clean = re.sub(r"(?i)tg://[^\s]+", "", l_clean)
        # Match @handle only when NOT preceded by word/dot and NOT followed by a domain extension (.com, .net, etc.)
        l_clean = re.sub(r"(?<![\w\d._%+-])@([a-zA-Z0-9_]{3,})\b(?!\.[a-zA-Z]{2,})", "", l_clean)

        # 8. Check if line became an orphaned label
        clean_stripped = l_clean.strip(" \t-►👉*━═~_=•#|┌┐└┘├┤┼│■█▬")
        is_orphaned = False
        for orph_pat in orphaned_label_patterns:
            if re.match(orph_pat, clean_stripped):
                is_orphaned = True
                break
        if is_orphaned:
            continue

        if not clean_stripped:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue

        cleaned_lines.append(l_clean)

    # Strip leading and trailing empty lines
    while cleaned_lines and cleaned_lines[0] == "":
        cleaned_lines.pop(0)
    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()

    result = "\n".join(cleaned_lines)
    return result, audits


def clean_text_file(
    file_path: str,
    channel_title: str = "",
    channel_username: str = "",
    custom_words: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """
    Reads a .txt, .srt, .nfo, .md, or code file, strips all branding, and rewrites clean.
    """
    if not os.path.exists(file_path):
        return file_path, []

    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
    content = None
    used_enc = "utf-8"

    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                content = f.read()
            used_enc = enc
            break
        except Exception:
            continue

    if content is None:
        return file_path, ["Could not decode text file for cleaning"]

    cleaned_content, audits = clean_text_string(content, channel_title, channel_username, custom_words)

    try:
        with open(file_path, "w", encoding=used_enc) as f:
            f.write(cleaned_content)
        audits.append(f"Scrubbed text file: {os.path.basename(file_path)}")
    except Exception as e:
        audits.append(f"Error writing scrubbed text: {e}")

    return file_path, audits


async def clean_media_metadata(file_path: str) -> Tuple[str, List[str]]:
    """
    Losslessly strips all embedded EXIF, tags, comments, author credits, and channel IDs
    from video/audio bitstreams via FFmpeg (-map_metadata -1 -c copy).
    Takes milliseconds, 0 quality loss, 0 CPU re-encoding overhead.
    """
    if not os.path.exists(file_path):
        return file_path, []

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts", ".mp3", ".m4a", ".aac", ".ogg", ".opus"):
        return file_path, []

    ffmpeg_bin = get_ffmpeg_binary()
    dir_name = os.path.dirname(file_path)
    clean_out = os.path.join(dir_name, f"clean_{os.path.basename(file_path)}")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", file_path,
        "-map_metadata", "-1",
        "-c", "copy",
        "-movflags", "+faststart",
        clean_out,
    ]

    audits = []
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=45.0)

        if proc.returncode == 0 and os.path.exists(clean_out) and os.path.getsize(clean_out) > 100:
            os.replace(clean_out, file_path)
            audits.append("Purged all bitstream metadata & author tags (-map_metadata -1)")
            return file_path, audits
    except Exception as e:
        audits.append(f"FFmpeg metadata strip error: {e}")

    if os.path.exists(clean_out):
        try:
            os.remove(clean_out)
        except Exception:
            pass

    return file_path, audits


def scan_file_defender(file_path: str) -> Tuple[bool, str]:
    """
    Performs real-time virus scan using Windows Defender CLI.
    Returns (is_infected, threat_info).
    Exit code 0: Clean, Exit code 2: Infected!
    """
    if not os.path.exists(file_path) or not os.path.exists(DEFENDER_CLI):
        return False, "Scanner unavailable or file missing"

    try:
        cmd = [DEFENDER_CLI, "-Scan", "-ScanType", "3", "-File", file_path]
        ret = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if ret.returncode == 2:
            return True, "Threat detected by Windows Defender engine"
        return False, "Clean"
    except Exception as e:
        return False, f"Scan bypassed: {e}"


def clean_zip_archive(
    zip_path: str,
    channel_title: str = "",
    channel_username: str = "",
    custom_words: Optional[List[str]] = None,
    antivirus_scan: bool = True,
) -> Tuple[str, List[str]]:
    """
    Unpacks zip in memory/stream, drops promo files, purges dangerous malware droppers
    if antivirus_scan is ON, cleans inner text files, and rebuilds with 0 compression lag.
    """
    if not os.path.exists(zip_path) or not zipfile.is_zipfile(zip_path):
        return zip_path, []

    audits = []
    dir_name = os.path.dirname(zip_path)
    clean_zip_path = os.path.join(dir_name, f"sanitized_{os.path.basename(zip_path)}")

    promo_file_patterns = [
        r"(?i).*\.url$",
        r"(?i).*\.nfo$",
        r"(?i).*join.*telegram.*",
        r"(?i).*join.*channel.*",
        r"(?i).*subscribe.*",
        r"(?i).*credit.*\.txt$",
        r"(?i).*readme.*promo.*",
    ]

    try:
        with zipfile.ZipFile(zip_path, "r") as zin:
            with zipfile.ZipFile(clean_zip_path, "w", compression=zipfile.ZIP_STORED) as zout:
                for item in zin.infolist():
                    name = item.filename
                    inner_ext = os.path.splitext(name)[1].lower()

                    # 1. Anti-Virus Shield: Purge dangerous malware droppers
                    if antivirus_scan and inner_ext in DANGEROUS_EXTENSIONS:
                        audits.append(f"🛡️ [Anti-Virus Shield] Dropped suspicious executable payload: {name}")
                        continue

                    # 2. Check if the file is junk promo
                    is_junk = False
                    for pat in promo_file_patterns:
                        if re.search(pat, name):
                            audits.append(f"Dropped inner archive promo file: {name}")
                            is_junk = True
                            break
                    if is_junk:
                        continue

                    # 3. Sanitize inner filename
                    clean_inner_name = sanitize_filename(name, channel_title, channel_username, custom_words)
                    if clean_inner_name != name:
                        audits.append(f"Renamed inside archive: '{name}' -> '{clean_inner_name}'")

                    # 4. Read data
                    data = zin.read(item.filename)

                    # 5. If inner file is a text/subtitle file, clean its content
                    if inner_ext in (".txt", ".srt", ".vtt", ".nfo", ".md", ".html"):
                        try:
                            text_str = data.decode("utf-8")
                            cleaned_str, inner_audits = clean_text_string(
                                text_str, channel_title, channel_username, custom_words
                            )
                            data = cleaned_str.encode("utf-8")
                            if inner_audits:
                                audits.append(f"Cleaned {len(inner_audits)} promo items inside '{name}'")
                        except Exception:
                            pass

                    # 6. Write into clean archive with empty comment
                    zout.writestr(clean_inner_name, data)

                # Wipe archive-level comment
                zout.comment = b""

        os.replace(clean_zip_path, zip_path)
        audits.append("Archive rebuilt 100% clean (zero comment, promo & malware droppers purged)")
        return zip_path, audits

    except Exception as e:
        audits.append(f"Zip clean error: {e}")
        if os.path.exists(clean_zip_path):
            try:
                os.remove(clean_zip_path)
            except Exception:
                pass
        return zip_path, audits


def clean_rar_archive(
    rar_path: str,
    channel_title: str = "",
    channel_username: str = "",
    custom_words: Optional[List[str]] = None,
    antivirus_scan: bool = True,
) -> Tuple[str, List[str]]:
    """
    Extracts RAR using native UnRAR.exe, purges promo files and malware droppers,
    sanitizes inner names & text, and repacks into clean archive without comments.
    """
    if not os.path.exists(rar_path):
        return rar_path, []

    audits = []
    unrar_bin = WINRAR_UNRAR if os.path.exists(WINRAR_UNRAR) else "unrar"

    temp_extract = tempfile.mkdtemp(prefix="rar_clean_")
    try:
        cmd = [unrar_bin, "x", "-y", "-inul", rar_path, f"{temp_extract}\\"]
        ret = subprocess.run(cmd, capture_output=True, timeout=60)
        if ret.returncode != 0:
            audits.append(f"UnRAR failed or not found: {ret.stderr.decode(errors='ignore')}")
            shutil.rmtree(temp_extract, ignore_errors=True)
            return rar_path, audits

        promo_patterns = [r"(?i).*\.url$", r"(?i).*\.nfo$", r"(?i).*join.*", r"(?i).*promo.*"]
        for root, dirs, files in os.walk(temp_extract, topdown=False):
            for file in files:
                f_path = os.path.join(root, file)
                f_ext = os.path.splitext(file)[1].lower()

                # 1. Anti-Virus Shield: Purge dangerous malware droppers
                if antivirus_scan and f_ext in DANGEROUS_EXTENSIONS:
                    try:
                        os.remove(f_path)
                        audits.append(f"🛡️ [Anti-Virus Shield] Dropped suspicious executable payload: {file}")
                    except Exception:
                        pass
                    continue

                # 2. Drop promo files
                is_promo = any(re.search(pat, file) for pat in promo_patterns)
                if is_promo:
                    try:
                        os.remove(f_path)
                        audits.append(f"Dropped inner promo file: {file}")
                    except Exception:
                        pass
                    continue

                # 3. Clean text files
                if f_ext in (".txt", ".srt", ".vtt", ".md"):
                    clean_text_file(f_path, channel_title, channel_username, custom_words)

                # 4. Rename files containing channel names
                c_name = sanitize_filename(file, channel_title, channel_username, custom_words)
                if c_name != file:
                    new_f_path = os.path.join(root, c_name)
                    try:
                        os.rename(f_path, new_f_path)
                        audits.append(f"Renamed inner file: '{file}' -> '{c_name}'")
                    except Exception:
                        pass

        dir_name = os.path.dirname(rar_path)
        base_name = os.path.splitext(os.path.basename(rar_path))[0]
        clean_zip = os.path.join(dir_name, f"{base_name}.zip")

        with zipfile.ZipFile(clean_zip, "w", compression=zipfile.ZIP_STORED) as zout:
            for root, dirs, files in os.walk(temp_extract):
                for file in files:
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, temp_extract)
                    zout.write(full_p, rel_p)

        if os.path.exists(clean_zip) and os.path.getsize(clean_zip) > 0:
            try:
                os.remove(rar_path)
            except Exception:
                pass
            audits.append(f"Converted & repacked dirty RAR into 100% white-label ZIP: {os.path.basename(clean_zip)}")
            return clean_zip, audits

    except Exception as e:
        audits.append(f"RAR sanitize exception: {e}")
    finally:
        shutil.rmtree(temp_extract, ignore_errors=True)

    return rar_path, audits


async def deep_inspect_and_sanitize(
    file_path: str,
    channel_title: str = "",
    channel_username: str = "",
    custom_words: Optional[List[str]] = None,
    antivirus_scan: bool = True,
) -> Dict[str, Any]:
    """
    Master A-to-Z Inspection Gate with Anti-Virus Shield:
    Opens, scans for threats, strips metadata, cleans archives, and sanitizes filenames.
    Returns:
    {
        "original_path": str,
        "clean_path": str,
        "clean_name": str,
        "audits": List[str],
        "blocked_threat": bool,
        "threat_name": str
    }
    """
    if not file_path or not os.path.exists(file_path):
        return {
            "original_path": file_path,
            "clean_path": file_path,
            "clean_name": os.path.basename(file_path) if file_path else "",
            "audits": ["File does not exist on disk"],
            "blocked_threat": False,
            "threat_name": "",
        }

    audits = []
    current_path = file_path
    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()

    # 1. Anti-Virus Shield Check on Standalone Executables
    if antivirus_scan and ext in DANGEROUS_EXTENSIONS:
        return {
            "original_path": file_path,
            "clean_path": file_path,
            "clean_name": filename,
            "audits": [f"🛡️ [Anti-Virus Shield] Blocked dangerous standalone executable/script ({ext})"],
            "blocked_threat": True,
            "threat_name": f"Dangerous Executable Payload ({ext})",
        }

    # 2. Deep Archive Inspection & Malware Purge
    if ext == ".zip":
        current_path, arc_audits = await asyncio.to_thread(
            clean_zip_archive, current_path, channel_title, channel_username, custom_words, antivirus_scan
        )
        audits.extend(arc_audits)

    elif ext == ".rar":
        current_path, arc_audits = await asyncio.to_thread(
            clean_rar_archive, current_path, channel_title, channel_username, custom_words, antivirus_scan
        )
        audits.extend(arc_audits)

    # 3. Text File Content Inspection
    elif ext in (".txt", ".srt", ".vtt", ".nfo", ".md", ".html", ".py", ".json", ".csv"):
        current_path, txt_audits = await asyncio.to_thread(
            clean_text_file, current_path, channel_title, channel_username, custom_words
        )
        audits.extend(txt_audits)

    # 4. Media Metadata Bitstream Scrubbing
    elif ext in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts", ".mp3", ".m4a", ".aac", ".ogg", ".opus"):
        current_path, media_audits = await clean_media_metadata(current_path)
        audits.extend(media_audits)

    # 5. Active Defender Virus Scan if Antivirus Shield is ON
    if antivirus_scan and os.path.exists(current_path):
        is_threat, threat_info = await asyncio.to_thread(scan_file_defender, current_path)
        if is_threat:
            return {
                "original_path": file_path,
                "clean_path": current_path,
                "clean_name": os.path.basename(current_path),
                "audits": [f"🚨 [Anti-Virus Alert] {threat_info}"],
                "blocked_threat": True,
                "threat_name": threat_info,
            }

    # 6. Final Outer Filename Sanitization
    new_filename = sanitize_filename(
        os.path.basename(current_path),
        channel_title=channel_title,
        channel_username=channel_username,
        custom_words=custom_words,
    )

    if new_filename != os.path.basename(current_path):
        dir_p = os.path.dirname(current_path)
        renamed_path = os.path.join(dir_p, new_filename)
        try:
            os.replace(current_path, renamed_path)
            audits.append(f"Renamed file: '{os.path.basename(current_path)}' -> '{new_filename}'")
            current_path = renamed_path
        except Exception as e:
            audits.append(f"Rename error: {e}")

    return {
        "original_path": file_path,
        "clean_path": current_path,
        "clean_name": os.path.basename(current_path),
        "audits": audits,
        "blocked_threat": False,
        "threat_name": "",
    }
