"""Submit, DFO approve/reject, unlock, progress — the routes nothing served.

These six endpoints were defined in `app/api/calculations.py`, which `main.py`
never mounts and which cannot even be imported (it wants `i18n_error` from a
module that does not define it, and `app.api.forests_helpers`, which does not
exist). The live UI called all six and got **404** — including the DFO approve
and reject buttons, the approval step of a statutory workflow.

**Why a new module rather than reviving that one.** `calculations.py` is 1,501
lines, and ten of its twenty routes are duplicates of routes `forests.py`
already serves at `/forests/...`. Mounting it whole would shadow them — a
product decision nobody has made, taken by accident. These six are the ones
that exist *only* there, they use none of the rotted helpers, and lifting them
out is purely additive: no route that works today changes.

**Three defects were fixed in the lift, not carried across.**

1. `dfo-approve` and `dfo-reject` gated on `role not in ("dfo", "super_admin")`.
   There is no `"dfo"` role — `UserRole` is guest/user/org_admin/super_admin,
   and **DFO is `ORG_ADMIN`**. That check denied every real DFO and admitted
   only super admins. They now use `require_dfo_or_above` from `deps.py`, which
   exists for exactly this and says so in its docstring.
2. The role checks were open-coded rather than going through H2.7's helper.
   Ownership now runs through `is_owner_or_admin`.
3. `progress/stream` is deliberately **not** lifted. It does
   `async with SessionLocal()` on a *synchronous* sessionmaker, so it raises
   `AttributeError` on first use — it has never worked. Its only caller,
   `CalculationProgress.tsx`, is rendered by nothing, and `EventSource` cannot
   send an `Authorization` header, so it could not authenticate as written
   either. Reviving SSE is its own task; see `CURRENT_PLAN.md`.

The state transitions are unchanged and match `ALLOWED_TRANSITIONS` in
`deps.py`: submit is draft/failed → submitted, approve is completed → locked,
reject and unlock are completed/locked → draft.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import (
    log_state_transition,
    require_dfo_or_above,
    validate_transition,
)
from app.core.database import get_db
from app.core.errors import CalculationErrors
from app.models.calculation import Calculation, MapLifecycleStatus
from app.models.calculation_progress import CalculationProgress
from app.models.user import User
from app.schemas.calculations.dfo_review import DfoApproveRequest, DfoRejectRequest
from app.schemas.calculations.progress import (
    CalculationProgressResponse,
    CostEstimateResponse,
    ProgressWithCostResponse,
)
from app.services.calculation_cost_service import get_cost_estimate
from app.utils.auth import get_current_active_user
from app.utils.authz import is_owner_or_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Calculation Lifecycle"])


def _owned_calculation(db: Session, calculation_id: UUID, user: User) -> Calculation:
    """Load a calculation the caller owns, or refuse.

    404 and 403 stay distinguishable, matching `require_calculation_access`:
    these ids appear in the user's own URLs, so collapsing them buys no secrecy
    and makes a genuine wrong-account mistake undiagnosable.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calculation is None:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    if not is_owner_or_admin(calculation, user):
        raise HTTPException(status_code=403, detail="Ownership required")
    return calculation


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/calculations/{calculation_id}/workflow-readiness")
def get_workflow_readiness(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Per-step completion for the guided workflow (WORKSPACE_FLOW_NAV_PLAN P3).

    One call for the whole readiness strip: how far the work is, why a step is
    not done, and the current geometry clock.

    Reports only. Nothing here refuses access or blocks a step — a step that is
    not done is still reachable, which is the owner's governing rule that the
    system sequences and never enforces.

    `geometry_version` is returned rather than a server-side staleness verdict
    because no column records the clock's value at the moment a step was
    completed. The client compares it against what it last saw and labels the
    difference as "changed since you completed this", which is true; a
    server-side "designed at version N" would need a migration and would be
    permanently unknown for every existing row.
    """
    from app.services.operational_plan.workflow_readiness import workflow_readiness

    calculation = _owned_calculation(db, calculation_id, current_user)
    return workflow_readiness(db, calculation.id)


@router.get("/calculations/{calculation_id}/unified-shell-status")
def get_unified_shell_status(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Whether the unified shell is enabled for this calculation.

    Precedence, highest first: the user's opt-out, the calculation's own
    override, the global tenant flag, then off. `App.tsx` calls this on every
    load and falls back to disabled if it fails, which is why a 404 here went
    unnoticed for so long.
    """
    from app.models.tenant_flag import TenantFlag

    calculation = _owned_calculation(db, calculation_id, current_user)

    if getattr(current_user, "unified_shell_opt_out", False):
        return {"enabled": False}

    if calculation.unified_shell_enabled is not None:
        return {"enabled": calculation.unified_shell_enabled}

    try:
        flag = (
            db.query(TenantFlag)
            .filter(
                TenantFlag.key == "unified_shell_default",
                TenantFlag.tenant_id.is_(None),  # the global default row
            )
            .first()
        )
        if flag:
            return {"enabled": bool(flag.value)}
    except Exception:
        logger.exception(
            "tenant flag lookup failed - falling through to the built-in "
            "default, ignoring whatever the tenant configured"
        )

    return {"enabled": False}


def _require_super_admin(user: User) -> None:
    """The archive is a super-admin surface.

    It contains every field of every deleted calculation, including household
    records with caste classification and precise coordinates (S1-53). An
    ordinary owner has no business reading somebody else's deleted forest, and
    the ordinary owner is exactly who most often wants to.
    """
    from app.models.user import UserRole

    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SUPER_ADMIN_ONLY",
                "message": "The deleted-calculation archive is restricted to super admins.",
            },
        )


