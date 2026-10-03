# language: Python, file: main.py, target: Python 3.10+, Pyrogram
"""
Telegram Restricted Content Downloader & Business Platform Bot.
Main runner script with Multi-Worker Priority Queue, Admin Pool, and Signal Handling.
"""

import os
import sys
import asyncio

# Ensure clean event loop on Python 3.12+
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# Critical: Telegram 64-bit Channel ID support for Pyrogram
import pyrogram.utils
pyrogram.utils.MIN_CHANNEL_ID = -1009999999999
pyrogram.utils.MAX_CHANNEL_ID = -1000000000000
from pyrogram import Client, idle
import config
from config import API_ID, API_HASH, BOT_TOKEN, USERBOT_SESSIONS, ADMIN_IDS, TEMP_DOWNLOAD_DIR
from database import db
from core.client_manager import stop_all_user_clients, initialize_admin_pool, get_configured_proxy, warmup_all_active_sessions
from core.queue_manager import job_queue
from core.idempotency_guard import install_idempotency_guard

# Force UTF-8 for console output on Windows to prevent UnicodeEncodeError
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def check_configuration():
    """Validates that Telegram credentials are provided, or prompts interactively."""
    global API_ID, API_HASH, BOT_TOKEN
    import config

    if not config.API_ID or not config.API_HASH or not config.BOT_TOKEN:
        if sys.stdin and sys.stdin.isatty():
            print("\n" + "=" * 60)
            print("🚀 QUICK SETUP WIZARD (Credentials Missing)")
            print("=" * 60)
            try:
                bot_token = input("1. Enter BOT_TOKEN (from @BotFather): ").strip()
                api_id_str = input("2. Enter API_ID (from my.telegram.org): ").strip()
                api_hash = input("3. Enter API_HASH (from my.telegram.org): ").strip()
                admin_id_str = input("4. Enter your Telegram User ID (optional, for admin panel): ").strip()

                if bot_token and api_id_str and api_hash:
                    env_path = config.BASE_DIR / ".env"
                    env_content = (
                        f"TELEGRAM_BOT_TOKEN={bot_token}\n"
                        f"TELEGRAM_API_ID={api_id_str}\n"
                        f"TELEGRAM_API_HASH={api_hash}\n"
                        f"ADMIN_IDS={admin_id_str}\n"
                        f"BKASH_NUMBER=017XXXXXXXX\n"
                        f"NAGAD_NUMBER=018XXXXXXXX\n"
                    )
                    with open(env_path, "w", encoding="utf-8") as f:
                        f.write(env_content)
                    print("\n[+] Credentials saved to .env successfully!")
                    config.BOT_TOKEN = bot_token
                    config.API_ID = int(api_id_str)
                    config.API_HASH = api_hash
                    if admin_id_str.isdigit():
                        config.ADMIN_IDS = [int(admin_id_str)]
                    return True
            except Exception as e:
                print(f"[!] Interactive setup error: {e}")

        missing = []
        if not config.API_ID:
            missing.append("TELEGRAM_API_ID")
        if not config.API_HASH:
            missing.append("TELEGRAM_API_HASH")
        if not config.BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")

        print("\n" + "=" * 60)
        print("⚠️  CONFIGURATION NEEDED:")
        print(f"Missing required settings: {', '.join(missing)}")
        print("\nPlease update '.env' or 'config.py':")
        print("  - TELEGRAM_API_ID   : Obtain from https://my.telegram.org")
        print("  - TELEGRAM_API_HASH : Obtain from https://my.telegram.org")
        print("  - TELEGRAM_BOT_TOKEN: Obtain from @BotFather")
        print("=" * 60 + "\n")
        return False

    return True


async def _downloads_auto_janitor():
    """
    Industrial-grade disk garbage collector.
    Runs every 2 hours to sweep any leftover/aborted download files older than 2 hours.
    Prevents VPS disk exhaustion.
    """
    import time
    while True:
        try:
            now = time.time()
            if os.path.exists(TEMP_DOWNLOAD_DIR):
                for fname in os.listdir(TEMP_DOWNLOAD_DIR):
                    fpath = os.path.join(TEMP_DOWNLOAD_DIR, fname)
                    if os.path.isfile(fpath):
                        # If file is older than 2 hours (7200 seconds)
                        if now - os.path.getmtime(fpath) > 7200:
                            try:
                                os.remove(fpath)
                                print(f"[Janitor] Cleaned stale temp file: {fname}")
                            except Exception:
                                pass
        except Exception as e:
            print(f"[!] Janitor sweep error: {e}")
        await asyncio.sleep(7200)


