"""Server-side sessions. The `session` cookie holds a random token; the DB stores its SHA-256."""

import hashlib
import secrets
from datetime import timedelta

from fastapi import Response
from sqlmodel import Session, delete, select

from app.config import get_settings
from app.models import User, UserSession
from app.models.base import utcnow

SESSION_COOKIE = "session"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    """Create a session row and return the raw token for the cookie. Commits.

    Also deletes the user's expired sessions, so the table doesn't grow forever.
    """
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.exec(delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at <= now))
    db.add(
        UserSession(
            token_hash=hash_token(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=settings.session_max_age_days),
        )
    )
    db.commit()
    return token


def user_for_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = db.exec(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(UserSession.token_hash == hash_token(token), UserSession.expires_at > utcnow())
    ).first()
    return row


def delete_session(db: Session, token: str | None) -> None:
    if token:
        db.exec(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
        db.commit()


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_max_age_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
