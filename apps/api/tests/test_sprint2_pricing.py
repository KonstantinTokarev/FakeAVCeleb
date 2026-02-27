"""
Sprint 2 tests: Pricing logic (402 + credit deduction).

Testable results:
- User A: 1st job (no DONE yet) → job created (free).
- User A: 2nd job (still 0 DONE) → 402 (next is 2nd = paid, no credits).
- Manually set User A paid_credits = 1; 2nd job → job created, paid_credits becomes 0.
- After one DONE (simulated): 2nd job → 402; 3rd job → created (free).
"""
import sqlite3
import uuid
import pytest


def test_first_job_free(client, test_db_path):
    """1st job (total_completed=0) → job created, no payment required."""
    uid = str(uuid.uuid4())
    resp = client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data


def test_second_job_402_when_no_credits(client, test_db_path):
    """When next job would be 2nd (paid) and paid_credits=0 → 402."""
    uid = str(uuid.uuid4())
    # Create user by creating first job
    client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    # Simulate one job completed: set total_completed=1 so next is 2nd = paid
    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "UPDATE anonymous_users SET total_completed = 1 WHERE id = ?", (uid,)
    )
    conn.commit()
    conn.close()

    resp = client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    assert resp.status_code == 402
    data = resp.json()
    assert data.get("detail", {}).get("code") == "PAYMENT_REQUIRED"
    assert data.get("detail", {}).get("amount_eur") == 1


def test_second_job_created_when_has_credit(client, test_db_path):
    """When next is 2nd (paid) and paid_credits=1 → job created, paid_credits becomes 0."""
    uid = str(uuid.uuid4())
    client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "UPDATE anonymous_users SET total_completed = 1, paid_credits = 1 WHERE id = ?",
        (uid,),
    )
    conn.commit()
    conn.close()

    resp = client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    assert resp.status_code == 200
    assert "job_id" in resp.json()

    conn = sqlite3.connect(test_db_path)
    row = conn.execute(
        "SELECT paid_credits FROM anonymous_users WHERE id = ?", (uid,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 0


def test_third_job_free(client, test_db_path):
    """When total_completed=2, next is 3rd = free → job created, no credit deduction."""
    uid = str(uuid.uuid4())
    client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "UPDATE anonymous_users SET total_completed = 2, paid_credits = 0 WHERE id = ?",
        (uid,),
    )
    conn.commit()
    conn.close()

    resp = client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    assert resp.status_code == 200
    # paid_credits should still be 0 (no deduction for free slot)
    conn = sqlite3.connect(test_db_path)
    row = conn.execute(
        "SELECT paid_credits FROM anonymous_users WHERE id = ?", (uid,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 0
