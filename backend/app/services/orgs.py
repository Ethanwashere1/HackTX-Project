"""Orgs (contract section 2): admin checks, join auto-approval, roster parsing and the feed.

Auto-approval: `email_domain` orgs approve a user whose email domain (or a subdomain of it) is
listed; `roster` orgs approve a user whose email is on the roster. Only the email counts, since
Google verifies it: the name is the user's own Google display name, so a name matching a name-only
roster row is just a hint for admins (`roster_match: "name"` in the join-requests list) and the
request waits. Everything else waits for an admin too, and `manual` orgs always wait.

A request made again after a decline always waits for an admin. Its pending row keeps the
decline's `decided_at`/`decided_by`, while a first request has none: that is how the join and
auto_approve_pending tell the two apart.
"""

import csv
import email
import email.policy
import io
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session, col, func, or_, select

from app.errors import AppError
from app.models import Event, EventMember, Org, OrgMember, OrgRosterEntry, User
from app.models.base import iso, utcnow

MAX_ROSTER_BYTES = 1024 * 1024  # 1 MB CSV
MAX_ROSTER_ROWS = 5000
# Room for the multipart boundaries and part headers around the CSV.
MAX_ROSTER_UPLOAD_BYTES = MAX_ROSTER_BYTES + 64 * 1024
MAX_NAME = 200
MAX_EMAIL = 320

# Events that started this recently still count as upcoming (events have no end time).
FEED_GRACE = timedelta(hours=12)
FEED_LIMIT = 100
LIST_LIMIT = 500

_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_name(name: str | None) -> str | None:
    """Case-insensitive, whitespace-collapsed form used for roster name matching."""
    if not name:
        return None
    norm = " ".join(unicodedata.normalize("NFKC", name).casefold().split())
    return norm or None


def clean_domains(domains: list[str]) -> list[str]:
    """Lowercase, strip a leading "@", validate and dedupe email domains (ValueError if invalid)."""
    out: list[str] = []
    for d in domains:
        d = d.strip().lower().removeprefix("@")
        if not DOMAIN_RE.match(d):
            raise ValueError(f"invalid email domain {d!r}")
        if d not in out:
            out.append(d)
    return out


def _domain_matches(user_email: str, domains: list[str]) -> bool:
    domain = user_email.rsplit("@", 1)[-1].lower()
    return any(domain == d or domain.endswith("." + d) for d in domains)


# --- lookups and permissions ---------------------------------------------------------------------

def _locked(db: Session, stmt):
    """First row of `stmt` under SELECT ... FOR UPDATE, refreshing any copy in the session."""
    return db.exec(stmt.with_for_update().execution_options(populate_existing=True)).first()


def get_org(db: Session, org_id: str, *, lock: bool = False) -> Org:
    stmt = select(Org).where(Org.id == org_id)
    org = _locked(db, stmt) if lock else db.exec(stmt).first()
    if org is None:
        raise AppError(404, "not_found", "Org not found")
    return org


def get_org_member(
    db: Session, org_id: str, user_id: str, *, lock: bool = False
) -> OrgMember | None:
    stmt = select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
    return _locked(db, stmt) if lock else db.exec(stmt).first()


def require_admin(db: Session, org_id: str, user: User) -> Org:
    """The org, or 404 `not_found` if unknown / 403 `not_org_admin` unless the user is its admin."""
    org = get_org(db, org_id)
    member = get_org_member(db, org_id, user.id)
    if member is None or member.role != "admin" or member.status != "approved":
        raise AppError(403, "not_org_admin", "Only admins of this org can do that")
    return org


# --- auto-approval -------------------------------------------------------------------------------

def roster_matcher(db: Session, org_id: str) -> Callable[[User], str | None]:
    """How a user matches the org's roster: "email" (their email is listed), "name" (their name
    matches a row that has no email), or None. A row with an email matches by email only."""
    rows = db.exec(
        select(OrgRosterEntry.email, OrgRosterEntry.name_normalized).where(
            OrgRosterEntry.org_id == org_id
        )
    ).all()
    emails = {e for e, _ in rows if e}
    names = {n for e, n in rows if n and not e}

    def match(u: User) -> str | None:
        if u.email.lower() in emails:
            return "email"
        if normalize_name(u.name) in names:
            return "name"
        return None

    return match


