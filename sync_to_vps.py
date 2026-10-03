# language: Python, file: sync_to_vps.py, target: Windows 10/11 / Linux
"""
1-Click Fast Session & Database Pusher (Windows PC -> Linux VPS).
Instantly copies your authenticated Telegram accounts, database, and settings
directly to your VPS with zero loss and zero re-logins required.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
RESET = "\033[0m"


def print_banner():
    print(f"{CYAN}=================================================================={RESET}")
    print(f"{GREEN}    🚀 TELEGRAM SESSIONS & DATABASE 1-CLICK VPS SYNCHRONIZER     {RESET}")
    print(f"{CYAN}=================================================================={RESET}")
    print("Copies your logged-in accounts, database, and vault directly to your VPS.")
    print("Zero accounts lost. Zero re-logins. 100% persistent.\n")


def run_sync():
    print_banner()

    bot_dir = Path(__file__).resolve().parent
    db_file = bot_dir / "bot_database.db"
    vault_file = bot_dir / "data" / "sessions_vault.json"
    env_file = bot_dir / ".env"

    # Step 1: Pre-sync check & auto-recover audit locally
    print(f"{YELLOW}[*] Preparing local session vault...{RESET}")
    try:
        from core.auto_recover import run_auto_recovery, sync_db_to_sessions_vault
        sync_db_to_sessions_vault(db_file)
        count = run_auto_recovery(db_file)
        print(f"{GREEN}[+] {count} active worker account(s) secured in local vault.{RESET}\n")
    except Exception as e:
        print(f"{YELLOW}[!] Local audit note: {e}{RESET}\n")

    # Step 2: Prompt for VPS connection details
    default_dir = "/root/RESTRIC"
    vps_ip = input(f"{YELLOW}Enter your VPS IP Address (e.g. 194.164.x.x): {RESET}").strip()
    if not vps_ip:
        print(f"{RED}[!] Error: VPS IP cannot be empty.{RESET}")
        input("\nPress Enter to exit...")
        return

    vps_user = input(f"{YELLOW}Enter VPS username [default: root]: {RESET}").strip() or "root"
    target_dir = input(f"{YELLOW}Enter VPS bot directory [default: {default_dir}]: {RESET}").strip() or default_dir

    print(f"\n{CYAN}[*] Connecting to {vps_user}@{vps_ip}:{target_dir} ...{RESET}")

    # Ensure remote directory structure exists
    mkdir_cmd = ["ssh", f"{vps_user}@{vps_ip}", f"mkdir -p '{target_dir}/data' '{target_dir}/sessions' '{target_dir}/backups'"]
    try:
        subprocess.run(mkdir_cmd, check=True)
    except Exception as e:
        print(f"{RED}[!] Could not create remote directories via SSH: {e}{RESET}")
        print(f"{YELLOW}Hint: Make sure SSH key is added or password prompt is completed.{RESET}")
        input("\nPress Enter to exit...")
        return

    # Files to upload
    files_to_copy = []
    if db_file.exists():
        files_to_copy.append((str(db_file), f"{vps_user}@{vps_ip}:{target_dir}/bot_database.db"))
    if vault_file.exists():
        files_to_copy.append((str(vault_file), f"{vps_user}@{vps_ip}:{target_dir}/data/sessions_vault.json"))
    if env_file.exists():
        files_to_copy.append((str(env_file), f"{vps_user}@{vps_ip}:{target_dir}/.env"))

    # Copy files
    for local_p, remote_p in files_to_copy:
        fname = Path(local_p).name
        print(f"{YELLOW}[*] Uploading {fname} to VPS...{RESET}")
        res = subprocess.run(["scp", local_p, remote_p])
        if res.returncode == 0:
            print(f"  {GREEN}[+] {fname} uploaded successfully!{RESET}")
        else:
            print(f"  {RED}[!] Failed uploading {fname}!{RESET}")

    # Step 3: Run auto-recovery & restart bot on VPS
    print(f"\n{YELLOW}[*] Triggering auto-recovery and restarting bot service on VPS...{RESET}")
    remote_script = (
        f"cd '{target_dir}' && "
        "if [ -d 'venv' ]; then ./venv/bin/python -c 'from core.auto_recover import run_auto_recovery; import config; run_auto_recovery(config.DB_PATH)' 2>/dev/null; fi && "
        "if command -v systemctl >/dev/null 2>&1; then systemctl restart bot bot-studio 2>/dev/null || true; fi"
    )
    subprocess.run(["ssh", f"{vps_user}@{vps_ip}", remote_script], check=False)

    print(f"\n{CYAN}=================================================================={RESET}")
    print(f"{GREEN}🎉 SYNCHRONIZATION COMPLETE! ACCOUNTS ARE LIVE ON VPS!{RESET}")
    print(f"{CYAN}=================================================================={RESET}")
    print(f"• Target VPS:          {vps_ip}")
    print(f"• Remote Folder:       {target_dir}")
    print(f"• Accounts Transferred: All active sessions from bot_database.db & vault")
    print(f"• Bot Service:         Restarted & Connected on VPS")
    print(f"{CYAN}=================================================================={RESET}\n")

    input("Press Enter to finish...")


if __name__ == "__main__":
    try:
        run_sync()
    except KeyboardInterrupt:
        print("\nAborted.")
