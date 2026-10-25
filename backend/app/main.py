"""SquadUp core API. Run from backend/: `uv run uvicorn app.main:app --reload --port 8001`."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.errors import install_error_handlers
from app.routers import (
    auth,
    events,
    groups,
    health,
    internal,
    me,
    orgs,
    question_suggestions,
    recommendations,
    requests,
    threads,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SquadUp API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(events.router)
    app.include_router(question_suggestions.router)
    app.include_router(requests.router)
    app.include_router(threads.router)
    app.include_router(groups.router)
    app.include_router(orgs.router)
    app.include_router(recommendations.router)
    app.include_router(internal.router)
    if settings.is_dev_login_enabled():
        logging.getLogger(__name__).warning("DEV_LOGIN is enabled: POST /api/auth/dev-login is open")
    return app


app = create_app()
