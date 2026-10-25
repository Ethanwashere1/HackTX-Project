"""Contract section 2: orgs, join requests, roster and the event feed."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete

from app.auth.deps import CurrentUser, DbSession
from app.errors import AppError
from app.models import Org, OrgMember, OrgRosterEntry
from app.models.base import utcnow
from app.services import events as events_svc
from app.services import orgs as svc

router = APIRouter(prefix="/api/orgs", tags=["orgs"])

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Verification = Literal["manual", "email_domain", "roster"]
Domains = Annotated[list[Annotated[str, Field(max_length=260)]], Field(max_length=20)]


def _domains(v: list[str] | None) -> list[str] | None:
    return None if v is None else svc.clean_domains(v)


def _need_domains(verification: str | None, domains: list[str] | None) -> None:
    if verification == "email_domain" and not domains:
        raise ValueError("email_domain verification needs at least one email domain")


class OrgCreate(BaseModel):
    name: Text200
    verification: Verification = "manual"
    email_domains: Domains = Field(default_factory=list)
    discoverable: bool = True

    clean_email_domains = field_validator("email_domains")(_domains)

    @model_validator(mode="after")
    def _check(self):
        _need_domains(self.verification, self.email_domains)
        return self


class OrgPatch(BaseModel):
    """Omitted (or null) fields are left unchanged."""

    name: Text200 | None = None
    verification: Verification | None = None
    email_domains: Domains | None = None
    discoverable: bool | None = None

    clean_email_domains = field_validator("email_domains")(_domains)


class JoinOrgBody(BaseModel):
    message: str | None = Field(default=None, max_length=1000)

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


class AdminBody(BaseModel):
    user_id: str = Field(max_length=40)


@router.get("")
def list_orgs(user: CurrentUser, db: DbSession):
    return svc.list_orgs_payload(db, user)


@router.post("", status_code=201)
def create_org(body: OrgCreate, user: CurrentUser, db: DbSession):
    org = Org(
        name=body.name,
        verification=body.verification,
        email_domains=body.email_domains,
        discoverable=body.discoverable,
        created_by=user.id,
    )
    db.add(org)
    db.flush()
    admin = OrgMember(org_id=org.id, user_id=user.id, role="admin")
    svc.approve(admin, user.id)
    db.add(admin)
    db.commit()
    return {"org_id": org.id, "verification": org.verification}


@router.patch("/{org_id}")
def update_org(org_id: str, body: OrgPatch, user: CurrentUser, db: DbSession):
    """Change settings (admin). Pending requests the new settings accept are approved."""
    svc.require_admin(db, org_id, user)
    org = svc.get_org(db, org_id, lock=True)
    changes = body.model_dump(exclude_none=True)
    try:
        _need_domains(
            changes.get("verification", org.verification),
            changes.get("email_domains", org.email_domains),
        )
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc))
    for key, value in changes.items():
        setattr(org, key, value)
    db.add(org)
    if {"verification", "email_domains"} & changes.keys():
        svc.auto_approve_pending(db, org)
    db.commit()
    me = svc.get_org_member(db, org.id, user.id)
    return svc.org_payload(org, me, svc.approved_counts(db, [org.id]).get(org.id, 0))


@router.post("/{org_id}/join")
def join_org(org_id: str, user: CurrentUser, db: DbSession, body: JoinOrgBody | None = None):
    """Request to join. Auto-approved on an email-domain or roster match, else pending.
    A pending request keeps its place; a declined user may ask again."""
    org = svc.get_org(db, org_id)
    message = body.message if body else None
    member = svc.get_org_member(db, org.id, user.id, lock=True)
    if member is not None and member.status == "approved":
        raise AppError(409, "already_member", "You are already a member of this org")
    if member is None:
        member = OrgMember(org_id=org.id, user_id=user.id)
    elif member.status == "declined":
        member.requested_at = utcnow()
    member.status = "pending"
    if message is not None:
        member.message = message
    member.decided_at = member.decided_by = None
    if svc.auto_matcher(db, org)(user):
        svc.approve(member, None)
    db.add(member)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # a concurrent join by the same user created the row first
        member = svc.get_org_member(db, org.id, user.id)
        if member is None or member.status == "approved":
            raise AppError(409, "already_member", "You are already a member of this org")
    return {"status": member.status}


@router.get("/{org_id}/join-requests")
def list_join_requests(
    org_id: str,
    user: CurrentUser,
    db: DbSession,
    status: Literal["pending", "approved", "declined"] = "pending",
):
    svc.require_admin(db, org_id, user)
    return svc.join_requests_payload(db, org_id, status)


def _decide(db: DbSession, org_id: str, user_id: str, admin_id: str, status: str) -> dict:
    member = svc.get_org_member(db, org_id, user_id, lock=True)
    if member is None:
        raise AppError(404, "not_found", "No join request from that user")
    if member.status != "pending":
        raise AppError(409, "request_not_pending", f"This request is already {member.status}")
    if status == "approved":
        svc.approve(member, admin_id)
    else:
        member.status = "declined"
        member.decided_at = utcnow()
        member.decided_by = admin_id
    db.add(member)
    db.commit()
    return {"user_id": member.user_id, "status": member.status}


@router.post("/{org_id}/join-requests/{user_id}/approve")
def approve_join_request(org_id: str, user_id: str, user: CurrentUser, db: DbSession):
    svc.require_admin(db, org_id, user)
    return _decide(db, org_id, user_id, user.id, "approved")


@router.post("/{org_id}/join-requests/{user_id}/decline")
def decline_join_request(org_id: str, user_id: str, user: CurrentUser, db: DbSession):
    svc.require_admin(db, org_id, user)
    return _decide(db, org_id, user_id, user.id, "declined")


def _admin_org(org_id: str, user: CurrentUser, db: DbSession) -> Org:
    return svc.require_admin(db, org_id, user)


AdminOrg = Annotated[Org, Depends(_admin_org)]


async def _roster_upload(request: Request, _: AdminOrg) -> list[svc.RosterRow]:
    """Read (capped) and validate the uploaded CSV, after the admin check."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > svc.MAX_ROSTER_UPLOAD_BYTES:
        raise svc.too_large()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > svc.MAX_ROSTER_UPLOAD_BYTES:
            raise svc.too_large()
    data = svc.extract_upload(request.headers.get("content-type", ""), bytes(body))
    return svc.parse_roster_csv(data)


