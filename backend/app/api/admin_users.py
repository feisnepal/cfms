"""Super-admin user panel: see every account and give it a role.

New accounts are created as plain users (and PENDING, see ``/auth/register``); nobody can pick their own role at sign-up. This is
the one place a role is assigned. The role list is read from ``UserRole``, so a role added to the enum later appears here without
any change to this file (only the one-line description below is optional).

Guards, because a role decides who may publish templates, approve accounts and read household data:
  * super-admin only;
  * you cannot change your own role (a super admin cannot lock themselves out or elevate by accident);
  * (so the system always keeps a super admin: the caller is one, and cannot demote themselves);
  * every change is written to ``user_role_changes`` with who made it.
Approving / suspending an account stays with ``/auth/users/{id}/approve`` and ``/suspend`` (org admin and above).
"""

from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.exceptions import i18n_error
from ..models.user import User, UserRole, UserStatus, UserType
from ..models.user_role_change import UserRoleChange
from ..schemas.auth import UserResponse
from ..utils.auth import require_super_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/users", tags=["Admin Users"])

# one line each; a role missing here is still listed (label only)
ROLE_DESCRIPTIONS = {
    UserRole.GUEST: "Read-only visitor.",
    UserRole.USER: "A community-forest user: creates and manages their own forests.",
    UserRole.ORG_ADMIN: "Approves and suspends accounts of an organisation.",
    UserRole.SUPER_ADMIN: "Everything, including this panel and publishing templates.",
    UserRole.TEMPLATE_DESIGNER: "Authors Operational Plan templates; cannot review or publish them.",
}


class RoleInfo(BaseModel):
    value: str
    label: str
    description: str


class RoleChange(BaseModel):
    role: UserRole


@router.get("/roles", response_model=List[RoleInfo])
def list_roles(current_user: User = Depends(require_super_admin)):
    """Every role the system knows, with a one-line description."""
    return [
        RoleInfo(value=r.value, label=r.value.replace("_", " ").title(), description=ROLE_DESCRIPTIONS.get(r, ""))
        for r in UserRole
    ]


@router.get("", response_model=List[UserResponse])
def list_users(
    q: Optional[str] = Query(None, description="part of the email or the name"),
    role: Optional[UserRole] = None,
    user_type: Optional[UserType] = None,
    account_status: Optional[UserStatus] = Query(None, alias="status"),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Accounts, newest first (pending ones are not hidden)."""
    query = db.query(User)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(User.email.ilike(like), User.full_name.ilike(like)))
    if role is not None:
        query = query.filter(User.role == role)
    if user_type is not None:
        query = query.filter(User.user_type == user_type.value)
    if account_status is not None:
        query = query.filter(User.status == account_status)
    return query.order_by(User.created_at.desc()).all()


@router.patch("/{user_id}/role", response_model=UserResponse)
def set_role(
    user_id: UUID,
    body: RoleChange,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Give a user a role. Refused for yourself; every change is logged."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise i18n_error(status.HTTP_404_NOT_FOUND, "auth.user_not_found")
    if user.id == current_user.id:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.cannot_change_own_role")
    if user.role == body.role:
        return user  # idempotent
    old = user.role
    user.role = body.role
    db.add(UserRoleChange(user_id=user.id, changed_by=current_user.id, old_role=old.value, new_role=body.role.value))
    db.commit()
    db.refresh(user)
    logger.warning("role changed: user=%s %s -> %s by=%s", user.id, old.value, body.role.value, current_user.id)
    return user
