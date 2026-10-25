# SquadUp core API. Built by deploy/docker-compose.yml (context: backend/).
# Installs only the locked runtime dependencies (no dev group, so no pgserver): DATABASE_URL
# must point at a real Postgres (TigerData), or startup fails with a clear error.
FROM python:3.12.12-slim

# uv version matches the one that wrote uv.lock (lock revision 3).
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --system --uid 10001 --no-create-home squadup
USER squadup

EXPOSE 8001

# Migrations run on every start (idempotent). --proxy-headers trusts Caddy's X-Forwarded-*,
# so the app sees https and the real client IP.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips='*'"]