async def _start_analysis(db: Session, calculation: Calculation, user: User) -> bool:
    """Actually begin the analysis. Returns True when the worker took it.

    **Submitting used to start nothing.** This endpoint's docstring said it
    handed the map "to the calculation queue"; it set `map_lifecycle_status` and
    returned. `run_calculation_task` -- the pipeline carrying progress
    reporting, cost tracking, saga compensation, the state machine and H3.5's
    fail-fast gate -- is registered in `calculation_worker.py` and was
    **enqueued by nothing anywhere in the backend**. Users reached analysis
    through the legacy page's "Re-run Analysis" button instead, which runs a
    different and older path (`analyze_forest_boundary`) synchronously inside
    the HTTP request and bypasses the fail-fast gate entirely.

    The enqueue-then-fall-back shape is copied deliberately from
    `workspace.py`'s digitize finalize: it is the pattern this codebase already
    uses for exactly this situation, and a worker that is merely *not running*
    must never leave a user with a frozen map and nothing happening.

    On the fallback path the map stays `submitted` and the caller is told the
    work was not queued, rather than being told it succeeded.
    """
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
        from app.core.redis_config import redis_dsn

        pool = await create_pool(RedisSettings.from_dsn(redis_dsn()))
        job = await pool.enqueue_job(
            "run_calculation_task",
            str(calculation.id),
            _queue_name="arq:calculation",
        )
        await pool.close()
        logger.info(
            "submit: analysis queued for %s (job %s)",
            calculation.id,
            job,
        )
        return True
    except (
        Exception
    ) as exc:  # noqa: BLE001 -- worker or Redis down; reported, not swallowed
        # Deliberately NOT a 500. The submission itself succeeded and the map is
        # frozen; what failed is the hand-off. Telling the caller
        # `analysis_queued: false` lets the UI say "submitted, analysis will
        # start when the worker is available" instead of claiming a run began.
        logger.error(
            "submit: could not queue analysis for %s (%s). The map is submitted "
            "and frozen; analysis has NOT started.",
            calculation.id,
            exc,
            exc_info=True,
        )
        return False


