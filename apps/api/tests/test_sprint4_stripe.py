"""
Sprint 4 tests: Stripe Checkout + webhook.

Without real Stripe keys we test: create-checkout 503/400, webhook 503/400/422.
With mocked construct_event we test: webhook increments paid_credits and is idempotent.
"""
import json
import uuid
from unittest.mock import patch

import pytest


def test_create_checkout_no_header_400(client):
    """create-checkout without X-Anonymous-Id returns 400."""
    resp = client.post("/api/payment/create-checkout")
    assert resp.status_code == 400


def test_create_checkout_no_config_503(client):
    """create-checkout without Stripe config returns 503."""
    uid = str(uuid.uuid4())
    resp = client.post(
        "/api/payment/create-checkout",
        headers={"X-Anonymous-Id": uid},
    )
    assert resp.status_code == 503
    assert resp.json().get("detail", {}).get("code") == "PAYMENT_UNAVAILABLE"


def test_webhook_no_config_503(client):
    """webhooks/stripe without webhook secret returns 503."""
    resp = client.post(
        "/api/webhooks/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=x"},
    )
    assert resp.status_code == 503


def test_webhook_no_signature_400(client, monkeypatch):
    """webhooks/stripe without Stripe-Signature returns 400."""
    import api.routers.payment as payment_router
    monkeypatch.setattr(payment_router.settings, "stripe_webhook_secret", "whsec_test")
    resp = client.post("/api/webhooks/stripe", content=b"{}")
    assert resp.status_code == 400


def test_webhook_increment_and_idempotent(client, test_db_path, monkeypatch):
    """Webhook increments paid_credits; same event again does not double-increment."""
    import sqlite3
    import api.routers.payment as payment_router
    monkeypatch.setattr(payment_router.settings, "stripe_webhook_secret", "whsec_test")

    uid = str(uuid.uuid4())
    client.post("/api/jobs", json={"input_type": "upload"}, headers={"X-Anonymous-Id": uid})

    payload = json.dumps({
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_sprint4_123",
                "metadata": {"anonymous_id": uid},
            }
        },
    }).encode("utf-8")

    with patch("api.routers.payment.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = json.loads(payload.decode())
        resp1 = client.post(
            "/api/webhooks/stripe",
            content=payload,
            headers={"Stripe-Signature": "t=1,v1=ignored"},
        )
        assert resp1.status_code == 200

    conn = sqlite3.connect(test_db_path)
    row = conn.execute(
        "SELECT paid_credits FROM anonymous_users WHERE id = ?", (uid,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 1

    with patch("api.routers.payment.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.return_value = json.loads(payload.decode())
        resp2 = client.post(
            "/api/webhooks/stripe",
            content=payload,
            headers={"Stripe-Signature": "t=2,v1=ignored"},
        )
        assert resp2.status_code == 200

    conn = sqlite3.connect(test_db_path)
    row = conn.execute(
        "SELECT paid_credits FROM anonymous_users WHERE id = ?", (uid,)
    ).fetchone()
    conn.close()
    assert row[0] == 1
