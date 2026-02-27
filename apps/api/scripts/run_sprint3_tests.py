#!/usr/bin/env python3
"""
Run Sprint 3 testable results without pytest.
Simulates worker completion (UPDATE anonymous_users + set job DONE) to verify pricing flow.
Usage: from apps/api: PYTHONPATH=.. python3 scripts/run_sprint3_tests.py
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


def _simulate_worker_completion(conn, job_id: str):
    row = conn.execute("SELECT anonymous_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return
    anonymous_id = row[0]
    conn.execute("UPDATE jobs SET status = 'DONE' WHERE id = ?", (job_id,))
    if anonymous_id:
        conn.execute(
            "UPDATE anonymous_users SET total_completed = total_completed + 1 WHERE id = ?",
            (anonymous_id,),
        )
    conn.commit()


def main():
    errors = []
    with TestClient(app) as client:
        # 1. Complete job with anonymous_id -> total_completed increases by 1
        uid = str(uuid.uuid4())
        r = client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid})
        if r.status_code != 200:
            errors.append(f"create job: got {r.status_code}")
        else:
            job_id = r.json()["job_id"]
            conn = sqlite3.connect(_test_db_path)
            _simulate_worker_completion(conn, job_id)
            row = conn.execute("SELECT total_completed FROM anonymous_users WHERE id = ?", (uid,)).fetchone()
            conn.close()
            if not row or row[0] != 1:
                errors.append("total_completed should be 1 after one job completed")

        # 2. After one DONE, next create returns 402
        r2 = client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid})
        if r2.status_code != 402:
            errors.append(f"next create should 402: got {r2.status_code}")

    os.unlink(_test_db_path)

    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("Sprint 3: all checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