def auto_matcher(db: Session, org: Org) -> Callable[[User], bool]:
    """A predicate telling whether the org's verification method auto-approves a user: on the
    (Google-verified) email only, never on the self-chosen name."""
    if org.verification == "email_domain":
        domains = list(org.email_domains or [])
        return lambda u: _domain_matches(u.email, domains)
    if org.verification == "roster":
        roster = roster_matcher(db, org.id)
        return lambda u: roster(u) == "email"
    return lambda u: False


def approve(member: OrgMember, decided_by: str | None) -> None:
    member.status = "approved"
    member.decided_at = utcnow()
    member.decided_by = decided_by


def auto_approve_pending(db: Session, org: Org) -> int:
    """Approve the org's pending requests that its verification method now accepts, except
    requests made again after a decline (those wait for an admin). No commit."""
    matches = auto_matcher(db, org)
    pending = db.exec(
        select(OrgMember, User)
        .join(User, User.id == OrgMember.user_id)
        .where(
            OrgMember.org_id == org.id,
            OrgMember.status == "pending",
            col(OrgMember.decided_at).is_(None),
        )
        .with_for_update(of=OrgMember)
    ).all()
    approved = 0
    for member, user in pending:
        if matches(user):
            approve(member, None)
            db.add(member)
            approved += 1
    return approved


# --- payloads ------------------------------------------------------------------------------------

def org_payload(org: Org, member: OrgMember | None, member_count: int) -> dict:
    return {
        "org_id": org.id,
        "name": org.name,
        "verification": org.verification,
        "email_domains": list(org.email_domains or []),
        "discoverable": org.discoverable,
        "member_count": member_count,
        "my_role": member.role if member else None,
        "my_status": member.status if member else None,
    }


def approved_counts(db: Session, org_ids: list[str]) -> dict[str, int]:
    if not org_ids:
        return {}
    rows = db.exec(
        select(OrgMember.org_id, func.count())
        .where(col(OrgMember.org_id).in_(org_ids), OrgMember.status == "approved")
        .group_by(OrgMember.org_id)
    ).all()
    return dict(rows)


def list_orgs_payload(db: Session, user: User) -> dict:
    """Orgs the user has any membership row in (any status), plus discoverable orgs."""
    rows = db.exec(
        select(Org, OrgMember)
        .outerjoin(OrgMember, (OrgMember.org_id == Org.id) & (OrgMember.user_id == user.id))
        .where(or_(col(OrgMember.id).is_not(None), col(Org.discoverable).is_(True)))
        .order_by(Org.name, Org.id)
        .limit(LIST_LIMIT)
    ).all()
    counts = approved_counts(db, [org.id for org, _ in rows])
    return {"orgs": [org_payload(org, m, counts.get(org.id, 0)) for org, m in rows]}


def visible_org_payload(db: Session, org_id: str, user: User) -> dict:
    """One org as in GET /api/orgs, if it would be listed there for the user: discoverable, or
    the user has a membership row (any status). Otherwise 404, so hidden orgs can't be probed."""
    org = db.exec(select(Org).where(Org.id == org_id)).first()
    member = get_org_member(db, org_id, user.id) if org is not None else None
    if org is None or (member is None and not org.discoverable):
        raise AppError(404, "not_found", "Org not found")
    return org_payload(org, member, approved_counts(db, [org.id]).get(org.id, 0))


def join_requests_payload(db: Session, org_id: str, status: str) -> dict:
    """Admin view. `roster_match` ("email" | "name" | null) says how each user matches the org's
    uploaded roster, so admins can spot a name-only match, which is never auto-approved."""
    roster = roster_matcher(db, org_id)
    rows = db.exec(
        select(OrgMember, User)
        .join(User, User.id == OrgMember.user_id)
        .where(OrgMember.org_id == org_id, OrgMember.status == status)
        .order_by(OrgMember.requested_at, OrgMember.id)
        .limit(LIST_LIMIT)
    ).all()
    return {
        "requests": [
            {
                "user_id": u.id,
                "name": u.name,
                "email": u.email,
                "message": m.message,
                "requested_at": iso(m.requested_at),
                "roster_match": roster(u),
            }
            for m, u in rows
        ]
    }