def disable_windows_quick_edit():
    """Prevents Windows console from freezing when clicked."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h_stdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
            new_mode = (mode.value & ~0x0040) | 0x0080
            kernel32.SetConsoleMode(h_stdin, new_mode)
    except Exception:
        pass


def prevent_windows_sleep():
    """Prevents Windows PC from sleeping while bot is running."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000040)
    except Exception:
        pass


def auto_optimize_linux_network():
    """
    Automatically applies Google BBR Congestion Control and expands TCP socket buffers
    on Linux VPS (Hostinger KVM 4) for sustained 50+ MB/s MTProto wire speed.
    Fails silently on Windows or non-root environments without crashing.
    """
    if sys.platform != "linux":
        return

    import shutil
    import subprocess

    sysctl_bin = shutil.which("sysctl")
    if not sysctl_bin:
        return

    tuning_params = [
        ("net.core.default_qdisc", "fq"),
        ("net.ipv4.tcp_congestion_control", "bbr"),
        ("net.core.rmem_max", "16777216"),
        ("net.core.wmem_max", "16777216"),
        ("net.ipv4.tcp_rmem", "4096 87380 16777216"),
        ("net.ipv4.tcp_wmem", "4096 65536 16777216"),
        ("net.ipv4.tcp_fastopen", "3"),
    ]

    applied = 0
    for key, val in tuning_params:
        try:
            res = subprocess.run(
                [sysctl_bin, "-w", f"{key}={val}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if res.returncode == 0:
                applied += 1
        except Exception:
            pass

    if applied > 0:
        print(f"[⚡ TURBO KERNEL] Applied Linux BBR & TCP buffer optimizations ({applied} parameters tuned).")


async def main():
    # Automatically tune Linux network kernel on VPS for 50+ MB/s wire speed
    auto_optimize_linux_network()

    # Force UTF-8 for console output on Windows
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # Start automated background disk cleaner
    asyncio.create_task(_downloads_auto_janitor())

    print("[*] Initializing Business Database...")
    await db.init()
    print("[+] Database initialized with monetization schema.")

    # Automated session & worker recovery from git stash, sibling databases, and backups
    try:
        from core.auto_recover import run_auto_recovery
        run_auto_recovery(config.DB_PATH)
    except Exception as e:
        print(f"[!] Auto-recovery warning: {e}")

    # Pre-warm the asyncio thread pool so first OpenCV/PIL call has zero cold-start delay
    import concurrent.futures
    loop = asyncio.get_running_loop()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=16)
    loop.set_default_executor(pool)
    # Fire 8 dummy tasks to pre-spawn the threads immediately
    await asyncio.gather(*[
        asyncio.to_thread(lambda: None) for _ in range(8)
    ])
    print("[+] Thread pool pre-warmed (16 workers ready).")

    if not check_configuration():
        print("[!] Bot cannot start without valid credentials. Please configure config.py.")
        return

    # Start the priority multi-worker queue
    await job_queue.start()

    # Initialize shared admin pool if provided
    if USERBOT_SESSIONS:
        print("[*] Initializing Admin Session Pool...")
        await initialize_admin_pool(USERBOT_SESSIONS)

    # Pre-warm all active user sessions with 12s timeout so personal userbots are ready before bot accepts messages
    try:
        print("[*] Warming up active userbot sessions from database...")
        await asyncio.wait_for(warmup_all_active_sessions(), timeout=12.0)
    except asyncio.TimeoutError:
        print("[!] Session warmup reached timeout; continuing remaining in background...")
    except Exception as e:
        print(f"[!] Session warmup error: {e}")

    # Disable Windows console freeze and keep PC awake 24/7
    disable_windows_quick_edit()
    prevent_windows_sleep()

    # Dynamic bot session name based on token ID to prevent cross-bot session collisions
    bot_id = BOT_TOKEN.split(":")[0] if ":" in BOT_TOKEN else "restricted_saver_bot"
    session_name = f"bot_{bot_id}"

    # Auto-clean legacy mismatched session if token was changed
    legacy_session = os.path.join("sessions", "restricted_saver_bot.session")
    if os.path.exists(legacy_session):
        try:
            import sqlite3
            conn = sqlite3.connect(legacy_session)
            row = conn.execute("SELECT user_id FROM sessions LIMIT 1").fetchone()
            conn.close()
            if row and str(row[0]) != str(bot_id):
                os.remove(legacy_session)
                print(f"[+] Detected bot token migration from {row[0]} to {bot_id}. Purged legacy session.")
        except Exception:
            pass

    print(f"[*] Starting Telegram Bot Client ({session_name})...")
    bot = Client(
        name=session_name,
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins=dict(root="handlers"),
        workdir="sessions",
        max_concurrent_transmissions=20,  # doubled for higher batch throughput
        workers=32,                         # more parallel task runners
        ipv6=False,
        proxy=get_configured_proxy(),
        sleep_threshold=60,                 # handle FloodWait faster
    )

    # Attach Anti-Duplicate Idempotency Guard to prevent double execution and duplicate messages
    install_idempotency_guard(bot)

    started = False
    for attempt in range(1, 11):
        try:
            await bot.start()
            started = True
            break
        except Exception as e:
            err_msg = str(e).lower()
            if "database is locked" in err_msg:
                print(f"[!] Session database is locked (attempt {attempt}/10). Cleaning lock & retrying in 2s...")
                import glob
                for j_file in glob.glob(os.path.join("sessions", "*.session-journal")):
                    try:
                        os.remove(j_file)
                    except Exception:
                        pass
                await asyncio.sleep(2)
            elif any(k in err_msg for k in ("network", "timeout", "connection", "connect", "flood")):
                print(f"[!] Network issue during Telegram start (attempt {attempt}/10): {e}. Retrying in 4s...")
                await asyncio.sleep(4)
            else:
                print(f"[!] Error starting bot client (attempt {attempt}/10): {e}. Retrying in 3s...")
                await asyncio.sleep(3)

    if not started:
        print("[!] Fatal: Could not connect to Telegram after 10 attempts. Exiting for supervisor restart.")
        await job_queue.stop()
        return

    me = await bot.get_me()
    print("=" * 65)
    print(f"🚀 Telegram Bot IS ONLINE: @{me.username} ({me.first_name})")
    print(f"👑 Admin IDs configured: {config.ADMIN_IDS}")
    print("⚡ Priority Multi-Worker Queue: ACTIVE")
    print("🛡️ Anti-Ban Engine & Device Fingerprinting: ACTIVE")

    # Start silent 24-hour automated database backup daemon
    from handlers.admin import start_auto_backup_loop
    asyncio.create_task(start_auto_backup_loop(bot))
    print("💾 Automated 24h Cloud Database Backup Daemon: ACTIVE")
    print("=" * 65)

    # Register bot menu commands in Telegram UI
    try:
        from pyrogram.types import BotCommand
        await bot.set_bot_commands([
            BotCommand("start", "Start bot & view dashboard"),
            BotCommand("setup", "Watermark (text, headline, clip)"),
            BotCommand("login", "Connect Telegram account for restricted content"),
            BotCommand("batch", "Multi-link batch queue downloader"),
            BotCommand("range", "Range batch clone (/range link 1 50)"),
            BotCommand("topic", "Download from forum topic group"),
            BotCommand("settings", "Thumbnail, caption, templates, auto-forward"),
            BotCommand("premium", "Lifetime VIP Premium (bKash/Nagad)"),
            BotCommand("status", "Current batch & account status"),
            BotCommand("cancel", "Stop the current active batch"),
            BotCommand("logout", "Disconnect your Telegram account"),
        ])
        print("[+] Telegram Bot menu commands registered.")
    except Exception as e:
        print(f"[!] Could not set bot commands: {e}")

    print("[*] Listening for restricted links, web videos, user sessions, and payments...", flush=True)

    # Resilient 24/7 idle loop on Windows
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[!] Idle loop exception: {e}", flush=True)

    print("\n[*] Stopping bot, priority queue, and user clients...", flush=True)
    await job_queue.stop()
    await stop_all_user_clients()
    try:
        await bot.stop()
    except Exception:
        pass
    print("[+] Bot stopped cleanly.", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n[+] Exited.", flush=True)
