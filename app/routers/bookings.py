from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Booking, BookingStatus, User
from app.schemas import BookingCreate, BookingOut
from app.services import bookings as service

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("", response_model=BookingOut, status_code=201)
def create_booking(data: BookingCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.create_booking(db, user, data)


@router.get("", response_model=list[BookingOut])
def list_my_bookings(
    status: BookingStatus | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Booking).where(Booking.user_id == user.id).order_by(Booking.id.desc())
    if status is not None:
        stmt = stmt.where(Booking.status == status)
    return db.scalars(stmt.limit(limit).offset(offset)).all()


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.get_owned_booking(db, user, booking_id)


@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.cancel_booking(db, user, booking_id)
