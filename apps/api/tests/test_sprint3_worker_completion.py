"""
Sprint 3 tests: Worker increments total_completed on job DONE.

We simulate worker completion (set job DONE + run same UPDATE as worker)
since running the full pipeline would require worker env. This validates
that when a job with anonymous_id is marked DONE, total_completed increases,
and the next create returns 402.
"""
import sqlite3
import uuid
import pytest


def _simulate_worker_completion(conn, job_id: str):
    """Simulate what the worker does: set job to DONE and increment user's total_completed."""
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


def test_complete_job_increments_total_completed(client, test_db_path):
    """Create and complete job with anonymous_id; anonymous_users.total_completed increases by 1."""
    uid = str(uuid.uuid4())
    resp = client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    conn = sqlite3.connect(test_db_path)
    _simulate_worker_completion(conn, job_id)
    row = conn.execute(
        "SELECT total_completed FROM anonymous_users WHERE id = ?", (uid,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 1


def test_complete_job_without_anonymous_id_no_increment(client, test_db_path):
    """Job without anonymous_id (legacy): completion does not change any user's total_completed."""
    uid = str(uuid.uuid4())
    client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    conn = sqlite3.connect(test_db_path)
    job_id = conn.execute("SELECT id FROM jobs WHERE anonymous_id = ?", (uid,)).fetchone()[0]
    conn.execute("UPDATE jobs SET anonymous_id = NULL WHERE id = ?", (job_id,))
    conn.commit()
    _simulate_worker_completion(conn, job_id)
    row = conn.execute(
        "SELECT total_completed FROM anonymous_users WHERE id = ?", (uid,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 0


def test_after_one_done_next_create_returns_402(client, test_db_path):
    """Full flow: 1st job created → completed → total_completed = 1; next create returns 402."""
    uid = str(uuid.uuid4())
    resp = client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    conn = sqlite3.connect(test_db_path)
    _simulate_worker_completion(conn, job_id)
    conn.close()

    resp2 = client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    assert resp2.status_code == 402
    assert resp2.json().get("detail", {}).get("code") == "PAYMENT_REQUIRED"