def feed_payload(db: Session, org_id: str, user: User) -> dict:
    """Upcoming events of the org (unscheduled ones last). Caller checks membership."""
    org = get_org(db, org_id)
    counts = (
        select(EventMember.event_id, func.count().label("n"))
        .group_by(EventMember.event_id)
        .subquery()
    )
    rows = db.exec(
        select(Event, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.event_id == Event.id)
        .where(
            Event.org_id == org_id,
            or_(
                col(Event.starts_at).is_(None),
                col(Event.starts_at) >= utcnow() - FEED_GRACE,
            ),
        )
        .order_by(col(Event.starts_at).asc().nulls_last(), col(Event.created_at).desc())
        .limit(FEED_LIMIT)
    ).all()
    event_ids = [e.id for e, _ in rows]
    joined = set(
        db.exec(
            select(EventMember.event_id).where(
                EventMember.user_id == user.id, col(EventMember.event_id).in_(event_ids)
            )
        ).all()
    ) if event_ids else set()
    return {
        "org_id": org_id,
        "name": org.name,
        "events": [
            {
                "event_id": e.id,
                "name": e.name,
                "type": e.type,
                "tone": e.tone,
                "starts_at": iso(e.starts_at),
                "member_count": n,
                "joined": e.id in joined,
            }
            for e, n in rows
        ],
    }


# --- roster upload -------------------------------------------------------------------------------

@dataclass(frozen=True)
class RosterRow:
    name: str | None
    name_normalized: str | None
    email: str | None


def invalid_roster(message: str) -> AppError:
    return AppError(422, "invalid_roster", message)


def too_large() -> AppError:
    return invalid_roster(f"The roster file is too large (max {MAX_ROSTER_BYTES // 1024} KB)")


def extract_upload(content_type: str, body: bytes, field: str = "file") -> bytes:
    """The bytes of form field `field` from a multipart/form-data body (stdlib parser, so no
    python-multipart dependency)."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise invalid_roster("Upload the roster as multipart/form-data with a `file` field")
    msg = email.message_from_bytes(
        b"Content-Type: " + content_type.encode("latin-1", "replace")
        + b"\r\nMIME-Version: 1.0\r\n\r\n" + body,
        policy=email.policy.HTTP,
    )
    if msg.is_multipart():
        for part in msg.iter_parts():
            if part.get_param("name", header="content-disposition") == field:
                data = part.get_payload(decode=True) or b""
                if len(data) > MAX_ROSTER_BYTES:
                    raise too_large()
                return data
    raise invalid_roster("The upload has no `file` field")


def parse_roster_csv(data: bytes) -> list[RosterRow]:
    """Validate a CSV with `name` and/or `email` columns (any order, case-insensitive headers).
    Blank rows are skipped and duplicates dropped. 422 `invalid_roster` on any problem."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise invalid_roster("The roster must be a UTF-8 CSV file")
    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        header = next((r for r in reader if any(c.strip() for c in r)), None)
        if header is None:
            raise invalid_roster("The roster is empty; it needs a `name` and/or `email` header")
        columns = [c.strip().lower() for c in header]
        if "name" not in columns and "email" not in columns:
            raise invalid_roster("The roster needs a `name` and/or `email` column")
        if columns.count("name") > 1 or columns.count("email") > 1:
            raise invalid_roster("The roster has duplicate `name` or `email` columns")
        name_i = columns.index("name") if "name" in columns else None
        email_i = columns.index("email") if "email" in columns else None

        out: dict[tuple[str | None, str | None], RosterRow] = {}
        count = 0
        for row in reader:
            if not any(c.strip() for c in row):
                continue
            count += 1
            if count > MAX_ROSTER_ROWS:
                raise invalid_roster(f"The roster has more than {MAX_ROSTER_ROWS} rows")
            line = reader.line_num
            name = row[name_i].strip() if name_i is not None and name_i < len(row) else ""
            mail = row[email_i].strip() if email_i is not None and email_i < len(row) else ""
            mail = mail.lower()
            if len(name) > MAX_NAME:
                raise invalid_roster(f"Line {line}: name is too long (max {MAX_NAME} characters)")
            if mail and (len(mail) > MAX_EMAIL or not _EMAIL_RE.match(mail)):
                raise invalid_roster(f"Line {line}: invalid email")
            if not name and not mail:
                continue
            entry = RosterRow(name or None, normalize_name(name), mail or None)
            out.setdefault((entry.name_normalized, entry.email), entry)
    except csv.Error as exc:
        raise invalid_roster(f"The roster is not a valid CSV file: {exc}")
    return list(out.values())
