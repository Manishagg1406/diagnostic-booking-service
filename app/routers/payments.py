import hmac
import hashlib
import json

from fastapi import APIRouter, Depends, Header, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import UnauthorizedError
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import PaymentCreate, PaymentOut, WebhookPayload, WebhookResult
from app.services import payments as service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/", response_model=PaymentOut, status_code=201)
def create_payment(data: PaymentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    payment, booking = service.simulate_payment(db, user, data.booking_id, data.simulate)
    return PaymentOut(
        id=payment.id,
        booking_id=payment.booking_id,
        amount=payment.amount,
        status=payment.status,
        reference=payment.reference,
        booking_status=booking.status,
        created_at=payment.created_at,
    )


@router.post("/webhook/", response_model=WebhookResult)
async def payment_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(None),
    db: Session = Depends(get_db),
):
    """Called by the (simulated) payment provider. Auth = HMAC-SHA256 of the raw body, hex in X-Webhook-Signature."""
    raw_body = await request.body()
    expected = hmac.new(settings.webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not x_webhook_signature or not hmac.compare_digest(expected, x_webhook_signature):
        raise UnauthorizedError("Invalid webhook signature")

    try:
        event = WebhookPayload.model_validate_json(raw_body)
    except ValidationError as exc:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=422, content={"detail": json.loads(exc.json(include_url=False, include_context=False))})

    result, booking = service.process_webhook(db, event)
    return WebhookResult(result=result, booking_id=booking.id, booking_status=booking.status)
