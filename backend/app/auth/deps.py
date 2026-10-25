from typing import Annotated

from fastapi import Cookie, Depends
from sqlmodel import Session

from app.auth.sessions import SESSION_COOKIE, user_for_token
from app.db import get_session
from app.errors import AppError
from app.models import User

DbSession = Annotated[Session, Depends(get_session)]


def current_user(
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    """The signed-in user, or 401 `unauthenticated`."""
    user = user_for_token(db, session_token)
    if user is None:
        raise AppError(401, "unauthenticated", "Sign in required")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
