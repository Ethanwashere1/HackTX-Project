"""Requests and mutual consent (contract section 5).

Accepting is the only path that forms groups, adds group members or creates connections, and it
is where the event's limits are enforced. Every accept runs in one transaction that locks, in
this order: the event row (group_count, and it serializes accepts within the event), the target
group row (max_size), both users' event_members rows in id order (max_groups_per_user), then the
request row. Limits are re-checked only after the locks are held. Leaving a group locks the group
row first too, and decline/cancel lock only the request row, so the lock order never inverts.
For a structured user -> user accept, the group slot holds the group the pair already shares, if any.
Every accept also locks, last, the other pending requests it settles, to accept them with it: the
pair's crossing request, and in structured events any request between people now in the group.
"""

from dataclasses import dataclass, field

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, and_, func, or_, select

from app.errors import AppError
from app.models import Connection, Event, EventMember, Group, GroupMember, Request, User
from app.models.base import iso, utcnow
from app.services.events import get_membership, get_visible_event
from app.services.groups import (
    count_group_members,
    count_user_groups,
    default_group_name,
    group_member_ids,
    is_group_member,
    user_group_ids,
)
from app.services.threads import add_participants, create_thread


def _locked(db: Session, stmt):
    """First row of `stmt` under SELECT ... FOR UPDATE, refreshing any copy already in the session."""
    return db.exec(stmt.with_for_update().execution_options(populate_existing=True)).first()


def _connection_between(db: Session, event_id: str, u1: str, u2: str) -> Connection | None:
    a, b = sorted((u1, u2))
    return db.exec(
        select(Connection).where(
            Connection.event_id == event_id, Connection.user_a_id == a, Connection.user_b_id == b
        )
    ).first()


def _shared_group_id(db: Session, event_id: str, u1: str, u2: str) -> str | None:
    """A group in the event that both users are in, if any."""
    return db.exec(
        select(GroupMember.group_id)
        .where(GroupMember.event_id == event_id, GroupMember.user_id.in_([u1, u2]))
        .group_by(GroupMember.group_id)
        .having(func.count(func.distinct(GroupMember.user_id)) == 2)
        .order_by(GroupMember.group_id)
    ).first()


# --- send ----------------------------------------------------------------------------------------

def create_request(
    db: Session, user: User, *, event_id: str, target_type: str, target_id: str, message: str | None
) -> Request:
    """Validate and store a pending request with its chat thread. Commits."""
    event = get_visible_event(db, event_id, user)
    if get_membership(db, event.id, user.id) is None:
        raise AppError(403, "forbidden", "Join the event before sending requests")

    if target_type == "user":
        if target_id == user.id:
            raise AppError(422, "validation_error", "You can't send a request to yourself")
        if get_membership(db, event.id, target_id) is None:
            raise AppError(404, "not_found", "User not found in this event")
        if event.type == "informal" and _connection_between(db, event.id, user.id, target_id):
            raise AppError(409, "already_connected", "You're already connected")
        if event.type == "structured" and _shared_group_id(db, event.id, user.id, target_id):
            raise AppError(409, "already_in_group", "You're already in a group together")
        participants = [user.id, target_id]
    else:
        if event.type == "informal":
            raise AppError(422, "validation_error", "Informal events have no groups")
        group = db.get(Group, target_id)
        if group is None or group.event_id != event.id:
            raise AppError(404, "not_found", "Group not found in this event")
        if is_group_member(db, group.id, user.id):
            raise AppError(
                409,
                "already_in_group",
                "You're already in this squad — owners and members can't join again",
            )
        participants = [user.id, *group_member_ids(db, group.id)]

    thread = create_thread(db, event_id=event.id, kind="request", user_ids=participants)
    req = Request(
        event_id=event.id,
        sender_id=user.id,
        target_type=target_type,
        target_user_id=target_id if target_type == "user" else None,
        target_group_id=target_id if target_type == "group" else None,
        message=message,
        thread_id=thread.id,
    )
    db.add(req)
    try:
        db.commit()
    except IntegrityError:
        # uq_requests_pending_user / uq_requests_pending_group: one pending request per target.
        db.rollback()
        raise AppError(409, "duplicate_request", "You already have a pending request to them")
    db.refresh(req)
    return req


