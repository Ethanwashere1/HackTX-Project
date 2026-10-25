"""Contract section 1: the signed-in user, contact methods, and shared profile."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from sqlmodel import delete

from app.auth.deps import CurrentUser, DbSession
from app.models import ContactMethod
from app.services import profiles as profile_svc
from app.services.users import list_contacts, me_payload

router = APIRouter(prefix="/api/me", tags=["me"])

ContactKind = Literal[
    "discord", "phone", "email", "instagram", "facebook", "linkedin", "github", "other"
]


class ContactIn(BaseModel):
    kind: ContactKind
    value: str = Field(max_length=300)

    @field_validator("value")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


class ContactsBody(BaseModel):
    contacts: list[ContactIn] = Field(max_length=20)


@router.get("")
def get_me(user: CurrentUser, db: DbSession):
    return me_payload(db, user)


@router.get("/profile")
def get_my_profile(user: CurrentUser, db: DbSession):
    """Shared person profile: overview, interview summary/traits, contacts, socials."""
    profile = profile_svc.get_or_create_profile(db, user.id)
    db.commit()  # persist an empty profile row if this was the first touch
    return {
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "overview": profile.overview,
        "summary": profile.summary,
        "traits": dict(profile.traits) if profile.traits else {},
        "contacts": list_contacts(db, user.id),
        "socials": list(profile.socials) if profile.socials else [],
    }


@router.put("/contacts")
def put_contacts(body: ContactsBody, user: CurrentUser, db: DbSession):
    """Replace the user's contact methods. Returns {"contacts": [...]}."""
    db.exec(delete(ContactMethod).where(ContactMethod.user_id == user.id))
    for i, c in enumerate(body.contacts):
        db.add(ContactMethod(user_id=user.id, kind=c.kind, value=c.value, position=i))
    db.commit()
    return {"contacts": list_contacts(db, user.id)}
