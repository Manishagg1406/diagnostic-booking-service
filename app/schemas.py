from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PlainSerializer, field_validator

from app.models import BookingStatus, PaymentStatus

# Money is stored as Decimal; in JSON responses we emit a plain number.
Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, v: str) -> str:
        if len(v.encode()) > 72:
            raise ValueError("password must be at most 72 bytes")
        return v

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()


class UserOut(ORM):
    id: int
    email: EmailStr
    is_admin: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- catalog ----------
class TestCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class TestOut(ORM):
    id: int
    name: str


class CentreCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    location: str = Field(min_length=2, max_length=255)


class CentreOut(ORM):
    id: int
    name: str
    location: str


class CentreTestCreate(BaseModel):
    test_id: int
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class CentreTestOut(BaseModel):
    test_id: int
    test_name: str
    price: Money


class CentreDetail(CentreOut):
    tests: list[CentreTestOut]


# ---------- bookings ----------
class BookingCreate(BaseModel):
    centre_id: int
    test_id: int
    appointment_at: datetime


class BookingOut(ORM):
    id: int
    user_id: int
    centre: CentreOut
    test: TestOut
    appointment_at: datetime
    amount: Money
    status: BookingStatus
    created_at: datetime


# ---------- payments ----------
class PaymentCreate(BaseModel):
    booking_id: int
    # Optional override so the mock outcome can be forced (handy for demos/tests).
    simulate: PaymentStatus | None = None


class PaymentOut(BaseModel):
    id: int
    booking_id: int
    amount: Money
    status: PaymentStatus
    reference: str
    booking_status: BookingStatus
    created_at: datetime


class WebhookPayload(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    booking_id: int
    status: Literal["SUCCESS", "FAILED"]


class WebhookResult(BaseModel):
    result: Literal["processed", "ignored", "duplicate"]
    booking_id: int
    booking_status: BookingStatus
