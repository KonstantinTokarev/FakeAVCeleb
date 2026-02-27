#!/usr/bin/env python3
"""
Run Sprint 2 testable results without pytest.
Usage: from apps/api: PYTHONPATH=.. python3 scripts/run_sprint2_tests.py
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db.close()
_test_db_path = _test_db.name
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import sqlite3
from fastapi.testclient import TestClient
from api.main import app


def main():
    errors = []
    with TestClient(app) as client:
        # 1. First job free
        uid1 = str(uuid.uuid4())
        r = client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid1})
        if r.status_code != 200:
            errors.append(f"1st job should be free: got {r.status_code}")

        # 2. Second job 402 when no credits (simulate total_completed=1)
        uid2 = str(uuid.uuid4())
        client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid2})
        conn = sqlite3.connect(_test_db_path)
        conn.execute("UPDATE anonymous_users SET total_completed = 1 WHERE id = ?", (uid2,))
        conn.commit()
        conn.close()
        r = client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid2})
        if r.status_code != 402:
            errors.append(f"2nd job without credits should 402: got {r.status_code}")
        elif r.json().get("detail", {}).get("code") != "PAYMENT_REQUIRED":
            errors.append("402 body should have code PAYMENT_REQUIRED")

        # 3. Second job created when has credit; paid_credits becomes 0
        uid3 = str(uuid.uuid4())
        client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid3})
        conn = sqlite3.connect(_test_db_path)
        conn.execute("UPDATE anonymous_users SET total_completed = 1, paid_credits = 1 WHERE id = ?", (uid3,))
        conn.commit()
        conn.close()
        r = client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid3})
        if r.status_code != 200:
            errors.append(f"2nd job with credit should 200: got {r.status_code}")
        else:
            conn = sqlite3.connect(_test_db_path)
            row = conn.execute("SELECT paid_credits FROM anonymous_users WHERE id = ?", (uid3,)).fetchone()
            conn.close()
            if not row or row[0] != 0:
                errors.append("paid_credits should be 0 after using credit")

        # 4. Third job free (total_completed=2 → next is 3rd = free)
        uid4 = str(uuid.uuid4())
        client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid4})
        conn = sqlite3.connect(_test_db_path)
        conn.execute("UPDATE anonymous_users SET total_completed = 2, paid_credits = 0 WHERE id = ?", (uid4,))
        conn.commit()
        conn.close()
        r = client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid4})
        if r.status_code != 200:
            errors.append(f"3rd job should be free: got {r.status_code}")
        else:
            conn = sqlite3.connect(_test_db_path)
            row = conn.execute("SELECT paid_credits FROM anonymous_users WHERE id = ?", (uid4,)).fetchone()
            conn.close()
            if not row or row[0] != 0:
                errors.append("3rd job (free) should not deduct credit")

    os.unlink(_test_db_path)

    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("Sprint 2: all checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
