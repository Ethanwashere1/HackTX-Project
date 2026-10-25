from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.errors import AppError
from app.models import ContactMethod, Org, OrgMember, Profile, User
from app.models.base import utcnow


def _account_conflict() -> AppError:
    return AppError(
        409, "account_conflict", "This email is already linked to a different Google account"
    )


def _find_or_build(
    db: Session, *, email: str, name: str, avatar_url: str | None, google_sub: str | None
) -> User:
    user = None
    if google_sub:
        user = db.exec(select(User).where(User.google_sub == google_sub)).first()
    if user is None:
        user = db.exec(select(User).where(User.email == email)).first()
        # Only link a Google account to an existing email when that user has none yet.
        if user is not None and google_sub and user.google_sub and user.google_sub != google_sub:
            raise _account_conflict()
    if user is None:
        return User(email=email, name=name, avatar_url=avatar_url, google_sub=google_sub)
    user.email = email
    user.name = name or user.name
    if avatar_url:
        user.avatar_url = avatar_url
    if google_sub:
        user.google_sub = google_sub
    user.updated_at = utcnow()
    return user


def upsert_user(
    db: Session,
    *,
    email: str,
    name: str,
    avatar_url: str | None = None,
    google_sub: str | None = None,
) -> User:
    """Find the user by Google `sub`, then by email; create if missing. Commits.

    An email that already belongs to a different Google account is never taken over: 409
    `account_conflict`. Two first logins racing for the same account retry once, then reuse
    whichever row won.
    """
    email = email.strip().lower()
    for attempt in range(2):
        user = _find_or_build(
            db, email=email, name=name, avatar_url=avatar_url, google_sub=google_sub
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt == 0:
                continue
            raise _account_conflict()
        db.refresh(user)
        return user
    raise AssertionError("unreachable")


def list_contacts(db: Session, user_id: str) -> list[dict]:
    rows = db.exec(
        select(ContactMethod)
        .where(ContactMethod.user_id == user_id)
        .order_by(ContactMethod.position, ContactMethod.id)
    ).all()
    return [{"kind": c.kind, "value": c.value} for c in rows]


def me_payload(db: Session, user: User) -> dict:
    """The GET /api/me body. `orgs` lists approved memberships only."""
    orgs = db.exec(
        select(Org.id, Org.name)
        .join(OrgMember, OrgMember.org_id == Org.id)
        .where(OrgMember.user_id == user.id, OrgMember.status == "approved")
        .order_by(Org.name)
    ).all()
    return {
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "orgs": [{"org_id": org_id, "name": name} for org_id, name in orgs],
        "contacts": list_contacts(db, user.id),
    }


def my_profile_payload(db: Session, user: User) -> dict:
    """The GET /api/me/profile body: the user's own shared profile. Leaves out the SerpAPI
    `social_notes` and the interview transcript. `overview` is the AI blurb (null until generated);
    `interviewed` is true once a summary is saved."""
    profile = db.exec(select(Profile).where(Profile.user_id == user.id)).first()
    return {
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "overview": profile.overview if profile else None,
        "summary": profile.summary if profile else None,
        "traits": (profile.traits or None) if profile else None,
        "socials": [
            {"kind": s["kind"], "value": s["value"]} for s in (profile.socials if profile else [])
        ],
        "contacts": list_contacts(db, user.id),
        "interviewed": profile is not None and profile.summary is not None,
    }
