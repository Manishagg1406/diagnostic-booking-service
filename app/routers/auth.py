from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import LoginRequest, SignupRequest, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.email)):
        raise ConflictError("Email already registered")
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        is_admin=data.email in settings.admin_email_set,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two signups with the same email at the same instant
        db.rollback()
        raise ConflictError("Email already registered")
    return user


@router.post("/login", response_model=TokenOut)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    # Same message for "no such user" and "wrong password" so emails can't be enumerated.
    if user is None or not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
