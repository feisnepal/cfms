"""User types: who a person says they are, what each type must tell us, and the access it starts with.

The type is NOT a permission. `User.role` still decides what a person may do; the type decides what we ask at
sign-up, what a super admin checks on approval, and the default access tier (a table, so it is easy to change).
"""
import re
from typing import Any, Optional

from ..models.user import UserDesignation, UserType

STUDENT_LEVELS = ("university", "college", "campus")
ORG_KINDS = ("cfug", "ngo", "ingo", "donor", "government", "company", "other")

# type -> the access tier a new account starts with. read_only: may look, may not change anything.
DEFAULT_ACCESS = {
    UserType.OFFICIAL: "full",
    UserType.STUDENT: "read_only",
    UserType.RESEARCHER: "read_only",
    UserType.ORGANIZATION: "full",
}

# type -> (key, kind) for what lives in User.type_details. kind: text | email | choice:<a,b> | orcid(optional)
_FIELDS = {
    UserType.STUDENT: [("level", "choice"), ("institution", "text"), ("programme", "text"),
                       ("supervisor_name", "text"), ("supervisor_email", "email")],
    UserType.RESEARCHER: [("affiliation", "text"), ("topic", "text"), ("orcid", "orcid")],
    UserType.ORGANIZATION: [("organization_name", "text"), ("org_kind", "choice"), ("position", "text")],
}
_CHOICES = {"level": STUDENT_LEVELS, "org_kind": ORG_KINDS}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


class TypeDetailsError(ValueError):
    """`field` is the missing or malformed key, so the form can point at it."""

    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


def default_access(user_type: Optional[str]) -> str:
    try:
        return DEFAULT_ACCESS[UserType(user_type)]
    except ValueError:
        return "full"  # unspecified (legacy) accounts keep what they had


def clean(user_type: UserType, designation: Optional[str], sub_division: Optional[str],
          details: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Validate what a type asks for. Returns {designation, sub_division, type_details} to store."""
    details = details or {}
    if user_type == UserType.OFFICIAL:
        if designation not in {d.value for d in UserDesignation}:
            raise TypeDetailsError("designation")
        if len((sub_division or "").strip()) < 2:
            raise TypeDetailsError("sub_division")
        return {"designation": designation, "sub_division": sub_division.strip(), "type_details": None}

    out: dict[str, Any] = {}
    for key, kind in _FIELDS[user_type]:
        raw = str(details.get(key) or "").strip()
        if kind == "orcid":
            if raw and not _ORCID.match(raw):
                raise TypeDetailsError(key)
            if raw:
                out[key] = raw
            continue
        if not raw or len(raw) > 255:
            raise TypeDetailsError(key)
        if kind == "choice" and raw not in _CHOICES[key]:
            raise TypeDetailsError(key)
        if kind == "email" and not _EMAIL.match(raw):
            raise TypeDetailsError(key)
        out[key] = raw.lower() if kind == "email" else raw
    return {"designation": None, "sub_division": None, "type_details": out}


def apply_type(db, user, user_type: UserType, designation: Optional[str], sub_division: Optional[str],
               details: Optional[dict[str, Any]]) -> None:
    """Validate and store a declared type on ``user`` (raises TypeDetailsError), joining or creating the
    organisation for type ``organization``. The caller commits.

    A name that already exists joins that organisation as a member; a new name creates it, unverified, with
    this user as its owner. Nothing here approves anyone: the owner of a *verified* organisation can later vouch."""
    from sqlalchemy import func
    from sqlalchemy.exc import IntegrityError

    from ..models.organization import Organization

    cleaned = clean(user_type, designation, sub_division, details)
    user.user_type = user_type.value
    user.designation = cleaned["designation"]
    user.sub_division = cleaned["sub_division"]
    user.type_details = cleaned["type_details"]
    if user_type != UserType.ORGANIZATION:
        user.organization_id, user.org_member_role = None, None
        return

    name = cleaned["type_details"]["organization_name"]
    org = db.query(Organization).filter(func.lower(Organization.name) == name.lower()).first()
    if org is None:
        try:
            with db.begin_nested():  # a racing sign-up may create the same name first
                org = Organization(name=name, kind=cleaned["type_details"]["org_kind"],
                                   contact_email=user.email or "", created_by=user.id)
                db.add(org)
                db.flush()
            user.org_member_role = "owner"
        except IntegrityError:
            org = db.query(Organization).filter(func.lower(Organization.name) == name.lower()).one()
            user.org_member_role = "member"
    else:
        user.org_member_role = "member"
    user.organization_id = org.id
    user.org_vouched_at = user.org_vouched_by = None
