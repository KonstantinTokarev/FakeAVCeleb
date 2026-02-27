#!/usr/bin/env python3
"""
Run Sprint 6 testable results without pytest.
Verifies GET /api/me behavior and next_check_free flag.
Usage: from apps/api: PYTHONPATH=.. python3 scripts/run_sprint6_tests.py
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
        # 1. New user -> total_completed=0, next_check_free=True
        uid = str(uuid.uuid4())
        r = client.get("/api/me", headers={"X-Anonymous-Id": uid})
        if r.status_code != 200:
            errors.append(f"/api/me new user: expected 200, got {r.status_code}")
        else:
            data = r.json()
            if data["anonymous_id"] != uid:
                errors.append("anonymous_id mismatch")
            if data["total_completed"] != 0 or data["paid_credits"] != 0:
                errors.append("expected total_completed=0, paid_credits=0 for new user")
            if not data["next_check_free"]:
                errors.append("next_check_free should be True for first check")

        # 2. total_completed=1 -> next_check_free=False
        conn = sqlite3.connect(_test_db_path)
        conn.execute(
            "UPDATE anonymous_users SET total_completed = 1 WHERE id = ?",
            (uid,),
        )
        conn.commit()
        conn.close()

        r2 = client.get("/api/me", headers={"X-Anonymous-Id": uid})
        if r2.status_code != 200:
            errors.append(f"/api/me after update: expected 200, got {r2.status_code}")
        else:
            data2 = r2.json()
            if data2["total_completed"] != 1:
                errors.append("expected total_completed=1 after update")
            if data2["next_check_free"]:
                errors.append("next_check_free should be False when next is 2nd (paid)")

    os.unlink(_test_db_path)

    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("Sprint 6: all checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()

