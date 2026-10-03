# language: Python, file: core/auto_recover.py, target: Linux/Windows
"""
Self-Healing Worker Account & Session Recovery Engine.
Automatically detects and recovers lost Telegram worker sessions from:
1. Git stash (if update.sh stashed local uncommitted database)
2. Sibling/parent directories (/root/RESTRIC, /root/bot, backups/)
3. WAL/journal checkpoints
4. Users table single-session records
"""

import os
import sys
import glob
import sqlite3
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("AutoRecover")


def recover_from_git_stash():
    """Pops or applies git stash if VPS update.sh stashed the database."""
    try:
        check = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode == 0 and check.stdout.strip():
            print("[AutoRecover] Detected git stash entries on VPS. Restoring stashed data...")
            pop_res = subprocess.run(
                ["git", "stash", "pop"],
                capture_output=True,
                text=True,
                check=False,
            )
            print(f"[AutoRecover] git stash pop output: {pop_res.stdout.strip() or pop_res.stderr.strip()}")
            return True
    except Exception as e:
        logger.warning(f"Git stash recovery error: {e}")
    return False


def find_alternate_databases(current_db_path: Path) -> list:
    """Finds all potential database files across common VPS directory structures."""
    candidates = []
    search_dirs = [
        current_db_path.parent,
        current_db_path.parent.parent,
        Path("/root"),
        Path("/root/RESTRIC"),
        Path("/root/bot"),
        Path("/home"),
        current_db_path.parent / "backups",
    ]

    for d in search_dirs:
        if d.exists() and d.is_dir():
            try:
                for f in d.glob("*.db"):
                    resolved = f.resolve()
                    if resolved != current_db_path.resolve() and resolved.exists():
                        candidates.append(resolved)
            except Exception:
                pass
    return list(set(candidates))


def merge_accounts_from_db(source_db_path: Path, target_db_path: Path) -> int:
    """Safely extracts accounts from a source DB and merges into target DB."""
    if not source_db_path.exists() or not target_db_path.exists():
        return 0

    recovered_count = 0
    try:
        s_conn = sqlite3.connect(str(source_db_path))
        s_cur = s_conn.cursor()

        # Check if source has bot_accounts table
        s_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_accounts'")
        if not s_cur.fetchone():
            s_conn.close()
            return 0

        # Extract all accounts from source
        s_cur.execute(
            """
            SELECT owner_user_id, account_id, phone, first_name, username, string_session, is_active, status, can_share
            FROM bot_accounts
            WHERE string_session IS NOT NULL AND string_session != ''
            """
        )
        rows = s_cur.fetchall()
        s_conn.close()

        if not rows:
            return 0

        t_conn = sqlite3.connect(str(target_db_path))
        t_cur = t_conn.cursor()
        for r in rows:
            try:
                t_cur.execute(
                    """
                    INSERT INTO bot_accounts (
                        owner_user_id, account_id, phone, first_name, username, string_session, is_active, status, can_share
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_id) DO UPDATE SET
                        string_session = excluded.string_session,
                        is_active = 1,
                        status = 'healthy'
                    """,
                    r,
                )
                recovered_count += 1
            except Exception as e:
                logger.warning(f"Error inserting account {r[1]}: {e}")

        t_conn.commit()
        t_conn.close()
    except Exception as e:
        logger.warning(f"Error merging accounts from {source_db_path}: {e}")

    return recovered_count


def run_auto_recovery(current_db_path: Path) -> int:
    """Executes the full recovery pipeline and returns number of accounts restored."""
    print("[*] Running automated session & worker recovery audit...")

    # 1. First attempt: recover from git stash
    recover_from_git_stash()

    # 2. Check if current database already has accounts
    total_in_current = 0
    if current_db_path.exists():
        try:
            conn = sqlite3.connect(str(current_db_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_accounts'")
            if cur.fetchone():
                cur.execute("SELECT COUNT(*) FROM bot_accounts WHERE string_session IS NOT NULL AND string_session != ''")
                total_in_current = cur.fetchone()[0]
            conn.close()
        except Exception:
            pass

    if total_in_current > 0:
        print(f"[+] Current database is healthy: {total_in_current} worker account(s) present.")
        return total_in_current

    print("[!] Current database has 0 worker accounts. Searching filesystem for alternate database files...")

    # 3. Search alternate database candidates
    candidates = find_alternate_databases(current_db_path)
    total_recovered = 0
    for cand in candidates:
        try:
            rec = merge_accounts_from_db(cand, current_db_path)
            if rec > 0:
                print(f"[✅ RESTORED] Recovered {rec} worker account(s) from alternate database: {cand}")
                total_recovered += rec
        except Exception as e:
            logger.warning(f"Failed checking {cand}: {e}")

    # 4. Check users table in current DB as fallback
    if total_recovered == 0 and current_db_path.exists():
        try:
            conn = sqlite3.connect(str(current_db_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if cur.fetchone():
                cur.execute(
                    """
                    INSERT OR IGNORE INTO bot_accounts (owner_user_id, account_id, phone, first_name, username, string_session, is_active, can_share)
                    SELECT user_id, user_id, phone, first_name, username, string_session, 1, 1
                    FROM users
                    WHERE string_session IS NOT NULL AND string_session != ''
                    """
                )
                conn.commit()
                cur.execute("SELECT COUNT(*) FROM bot_accounts")
                total_recovered = cur.fetchone()[0]
                if total_recovered > 0:
                    print(f"[✅ RESTORED] Recovered {total_recovered} worker account(s) from users session table.")
            conn.close()
        except Exception as e:
            logger.warning(f"Fallback users table recovery error: {e}")

    return total_recovered
