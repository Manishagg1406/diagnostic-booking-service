import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    """Naive UTC datetime. We store every timestamp as UTC without tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DiagnosticTest(Base):
    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Centre(Base):
    __tablename__ = "centres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(255), index=True)

    offerings: Mapped[list["CentreTest"]] = relationship(back_populates="centre", order_by="CentreTest.id")


class CentreTest(Base):
    """Which test a centre offers, and at what price (price differs per centre)."""

    __tablename__ = "centre_tests"
    __table_args__ = (
        UniqueConstraint("centre_id", "test_id", name="uq_centre_test"),
        CheckConstraint("price > 0", name="ck_centre_test_price_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id", ondelete="CASCADE"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    centre: Mapped[Centre] = relationship(back_populates="offerings")
    test: Mapped[DiagnosticTest] = relationship()


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id"), index=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id"), index=True)
    appointment_at: Mapped[datetime] = mapped_column(DateTime)
    # Snapshot of the price at booking time, so later price changes don't alter old bookings.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, native_enum=False, length=20), default=BookingStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    centre: Mapped[Centre] = relationship()
    test: Mapped[DiagnosticTest] = relationship()


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, native_enum=False, length=20))
    source: Mapped[str] = mapped_column(String(20))  # "API" (mock endpoint) or "WEBHOOK"
    # Unique: a second payment with the same reference can never be inserted.
    reference: Mapped[str] = mapped_column(String(150), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WebhookEvent(Base):
    """Log of processed webhook events. The UNIQUE event_id is the idempotency key."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), unique=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    reported_status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, native_enum=False, length=20))
    outcome: Mapped[str] = mapped_column(String(20))  # APPLIED or IGNORED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
