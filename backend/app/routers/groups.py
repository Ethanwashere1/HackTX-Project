"""Contract section 7: the team page, renaming and leaving a group (members only)."""

from typing import Annotated

from fastapi import APIRouter, Response
from pydantic import BaseModel, StringConstraints

from app.auth.deps import CurrentUser, DbSession
from app.services import groups as svc

router = APIRouter(prefix="/api/groups", tags=["groups"])


class GroupPatch(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


@router.get("/{group_id}")
def get_group(group_id: str, user: CurrentUser, db: DbSession):
    return svc.group_payload(db, svc.get_group_for_member(db, group_id, user))


@router.patch("/{group_id}")
def rename_group(group_id: str, body: GroupPatch, user: CurrentUser, db: DbSession):
    group = svc.get_group_for_member(db, group_id, user)
    group.name = body.name
    db.add(group)
    db.commit()
    db.refresh(group)
    return svc.group_payload(db, group)


@router.post("/{group_id}/leave", status_code=204)
def leave_group(group_id: str, user: CurrentUser, db: DbSession):
    svc.leave_group(db, group_id, user)
    return Response(status_code=204)
