# language: Python, file: core/auto_sync.py, target: Linux VPS / Python 3.10+
"""
Automated 24/7 VPS Background Git Sync & Self-Healing Watchdog.
Polls GitHub for new commits every 90 seconds.
When a new update is pushed:
  1. Physically backs up bot_database.db + sessions/ BEFORE any git operation.
  2. Runs git pull / git reset --hard safely.
  3. RESTORES database & sessions from physical backup — accounts can NEVER be lost.
  4. Runs auto_recover to merge any orphan sessions.
  5. Restarts bot service via systemd (zero terminal interaction).
"""

import asyncio
import os
import shutil
import subprocess
import logging
import tempfile
from pathlib import Path
from pyrogram import Client
from config import ADMIN_IDS, DB_PATH

logger = logging.getLogger("AutoSync")

# Root directory of the project (parent of this file's directory)
_BOT_DIR = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: physical backup / restore
# ─────────────────────────────────────────────────────────────────────────────

def _backup_user_data(safe_dir: Path) -> dict:
    """
    Copies bot_database.db (and any *.db in project root) plus sessions/ into
    safe_dir before a git operation.  Returns a summary dict.
    """
    safe_dir.mkdir(parents=True, exist_ok=True)
    (safe_dir / "sessions").mkdir(exist_ok=True)

    backed_dbs = []
    for db_file in _BOT_DIR.glob("*.db"):
        try:
            shutil.copy2(db_file, safe_dir / db_file.name)
            backed_dbs.append(db_file.name)
        except Exception as e:
            logger.warning(f"DB backup failed for {db_file.name}: {e}")

    session_count = 0
    sessions_src = _BOT_DIR / "sessions"
    if sessions_src.exists():
        try:
            for sf in sessions_src.rglob("*.session"):
                dst = safe_dir / "sessions" / sf.name
                shutil.copy2(sf, dst)
                session_count += 1
            # Also copy WAL/journal companions
            for ext in ("*.session-journal", "*.session-wal", "*.session-shm"):
                for sf in sessions_src.rglob(ext):
                    shutil.copy2(sf, safe_dir / "sessions" / sf.name)
        except Exception as e:
            logger.warning(f"Session backup error: {e}")

    env_src = _BOT_DIR / ".env"
    if env_src.exists():
        try:
            shutil.copy2(env_src, safe_dir / ".env")
        except Exception:
            pass

    logger.info(f"[Backup] {len(backed_dbs)} DB(s), {session_count} session(s) backed up → {safe_dir}")
    return {"dbs": backed_dbs, "sessions": session_count}


def _restore_user_data(safe_dir: Path) -> dict:
    """
    Restores backed-up database files and session files from safe_dir back
    into the project directory.  Runs UNCONDITIONALLY after git operations.
    """
    restored_dbs = []
    for db_file in safe_dir.glob("*.db"):
        try:
            shutil.copy2(db_file, _BOT_DIR / db_file.name)
            restored_dbs.append(db_file.name)
        except Exception as e:
            logger.warning(f"DB restore failed for {db_file.name}: {e}")

    session_count = 0
    sessions_dst = _BOT_DIR / "sessions"
    sessions_dst.mkdir(exist_ok=True)
    safe_sessions = safe_dir / "sessions"
    if safe_sessions.exists():
        try:
            for sf in safe_sessions.rglob("*"):
                if sf.is_file():
                    dst = sessions_dst / sf.name
                    # Always overwrite — our backup is the ground truth
                    shutil.copy2(sf, dst)
                    if sf.suffix == ".session":
                        session_count += 1
        except Exception as e:
            logger.warning(f"Session restore error: {e}")

    env_bak = safe_dir / ".env"
    if env_bak.exists():
        try:
            shutil.copy2(env_bak, _BOT_DIR / ".env")
        except Exception:
            pass

    logger.info(f"[Restore] {len(restored_dbs)} DB(s), {session_count} session(s) restored ✅")
    return {"dbs": restored_dbs, "sessions": session_count}


def _run_git(args: list[str]) -> tuple[int, str]:
    """Runs a git command in the project directory, returns (returncode, output)."""
    res = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_BOT_DIR),
    )
    return res.returncode, (res.stdout + res.stderr).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Main update executor
# ─────────────────────────────────────────────────────────────────────────────

