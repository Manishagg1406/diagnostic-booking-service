import logging
import random
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError
from app.models import Booking, BookingStatus, Payment, PaymentStatus, User, WebhookEvent
from app.schemas import WebhookPayload
from app.services.bookings import get_owned_booking
from app.services.state import can_transition, transition

logger = logging.getLogger("eve.payments")

_RESULT_TO_BOOKING = {
    PaymentStatus.SUCCESS: BookingStatus.CONFIRMED,
    PaymentStatus.FAILED: BookingStatus.FAILED,
}


def simulate_payment(db: Session, user: User, booking_id: int, simulate: PaymentStatus | None) -> tuple[Payment, Booking]:
    """Mock payment gateway: randomly succeeds/fails (or uses `simulate`) and updates the booking."""
    booking = get_owned_booking(db, user, booking_id, lock=True)
    if booking.status != BookingStatus.PENDING:
        raise ConflictError(f"Booking is {booking.status.value}; only PENDING bookings can be paid")

    if simulate is not None:
        outcome = simulate
    else:
        outcome = PaymentStatus.SUCCESS if random.random() < settings.payment_success_rate else PaymentStatus.FAILED

    payment = Payment(
        booking_id=booking.id,
        amount=booking.amount,
        status=outcome,
        source="API",
        reference=f"pay_{uuid4().hex}",
    )
    transition(booking, _RESULT_TO_BOOKING[outcome])
    db.add(payment)
    db.commit()
    logger.info("payment booking_id=%s status=%s reference=%s", booking.id, outcome.value, payment.reference)
    return payment, booking


def process_webhook(db: Session, event: WebhookPayload) -> tuple[str, Booking]:
    """Idempotent webhook handler. Returns ("processed" | "ignored" | "duplicate", booking).

    Idempotency has two layers:
      1. We look the event_id up first and return early if we've seen it.
      2. UNIQUE(webhook_events.event_id) and UNIQUE(payments.reference) make the database reject a
         duplicate even if two identical requests race past step 1.
    """
    booking = db.scalar(select(Booking).where(Booking.id == event.booking_id).with_for_update())
    if booking is None:
        raise NotFoundError("Booking not found")

    if db.scalar(select(WebhookEvent.id).where(WebhookEvent.event_id == event.event_id)) is not None:
        logger.info("webhook duplicate event_id=%s", event.event_id)
        return "duplicate", booking

    reported = PaymentStatus(event.status)
    target = _RESULT_TO_BOOKING[reported]

    if can_transition(booking.status, target):
        db.add(
            Payment(
                booking_id=booking.id,
                amount=booking.amount,
                status=reported,
                source="WEBHOOK",
                reference=f"evt_{event.event_id}",
            )
        )
        transition(booking, target)
        outcome, result = "APPLIED", "processed"
    else:
        # e.g. late FAILED for an already CONFIRMED booking: record it, but don't touch state.
        outcome, result = "IGNORED", "ignored"
        logger.warning(
            "webhook ignored event_id=%s booking_id=%s booking_status=%s reported=%s",
            event.event_id, booking.id, booking.status.value, reported.value,
        )

    db.add(WebhookEvent(event_id=event.event_id, booking_id=booking.id, reported_status=reported, outcome=outcome))
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request with the same event_id won the race.
        db.rollback()
        booking = db.get(Booking, event.booking_id)
        logger.info("webhook duplicate (race) event_id=%s", event.event_id)
        return "duplicate", booking

    logger.info("webhook %s event_id=%s booking_id=%s", result, event.event_id, booking.id)
    return result, booking
