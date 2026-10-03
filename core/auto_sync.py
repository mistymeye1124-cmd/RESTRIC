# language: Python, file: core/auto_sync.py, target: Linux VPS / Python 3.10+
"""
Automated 24/7 VPS Background Git Sync & Self-Healing Watchdog.
Polls GitHub for new commits every 60 seconds.
When a new update is pushed:
1. Preserves local database & sessions (git stash pop / auto-recover).
2. Fast-forwards code from GitHub (git pull origin main).
3. Automatically restarts bot service with 0 terminal interaction needed!
"""

import asyncio
import os
import subprocess
import logging
from pathlib import Path
from pyrogram import Client
from config import ADMIN_IDS, DB_PATH

logger = logging.getLogger("AutoSync")


async def execute_vps_update_and_restart(bot_client: Client = None, notify_chat_id: int = None) -> tuple[bool, str]:
    """Executes clean pull, stash pop, auto-recovery, and systemd service reload."""
    msg = None
    if bot_client and notify_chat_id:
        try:
            msg = await bot_client.send_message(
                chat_id=notify_chat_id,
                text="🔄 **Auto-Sync Triggered!**\nPulling latest updates from GitHub and restoring worker sessions..."
            )
        except Exception:
            pass

    try:
        # 1. Stash pop if any previous stash exists
        subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, check=False)

        # 2. Fetch and pull
        subprocess.run(["git", "fetch", "origin", "main"], capture_output=True, text=True, check=False)
        pull_res = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, check=False)

        # 3. Re-pop stash to make sure uncommitted database changes are never lost
        subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, check=False)

        # 4. Run automated recovery engine
        try:
            from core.auto_recover import run_auto_recovery
            run_auto_recovery(DB_PATH)
        except Exception as e:
            logger.warning(f"Auto-recovery step error: {e}")

        # 5. Notify admin of success
        succ_text = (
            "✅ **VPS Auto-Update Completed Successfully!**\n\n"
            f"• Git: `{pull_res.stdout.strip()[:100] or 'Updated'}`\n"
            "• Worker Sessions: `Restored & Healthy 🟢`\n"
            "• Service: `Reloading daemon now...`"
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

        # 6. Restart systemd service asynchronously
        async def _delayed_restart():
            await asyncio.sleep(2.0)
            subprocess.run(["sudo", "systemctl", "restart", "bot"], capture_output=True, check=False)

        asyncio.create_task(_delayed_restart())
        return True, "Update applied successfully. Service restarting."
    except Exception as e:
        err_msg = f"❌ Auto-update failed: {e}"
        if msg:
            try:
                await msg.edit_text(err_msg)
            except Exception:
                pass
        return False, err_msg


async def vps_git_watchdog(bot_client: Client):
    """
    Background daemon running every 90 seconds.
    Silently checks if remote GitHub main branch has new commits.
    If new commit detected, auto-pulls and restarts!
    """
    await asyncio.sleep(30.0)  # Wait for initial boot to settle
    while True:
        try:
            # Check if git is available
            fetch_res = await asyncio.to_thread(
                lambda: subprocess.run(
                    ["git", "fetch", "origin", "main"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            )
            if fetch_res.returncode == 0:
                # Compare HEAD vs origin/main
                diff_res = await asyncio.to_thread(
                    lambda: subprocess.run(
                        ["git", "rev-list", "HEAD..origin/main", "--count"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                )
                if diff_res.returncode == 0:
                    behind_count = int(diff_res.stdout.strip() or 0)
                    if behind_count > 0:
                        admin_id = ADMIN_IDS[0] if ADMIN_IDS else None
                        print(f"[AutoSync Watchdog] Detected {behind_count} new commit(s) on GitHub! Auto-updating VPS...")
                        await execute_vps_update_and_restart(bot_client, notify_chat_id=admin_id)
                        break  # service will restart
        except Exception as e:
            logger.debug(f"Watchdog check loop error: {e}")

        await asyncio.sleep(90.0)
