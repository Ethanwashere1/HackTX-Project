"""Contract section 1: Google sign-in, logout, and the dev-only login."""

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.auth import google
from app.auth.deps import DbSession
from app.auth.sessions import (
    SESSION_COOKIE,
    clear_session_cookie,
    create_session,
    delete_session,
    set_session_cookie,
)
from app.config import get_settings
from app.errors import AppError, error_response
from app.services.users import me_payload, upsert_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

STATE_COOKIE_PATH = "/api/auth/google"


def _frontend_url(path: str) -> str:
    return get_settings().frontend_origin.rstrip("/") + path


def _clear_state_cookie(response: Response) -> None:
    response.delete_cookie(google.STATE_COOKIE, path=STATE_COOKIE_PATH)


@router.get("/google/login")
def google_login(next: str | None = None):
    google.require_configured()
    url, cookie = google.build_login(next)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        google.STATE_COOKIE,
        cookie,
        max_age=google.STATE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path=STATE_COOKIE_PATH,
    )
    return response


@router.get("/google/callback")
async def google_callback(
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    state_cookie: Annotated[str | None, Cookie(alias=google.STATE_COOKIE)] = None,
):
    """Every response from here, success or error, clears the one-time oauth_state cookie."""
    try:
        response = await _complete_google_login(db, code, state, error, state_cookie)
    except AppError as exc:
        response = error_response(exc.status_code, exc.code, exc.message)
    _clear_state_cookie(response)
    return response


async def _complete_google_login(
    db, code: str | None, state: str | None, error: str | None, state_cookie: str | None
) -> Response:
    google.require_configured()
    if error:
        # The user cancelled or Google refused: send them back to the login page.
        return RedirectResponse(
            _frontend_url("/login?" + urlencode({"error": "oauth_" + error[:40]})), status_code=302
        )

    verifier, next_path = google.verify_state(state_cookie, state)
    if not code:
        raise AppError(400, "bad_request", "Missing authorization code")
    guser = await google.exchange_code(code, verifier)

    def _sign_in() -> str:
        # Sync DB work runs in the threadpool so it doesn't block the event loop.
        user = upsert_user(
            db, email=guser.email, name=guser.name, avatar_url=guser.picture, google_sub=guser.sub
        )
        return create_session(db, user)

    token = await run_in_threadpool(_sign_in)
    response = RedirectResponse(_frontend_url(next_path), status_code=302)
    set_session_cookie(response, token)
    return response


@router.post("/logout", status_code=204)
def logout(
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
):
    delete_session(db, session_token)
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


class DevLoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    name: str = Field(min_length=1, max_length=200)


@router.post("/dev-login")
def dev_login(body: DevLoginBody, db: DbSession):
    """DEV ONLY. Signs in as any email without Google. 404 unless DEV_LOGIN=1 on a local env."""
    if not get_settings().is_dev_login_enabled():
        raise AppError(404, "not_found", "Not found")
    user = upsert_user(db, email=body.email, name=body.name.strip())
    token = create_session(db, user)
    response = JSONResponse(me_payload(db, user))
    set_session_cookie(response, token)
    return response