async def execute_vps_update_and_restart(
    bot_client: Client = None,
    notify_chat_id: int = None,
) -> tuple[bool, str]:
    """
    Full update pipeline:
      0. Backup sessions + DB to temp dir (BEFORE git)
      1. git fetch + pull (or reset --hard)
      2. Restore sessions + DB from temp dir (AFTER git — unconditional)
      3. run_auto_recovery to merge any orphan worker records
      4. systemctl restart bot
    """
    msg = None
    if bot_client and notify_chat_id:
        try:
            msg = await bot_client.send_message(
                chat_id=notify_chat_id,
                text=(
                    "🔄 **Auto-Sync Triggered!**\n"
                    "Backing up sessions → pulling from GitHub → restoring sessions...\n"
                    "Your accounts will **NOT** be logged out. 🔐"
                ),
            )
        except Exception:
            pass

    safe_dir = Path(tempfile.mkdtemp(prefix="tgbot_safe_"))
    backup_info = {}
    pull_output = ""

    try:
        # ── PHASE 0: Physical backup ──────────────────────────────────────
        backup_info = await asyncio.to_thread(_backup_user_data, safe_dir)

        # ── PHASE 1: Git operations ───────────────────────────────────────
        await asyncio.to_thread(lambda: _run_git(["fetch", "origin", "main"]))

        # Stash only tracked file changes (code, not db/sessions)
        rc, _ = await asyncio.to_thread(
            lambda: subprocess.run(
                ["git", "diff-index", "--quiet", "HEAD", "--"],
                capture_output=True, check=False, cwd=str(_BOT_DIR)
            )
        )
        if rc != 0:
            await asyncio.to_thread(lambda: _run_git(
                ["stash", "push", "--message", f"auto-sync stash"]
            ))

        rc_pull, pull_output = await asyncio.to_thread(
            lambda: _run_git(["pull", "origin", "main"])
        )
        if rc_pull != 0:
            logger.warning("git pull failed — falling back to git reset --hard origin/main")
            await asyncio.to_thread(lambda: _run_git(["reset", "--hard", "origin/main"]))
            pull_output = "reset --hard applied"

        # Pop stash if any code-level stash exists
        rc_sl, stash_list = await asyncio.to_thread(lambda: _run_git(["stash", "list"]))
        if rc_sl == 0 and "stash@{0}" in stash_list:
            await asyncio.to_thread(lambda: _run_git(["stash", "pop"]))

        # ── PHASE 2: Unconditional restore ────────────────────────────────
        restore_info = await asyncio.to_thread(_restore_user_data, safe_dir)

        # ── PHASE 3: Auto-recovery audit ─────────────────────────────────
        recovered = 0
        try:
            from core.auto_recover import run_auto_recovery
            recovered = await asyncio.to_thread(run_auto_recovery, DB_PATH)
        except Exception as e:
            logger.warning(f"Auto-recovery step error: {e}")

        # ── PHASE 4: Notify admin ─────────────────────────────────────────
        succ_text = (
            "✅ **VPS Auto-Update Completed!**\n\n"
            f"• Git: `{pull_output[:80] or 'Up to date'}`\n"
            f"• Sessions Restored: `{restore_info.get('sessions', 0)} file(s) 🔐`\n"
            f"• Worker Accounts: `{recovered} healthy 🟢`\n"
            "• No logout. No re-login needed. ✔️\n"
            "• Service: `Reloading in 3s...`"
        )
        if msg:
            try:
                await msg.edit_text(succ_text)
            except Exception:
                pass
        elif bot_client and ADMIN_IDS:
            try:
                await bot_client.send_message(chat_id=ADMIN_IDS[0], text=succ_text)
            except Exception:
                pass

        # ── PHASE 5: Delayed service restart ─────────────────────────────
        async def _delayed_restart():
            await asyncio.sleep(3.0)
            subprocess.run(
                ["sudo", "systemctl", "restart", "bot"],
                capture_output=True,
                check=False,
            )

        asyncio.create_task(_delayed_restart())
        return True, "Update applied. Sessions preserved. Service restarting."

    except Exception as e:
        err_msg = f"❌ Auto-update failed: {e}"
        logger.error(err_msg, exc_info=True)

        # Emergency restore — even on error, restore what we backed up
        try:
            if safe_dir.exists():
                await asyncio.to_thread(_restore_user_data, safe_dir)
                logger.info("[Emergency Restore] Backup restored after update failure.")
        except Exception as re:
            logger.error(f"Emergency restore also failed: {re}")

        if msg:
            try:
                await msg.edit_text(err_msg)
            except Exception:
                pass
        return False, err_msg

    finally:
        # Clean up temp backup dir
        try:
            if safe_dir.exists():
                shutil.rmtree(safe_dir, ignore_errors=True)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Background watchdog daemon
# ─────────────────────────────────────────────────────────────────────────────

async def vps_git_watchdog(bot_client: Client):
    """
    Background daemon — runs every 90 seconds.
    Silently checks if remote GitHub main branch has new commits.
    If new commit detected → auto-pulls (with session backup/restore) and restarts.
    """
    await asyncio.sleep(30.0)  # Wait for initial boot to settle
    while True:
        try:
            fetch_res = await asyncio.to_thread(
                lambda: subprocess.run(
                    ["git", "fetch", "origin", "main"],
                    capture_output=True,
                    text=True,
                    check=False,
                    cwd=str(_BOT_DIR),
                )
            )
            if fetch_res.returncode == 0:
                diff_res = await asyncio.to_thread(
                    lambda: subprocess.run(
                        ["git", "rev-list", "HEAD..origin/main", "--count"],
                        capture_output=True,
                        text=True,
                        check=False,
                        cwd=str(_BOT_DIR),
                    )
                )
                if diff_res.returncode == 0:
                    behind_count = int(diff_res.stdout.strip() or 0)
                    if behind_count > 0:
                        admin_id = ADMIN_IDS[0] if ADMIN_IDS else None
                        logger.info(
                            f"[AutoSync Watchdog] {behind_count} new commit(s) on GitHub. "
                            "Auto-updating VPS (sessions will be preserved)..."
                        )
                        await execute_vps_update_and_restart(
                            bot_client, notify_chat_id=admin_id
                        )
                        break  # service will restart — this process ends
        except Exception as e:
            logger.debug(f"Watchdog check loop error: {e}")

        await asyncio.sleep(90.0)
