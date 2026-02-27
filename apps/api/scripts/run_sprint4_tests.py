#!/usr/bin/env python3
"""
Run Sprint 4 testable results without pytest.
Uses mocked Stripe webhook to test increment + idempotency.
Usage: from apps/api: PYTHONPATH=.. python3 scripts/run_sprint4_tests.py
"""
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

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
        # 1. create-checkout without header -> 400
        r = client.post("/api/payment/create-checkout")
        if r.status_code != 400:
            errors.append(f"create-checkout no header: expected 400, got {r.status_code}")

        # 2. create-checkout without config -> 503
        uid = str(uuid.uuid4())
        r = client.post("/api/payment/create-checkout", headers={"X-Anonymous-Id": uid})
        if r.status_code != 503:
            errors.append(f"create-checkout no config: expected 503, got {r.status_code}")

        # 3. webhook without secret -> 503
        r = client.post("/api/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})
        if r.status_code != 503:
            errors.append(f"webhook no config: expected 503, got {r.status_code}")

        # 4. webhook with mocked event: increment paid_credits and idempotent
        import api.routers.payment as payment_router
        payment_router.settings.stripe_webhook_secret = "whsec_test"

        uid2 = str(uuid.uuid4())
        client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid2})
        payload = json.dumps({
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_run4",
                    "metadata": {"anonymous_id": uid2},
                }
            },
        }).encode("utf-8")

        with patch("api.routers.payment.stripe.Webhook.construct_event") as mock_construct:
            mock_construct.return_value = json.loads(payload.decode())
            r = client.post(
                "/api/webhooks/stripe",
                content=payload,
                headers={"Stripe-Signature": "t=1,v1=x"},
            )
        if r.status_code != 200:
            errors.append(f"webhook first call: expected 200, got {r.status_code}")
        else:
            conn = sqlite3.connect(_test_db_path)
            row = conn.execute(
                "SELECT paid_credits FROM anonymous_users WHERE id = ?", (uid2,)
            ).fetchone()
            conn.close()
            if not row or row[0] != 1:
                errors.append("paid_credits should be 1 after webhook")

        with patch("api.routers.payment.stripe.Webhook.construct_event") as mock_construct:
            mock_construct.return_value = json.loads(payload.decode())
            client.post(
                "/api/webhooks/stripe",
                content=payload,
                headers={"Stripe-Signature": "t=2,v1=x"},
            )
        conn = sqlite3.connect(_test_db_path)
        row = conn.execute(
            "SELECT paid_credits FROM anonymous_users WHERE id = ?", (uid2,)
        ).fetchone()
        conn.close()
        if not row or row[0] != 1:
            errors.append("paid_credits should still be 1 after duplicate webhook (idempotent)")

    os.unlink(_test_db_path)

    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("Sprint 4: all checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