# --- list ----------------------------------------------------------------------------------------

def list_requests(db: Session, user: User, *, box: str, event_id: str | None) -> list[dict]:
    q = select(Request)
    if box == "outgoing":
        q = q.where(Request.sender_id == user.id)
    else:
        my_groups = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
        q = q.where(
            or_(Request.target_user_id == user.id, Request.target_group_id.in_(my_groups)),
            Request.sender_id != user.id,
        )
    if event_id:
        q = q.where(Request.event_id == event_id)
    rows = db.exec(q.order_by(Request.created_at.desc(), Request.id.desc())).all()

    user_ids = {r.sender_id for r in rows} | {r.target_user_id for r in rows if r.target_user_id}
    group_ids = {r.target_group_id for r in rows if r.target_group_id}
    names = dict(db.exec(select(User.id, User.name).where(User.id.in_(user_ids))).all()) if user_ids else {}
    group_names = (
        dict(db.exec(select(Group.id, Group.name).where(Group.id.in_(group_ids))).all())
        if group_ids else {}
    )

    out = []
    for r in rows:
        if r.target_type == "user":
            target = {"user_id": r.target_user_id, "name": names.get(r.target_user_id)}
        else:
            target = {"group_id": r.target_group_id, "name": group_names.get(r.target_group_id)}
        # The other side from the viewer's point of view: the target (user or group) for an
        # outgoing request, the sender for an incoming one.
        if box == "outgoing":
            other = {"type": r.target_type, "id": r.target_user_id or r.target_group_id,
                     "name": target["name"]}
        else:
            other = {"type": "user", "id": r.sender_id, "name": names.get(r.sender_id)}
        out.append(
            {
                "request_id": r.id,
                "event_id": r.event_id,
                "sender": {"user_id": r.sender_id, "name": names.get(r.sender_id)},
                "target_type": r.target_type,
                "target": target,
                "direction": box,
                "other_party": other,
                "message": r.message,
                "status": r.status,
                "thread_id": r.thread_id,
                "group_id": r.group_id,
                "connection_id": r.connection_id,
                "created_at": iso(r.created_at),
                "decided_at": iso(r.decided_at),
            }
        )
    return out


# --- decide --------------------------------------------------------------------------------------

def decision_payload(req: Request) -> dict:
    return {
        "request_id": req.id,
        "status": req.status,
        "group_id": req.group_id,
        "connection_id": req.connection_id,
    }


def _is_target_side(db: Session, req: Request, user_id: str) -> bool:
    if req.target_type == "user":
        return req.target_user_id == user_id
    return is_group_member(db, req.target_group_id, user_id)


def _get_for_target_side(db: Session, request_id: str, user: User, verb: str) -> Request:
    """The request if `user` may accept/decline it: 404 if unrelated, 403 for the sender."""
    req = db.get(Request, request_id)
    if req is None:
        raise AppError(404, "not_found", "Request not found")
    if _is_target_side(db, req, user.id):
        return req
    if req.sender_id == user.id:
        raise AppError(403, "forbidden", f"Only the recipient can {verb} this request")
    raise AppError(404, "not_found", "Request not found")


def _require_pending(req: Request) -> None:
    if req.status != "pending":
        raise AppError(409, "request_not_pending", f"This request is already {req.status}")


def _decide(req: Request, user: User, status: str) -> None:
    req.status = status
    req.decided_at = utcnow()
    req.decided_by = user.id


def accept_request(db: Session, request_id: str, user: User) -> Request:
    """Accept, forming a group, adding the sender to a group, or creating a connection. Commits."""
    req = _get_for_target_side(db, request_id, user, "accept")
    try:
        req = _accept_locked(db, req, user)
        db.commit()
    except AppError:
        db.rollback()  # release the row locks before the error response
        raise
    db.refresh(req)
    return req


