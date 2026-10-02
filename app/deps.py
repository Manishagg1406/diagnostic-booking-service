import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise UnauthorizedError("Not authenticated")
    try:
        user_id = decode_access_token(creds.credentials)
    except (jwt.PyJWTError, ValueError, KeyError):
        raise UnauthorizedError("Invalid or expired token")
    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("Invalid or expired token")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise ForbiddenError("Admin access required")
    return user
