"""Stripe Checkout and webhook for 1 EUR payment; credits anonymous user."""
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import AnonymousUser, StripeProcessedSession

router = APIRouter()


class CreateCheckoutResponse(BaseModel):
    checkout_url: str


@router.post("/payment/create-checkout", response_model=CreateCheckoutResponse)
async def create_checkout(
    db: AsyncSession = Depends(get_db),
    x_anonymous_id: Optional[str] = Header(None, alias="X-Anonymous-Id"),
):
    if not x_anonymous_id or not x_anonymous_id.strip():
        raise HTTPException(status_code=400, detail="X-Anonymous-Id header required")
    if not settings.stripe_secret_key or not settings.stripe_price_id:
        raise HTTPException(
            status_code=503,
            detail={"code": "PAYMENT_UNAVAILABLE", "message": "Payment is not configured"},
        )

    stripe.api_key = settings.stripe_secret_key
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
            success_url=settings.payment_success_url,
            cancel_url=settings.payment_cancel_url,
            metadata={"anonymous_id": x_anonymous_id.strip()},
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return CreateCheckoutResponse(checkout_url=session.url or "")


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")

    body = await request.body()
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            body, stripe_signature, settings.stripe_webhook_secret
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError as e:
        raise HTTPException(status_code=422, detail="Invalid signature")

    if event["type"] != "checkout.session.completed":
        return {"received": True}

    session = event["data"]["object"]
    session_id = session.get("id")
    if not session_id:
        return {"received": True}

    # Idempotency: skip if already processed
    r = await db.execute(
        select(StripeProcessedSession).where(StripeProcessedSession.session_id == session_id)
    )
    if r.scalar_one_or_none():
        return {"received": True}

    anonymous_id = (session.get("metadata") or {}).get("anonymous_id")
    if not anonymous_id:
        return {"received": True}

    # Increment paid_credits and record session
    await db.execute(
        text(
            "UPDATE anonymous_users SET paid_credits = paid_credits + 1 WHERE id = :aid"
        ),
        {"aid": anonymous_id},
    )
    db.add(StripeProcessedSession(session_id=session_id))
    await db.commit()

    return {"received": True}
