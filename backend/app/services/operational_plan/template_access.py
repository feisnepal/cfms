"""Who may see, use and copy a template: the one rule, used by every endpoint that hands a template to a user.

Before this each endpoint repeated "published, or yours, or you are the super admin", and plan creation did not check at all (a
template id was enough to build a plan from someone's private draft).

A template is visible to a user when

* it is theirs, or they are the super admin; or
* it is the system template; or
* it is live (``published`` / ``deprecated``) and shared to everyone (``public``), or shared to the author's office
  (``office``) and the user belongs to that same office (``organization_id``).

Using a template (building a plan from it, previewing it) needs only visibility. Copying it also needs the licence to allow it.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from ...models.op_template import OPTemplate
from ...models.user import UserRole

LIVE_STATUSES = ("published", "deprecated")
SCOPES = ("private", "office", "public")
TIERS = ("community", "verified", "official")
LICENSES = ("cc_by", "cc0", "view_only")


def _is_admin(user: Any) -> bool:
    return getattr(user, "role", None) == UserRole.SUPER_ADMIN


def visible_clause(user: Any):
    """SQL condition: templates this user may see."""
    if _is_admin(user):
        return sa.true()
    shared = sa.and_(OPTemplate.status.in_(LIVE_STATUSES), OPTemplate.share_scope == "public")
    parts = [OPTemplate.created_by == user.id, OPTemplate.is_system.is_(True), shared]
    org = getattr(user, "organization_id", None)
    if org is not None:
        parts.append(
            sa.and_(
                OPTemplate.status.in_(LIVE_STATUSES),
                OPTemplate.share_scope == "office",
                OPTemplate.organization_id == org,
            )
        )
    return sa.or_(*parts)


def ever_shared(tmpl: OPTemplate) -> bool:
    """Has this template been put out to others at any time (published at least once)? Sharing is the author's consent to be
    credited; taking it back later does not revoke that, so the credit chain keeps the name."""
    return tmpl.published_version is not None or bool(tmpl.is_system)


def can_view(tmpl: OPTemplate, user: Any) -> bool:
    if _is_admin(user) or tmpl.created_by == user.id or tmpl.is_system:
        return True
    if tmpl.status not in LIVE_STATUSES:
        return False
    if tmpl.share_scope == "public":
        return True
    org = getattr(user, "organization_id", None)
    return tmpl.share_scope == "office" and org is not None and tmpl.organization_id == org


def can_copy(tmpl: OPTemplate, user: Any) -> bool:
    """Visible, and the licence lets others copy it. The author and the super admin may always copy."""
    if not can_view(tmpl, user):
        return False
    if _is_admin(user) or tmpl.created_by == user.id:
        return True
    return tmpl.license != "view_only"
