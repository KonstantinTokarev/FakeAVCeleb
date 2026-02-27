"""
Sprint 6 tests: GET /api/me + next_check_free.

Testable results:
- With total_completed=0: next_check_free is True.
- With total_completed=1: next_check_free is False.
- GET /api/me creates user if not exists and returns consistent anonymous_id.
"""
import sqlite3
import uuid


def test_me_creates_user_and_reports_free_first_check(client, test_db_path):
    """First call to /api/me with new ID creates user; next_check_free is True."""
    uid = str(uuid.uuid4())
    resp = client.get("/api/me", headers={"X-Anonymous-Id": uid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["anonymous_id"] == uid
    assert data["total_completed"] == 0
    assert data["paid_credits"] == 0
    assert data["next_check_free"] is True


def test_me_next_check_free_false_when_second_check(client, test_db_path):
    """When total_completed=1, next_check_free is False (2nd = paid)."""
    uid = str(uuid.uuid4())
    # Create user
    client.get("/api/me", headers={"X-Anonymous-Id": uid})

    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "UPDATE anonymous_users SET total_completed = 1, paid_credits = 0 WHERE id = ?",
        (uid,),
    )
    conn.commit()
    conn.close()

    resp = client.get("/api/me", headers={"X-Anonymous-Id": uid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_completed"] == 1
    assert data["next_check_free"] is False