def _accept_locked(db: Session, req: Request, user: User) -> Request:
    event = _locked(db, select(Event).where(Event.id == req.event_id))
    group = None
    if req.target_type == "group":
        group = _locked(db, select(Group).where(Group.id == req.target_group_id))
        if group is None:
            raise AppError(404, "not_found", "Group not found")
    elif event.type == "structured":
        # The pair may already be group-mates (a request sent while another accept committed).
        # Only accepts add members and they wait on the event lock, so this can only shrink later.
        shared = _shared_group_id(db, event.id, req.sender_id, req.target_user_id)
        if shared:
            group = _locked(db, select(Group).where(Group.id == shared))
    other = req.target_user_id or user.id
    db.exec(
        select(EventMember.id)
        .where(EventMember.event_id == event.id, EventMember.user_id.in_([req.sender_id, other]))
        .order_by(EventMember.id)
        .with_for_update()
    ).all()
    req = _locked(db, select(Request).where(Request.id == req.id))
    if req is None:  # deleted with its group while we waited
        raise AppError(404, "not_found", "Request not found")
    _require_pending(req)
    # Group membership may have changed while we waited for the locks.
    if not _is_target_side(db, req, user.id):
        raise AppError(403, "forbidden", "Only the recipient can accept this request")

    if event.type == "informal":
        _connect(db, event, req, user)
    elif req.target_type == "group":
        _join_group(db, event, group, req)
        _settle_pending(db, event, group, [req.sender_id], req, user)
    else:
        pair = [req.sender_id, req.target_user_id]
        if group is None or set(pair) - set(group_member_ids(db, group.id)):
            group = _form_group(db, event, req)  # no shared group, or one of them left it meanwhile
        else:
            req.group_id = group.id
        _settle_pending(db, event, group, pair, req, user)
    _decide(req, user, "accepted")
    db.add(req)
    db.flush()
    return req


def _check_user_limit(db: Session, event: Event, user_id: str) -> None:
    if count_user_groups(db, event.id, user_id) >= event.max_groups_per_user:
        raise AppError(
            409, "group_limit_per_user",
            f"That would put someone in more than {event.max_groups_per_user} group(s) in this event",
        )


def _add_member(db: Session, group: Group, user_id: str) -> None:
    db.add(GroupMember(group_id=group.id, event_id=group.event_id, user_id=user_id))
    if group.thread_id:
        add_participants(db, group.thread_id, [user_id])


def _form_group(db: Session, event: Event, req: Request) -> Group:
    groups_formed = db.exec(
        select(func.count()).select_from(Group).where(Group.event_id == event.id)
    ).one()
    if groups_formed >= event.group_count:
        raise AppError(409, "group_limit_reached", "This event already has all its groups")
    if event.max_size < 2:
        raise AppError(409, "group_full", "Groups in this event can't have two members")
    for uid in (req.sender_id, req.target_user_id):
        _check_user_limit(db, event, uid)
    thread = create_thread(db, event_id=event.id, kind="group", user_ids=[])
    group = Group(event_id=event.id, name=default_group_name(db, event.id), thread_id=thread.id)
    db.add(group)
    db.flush()
    for uid in (req.sender_id, req.target_user_id):
        _add_member(db, group, uid)
    req.group_id = group.id
    return group


def _join_group(db: Session, event: Event, group: Group, req: Request) -> None:
    if is_group_member(db, group.id, req.sender_id):
        raise AppError(409, "already_in_group", "The requester is already in this group")
    if count_group_members(db, group.id) >= event.max_size:
        raise AppError(409, "group_full", "This group is full")
    _check_user_limit(db, event, req.sender_id)
    _add_member(db, group, req.sender_id)
    # The new member can now accept other pending requests to the group, so let them see those chats.
    for thread_id in db.exec(
        select(Request.thread_id).where(
            Request.target_group_id == group.id,
            Request.status == "pending",
            Request.id != req.id,
            Request.thread_id.is_not(None),
        )
    ).all():
        add_participants(db, thread_id, [req.sender_id])
    req.group_id = group.id


