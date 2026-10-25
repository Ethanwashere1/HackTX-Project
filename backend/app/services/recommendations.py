"""Recommendations (contract section 4).

1. Exclusions: the viewer, their group-mates and groups, connections, anyone declined either way
   (requests.excluded_for_viewer), plus anyone with a pending request to or from the viewer
   (they're already in the requests inbox).
2. Structured events only recommend what an accept could actually settle (requests._form_group,
   _join_group): people only while a new group can still form (the event has fewer than
   group_count groups and the viewer is under max_groups_per_user), and never people already at
   max_groups_per_user; open groups (not full) only while the viewer is under max_groups_per_user.
   Informal events have no groups.
3. Similarity of each event member to the viewer's embedding: Snowflake, with pgvector filling in
   embedded members Snowflake lacks, or pgvector alone when Snowflake isn't configured, times out
   or fails. Members without a vector rank last. Groups score their members' mean similarity.
4. The agents service reranks them with reasons; on any failure the similarity order is used.

No DB connection is held while waiting on Gemini, Snowflake or the agents service: the request's
transaction is committed first and everything needed later is read into plain values.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlmodel import Session, and_, func, or_, select, update

from app.config import get_settings
from app.models import Event, EventMember, Group, GroupMember, Profile, Request, User
from app.models.base import utcnow
from app.services import agents_client, embeddings, snowflake_store
from app.services.groups import count_user_groups, user_group_ids
from app.services.requests import Exclusions, excluded_for_viewer

log = logging.getLogger(__name__)

CANDIDATE_POOL = 20  # per type; at least `limit`
SIMILARITY_SCAN_LIMIT = 1000  # members scored per query
# Handles, and the SerpAPI notes that often repeat them, stay out of what the agent sees about
# other people, so a reason can't reveal them. The viewer's own text keeps them.
_PRIVATE_LINES = re.compile(r"^(?:Socials|Public info): .*$\n?", re.MULTILINE)


@dataclass(frozen=True)
class _Snapshot:
    """The event and viewer fields recommend() needs, read before the first commit."""
    event_id: str
    event_type: str
    tone: str
    description: str | None
    group_count: int | None
    max_size: int | None
    max_groups_per_user: int | None
    member_id: str
    user_id: str
    profile_text: str
    embedding: list[float] | None


@dataclass
class _Candidate:
    candidate_type: str  # user|group
    id: str
    profile_text: str
    similarity: float | None
    payload: dict[str, Any] = field(default_factory=dict)  # the response fields besides score/reason

    def sort_key(self, tiebreak: Any) -> tuple:
        return (self.similarity is None, -(self.similarity or 0.0), tiebreak, self.id)


def exclusions(db: Session, event_id: str, viewer_id: str) -> Exclusions:
    ex = excluded_for_viewer(db, event_id, viewer_id)
    my_groups = user_group_ids(db, viewer_id, event_id)
    pending = db.exec(
        select(Request).where(
            Request.event_id == event_id,
            Request.status == "pending",
            or_(
                Request.sender_id == viewer_id,
                Request.target_user_id == viewer_id,
                Request.target_group_id.in_(my_groups),
            ),
        )
    ).all()
    for r in pending:
        if r.sender_id != viewer_id:
            ex.user_ids.add(r.sender_id)
        elif r.target_user_id:
            ex.user_ids.add(r.target_user_id)
        else:
            ex.group_ids.add(r.target_group_id)
    return ex


def _snapshot(event: Event, member: EventMember) -> _Snapshot:
    return _Snapshot(
        event_id=event.id, event_type=event.type, tone=event.tone, description=event.description,
        group_count=event.group_count, max_size=event.max_size,
        max_groups_per_user=event.max_groups_per_user,
        member_id=member.id, user_id=member.user_id, profile_text=member.profile_text or "",
        embedding=None if member.embedding is None else [float(v) for v in member.embedding],
    )


def _embed_viewer(db: Session, s: _Snapshot) -> list[float] | None:
    """Embed the viewer now (the background hook hasn't, or failed), store the vector and sync it
    to Snowflake. Called with no transaction open; only the UPDATE touches the DB."""
    if not s.profile_text.strip() or not get_settings().gemini_configured:
        return None
    try:
        (vector,) = embeddings.embed_texts([s.profile_text])
    except embeddings.EmbeddingError as exc:
        log.warning("Embedding the viewer failed: %s", exc)
        return None
    now = utcnow()
    # Only if the text is still the one we embedded; a newer change re-runs the hook.
    stored = db.exec(
        update(EventMember)
        .where(EventMember.id == s.member_id, EventMember.profile_text == s.profile_text)
        .values(embedding=vector, embedded_at=now)
    ).rowcount
    db.commit()
    if stored:
        embeddings.sync_to_snowflake(
            [snowflake_store.EmbeddingRow(s.member_id, s.event_id, s.user_id, vector, now)]
        )
    return vector


def _snowflake_similarities(event_id: str, viewer_id: str, vector: list[float] | None) -> dict[str, float] | None:
    """Snowflake's {user_id: similarity}, or None when it isn't configured or fails."""
    if vector is None or not get_settings().snowflake_configured:
        return None
    try:
        return snowflake_store.similarities(event_id, vector, viewer_id, SIMILARITY_SCAN_LIMIT)
    except snowflake_store.SnowflakeError as exc:
        log.warning("Snowflake similarity failed, using pgvector: %s", exc)
        return None


def _pgvector_similarities(
    db: Session, event_id: str, viewer_id: str, vector: list[float], skip: set[str]
) -> dict[str, float]:
    distance = EventMember.embedding.cosine_distance(vector)
    query = select(EventMember.user_id, distance).where(
        EventMember.event_id == event_id,
        EventMember.user_id != viewer_id,
        EventMember.embedding.is_not(None),
    )
    if skip:
        query = query.where(EventMember.user_id.not_in(list(skip)))
    rows = db.exec(query.order_by(distance).limit(SIMILARITY_SCAN_LIMIT)).all()
    return {user_id: 1.0 - float(d) for user_id, d in rows if d is not None}


def similarity_scores(
    db: Session, event_id: str, viewer_id: str, vector: list[float] | None,
    remote: dict[str, float] | None,
) -> dict[str, float]:
    """{user_id: cosine similarity to the viewer}: Snowflake's answer (`remote`) plus pgvector for
    the embedded members it lacks (not synced yet, or a failed sync), or pgvector alone."""
    if vector is None:
        return {}
    sims = dict(remote or {})
    sims.update(_pgvector_similarities(db, event_id, viewer_id, vector, skip=set(sims)))
    return sims


def _strip_private(text: str) -> str:
    return _PRIVATE_LINES.sub("", text or "").strip()


def _people_blocked(db: Session, s: _Snapshot, viewer_groups: int) -> bool:
    """True when no user -> user accept could succeed for the viewer (requests._form_group)."""
    if s.max_size < 2 or viewer_groups >= s.max_groups_per_user:
        return True
    groups_formed = db.exec(
        select(func.count()).select_from(Group).where(Group.event_id == s.event_id)
    ).one()
    return groups_formed >= s.group_count


def _users_at_group_limit(db: Session, s: _Snapshot) -> set[str]:
    """People already in max_groups_per_user groups: accepting them would be group_limit_per_user."""
    return set(
        db.exec(
            select(GroupMember.user_id)
            .where(GroupMember.event_id == s.event_id)
            .group_by(GroupMember.user_id)
            .having(func.count() >= s.max_groups_per_user)
        ).all()
    )


def _people(db: Session, s: _Snapshot, ex: Exclusions, sims: dict[str, float], pool: int) -> list[_Candidate]:
    rows = db.exec(
        select(EventMember.user_id, EventMember.profile_text, EventMember.joined_at, User.name, Profile.summary)
        .join(User, User.id == EventMember.user_id)
        .outerjoin(Profile, Profile.user_id == EventMember.user_id)
        .where(EventMember.event_id == s.event_id, EventMember.user_id.not_in(list(ex.user_ids)))
    ).all()
    ranked = sorted(
        (
            (
                _Candidate(
                    "user", user_id, _strip_private(text), sims.get(user_id),
                    {"user_id": user_id, "name": name, "summary": summary},
                ),
                joined_at,
            )
            for user_id, text, joined_at, name, summary in rows
        ),
        key=lambda pair: pair[0].sort_key(pair[1]),
    )
    return [c for c, _ in ranked[:pool]]


def _groups(db: Session, s: _Snapshot, ex: Exclusions, sims: dict[str, float], pool: int) -> list[_Candidate]:
    groups = db.exec(
        select(Group).where(Group.event_id == s.event_id, Group.id.not_in(list(ex.group_ids)))
    ).all()
    if not groups:
        return []
    members: dict[str, list[tuple[str, str, str]]] = {g.id: [] for g in groups}
    for group_id, user_id, name, text in db.exec(
        select(GroupMember.group_id, GroupMember.user_id, User.name, EventMember.profile_text)
        .join(User, User.id == GroupMember.user_id)
        .outerjoin(
            EventMember,
            and_(EventMember.event_id == GroupMember.event_id, EventMember.user_id == GroupMember.user_id),
        )
        .where(GroupMember.group_id.in_(list(members)))
        .order_by(GroupMember.joined_at, GroupMember.id)
    ).all():
        members[group_id].append((user_id, name, text or ""))

    ranked: list[tuple[_Candidate, datetime]] = []
    for g in groups:
        group_members = members[g.id]
        size = len(group_members)
        if size == 0 or size >= s.max_size:
            continue  # full (or emptied by a concurrent leave)
        known = [sims[uid] for uid, _, _ in group_members if uid in sims]
        text = "\n\n".join(
            [f"Group: {g.name} ({size} of {s.max_size} members)"]
            + [f"Member {name}:\n{_strip_private(t)}" for _, name, t in group_members]
        )
        candidate = _Candidate(
            "group", g.id, text, sum(known) / len(known) if known else None,
            {
                "group_id": g.id,
                "name": g.name,
                "size": size,
                "max_size": s.max_size,
                "members": [{"user_id": uid, "name": name} for uid, name, _ in group_members],
            },
        )
        ranked.append((candidate, g.created_at))
    ranked.sort(key=lambda pair: pair[0].sort_key(pair[1]))
    return [c for c, _ in ranked[:pool]]


def _score(value: float | None) -> float:
    return round(value, 4) if value is not None else 0.0


def _by_similarity(candidates: list[_Candidate], limit: int) -> list[dict]:
    return [{**c.payload, "score": _score(c.similarity), "reason": None} for c in candidates[:limit]]


def recommend(db: Session, event: Event, viewer: EventMember, limit: int) -> dict:
    """The recommendations body for an event member (contract section 4)."""
    pool = max(CANDIDATE_POOL, limit)
    s = _snapshot(event, viewer)
    db.commit()  # release the connection before Gemini/Snowflake; nothing below reads ORM attributes

    vector = s.embedding if s.embedding is not None else _embed_viewer(db, s)
    remote = _snowflake_similarities(s.event_id, s.user_id, vector)

    sims = similarity_scores(db, s.event_id, s.user_id, vector, remote)
    ex = exclusions(db, s.event_id, s.user_id)
    people: list[_Candidate] = []
    groups: list[_Candidate] = []
    if s.event_type == "structured":
        viewer_groups = count_user_groups(db, s.event_id, s.user_id)
        if not _people_blocked(db, s, viewer_groups):
            ex.user_ids |= _users_at_group_limit(db, s)
            people = _people(db, s, ex, sims, pool)
        if viewer_groups < s.max_groups_per_user:
            groups = _groups(db, s, ex, sims, pool)
    else:
        people = _people(db, s, ex, sims, pool)
    db.commit()  # done reading; don't hold a connection during the agents call

    candidates = people + groups
    picks = agents_client.rerank(
        {"event_id": s.event_id, "type": s.event_type, "tone": s.tone, "description": s.description},
        {"user_id": s.user_id, "profile_text": s.profile_text},
        [
            {"candidate_type": c.candidate_type, "id": c.id, "profile_text": c.profile_text,
             "similarity": _score(c.similarity)}
            for c in candidates
        ],
        min(50, limit * (bool(people) + bool(groups)) or limit),
    )
    if picks is None:
        return {"ranked_by": "similarity", "people": _by_similarity(people, limit),
                "groups": _by_similarity(groups, limit)}

    by_key = {(c.candidate_type, c.id): c for c in candidates}
    out: dict[str, list[dict]] = {"user": [], "group": []}
    for pick in picks:
        c = by_key[(pick["candidate_type"], pick["id"])]
        if len(out[c.candidate_type]) < limit:
            score = pick["score"] if pick["score"] is not None else _score(c.similarity)
            out[c.candidate_type].append({**c.payload, "score": round(score, 4), "reason": pick["reason"]})
    # A type the agent returned nothing for keeps its similarity order rather than coming back empty.
    for ctype, ranked in (("user", people), ("group", groups)):
        if not out[ctype]:
            out[ctype] = _by_similarity(ranked, limit)
    return {"ranked_by": "gemini", "people": out["user"], "groups": out["group"]}
