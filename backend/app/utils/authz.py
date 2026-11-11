"""Shared authorisation helper for calculation-scoped resources.

H2.4 / S1-04. Ownership was checked ad hoc, spelled out at each call site, and
simply absent at others — five tile and query routes in `tiles.py` took no
credentials at all, so any calculation id was enough to read another
community's raster analysis and point queries.

One helper so the check exists in one place and reads the same everywhere.
H2.7 / S2-07 replaces the remaining hand-written comparisons with it.
"""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models.calculation import Calculation
from ..models.user import User, UserRole


def is_owner_or_admin(calculation: Calculation, user: User) -> bool:
    """Whether `user` may act on `calculation`.

    Deliberately matches the check already used by the authenticated routes in
    this area (owner, or super admin) rather than quietly widening access —
    the role matrix itself is H2.7's subject.
    """
    return calculation.user_id == user.id or user.role == UserRole.SUPER_ADMIN


def require_calculation_access(
    db: Session, calculation_id: str, user: User
) -> Calculation:
    """Load a calculation the user is entitled to, or refuse.

    404 when it does not exist, 403 when it does but is not theirs. The two are
    distinguishable on purpose: these ids appear in the user's own URLs, so
    collapsing them into a single 404 buys no real secrecy and makes genuine
    "wrong account" mistakes undiagnosable.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calculation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Calculation not found")
    if not is_owner_or_admin(calculation, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Not authorized to access this calculation")
    return calculation


# The plan panel and its decisions are opened by the owner, by a DFO who administers the owner's organisation, and by a
# super admin. This is NOT `deps.require_dfo_or_above`, which accepts any DFO for any forest.
def can_review(db: Session, calculation: Calculation, user: User) -> bool:
    """Whether `user` may open the forest summary panel (read, answer decisions, export) for `calculation`.

    Owner or super admin always. A DFO (``ORG_ADMIN``) only when the owner belongs to the *same, non-null* organisation.
    Higher administrative levels (directorate, province, federal) are deliberately not here yet: add them in this one
    function (plan §5.4).
    """
    if is_owner_or_admin(calculation, user):
        return True
    if user.role != UserRole.ORG_ADMIN or user.organization_id is None:
        return False
    owner_org = (
        db.query(User.organization_id).filter(User.id == calculation.user_id).scalar()
    )
    return owner_org is not None and owner_org == user.organization_id


def require_panel_access(db: Session, calculation_id: str, user: User) -> Calculation:
    """Load a calculation for the forest summary panel, or refuse (404 missing, 403 not allowed)."""
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calculation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calculation not found")
    if not can_review(db, calculation, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this calculation")
    return calculation


# `structure_locked` is already true during the DFO's review (it is set at submit), so it can never be the lock for a
# decision. The decisions close when the DFO has approved the map, and while the analysis is running.
DECISIONS_CLOSED_STATUSES = ("locked", "calculating")


def decisions_closed(calculation: Calculation) -> bool:
    return calculation.map_lifecycle_status in DECISIONS_CLOSED_STATUSES