def _settle_pending(
    db: Session, event: Event, group: Group, newcomers: list[str], req: Request, user: User
) -> None:
    """Accept, with `group`, the other pending requests this accept made moot: any user request
    between a newcomer and someone now in the group (the pair's crossing request, or one between a
    new member and an existing one), and any newcomer's own request to the group. Both people are
    group-mates already, so accepting one of these later would only form a second group with the
    same people or fail on max_groups_per_user."""
    mates = set(group_member_ids(db, group.id)) | set(newcomers)
    for other in db.exec(
        select(Request)
        .where(
            Request.event_id == event.id,
            Request.status == "pending",
            Request.id != req.id,
            or_(
                and_(Request.sender_id.in_(newcomers), Request.target_user_id.in_(mates)),
                and_(Request.sender_id.in_(mates), Request.target_user_id.in_(newcomers)),
                and_(Request.sender_id.in_(newcomers), Request.target_group_id == group.id),
            ),
        )
        .order_by(Request.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all():
        _decide(other, user, "accepted")
        other.group_id = group.id
        db.add(other)


def _connect(db: Session, event: Event, req: Request, user: User) -> None:
    """Connect the pair once. Both users have consented, so any other pending request between them
    (the crossing one they sent each other) is accepted with the same connection. If a connection
    already exists (a request sent while another accept was committing), it is reused."""
    con = _connection_between(db, event.id, req.sender_id, req.target_user_id)
    if con is None:
        a, b = sorted((req.sender_id, req.target_user_id))
        con = Connection(event_id=event.id, user_a_id=a, user_b_id=b, thread_id=req.thread_id)
        db.add(con)
        db.flush()
    req.connection_id = con.id
    pair = (req.sender_id, req.target_user_id)
    for other in db.exec(
        select(Request)
        .where(
            Request.event_id == event.id,
            Request.status == "pending",
            Request.id != req.id,
            Request.sender_id.in_(pair),
            Request.target_user_id.in_(pair),
            Request.sender_id != Request.target_user_id,
        )
        .order_by(Request.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all():
        _decide(other, user, "accepted")
        other.connection_id = con.id
        db.add(other)


def decline_request(db: Session, request_id: str, user: User) -> Request:
    req = _get_for_target_side(db, request_id, user, "decline")
    return _close(db, req, user, "declined")


def cancel_request(db: Session, request_id: str, user: User) -> Request:
    """The sender withdraws a pending request."""
    req = db.get(Request, request_id)
    if req is None:
        raise AppError(404, "not_found", "Request not found")
    if req.sender_id != user.id:
        if _is_target_side(db, req, user.id):
            raise AppError(403, "forbidden", "Only the sender can cancel this request")
        raise AppError(404, "not_found", "Request not found")
    return _close(db, req, user, "cancelled")


def _close(db: Session, req: Request, user: User, status: str) -> Request:
    try:
        req = _locked(db, select(Request).where(Request.id == req.id))
        if req is None:
            raise AppError(404, "not_found", "Request not found")
        _require_pending(req)
        _decide(req, user, status)
        db.add(req)
        db.commit()
    except AppError:
        db.rollback()
        raise
    db.refresh(req)
    return req


# --- recommendations support ---------------------------------------------------------------------

@dataclass
class Exclusions:
    user_ids: set[str] = field(default_factory=set)
    group_ids: set[str] = field(default_factory=set)


def excluded_for_viewer(db: Session, event_id: str, viewer_id: str) -> Exclusions:
    """Users and groups never recommended to the viewer in this event (contract section 4):
    the viewer, their group-mates and groups, their connections, and anyone the viewer declined
    or was declined by (including requests to or from the viewer's current groups).
    Full groups and the max_groups_per_user rule are left to the recommendations query."""
    my_groups = set(user_group_ids(db, viewer_id, event_id))
    ex = Exclusions(user_ids={viewer_id}, group_ids=set(my_groups))
    if my_groups:
        ex.user_ids.update(
            db.exec(select(GroupMember.user_id).where(GroupMember.group_id.in_(my_groups))).all()
        )
    for a, b in db.exec(
        select(Connection.user_a_id, Connection.user_b_id).where(
            Connection.event_id == event_id,
            or_(Connection.user_a_id == viewer_id, Connection.user_b_id == viewer_id),
        )
    ).all():
        ex.user_ids.update((a, b))
    declined = db.exec(
        select(Request).where(
            Request.event_id == event_id,
            Request.status == "declined",
            or_(
                Request.sender_id == viewer_id,
                Request.target_user_id == viewer_id,
                Request.decided_by == viewer_id,
                Request.target_group_id.in_(my_groups),
            ),
        )
    ).all()
    for r in declined:
        if r.sender_id == viewer_id:
            if r.target_user_id:
                ex.user_ids.add(r.target_user_id)
            else:
                ex.group_ids.add(r.target_group_id)
        else:
            ex.user_ids.add(r.sender_id)
    return ex
