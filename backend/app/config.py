"""Settings loaded from environment variables and backend/.env.

Paths resolve relative to the backend directory, never the current working directory.
Any value that is empty or contains REPLACE_ME counts as "not configured".
"""

import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PLACEHOLDER = "REPLACE_ME"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEV_SESSION_SECRET = "dev-only-insecure-session-secret"
# Fixed by the migrations (event_members.embedding is vector(768)); changing it needs a new migration.
EMBEDDING_DIM = 768

log = logging.getLogger(__name__)


def is_placeholder(value: str | None) -> bool:
    return not value or not value.strip() or PLACEHOLDER in value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # local | test | production. Anything other than local/test is treated as a real deployment,
    # so a missing APP_ENV fails safe (secure cookies, real session secret required).
    app_env: str = "production"

    database_url: str = ""
    test_database_url: str = ""

    session_secret: str = ""
    session_cookie_secure: bool = False
    session_max_age_days: int = 14

    google_client_id: str = ""
    google_client_secret: str = ""
    # Must match the redirect URI registered in Google Cloud. In dev the browser goes through the
    # Vite proxy, so the callback is on the frontend origin.
    oauth_redirect_url: str = "http://localhost:5173/api/auth/google/callback"

    frontend_origin: str = "http://localhost:5173"

    # Dev-only password-less login (POST /api/auth/dev-login). See is_dev_login_enabled().
    dev_login: bool = False

    gemini_api_key: str = ""
    # Requested with outputDimensionality=EMBEDDING_DIM (768).
    gemini_embed_model: str = "gemini-embedding-001"
    gemini_timeout_s: float = 10
    embedding_dim: int = 768

    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_password: str = ""
    snowflake_warehouse: str = ""
    snowflake_database: str = ""
    snowflake_schema: str = ""
    snowflake_role: str = ""
    snowflake_table: str = "PROFILE_EMBEDDINGS"
    snowflake_timeout_s: float = 5  # reads (similarity queries)
    # Writes (embedding sync, deletes): may include the login, a warehouse resume and CREATE TABLE.
    snowflake_write_timeout_s: float = 30

    serpapi_api_key: str = ""
    serpapi_timeout_s: float = 8
    # Cached social lookups (social_lookups) are reused for this long.
    social_lookup_ttl_hours: float = 24
    agents_url: str = "http://localhost:8000"
    agents_timeout_s: float = 20
    # Browser-facing interview WebSocket. Empty -> derived from AGENTS_URL (http->ws) + /ws/interview.
    agents_ws_url: str = ""
    internal_api_key: str = ""

    @property
    def is_local(self) -> bool:
        return self.app_env in ("local", "test")

    @property
    def cookie_secure(self) -> bool:
        """Cookies are always Secure outside local/test; SESSION_COOKIE_SECURE only matters locally."""
        return self.session_cookie_secure or not self.is_local

    @property
    def interview_ws_url(self) -> str:
        if not is_placeholder(self.agents_ws_url):
            return self.agents_ws_url
        base = self.agents_url.rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
        return base + "/ws/interview"

    @property
    def google_oauth_configured(self) -> bool:
        return not (
            is_placeholder(self.google_client_id)
            or is_placeholder(self.google_client_secret)
            or is_placeholder(self.oauth_redirect_url)
        )

    @property
    def gemini_configured(self) -> bool:
        return not is_placeholder(self.gemini_api_key)

    @property
    def snowflake_configured(self) -> bool:
        """Every SNOWFLAKE_* connection setting is set (the role is optional)."""
        return not any(
            is_placeholder(v)
            for v in (
                self.snowflake_account,
                self.snowflake_user,
                self.snowflake_password,
                self.snowflake_warehouse,
                self.snowflake_database,
                self.snowflake_schema,
            )
        )

    @property
    def serpapi_configured(self) -> bool:
        return not is_placeholder(self.serpapi_api_key)

    @property
    def internal_key_configured(self) -> bool:
        return not is_placeholder(self.internal_api_key)

    @property
    def effective_session_secret(self) -> str:
        if not is_placeholder(self.session_secret) and self.session_secret != DEV_SESSION_SECRET:
            return self.session_secret
        if not self.is_local:
            raise RuntimeError("SESSION_SECRET must be set to a real secret outside local development")
        return DEV_SESSION_SECRET

    def check_startup(self) -> None:
        """Refuse to boot with settings that would be unsafe or break the schema."""
        if self.embedding_dim != EMBEDDING_DIM:
            raise RuntimeError(
                f"EMBEDDING_DIM={self.embedding_dim} but the schema stores vector({EMBEDDING_DIM}); "
                "changing it needs a new migration"
            )
        self.effective_session_secret  # raises outside local/test without a real secret

    def is_dev_login_enabled(self) -> bool:
        """Dev login needs DEV_LOGIN=1, a local APP_ENV and a localhost FRONTEND_ORIGIN."""
        host = urlparse(self.frontend_origin).hostname or ""
        return self.dev_login and self.is_local and host in LOCAL_HOSTS


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check_startup()
    if settings.effective_session_secret == DEV_SESSION_SECRET:
        log.warning("SESSION_SECRET is not set; using an insecure dev secret")
    return settings
