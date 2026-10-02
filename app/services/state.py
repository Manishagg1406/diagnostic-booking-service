"""Booking state machine. All status changes go through here."""
from app.core.errors import ConflictError
from app.models import Booking, BookingStatus

ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.PENDING: {BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED},
    BookingStatus.FAILED: set(),
    BookingStatus.CANCELLED: set(),
}


def can_transition(current: BookingStatus, new: BookingStatus) -> bool:
    return new in ALLOWED_TRANSITIONS[current]


def transition(booking: Booking, new: BookingStatus) -> None:
    if not can_transition(booking.status, new):
        raise ConflictError(f"Cannot change booking from {booking.status.value} to {new.value}")
    booking.status = new
