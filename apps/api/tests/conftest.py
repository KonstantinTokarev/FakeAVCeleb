"""Pytest fixtures for API tests. Uses a test SQLite DB and TestClient (lifespan runs)."""
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure api package is importable (whether run from repo root or apps/api)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Use a test DB before any app import that reads database_url
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db.close()
_test_db_path = _test_db.name
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# Now import app (reads env)
from api.main import app


@pytest.fixture
def client():
    """HTTP client. Using 'with' ensures lifespan (init_db) runs."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_db_path():
    """Path to test SQLite DB file for sync queries in tests."""
    return _test_db_path
