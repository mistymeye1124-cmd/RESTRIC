# language: Python, file: scratch/full_deep_audit.py, target: Python 3.10+
import os
import sys
import glob
import re
import py_compile
import sqlite3

sys.path.insert(0, os.path.abspath("."))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

print("=" * 70)
print("       CYBR-MAHI ENTERPRISE FULL-SPECTRUM SYSTEM AUDIT")
print("=" * 70)

# 1. Compilation & Syntax Audit
print("\n[1] AUDITING COMPILATION & SYNTAX INTEGRITY...")
py_files = [f for f in glob.glob("**/*.py", recursive=True) if "__pycache__" not in f and ".gemini" not in f]
compile_errs = []
for f in py_files:
    try:
        py_compile.compile(f, doraise=True)
    except Exception as e:
        compile_errs.append((f, str(e)))

if compile_errs:
    print(f"  ❌ FAILED: {len(compile_errs)} compilation errors found!")
    for err in compile_errs:
        print(f"    - {err[0]}: {err[1]}")
else:
    print(f"  ✅ PASSED: All {len(py_files)} Python source files compiled with 100% clean syntax.")

# 2. Database Concurrency & Lock Audit
print("\n[2] AUDITING SQLITE CONCURRENCY & PRAGMA SETTINGS...")
db_path = "bot_database.db"
if os.path.exists(db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode;")
    jmode = cur.fetchone()[0]
    cur.execute("PRAGMA busy_timeout;")
    btimeout = cur.fetchone()[0]
    cur.execute("PRAGMA synchronous;")
    sync = cur.fetchone()[0]
    con.close()
    print(f"  • journal_mode: {jmode}")
    print(f"  • busy_timeout: {btimeout} ms")
    print(f"  • synchronous : {sync}")
    
    if jmode.upper() != "WAL":
        print("  ⚠️ WEAK POINT IDENTIFIED: SQLite is NOT in WAL (Write-Ahead-Logging) mode!")
        print("    -> Under multi-user live load, writes will lock readers and cause 'database is locked' errors!")
    else:
        print("  ✅ PASSED: WAL mode active for zero-lock concurrent read/write.")
else:
    print("  ❌ Database file not found!")

# 3. Temp Directory & Disk Leakage Audit
print("\n[3] AUDITING STORAGE & TEMP DIRECTORY RETENTION...")
dirs_to_check = ["downloads", "sessions", "cookies"]
for d in dirs_to_check:
    if os.path.exists(d):
        files = os.listdir(d)
        total_size = sum(os.path.getsize(os.path.join(d, f)) for f in files if os.path.isfile(os.path.join(d, f)))
        print(f"  • Directory '{d}': {len(files)} items ({total_size / (1024*1024):.2f} MB)")
    else:
        print(f"  • Directory '{d}': Missing (will be auto-created)")

# 4. Critical Dependencies & Binaries
print("\n[4] AUDITING EXTERNAL BINARIES & ACCELERATION...")
from core.media_processor import get_ffmpeg_binary
ffmpeg_path = get_ffmpeg_binary()
print(f"  • FFmpeg binary resolved: {ffmpeg_path}")
try:
    import tgcrypto
    print(f"  • TgCrypto acceleration: ACTIVE ({tgcrypto.__file__})")
except ImportError:
    print("  ⚠️ TgCrypto NOT found, fallback active.")

try:
    from PIL import Image
    print("  • Pillow (Image / EXIF cleaner): ACTIVE")
except ImportError:
    print("  ❌ Pillow NOT installed!")

try:
    import aiohttp
    import httpx
    print("  • Async HTTP engines (aiohttp & httpx): ACTIVE")
except ImportError as e:
    print(f"  ❌ Missing HTTP library: {e}")

# 5. Rate Limiter & Concurrency Configuration Audit
print("\n[5] AUDITING RATE LIMITER & CLIENT TRANSMISSION LIMITS...")
from core.rate_limiter import SessionRateLimiter
print(f"  • MIN_INTERVAL : {SessionRateLimiter.MIN_INTERVAL}s")
print(f"  • JITTER_MAX   : {SessionRateLimiter.JITTER_MAX}s")
print(f"  • QUARANTINE   : {SessionRateLimiter.QUARANTINE_SECONDS}s on {SessionRateLimiter.QUARANTINE_THRESHOLD} PeerFloods")

# 6. Auditing Callback Query Coverage
print("\n[6] AUDITING INLINE BUTTON CALLBACK COVERAGE...")
handler_regexes = []
h_files = glob.glob("handlers/*.py")

for f in h_files:
    with open(f, "r", encoding="utf-8", errors="ignore") as fp:
        c = fp.read()
    for m in re.findall(r"@Client\.on_callback_query\(filters\.regex\((?:r?[\'\"])(.+?)(?:[\'\"])\)", c):
        try:
            handler_regexes.append((re.compile(m), m, f))
        except Exception as e:
            print("  ⚠️ Invalid regex:", m, e)

unhandled_buttons = []
for f in h_files:
    with open(f, "r", encoding="utf-8", errors="ignore") as fp:
        c = fp.read()
    for cb in re.findall(r"callback_data=[\'\"]([^\'\"]+)[\'\"]", c):
        if "{" in cb or "$" in cb:
            continue
        matched = False
        for rgx, orig, src in handler_regexes:
            if rgx.search(cb):
                matched = True
                break
        if not matched:
            unhandled_buttons.append((f, cb))

from collections import defaultdict
grouped = defaultdict(list)
for src, cb in unhandled_buttons:
    grouped[cb].append(os.path.basename(src))

if grouped:
    print(f"  ⚠️ FOUND {len(grouped)} UNHANDLED BUTTON(S):")
    for cb, srcs in grouped.items():
        print(f"    - callback_data: '{cb}' in {list(set(srcs))}")
else:
    print(f"  ✅ PASSED: 100% of inline buttons have registered, active callback query handlers!")

print("\n" + "=" * 70)
print("AUDIT EXECUTION COMPLETE")
print("=" * 70)