@router.post("/calculations/{calculation_id}/submit-for-calculation")
async def submit_for_calculation(
    calculation_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Hand a draft map to the calculation queue. draft/failed -> submitted.

    Submitting FREEZES the map (H-SUBMIT A1). Until this, `structure_locked`
    was set in exactly one place -- `dfo_approve`, at `completed -> locked` --
    so the whole span from submission through the analysis run and the DFO
    review left the geometry editable. Analysis reads geometry at run time, so
    a block edited mid-run produced areas, volumes, biomass and carbon
    describing a shape that no longer existed, with nothing marking the result
    stale and nothing telling the reviewer the map had moved under them. In an
    output with statutory standing (S1-54) that is a wrong number nobody is
    told about.

    The lock is not permanent: `withdraw_submission` below returns the map to
    the owner while analysis has not yet started, and the DFO paths reopen it
    afterwards.
    """
    calculation = _owned_calculation(db, calculation_id, current_user)

    validate_transition(calculation.map_lifecycle_status, "submitted")
    from_state = calculation.map_lifecycle_status
    calculation.map_lifecycle_status = MapLifecycleStatus.SUBMITTED.value
    calculation.submitted_at = datetime.now(timezone.utc)
    calculation.submitted_by = current_user.id
    calculation.structure_locked = True
    calculation.structure_locked_at = datetime.now(timezone.utc)
    log_state_transition(
        db,
        calculation_id,
        from_state,
        "submitted",
        triggered_by=current_user.id,
        ip_address=_client_ip(request),
    )
    db.commit()

    queued = await _start_analysis(db, calculation, current_user)
    return {
        "id": str(calculation.id),
        "map_lifecycle_status": calculation.map_lifecycle_status,
        "structure_locked": True,
        "analysis_queued": queued,
    }


@router.post("/calculations/{calculation_id}/withdraw-submission")
def withdraw_submission(
    calculation_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Take a submitted map back, before analysis starts. submitted -> draft.

    Why the owner may do this without an administrator (H-SUBMIT D3). The
    guarantee submission buys is that the analysis output describes the geometry
    that was analysed, and that only needs to hold once the pipeline has
    *consumed* the map. Before then there is nothing to protect, and requiring
    a support request to fix a typo thirty seconds after submitting would teach
    people to avoid submitting at all -- which costs more than it saves.

    The window is deliberately narrow: **exactly `submitted`**. Once the state
    is `calculating` this refuses with 409 and the DFO paths take over, because
    from that point a withdrawal would race a running analysis.
    """
    calculation = _owned_calculation(db, calculation_id, current_user)

    # Not `validate_transition`: `submitted -> draft` is legal (deps.py), but
    # so is `failed -> submitted`, and this endpoint must not become a general
    # unwind. The state is checked exactly, and the 409 says which state it
    # found -- a caller that arrives one second too late deserves to be told
    # that analysis has begun, not "invalid transition".
    if calculation.map_lifecycle_status != MapLifecycleStatus.SUBMITTED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "NOT_WITHDRAWABLE",
                "message": (
                    "This map can only be withdrawn while it is waiting for "
                    "analysis to start. Ask a DFO to send it back."
                ),
                "message_np": (
                    "यो नक्सा विश्लेषण सुरु नहुँदासम्म मात्र फिर्ता लिन सकिन्छ। "
                    "फिर्ता पठाउन DFO लाई अनुरोध गर्नुहोस्।"
                ),
                "current_state": calculation.map_lifecycle_status,
            },
        )

    from_state = calculation.map_lifecycle_status
    calculation.map_lifecycle_status = MapLifecycleStatus.DRAFT.value
    calculation.structure_locked = False
    calculation.submitted_at = None
    calculation.submitted_by = None
    log_state_transition(
        db,
        calculation_id,
        from_state,
        "draft",
        triggered_by=current_user.id,
        reason="withdrawn_by_owner",
        ip_address=_client_ip(request),
    )
    db.commit()
    return {
        "id": str(calculation.id),
        "map_lifecycle_status": "draft",
        "structure_locked": False,
    }


