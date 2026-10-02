from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UnprocessableError
from app.models import Booking, BookingStatus, CentreTest, User, utcnow
from app.schemas import BookingCreate
from app.services.state import transition


def get_owned_booking(db: Session, user: User, booking_id: int, lock: bool = False) -> Booking:
    """Fetch a booking that belongs to `user`.

    Someone else's booking looks exactly like a missing one (404) so IDs can't be probed.
    lock=True uses SELECT ... FOR UPDATE (real row lock on PostgreSQL; no-op on SQLite).
    """
    stmt = select(Booking).where(Booking.id == booking_id)
    if lock:
        stmt = stmt.with_for_update()
    booking = db.scalar(stmt)
    if booking is None or booking.user_id != user.id:
        raise NotFoundError("Booking not found")
    return booking


def _to_naive_utc(dt):
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt  # naive input is assumed to be UTC


def create_booking(db: Session, user: User, data: BookingCreate) -> Booking:
    offering = db.scalar(
        select(CentreTest).where(CentreTest.centre_id == data.centre_id, CentreTest.test_id == data.test_id)
    )
    if offering is None:
        raise NotFoundError("This centre does not offer the requested test")

    appointment_at = _to_naive_utc(data.appointment_at)
    if appointment_at <= utcnow():
        raise UnprocessableError("appointment_at must be in the future")

    booking = Booking(
        user_id=user.id,
        centre_id=data.centre_id,
        test_id=data.test_id,
        appointment_at=appointment_at,
        amount=offering.price,  # price comes from the server, never from the client
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    db.commit()
    return booking


def cancel_booking(db: Session, user: User, booking_id: int) -> Booking:
    booking = get_owned_booking(db, user, booking_id, lock=True)
    transition(booking, BookingStatus.CANCELLED)  # 409 if already FAILED/CANCELLED
    db.commit()
    return booking
