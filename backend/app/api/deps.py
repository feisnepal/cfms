"""
Shared API dependencies — reusable FastAPI dependencies.
"""
import logging
from functools import wraps
from typing import Callable, Any

from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.models.calculation import Calculation, MapLifecycleStatus
from app.models.user import User, UserRole
from app.core.errors import CalculationErrors
from app.utils.auth import get_current_user, get_current_active_user

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted"},
    # `draft` added for H-SUBMIT A2: submitting now freezes the map, so the
    # owner needs a way back while analysis has NOT yet started. The withdraw
    # endpoint checks the state is exactly `submitted` before using it, so this
    # entry does not by itself let anything unwind mid-analysis.
    #
    # It also makes `dfo_reject` legal from `submitted`, which it was not
    # before. That is a widening, and a defensible one: a reviewer who can see
    # a submitted map should be able to send it back without waiting for
    # analysis to finish first.
    "submitted": {"calculating", "failed", "draft"},
    "calculating": {"completed", "retrying", "failed"},
    "retrying": {"calculating", "failed"},
    "failed": {"submitted"},
    "completed": {"locked", "draft"},
    "locked": {"draft"},
}


def validate_transition(from_state: str, to_state: str) -> None:
    """Raise HTTP 409 if the transition is not allowed."""
    allowed = ALLOWED_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVALID_MAP_STATE",
                "message": f"Cannot transition from '{from_state}' to '{to_state}'",
                "current_state": from_state,
                "requested_state": to_state,
                "allowed_transitions": sorted(allowed),
            },
        )


def require_map_state(*allowed_states: str) -> Callable:
    """Decorator that checks calculation's map_lifecycle_status is in allowed_states.

    Usage:
        @router.post("/{id}/submit")
        @require_map_state('draft', 'failed')
        async def submit(calc: Calculation = Depends(get_calculation_or_404)):
            ...
    """
    allowed_set = set(allowed_states)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            calc = kwargs.get("calc") or kwargs.get("calculation")
            if calc is None:
                for v in kwargs.values():
                    if isinstance(v, Calculation):
                        calc = v
                        break
            if calc is None:
                raise HTTPException(status_code=500, detail="Calculation not found in kwargs")
            if calc.map_lifecycle_status not in allowed_set:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "INVALID_MAP_STATE",
                        "message": f"Expected state {sorted(allowed_set)}, got '{calc.map_lifecycle_status}'",
                        "current_state": calc.map_lifecycle_status,
                    },
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def log_state_transition(
    db: Session,
    calculation_id: UUID,
    from_state: str,
    to_state: str,
    triggered_by: UUID | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Append an immutable audit log entry for a state transition."""
    from app.models.calculation_audit_log import CalculationAuditLog
    entry = CalculationAuditLog(
        calculation_id=calculation_id,
        from_state=from_state,
        to_state=to_state,
        triggered_by=triggered_by,
        reason=reason,
        ip_address=ip_address,
        correlation_id=correlation_id,
    )
    db.add(entry)
    db.flush()


def get_calculation_or_404(
    calculation_id: UUID,
    db: Session = Depends(get_db),
) -> Calculation:
    """Fetch a Calculation by ID or raise 404. Use as a FastAPI dependency.

    Usage:
        @router.get("/{calculation_id}/something")
        async def something(calc: Calculation = Depends(get_calculation_or_404)):
            ...
    """
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND,
        )
    return calc


def require_unlocked_structure(
    calc: Calculation = Depends(get_calculation_or_404),
) -> Calculation:
    """Raise HTTP 423 if the calculation's structure is locked.

    Use as a FastAPI dependency on endpoints that mutate blocks or sub-areas.

    Usage:
        @router.patch("/{calculation_id}/blocks/{block_id}")
        async def update_block(
            calc: Calculation = Depends(require_unlocked_structure),
            ...
        ):
    """
    if calc.structure_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "code": "structure_locked",
                "message": "Structure is locked — block and sub-area edits are disabled.",
                "message_np": "यो संरचना लक गरिएको छ — ब्लक र उप-क्षेत्र सम्पादन गर्न सकिँदैन।",
                "structure_locked_at": str(calc.structure_locked_at) if calc.structure_locked_at else None,
            },
        )
    return calc


def require_draw_role(
    calc: Calculation = Depends(get_calculation_or_404),
    current_user: User = Depends(get_current_active_user),
) -> Calculation:
    """Raise HTTP 403 if the user lacks geometry-write permission for this calculation.

    Allowed roles: Editor (user), Org Admin, Super Admin.
    DFO (org_admin) is also allowed since they can unlock.
    Reviewer (guest) and Guest are NOT allowed.

    This enforces backend parity with frontend `toolEnabled()` gates (U07).
    """
    allowed_roles = {UserRole.USER, UserRole.ORG_ADMIN, UserRole.SUPER_ADMIN}
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "insufficient_role",
                "message": "Geometry editing requires Editor, Org Admin, or Super Admin role.",
                "message_np": "ज्यामिती सम्पादनका लागि Editor, Org Admin, वा Super Admin भूमिका आवश्यक छ।",
                "user_role": current_user.role.value,
                "allowed_roles": [r.value for r in allowed_roles],
            },
        )
    # Also ensure structure is not locked
    if calc.structure_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "code": "structure_locked",
                "message": "Structure is locked — geometry edits are disabled.",
                "message_np": "यो संरचना लक गरिएको छ — ज्यामिती सम्पादन गर्न सकिँदैन।",
                "structure_locked_at": str(calc.structure_locked_at) if calc.structure_locked_at else None,
            },
        )
    return calc


def require_dfo_or_above(
    calc: Calculation = Depends(get_calculation_or_404),
    current_user: User = Depends(get_current_active_user),
) -> Calculation:
    """Raise HTTP 403 if the user is not DFO (Org Admin) or Super Admin.

    Used for approve/unlock endpoints.
    """
    if current_user.role not in {UserRole.ORG_ADMIN, UserRole.SUPER_ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "insufficient_role",
                "message": "This action requires DFO or Super Admin role.",
                "message_np": "यस कार्यका लागि DFO वा Super Admin भूमिका आवश्यक छ।",
                "user_role": current_user.role.value,
            },
        )
    return calc


def require_export_not_running(
    calculation_id: UUID,
    db: Session = Depends(get_db),
) -> Calculation:
    """Raise HTTP 409 if the calculation's export_status is 'running'.

    Use as a FastAPI dependency on geometry-write endpoints to block writes
    during OP export. Lease expires after EXPORT_LEASE_TTL_SECONDS (5 min).

    Usage:
        @router.patch("/{calculation_id}/blocks/{block_id}")
        async def update_block(
            calc: Calculation = Depends(require_export_not_running),
            ...
        ):
    """
    from app.api.operational_plans import EXPORT_LEASE_TTL_SECONDS
    from datetime import datetime, timezone

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")

    if calc.export_status == "running":
        # Check if lease has expired
        if calc.export_heartbeat_at:
            now = datetime.now(timezone.utc)
            if (now - calc.export_heartbeat_at).total_seconds() > EXPORT_LEASE_TTL_SECONDS:
                return calc  # lease expired, allow
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXPORT_RUNNING",
                "message": "Export is running. Geometry writes are blocked until export completes.",
                "retry_after_seconds": EXPORT_LEASE_TTL_SECONDS,
            },
        )
    return calc
