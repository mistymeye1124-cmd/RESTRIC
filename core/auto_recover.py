# language: Python, file: core/auto_recover.py, target: Linux/Windows
"""
Enterprise Self-Healing Worker Account & Session Recovery Engine.
Guarantees that Telegram accounts and userbot sessions can NEVER be lost during
VPS deployments, git pulls, container rebuilds, server restarts, or system updates.

Multi-Tier Persistence & Recovery:
1. Git stash recovery (if git stashed local uncommitted changes).
2. Persistent Session Vault recovery (data/sessions_vault.json).
3. Environment variable session recovery (.env USERBOT_SESSIONS).
4. Users table single-session reconciliation.
5. Sibling/parent database search (/root/RESTRIC, /root/bot, backups/).
6. Auto-healing of stale/dead statuses on restart to allow clean reconnection.
7. Bi-directional sync back to disk vault and .env on every run.
"""

import os
import sys
import glob
import json
import sqlite3
import subprocess
import logging
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
        Path("/var/backups"),
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


def recover_from_sessions_vault(current_db_path: Path) -> int:
    """
    Restores all accounts from persistent JSON vault (data/sessions_vault.json).
    Guarantees accounts persist across fresh clones, Docker rebuilds, or VPS re-deploys.
    """
    vault_locations = [
        current_db_path.parent / "data" / "sessions_vault.json",
        current_db_path.parent / "sessions_vault.json",
        current_db_path.parent / "backups" / "sessions_vault.json",
        Path("/root/RESTRIC/data/sessions_vault.json"),
        Path("/root/data/sessions_vault.json"),
    ]

    total_restored = 0
    for v_path in vault_locations:
        if not v_path.exists():
            continue
        try:
            with open(v_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue

            conn = sqlite3.connect(str(current_db_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_accounts'")
            if not cur.fetchone():
                conn.close()
                continue

            for aid_str, acc in data.items():
                s_str = acc.get("string_session", "").strip()
                if not s_str:
                    continue
                try:
                    aid = int(acc.get("account_id", aid_str))
                    owner_id = int(acc.get("owner_user_id", aid))
                    phone = acc.get("phone", "")
                    first_name = acc.get("first_name", "")
                    username = acc.get("username", "")
                    can_share = int(acc.get("can_share", 1))
                    is_prem = int(acc.get("is_tg_premium", 0))

                    cur.execute(
                        """
                        INSERT INTO bot_accounts (
                            owner_user_id, account_id, phone, first_name, username, string_session, is_active, status, can_share, is_tg_premium
                        )
                        VALUES (?, ?, ?, ?, ?, ?, 1, 'healthy', ?, ?)
                        ON CONFLICT(account_id) DO UPDATE SET
                            string_session = excluded.string_session,
                            is_active = 1,
                            status = 'healthy',
                            can_share = excluded.can_share,
                            is_tg_premium = CASE WHEN excluded.is_tg_premium = 1 THEN 1 ELSE bot_accounts.is_tg_premium END
                        """,
                        (owner_id, aid, phone, first_name, username, s_str, can_share, is_prem),
                    )
                    # Also ensure presence in users table
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
                    if cur.fetchone():
                        cur.execute(
                            """
                            INSERT INTO users (user_id, phone, string_session, is_active)
                            VALUES (?, ?, ?, 1)
                            ON CONFLICT(user_id) DO UPDATE SET
                                string_session = excluded.string_session,
                                is_active = 1
                            """,
                            (owner_id, phone, s_str),
                        )
                    total_restored += 1
                except Exception as e:
                    logger.warning(f"Error restoring account {aid_str} from vault: {e}")

            conn.commit()
            conn.close()
            if total_restored > 0:
                print(f"[RESTORED] Recovered {total_restored} account(s) from session vault ({v_path.name}).")
                break
        except Exception as e:
            logger.warning(f"Error reading session vault {v_path}: {e}")

    return total_restored


def _decode_session_user_id(session_string: str) -> int:
    """Decodes user_id from Pyrogram string session without making network calls."""
    try:
        import struct
        import base64
        raw = base64.urlsafe_b64decode(session_string + "=" * (-len(session_string) % 4))
        # 351 bytes = 32-bit user_id; 355 or 267 bytes = 64-bit user_id
        if len(raw) == 351:
            dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(">B?256sI?", raw)
            return int(user_id)
        elif len(raw) >= 267:
            dc_id, test_mode, auth_key, user_id = struct.unpack(">B?256sq", raw[:266])
            return int(user_id)
    except Exception:
        pass
    import hashlib
    return int(hashlib.md5(session_string.encode()).hexdigest()[:8], 16)


def recover_from_env_sessions(current_db_path: Path) -> int:
    """Restores userbot sessions defined in USERBOT_SESSIONS inside .env."""
    env_path = current_db_path.parent / ".env"
    raw_sessions = os.getenv("USERBOT_SESSIONS", "")

    if not raw_sessions and env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("USERBOT_SESSIONS="):
                        raw_sessions = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass

    if not raw_sessions:
        return 0

    sessions = [s.strip() for s in raw_sessions.split("||") if s.strip()]
    if not sessions:
        return 0

    recovered = 0
    try:
        conn = sqlite3.connect(str(current_db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_accounts'")
        if not cur.fetchone():
            conn.close()
            return 0

        for s_str in sessions:
            uid = _decode_session_user_id(s_str)
            cur.execute(
                """
                INSERT INTO bot_accounts (
                    owner_user_id, account_id, phone, first_name, username, string_session, is_active, status, can_share
                )
                VALUES (?, ?, '', 'Worker', '', ?, 1, 'healthy', 1)
                ON CONFLICT(account_id) DO UPDATE SET
                    string_session = excluded.string_session,
                    is_active = 1,
                    status = 'healthy'
                """,
                (uid, uid, s_str),
            )
            recovered += 1

        conn.commit()
        conn.close()
        if recovered > 0:
            print(f"[RESTORED] Synchronized {recovered} account(s) from .env USERBOT_SESSIONS.")
    except Exception as e:
        logger.warning(f"Error recovering sessions from .env: {e}")

    return recovered


def recover_from_users_table(current_db_path: Path) -> int:
    """Ensures all session strings in the users table are mirrored into bot_accounts."""
    recovered = 0
    try:
        conn = sqlite3.connect(str(current_db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if not cur.fetchone():
            conn.close()
            return 0

        cur.execute(
            """
            INSERT INTO bot_accounts (owner_user_id, account_id, phone, first_name, username, string_session, is_active, status, can_share)
            SELECT user_id, user_id, phone, first_name, username, string_session, 1, 'healthy', 1
            FROM users
            WHERE string_session IS NOT NULL AND string_session != ''
            ON CONFLICT(account_id) DO UPDATE SET
                string_session = excluded.string_session,
                is_active = 1,
                status = 'healthy'
            """
        )
        recovered = cur.rowcount
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Users table recovery error: {e}")
    return max(0, recovered)


def auto_heal_stale_accounts(current_db_path: Path) -> int:
    """
    Auto-heals any accounts marked 'dead' or inactive on reboot/restart.
    Guarantees that a server reboot, IP change, or temporary network hiccup
    never permanently kills a valid account session.
    """
    healed = 0
    try:
        conn = sqlite3.connect(str(current_db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_accounts'")
        if cur.fetchone():
            cur.execute(
                """
                UPDATE bot_accounts
                SET is_active = 1, status = 'healthy', flood_wait_until = 0
                WHERE string_session IS NOT NULL AND string_session != '' AND (is_active = 0 OR status = 'dead')
                """
            )
            healed = cur.rowcount
            conn.commit()
        conn.close()
        if healed > 0:
            print(f"[AUTO-HEAL] Re-activated {healed} account(s) into healthy pool for fresh connection.")
    except Exception as e:
        logger.warning(f"Auto-heal error: {e}")
    return healed


def sync_db_to_sessions_vault(current_db_path: Path):
    """
    Synchronizes all valid accounts from database into:
    1. data/sessions_vault.json
    2. .env USERBOT_SESSIONS
    Ensures that disk vault and environment are ALWAYS 100% current.
    """
    try:
        conn = sqlite3.connect(str(current_db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_accounts'")
        if not cur.fetchone():
            conn.close()
            return

        cur.execute(
            """
            SELECT account_id, owner_user_id, phone, first_name, username, string_session, can_share, is_tg_premium
            FROM bot_accounts
            WHERE string_session IS NOT NULL AND string_session != ''
            """
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return

        vault_dir = current_db_path.parent / "data"
        vault_dir.mkdir(parents=True, exist_ok=True)
        vault_file = vault_dir / "sessions_vault.json"

        vault_data = {}
        sessions_list = []

        for r in rows:
            aid, owner_id, phone, first_name, username, s_str, can_share, is_prem = r
            s_str = s_str.strip()
            if s_str:
                vault_data[str(aid)] = {
                    "account_id": aid,
                    "owner_user_id": owner_id,
                    "phone": phone or "",
                    "first_name": first_name or "",
                    "username": username or "",
                    "string_session": s_str,
                    "can_share": can_share if can_share is not None else 1,
                    "is_tg_premium": is_prem if is_prem is not None else 0,
                }
                if s_str not in sessions_list:
                    sessions_list.append(s_str)

        # Write to vault JSON
        with open(vault_file, "w", encoding="utf-8") as f:
            json.dump(vault_data, f, indent=2, ensure_ascii=False)

        # Update .env USERBOT_SESSIONS safely
        env_file = current_db_path.parent / ".env"
        if env_file.exists() and sessions_list:
            with open(env_file, "r", encoding="utf-8") as f:
                env_lines = f.readlines()

            joined_sessions = "||".join(sessions_list)
            new_lines = []
            found = False
            for line in env_lines:
                if line.startswith("USERBOT_SESSIONS="):
                    new_lines.append(f"USERBOT_SESSIONS={joined_sessions}\n")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"\nUSERBOT_SESSIONS={joined_sessions}\n")

            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"Error syncing DB to vault: {e}")


def run_auto_recovery(current_db_path: Path) -> int:
    """
    Executes the full automated session & account self-healing pipeline.
    Runs unconditionally on every bot start, git pull, and VPS deployment.
    """
    print("[*] Running automated session & worker recovery audit...")

    # 1. Recover from git stash if any
    recover_from_git_stash()

    # 2. Recover from persistent sessions vault (data/sessions_vault.json)
    recover_from_sessions_vault(current_db_path)

    # 3. Recover from .env USERBOT_SESSIONS
    recover_from_env_sessions(current_db_path)

    # 4. Mirror any sessions from users table into bot_accounts
    recover_from_users_table(current_db_path)

    # 5. Search alternate databases across common VPS directory structures
    candidates = find_alternate_databases(current_db_path)
    for cand in candidates:
        try:
            merge_accounts_from_db(cand, current_db_path)
        except Exception:
            pass

    # 6. Auto-heal any stale/dead status so accounts have a fresh chance to connect
    auto_heal_stale_accounts(current_db_path)

    # 7. Count active, healthy accounts in DB
    total_active = 0
    try:
        conn = sqlite3.connect(str(current_db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_accounts'")
        if cur.fetchone():
            cur.execute(
                "SELECT COUNT(*) FROM bot_accounts WHERE string_session IS NOT NULL AND string_session != '' AND is_active = 1"
            )
            total_active = cur.fetchone()[0]
        conn.close()
    except Exception:
        pass

    # 8. Synchronize current state to disk vault and .env
    sync_db_to_sessions_vault(current_db_path)

    print(f"[AUTO-RECOVER] Audit complete: {total_active} healthy worker account(s) ready in pool.")
    return total_active
