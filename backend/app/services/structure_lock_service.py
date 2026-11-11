"""
Structure lifecycle state machine (S14).

Applies structure_locked transitions with role validation, state checking,
and audit trail creation. Supports AUTO_LOCK (OP submission), MANUAL_LOCK
(DFO), and DFO_UNLOCK transitions.
"""
from __future__ import annotations
import enum
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models.user import User, UserRole

logger = logging.getLogger(__name__)


class LockTransition(str, enum.Enum):
    AUTO_LOCK = "auto_lock"
    MANUAL_LOCK = "manual_lock"
    DFO_UNLOCK = "dfo_unlock"


VALID_TRANSITIONS: dict[LockTransition, dict] = {
    LockTransition.AUTO_LOCK: {
        "from_state": False,
        "to_state": True,
        "allowed_roles": [UserRole.USER.value, UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value],
        "reason_required": False,
        "description": "Auto-lock on OP submission",
    },
    LockTransition.MANUAL_LOCK: {
        "from_state": False,
        "to_state": True,
        "allowed_roles": [UserRole.SUPER_ADMIN.value],
        "reason_required": True,
        "description": "DFO manually locks structure",
    },
    LockTransition.DFO_UNLOCK: {
        "from_state": True,
        "to_state": False,
        "allowed_roles": [UserRole.SUPER_ADMIN.value],
        "reason_required": True,
        "description": "DFO unlocks structure",
    },
}


def apply_structure_lock_transition(
    calculation,
    transition: LockTransition,
    db: Session,
    current_user: User,
    reason_np: Optional[str] = None,
) -> dict:
    """
    Validate and apply a structure lock state transition.

    Parameters
    ----------
    calculation : Calculation
        The calculation/forest to transition.
    transition : LockTransition
        Which transition to apply.
    db : Session
        Database session.
    current_user : User
        The user performing the action.
    reason_np : str, optional
        Nepali reason (required for MANUAL_LOCK and DFO_UNLOCK).

    Returns
    -------
    dict with keys: from_state, to_state, transition, audit_id
    """
    config = VALID_TRANSITIONS.get(transition)
    if not config:
        raise HTTPException(400, detail=f"Invalid transition: {transition}")

    from_state = config["from_state"]
    to_state = config["to_state"]

    if calculation.structure_locked != from_state:
        raise HTTPException(
            409,
            detail=f"Cannot apply {transition.value}: expected from_state={from_state}, "
                    f"current state={calculation.structure_locked}",
        )

    if current_user.role not in config["allowed_roles"]:
        raise HTTPException(403, detail="Only DFO can perform this action")

    if config["reason_required"] and (not reason_np or len(reason_np.strip()) < 10):
        raise HTTPException(400, detail="Written reason required (minimum 10 characters)")

    # Apply transition
    calculation.structure_locked = to_state
    calculation.structure_locked_at = datetime.now(timezone.utc)
    calculation.structure_locked_by = current_user.id

    # Create audit record
    from ..models.structure_lock_audit import StructureLockAudit

    audit = StructureLockAudit(
        calculation_id=calculation.id,
        transition=transition.value,
        from_state=from_state,
        to_state=to_state,
        triggered_by_user_id=current_user.id,
        reason_np=reason_np,
    )
    db.add(audit)
    db.flush()

    logger.info(
        "Structure lock transition: calculation=%s transition=%s from=%s to=%s user=%s",
        calculation.id,
        transition.value,
        from_state,
        to_state,
        current_user.id,
    )

    return {
        "from_state": from_state,
        "to_state": to_state,
        "transition": transition.value,
        "audit_id": audit.id,
    }


def check_structure_locked(calculation, detail: str = "Structure is locked"):
    """Raise HTTP 423 if structure is locked, with Nepali message."""
    if calculation.structure_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "code": "structure_locked",
                "message": detail,
                "message_np": "यो संरचना लक गरिएको छ — ब्लक र उप-क्षेत्र सम्पादन गर्न सकिँदैन।",
                "structure_locked_at": str(calculation.structure_locked_at) if calculation.structure_locked_at else None,
            },
        )
