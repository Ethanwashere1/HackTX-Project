"""Profile embeddings: Gemini embeds each event member's `profile_text` into pgvector, then the
vectors are synced to Snowflake for similarity search.

embed_members() is the body of the profiles.on_member_text_changed hook. It runs after the
response, opens its own DB session and never raises: while Gemini isn't configured or when a
call fails, the embedding stays null (recommendations still work, just without similarity).
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlmodel import Session, select, update

from app import db as dbmod
from app.config import EMBEDDING_DIM, get_settings
from app.models import EventMember
from app.models.base import utcnow
from app.services import snowflake_store

log = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_BATCH_LIMIT = 100  # max requests per batchEmbedContents call


class EmbeddingError(Exception):
    """Gemini embeddings failed or returned something unusable."""


@dataclass
class _Pending:
    id: str
    event_id: str
    user_id: str
    text: str


def _post(url: str, **kwargs) -> httpx.Response:
    return httpx.post(url, **kwargs)


def _model_name() -> str:
    model = get_settings().gemini_embed_model.strip()
    return model if model.startswith("models/") else f"models/{model}"


def _normalize(values: list) -> list[float]:
    if len(values) != EMBEDDING_DIM:
        raise EmbeddingError(f"Gemini returned {len(values)} dimensions, expected {EMBEDDING_DIM}")
    try:
        floats = [float(v) for v in values]
    except (TypeError, ValueError) as exc:
        raise EmbeddingError("Gemini returned a non-numeric embedding") from exc
    norm = math.sqrt(sum(v * v for v in floats))
    if not math.isfinite(norm) or norm == 0:
        raise EmbeddingError("Gemini returned an empty embedding")
    # gemini-embedding-001 only normalizes its full 3072-dim output, so normalize here.
    return [v / norm for v in floats]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """One unit-length 768-dim vector per text, in order. Raises EmbeddingError."""
    settings = get_settings()
    if not settings.gemini_configured:
        raise EmbeddingError("GEMINI_API_KEY is not configured")
    model = _model_name()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), GEMINI_BATCH_LIMIT):
        chunk = texts[start:start + GEMINI_BATCH_LIMIT]
        body = {
            "requests": [
                {
                    "model": model,
                    "content": {"parts": [{"text": text}]},
                    "taskType": "SEMANTIC_SIMILARITY",
                    "outputDimensionality": EMBEDDING_DIM,
                }
                for text in chunk
            ]
        }
        try:
            resp = _post(
                f"{GEMINI_API_BASE}/{model}:batchEmbedContents",
                json=body,
                headers={"x-goog-api-key": settings.gemini_api_key},
                timeout=settings.gemini_timeout_s,
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Gemini embeddings request failed: {exc.__class__.__name__}") from exc
        if resp.status_code != 200:
            raise EmbeddingError(f"Gemini embeddings returned HTTP {resp.status_code}")
        try:
            embeddings = resp.json()["embeddings"]
            values = [e["values"] for e in embeddings]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError("Gemini embeddings returned an unexpected body") from exc
        if len(values) != len(chunk):
            raise EmbeddingError(f"Gemini returned {len(values)} embeddings for {len(chunk)} texts")
        vectors.extend(_normalize(v) for v in values)
    return vectors


def embed_members(member_ids: list[str], *, sync: bool = True) -> None:
    """Embed these members' profile_text, store it (embedding, embedded_at) and, with `sync`,
    push the new vectors to Snowflake (snowflake_synced_at). Logs and returns on any failure."""
    if not member_ids:
        return
    if not get_settings().gemini_configured:
        log.debug("Gemini not configured; not embedding %d member(s)", len(member_ids))
        return
    try:
        stored = _embed_and_store(member_ids)
    except EmbeddingError as exc:
        log.warning("Embedding %d member(s) failed: %s", len(member_ids), exc)
        return
    except Exception:
        log.exception("Embedding %d member(s) failed", len(member_ids))
        return
    if sync and stored:
        sync_to_snowflake(stored)


def _embed_and_store(member_ids: list[str]) -> list[snowflake_store.EmbeddingRow]:
    with Session(dbmod.get_engine()) as db:
        rows = db.exec(
            select(EventMember.id, EventMember.event_id, EventMember.user_id, EventMember.profile_text)
            .where(EventMember.id.in_(member_ids))
            .order_by(EventMember.id)
        ).all()
        pending = [_Pending(*row) for row in rows if row[3] and row[3].strip()]
        if not pending:
            return []
        vectors = embed_texts([p.text for p in pending])
        now = utcnow()
        stored = []
        for p, vector in zip(pending, vectors):
            # Only if the text is still the one we embedded; a newer change re-runs this hook.
            result = db.exec(
                update(EventMember)
                .where(EventMember.id == p.id, EventMember.profile_text == p.text)
                .values(embedding=vector, embedded_at=now)
            )
            if result.rowcount:
                stored.append(snowflake_store.EmbeddingRow(p.id, p.event_id, p.user_id, vector, now))
        db.commit()
        log.info("Embedded %d of %d member(s)", len(stored), len(member_ids))
        return stored


def sync_to_snowflake(rows: list[snowflake_store.EmbeddingRow]) -> None:
    """Upsert the vectors into Snowflake and set snowflake_synced_at. Never raises."""
    if not rows or not get_settings().snowflake_configured:
        return
    try:
        snowflake_store.upsert_embeddings(rows)
    except Exception as exc:
        log.warning("Snowflake sync of %d member(s) failed: %s", len(rows), exc)
        return
    try:
        with Session(dbmod.get_engine()) as db:
            for row in rows:
                _mark_synced(db, row.event_member_id, row.embedded_at)
            db.commit()
    except Exception:
        log.exception("Recording the Snowflake sync failed")


def _mark_synced(db: Session, member_id: str, embedded_at: datetime) -> None:
    # Skipped if the member was re-embedded meanwhile; that run syncs its own vector.
    db.exec(
        update(EventMember)
        .where(EventMember.id == member_id, EventMember.embedded_at == embedded_at)
        .values(snowflake_synced_at=utcnow())
    )
