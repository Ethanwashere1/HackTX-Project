"""Recommendations (contract section 4).

1. Exclusions: the viewer, their group-mates and groups, connections, anyone declined either way
   (requests.excluded_for_viewer), plus anyone with a pending request to or from the viewer
   (they're already in the requests inbox).
2. Similarity of each event member to the viewer's embedding: Snowflake, or pgvector when
   Snowflake isn't configured, times out or fails. Members without a vector rank last.
3. Candidates: the top people, and open groups (not full; none for informal events or once the
   viewer has reached max_groups_per_user) scored by their members' mean similarity.
4. The agents service reranks them with reasons; on any failure the similarity order is used.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlmodel import Session, and_, or_, select

from app.config import get_settings
from app.models import Event, EventMember, Group, GroupMember, Profile, Request, User
from app.services import agents_client, embeddings, snowflake_store
from app.services.groups import count_user_groups, user_group_ids
from app.services.requests import Exclusions, excluded_for_viewer

log = logging.getLogger(__name__)

CANDIDATE_POOL = 20  # per type; at least `limit`
SIMILARITY_SCAN_LIMIT = 1000  # members scored per query
# Handles stay out of what the agent sees about others, so a reason can't reveal them.
_SOCIALS_LINE = re.compile(r"^Socials: .*$\n?", re.MULTILINE)


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


def _viewer_vector(db: Session, member: EventMember) -> list[float] | None:
    """The viewer's embedding, embedding it now if the background hook hasn't (or failed)."""
    if member.embedding is None and get_settings().gemini_configured:
        embeddings.embed_members([member.id])
        db.refresh(member)
    if member.embedding is None:
        return None
    return [float(v) for v in member.embedding]


def _pgvector_similarities(
    db: Session, event_id: str, viewer_id: str, vector: list[float]
) -> dict[str, float]:
    distance = EventMember.embedding.cosine_distance(vector)
    rows = db.exec(
        select(EventMember.user_id, distance)
        .where(
            EventMember.event_id == event_id,
            EventMember.user_id != viewer_id,
            EventMember.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(SIMILARITY_SCAN_LIMIT)
    ).all()
    return {user_id: 1.0 - float(d) for user_id, d in rows if d is not None}


def similarity_scores(
    db: Session, event_id: str, viewer_id: str, vector: list[float] | None
) -> dict[str, float]:
    """{user_id: cosine similarity to the viewer} from Snowflake, falling back to pgvector."""
    if vector is None:
        return {}
    if get_settings().snowflake_configured:
        try:
            return snowflake_store.similarities(event_id, vector, viewer_id, SIMILARITY_SCAN_LIMIT)
        except snowflake_store.SnowflakeError as exc:
            log.warning("Snowflake similarity failed, using pgvector: %s", exc)
    return _pgvector_similarities(db, event_id, viewer_id, vector)


def _strip_socials(text: str) -> str:
    return _SOCIALS_LINE.sub("", text or "").strip()


def _people(db: Session, event: Event, ex: Exclusions, sims: dict[str, float], pool: int) -> list[_Candidate]:
    rows = db.exec(
        select(EventMember.user_id, EventMember.profile_text, EventMember.joined_at, User.name, Profile.summary)
        .join(User, User.id == EventMember.user_id)
        .outerjoin(Profile, Profile.user_id == EventMember.user_id)
        .where(EventMember.event_id == event.id, EventMember.user_id.not_in(list(ex.user_ids)))
    ).all()
    ranked = sorted(
        (
            (
                _Candidate(
                    "user", user_id, _strip_socials(text), sims.get(user_id),
                    {"user_id": user_id, "name": name, "summary": summary},
                ),
                joined_at,
            )
            for user_id, text, joined_at, name, summary in rows
        ),
        key=lambda pair: pair[0].sort_key(pair[1]),
    )
    return [c for c, _ in ranked[:pool]]


def _groups(db: Session, event: Event, ex: Exclusions, sims: dict[str, float], pool: int) -> list[_Candidate]:
    groups = db.exec(
        select(Group).where(Group.event_id == event.id, Group.id.not_in(list(ex.group_ids)))
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
        if size == 0 or size >= event.max_size:
            continue  # full (or emptied by a concurrent leave)
        known = [sims[uid] for uid, _, _ in group_members if uid in sims]
        text = "\n\n".join(
            [f"Group: {g.name} ({size} of {event.max_size} members)"]
            + [f"Member {name}:\n{_strip_socials(t)}" for _, name, t in group_members]
        )
        candidate = _Candidate(
            "group", g.id, text, sum(known) / len(known) if known else None,
            {
                "group_id": g.id,
                "name": g.name,
                "size": size,
                "max_size": event.max_size,
                "members": [{"user_id": uid, "name": name} for uid, name, _ in group_members],
            },
        )
        ranked.append((candidate, g.created_at))
    ranked.sort(key=lambda pair: pair[0].sort_key(pair[1]))
    return [c for c, _ in ranked[:pool]]


def _score(value: float | None) -> float:
    return round(value, 4) if value is not None else 0.0


def recommend(db: Session, event: Event, viewer: EventMember, limit: int) -> dict:
    """The recommendations body for an event member (contract section 4)."""
    pool = max(CANDIDATE_POOL, limit)
    ex = exclusions(db, event.id, viewer.user_id)
    vector = _viewer_vector(db, viewer)
    sims = similarity_scores(db, event.id, viewer.user_id, vector)
    people = _people(db, event, ex, sims, pool)
    groups: list[_Candidate] = []
    if event.type == "structured" and count_user_groups(db, event.id, viewer.user_id) < event.max_groups_per_user:
        groups = _groups(db, event, ex, sims, pool)
    viewer_text = viewer.profile_text
    event_info = {"event_id": event.id, "type": event.type, "tone": event.tone,
                  "description": event.description}
    db.commit()  # done reading; don't hold a connection during the agents call

    candidates = people + groups
    picks = agents_client.rerank(
        event_info,
        {"user_id": viewer.user_id, "profile_text": viewer_text},
        [
            {"candidate_type": c.candidate_type, "id": c.id, "profile_text": c.profile_text,
             "similarity": _score(c.similarity)}
            for c in candidates
        ],
        min(50, limit * (bool(people) + bool(groups)) or limit),
    )
    if picks is None:
        return {
            "ranked_by": "similarity",
            "people": [{**c.payload, "score": _score(c.similarity), "reason": None} for c in people[:limit]],
            "groups": [{**c.payload, "score": _score(c.similarity), "reason": None} for c in groups[:limit]],
        }

    by_key = {(c.candidate_type, c.id): c for c in candidates}
    out: dict[str, list[dict]] = {"user": [], "group": []}
    for pick in picks:
        c = by_key[(pick["candidate_type"], pick["id"])]
        if len(out[c.candidate_type]) < limit:
            score = pick["score"] if pick["score"] is not None else _score(c.similarity)
            out[c.candidate_type].append({**c.payload, "score": round(score, 4), "reason": pick["reason"]})
    return {"ranked_by": "gemini", "people": out["user"], "groups": out["group"]}