@router.post("/calculations/{calculation_id}/dfo-approve")
def dfo_approve(
    body: DfoApproveRequest,
    request: Request,
    calculation: Calculation = Depends(require_dfo_or_above),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Approve a completed map and lock its structure. completed -> locked.

    `require_dfo_or_above` supplies the calculation and the 403; DFO is the
    `ORG_ADMIN` role, which the original literal check got wrong.
    """
    validate_transition(calculation.map_lifecycle_status, "locked")
    from_state = calculation.map_lifecycle_status
    calculation.map_lifecycle_status = MapLifecycleStatus.LOCKED.value
    calculation.structure_locked = True
    calculation.locked_at = datetime.now(timezone.utc)
    calculation.locked_by = current_user.id
    calculation.dfo_decision_at = datetime.now(timezone.utc)
    calculation.dfo_decision_by = current_user.id
    calculation.dfo_decision_notes = body.notes
    log_state_transition(
        db,
        calculation.id,
        from_state,
        "locked",
        triggered_by=current_user.id,
        reason=body.notes or "dfo_approved",
        ip_address=_client_ip(request),
    )
    db.commit()
    return {
        "id": str(calculation.id),
        "map_lifecycle_status": "locked",
        "structure_locked": True,
    }


@router.post("/calculations/{calculation_id}/dfo-reject")
def dfo_reject(
    body: DfoRejectRequest,
    request: Request,
    calculation: Calculation = Depends(require_dfo_or_above),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Send a map back for rework. completed/locked -> draft."""
    validate_transition(calculation.map_lifecycle_status, "draft")
    from_state = calculation.map_lifecycle_status
    calculation.map_lifecycle_status = MapLifecycleStatus.DRAFT.value
    # Rework means editable. Without this the map returns to `draft` still
    # carrying `structure_locked` from the approval it is being sent back from,
    # and `locked -> draft` IS a legal transition, so this is reachable: the
    # owner is told to fix the map and then refused every edit with a 423. The
    # Unlock button does not appear either, because `WorkspaceHeader` renders it
    # only while the status is `locked` -- which it no longer is. The map ends up
    # editable by nobody short of a super admin who knows to look.
    #
    # `super_admin_unlock` has always cleared it on the same transition; the two
    # paths back to `draft` simply did not agree.
    calculation.structure_locked = False
    calculation.dfo_decision_at = datetime.now(timezone.utc)
    calculation.dfo_decision_by = current_user.id
    calculation.dfo_decision_notes = body.reason
    log_state_transition(
        db,
        calculation.id,
        from_state,
        "draft",
        triggered_by=current_user.id,
        reason=body.reason or "dfo_rejected",
        ip_address=_client_ip(request),
    )
    db.commit()
    return {
        "id": str(calculation.id),
        "map_lifecycle_status": "draft",
        "structure_locked": False,
    }


@router.post("/calculations/{calculation_id}/super-admin-unlock")
def super_admin_unlock(
    calculation_id: UUID,
    request: Request,
    reason: str = Form(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Break a structure lock. completed/locked -> draft. Super admin only.

    Deliberately stricter than `require_dfo_or_above`: a DFO approves, only a
    super admin undoes an approval. `reason` is form-encoded because that is
    what `WorkspaceHeader.tsx` sends.
    """
    from app.models.user import UserRole

    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Only a super admin can unlock a map",
        )
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calculation is None:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    validate_transition(calculation.map_lifecycle_status, "draft")
    from_state = calculation.map_lifecycle_status
    calculation.map_lifecycle_status = MapLifecycleStatus.DRAFT.value
    calculation.structure_locked = False
    calculation.map_lifecycle_retries = 0
    calculation.locked_at = datetime.now(timezone.utc)
    calculation.locked_by = current_user.id
    calculation.locked_reason = reason
    log_state_transition(
        db,
        calculation_id,
        from_state,
        "draft",
        triggered_by=current_user.id,
        reason=reason,
        ip_address=_client_ip(request),
    )
    db.commit()
    return {
        "id": str(calculation.id),
        "map_lifecycle_status": "draft",
        "structure_locked": False,
    }


@router.get(
    "/calculations/{calculation_id}/progress",
    response_model=ProgressWithCostResponse,
)
def get_calculation_progress(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Progress and cost estimate for a running calculation."""
    calculation = _owned_calculation(db, calculation_id, current_user)

    progress = (
        db.query(CalculationProgress)
        .filter(CalculationProgress.calculation_id == calculation_id)
        .first()
    )

    cost = get_cost_estimate(calculation)
    return ProgressWithCostResponse(
        progress=(
            CalculationProgressResponse.model_validate(progress) if progress else None
        ),
        cost_estimate=CostEstimateResponse(**cost) if cost else None,
        map_lifecycle_status=calculation.map_lifecycle_status,
    )
