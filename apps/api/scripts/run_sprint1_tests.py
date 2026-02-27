#!/usr/bin/env python3
"""
Run Sprint 1 testable results without pytest.
Usage: from apps/api: PYTHONPATH=. python3 scripts/run_sprint1_tests.py
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

# Test DB and env before importing app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db.close()
_test_db_path = _test_db.name
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from fastapi.testclient import TestClient
from api.main import app

def main():
    errors = []
    with TestClient(app) as client:
        # 1. Migration applied
        import sqlite3
        conn = sqlite3.connect(_test_db_path)
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='anonymous_users'"
            )
            if cur.fetchone() is None:
                errors.append("anonymous_users table missing")
            cur = conn.execute("PRAGMA table_info(jobs)")
            cols = [row[1] for row in cur.fetchall()]
            if "anonymous_id" not in cols:
                errors.append("jobs.anonymous_id column missing")
        finally:
            conn.close()

        # 2. POST with X-Anonymous-Id creates job with matching anonymous_id
        uid = str(uuid.uuid4())
        resp = client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid})
        if resp.status_code != 200:
            errors.append(f"create job with header: status {resp.status_code}")
        else:
            data = resp.json()
            if data.get("anonymous_id") is not None:
                errors.append("expected anonymous_id None when client provided it")
            conn = sqlite3.connect(_test_db_path)
            row = conn.execute("SELECT anonymous_id FROM jobs WHERE id = ?", (data["job_id"],)).fetchone()
            conn.close()
            if not row or row[0] != uid:
                errors.append("job.anonymous_id does not match header")

        # 3. Same X-Anonymous-Id twice -> one anonymous_users row
        uid2 = str(uuid.uuid4())
        client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid2})
        client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid2})
        conn = sqlite3.connect(_test_db_path)
        n = conn.execute("SELECT COUNT(*) FROM anonymous_users WHERE id = ?", (uid2,)).fetchone()[0]
        conn.close()
        if n != 1:
            errors.append(f"expected 1 anonymous_users row for same id, got {n}")

        # 4. New anonymous IDs -> new rows
        uid3 = str(uuid.uuid4())
        uid4 = str(uuid.uuid4())
        client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid3})
        client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid4})
        conn = sqlite3.connect(_test_db_path)
        rows = conn.execute("SELECT id FROM anonymous_users WHERE id IN (?, ?)", (uid3, uid4)).fetchall()
        conn.close()
        ids = [r[0] for r in rows]
        if uid3 not in ids or uid4 not in ids or len(ids) != 2:
            errors.append(f"expected 2 new user rows, got {ids}")

        # 5. Missing header -> server returns new anonymous_id in response
        resp = client.post("/api/jobs", json={"input_type": "upload"})
        if resp.status_code != 200:
            errors.append(f"create job without header: status {resp.status_code}")
        else:
            data = resp.json()
            if data.get("anonymous_id") is None:
                errors.append("expected anonymous_id in response when header missing")
            try:
                uuid.UUID(data["anonymous_id"])
            except ValueError:
                errors.append("anonymous_id in response is not a valid UUID")

    os.unlink(_test_db_path)

    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("Sprint 1: all checks passed.")
    sys.exit(0)

if __name__ == "__main__":
    main()
