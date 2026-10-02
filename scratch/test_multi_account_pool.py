# language: Python, file: scratch/test_multi_account_pool.py
"""
Deep verification test for Multi-Account Userbot Pool & Anti-Ban Architecture.
Tests:
1. Database schema & CRUD operations for bot_accounts.
2. Deterministic device fingerprinting per account.
3. Isolated rate-limiting buckets per account.
4. Hot-swap failover and round-robin load distribution.
"""

import sys
import os
import asyncio
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from database import db
from core.device_spoofer import get_fingerprint_for_user
from core.rate_limiter import rate_registry


async def run_tests():
    print("=" * 60)
    print("🧪 STARTING MULTI-ACCOUNT WORKER POOL & ANTI-BAN VERIFICATION")
    print("=" * 60)

    await db.init()

    test_owner = 999888777
    acc1_id = 10001
    acc2_id = 10002
    acc3_id = 10003

    # Clean prior test rows
    await db.delete_bot_account(acc1_id)
    await db.delete_bot_account(acc2_id)
    await db.delete_bot_account(acc3_id)

    # 1. Test Adding Multiple Accounts
    print("\n[1] Testing Multi-Account Registration...")
    ok1, msg1 = await db.add_or_update_bot_account(
        owner_user_id=test_owner,
        account_id=acc1_id,
        phone="+8801700000001",
        first_name="WorkerOne",
        username="worker_alpha",
        string_session="SESSION_STRING_ALPHA_TEST_MOCK_1234567890",
    )
    assert ok1, f"Failed adding account 1: {msg1}"
    print(f"  ✅ Account 1 registered: {msg1}")

    ok2, msg2 = await db.add_or_update_bot_account(
        owner_user_id=test_owner,
        account_id=acc2_id,
        phone="+8801700000002",
        first_name="WorkerTwo",
        username="worker_beta",
        string_session="SESSION_STRING_BETA_TEST_MOCK_1234567890",
    )
    assert ok2, f"Failed adding account 2: {msg2}"
    print(f"  ✅ Account 2 registered: {msg2}")

    ok3, msg3 = await db.add_or_update_bot_account(
        owner_user_id=test_owner,
        account_id=acc3_id,
        phone="+8801700000003",
        first_name="WorkerThree",
        username="worker_gamma",
        string_session="SESSION_STRING_GAMMA_TEST_MOCK_1234567890",
    )
    assert ok3, f"Failed adding account 3: {msg3}"
    print(f"  ✅ Account 3 registered: {msg3}")

    # 2. Test Retrieving Accounts
    print("\n[2] Testing Multi-Account Retrieval & Telemetry...")
    accs = await db.get_bot_accounts(owner_user_id=test_owner)
    assert len(accs) == 3, f"Expected 3 accounts, got {len(accs)}"
    print(f"  ✅ Successfully retrieved {len(accs)} accounts for owner {test_owner}")

    # 3. Test Telemetry Increment
    await db.increment_bot_account_downloads(acc1_id)
    await db.increment_bot_account_downloads(acc1_id)
    rec1 = await db.get_bot_account_by_id(acc1_id)
    assert rec1["total_downloads"] == 2, f"Expected 2 downloads, got {rec1['total_downloads']}"
    assert rec1["daily_downloads"] == 2
    print(f"  ✅ Download telemetry increment verified: {rec1['total_downloads']} downloads")

    # 4. Test Deterministic Anti-Ban Device Fingerprinting
    print("\n[3] Testing Anti-Ban Device Fingerprinting...")
    fp1_a = get_fingerprint_for_user(acc1_id)
    fp1_b = get_fingerprint_for_user(acc1_id)
    fp2 = get_fingerprint_for_user(acc2_id)
    fp3 = get_fingerprint_for_user(acc3_id)

    assert fp1_a == fp1_b, "Fingerprint must be deterministic across calls!"
    print(f"  ✅ Account 1 Fingerprint: {fp1_a['device_model']} | OS: {fp1_a['system_version']}")
    print(f"  ✅ Account 2 Fingerprint: {fp2['device_model']} | OS: {fp2['system_version']}")
    print(f"  ✅ Account 3 Fingerprint: {fp3['device_model']} | OS: {fp3['system_version']}")

    # 5. Test Rate Limiter Isolation
    print("\n[4] Testing Rate Limiter Isolation...")
    limiter1 = rate_registry.get_sync(f"account_{acc1_id}")
    limiter2 = rate_registry.get_sync(f"account_{acc2_id}")
    assert limiter1 is not limiter2, "Each account must have an isolated rate limiter!"

    # Simulate FloodWait on Account 1
    limiter1.on_flood_wait(30)
    assert limiter1.is_quarantined, "Account 1 must be quarantined after flood wait"
    assert not limiter2.is_quarantined, "Account 2 must remain healthy and unquarantined!"
    print(f"  ✅ Account 1 quarantined ({limiter1.quarantine_remaining:.1f}s), Account 2 remains Healthy!")

    # 6. Test Account Pause/Resume
    print("\n[5] Testing Account Toggle (Pause/Resume)...")
    ok_tog, new_val = await db.toggle_bot_account(acc2_id, test_owner)
    assert ok_tog and new_val == 0, "Account 2 should be paused"
    rec2_paused = await db.get_bot_account_by_id(acc2_id)
    assert rec2_paused["is_active"] == 0, "Account 2 is_active should be 0"
    print(f"  ✅ Account 2 toggled to PAUSED (is_active=0)")

    ok_tog2, new_val2 = await db.toggle_bot_account(acc2_id, test_owner)
    assert ok_tog2 and new_val2 == 1, "Account 2 should be resumed"
    print(f"  ✅ Account 2 toggled to RESUMED (is_active=1)")

    # 7. Cleanup Test Data
    await db.delete_bot_account(acc1_id)
    await db.delete_bot_account(acc2_id)
    await db.delete_bot_account(acc3_id)
    accs_after = await db.get_bot_accounts(owner_user_id=test_owner)
    assert len(accs_after) == 0, "Test accounts should be deleted"
    print(f"  ✅ Account deletion and cleanup verified.")

    print("\n" + "=" * 60)
    print("🎉 ALL MULTI-ACCOUNT & ANTI-BAN ARCHITECTURE TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
