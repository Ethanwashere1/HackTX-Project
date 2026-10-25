"""Google OAuth 2.0 authorization code flow (with PKCE), hand-rolled on httpx.

The state, PKCE verifier and `next` path live in a short-lived signed cookie, so no server-side
state table is needed.
"""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import get_settings
from app.errors import AppError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_COOKIE = "oauth_state"
STATE_MAX_AGE = 600  # seconds
HTTP_TIMEOUT = 10.0


@dataclass
class GoogleUser:
    sub: str
    email: str
    name: str
    picture: str | None


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().effective_session_secret, salt="oauth-state")


def safe_next(next_path: str | None) -> str:
    """Only allow same-site relative paths like `/orgs`; anything else becomes `/`."""
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    if "\\" in next_path or any(c in next_path for c in "\r\n\t") or ":" in next_path.split("?")[0]:
        return "/"
    return next_path


def require_configured() -> None:
    if not get_settings().google_oauth_configured:
        raise AppError(503, "oauth_not_configured", "Google sign-in is not configured yet")


def build_login(next_path: str | None) -> tuple[str, str]:
    """Return (Google authorization URL, signed state cookie value)."""
    settings = get_settings()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.oauth_redirect_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    cookie = _serializer().dumps({"s": state, "v": verifier, "n": safe_next(next_path)})
    return f"{AUTH_URL}?{urlencode(params)}", cookie


def verify_state(cookie_value: str | None, state: str | None) -> tuple[str, str]:
    """Check the callback `state` against the cookie. Returns (pkce verifier, next path)."""
    if not cookie_value or not state:
        raise AppError(400, "invalid_oauth_state", "Sign-in session expired or invalid; try again")
    try:
        data = _serializer().loads(cookie_value, max_age=STATE_MAX_AGE)
    except BadSignature:
        raise AppError(400, "invalid_oauth_state", "Sign-in session expired or invalid; try again")
    if not isinstance(data, dict) or not hmac.compare_digest(str(data.get("s", "")), state):
        raise AppError(400, "invalid_oauth_state", "Sign-in session expired or invalid; try again")
    return data["v"], safe_next(data.get("n"))


def _json(resp: httpx.Response) -> dict:
    """The response body as a JSON object, or 502 `oauth_failed`."""
    try:
        data = resp.json()
    except ValueError:
        raise AppError(502, "oauth_failed", "Google returned an invalid response")
    if not isinstance(data, dict):
        raise AppError(502, "oauth_failed", "Google returned an invalid response")
    return data


async def exchange_code(code: str, verifier: str) -> GoogleUser:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            token_resp = await client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.oauth_redirect_url,
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
            if token_resp.status_code != 200:
                raise AppError(502, "oauth_failed", "Google rejected the sign-in code")
            access_token = _json(token_resp).get("access_token")
            if not access_token:
                raise AppError(502, "oauth_failed", "Google did not return an access token")
            info_resp = await client.get(
                USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            if info_resp.status_code != 200:
                raise AppError(502, "oauth_failed", "Could not fetch the Google profile")
            info = _json(info_resp)
    except httpx.HTTPError:
        raise AppError(502, "oauth_failed", "Could not reach Google; try again")

    if not info.get("sub") or not info.get("email"):
        raise AppError(502, "oauth_failed", "Google profile is missing an email")
    if info.get("email_verified") is not True:
        raise AppError(403, "email_not_verified", "Your Google email address is not verified")
    email = info["email"].strip().lower()
    return GoogleUser(
        sub=str(info["sub"]),
        email=email,
        name=(info.get("name") or email.split("@")[0]).strip()[:200],
        picture=info.get("picture"),
    )
