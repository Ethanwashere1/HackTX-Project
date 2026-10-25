"""Groups: default names, membership helpers, the team page and connections (contacts live here)."""

import secrets

from sqlmodel import Session, delete, func, or_, select

from app.errors import AppError
from app.models import Connection, Group, GroupMember, Profile, Request, Thread, User
from app.models.base import iso
from app.services.threads import remove_participant
from app.services.users import list_contacts

_ADJECTIVES = [
    "Amber", "Bold", "Brave", "Bright", "Cosmic", "Crimson", "Electric", "Golden", "Jade",
    "Lucky", "Lunar", "Mighty", "Neon", "Nimble", "Quantum", "Rapid", "Solar", "Stellar",
    "Swift", "Velvet",
]
_NOUNS = [
    "Comet", "Falcon", "Fox", "Galaxy", "Harbor", "Lynx", "Meteor", "Nebula", "Orbit", "Otter",
    "Panda", "Phoenix", "Pixel", "Raven", "Rocket", "Summit", "Tiger", "Voyager", "Wave", "Zephyr",
]


def default_group_name(db: Session, event_id: str) -> str:
    """"Team <Adjective> <Noun>", avoiding names already used in the event when possible."""
    taken = set(db.exec(select(Group.name).where(Group.event_id == event_id)).all())
    name = ""
    for _ in range(10):
        name = f"Squad {secrets.choice(_ADJECTIVES)} {secrets.choice(_NOUNS)}"
        if name not in taken:
            return name
    return name


def is_group_member(db: Session, group_id: str, user_id: str) -> bool:
    return (
        db.exec(
            select(GroupMember.id).where(
                GroupMember.group_id == group_id, GroupMember.user_id == user_id
            )
        ).first()
        is not None
    )


def group_member_ids(db: Session, group_id: str) -> list[str]:
    return list(
        db.exec(
            select(GroupMember.user_id)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.joined_at, GroupMember.id)
        ).all()
    )


def count_group_members(db: Session, group_id: str) -> int:
    return db.exec(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)
    ).one()


def count_user_groups(db: Session, event_id: str, user_id: str) -> int:
    return db.exec(
        select(func.count())
        .select_from(GroupMember)
        .where(GroupMember.event_id == event_id, GroupMember.user_id == user_id)
    ).one()


def user_group_ids(db: Session, user_id: str, event_id: str | None = None) -> list[str]:
    q = select(GroupMember.group_id).where(GroupMember.user_id == user_id)
    if event_id is not None:
        q = q.where(GroupMember.event_id == event_id)
    return list(db.exec(q).all())


def get_group_for_member(db: Session, group_id: str, user: User) -> Group:
    """404 for an unknown group, 403 `forbidden` for a non-member."""
    group = db.get(Group, group_id)
    if group is None:
        raise AppError(404, "not_found", "Group not found")
    if not is_group_member(db, group.id, user.id):
        raise AppError(403, "forbidden", "Only group members can see this group")
    return group


def leave_group(db: Session, group_id: str, user: User) -> None:
    """Remove the user from the group and its chats; delete the group (and its thread) once empty.

    Locks the group row first, like accepts do, so a concurrent accept into this group either
    sees the member gone or happens before the leave. Commits."""
    group = db.exec(
        select(Group)
        .where(Group.id == group_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if group is None:
        db.rollback()
        raise AppError(404, "not_found", "Group not found")
    if not is_group_member(db, group.id, user.id):
        db.rollback()
        raise AppError(403, "forbidden", "You're not in this group")
    db.exec(
        delete(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == user.id)
    )
    if group.thread_id:
        remove_participant(db, group.thread_id, user.id)
    for thread_id in db.exec(
        select(Request.thread_id).where(
            Request.target_group_id == group.id,
            Request.status == "pending",
            Request.sender_id != user.id,
            Request.thread_id.is_not(None),
        )
    ).all():
        remove_participant(db, thread_id, user.id)
    if count_group_members(db, group.id) == 0:
        # Pending requests to the group are deleted with it (FK cascade).
        thread = db.get(Thread, group.thread_id) if group.thread_id else None
        db.delete(group)
        if thread is not None:
            db.delete(thread)
    db.commit()


def _person(db: Session, user_id: str) -> dict:
    """Name, profile summary and contacts. Only call this for group-mates or connections.

    `summary` prefers the AI overview over the interview summary (CONTRACT §1 / team page).
    """
    from app.services.profiles import display_summary

    user = db.get(User, user_id)
    profile = db.exec(select(Profile).where(Profile.user_id == user_id)).first()
    return {
        "user_id": user_id,
        "name": user.name if user else None,
        "summary": display_summary(profile),
        "contacts": list_contacts(db, user_id),
    }


def group_payload(db: Session, group: Group) -> dict:
    """The squad page body. Includes contacts, so only return it to the group's members.

    The earliest member is treated as the squad owner (hosts / founders can't \"join\" again).
    """
    member_ids = group_member_ids(db, group.id)
    owner_id = member_ids[0] if member_ids else None
    return {
        "group_id": group.id,
        "event_id": group.event_id,
        "name": group.name,
        "thread_id": group.thread_id,
        "owner_user_id": owner_id,
        "members": [_person(db, uid) for uid in member_ids],
    }


def connections_payload(db: Session, event_id: str, user_id: str) -> list[dict]:
    """The user's connections in an event, with the other person's contacts."""
    rows = db.exec(
        select(Connection)
        .where(
            Connection.event_id == event_id,
            or_(Connection.user_a_id == user_id, Connection.user_b_id == user_id),
        )
        .order_by(Connection.created_at, Connection.id)
    ).all()
    out = []
    for c in rows:
        other = c.user_b_id if c.user_a_id == user_id else c.user_a_id
        out.append(
            {
                "connection_id": c.id,
                **_person(db, other),
                "thread_id": c.thread_id,
                "connected_at": iso(c.created_at),
            }
        )
    return out
