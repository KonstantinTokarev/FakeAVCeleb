"""
Sprint 1 tests: Data model and anonymous user resolution.

Testable results:
- Migration applies; anonymous_users and jobs.anonymous_id exist.
- POST /api/jobs with valid X-Anonymous-Id creates job and job.anonymous_id matches.
- Same X-Anonymous-Id twice creates one anonymous_users row (get-or-create).
- New anonymous ID creates new anonymous_users row.
"""
import sqlite3
import uuid
import pytest


def test_migration_applied(client, test_db_path):
    """Migration applies; anonymous_users and jobs.anonymous_id exist."""
    conn = sqlite3.connect(test_db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='anonymous_users'"
        )
        assert cur.fetchone() is not None, "anonymous_users table should exist"
        cur = conn.execute("PRAGMA table_info(jobs)")
        cols = [row[1] for row in cur.fetchall()]
        assert "anonymous_id" in cols, "jobs.anonymous_id column should exist"
    finally:
        conn.close()


def test_create_job_with_valid_anonymous_id_sets_job_anonymous_id(client, test_db_path):
    """POST /api/jobs with valid X-Anonymous-Id creates job and job.anonymous_id matches."""
    uid = str(uuid.uuid4())
    resp = client.post(
        "/api/jobs",
        json={"input_type": "upload"},
        headers={"X-Anonymous-Id": uid},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data.get("anonymous_id") is None  # we provided it, so not returned
    conn = sqlite3.connect(test_db_path)
    try:
        row = conn.execute(
            "SELECT anonymous_id FROM jobs WHERE id = ?", (data["job_id"],)
        ).fetchone()
        assert row is not None
        assert row[0] == uid
    finally:
        conn.close()


def test_same_anonymous_id_twice_creates_one_user_row(client, test_db_path):
    """Same X-Anonymous-Id twice creates one anonymous_users row (get-or-create)."""
    uid = str(uuid.uuid4())
    client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid})
    client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid})

    conn = sqlite3.connect(test_db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM anonymous_users WHERE id = ?", (uid,)
        ).fetchone()[0]
        assert n == 1
    finally:
        conn.close()


def test_new_anonymous_id_creates_new_user_row(client, test_db_path):
    """New anonymous ID creates new anonymous_users row."""
    uid1 = str(uuid.uuid4())
    uid2 = str(uuid.uuid4())
    client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid1})
    client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid2})

    conn = sqlite3.connect(test_db_path)
    try:
        rows = conn.execute(
            "SELECT id FROM anonymous_users WHERE id IN (?, ?)", (uid1, uid2)
        ).fetchall()
        ids = [r[0] for r in rows]
        assert uid1 in ids
        assert uid2 in ids
        assert len(ids) == 2
    finally:
        conn.close()


def test_missing_anonymous_id_returns_new_id_in_response(client):
    """When X-Anonymous-Id is missing, server generates ID and returns it in response."""
    resp = client.post("/api/jobs", json={"input_type": "upload"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("anonymous_id") is not None
    try:
        uuid.UUID(data["anonymous_id"])
    except ValueError:
        pytest.fail("anonymous_id should be a valid UUID")