@router.put("/{org_id}/roster")
def put_roster(
    org: AdminOrg,
    rows: Annotated[list[svc.RosterRow], Depends(_roster_upload)],
    db: DbSession,
):
    """Replace the org's roster (admin). For `roster` orgs, pending requests that now match are
    approved. The roster itself is never returned by the API."""
    org = svc.get_org(db, org.id, lock=True)  # serializes concurrent uploads
    db.exec(delete(OrgRosterEntry).where(OrgRosterEntry.org_id == org.id))
    db.add_all(
        OrgRosterEntry(org_id=org.id, name=r.name, name_normalized=r.name_normalized, email=r.email)
        for r in rows
    )
    db.flush()
    if org.verification == "roster":
        svc.auto_approve_pending(db, org)
    db.commit()
    return {"entries": len(rows)}


@router.post("/{org_id}/admins")
def add_admin(org_id: str, body: AdminBody, user: CurrentUser, db: DbSession):
    """Make an approved member an admin (admin)."""
    svc.require_admin(db, org_id, user)
    member = svc.get_org_member(db, org_id, body.user_id, lock=True)
    if member is None or member.status != "approved":
        raise AppError(404, "not_found", "No approved member with that user_id")
    member.role = "admin"
    db.add(member)
    db.commit()
    return {"user_id": member.user_id, "role": member.role}


@router.get("/{org_id}/feed")
def org_feed(org_id: str, user: CurrentUser, db: DbSession):
    events_svc.require_org_member(db, org_id, user)
    return svc.feed_payload(db, org_id, user)
