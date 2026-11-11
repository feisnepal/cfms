"""
Operational Plan API endpoints — Tree Document Model
"""

# business: document tree is the canonical OP representation — all CRUD, export, and preview operate on it
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from typing import Dict, Any, Optional, List
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import logging
import re
import time
import json
from app.core.errors import CalculationErrors

from app.core.dropped import report_dropped

logger = logging.getLogger(__name__)

from ..core.database import get_db
from ..core.exceptions import i18n_success
from ..services.calculation_notification_service import send_docx_email
from ..models.user import User, UserRole
from ..models.calculation import Calculation
from ..models.operational_plan import OperationalPlan
from ..models.op_template import OPTemplate, OPTemplateVersion, OPTemplateCategory, OPTemplateReport
from ..services.operational_plan import template_access, plan_live
from ..models.forest_block import ForestBlock
from ..models.op_table import OPTableData
from ..schemas.operational_plan import (
    OperationalPlanCreate,
    OperationalPlanUpdate,
    OperationalPlanSectionUpdate,
    OperationalPlanResponse,
    TreeNodeCreate,
    TreeNodeUpdate,
    TreeNodeReorder,
    TreeNodeSchema,
    VariableDefResponse,
    TemplateCreate,
    TemplateUpdate,
    TemplatePublish,
    TemplateClone,
    TemplateApprove,
    TemplateLifecycleRequest,
    TemplateResponse,
    TemplateSummary,
    TemplateVersionResponse,
    TemplateRollbackRequest,
    TemplateValidateResponse,
    TemplateAuditEntry,
    SystemTemplateResponse,
    AdoptFromPlanResponse,
    PlanKindResponse,
    PlanKindUpdate,
    PlanTemplateStatusResponse,
    TemplateUpgradeRequest,
    TemplateUpgradeDiff,
    TemplateUpgradeResponse,
    SuggestKindResponse,
    UpdateDefaultTemplateRequest,
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
)
from ..schemas.metadata_form import MetadataFormUpdate
from ..services.metadata.admin_location_service import (
    get_provinces,
    get_districts,
    get_divisions,
    get_sub_divisions,
    get_municipalities,
    get_municipalities_by_district,
    get_wards,
    get_wards_by_district_municipality,
    get_physiography_and_jurisdiction,
    get_physiography_by_district_municipality,
    get_location_by_centroid,
    resolve_from_resolved_vars,
)
from ..services.operational_plan.template_utils import generate_template_summaries
from ..services.operational_plan import template_lifecycle
from ..services.operational_plan import template_parent_update
from ..services.operational_plan.template_lifecycle import TransitionError
from ..services.operational_plan.template_validation import validate_template
from ..services.operational_plan.plan_kinds import (
    list_plan_kinds,
    get_plan_kind,
    effective_required_sections,
    resolve_kind_key,
)
from ..services.operational_plan.cover import ensure_cover_node
from ..models.op_template import OPPlanKind, OPTemplateAudit
from ..utils.auth import require_template_designer, require_template_publisher
from ..utils.auth import get_current_active_user
from ..services.operational_plan.tree_models import (
    TreeNode,
    TreeOperations,
    DocumentTree,
)
from ..services.operational_plan.auto_numbering import recompute_numbers
from ..services.operational_plan.seed_data import get_full_seed_document
from ..services.operational_plan.variable_registry import (
    VARIABLE_REGISTRY,
    get_variable,
    get_variables_by_category,
    search_variables,
    get_all_variables,
    VariableDef,
)
from ..services.operational_plan.variable_resolver import VariableResolver
from ..services.operational_plan.plan_readiness import plan_readiness
from ..services.document_integrity import list_submissions, record_submission
from ..services.operational_plan.variable_enrichment import (
    get_enriched_variables,
    build_csv_string,
)
from ..services.document_integrity import (
    mint_verification_code,
    record_issuance,
    sha256_of,
)
from ..services.operational_plan.op_docx_builder import build_op_document
from ..utils.file_export import build_disposition
from ..utils.number_format import format_devanagari
from nepali_datetime import date as nepali_date

router = APIRouter(tags=["operational-plans"])

# U12: Export lease TTL (seconds) — heartbeat must arrive within this window
EXPORT_LEASE_TTL_SECONDS = 300  # 5 minutes


# business: tree ↔ dict conversion bridges the DB JSONB column and in-memory TreeNode objects
def _tree_to_dict_list(tree: list) -> list:
    return [n.model_dump() for n in tree]


def _dict_list_to_tree(data: list) -> list:
    return [TreeNode.from_dict(n) if isinstance(n, dict) else n for n in data]


def plan_to_dict(plan: OperationalPlan) -> Dict[str, Any]:
    """Convert OperationalPlan ORM instance to a serializable dictionary."""
    tree_data = plan.sections.get("tree", []) if plan.sections else []
    return {
        "id": str(plan.id),
        "calculation_id": str(plan.calculation_id),
        "forest_name": plan.forest_name,
        "sections": plan.sections or {},
        "tree": tree_data,
        "plan_metadata": plan.plan_metadata or {},
        "status": plan.status,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        "submitted_at": plan.submitted_at.isoformat() if plan.submitted_at else None,
        "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
    }


# constraint: only calculation owner or SUPER_ADMIN may access/create/modify OP
def _check_calc_access(
    calculation_id: UUID, current_user: User, db: Session
) -> Calculation:
    calculation = db.execute(
        select(Calculation).where(Calculation.id == calculation_id)
    ).scalar_one_or_none()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    if (
        calculation.user_id != current_user.id
        and current_user.role != UserRole.SUPER_ADMIN
    ):
        raise HTTPException(status_code=403, detail="Access denied")
    return calculation


def _check_plan_access(
    plan_id: UUID, current_user: User, db: Session
) -> OperationalPlan:
    plan = db.execute(
        select(OperationalPlan).where(OperationalPlan.id == plan_id)
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Operational plan not found")
    _check_calc_access(plan.calculation_id, current_user, db)
    return plan


# U12: Export lock helpers
async def _acquire_export_lock(calculation_id: UUID, db: Session) -> Calculation:
    """Acquire export lock by setting export_status to 'running' if idle.
    Returns the calculation if lock acquired, raises 409 if already running.
    """
    calculation = db.execute(
        select(Calculation).where(Calculation.id == calculation_id)
    ).scalar_one_or_none()
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")

    if calculation.export_status == "running":
        # Check if lease has expired (stale heartbeat)
        if calculation.export_heartbeat_at:
            now = datetime.now(timezone.utc)
            if (
                now - calculation.export_heartbeat_at
            ).total_seconds() > EXPORT_LEASE_TTL_SECONDS:
                # Lease expired, we can take over
                pass
            else:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "EXPORT_RUNNING",
                        "message": "Export is already running. Geometry writes are blocked.",
                        "export_started_at": (
                            calculation.export_started_at.isoformat()
                            if calculation.export_started_at
                            else None
                        ),
                        "export_heartbeat_at": (
                            calculation.export_heartbeat_at.isoformat()
                            if calculation.export_heartbeat_at
                            else None
                        ),
                    },
                )
        else:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "EXPORT_RUNNING",
                    "message": "Export is already running. Geometry writes are blocked.",
                    "export_started_at": (
                        calculation.export_started_at.isoformat()
                        if calculation.export_started_at
                        else None
                    ),
                },
            )

    # Acquire lock
    calculation.export_status = "running"
    calculation.export_started_at = datetime.now(timezone.utc)
    calculation.export_heartbeat_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(calculation)
    return calculation


async def _release_export_lock(
    calculation_id: UUID, db: Session, status: str = "complete"
) -> None:
    """Release export lock by setting export_status to 'complete' or 'failed'.
    Clears heartbeat and started_at.

    Robust to a poisoned session: if the export body raised a DB error, the
    session transaction is already aborted (InFailedSqlTransaction), so a
    rollback is required before the release can commit. Without this the lock
    would be left 'running' and every subsequent export/geometry-write would
    hit "Export is already running".
    """
    try:
        calculation = db.execute(
            select(Calculation).where(Calculation.id == calculation_id)
        ).scalar_one_or_none()
        if calculation:
            calculation.export_status = status  # "complete" or "failed"
            calculation.export_heartbeat_at = None
            calculation.export_started_at = None
            db.commit()
    except Exception:
        logger.warning(
            "export lock release for calc=%s failed on the first attempt "
            "(likely a poisoned session) - retrying after rollback",
            calculation_id, exc_info=True,
        )
        db.rollback()
        try:
            calculation = db.execute(
                select(Calculation).where(Calculation.id == calculation_id)
            ).scalar_one_or_none()
            if calculation:
                calculation.export_status = status
                calculation.export_heartbeat_at = None
                calculation.export_started_at = None
                db.commit()
        except Exception:
            logger.error(
                "export lock release for calc=%s failed on retry too - the "
                "lock is stuck 'running'; every subsequent export/geometry-"
                "write on this calculation will report 'Export is already "
                "running' until it is cleared manually",
                calculation_id, exc_info=True,
            )
            db.rollback()


async def _heartbeat_export_lock(calculation_id: UUID, db: Session) -> None:
    """Update export heartbeat timestamp to keep lease alive."""
    calculation = db.execute(
        select(Calculation).where(Calculation.id == calculation_id)
    ).scalar_one_or_none()
    if calculation and calculation.export_status == "running":
        calculation.export_heartbeat_at = datetime.now(timezone.utc)
        db.commit()


def require_export_not_running(
    calculation_id: UUID = Depends(
        lambda: None
    ),  # will be overridden by path parameter
    db: Session = Depends(get_db),
) -> Calculation:
    """Dependency that raises 409 if calculation's export_status is 'running'.
    Used on geometry-write endpoints to block writes during export.
    """
    calculation = db.execute(
        select(Calculation).where(Calculation.id == calculation_id)
    ).scalar_one_or_none()
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")

    if calculation.export_status == "running":
        # Check if lease has expired
        if calculation.export_heartbeat_at:
            now = datetime.now(timezone.utc)
            if (
                now - calculation.export_heartbeat_at
            ).total_seconds() > EXPORT_LEASE_TTL_SECONDS:
                return calculation  # lease expired, allow
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXPORT_RUNNING",
                "message": "Export is running. Geometry writes are blocked until export completes.",
                "retry_after_seconds": EXPORT_LEASE_TTL_SECONDS,
            },
        )
    return calculation


# NOTE: flag_modified(plan, "sections") required for JSONB mutation detection
def _save_tree(plan: OperationalPlan, tree: list, db: Session) -> None:
    sections = plan.sections or {}
    sections["tree"] = _tree_to_dict_list(tree)
    plan.sections = dict(sections)
    flag_modified(plan, "sections")
    plan.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(plan)


# business: CFMG — OP document must follow prescribed template structure.
# Resolution order (OP_MULTI_TEMPLATE_PLAN.md §3.5): explicit template_id ->
# the (regime, stage) kind's default_template_id -> the बृन्दावन base -> seed.
def _plan_exists_detail(db: Session, plan: OperationalPlan) -> Dict[str, Any]:
    """What the screen needs when a forest already has a plan: which plan, from which template, and whether it may be replaced."""
    blocked = _plan_replace_blocked(db, plan)
    tid = (plan.plan_metadata or {}).get("template_id")
    old_tmpl = db.get(OPTemplate, UUID(str(tid))) if tid else None
    return {
        "code": "PLAN_EXISTS",
        "message": "Operational plan already exists for this calculation",
        "plan_id": str(plan.id),
        "template_name": old_tmpl.name if old_tmpl else None,
        "updated_at": plan.updated_at.isoformat() if getattr(plan, "updated_at", None) else None,
        "can_replace": blocked is None,
        "blocked_reason": blocked,
    }


def _plan_replace_blocked(db: Session, plan: OperationalPlan) -> Optional[str]:
    """Why a plan cannot be replaced by starting again, or None when it can. A plan that was submitted to an office, or moved past
    draft, is a record and stays. Exports alone do not block it."""
    from sqlalchemy import text as _text

    if (plan.status or "draft") != "draft":
        return "The plan is no longer a draft, so it cannot be replaced."
    submitted = db.execute(
        _text("SELECT 1 FROM document_submissions WHERE plan_id = :p LIMIT 1"), {"p": plan.id}
    ).first()
    if submitted:
        return "The plan was submitted to an office, so it cannot be replaced."
    return None


@router.get("/calculation/{calculation_id}/replace-status")
def plan_replace_status(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Does this forest already have a plan? The store's Export uses it to export the existing document as it is
    instead of making a new one; the answer also says whether the plan could be replaced."""
    _check_calc_access(calculation_id, current_user, db)
    plan = db.execute(
        select(OperationalPlan).where(OperationalPlan.calculation_id == calculation_id)
    ).scalar_one_or_none()
    if plan is None:
        return {"exists": False}
    return {"exists": True, **_plan_exists_detail(db, plan)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_operational_plan(
    plan_data: OperationalPlanCreate,
    template_id: Optional[UUID] = Query(
        None, description="Explicit template to build from"
    ),
    plan_regime: Optional[str] = Query(
        None, description="sustainable_fmp | brief_fmp | scientific_fmp"
    ),
    plan_stage: Optional[str] = Query(None, description="new | revision"),
    authoring: bool = Query(
        False,
        description=(
            "Author-mode template test (template designer / super admin only): "
            "skip auto-population so every {{token}} stays verbatim. "
            "OP_TEMPLATE_MANAGEMENT_PLAN.md §3.2."
        ),
    ),
    replace: bool = Query(
        False,
        description="Start again: replace the forest's existing plan (refused once it was submitted). The old plan is kept if anything fails.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a new Operational Plan with auto-populated variables."""
    calculation = _check_calc_access(plan_data.calculation_id, current_user, db)

    is_authoring = authoring and current_user.role in (
        UserRole.TEMPLATE_DESIGNER,
        UserRole.SUPER_ADMIN,
    )

    existing_plan = db.execute(
        select(OperationalPlan).where(
            OperationalPlan.calculation_id == plan_data.calculation_id
        )
    ).scalar_one_or_none()
    if existing_plan:
        blocked = _plan_replace_blocked(db, existing_plan)
        if not replace or blocked:
            # The store's "Open in builder" passes replace=true (a click on a template is the user asking for that
            # template); Export never reaches here with a plan in the way. This answers the leftover races and older
            # callers. A plan submitted to an office is a record and stays, replaced or not.
            raise HTTPException(status_code=400, detail=_plan_exists_detail(db, existing_plan))
        # same transaction as the new plan below: if building the new one fails, nothing is committed and the old one stays
        db.delete(existing_plan)
        db.flush()

    from ..core.feature_flags import feature_flags

    # Phase 6: auto-resolve the stage from the forest's plan history when the
    # `op_auto_stage` flag is on and the caller left it blank.
    if feature_flags.is_enabled("op_auto_stage") and plan_regime and not plan_stage:
        plan_stage, _, _ = _suggest_stage(db, calculation, plan_regime)

    kind_key = resolve_kind_key(None, plan_regime, plan_stage)
    src_tmpl = None
    if template_id:
        src_tmpl = db.execute(
            select(OPTemplate).where(OPTemplate.id == template_id)
        ).scalar_one_or_none()
        if not src_tmpl:
            raise HTTPException(status_code=404, detail="Template not found")
        if not template_access.can_view(src_tmpl, current_user):
            raise HTTPException(status_code=403, detail="Access denied")
        if src_tmpl.item_type != "template":
            raise HTTPException(status_code=400, detail="That is a section from the library, not a template")
        # Phase 6: kind-match enforcement (feature-flagged, off by default).
        if (
            feature_flags.is_enabled("op_template_kind_match")
            and kind_key
            and src_tmpl.plan_kind
            and src_tmpl.plan_kind != kind_key
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "KIND_MISMATCH",
                    "message": (
                        f"Template is for '{src_tmpl.plan_kind}' but the plan is "
                        f"'{kind_key}'. Pick a template for this plan kind."
                    ),
                    "template_kind": src_tmpl.plan_kind,
                    "requested_kind": kind_key,
                },
            )
    elif kind_key:
        kind = get_plan_kind(db, kind_key)
        if kind and kind.default_template_id:
            src_tmpl = db.execute(
                select(OPTemplate).where(OPTemplate.id == kind.default_template_id)
            ).scalar_one_or_none()
    if src_tmpl is None:
        src_tmpl = (
            db.execute(
                select(OPTemplate)
                .where(OPTemplate.is_system == True)
                .order_by(OPTemplate.updated_at.desc())
            )
            .scalars()
            .first()
        )

    if src_tmpl is not None:
        tree_list = [TreeNode.from_dict(n) for n in src_tmpl.tree]
    else:
        tree_list = get_full_seed_document()

    recompute_numbers(tree_list, language="NP")

    sections = {"tree": _tree_to_dict_list(tree_list)}

    metadata = {"version": "2.0", "language": "NP", "auto_populated": False}
    if plan_data.custom_notes:
        metadata["custom_notes"] = plan_data.custom_notes
    # OP multi-template §3.5: pin which template/version/kind this plan was built
    # from (drives per-kind export naming + the upgrade path).
    if src_tmpl is not None:
        metadata["template_id"] = str(src_tmpl.id)
        metadata["template_version"] = src_tmpl.published_version or src_tmpl.version
        metadata["template_kind"] = src_tmpl.plan_kind or kind_key
        metadata["template_name"] = src_tmpl.name
    metadata["template_regime"] = plan_regime or (
        src_tmpl.plan_regime if src_tmpl else None
    )
    metadata["template_stage"] = plan_stage or (
        src_tmpl.plan_stage if src_tmpl else None
    )
    if is_authoring:
        # Author mode: a disposable template-test plan. Keep {{tokens}} verbatim
        # (no auto-populate below) and mark it so it is never mistaken for a
        # CFUG's real Operational Plan.
        metadata["authoring"] = True
        metadata["template_test"] = True

    plan = OperationalPlan(
        calculation_id=plan_data.calculation_id,
        forest_name=plan_data.forest_name or calculation.forest_name,
        created_by=current_user.id,
        sections=sections,
        plan_metadata=metadata,
    )

    db.add(plan)
    db.commit()
    db.refresh(plan)

    # Auto-populate variables so the plan is ready-to-print immediately.
    # Author-mode plans skip this: their whole point is to keep {{tokens}} visible.
    if is_authoring:
        return plan_to_dict(plan)
    try:
        resolver = VariableResolver(db, plan.calculation_id, plan)
        tree_list = _dict_list_to_tree(sections.get("tree", []))
        resolved = resolver.resolve_all()
        for node in TreeOperations.flatten(tree_list):
            plan_live.populate_node(node, resolver.resolve_node_content)
        plan.sections["tree"] = _tree_to_dict_list(tree_list)
        plan.plan_metadata["auto_populated"] = True
        plan.plan_metadata["auto_populated_at"] = datetime.now(timezone.utc).isoformat()
        flag_modified(plan, "sections")
        plan.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(plan)
    except Exception:
        # The whole auto-population - every resolved variable, and the commit
        # that saves them - is inside this try. Swallowing it returned a
        # plan that looks populated and is not, with a 200.
        logger.exception(
            "auto-population failed for plan %s - the plan is returned "
            "unpopulated and its variables are unresolved",
            getattr(plan, "id", "?"),
        )
        # POSTPONED 2026-08-25 (H3.4). Re-enable with:
        #   db.rollback()
        # so the response reflects the database instead of a half-mutated
        # in-memory plan claiming auto_populated: true. Off until H3.4 is
        # retested.

    return plan_to_dict(plan)


@router.get("/calculation/{calculation_id}")
def get_operational_plan_by_calculation(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get the Operational Plan for a given calculation ID."""
    plan = db.execute(
        select(OperationalPlan).where(OperationalPlan.calculation_id == calculation_id)
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Operational plan not found")
    _check_calc_access(calculation_id, current_user, db)

    sections = plan.sections or {}
    if not sections.get("tree"):
        seed_tree = get_full_seed_document()
        recompute_numbers(seed_tree, language="NP")
        sections["tree"] = _tree_to_dict_list(seed_tree)
        plan.sections = dict(sections)
        flag_modified(plan, "sections")
        db.commit()
        db.refresh(plan)

    return plan_to_dict(plan)


@router.get("/calculation/{calculation_id}/export-requirements")
def get_export_requirements_for_calculation(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """The same checklist as ``/{plan_id}/export-requirements``, asked before any plan exists (the template store shows it)."""
    _check_calc_access(calculation_id, current_user, db)
    from app.services.operational_plan.export_requirements import export_requirements

    return export_requirements(db, calculation_id)


@router.put("/{plan_id}")
def update_operational_plan(
    plan_id: UUID,
    plan_data: OperationalPlanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update an existing Operational Plan's tree, sections, or status."""
    plan = _check_plan_access(plan_id, current_user, db)

    if plan_data.tree is not None:
        tree = _dict_list_to_tree([t.model_dump() for t in plan_data.tree])
        recompute_numbers(
            tree, language=(plan.plan_metadata or {}).get("language", "NP")
        )
        _save_tree(plan, tree, db)

    if plan_data.sections is not None:
        plan.sections = plan_data.sections

    if plan_data.status is not None:
        plan.status = plan_data.status
        if plan_data.status == "submitted" and not plan.submitted_at:
            plan.submitted_at = datetime.now(timezone.utc)
            plan.submitted_by = current_user.id
            calc = (
                db.query(Calculation)
                .filter(Calculation.id == plan.calculation_id)
                .first()
            )
            if calc:
                from ..services.structure_lock_service import (
                    apply_structure_lock_transition,
                    LockTransition,
                )

                apply_structure_lock_transition(
                    calculation=calc,
                    transition=LockTransition.AUTO_LOCK,
                    db=db,
                    current_user=current_user,
                )
                logger.info(
                    f"Auto-lock: calculation={plan.calculation_id} plan={plan_id} user={current_user.id}"
                )
        elif plan_data.status == "approved" and not plan.approved_at:
            plan.approved_at = datetime.now(timezone.utc)
            plan.approved_by = current_user.id

    if plan_data.plan_metadata is not None:
        plan.plan_metadata = plan_data.plan_metadata

    plan.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(plan)

    return plan_to_dict(plan)


# ═══════════════════════════════════════════════════════════
# Tree CRUD Endpoints
# ═══════════════════════════════════════════════════════════


# business: document tree is the canonical OP representation — all CRUD, export, and preview operate on it
@router.get("/{plan_id}/tree")
def get_tree(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get the document tree for an Operational Plan."""
    plan = _check_plan_access(plan_id, current_user, db)
    sections = plan.sections or {}
    tree_data = sections.get("tree", [])
    return {"tree": tree_data}


# business: document tree is the canonical OP representation — all CRUD, export, and preview operate on it
@router.post("/{plan_id}/tree/nodes", status_code=status.HTTP_201_CREATED)
def add_tree_node(
    plan_id: UUID,
    node_data: TreeNodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Add a new node to the document tree."""
    plan = _check_plan_access(plan_id, current_user, db)
    sections = plan.sections or {}
    tree_list = _dict_list_to_tree(sections.get("tree", []))

    new_node = TreeNode(
        type=node_data.type,
        title_ne=node_data.title_ne,
        title_en=node_data.title_en or node_data.title_ne,
        content=node_data.content,
        content_type=node_data.content_type,
        chart_type=node_data.chart_type,
        table_id=node_data.table_id,
        map_type=node_data.map_type,
        static_table=node_data.static_table,
    )

    tree_list = TreeOperations.add_node(
        tree_list, node_data.parent_id, new_node, node_data.position
    )
    recompute_numbers(
        tree_list, language=(plan.plan_metadata or {}).get("language", "NP")
    )
    _save_tree(plan, tree_list, db)

    return {"node": new_node.model_dump(), "tree": _tree_to_dict_list(tree_list)}


@router.put("/{plan_id}/tree/nodes/{node_id}")
def update_tree_node(
    plan_id: UUID,
    node_id: str,
    node_data: TreeNodeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a specific node in the document tree."""
    plan = _check_plan_access(plan_id, current_user, db)
    sections = plan.sections or {}
    tree_list = _dict_list_to_tree(sections.get("tree", []))

    updates = {k: v for k, v in node_data.model_dump(exclude_none=True).items()}
    tree_list = TreeOperations.update_node(tree_list, node_id, updates)
    _save_tree(plan, tree_list, db)

    updated = TreeOperations.find_node(tree_list, node_id)
    return {"node": updated.model_dump() if updated else None}


@router.delete("/{plan_id}/tree/nodes/{node_id}")
def delete_tree_node(
    plan_id: UUID,
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete a node from the document tree."""
    plan = _check_plan_access(plan_id, current_user, db)
    sections = plan.sections or {}
    tree_list = _dict_list_to_tree(sections.get("tree", []))

    try:
        tree_list = TreeOperations.delete_node(tree_list, node_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    recompute_numbers(
        tree_list, language=(plan.plan_metadata or {}).get("language", "NP")
    )
    _save_tree(plan, tree_list, db)

    return {"tree": _tree_to_dict_list(tree_list)}


@router.put("/{plan_id}/tree/reorder")
def reorder_tree(
    plan_id: UUID,
    reorder_data: TreeNodeReorder,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Reorder nodes in the document tree by moving a node to a new parent or position."""
    plan = _check_plan_access(plan_id, current_user, db)
    sections = plan.sections or {}
    tree_list = _dict_list_to_tree(sections.get("tree", []))

    try:
        tree_list = TreeOperations.move_node(
            tree_list,
            reorder_data.node_id,
            reorder_data.new_parent_id,
            reorder_data.new_position,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    recompute_numbers(
        tree_list, language=(plan.plan_metadata or {}).get("language", "NP")
    )
    _save_tree(plan, tree_list, db)

    return {"tree": _tree_to_dict_list(tree_list)}


# ═══════════════════════════════════════════════════════════
# Auto-Populate Endpoint
# ═══════════════════════════════════════════════════════════


# business: auto-populate resolves all registered variables into the document tree sections
@router.post("/{plan_id}/auto-populate")
def auto_populate_sections(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Auto-populate all registered variables into the document tree."""
    plan = _check_plan_access(plan_id, current_user, db)

    if (plan.plan_metadata or {}).get("authoring"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "authoring_plan",
                "message": (
                    "This is an author-mode template test — {{tokens}} are kept "
                    "verbatim on purpose. Use Preview to see resolved values."
                ),
            },
        )

    resolver = VariableResolver(db, plan.calculation_id, plan)
    resolved = resolver.resolve_all()

    sections = plan.sections or {}
    tree_list = _dict_list_to_tree(sections.get("tree", []))

    for node in TreeOperations.flatten(tree_list):
        plan_live.populate_node(node, resolver.resolve_node_content)

    sections["tree"] = _tree_to_dict_list(tree_list)
    plan.sections = dict(sections)
    plan.plan_metadata = {
        **(plan.plan_metadata or {}),
        "auto_populated": True,
        "auto_populated_at": datetime.now(timezone.utc).isoformat(),
        "resolved_variables": {
            k: v for k, v in resolved.items() if isinstance(v, (str, int, float, bool))
        },
    }
    flag_modified(plan, "sections")
    plan.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(plan)

    return plan_to_dict(plan)


# ═══════════════════════════════════════════════════════════
# Variable Registry Endpoints
# ═══════════════════════════════════════════════════════════


# business: variable registry drives template auto-population — each key maps to a data collector
@router.get("/variables")
async def list_variables(
    category: Optional[str] = Query(None, description="Filter by category (A-F)"),
    search: Optional[str] = Query(None, description="Search by name or label"),
):
    """List all registered variables with optional category or search filter."""
    if search:
        vars_list = search_variables(search)
    elif category:
        vars_list = get_variables_by_category(category.upper())
    else:
        vars_list = get_all_variables()

    # HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P1 — a legacy key with a canonical
    # twin still resolves, but the picker shows one descriptive name per value.
    vars_list = [v for v in vars_list if not getattr(v, "alias_of", "")]

    enriched = {v["key"]: v for v in get_enriched_variables()}

    return {
        "total": len(vars_list),
        "variables": [
            VariableDefResponse(
                key=v.key,
                category=v.category,
                label_ne=v.label_ne,
                label_en=v.label_en,
                var_type=v.var_type,
                source=v.source,
                auto_populate=v.auto_populate,
                description=v.description,
                description_ne=enriched.get(v.key, {}).get("description_ne", ""),
                table_columns=json.loads(
                    enriched.get(v.key, {}).get("table_columns", "[]")
                ),
                mock_rows=json.loads(enriched.get(v.key, {}).get("mock_rows", "[]")),
            )
            for v in vars_list
        ],
    }


@router.get("/variables/{key}")
async def get_variable_detail(key: str):
    """Get detailed information for a single registered variable by key."""
    var = get_variable(key)
    if not var:
        raise HTTPException(status_code=404, detail=f"Variable '{key}' not found")
    enriched = next((v for v in get_enriched_variables() if v["key"] == key), {})
    return VariableDefResponse(
        key=var.key,
        category=var.category,
        label_ne=var.label_ne,
        label_en=var.label_en,
        var_type=var.var_type,
        source=var.source,
        auto_populate=var.auto_populate,
        description=var.description,
        description_ne=enriched.get("description_ne", ""),
        table_columns=json.loads(enriched.get("table_columns", "[]")),
        mock_rows=json.loads(enriched.get("mock_rows", "[]")),
    )


# ═══════════════════════════════════════════════════════════════════
# Map variables — the reference page + Copyable? column
# THEMATIC_MAP_VARIABLES_PLAN §3.9 / P3
# ═══════════════════════════════════════════════════════════════════
@router.get("/map-variables/forests")
def list_map_variable_forests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Forests the user can pick to evaluate map-variable availability against.

    A super admin sees every completed calculation; anyone else sees their own.
    Each row: ``{calc_id, forest_name, status, has_field_inventory, created_at}``.
    The `Copyable?` pill is computed live per request, so a forest created or
    processed later works exactly the same — pick it and the checks re-run
    against its current data.
    """
    from app.models.field_inventory import FieldInventoryCalculation

    q = db.query(
        Calculation.id,
        Calculation.forest_name,
        Calculation.status,
        Calculation.created_at,
    ).filter(Calculation.status == "completed")
    if current_user.role != UserRole.SUPER_ADMIN:
        q = q.filter(Calculation.user_id == current_user.id)
    rows = q.order_by(Calculation.created_at.desc()).limit(500).all()

    fi_ids: set[str] = set()
    if rows:
        fi_ids = {
            str(cid)
            for (cid,) in db.query(FieldInventoryCalculation.calculation_id)
            .filter(FieldInventoryCalculation.calculation_id.in_([r[0] for r in rows]))
            .distinct()
        }

    return {
        "forests": [
            {
                "calc_id": str(r[0]),
                "forest_name": r[1] or "(unnamed)",
                "status": r[2],
                "has_field_inventory": str(r[0]) in fi_ids,
                "created_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ]
    }


@router.get("/map-variables")
def list_map_variables(
    calc_id: Optional[UUID] = Query(
        None, description="Evaluate availability for this forest"
    ),
    family: Optional[str] = Query(None, description="thememap | opsmap | legacy"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Every map variable (`thememap:*`, `opsmap:*`, legacy `map:*`) with its
    reference-page metadata and the §3.9.1 `Copyable?` availability block.

    Without `calc_id` the availability block is *generic* (requirement text);
    with `calc_id` it is that forest's real answer.
    """
    from app.core import semantic_palettes as _sp
    from app.services.operational_plan import prereq_check as _pc
    from app.services.operational_plan.thematic_map_spec import (
        LEGACY_MAP_META,
        SECTION_NAMES,
        all_specs,
    )

    def _swatch(palette: str) -> list[str]:
        try:
            return _sp.resolve_palette(palette, 5)
        except Exception:  # noqa: BLE001
            return []

    def _availability(requires: list[str]) -> dict:
        r = _pc.check(db if calc_id else None, calc_id, requires or [])
        return {
            "status": r.status,  # available | partial | unavailable
            "copyable": r.copyable,
            "requires": requires or [],
            "reason_ne": r.reason_ne,
            "reason_en": r.reason_en,
            "hint_ne": r.hint_ne,
            "hint_en": r.hint_en,
        }

    items: list[dict] = []

    if family in (None, "thememap", "opsmap"):
        for spec in all_specs():
            if family and spec.family != family:
                continue
            sect = SECTION_NAMES.get(spec.section, {})
            items.append(
                {
                    "key": spec.token,
                    "family": spec.family,
                    "section": spec.section,
                    "section_ne": sect.get("ne", spec.section),
                    "section_en": sect.get("en", spec.section),
                    "label_ne": spec.label_ne or spec.key,
                    "label_en": spec.label_en or spec.key,
                    "description_ne": spec.description_ne,
                    "description_en": spec.description_en,
                    "viz": spec.viz,
                    "palette": spec.palette,
                    "palette_swatch": _swatch(spec.palette),
                    "basemap": spec.basemap,
                    "missing_data_behavior": spec.missing_data_behavior,
                    "preview_url": f"/api/operational-plans/map-variables/{spec.token}/preview.png",
                    "availability": _availability(list(spec.requires or [])),
                }
            )

    if family in (None, "legacy"):
        from app.services.operational_plan.variable_registry import get_variable

        for key, (section, requires, desc_en, basemap) in LEGACY_MAP_META.items():
            vd = get_variable(key)
            if vd is None:
                continue
            sect = SECTION_NAMES.get(section, {})
            items.append(
                {
                    "key": key,
                    "family": "legacy",
                    "section": section,
                    "section_ne": sect.get("ne", section),
                    "section_en": sect.get("en", section),
                    "label_ne": vd.label_ne,
                    "label_en": vd.label_en,
                    "description_ne": "",
                    "description_en": desc_en,
                    "viz": "basemap_overlay",
                    "palette": "",
                    "palette_swatch": [],
                    "basemap": basemap,
                    "missing_data_behavior": "placeholder",
                    "preview_url": (
                        f"/api/operational-plans/map-variables/{key}/preview.png"
                        + (f"?calc_id={calc_id}" if calc_id else "")
                    ),
                    "availability": _availability(list(requires or [])),
                }
            )

    # group by family then section for the page rail
    return {
        "total": len(items),
        "sections": SECTION_NAMES,
        "variables": items,
    }


@router.get("/map-variables/{key:path}/preview.png")
def map_variable_preview(
    key: str,
    calc_id: Optional[UUID] = Query(None),
    variant: str = Query("baseline"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """PNG thumbnail for a map variable. Without `calc_id` a `thememap:` spec
    renders against the synthetic fixture; a legacy `map:*` needs a real forest
    and otherwise returns a placeholder.

    ``variant`` selects the SFM data key for ``sustainable_fm`` specs
    (``baseline`` | ``user``; SV-1.6). Unknown values → 422."""
    import io as _io

    from app.services.operational_plan.thematic_map_spec import resolve_spec

    _VARIANT_ALIASES = {
        "baseline": "baseline",
        "user": "user",
        "sfm": "baseline",
        "sfm_user": "user",
    }
    resolved_variant = _VARIANT_ALIASES.get(variant.strip().lower())
    if resolved_variant is None:
        raise HTTPException(
            status_code=422, detail="variant must be 'baseline' or 'user'"
        )

    png: bytes
    if key.startswith(("thememap:", "opsmap:")):
        spec = resolve_spec(key)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"Unknown map variable '{key}'")
        from app.services.operational_plan.thematic_overlay import (
            generate_thematic_map,
            render_from_fixture,
        )

        if calc_id:
            calc = db.query(Calculation).filter(Calculation.id == calc_id).first()
            buf = generate_thematic_map(
                db,
                calc_id,
                spec,
                forest_name=(calc.forest_name if calc else "") or "",
                dpi=96,
                use_cache=True,
                variant=resolved_variant,
            )
        else:
            buf = render_from_fixture(spec, dpi=96)
        png = buf.getvalue()
    elif key.startswith("map:"):
        if not calc_id:
            png = _legacy_placeholder_png(key)
        else:
            from app.services.management_plan_docx.plan_map_service import (
                generate_standard_map,
            )

            layer = key.split(":", 1)[1]
            layer = {"boundary_map": "boundary"}.get(layer, layer)
            calc = db.query(Calculation).filter(Calculation.id == calc_id).first()
            try:
                buf = generate_standard_map(
                    db,
                    calc_id,
                    layer,
                    forest_name=(calc.forest_name if calc else "") or "",
                    use_cache=True,
                )
                png = buf.getvalue()
            except Exception:  # noqa: BLE001
                png = _legacy_placeholder_png(key)
    else:
        raise HTTPException(status_code=400, detail="Not a map variable key")

    # The synthetic fixture never changes → cache hard. A calc-bound render can
    # change whenever the forest is re-analysed or its field inventory
    # reprocessed, so the browser must revalidate rather than sit on a day-old
    # image (the server-side maps_cache is cleared on those events).
    cache_control = (
        "no-cache" if calc_id else "public, max-age=86400"
    )
    return StreamingResponse(
        _io.BytesIO(png),
        media_type="image/png",
        headers={"Cache-Control": cache_control},
    )


def _legacy_placeholder_png(key: str) -> bytes:
    """A tiny 'preview in DOCX/PDF export' placeholder for legacy raster maps
    with no forest in context."""
    import io as _io

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt

    from app.core.text_shaping import save_figure

    fig, ax = _plt.subplots(figsize=(4, 3), dpi=96)
    ax.axis("off")
    ax.text(
        0.5,
        0.5,
        f"{key}\n\n(preview needs a forest)",
        ha="center",
        va="center",
        fontsize=10,
        color="#888888",
    )
    ax.add_patch(
        _plt.Rectangle(
            (0.03, 0.03),
            0.94,
            0.94,
            fill=False,
            edgecolor="#cccccc",
            linewidth=1.0,
            transform=ax.transAxes,
        )
    )
    b = _io.BytesIO()
    save_figure(fig, b, format="PNG", dpi=96, facecolor="white", bbox_inches="tight")
    _plt.close(fig)
    return b.getvalue()


@router.get("/variables/export/csv")
async def export_variables_csv(
    current_user: User = Depends(get_current_active_user),
):
    """Superuser-only CSV export of enriched variable registry — 28 columns."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only super admins can export the variable registry"
        )
    enriched = get_enriched_variables()
    csv_content = build_csv_string(enriched)
    filename, disposition = build_disposition("OP", "Variable", "Registry", "csv")
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": disposition},
    )


@router.get("/{calculation_id}/variable-catalog")
def get_variable_catalog(
    calculation_id: UUID,
    category: Optional[str] = Query(None, description="Filter by category (A-F)"),
    search: Optional[str] = Query(None, description="Search by key or label"),
    keys: Optional[str] = Query(
        None,
        description="Comma-separated variable keys — return (and include the "
        "raw resolved value for) only these. Used by the in-context variable "
        "reference (HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P3).",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Returns ALL variables with their resolved values for a given calculation.
    This is the complete variable catalog — shows variable key, type, sample output,
    and whether the data is available for the current forest calculation."""
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    plan = (
        db.query(OperationalPlan)
        .filter(OperationalPlan.calculation_id == calculation_id)
        .first()
    )
    if not plan:
        plan = OperationalPlan(
            calculation_id=calculation_id,
            forest_name=calc.forest_name or "",
            plan_metadata={},
            status="draft",
        )

    resolver = VariableResolver(db, calculation_id, plan)
    try:
        all_resolved = resolver.resolve_all()
    except Exception as e:
        logger.warning(
            "OP_VARIABLE_CATALOG: resolve_all failed for calc %s: %s", calculation_id, e
        )
        all_resolved = {}

    if search:
        vars_list = search_variables(search)
    elif category:
        vars_list = get_variables_by_category(category.upper())
    else:
        vars_list = get_all_variables()

    # HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P1 — hide legacy keys that have a
    # canonical `hazard_*` twin (they still resolve for existing templates).
    vars_list = [v for v in vars_list if not getattr(v, "alias_of", "")]

    # P3 — an explicit key list narrows the response and opts each row into
    # carrying its raw resolved value (so the reference page can render a real
    # table / chart / prose block, not just a sample string).
    want_keys = (
        {k.strip() for k in keys.split(",") if k.strip()} if keys else None
    )
    if want_keys is not None:
        vars_list = [v for v in vars_list if v.key in want_keys]

    enriched = {v["key"]: v for v in get_enriched_variables()}

    def _resolved_payload(val):
        """Bounded copy of a resolved value for the P3 preview."""
        if isinstance(val, list):
            return val[:60]
        if isinstance(val, str):
            return val[:8000]
        return val

    catalog = []
    for var_def in vars_list:
        resolved = all_resolved.get(var_def.key)

        data_status = "available"
        sample_value = resolved
        if resolved is None:
            data_status = "empty"
            sample_value = None
        elif isinstance(resolved, dict):
            if "datasets" in resolved:
                sample_value = f"[Chart: {resolved.get('type', 'pie')}, {len(resolved.get('labels', []))} categories]"
            elif "rows" in resolved:
                sample_value = f"[Table: {len(resolved.get('rows', []))} rows]"
            elif len(str(resolved)) > 200:
                sample_value = str(resolved)[:200] + "..."
        elif isinstance(resolved, list):
            if len(resolved) > 5:
                sample_value = f"[List: {len(resolved)} items]"
            elif all(isinstance(v, dict) for v in resolved):
                sample_value = (
                    f"[Table: {len(resolved)} rows, columns: {list(resolved[0].keys())}]"
                    if resolved
                    else "[]"
                )
        elif isinstance(resolved, bool):
            sample_value = str(resolved)

        enc = enriched.get(var_def.key, {})
        catalog.append(
            {
                "key": var_def.key,
                "category": var_def.category,
                "label_ne": var_def.label_ne,
                "label_en": var_def.label_en,
                "var_type": var_def.var_type,
                "source": var_def.source,
                "auto_populate": var_def.auto_populate,
                "data_status": data_status,
                "sample_value": sample_value,
                "description_ne": enc.get("description_ne", ""),
                "sub_group": enc.get("sub_group", ""),
                "table_columns": json.loads(enc.get("table_columns", "[]")),
                "mock_rows": json.loads(enc.get("mock_rows", "[]")),
                **(
                    {"resolved": _resolved_payload(resolved)}
                    if want_keys is not None
                    else {}
                ),
            }
        )

    return {"total": len(catalog), "variables": catalog}


@router.get("/{plan_id}/validity")
def get_plan_validity(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """"Check my document": problems the owner's edits would leave in the printed plan (never blocks anything)."""
    plan = _check_plan_access(plan_id, current_user, db)
    from app.services.operational_plan.plan_validity import plan_validity

    return plan_validity(db, (plan.sections or {}).get("tree", []))


@router.get("/{plan_id}/export-requirements")
def get_export_requirements(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """The mandatory-steps checklist the export is gated on (owner rule 2026-10-10), bilingual."""
    from app.services.operational_plan.export_requirements import export_requirements

    plan = _check_plan_access(plan_id, current_user, db)
    return export_requirements(db, plan.calculation_id)


@router.get("/{plan_id}/readiness")
def get_plan_readiness(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Which of *this plan's* variables have no data for this forest.

    WORKSPACE_FLOW_NAV_PLAN §7.1. The forest-scoped `variable-catalog` cannot
    answer this: it reports every registered key, not the tokens this document
    uses, so it cannot distinguish a plan that is ready from a plan that
    happens to use few variables.

    Three buckets, because "not ready" has three causes and only one of them is
    actionable by the user:

    * `missing` — a `{{token}}` with no data here (`known: false` means the key
      is not registered at all, i.e. a typo).
    * `unmet_maps` — a `{{thememap:…}}` / `{{opsmap:…}}` whose spec `requires`
      tags are unsatisfied.
    * `unverified` — a `{{chart:…}}` / `{{table:…}}` / `{{map:…}}`, dispatched
      by `op_docx_builder` with nothing checking it renders. Counted, not
      dropped, so an unrenderable chart cannot hide behind "all resolved".

    A fourth, **non-blocking** bucket `empty_lists` (ND-7, 2026-10-18) lists
    tokens that resolve to `[]`: the document prints a grey "सूची खाली छ" note
    for them and they do not block `ready`.

    Every human-readable field is bilingual. Never fails the request: an
    unreadiness that 500s is worse than one that reports nothing.
    """
    plan = _check_plan_access(plan_id, current_user, db)
    return plan_readiness(db, plan.calculation_id, plan)


class SubmissionCreate(BaseModel):
    """A submission of an issued plan to a receiving office.

    `reference_no` is the receiving office's own file reference for the printed
    hard copy. It is optional here because an office sometimes issues the
    reference after accepting the document, but it is the field a forest office
    is asked for months later, so the UI should push for it.
    """

    submitted_to: str = Field(
        ..., min_length=1, max_length=255,
        description="Receiving office, e.g. the District Forest Office.",
    )
    channel: str = Field(
        "hand_delivery", max_length=32,
        description="How it reached the office: hand_delivery | email | post | portal.",
    )
    reference_no: Optional[str] = Field(
        None, max_length=64,
        description="The office's own file reference for the printed copy.",
    )
    notes: Optional[str] = None
    issuance_id: Optional[UUID] = None
    submitted_at: Optional[datetime] = None


@router.post("/{plan_id}/submissions", status_code=201)
def create_submission(
    plan_id: UUID,
    payload: SubmissionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Record that the plan was submitted to a receiving office.

    WORKSPACE_FLOW_NAV_PLAN P1. `document_issuances` records that bytes were
    produced; this records that the document left the building. A plan can be
    exported, printed and never submitted, and before this there was no way to
    tell those apart.

    P1 records the fact only. Per D17 the *projection* of it onto
    `operational_plans.status` -- which already has a `submitted` value, dormant
    transitions at `:576-603` and unused i18n keys -- lands in P6, where the
    projection and its transaction are done together. Do not set `status` here:
    writing it from two places is how the two drift apart.
    """
    plan = _check_plan_access(plan_id, current_user, db)
    from app.services.sub_area_plan import assert_sub_areas_planned

    assert_sub_areas_planned(db, db.get(Calculation, plan.calculation_id))  # a plan with unplanned sub-areas is not submitted
    try:
        new_id = record_submission(
            db,
            submitted_to=payload.submitted_to,
            plan_id=plan.id,
            calculation_id=plan.calculation_id,
            issuance_id=payload.issuance_id,
            channel=payload.channel,
            reference_no=payload.reference_no,
            notes=payload.notes,
            submitted_at=payload.submitted_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": str(new_id) if new_id else None, "plan_id": str(plan.id)}


@router.get("/{plan_id}/submissions")
def list_plan_submissions(
    plan_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Submissions for this plan, newest first. Never fails the request.

    Named `list_plan_submissions`, not `list_submissions`: the latter is the
    service function this calls, and shadowing it at module scope would make the
    body recurse into the endpoint.
    """
    plan = _check_plan_access(plan_id, current_user, db)
    return {
        "plan_id": str(plan.id),
        "submissions": list_submissions(db, plan_id=plan.id, limit=limit),
    }


# ═══════════════════════════════════════════════════════════
# Cascading Location Data Endpoints (from admin.admin_nepal)
# ═══════════════════════════════════════════════════════════


@router.get("/locations/provinces")
def list_provinces(db: Session = Depends(get_db)):
    """List all provinces for cascading location selection."""
    return get_provinces(db)


@router.get("/locations/districts")
def list_districts(
    province: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List districts with optional province filter."""
    return get_districts(db, province)


@router.get("/locations/municipalities-by-district")
def list_municipalities_by_district(
    province: str = Query(...),
    district: str = Query(...),
    db: Session = Depends(get_db),
):
    """List municipalities filtered by province and district."""
    return get_municipalities_by_district(db, province, district)


@router.get("/locations/wards-by-district")
def list_wards_by_district(
    province: str = Query(...),
    district: str = Query(...),
    municipality: str = Query(...),
    db: Session = Depends(get_db),
):
    """List wards filtered by province, district, and municipality."""
    return get_wards_by_district_municipality(db, province, district, municipality)


@router.get("/locations/physiography-by-district")
def get_physiography_by_district(
    province: str = Query(...),
    district: str = Query(...),
    municipality: str = Query(...),
    db: Session = Depends(get_db),
):
    """Get physiography and jurisdiction data for a given location."""
    return get_physiography_by_district_municipality(
        db, province, district, municipality
    )


@router.get("/locations/divisions")
def list_divisions(
    province: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List forest divisions with optional province filter."""
    return get_divisions(db, province)


@router.get("/locations/sub-divisions")
def list_sub_divisions(
    province: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List sub-divisions with optional province and division filter."""
    return get_sub_divisions(db, province, division)


@router.get("/locations/municipalities")
def list_municipalities(
    province: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    sub_division: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List municipalities with optional province, division, and sub-division filter."""
    return get_municipalities(db, province, division, sub_division)


@router.get("/locations/wards")
def list_wards(
    province: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    sub_division: Optional[str] = Query(None),
    municipality: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List wards with optional cascade filters."""
    return get_wards(db, province, division, sub_division, municipality)


@router.get("/locations/physiography-jurisdiction")
def get_location_physiography(
    province: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    sub_division: Optional[str] = Query(None),
    municipality: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Get physiography and jurisdiction details for cascaded location inputs."""
    return get_physiography_and_jurisdiction(
        db, province, division, sub_division, municipality
    )


# ═══════════════════════════════════════════════════════════
# Metadata Form Endpoint
# ═══════════════════════════════════════════════════════════


def _forest_shared(db, calculation_id) -> dict:
    """The forest's own facts (Forest Metadata tab) as plan-form keys: what every document reads for them."""
    from app.services.operational_plan.forest_shared_fields import shared_values

    return shared_values(db, calculation_id)


@router.get("/{plan_id}/metadata-form")
def get_metadata_form(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get the metadata form with user inputs and system defaults for a plan."""
    plan = _check_plan_access(plan_id, current_user, db)
    user_inputs = (plan.plan_metadata or {}).get("user_inputs", {})
    hybrid_overrides = (plan.plan_metadata or {}).get("hybrid_overrides", {})

    # Backward compat: map old municipality_type → forest_municipality_type
    if user_inputs.get("municipality_type") and not user_inputs.get(
        "forest_municipality_type"
    ):
        user_inputs["forest_municipality_type"] = user_inputs["municipality_type"]

    system_defaults = {}
    try:
        resolver = VariableResolver(db, plan.calculation_id, plan)
        for key, var_def in VARIABLE_REGISTRY.items():
            if var_def.resolver == "resolve_hybrid":
                val = resolver._resolve_category_a(var_def)
                if val is not None:
                    system_defaults[key] = val
    except Exception:
        logger.exception(
            "system defaults could not be resolved for plan %s - the form "
            "will open with blank fields where computed values belong",
            getattr(plan, "id", "?"),
        )

    has_location = bool(user_inputs.get("province"))
    if not has_location:
        loc = get_location_by_centroid(plan.calculation_id, db)
        if not loc:
            resolved = (plan.plan_metadata or {}).get("resolved_variables", {})
            loc = resolve_from_resolved_vars(resolved, db)
        if loc:
            loc["forest_municipality"] = loc.get("forest_municipality") or loc.get(
                "municipality"
            )
            loc["forest_ward"] = loc.get("forest_ward") or loc.get("ward")
            loc["forest_district"] = loc.get("forest_district") or loc.get("district")
            loc["forest_municipality_type"] = loc.get(
                "forest_municipality_type"
            ) or loc.get("municipality_type")
            loc["municipality"] = loc["forest_municipality"]
            loc["ward"] = loc["forest_ward"]
            loc["district"] = loc["forest_district"]
            loc["municipality_type"] = loc["forest_municipality_type"]
            loc["ug_prepopulated"] = True
            loc["ug_province"] = loc.get("province")
            loc["ug_district"] = loc.get("forest_district")
            loc["ug_division"] = loc.get("division")
            loc["ug_sub_division"] = loc.get("sub_division")
            loc["ug_municipality"] = loc.get("forest_municipality")
            loc["ug_municipality_type"] = loc.get("forest_municipality_type")
            loc["ug_ward"] = loc.get("forest_ward")
            loc = {k: v for k, v in loc.items() if v is not None}
            user_inputs = {**user_inputs, **loc}
            metadata = plan.plan_metadata or {}
            metadata["user_inputs"] = user_inputs
            plan.plan_metadata = metadata
            flag_modified(plan, "plan_metadata")
            db.commit()

    if not user_inputs.get("kabuliyatnama_date"):
        today_bs = nepali_date.today()
        user_inputs["kabuliyatnama_date"] = today_bs.strftime("%Y/%m/%d")
        metadata = plan.plan_metadata or {}
        metadata["user_inputs"] = user_inputs
        plan.plan_metadata = metadata
        flag_modified(plan, "plan_metadata")
        db.commit()

    # The forest's own facts (Forest Metadata tab) are shown here but never stored in the plan: no per-plan copy.
    from app.services.operational_plan.forest_shared_fields import SHARED_FIELDS, shared_values

    shared = shared_values(db, plan.calculation_id)
    user_inputs = {**user_inputs, **shared}

    admin_locations = {
        "provinces": get_provinces(db),
        "districts": [],
        "divisions": [],
        "sub_divisions": [],
        "municipalities": [],
        "wards": [],
    }

    province = user_inputs.get("province")
    forest_district = user_inputs.get("forest_district")
    division = user_inputs.get("division")
    sub_division = user_inputs.get("sub_division")

    if province:
        admin_locations["districts"] = get_districts(db, province)
        admin_locations["divisions"] = get_divisions(db, province)
    if province and forest_district:
        admin_locations["municipalities"] = get_municipalities_by_district(
            db, province, forest_district
        )
    if province and forest_district:
        mun = user_inputs.get("forest_municipality")
        if mun:
            admin_locations["wards"] = get_wards_by_district_municipality(
                db, province, forest_district, mun
            )
    if province and division:
        admin_locations["sub_divisions"] = get_sub_divisions(db, province, division)

    return {
        "user_inputs": user_inputs,
        "hybrid_overrides": hybrid_overrides,
        "system_defaults": system_defaults,
        "admin_locations": admin_locations,
        "shared_keys": sorted(SHARED_FIELDS),
        "calculation_id": str(plan.calculation_id),
    }


@router.put("/{plan_id}/metadata-form")
def update_metadata_form(
    plan_id: UUID,
    form_data: MetadataFormUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update the metadata form with user inputs and hybrid overrides."""
    plan = _check_plan_access(plan_id, current_user, db)

    user_inputs = (
        form_data.user_inputs.model_dump(exclude_none=True)
        if form_data.user_inputs
        else {}
    )
    hybrid = (
        form_data.hybrid_overrides.model_dump(exclude_none=True)
        if form_data.hybrid_overrides
        else {}
    )

    from app.services.operational_plan.forest_shared_fields import without_shared

    user_inputs = without_shared(user_inputs)      # entered once, on the Forest Metadata tab
    metadata = plan.plan_metadata or {}
    metadata["user_inputs"] = user_inputs
    metadata["hybrid_overrides"] = hybrid
    plan.plan_metadata = metadata
    flag_modified(plan, "plan_metadata")
    plan.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(plan)

    admin_locations = {
        "provinces": get_provinces(db),
        "districts": [],
        "divisions": [],
        "sub_divisions": [],
        "municipalities": [],
        "wards": [],
    }

    province = user_inputs.get("province")
    forest_district = user_inputs.get("forest_district")
    division = user_inputs.get("division")
    sub_division = user_inputs.get("sub_division")

    if province:
        admin_locations["districts"] = get_districts(db, province)
        admin_locations["divisions"] = get_divisions(db, province)
    if province and forest_district:
        admin_locations["municipalities"] = get_municipalities_by_district(
            db, province, forest_district
        )
    if province and forest_district:
        mun = user_inputs.get("forest_municipality")
        if mun:
            admin_locations["wards"] = get_wards_by_district_municipality(
                db, province, forest_district, mun
            )
    if province and division:
        admin_locations["sub_divisions"] = get_sub_divisions(db, province, division)

    return {
        "status": "ok",
        "plan_metadata": plan.plan_metadata,
        "admin_locations": admin_locations,
    }


# ═══════════════════════════════════════════════════════════
# HTML Preview Endpoint
# ═══════════════════════════════════════════════════════════

from fastapi.responses import HTMLResponse
from app.services.operational_plan.op_docx_builder import _walk_tree_html, _html_escape


def _render_mode(mode: str) -> str:
    """Validate the preview/render ``mode`` query param
    (OP_TEMPLATE_MANAGEMENT_PLAN.md T2). ``values`` (default) resolves every
    ``{{token}}``; ``tokens`` leaves them verbatim for template proofing."""
    if mode not in ("values", "tokens"):
        raise HTTPException(
            status_code=422, detail="mode must be 'values' or 'tokens'"
        )
    return mode


# business: HTML preview renders resolved variables and charts for in-browser review before DOCX export
# Both paths are read-only: they resolve in memory and never write the plan.
@router.get("/{plan_id}/preview")
@router.get("/{plan_id}/render")
def preview_operational_plan(
    plan_id: UUID,
    mode: str = Query("values", description="values | tokens"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Render the full Operational Plan as an HTML preview. ``mode=tokens``
    keeps every ``{{variable}}`` verbatim (author-mode proofing)."""
    mode = _render_mode(mode)
    plan = _check_plan_access(plan_id, current_user, db)
    sections = plan.sections or {}
    tree_list = _dict_list_to_tree(sections.get("tree", []))
    resolver = VariableResolver(db, plan.calculation_id, plan, render_mode=mode)

    plan_live.resolve_for_output(TreeOperations.flatten(tree_list), resolver.resolve_node_content)

    # OP multi-template §3.9: a template-owned cover node replaces the built-in
    # hardcoded cover; it is rendered separately and dropped from the body/TOC.
    from app.services.operational_plan.cover import partition_cover

    cover_node, body_tree = partition_cover(tree_list)

    raw_data = resolver.get_raw_data()
    metadata = plan.plan_metadata or {}
    raw_data["user_inputs"] = {**(metadata.get("user_inputs") or {}), **_forest_shared(db, plan.calculation_id)}
    from app.services.operational_plan.op_docx_builder import _build_table_cache

    table_cache = _build_table_cache(plan.calculation_id, db, raw_data)
    body_html = _walk_tree_html(
        body_tree, plan.calculation_id, raw_data, db, table_cache,
        keep_tokens=(mode == "tokens"), resolver=resolver,
    )
    metadata = plan.plan_metadata or {}
    user_inputs = metadata.get("user_inputs", {})

    _dev = format_devanagari
    fn = plan.forest_name or user_inputs.get("forest_name", "")
    sn = user_inputs.get("sn_number", "")
    div = user_inputs.get("division", "")
    sdiv = user_inputs.get("sub_division", "")
    mun = user_inputs.get("forest_municipality", "")
    wd = user_inputs.get("forest_ward", "")
    py = user_inputs.get("op_preparation_year", "")
    sf = user_inputs.get("op_start_fy", "")
    ef = user_inputs.get("op_end_fy", "")
    reg = user_inputs.get("cf_registration_number", "")
    hd = user_inputs.get("cf_handover_date", "")
    dst = user_inputs.get("forest_district", "") or user_inputs.get("district", "")
    mun_type = user_inputs.get("municipality_type", "")
    mun_disp = f"{mun} {mun_type}" if mun_type else mun
    addr_parts = [f"{mun_disp} वडा नं. {wd}"]
    if dst:
        addr_parts.append(dst)

    if cover_node is not None:
        _cm = getattr(cover_node, "cover_meta", None) or {}
        _align = _cm.get("align", "center")
        _border = (
            ""
            if _cm.get("border_style") == "none"
            else ('<div class="border-outer"></div><div class="border-inner"></div>')
        )
        _ctitle = _html_escape(cover_node.title_ne or cover_node.title_en or "")
        _clines = "".join(
            f'<div style="font-size:14pt;margin:6px 0;">{_html_escape(l.strip())}</div>'
            for l in (cover_node.content or "").split("\n")
        )
        cover_html = (
            f'<div class="page">{_border}'
            f'<div class="content"><div class="inner" style="text-align:{_align};">'
            f'<div class="main-title" style="margin-top:64px;"><h1>{_ctitle}</h1></div>'
            f'<hr class="divider">{_clines}'
            f"</div></div></div>"
        )
    else:
        cover_html = f"""<div class="page">
  <div class="border-outer"></div>
  <div class="border-inner"></div>
  <div class="content">
    <div class="inner">

      <div class="reg-no">{'सामुदायिक वन द.नं. : ' + _dev(reg) if reg else ''}</div>

      <div class="main-title">
        <h1>सामुदायिक वन व्यवस्थापन कार्ययोजना</h1>
        <div class="year">{_dev(str(py)) if py else ''}</div>
      </div>

      <hr class="divider">

      <div class="details">
        <div><span class="label">क्रम संख्या :</span> {sn or '-'}</div>
        <div><span class="label">डिभिजन / सव डिभिजन / स्थानिय तह / वडा :</span> {_dev(div) if div else '-'} / {_dev(sdiv) if sdiv else '-'} / {_dev(mun) if mun else '-'} / {_dev(wd) if wd else '-'}</div>

        <div class="group">श्री {fn} सामुदायिक वन उपभोक्ता समूह</div>
        <div class="addr">{addr_parts[0] + (', ' + dst if dst else '')}</div>
        <div class="period">आ.व. {_dev(sf) if sf else '-'} देखि आ.व. {_dev(ef) if ef else '-'} सम्म</div>
      </div>

      <div class="en-box">
        <div class="t">COMMUNITY FORESTRY OPERATIONAL PLAN</div>
        <div class="sub">FY {sf} TO {ef}</div>
        <div class="d"><strong>Serial No.:</strong> {sn} &nbsp;|&nbsp; <strong>District/Sub Division/RM/Ward:</strong> {div} / {sdiv} / {mun} / {wd}</div>
        <div class="d"><strong>Shree {fn} Community Forest User Group</strong><br>{'Bagmati RM' if mun else ''} Ward No. {wd}{', ' + dst if dst else ''}</div>
      </div>

      <div class="bottom">
        <div class="h">{'वन हस्तान्तरण मिति : ' + _dev(hd) if hd else ''}</div>
        <div class="f">वन व्यवस्थापन कार्ययोजना {_dev(str(py)) if py else ''}</div>
      </div>

    </div>
  </div>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="ne">
<head>
<meta charset="UTF-8">
<title>{fn or 'CF'} — Operational Plan Preview</title>
<style>
  body {{ font-family: 'Noto Sans', 'Segoe UI', sans-serif; max-width: 21cm; margin: 0 auto; padding: 0; line-height: 1.7; color: #222; background: #eee; }}
  .page {{ background: white; width: 21cm; min-height: 29.7cm; margin: 0 auto; padding: 0; position: relative; box-sizing: border-box; }}
  .border-outer {{ position: absolute; top: 12px; left: 12px; right: 12px; bottom: 12px; border: 2px solid #006400; pointer-events: none; }}
  .border-inner {{ position: absolute; top: 16px; left: 16px; right: 16px; bottom: 16px; border: 1px solid #006400; pointer-events: none; }}
  .content {{ padding: 36px 32px 24px 32px; display: flex; flex-direction: column; min-height: 29.7cm; box-sizing: border-box; position: relative; z-index: 1; }}
  .inner {{ display: flex; flex-direction: column; min-height: calc(29.7cm - 60px); }}
  .reg-no {{ text-align: right; font-size: 11pt; margin-bottom: 16px; }}
  .main-title {{ text-align: center; margin: 0; padding-top: 12px; }}
  .main-title h1 {{ font-size: 22pt; font-weight: bold; color: #006400; margin: 0 0 4px; border: none; padding: 0; }}
  .main-title .year {{ font-size: 18pt; font-weight: bold; color: #006400; margin: 0; }}
  .divider {{ border: none; border-top: 2.5px solid #006400; margin: 12px 0 14px; }}
  .details {{ font-size: 11pt; line-height: 2; flex: 1; display: flex; flex-direction: column; justify-content: center; padding: 4px 0; }}
  .details .label {{ font-weight: 600; }}
  .details .group {{ font-size: 12pt; font-weight: bold; color: #006400; margin: 8px 0 3px; }}
  .details .addr {{ color: #444; }}
  .details .period {{ font-weight: 600; margin-top: 6px; }}
  .en-box {{ text-align: center; border: 2px double #006400; padding: 10px 14px; margin: 0; }}
  .en-box .t {{ font-size: 13pt; font-weight: bold; color: #333; }}
  .en-box .sub {{ font-size: 10pt; color: #666; margin: 2px 0 6px; }}
  .en-box .d {{ font-size: 10pt; color: #444; line-height: 1.8; margin: 0; }}
  .bottom {{ text-align: center; margin-top: auto; padding-top: 10px; }}
  .bottom .h {{ font-size: 11pt; color: #444; margin: 0 0 4px; }}
  .bottom .f {{ font-size: 14pt; font-weight: bold; color: #006400; margin: 0; }}

  h2 {{ color: #006400; margin-top: 24px; }}
  h3 {{ color: #333; }}
  .toc {{ margin-bottom: 30px; }}
  .toc a {{ color: #006400; text-decoration: none; }}
  .section {{ margin-bottom: 20px; }}
  .section-content {{ white-space: pre-wrap; font-size: 13px; }}
  .chart-placeholder {{ background: #f5f5f5; border: 2px dashed #ccc; border-radius: 8px; padding: 20px; text-align: center; margin: 12px 0; color: #999; }}
  .table-preview {{ overflow-x: auto; margin: 12px 0; }}
  table.data {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  table.data th {{ background: #006400; color: white; padding: 6px 8px; text-align: center; }}
  table.data td {{ padding: 4px 8px; border: 1px solid #ddd; }}
  table.data tr:nth-child(even) {{ background: #f9f9f9; }}
  .hidden {{ display: none; }}
  .page-break {{ page-break-before: always; }}
  hr.pb-marker {{ border: none; border-top: 2px dashed #006400; margin: 24px 0; }}
</style>
</head>
<body>
{cover_html}
<h2>विषय सूची</h2>
<div class="toc">{_build_toc_html(body_tree)}</div>
<hr>
{body_html}
{_render_custom_notes_html(metadata)}
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/{plan_id}/preview/section/{node_id}")
@router.get("/{plan_id}/render/section/{node_id}")
def preview_operational_plan_section(
    plan_id: UUID,
    node_id: str,
    mode: str = Query("values", description="values | tokens"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Render a single section as HTML preview (read-only — never writes the plan).
    Used by the editor's inline preview tab for immediate feedback.
    ``mode=tokens`` keeps every ``{{variable}}`` verbatim.
    """
    mode = _render_mode(mode)
    plan = _check_plan_access(plan_id, current_user, db)
    sections = plan.sections or {}
    tree_list = _dict_list_to_tree(sections.get("tree", []))
    resolver = VariableResolver(db, plan.calculation_id, plan, render_mode=mode)

    # Find the node by ID
    target = None
    for node in TreeOperations.flatten(tree_list):
        if node.id == node_id:
            target = node
            break

    if not target:
        raise HTTPException(status_code=404, detail="Section not found")

    # Resolve only this node's content
    plan_live.resolve_for_output([target], resolver.resolve_node_content)

    raw_data = resolver.get_raw_data()
    raw_data["user_inputs"] = {**((plan.plan_metadata or {}).get("user_inputs") or {}), **_forest_shared(db, plan.calculation_id)}
    from app.services.operational_plan.op_docx_builder import _build_table_cache

    table_cache = _build_table_cache(plan.calculation_id, db, raw_data)

    body_html = _walk_tree_html(
        [target], plan.calculation_id, raw_data, db, table_cache,
        keep_tokens=(mode == "tokens"), resolver=resolver,
    )

    html = f"""<!DOCTYPE html>
<html lang="ne">
<head>
<meta charset="UTF-8">
<title>Section Preview</title>
<style>
  body {{ font-family: 'Noto Sans', 'Segoe UI', sans-serif; margin: 0; padding: 16px; line-height: 1.7; color: #222; }}
  h1 {{ font-size: 18pt; font-weight: bold; color: #006400; margin: 0 0 8px; padding: 0; border: none; }}
  h2 {{ font-size: 15pt; font-weight: bold; color: #006400; margin: 0 0 6px; padding: 0; border: none; }}
  .section {{ margin-bottom: 8px; }}
  .section-content {{ font-size: 14pt; line-height: 1.8; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  th, td {{ border: 1px solid #333; padding: 6px 10px; font-size: 12pt; }}
  th {{ background: #e8f5e9; font-weight: 600; }}
  .chart-placeholder {{ background: #f9f9f9; border: 1px dashed #ccc; padding: 24px; text-align: center; margin: 8px 0; }}
  .page-break {{ page-break-before: always; }}
  hr.pb-marker {{ border: none; border-top: 2px dashed #006400; margin: 24px 0; }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get(
    "/templates/{template_id}/preview",
    summary="Render a template against a forest's data WITHOUT creating a plan",
)
def preview_template_with_forest(
    template_id: UUID,
    calculation_id: UUID = Query(..., description="Forest to resolve against"),
    mode: str = Query("values", description="values | tokens"),
    node_id: Optional[str] = Query(
        None, description="Render only this node's subtree (designer section preview)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """"Preview with my forest" (OP_TEMPLATE_MANAGEMENT_PLAN.md §3.5, T2).

    Resolves the template's tree against a real calculation and returns the HTML
    — nothing is persisted, no ``operational_plans`` row is touched. Lets a user
    (or a designer proofing a template) see how a template will render for a
    given forest before committing to "Use this template".
    """
    from types import SimpleNamespace

    from app.services.operational_plan.cover import partition_cover
    from app.services.operational_plan.op_docx_builder import _build_table_cache

    mode = _render_mode(mode)
    _check_calc_access(calculation_id, current_user, db)

    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == template_id)
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template_access.can_view(tmpl, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    tree_list = _dict_list_to_tree(tmpl.tree or [])
    recompute_numbers(tree_list, language="NP")

    # Transient stand-in for the plan — the resolver only reads plan_metadata.
    stub = SimpleNamespace(plan_metadata={})
    resolver = VariableResolver(
        db, calculation_id, stub, render_mode=mode  # type: ignore[arg-type]
    )
    for node in TreeOperations.flatten(tree_list):
        if node.content:
            node.content = resolver.resolve_node_content(node.content)

    _cover, body_tree = partition_cover(tree_list)

    if node_id:
        target = next(
            (n for n in TreeOperations.flatten(tree_list) if n.id == node_id), None
        )
        if target is None:
            raise HTTPException(status_code=404, detail="Section not found")
        body_tree = [target]

    raw_data = resolver.get_raw_data()
    raw_data["user_inputs"] = _forest_shared(db, calculation_id)
    table_cache = _build_table_cache(calculation_id, db, raw_data)
    body_html = _walk_tree_html(
        body_tree, calculation_id, raw_data, db, table_cache,
        keep_tokens=(mode == "tokens"), resolver=resolver,
    )

    html = f"""<!DOCTYPE html>
<html lang="ne">
<head>
<meta charset="UTF-8">
<title>{_html_escape(tmpl.name)} — Template Preview</title>
<style>
  body {{ font-family: 'Noto Sans', 'Segoe UI', sans-serif; margin: 0; padding: 24px; line-height: 1.7; color: #222; }}
  h1 {{ font-size: 18pt; font-weight: bold; color: #006400; margin: 0 0 8px; }}
  h2 {{ font-size: 15pt; font-weight: bold; color: #006400; margin: 0 0 6px; }}
  .section {{ margin-bottom: 8px; }}
  .section-content {{ font-size: 14pt; line-height: 1.8; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  th, td {{ border: 1px solid #333; padding: 6px 10px; font-size: 12pt; }}
  th {{ background: #e8f5e9; font-weight: 600; }}
  .chart-placeholder {{ background: #f9f9f9; border: 1px dashed #ccc; padding: 24px; text-align: center; margin: 8px 0; }}
  .page-break {{ page-break-before: always; }}
  hr.pb-marker {{ border: none; border-top: 2px dashed #006400; margin: 24px 0; }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""
    return HTMLResponse(content=html)


def _build_toc_html(tree: List[TreeNode]) -> str:
    lines = []
    for node in tree:
        if node.hidden_in_export or node.deleted:
            continue
        num = f"{node.number}. " if node.number else ""
        lines.append(
            f'<div style="padding-left:{node.level * 20}px"><a href="#{node.id}">{num}{node.title_ne}</a></div>'
        )
        if node.children:
            lines.append(_build_toc_html(node.children))
    return "\n".join(lines)


def _render_custom_notes_html(metadata: dict) -> str:
    custom_notes = metadata.get("custom_notes")
    if not custom_notes:
        return ""
    from app.services.operational_plan.op_docx_builder import _html_escape

    parts = ['<div style="page-break-before:always;margin-top:24px;">']
    parts.append("<h1>Custom Notes</h1>")
    for line in custom_notes.strip().split("\n"):
        parts.append(f"<p>{_html_escape(line.strip())}</p>")
    parts.append("</div>")
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════
# DOCX Export Endpoint
# ═══════════════════════════════════════════════════════════

from fastapi.responses import StreamingResponse, JSONResponse

# ═══════════════════════════════════════════════════════════
# Chart Data Endpoint (for live Chart.js preview)
# ═══════════════════════════════════════════════════════════


# business: chart data pulled from calculation result_data; drives inline Chart.js visualisations
@router.get("/{plan_id}/chart-data/{chart_type}")
def get_chart_data(
    plan_id: UUID,
    chart_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get chart data for live Chart.js preview of a given chart type."""
    plan = _check_plan_access(plan_id, current_user, db)
    resolver = VariableResolver(db, plan.calculation_id, plan)
    raw_data = resolver.get_raw_data()
    forest_name = raw_data.get("basic_info", {}).get("forest_name", "")

    chart_configs = {
        "species_pie": {
            "chart_type": "pie",
            "title": f"{forest_name} - Species Composition (Top 8)",
            "get_data": lambda rd: _chart_species_pie(rd, forest_name),
        },
        "forest_type_pie": {
            "chart_type": "pie",
            "title": f"{forest_name} - Forest Type Distribution",
            "get_data": lambda rd: _chart_forest_type_pie(rd, forest_name),
        },
        "block_area_bar": {
            "chart_type": "bar",
            "title": f"{forest_name} - Block-wise Area",
            "get_data": lambda rd: _chart_block_area_bar(rd, forest_name),
        },
        "dbh_histogram": {
            "chart_type": "bar",
            "title": f"{forest_name} - DBH Class Distribution",
            "get_data": lambda rd: _chart_dbh_histogram(rd, forest_name),
        },
        "biomass_bar": {
            "chart_type": "bar",
            "title": f"{forest_name} - Biomass & Carbon Stock",
            "get_data": lambda rd: _chart_biomass_bar(rd, forest_name),
        },
        "slope_pie": {
            "chart_type": "pie",
            "title": f"{forest_name} - Slope Classification",
            "get_data": lambda rd: _chart_slope_pie(rd, forest_name),
        },
        "canopy_pie": {
            "chart_type": "pie",
            "title": f"{forest_name} - Canopy Cover",
            "get_data": lambda rd: _chart_canopy_pie(rd, forest_name),
        },
        "landcover_pie": {
            "chart_type": "pie",
            "title": f"{forest_name} - Land Cover Distribution",
            "get_data": lambda rd: _chart_landcover_pie(rd, forest_name),
        },
        "species_composition_pie_fi": {
            "chart_type": "pie",
            "title": f"{forest_name} - प्रजाति संरचना (Species Composition)",
            "get_data": lambda rd: _chart_species_composition_pie_fi(rd, forest_name),
        },
        "forest_health_pie": {
            "chart_type": "pie",
            "title": f"{forest_name} - Forest Health Distribution",
            "get_data": lambda rd: _chart_forest_health_pie(rd, forest_name),
        },
        "aspect_rose": {
            "chart_type": "pie",
            "title": f"{forest_name} - Aspect Distribution",
            "get_data": lambda rd: _chart_aspect_pie(rd, forest_name),
        },
        "soil_bar": {
            "chart_type": "bar",
            "title": f"{forest_name} - Soil Distribution",
            "get_data": lambda rd: _chart_soil_bar(rd, forest_name),
        },
        "nasa_forest_2020_pie": {
            "chart_type": "pie",
            "title": f"{forest_name} - Forest Quality (NASA 2020)",
            "get_data": lambda rd: _chart_nasa_forest_2020_pie(rd, forest_name),
        },
    }

    if chart_type not in chart_configs:
        raise HTTPException(status_code=404, detail=f"Unknown chart type: {chart_type}")

    config = chart_configs[chart_type]
    result = config["get_data"](raw_data)
    if not result:
        raise HTTPException(
            status_code=404, detail=f"No data available for chart: {chart_type}"
        )

    return {
        "chart_type": config["chart_type"],
        "title": config["title"],
        "labels": result["labels"],
        "datasets": result["datasets"],
    }


def _chart_species_pie(raw: dict, forest_name: str) -> dict:
    species = raw.get("species", {})
    if isinstance(species, dict):
        species = species.get("species_list", [])
    if isinstance(species, dict):
        species = species.get("species_list", [])
    if not species or not isinstance(species, list):
        return None
    sorted_sp = sorted(species, key=lambda x: x.get("availability_rank", 999))[:8]
    labels = [s.get("scientific_name", "Unknown")[:25] for s in sorted_sp]
    colors = [
        "#2ecc71",
        "#3498db",
        "#e67e22",
        "#9b59b6",
        "#f1c40f",
        "#1abc9c",
        "#e74c3c",
        "#95a5a6",
    ]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Species Composition",
                "data": [1] * len(labels),
                "backgroundColor": colors[: len(labels)],
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_forest_type_pie(raw: dict, forest_name: str) -> dict:
    ra = raw.get("raster_analysis", {})
    ft = ra.get("forest_type", {}).get("percentages", {})
    if not ft:
        return None
    labels = list(ft.keys())
    values = list(ft.values())
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Forest Type",
                "data": values,
                "backgroundColor": [
                    "#1a5c2e",
                    "#27ae60",
                    "#82e0aa",
                    "#d5f5e3",
                    "#2ecc71",
                ],
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_block_area_bar(raw: dict, forest_name: str) -> dict:
    blocks = raw.get("blocks", {}).get("blocks", [])
    if not blocks:
        return None
    labels = [b.get("name", f"Block {i+1}")[:15] for i, b in enumerate(blocks)]
    values = [b.get("area_hectares", 0) for b in blocks]
    colors = [
        "#2ecc71",
        "#3498db",
        "#e67e22",
        "#e74c3c",
        "#9b59b6",
        "#f1c40f",
        "#1abc9c",
    ]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Area (hectares)",
                "data": values,
                "backgroundColor": colors[: len(blocks)],
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_dbh_histogram(raw: dict, forest_name: str) -> dict:
    inv = raw.get("inventory", {})
    dbh = inv.get("dbh_summary", {}) or inv.get("dbh_distribution", {})
    if not dbh or not isinstance(dbh, dict):
        return None
    labels = list(dbh.keys())
    values = list(dbh.values())
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Number of Trees",
                "data": values,
                "backgroundColor": "#3498db",
                "borderColor": "#2980b9",
                "borderWidth": 1,
            }
        ],
    }


def _chart_biomass_bar(raw: dict, forest_name: str) -> dict:
    bi = raw.get("basic_info", {})
    agb = bi.get("above_ground_biomass_tons", 0) or bi.get("agb_total", 0)
    carbon = bi.get("carbon_stock_tc", 0) or bi.get("carbon_stock", 0)
    if not agb and not carbon:
        return None
    return {
        "labels": ["Above Ground\nBiomass (tons)", "Carbon Stock\n(tons)"],
        "datasets": [
            {
                "label": "Amount (tons)",
                "data": [float(agb or 0), float(carbon or 0)],
                "backgroundColor": ["#27ae60", "#2980b9"],
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_slope_pie(raw: dict, forest_name: str) -> dict:
    ra = raw.get("raster_analysis", {})
    sp = ra.get("slope", {}).get("percentages", {})
    if not sp:
        return None
    labels = list(sp.keys())
    values = list(sp.values())
    color_map = {
        "gentle": "#84cc16",
        "moderate": "#eab308",
        "steep": "#f97316",
        "very_steep": "#ef4444",
        "flat": "#22c55e",
        "Flat": "#22c55e",
    }
    colors = [color_map.get(l, "#95a5a6") for l in labels]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Slope Classification",
                "data": values,
                "backgroundColor": colors,
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_canopy_pie(raw: dict, forest_name: str) -> dict:
    ra = raw.get("raster_analysis", {})
    cp = ra.get("canopy", {}).get("percentages", {})
    if not cp:
        return None
    labels = list(cp.keys())
    values = list(cp.values())
    color_map = {
        "tree": "#059669",
        "pole_trees": "#10b981",
        "regeneration": "#84cc16",
        "non_forest": "#94a3b8",
        "dense": "#059669",
        "medium": "#10b981",
        "sparse": "#84cc16",
    }
    colors = [color_map.get(l, "#95a5a6") for l in labels]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Canopy Cover",
                "data": values,
                "backgroundColor": colors,
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_landcover_pie(raw: dict, forest_name: str) -> dict:
    ra = raw.get("raster_analysis", {})
    lc = ra.get("landcover", {}).get("percentages", {})
    if not lc or not isinstance(lc, dict):
        return None
    sorted_lc = sorted(lc.items(), key=lambda x: x[1], reverse=True)[:6]
    labels = [x[0] for x in sorted_lc]
    values = [x[1] for x in sorted_lc]
    landcover_color_map = {
        "Tree cover": "#006400",
        "Shrubland": "#FFBB22",
        "Grassland": "#FFFF4C",
        "Cropland": "#F096FF",
        "Built-up": "#FA0000",
        "Bare/sparse vegetation": "#B4B4B4",
        "Permanent water bodies": "#0064C8",
        "Snow and ice": "#E0E0E0",
    }
    lc_colors = [landcover_color_map.get(l, "#95a5a6") for l in labels]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Land Cover",
                "data": values,
                "backgroundColor": lc_colors,
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_species_composition_pie_fi(raw: dict, forest_name: str) -> dict:
    fi = raw.get("field_inventory", {})
    comp = fi.get("fi_species_composition", {})
    if not comp or not isinstance(comp, dict):
        return None
    sorted_items = sorted(comp.items(), key=lambda x: x[1], reverse=True)[:10]
    labels = [x[0] for x in sorted_items]
    values = [x[1] for x in sorted_items]
    colors = [
        "#2ecc71",
        "#3498db",
        "#e67e22",
        "#9b59b6",
        "#f1c40f",
        "#1abc9c",
        "#e74c3c",
        "#95a5a6",
        "#27ae60",
        "#2980b9",
    ]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Species Composition (%)",
                "data": values,
                "backgroundColor": colors[: len(labels)],
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_forest_health_pie(raw: dict, forest_name: str) -> dict:
    ra = raw.get("raster_analysis", {})
    fh = ra.get("forest_health", {}).get("percentages", {})
    if not fh:
        return None
    labels = list(fh.keys())
    values = list(fh.values())
    color_map = {
        "excellent": "#228B22",
        "healthy": "#90EE90",
        "moderate": "#FFD700",
        "poor": "#FF8C00",
        "stressed": "#DC143C",
    }
    colors = [color_map.get(l, "#95a5a6") for l in labels]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Forest Health",
                "data": values,
                "backgroundColor": colors,
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_aspect_pie(raw: dict, forest_name: str) -> dict:
    ra = raw.get("raster_analysis", {})
    ap = ra.get("aspect", {}).get("percentages", {})
    if not ap:
        return None
    labels = list(ap.keys())
    values = list(ap.values())
    color_map = {
        "N": "#3498db",
        "NE": "#2ecc71",
        "E": "#f1c40f",
        "SE": "#e67e22",
        "S": "#e74c3c",
        "SW": "#9b59b6",
        "W": "#1abc9c",
        "NW": "#95a5a6",
    }
    colors = [color_map.get(l, "#95a5a6") for l in labels]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Aspect",
                "data": values,
                "backgroundColor": colors,
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_soil_bar(raw: dict, forest_name: str) -> dict:
    ra = raw.get("raster_analysis", {})
    sp = ra.get("soil", {}).get("percentages", {})
    if not sp:
        return None
    labels = list(sp.keys())
    values = list(sp.values())
    colors = ["#8B4513", "#A0522D", "#CD853F", "#D2691E", "#DEB887", "#D2B48C"][
        : len(labels)
    ]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Soil (%)",
                "data": values,
                "backgroundColor": colors,
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


def _chart_nasa_forest_2020_pie(raw: dict, forest_name: str) -> dict:
    rd = raw.get("result_data", {})
    pct = rd.get("whole_nasa_forest_2020_percentages", {})
    if not pct or not isinstance(pct, dict):
        return None
    items = {k: v for k, v in pct.items() if v > 0}
    if not items:
        return None
    labels = list(items.keys())
    values = list(items.values())
    color_map = {
        "Primary Forest": "#00FF00",
        "Young Secondary Forest": "#FF0000",
        "Old Secondary Forest": "#6666FF",
    }
    colors = [color_map.get(l, "#999999") for l in labels]
    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Forest Quality",
                "data": values,
                "backgroundColor": colors,
                "borderColor": "#fff",
                "borderWidth": 1,
            }
        ],
    }


# ═══════════════════════════════════════════════════════════
# Map GeoJSON Endpoint (for live Leaflet preview)
# ═══════════════════════════════════════════════════════════

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping


@router.get("/{plan_id}/map-geojson")
def get_map_geojson(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get GeoJSON features (boundary and blocks) for Leaflet map preview."""
    plan = _check_plan_access(plan_id, current_user, db)

    calculation = (
        db.query(Calculation).filter(Calculation.id == plan.calculation_id).first()
    )
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    features = []

    # Forest boundary
    if calculation.boundary_geom:
        try:
            shape = to_shape(calculation.boundary_geom)
            boundary_geojson = mapping(shape)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": "Forest Boundary",
                        "type": "boundary",
                        "color": "#27ae60",
                    },
                    "geometry": boundary_geojson,
                }
            )
        except Exception:
            logger.exception(
                "forest boundary unreadable - the plan map is built without it, "
                "so the blocks appear to float with no forest around them"
            )

    # Blocks
    blocks = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == plan.calculation_id)
        .order_by(ForestBlock.index)
        .all()
    )

    block_colors = [
        "#2ecc71",
        "#3498db",
        "#e67e22",
        "#e74c3c",
        "#9b59b6",
        "#f1c40f",
        "#1abc9c",
        "#e91e63",
    ]
    for i, block in enumerate(blocks):
        try:
            shape = to_shape(block.geometry)
            block_geojson = mapping(shape)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": block.name,
                        "type": "block",
                        "area_hectares": block.area_hectares,
                        "color": block_colors[i % len(block_colors)],
                    },
                    "geometry": block_geojson,
                }
            )
        except Exception:
            report_dropped(
                logger,
                "block",
                "it will be missing from the plan map",
                context=getattr(block, "name", None),
            )

    return {
        "type": "FeatureCollection",
        "features": features,
        "forest_name": calculation.forest_name or plan.forest_name or "CF",
    }


@router.post("/{plan_id}/clear-map-cache")
def clear_plan_map_cache(
    plan_id: UUID,
    layer: Optional[str] = Query(None, description="Specific layer or all"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Clear the map tile cache for this plan's layers."""
    from app.services.management_plan_docx.plan_map_service import clear_map_cache

    plan = _check_plan_access(plan_id, current_user, db)
    clear_map_cache(calculation_id=plan.calculation_id, layer_name=layer)
    return {"message": f"Map cache cleared for {layer or 'all layers'}"}


@router.get("/{plan_id}/editing-status")
def get_plan_editing_status(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Check whether user can edit the plan (super_admin only)."""
    plan = _check_plan_access(plan_id, current_user, db)
    return {
        "can_edit": current_user.role == UserRole.SUPER_ADMIN,
        "plan_created": plan.created_at.isoformat() if plan.created_at else None,
        "plan_updated": plan.updated_at.isoformat() if plan.updated_at else None,
    }


@router.get("/{plan_id}/export")
# business: CFMG — OP document must follow prescribed template structure
# constraint: in-memory DOCX stream via python-docx, not temp files
# NOTE: OP_EXPORT tag logs full export time (data_collect + resolve + build_doc)
async def export_operational_plan(
    plan_id: UUID,
    refresh_cache: bool = Query(False, description="Regenerate all cached maps"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Generate and download a DOCX Operational Plan."""
    t0 = time.time()
    from app.services.management_plan_docx.plan_map_service import clear_map_cache

    plan = _check_plan_access(plan_id, current_user, db)
    calc_id = plan.calculation_id

    # Owner rule 2026-10-10: the mandatory steps must all be complete before the document can be exported.
    from app.services.operational_plan.export_requirements import assert_export_ready

    assert_export_ready(db, calc_id)

    # Every sub-area tied to the yearly plan (owner rule 2026-10-08) is one of the requirements above, so a refusal lists it
    # with the rest and never leaves the lock behind.

    # U12: Acquire export lock (blocks geometry writes during export)
    calculation = await _acquire_export_lock(calc_id, db)
    if refresh_cache:
        clear_map_cache(calculation_id=plan.calculation_id)
        from app.models.op_data_cache import OpDataCache

        db.query(OpDataCache).filter(
            OpDataCache.calculation_id == plan.calculation_id
        ).delete()
        db.commit()

    try:
        sections = plan.sections or {}
        tree_list = _dict_list_to_tree(sections.get("tree", []))
        t1 = time.time()
        resolver = VariableResolver(db, plan.calculation_id, plan)

        plan_live.resolve_for_output(TreeOperations.flatten(tree_list), resolver.resolve_node_content)
        t2 = time.time()

        # H7.4: minted BEFORE the build, because it is stamped into the page
        # footer. The hash is then taken from the finished bytes, which include
        # the stamp. Doing it the other way round would record the hash of a
        # document that was never issued, and verification would fail for every
        # genuine copy.
        verification_code = mint_verification_code()

        from fastapi.concurrency import run_in_threadpool

        buffer = await run_in_threadpool(
            build_op_document,
            plan=plan_to_dict(plan),
            tree=tree_list,
            resolver=resolver,
            calculation_id=plan.calculation_id,
            db=db,
            verification_code=verification_code,
        )
        t3 = time.time()

        logger.info(
            "OP_EXPORT: plan_id=%s forest=%s data_collect=%.2fs resolve=%.2fs build_doc=%.2fs total=%.2fs",
            plan_id,
            plan.forest_name,
            t1 - t0,
            t2 - t1,
            t3 - t2,
            t3 - t0,
        )

        forest_name = plan.forest_name or "CF"
        # OP multi-template §3.9: per-kind export basename when the plan is pinned
        # to a kind whose op_plan_kinds.export_basename is set (D2b); else "OP".
        _tkind_key = (plan.plan_metadata or {}).get("template_kind")
        _tkind = get_plan_kind(db, _tkind_key) if _tkind_key else None
        _basename = (
            _tkind.export_basename if (_tkind and _tkind.export_basename) else "OP"
        )
        filename, disposition = build_disposition(
            forest_name, _basename, "DOCX", "docx"
        )

        # H7.4 / S1-54: hash the bytes actually sent, and record the issuance
        # with the provenance that produced its figures.
        #
        # `buffer.getvalue()` is taken once and reused for both the hash and
        # the response. Reading the buffer twice would risk hashing something
        # other than what was delivered, which is the one thing this must never
        # do -- a hash of a document nobody received verifies nothing.
        document_bytes = buffer.getvalue()
        record_issuance(
            db,
            document_bytes=document_bytes,
            verification_code=verification_code,
            document_type="operational_plan",
            calculation_id=plan.calculation_id,
            plan_id=plan.id,
            filename=filename,
        )

        # Email the DOCX to the user's account — best-effort and NEVER blocking.
        # The export/download proceeds regardless of SMTP config, a wrong
        # address, or a send failure; any error is logged and swallowed.
        try:
            send_docx_email(
                user_email=current_user.email,
                docx_bytes=document_bytes,
                filename=filename,
                forest_name=plan.forest_name or "",
            )
        except (
            Exception
        ) as e:  # pragma: no cover - defensive; send_docx_email never raises
            logger.warning(
                "[export] OP DOCX email skipped for %s: %s", current_user.email, e
            )

        return StreamingResponse(
            iter([document_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": disposition,
                # So a caller can check the file it received without a second
                # request, and so the code is recoverable if the recipient
                # loses the paper copy it is printed on.
                "X-Document-SHA256": sha256_of(document_bytes),
                "X-Verification-Code": verification_code,
            },
        )
    finally:
        # U12: Always release export lock
        await _release_export_lock(calc_id, db, status="complete")


# U12: Heartbeat endpoint to keep export lease alive during long exports
@router.get("/verify/{verification_code}")
def verify_document(
    verification_code: str,
    db: Session = Depends(get_db),
):
    """Resolve a verification code to the record of what was issued (H7.4).

    **Deliberately unauthenticated.** The person who needs this is holding a
    printed plan in a district forest office and asking whether it is genuine.
    Requiring an account would make the check useless to exactly the people it
    exists for -- a reviewer, an auditor, a member of the user group.

    It returns provenance, not content: the hash, the size, when it was issued,
    which geometry version and inventory produced its figures. Nothing here
    discloses household data or the document itself, and a code that does not
    exist gets the same shaped answer as one that does, so the endpoint cannot
    be used to enumerate.

    To check a file: hash it and compare.

        certutil -hashfile plan.docx SHA256      (Windows)
        sha256sum plan.docx                      (Linux, macOS)
    """
    from ..services.document_integrity import lookup

    record = lookup(db, verification_code)
    if record is None:
        return {
            "found": False,
            "message": (
                "No document was issued with this code. Check the code, or the "
                "document was not produced by this system."
            ),
            "message_np": (
                "यो कोड भएको कुनै कागजात जारी गरिएको छैन। कोड जाँच्नुहोस्, अथवा यो "
                "कागजात यस प्रणालीबाट बनेको होइन।"
            ),
        }
    return {
        "found": True,
        "message": (
            "This code matches a document issued by this system. Compare the "
            "SHA-256 below with your file to confirm it has not been altered."
        ),
        "message_np": (
            "यो कोड यस प्रणालीबाट जारी गरिएको कागजातसँग मिल्छ। तपाईंको फाइल "
            "परिवर्तन भएको छैन भन्ने पुष्टि गर्न तलको SHA-256 सँग तुलना गर्नुहोस्।"
        ),
        **record,
    }


@router.post("/{plan_id}/export-heartbeat")
async def export_heartbeat(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update export heartbeat to keep lease alive during long exports.
    Client should call this every ~60s during export.
    """
    plan = _check_plan_access(plan_id, current_user, db)
    await _heartbeat_export_lock(plan.calculation_id, db)
    return {"status": "ok"}


# U12: Emergency break export lock (SUPER_ADMIN only)
@router.post("/{plan_id}/export-break-lock")
async def break_export_lock(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Force-break an export lock (SUPER_ADMIN only).
    Use when an export process dies without releasing the lock.
    """
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only SUPER_ADMIN can break export locks"
        )

    plan = _check_plan_access(plan_id, current_user, db)
    await _release_export_lock(plan.calculation_id, db, status="failed")
    return {"status": "lock broken", "export_status": "failed"}


# ═══════════════════════════════════════════════════════════


# business: template system supports user-owned drafts and published (status-driven) templates
_PUBLIC_STATUSES = ("published", "deprecated")


def _with_authors(db: Session, templates, viewer: User):
    """Summaries with ``author_name`` filled in for shared templates (and the viewer's own)."""
    from app.services.operational_plan.template_credit import author_name

    out = []
    for t in templates:
        s = TemplateSummary.model_validate(t)
        s.author_name = author_name(db, t, viewer)
        out.append(s)
    return out


@router.get("/templates", summary="List templates (own + published)")
def list_templates(
    scope: str = Query("mine", description="mine | published | all"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List templates. `mine` = own (any status); `published` = live in the
    gallery; `all` = own + published (super admin also sees in_review)."""
    # legacy aliases
    if scope in ("shared", "global"):
        scope = "published"

    published = sa.and_(OPTemplate.status.in_(_PUBLIC_STATUSES), template_access.visible_clause(current_user))
    if scope == "mine":
        cond = OPTemplate.created_by == current_user.id
    elif scope == "published":
        cond = published
    else:  # all
        cond = sa.or_(OPTemplate.created_by == current_user.id, published)
        if current_user.role == UserRole.SUPER_ADMIN:
            cond = sa.or_(cond, OPTemplate.status == "in_review")

    conds = [cond, OPTemplate.item_type == "template"]
    if tag:
        # `tags` is JSONB: `@>` needs a JSON value, so wrap the tag in a
        # one-element array (`tags @> '["x"]'`), not a bare word.
        conds.append(OPTemplate.tags.contains([tag]))

    templates = (
        db.execute(
            select(OPTemplate)
            .where(sa.and_(*conds))
            .order_by(OPTemplate.is_system.desc(), OPTemplate.updated_at.desc())
        )
        .scalars()
        .all()
    )

    return {
        "total": len(templates),
        "templates": _with_authors(db, templates, current_user),
    }


@router.get("/templates/public", summary="Browse published templates (grouped by kind)")
def list_public_templates(
    tag: Optional[str] = Query(None, description="Filter by tag"),
    search: Optional[str] = Query(None, description="Search name or description"),
    plan_regime: Optional[str] = Query(None),
    plan_stage: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Published templates. Ordered regime -> stage -> kind-default -> updated,
    each tagged with `is_kind_default` so the gallery can badge the recommended
    one. No kind gate — any published template is selectable (D5)."""
    conditions = [OPTemplate.status == "published", OPTemplate.item_type == "template", template_access.visible_clause(current_user)]
    if tag:
        # JSONB `@>` needs a JSON value — wrap the tag in a one-element array.
        conditions.append(OPTemplate.tags.contains([tag]))
    if plan_regime:
        conditions.append(OPTemplate.plan_regime == plan_regime)
    if plan_stage:
        conditions.append(OPTemplate.plan_stage == plan_stage)
    if search:
        conditions.append(
            sa.or_(
                OPTemplate.name.ilike(f"%{search}%"),
                OPTemplate.description.ilike(f"%{search}%"),
            )
        )

    templates = (
        db.execute(
            select(OPTemplate)
            .where(sa.and_(*conditions))
            .order_by(
                OPTemplate.plan_regime.nullslast(),
                OPTemplate.plan_stage.nullslast(),
                OPTemplate.is_system.desc(),
                OPTemplate.updated_at.desc(),
            )
        )
        .scalars()
        .all()
    )

    kind_default_ids = {
        k.default_template_id for k in list_plan_kinds(db) if k.default_template_id
    }
    kinds = [
        _plan_kind_to_response(db, k) for k in list_plan_kinds(db, active_only=True)
    ]

    out = _with_authors(db, templates, current_user)
    for s in out:
        s.is_kind_default = s.id in kind_default_ids

    return {"total": len(out), "templates": out, "kinds": kinds}


class ReportBody(BaseModel):
    reason: str = Field(..., min_length=5, max_length=2000)


class ReportAction(BaseModel):
    action: str = Field(..., description="dismiss | unpublish")
    note: Optional[str] = ""


@router.get("/templates/analytics", summary="Super admin: what people change in the plans built from each template (anonymous counts)")
def template_analytics(
    min_owners: int = Query(2, ge=1, le=50, description="List an added section or a typed variable only when this many different people did it"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    from app.services.operational_plan.template_analytics import analyse

    return analyse(db, min_owners=min_owners)


@router.get("/templates/reports", summary="Super admin: complaints about shared templates")
def list_template_reports(
    status_filter: str = Query("open", alias="status", description="open | dismissed | actioned | all"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    q = select(OPTemplateReport).order_by(OPTemplateReport.created_at.asc())
    if status_filter != "all":
        q = q.where(OPTemplateReport.status == status_filter)
    rows = db.execute(q).scalars().all()
    out = []
    for r in rows:
        t = db.get(OPTemplate, r.template_id)
        who = db.get(User, r.reporter_id) if r.reporter_id else None
        out.append({
            "id": str(r.id), "template_id": str(r.template_id), "template_name": t.name if t else None,
            "template_status": t.status if t else None, "share_scope": t.share_scope if t else None,
            "reason": r.reason, "status": r.status, "reporter": (who.full_name if who else None),
            "created_at": r.created_at.isoformat() if r.created_at else None, "handled_note": r.handled_note,
        })
    return {"total": len(out), "reports": out}


@router.put("/templates/reports/{report_id}", summary="Super admin: dismiss a complaint or take the template down")
def handle_template_report(
    report_id: UUID,
    body: ReportAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    report = db.get(OPTemplateReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if body.action not in ("dismiss", "unpublish"):
        raise HTTPException(status_code=400, detail="action must be dismiss or unpublish")
    now = datetime.now(timezone.utc)
    if body.action == "dismiss":
        report.status, report.handled_by, report.handled_at, report.handled_note = "dismissed", current_user.id, now, body.note
    else:
        tmpl = _load_template_or_404(report.template_id, db)
        try:
            template_lifecycle.share(db, tmpl, actor_id=current_user.id, scope="private", license=tmpl.license)
        except TransitionError as e:
            raise _transition_error_to_http(e)
        for r in db.execute(
            select(OPTemplateReport).where(OPTemplateReport.template_id == tmpl.id, OPTemplateReport.status == "open")
        ).scalars():
            r.status, r.handled_by, r.handled_at, r.handled_note = "actioned", current_user.id, now, body.note
    db.commit()
    return {"id": str(report.id), "status": report.status}


@router.post("/templates/{template_id}/report", status_code=201, summary="Tell the super admin something is wrong with a shared template")
def report_template(
    template_id: UUID,
    body: ReportBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tmpl = _load_template_or_404(template_id, db)
    if not template_access.can_view(tmpl, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    if tmpl.created_by == current_user.id:
        raise HTTPException(status_code=400, detail="This is your own template")
    existing = db.execute(
        select(OPTemplateReport).where(
            OPTemplateReport.template_id == template_id,
            OPTemplateReport.reporter_id == current_user.id,
            OPTemplateReport.status == "open",
        )
    ).scalars().first()
    if existing:
        return {"id": str(existing.id), "already_reported": True}
    rep = OPTemplateReport(template_id=template_id, reporter_id=current_user.id, reason=body.reason.strip())
    db.add(rep)
    db.commit()
    return {"id": str(rep.id), "already_reported": False}


@router.get(
    "/templates/system",
    response_model=SystemTemplateResponse,
    summary="The one System Template + its version history + seed-tree sync status",
)
def get_system_template(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return the ``is_system`` template, its version snapshots, and whether its
    tree is still in sync with the code-owned seed tree
    (``scripts.rebuild_system_template.build_system_tree``).

    Any signed-in user may read it (it is the published fallback template); only
    a super admin can edit it (guarded on ``PUT /templates/{id}``).
    """
    tmpl = (
        db.execute(
            select(OPTemplate)
            .where(OPTemplate.is_system == True)  # noqa: E712
            .order_by(OPTemplate.updated_at.desc())
        )
        .scalars()
        .first()
    )
    if not tmpl:
        raise HTTPException(status_code=404, detail="No system template exists")

    versions = (
        db.execute(
            select(OPTemplateVersion)
            .where(OPTemplateVersion.template_id == tmpl.id)
            .order_by(OPTemplateVersion.version.desc())
        )
        .scalars()
        .all()
    )

    from scripts.rebuild_system_template import build_system_tree

    seed_tree = build_system_tree()

    def _titles(nodes: list) -> set:
        out: set = set()
        for n in nodes or []:
            if isinstance(n, dict):
                title = (n.get("title_ne") or n.get("title_en") or "").strip()
                if title:
                    out.add(title)
                out |= _titles(n.get("children", []))
        return out

    _skip = ("chart:", "map:", "table:", "thememap:", "opsmap:")

    def _tokens(nodes: list) -> set:
        out: set = set()
        for n in nodes or []:
            if isinstance(n, dict):
                for m in re.finditer(r"\{\{([^}]+)\}\}", n.get("content", "") or ""):
                    out.add(m.group(1).strip())
                out |= _tokens(n.get("children", []))
        return out

    row_tokens = _tokens(tmpl.tree or [])
    unregistered = sorted(
        tok
        for tok in row_tokens
        if tok not in VARIABLE_REGISTRY
        and not tok.startswith(_skip)
        and not tok.endswith(":full")
    )
    missing_sections = sorted(_titles(seed_tree) - _titles(tmpl.tree or []))

    from scripts.rebuild_system_template import _canonical

    in_sync = _canonical(tmpl.tree) == _canonical(seed_tree) and not unregistered

    return {
        "template": TemplateResponse.model_validate(tmpl),
        "versions": [TemplateVersionResponse.model_validate(v) for v in versions],
        "seed_sync": {
            "in_sync": in_sync,
            "missing_sections": missing_sections,
            "unregistered_tokens": unregistered,
        },
    }


_DEV_ASCII_DIGITS = set("0123456789०१२३४५६७८९")


@router.post(
    "/templates/system/adopt-from-plan",
    response_model=AdoptFromPlanResponse,
    summary="Rebuild the System Template's structure from a plan (super admin)",
)
def adopt_system_template_from_plan(
    plan_id: UUID = Query(..., description="Plan whose structure to adopt"),
    confirm: bool = Query(
        False, description="false = dry-run diff only; true = snapshot + apply"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    """Take a plan's **structure** (node tree, titles, order, content_type,
    static tables, cover) into the System Template, **restoring `{{tokens}}`**
    from the current System Template wherever a node still matches by id
    (OP_TEMPLATE_MANAGEMENT_PLAN.md §3.1 / Example A). The plan's resolved
    numbers never enter the template. ``confirm=false`` returns only the diff;
    ``confirm=true`` snapshots the current tree to ``op_template_versions``,
    writes the new tree, bumps the version, and audits it.
    """
    plan = _check_plan_access(plan_id, current_user, db)
    sys_tmpl = (
        db.execute(
            select(OPTemplate)
            .where(OPTemplate.is_system == True)  # noqa: E712
            .order_by(OPTemplate.updated_at.desc())
        )
        .scalars()
        .first()
    )
    if not sys_tmpl:
        raise HTTPException(status_code=404, detail="No system template exists")

    plan_tree = (plan.sections or {}).get("tree", [])
    if not plan_tree:
        raise HTTPException(status_code=400, detail="Plan has no document tree")

    sys_by_id: dict[str, dict] = {}

    def _index(nodes):
        for n in nodes or []:
            if isinstance(n, dict) and n.get("id"):
                sys_by_id[n["id"]] = n
            if isinstance(n, dict):
                _index(n.get("children") or [])

    _index(sys_tmpl.tree or [])

    def _title(n: dict) -> str:
        return (n.get("title_ne") or n.get("title_en") or "").strip()

    added: list[str] = []
    token_restored: list[str] = []
    needs_review: list[str] = []
    kept = 0

    def _rebuild(nodes):
        nonlocal kept
        out = []
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            newn = dict(n)
            if plan_live.is_live_dict(n):
                # nobody edited it: the template's own text, variables unresolved, is on record
                newn["content"] = n["source_content"]
            # a template never carries a plan's bookkeeping (plan_live.py)
            newn.pop("source_content", None)
            newn.pop("populated_hash", None)
            match = sys_by_id.get(n.get("id"))
            if match is not None:
                kept += 1
                tmpl_content = match.get("content", "") or ""
                if n.get("content") != tmpl_content:  # the plan's stored text, as the report has always counted it
                    newn["content"] = tmpl_content
                    if "{{" in tmpl_content:
                        token_restored.append(_title(n))
            else:
                added.append(_title(n))
                c = newn.get("content") or ""
                if (
                    c.strip()
                    and "{{" not in c
                    and any(ch in _DEV_ASCII_DIGITS for ch in c)
                ):
                    needs_review.append(_title(n))
            newn["children"] = _rebuild(n.get("children") or [])
            out.append(newn)
        return out

    new_tree = _rebuild(plan_tree)
    new_tree = ensure_cover_node(new_tree, cover_style=None)
    _t = _dict_list_to_tree(new_tree)
    recompute_numbers(_t, language="NP")
    new_tree = _tree_to_dict_list(_t)

    new_titles = {t for t in (_title(x) for x in sys_by_id.values()) if t}
    kept_titles: set[str] = set()

    def _collect_titles(nodes):
        for n in nodes or []:
            if isinstance(n, dict):
                if _title(n):
                    kept_titles.add(_title(n))
                _collect_titles(n.get("children") or [])

    _collect_titles(new_tree)
    removed = sorted(new_titles - kept_titles)

    diff = {
        "added": [a for a in added if a],
        "removed": removed,
        "token_restored": [t for t in token_restored if t],
        "needs_review": [t for t in needs_review if t],
        "kept": kept,
    }

    if not confirm:
        return {"diff": diff, "applied": False, "template": None}

    db.add(
        OPTemplateVersion(
            template_id=sys_tmpl.id,
            version=sys_tmpl.version or 1,
            tree=sys_tmpl.tree,
            name=sys_tmpl.name,
            description=sys_tmpl.description or "",
            changelog=f"Pre-adopt snapshot (structure from plan {plan_id})",
        )
    )
    sys_tmpl.tree = new_tree
    sys_tmpl.version = (sys_tmpl.version or 1) + 1
    summaries = generate_template_summaries(new_tree)
    sys_tmpl.sections_summary = summaries["sections_summary"]
    sys_tmpl.variables_summary = summaries["variables_summary"]
    sys_tmpl.changelog = f"Adopted structure from plan {plan_id}"
    sys_tmpl.updated_at = datetime.now(timezone.utc)
    template_lifecycle._write_audit(
        db,
        sys_tmpl,
        actor_id=current_user.id,
        action="adopt_from_plan",
        from_status=sys_tmpl.status,
        to_status=sys_tmpl.status,
        note=(
            f"from plan {plan_id}; +{len(diff['added'])} sections, "
            f"{len(diff['needs_review'])} need review"
        ),
        version=sys_tmpl.version,
    )
    db.commit()
    db.refresh(sys_tmpl)
    return {
        "diff": diff,
        "applied": True,
        "template": TemplateResponse.model_validate(sys_tmpl),
    }


@router.post(
    "/templates", status_code=status.HTTP_201_CREATED, summary="Save a new template"
)
def create_template(
    tmpl_data: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a new template from document tree data."""
    is_system = tmpl_data.is_system and current_user.role == UserRole.SUPER_ADMIN

    kind_key = resolve_kind_key(
        tmpl_data.plan_kind, tmpl_data.plan_regime, tmpl_data.plan_stage
    )
    _kind = get_plan_kind(db, kind_key) if kind_key else None
    tree_dicts = ensure_cover_node(
        [n.model_dump() for n in tmpl_data.tree], _kind.cover_style if _kind else None
    )
    summaries = generate_template_summaries(tree_dicts)

    tmpl = OPTemplate(
        name=tmpl_data.name,
        description=tmpl_data.description or "",
        tree=tree_dicts,
        tags=list(tmpl_data.tags) if tmpl_data.tags else [],
        template_category=tmpl_data.template_category,
        sections_summary=summaries["sections_summary"],
        variables_summary=summaries["variables_summary"],
        is_system=is_system,
        status="draft",
        plan_kind=kind_key,
        plan_regime=tmpl_data.plan_regime,
        plan_stage=tmpl_data.plan_stage,
        created_by=current_user.id,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)

    return TemplateResponse.model_validate(tmpl)


@router.get("/templates/{template_id}", summary="Get full template details")
def get_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get full details of a single template by ID."""
    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == template_id)
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template_access.can_view(tmpl, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    from app.services.operational_plan.template_credit import author_name

    resp = TemplateResponse.model_validate(tmpl)
    resp.author_name = author_name(db, tmpl, current_user)
    return resp


@router.put("/templates/{template_id}", summary="Update a template")
def update_template(
    template_id: UUID,
    tmpl_data: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a template's properties and optionally create a version snapshot."""
    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == template_id)
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if tmpl.is_system and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only super admins can edit system templates"
        )
    if (
        not tmpl.is_system
        and tmpl.created_by != current_user.id
        and current_user.role != UserRole.SUPER_ADMIN
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    # An author's change to a Verified or Official template voids the review: it is Community again until the super admin looks.
    if (
        tmpl.tier != "community"
        and not tmpl.is_system
        and current_user.role != UserRole.SUPER_ADMIN
        and (tmpl_data.tree is not None or tmpl_data.name is not None or tmpl_data.description is not None)
    ):
        tmpl.tier = "community"

    if tmpl_data.name is not None:
        tmpl.name = tmpl_data.name
    if tmpl_data.description is not None:
        tmpl.description = tmpl_data.description
    if tmpl_data.tree is not None:
        tree_dicts = [n.model_dump() for n in tmpl_data.tree]
        should_snapshot = tmpl.status in ("published", "deprecated") or tmpl.is_system
        if should_snapshot and tmpl.tree:
            old_version = tmpl.version
            old_snapshot = OPTemplateVersion(
                template_id=tmpl.id,
                version=old_version,
                tree=tmpl.tree,
                name=tmpl.name,
                description=tmpl.description or "",
                changelog=tmpl.changelog or "Version " + str(old_version),
            )
            db.add(old_snapshot)
            tmpl.version = (tmpl.version or 1) + 1
            if tmpl_data.changelog:
                tmpl.changelog = tmpl_data.changelog
        tmpl.tree = tree_dicts
        summaries = generate_template_summaries(tree_dicts)
        tmpl.sections_summary = summaries["sections_summary"]
        tmpl.variables_summary = summaries["variables_summary"]
    if tmpl_data.tags is not None:
        tmpl.tags = list(tmpl_data.tags)
    if tmpl_data.template_category is not None:
        tmpl.template_category = tmpl_data.template_category
    if tmpl_data.preview_image_url is not None:
        tmpl.preview_image_url = tmpl_data.preview_image_url
    if (
        tmpl_data.plan_kind is not None
        or tmpl_data.plan_regime is not None
        or tmpl_data.plan_stage is not None
    ):
        if tmpl_data.plan_regime is not None:
            tmpl.plan_regime = tmpl_data.plan_regime
        if tmpl_data.plan_stage is not None:
            tmpl.plan_stage = tmpl_data.plan_stage
        tmpl.plan_kind = (
            resolve_kind_key(tmpl_data.plan_kind, tmpl.plan_regime, tmpl.plan_stage)
            or tmpl_data.plan_kind
        )

    # §3.3 — editing a template that is out for review sends it back to draft.
    if tmpl_data.tree is not None and tmpl.status == "in_review":
        tmpl.status = "draft"

    tmpl.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(tmpl)

    return TemplateResponse.model_validate(tmpl)


@router.put(
    "/templates/{template_id}/publish",
    deprecated=True,
    summary="[deprecated] Toggle publish — use POST /templates/{id}/review (approve)",
)
def publish_template(
    template_id: UUID,
    publish_data: TemplatePublish,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Legacy publish toggle (super admin only).

    Kept working for existing callers/tests; it now also keeps the `status`
    column in sync and writes an audit row, but does NOT run the validation
    gate. Prefer POST /templates/{id}/review (approve) for a real publish.
    """
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only super admins can publish templates"
        )
    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == template_id)
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if tmpl.is_system:
        raise HTTPException(status_code=400, detail="Cannot unpublish system templates")

    template_lifecycle.legacy_publish_shim(
        db, tmpl, actor_id=current_user.id, is_active=publish_data.is_active
    )
    db.commit()
    db.refresh(tmpl)
    return TemplateResponse.model_validate(tmpl)


@router.post("/templates/{template_id}/clone", summary="Clone a template")
def clone_template(
    template_id: UUID,
    clone_data: Optional[TemplateClone] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Clone a template into a new private draft owned by the caller.

    Any signed-in user may copy a template they can see: a published or deprecated one, their own, or (super admin) any
    (owner, 2026-10-16). The original is never touched; the copy remembers it in ``source_template_id``.

    Pass target_plan_kind (or target_plan_regime + target_plan_stage) to fork
    a New template into a Revision one, etc.
    """
    source = db.execute(
        select(OPTemplate).where(OPTemplate.id == template_id)
    ).scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template_access.can_view(source, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    if not template_access.can_copy(source, current_user):
        raise HTTPException(
            status_code=403,
            detail="The author allows this template to be used but not copied (licence: view only).",
        )

    summaries = generate_template_summaries(source.tree)

    clone_name = (
        clone_data.name if clone_data and clone_data.name else f"{source.name} (Copy)"
    )

    target_regime = (
        clone_data.target_plan_regime if clone_data else None
    ) or source.plan_regime
    target_stage = (
        clone_data.target_plan_stage if clone_data else None
    ) or source.plan_stage
    target_kind = (
        resolve_kind_key(
            clone_data.target_plan_kind if clone_data else None,
            target_regime,
            target_stage,
        )
        or source.plan_kind
    )
    _tk = get_plan_kind(db, target_kind) if target_kind else None
    cloned_tree = ensure_cover_node(
        [dict(n) for n in (source.tree or [])], _tk.cover_style if _tk else None
    )

    tmpl = OPTemplate(
        name=clone_name,
        description=source.description,
        tree=cloned_tree,
        tags=source.tags or [],
        template_category=source.template_category,
        sections_summary=summaries["sections_summary"],
        variables_summary=summaries["variables_summary"],
        is_system=False,
        status="draft",
        plan_kind=target_kind,
        plan_regime=target_regime,
        plan_stage=target_stage,
        version=1,
        source_template_id=source.id,
        source_version=source.published_version,
        created_by=current_user.id,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)

    return TemplateResponse.model_validate(tmpl)


@router.get("/templates/{template_id}/parent-status", summary="Has the original of this copy published something new?")
def template_parent_status(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """For the owner of a copy: is the original newer, and which sections would be added (nothing is changed)."""
    tmpl = _load_template_or_404(template_id, db)
    if tmpl.created_by != current_user.id and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")
    return template_parent_update.status(db, tmpl)


@router.post("/templates/{template_id}/add-parent-updates", summary="Add the original's new sections to my copy")
def add_parent_updates(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Adds the sections the original gained since the copy was taken. Nothing in the copy is removed or changed."""
    tmpl = _load_template_or_404(template_id, db)
    if tmpl.created_by != current_user.id and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")
    new_tree, report = template_parent_update.merge_new_sections(db, tmpl)
    if not report["added"]:
        return {"added": [], "version": tmpl.source_version}
    tmpl.tree = new_tree
    summaries = generate_template_summaries(new_tree)
    tmpl.sections_summary = summaries["sections_summary"]
    tmpl.variables_summary = summaries["variables_summary"]
    tmpl.source_version = report["version"]
    if tmpl.tier != "community" and current_user.role != UserRole.SUPER_ADMIN:
        tmpl.tier = "community"
    db.commit()
    return {"added": report["added"], "version": report["version"]}


@router.get("/templates/{template_id}/versions", summary="Get template version history")
def get_template_versions(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get version history for a template."""
    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == template_id)
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    versions = (
        db.execute(
            select(OPTemplateVersion)
            .where(OPTemplateVersion.template_id == template_id)
            .order_by(OPTemplateVersion.version.desc())
        )
        .scalars()
        .all()
    )

    return [TemplateVersionResponse.model_validate(v) for v in versions]


@router.post(
    "/templates/{template_id}/rollback",
    summary="Rollback template to a previous version",
)
def rollback_template(
    template_id: UUID,
    rollback_data: TemplateRollbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Rollback a template to a previous version (super admin only)."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only super admins can rollback templates"
        )

    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == template_id)
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    version_snapshot = db.execute(
        select(OPTemplateVersion).where(
            OPTemplateVersion.template_id == template_id,
            OPTemplateVersion.version == rollback_data.version,
        )
    ).scalar_one_or_none()
    if not version_snapshot:
        raise HTTPException(status_code=404, detail="Version not found")

    old_tree = tmpl.tree
    _live = tmpl.status in ("published", "deprecated")
    if _live:
        current_snapshot = OPTemplateVersion(
            template_id=tmpl.id,
            version=tmpl.version or 1,
            tree=old_tree,
            name=tmpl.name,
            description=tmpl.description or "",
            changelog=f"Pre-rollback state before reverting to v{rollback_data.version}",
        )
        db.add(current_snapshot)

    tmpl.tree = version_snapshot.tree
    summaries = generate_template_summaries(version_snapshot.tree)
    tmpl.sections_summary = summaries["sections_summary"]
    tmpl.variables_summary = summaries["variables_summary"]
    tmpl.version = (tmpl.version or 1) + 1 if _live else tmpl.version
    tmpl.changelog = f"Rolled back to version {rollback_data.version}"
    tmpl.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(tmpl)

    return TemplateResponse.model_validate(tmpl)


@router.delete("/templates/{template_id}", summary="Delete a user template")
def delete_template(
    template_id: UUID,
    permanent: bool = Query(False, description="Super admin only: really delete a shared template instead of withdrawing it"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete a user template (system templates cannot be deleted).

    A template that was shared or copied is withdrawn instead (see below). The super admin may pass ``permanent=true`` to delete
    one for good, for example for copied or private material that must not stay: the copies keep working, but their credit chain
    then stops at the copy, because the original is gone."""
    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == template_id)
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if tmpl.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system templates")
    if tmpl.created_by != current_user.id and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")

    # A template that has been shared, or that others have copied, is WITHDRAWN, not deleted: its row stays so the credit chain of
    # every copy keeps the original author (owner, 2026-10-17). It disappears from everyone's lists and nobody can build a new
    # plan from it; plans already made from it are unaffected. Anything else is really deleted.
    copies = db.query(OPTemplate.id).filter(OPTemplate.source_template_id == tmpl.id).count()
    if permanent and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only the super admin can delete a shared template permanently")
    if permanent:
        logger.warning(
            "template %s (%s) deleted permanently by super admin %s; copies=%d, ever_shared=%s",
            tmpl.id, tmpl.name, current_user.id, copies, template_access.ever_shared(tmpl),
        )
        db.query(OPTemplateVersion).filter(OPTemplateVersion.template_id == tmpl.id).delete(synchronize_session=False)
        # the copies keep working; they no longer point at an original that is gone (fk_op_templates_source_template)
        db.query(OPTemplate).filter(OPTemplate.source_template_id == tmpl.id).update(
            {OPTemplate.source_template_id: None}, synchronize_session=False
        )
        db.delete(tmpl)
        db.commit()
        return {"status": "deleted_permanently", "copies": copies, **i18n_success("success.template_deleted_permanently")}
    if template_access.ever_shared(tmpl) or copies:
        if tmpl.status != "retired":
            try:
                template_lifecycle.retire(db, tmpl, actor_id=current_user.id, note="Withdrawn by its author")
            except TransitionError as e:
                raise _transition_error_to_http(e)
            tmpl.share_scope = "private"
            tmpl.organization_id = None
        db.commit()
        return {"status": "withdrawn", "copies": copies, **i18n_success("success.template_withdrawn")}

    # Its version snapshots go with it. The ORM would otherwise try to blank their template_id (NOT NULL) and refuse; the audit
    # rows and reports cascade in the database.
    db.query(OPTemplateVersion).filter(OPTemplateVersion.template_id == tmpl.id).delete(synchronize_session=False)
    db.delete(tmpl)
    db.commit()

    return {"status": "ok", **i18n_success("success.template_deleted")}


# ═══════════════════════════════════════════════════════════
# Template lifecycle (OP_MULTI_TEMPLATE_PLAN.md §3.3) — Phase 1
# ═══════════════════════════════════════════════════════════


def _load_template_or_404(template_id: UUID, db: Session) -> OPTemplate:
    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == template_id)
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tmpl


def _transition_error_to_http(err: TransitionError) -> HTTPException:
    if err.code == "validation_failed":
        return HTTPException(
            status_code=422,
            detail={"code": err.code, "message": err.message, "issues": err.issues},
        )
    if err.code in ("note_required",):
        return HTTPException(
            status_code=400, detail={"code": err.code, "message": err.message}
        )
    if err.code == "system_protected":
        return HTTPException(
            status_code=403, detail={"code": err.code, "message": err.message}
        )
    return HTTPException(
        status_code=409, detail={"code": err.code, "message": err.message}
    )


def _commit_and_return(db: Session, tmpl: OPTemplate) -> TemplateResponse:
    db.commit()
    db.refresh(tmpl)
    return TemplateResponse.model_validate(tmpl)


# ═══════════════════════════════════════════════════════════
# Section library: one chapter of a plan, kept and shared on its own (item_type = 'section')
# ═══════════════════════════════════════════════════════════


class SaveSectionBody(BaseModel):
    node_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = ""


class InsertSectionBody(BaseModel):
    section_id: UUID
    parent_id: Optional[str] = None
    position: int = -1


@router.post("/{plan_id}/sections/save", summary="Save one chapter of this plan to my section library (no forest figures)")
def save_plan_section(
    plan_id: UUID,
    body: SaveSectionBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """A private section made from a chapter of the plan, with the forest's own values turned back into variables (the same
    rule as "save as my template"). Share it afterwards like a template."""
    from app.services.operational_plan import section_library

    plan = _check_plan_access(plan_id, current_user, db)
    tree, report = _tokenised_tree_from_plan(db, plan)
    section_tree = section_library.extract_section(tree, body.node_id)
    if section_tree is None:
        raise HTTPException(status_code=404, detail="That chapter is not in this plan, or it is the cover page")
    meta = plan.plan_metadata or {}
    summaries = generate_template_summaries(section_tree)
    parent_id = None
    try:
        parent_id = UUID(str(meta["template_id"])) if meta.get("template_id") else None
    except ValueError:
        parent_id = None
    sec = OPTemplate(
        item_type="section",
        name=body.name.strip(),
        description=body.description or "",
        tree=section_tree,
        tags=[],
        sections_summary=summaries["sections_summary"],
        variables_summary=summaries["variables_summary"],
        is_system=False,
        status="draft",
        plan_kind=meta.get("template_kind"),
        plan_regime=meta.get("template_regime"),
        plan_stage=meta.get("template_stage"),
        source_template_id=parent_id,  # where the chapter came from, for the credit chain
        created_by=current_user.id,
    )
    db.add(sec)
    db.commit()
    db.refresh(sec)
    edited_here = [e for e in report["edited"] + report["new"] if section_library.find_subtree(section_tree, e["id"])]
    return {"section": TemplateResponse.model_validate(sec), "report": {"nodes": section_library.count_nodes(section_tree), "edited": edited_here}}


@router.get("/sections", summary="The section library: mine, or everyone's shared sections")
def list_sections(
    scope: str = Query("published", description="mine | published | all"),
    search: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    published = sa.and_(OPTemplate.status.in_(_PUBLIC_STATUSES), template_access.visible_clause(current_user))
    if scope == "mine":
        cond = OPTemplate.created_by == current_user.id
    elif scope == "all":
        cond = sa.or_(OPTemplate.created_by == current_user.id, published)
    else:
        cond = published
    conds = [cond, OPTemplate.item_type == "section"]
    if tag:
        conds.append(OPTemplate.tags.contains([tag]))
    if search:
        like = f"%{search}%"
        conds.append(sa.or_(OPTemplate.name.ilike(like), OPTemplate.description.ilike(like)))
    rows = db.execute(select(OPTemplate).where(sa.and_(*conds)).order_by(OPTemplate.updated_at.desc())).scalars().all()
    return {"total": len(rows), "sections": _with_authors(db, rows, current_user)}


@router.post("/{plan_id}/sections/insert", summary="Insert a section from the library into this plan")
def insert_plan_section(
    plan_id: UUID,
    body: InsertSectionBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Copies the chapter in with new ids, fills its variables from this plan's forest, and keeps it following the data (plan_live).
    A section licensed view-only arrives locked."""
    from app.services.operational_plan import section_library

    plan = _check_plan_access(plan_id, current_user, db)
    sec = _load_template_or_404(body.section_id, db)
    if sec.item_type != "section":
        raise HTTPException(status_code=400, detail="That is a template, not a section")
    if not template_access.can_view(sec, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    lock = sec.license == "view_only" and sec.created_by != current_user.id and current_user.role != UserRole.SUPER_ADMIN
    nodes, new_ids = section_library.prepare_for_insert(list(sec.tree or []), lock=lock)
    if not nodes:
        raise HTTPException(status_code=400, detail="The section is empty")

    tree_list = _dict_list_to_tree((plan.sections or {}).get("tree", []))
    new_nodes = [TreeNode.from_dict(n) for n in nodes]
    try:
        for i, node in enumerate(new_nodes):
            TreeOperations.add_node(tree_list, body.parent_id, node, body.position + i if body.position >= 0 else -1)
    except ValueError:
        raise HTTPException(status_code=404, detail="The place to insert it was not found in this plan")
    resolver = VariableResolver(db, plan.calculation_id, plan)
    for node in TreeOperations.flatten(new_nodes):
        plan_live.populate_node(node, resolver.resolve_node_content)
    recompute_numbers(tree_list, language=(plan.plan_metadata or {}).get("language", "NP"))
    _save_tree(plan, tree_list, db)
    return {"inserted": new_ids, "locked": lock, "tree": _tree_to_dict_list(tree_list)}


class ShareRequest(BaseModel):
    scope: str = Field(..., description="private | office | public")
    license: str = Field("cc_by", description="cc_by | cc0 | view_only")


class TierRequest(BaseModel):
    tier: str = Field(..., description="community | verified | official")
    note: Optional[str] = ""


def _owner_or_admin(tmpl: OPTemplate, user: User) -> None:
    if tmpl.created_by != user.id and user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only the author can do this")


def _check_template(db: Session, tmpl: OPTemplate, author_id) -> Dict[str, Any]:
    from app.services.operational_plan.template_publish_check import publish_check

    return publish_check(db, user_id=author_id or tmpl.created_by, name=tmpl.name, description=tmpl.description or "",
                         tree=list(tmpl.tree or []), item_type=tmpl.item_type or "template")


@router.get("/templates/{template_id}/lineage", summary="Who wrote this template and who adapted it, original first")
def template_lineage(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.services.operational_plan.template_credit import lineage

    tmpl = _load_template_or_404(template_id, db)
    if not template_access.can_view(tmpl, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    return {"chain": lineage(db, template_id, viewer=current_user)}


class CreditLineRequest(BaseModel):
    show: bool


@router.put("/{plan_id}/credit-line", summary="Print the template credit at the end of the exported plan (off by default)")
def set_plan_credit_line(
    plan_id: UUID,
    body: CreditLineRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    plan = _check_plan_access(plan_id, current_user, db)
    plan.plan_metadata = {**(plan.plan_metadata or {}), "show_template_credit": bool(body.show)}
    flag_modified(plan, "plan_metadata")
    db.commit()
    return {"show": bool(body.show)}


@router.post("/templates/{template_id}/publish-check", summary="What stops this template from being shared")
def template_publish_check_endpoint(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tmpl = _load_template_or_404(template_id, db)
    _owner_or_admin(tmpl, current_user)
    return _check_template(db, tmpl, tmpl.created_by)


@router.post("/templates/{template_id}/share", summary="Set who can see this template (private / my office / everyone)")
def share_template(
    template_id: UUID,
    body: ShareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """The author publishes at once as a Community template; no review is needed. The publish check runs first and its errors
    stop the sharing (422 with the issues)."""
    tmpl = _load_template_or_404(template_id, db)
    _owner_or_admin(tmpl, current_user)
    if body.scope not in template_access.SCOPES:
        raise HTTPException(status_code=400, detail="scope must be private, office or public")
    if body.license not in template_access.LICENSES:
        raise HTTPException(status_code=400, detail="license must be cc_by, cc0 or view_only")
    org_id = None
    if body.scope != "private":
        check = _check_template(db, tmpl, tmpl.created_by)
        if not check["ok"]:
            raise HTTPException(
                status_code=422,
                detail={"code": "publish_check_failed", "message": "Fix these before sharing.", "issues": check["errors"]},
            )
        if body.scope == "office":
            author = db.get(User, tmpl.created_by) if tmpl.created_by else current_user
            org_id = getattr(author, "organization_id", None)
    try:
        template_lifecycle.share(db, tmpl, actor_id=current_user.id, scope=body.scope, license=body.license,
                                 organization_id=org_id)
    except TransitionError as e:
        raise _transition_error_to_http(e)
    return _commit_and_return(db, tmpl)


@router.put("/templates/{template_id}/tier", summary="Super admin: make a shared template Verified or Official")
def set_template_tier(
    template_id: UUID,
    body: TierRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    tmpl = _load_template_or_404(template_id, db)
    try:
        template_lifecycle.set_tier(db, tmpl, actor_id=current_user.id, tier=body.tier, note=body.note or "")
    except TransitionError as e:
        raise _transition_error_to_http(e)
    return _commit_and_return(db, tmpl)


@router.post(
    "/templates/{template_id}/submit", summary="Submit a template for publishing review"
)
def submit_template_for_approval(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Submit a draft/rejected template for super-admin review (owner, or any
    template designer / super admin). Runs the validation gate first."""
    tmpl = _load_template_or_404(template_id, db)
    is_privileged = current_user.role in (
        UserRole.TEMPLATE_DESIGNER,
        UserRole.SUPER_ADMIN,
    )
    if tmpl.created_by != current_user.id and not is_privileged:
        raise HTTPException(
            status_code=403, detail="You can only submit your own templates"
        )
    try:
        template_lifecycle.submit(db, tmpl, actor_id=current_user.id)
    except TransitionError as e:
        raise _transition_error_to_http(e)
    return _commit_and_return(db, tmpl)


@router.post(
    "/templates/{template_id}/review",
    summary="Super admin: approve (= publish) or reject a template",
)
def review_template(
    template_id: UUID,
    review: TemplateApprove,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    """One-click: ``approve`` validates + snapshots + publishes; ``reject``
    needs a note and sends the template back to the designer."""
    tmpl = _load_template_or_404(template_id, db)
    try:
        if review.action == "approve":
            template_lifecycle.approve_publish(
                db, tmpl, actor_id=current_user.id, note=review.note or ""
            )
        else:
            template_lifecycle.reject(
                db, tmpl, actor_id=current_user.id, note=review.note or ""
            )
    except TransitionError as e:
        raise _transition_error_to_http(e)
    return _commit_and_return(db, tmpl)


@router.post(
    "/templates/{template_id}/unpublish", summary="Super admin: unpublish a template"
)
def unpublish_template(
    template_id: UUID,
    body: TemplateLifecycleRequest = TemplateLifecycleRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    tmpl = _load_template_or_404(template_id, db)
    try:
        template_lifecycle.unpublish(
            db, tmpl, actor_id=current_user.id, note=body.note or ""
        )
    except TransitionError as e:
        raise _transition_error_to_http(e)
    return _commit_and_return(db, tmpl)


@router.post(
    "/templates/{template_id}/deprecate",
    summary="Super admin: deprecate a published template",
)
def deprecate_template(
    template_id: UUID,
    body: TemplateLifecycleRequest = TemplateLifecycleRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    tmpl = _load_template_or_404(template_id, db)
    try:
        template_lifecycle.deprecate(
            db,
            tmpl,
            actor_id=current_user.id,
            note=body.note or "",
            superseded_by_template_id=body.superseded_by_template_id,
        )
    except TransitionError as e:
        raise _transition_error_to_http(e)
    return _commit_and_return(db, tmpl)


@router.post(
    "/templates/{template_id}/retire", summary="Super admin: retire a template"
)
def retire_template(
    template_id: UUID,
    body: TemplateLifecycleRequest = TemplateLifecycleRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    tmpl = _load_template_or_404(template_id, db)
    try:
        result = template_lifecycle.retire(
            db, tmpl, actor_id=current_user.id, note=body.note or ""
        )
    except TransitionError as e:
        raise _transition_error_to_http(e)
    db.commit()
    db.refresh(tmpl)
    return {
        "template": TemplateResponse.model_validate(tmpl),
        "live_plan_count": result["live_plan_count"],
    }


@router.post(
    "/templates/{template_id}/validate",
    response_model=TemplateValidateResponse,
    summary="Run the template validation gate",
)
def validate_template_endpoint(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Validate a template on demand (owner, designer, or super admin)."""
    tmpl = _load_template_or_404(template_id, db)
    is_privileged = current_user.role in (
        UserRole.TEMPLATE_DESIGNER,
        UserRole.SUPER_ADMIN,
    )
    if tmpl.created_by != current_user.id and not is_privileged:
        raise HTTPException(status_code=403, detail="Access denied")
    result = validate_template(
        db,
        tmpl.tree or [],
        plan_kind=tmpl.plan_kind,
        for_publish=False,
        description=tmpl.description,
        is_system=bool(tmpl.is_system),
    )
    return TemplateValidateResponse(**result)


@router.get(
    "/templates/{template_id}/audit",
    response_model=List[TemplateAuditEntry],
    summary="Template lifecycle audit trail",
)
def get_template_audit(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tmpl = _load_template_or_404(template_id, db)
    is_privileged = current_user.role in (
        UserRole.TEMPLATE_DESIGNER,
        UserRole.SUPER_ADMIN,
    )
    if tmpl.created_by != current_user.id and not is_privileged:
        raise HTTPException(status_code=403, detail="Access denied")
    rows = (
        db.execute(
            select(OPTemplateAudit)
            .where(OPTemplateAudit.template_id == template_id)
            .order_by(OPTemplateAudit.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [TemplateAuditEntry.model_validate(r) for r in rows]


# ═══════════════════════════════════════════════════════════
# Plan kinds (stage x regime) — OP_MULTI_TEMPLATE_PLAN.md §3.2
# ═══════════════════════════════════════════════════════════


def _plan_kind_to_response(db: Session, k: OPPlanKind) -> PlanKindResponse:
    data = PlanKindResponse.model_validate(k).model_dump()
    data["effective_required_section_keys"] = effective_required_sections(db, k.key)
    return PlanKindResponse(**data)


@router.get(
    "/plan-kinds", response_model=List[PlanKindResponse], summary="List plan kinds"
)
def list_plan_kinds_endpoint(
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return [
        _plan_kind_to_response(db, k)
        for k in list_plan_kinds(db, active_only=active_only)
    ]


@router.put(
    "/plan-kinds/{key}",
    response_model=PlanKindResponse,
    summary="Super admin: update a plan kind",
)
def update_plan_kind_endpoint(
    key: str,
    body: PlanKindUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_template_publisher),
):
    kind = get_plan_kind(db, key)
    if kind is None:
        raise HTTPException(status_code=404, detail="Plan kind not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(kind, field, value)
    kind.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(kind)
    return _plan_kind_to_response(db, kind)


# ═══════════════════════════════════════════════════════════
# Plan <-> template link: pinned version, upgrade, kind suggestion (Phase 4)
# ═══════════════════════════════════════════════════════════


def _published_template_tree(db: Session, tmpl: OPTemplate) -> list:
    """The tree that is actually live: the is_published_snapshot version if one
    exists, otherwise the template's current tree."""
    snap = (
        db.execute(
            select(OPTemplateVersion)
            .where(
                OPTemplateVersion.template_id == tmpl.id,
                OPTemplateVersion.is_published_snapshot.is_(True),
            )
            .order_by(OPTemplateVersion.version.desc())
        )
        .scalars()
        .first()
    )
    return (snap.tree if snap else tmpl.tree) or []


@router.get(
    "/{plan_id}/template-status",
    response_model=PlanTemplateStatusResponse,
    summary="Is the plan's template newer than the pinned version?",
)
def get_plan_template_status(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    plan = _check_plan_access(plan_id, current_user, db)
    meta = plan.plan_metadata or {}
    tmpl_id = meta.get("template_id")
    if not tmpl_id:
        return PlanTemplateStatusResponse(has_template=False)

    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == tmpl_id)
    ).scalar_one_or_none()
    if not tmpl:
        return PlanTemplateStatusResponse(has_template=False)

    pinned = meta.get("template_version")
    latest = (
        tmpl.published_version if tmpl.status in ("published", "deprecated") else None
    )
    upgrade = bool(latest and pinned and latest > pinned)

    changelog: list[str] = []
    if upgrade:
        rows = (
            db.execute(
                select(OPTemplateVersion)
                .where(
                    OPTemplateVersion.template_id == tmpl.id,
                    OPTemplateVersion.version > pinned,
                    OPTemplateVersion.version <= latest,
                )
                .order_by(OPTemplateVersion.version.asc())
            )
            .scalars()
            .all()
        )
        changelog = [r.changelog for r in rows if r.changelog]

    return PlanTemplateStatusResponse(
        has_template=True,
        template_id=tmpl.id,
        template_name=tmpl.name,
        template_status=tmpl.status,
        pinned_version=pinned,
        latest_published_version=latest,
        upgrade_available=upgrade,
        changelog_since=changelog,
    )


@router.post(
    "/{plan_id}/template-upgrade",
    response_model=TemplateUpgradeResponse,
    summary="Adopt the latest published version of the plan's template",
)
def upgrade_plan_template(
    plan_id: UUID,
    body: TemplateUpgradeRequest = TemplateUpgradeRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """`confirm=false` returns the diff only (dry run). `confirm=true` merges the
    plan's authored content onto the new published structure and saves it; the
    pre-upgrade tree is stashed in plan_metadata.pre_upgrade_snapshot."""
    from ..services.operational_plan.template_upgrade import merge_plan_onto_template

    plan = _check_plan_access(plan_id, current_user, db)
    meta = plan.plan_metadata or {}
    tmpl_id = meta.get("template_id")
    if not tmpl_id:
        raise HTTPException(
            status_code=400, detail="This plan is not linked to a template"
        )

    tmpl = db.execute(
        select(OPTemplate).where(OPTemplate.id == tmpl_id)
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Linked template not found")
    if tmpl.status not in ("published", "deprecated"):
        raise HTTPException(
            status_code=409, detail="Linked template has no published version"
        )

    pinned = meta.get("template_version")
    latest = tmpl.published_version
    if pinned and latest and pinned >= latest:
        return TemplateUpgradeResponse(
            applied=False,
            from_version=pinned,
            to_version=latest,
            diff=TemplateUpgradeDiff(),
        )

    plan_tree = (plan.sections or {}).get("tree", [])
    new_tree = _published_template_tree(db, tmpl)
    merged, diff = merge_plan_onto_template(plan_tree, new_tree)

    if not body.confirm:
        return TemplateUpgradeResponse(
            applied=False,
            from_version=pinned,
            to_version=latest,
            diff=TemplateUpgradeDiff(**diff),
        )

    merged_nodes = _dict_list_to_tree(merged)
    recompute_numbers(merged_nodes, language=(meta.get("language", "NP")))
    sections = dict(plan.sections or {})
    sections["tree"] = _tree_to_dict_list(merged_nodes)
    plan.sections = sections
    flag_modified(plan, "sections")

    new_meta = dict(meta)
    new_meta["pre_upgrade_snapshot"] = {
        "tree": plan_tree,
        "from_version": pinned,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    new_meta["template_version"] = latest
    plan.plan_metadata = new_meta
    flag_modified(plan, "plan_metadata")
    plan.updated_at = datetime.now(timezone.utc)
    db.commit()

    return TemplateUpgradeResponse(
        applied=True,
        from_version=pinned,
        to_version=latest,
        diff=TemplateUpgradeDiff(**diff),
    )


def _suggest_stage(
    db: Session, calc: Calculation, regime: Optional[str]
) -> tuple[str, bool, str]:
    """(stage, has_prior_plan, reason) — `revision` when the same forest already
    has an approved OP of `regime`. Shared by GET /suggest-kind and, when the
    `op_auto_stage` flag is on, by plan creation."""
    q = select(OperationalPlan).where(
        OperationalPlan.status == "approved",
        OperationalPlan.calculation_id != calc.id,
    )
    if calc.forest_name:
        q = q.where(OperationalPlan.forest_name == calc.forest_name)
    prior = db.execute(q).scalars().all()
    if regime:
        prior = [
            p for p in prior if (p.plan_metadata or {}).get("template_regime") == regime
        ]
    if prior:
        return "revision", True, "An approved plan already exists for this forest."
    return "new", False, "No approved plan found for this forest."


@router.get(
    "/suggest-kind",
    response_model=SuggestKindResponse,
    summary="Advisory: which stage (new/revision) to pre-select",
)
def suggest_kind(
    calculation_id: UUID = Query(...),
    regime: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Best-effort: `revision` when the same forest already has an approved OP
    of the given regime, else `new`. Advisory unless the `op_auto_stage` flag
    is on (Phase 6)."""
    calc = db.execute(
        select(Calculation).where(Calculation.id == calculation_id)
    ).scalar_one_or_none()
    if not calc:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    stage, has_prior, reason = _suggest_stage(db, calc, regime)
    return SuggestKindResponse(
        suggested_stage=stage, has_prior_plan=has_prior, reason=reason
    )


def _tokenised_tree_from_plan(db: Session, plan: OperationalPlan):
    """The plan's document with the forest's own values turned back into tokens (see ``template_from_plan``).

    Returns ``(tree, report)``. The parent is the template version the plan was built from, so unedited sections come back as
    the template's own text."""
    from app.services.operational_plan.template_from_plan import build_template_tree, value_tokens
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY

    meta = plan.plan_metadata or {}
    parent_tree = None
    tid = meta.get("template_id")
    if tid:
        try:
            parent_id = UUID(str(tid))
        except ValueError:
            parent_id = None
        if parent_id:
            snap = None
            if meta.get("template_version") is not None:
                snap = db.execute(
                    select(OPTemplateVersion).where(
                        OPTemplateVersion.template_id == parent_id,
                        OPTemplateVersion.version == meta.get("template_version"),
                    )
                ).scalars().first()
            parent = snap or db.execute(select(OPTemplate).where(OPTemplate.id == parent_id)).scalar_one_or_none()
            parent_tree = list(parent.tree) if parent is not None and parent.tree else None
    resolver = VariableResolver(db, plan.calculation_id, plan)
    values = value_tokens(list(VARIABLE_REGISTRY.keys()), resolver.resolve_node_content)
    return build_template_tree((plan.sections or {}).get("tree", []), parent_tree, values)


def _parent_published_version(db: Session, parent_id) -> Optional[int]:
    parent = db.get(OPTemplate, parent_id) if parent_id else None
    return parent.published_version if parent else None


class SaveAsMyTemplate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = ""


@router.post(
    "/{plan_id}/save-as-my-template",
    summary="Save the edited plan as the caller's own private template (no forest figures)",
)
def save_plan_as_my_template(
    plan_id: UUID,
    body: SaveAsMyTemplate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """A private draft template made from the plan's document, owned by the caller, remembering the template it grew from.

    The forest's own values are turned back into tokens first, so the template can be used for any forest; the report lists the
    sections the author wrote or edited, where a figure typed by hand would still be there."""
    plan = _check_plan_access(plan_id, current_user, db)
    tree_list, report = _tokenised_tree_from_plan(db, plan)
    if not tree_list:
        raise HTTPException(status_code=400, detail="Plan has no document tree to save")
    meta = plan.plan_metadata or {}
    regime, stage = meta.get("template_regime"), meta.get("template_stage")
    kind_key = meta.get("template_kind") or resolve_kind_key(None, regime, stage)
    _kind = get_plan_kind(db, kind_key) if kind_key else None
    tree_list = ensure_cover_node(tree_list, _kind.cover_style if _kind else None)
    summaries = generate_template_summaries(tree_list)
    parent_id = None
    try:
        parent_id = UUID(str(meta["template_id"])) if meta.get("template_id") else None
    except ValueError:
        parent_id = None
    tmpl = OPTemplate(
        name=body.name.strip(),
        description=body.description or "",
        tree=tree_list,
        tags=[],
        sections_summary=summaries["sections_summary"],
        variables_summary=summaries["variables_summary"],
        is_system=False,
        status="draft",
        plan_kind=kind_key,
        plan_regime=regime,
        plan_stage=stage,
        source_template_id=parent_id,
        source_version=_parent_published_version(db, parent_id),
        # deliberately no source_calculation_id: a template must not point at a forest
        created_by=current_user.id,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return {"template": TemplateResponse.model_validate(tmpl), "report": report}


@router.post(
    "/{plan_id}/save-as-template", summary="Save current operational plan as a template"
)
def save_plan_as_template(
    plan_id: UUID,
    tmpl_data: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Save the current operational plan as a reusable template."""
    plan = _check_plan_access(plan_id, current_user, db)

    if tmpl_data.tree:
        tree_list = [n.model_dump() for n in tmpl_data.tree]
    else:
        # not the stored tree as it is: that one holds this forest's own values in place of the tokens
        tree_list, _report = _tokenised_tree_from_plan(db, plan)

    if not tree_list:
        raise HTTPException(status_code=400, detail="Plan has no document tree to save")

    if tmpl_data.is_system and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only super admins can create system templates"
        )

    kind_key = resolve_kind_key(
        tmpl_data.plan_kind, tmpl_data.plan_regime, tmpl_data.plan_stage
    )
    _kind = get_plan_kind(db, kind_key) if kind_key else None
    tree_list = ensure_cover_node(tree_list, _kind.cover_style if _kind else None)
    summaries = generate_template_summaries(tree_list)

    tmpl = OPTemplate(
        name=tmpl_data.name,
        description=tmpl_data.description or "",
        tree=tree_list,
        tags=list(tmpl_data.tags) if tmpl_data.tags else [],
        template_category=tmpl_data.template_category,
        sections_summary=summaries["sections_summary"],
        variables_summary=summaries["variables_summary"],
        is_system=tmpl_data.is_system,
        status="draft",
        plan_kind=kind_key,
        plan_regime=tmpl_data.plan_regime,
        plan_stage=tmpl_data.plan_stage,
        source_calculation_id=plan.calculation_id,
        created_by=current_user.id,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)

    return TemplateResponse.model_validate(tmpl)


@router.put(
    "/{plan_id}/update-default-template",
    deprecated=True,
    summary="[gone] Use POST /templates/system/adopt-from-plan",
)
def update_default_template(
    plan_id: UUID,
    req: UpdateDefaultTemplateRequest = UpdateDefaultTemplateRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Removed in T4 (OP_TEMPLATE_MANAGEMENT_PLAN.md §5). It copied a plan's
    *resolved* tree — the forest's actual numbers — straight into the System
    Template. Use ``POST /operational-plans/templates/system/adopt-from-plan``
    instead: it takes the plan's structure and restores ``{{tokens}}``."""
    raise HTTPException(
        status_code=410,
        detail={
            "code": "endpoint_gone",
            "message": (
                "This endpoint baked resolved values into the System Template. "
                "Use POST /operational-plans/templates/system/adopt-from-plan "
                "(structure + token restore + diff)."
            ),
        },
    )


@router.get("/template-categories", summary="List all template categories")
def list_categories(db: Session = Depends(get_db)):
    """List all template categories."""
    cats = (
        db.execute(select(OPTemplateCategory).order_by(OPTemplateCategory.sort_order))
        .scalars()
        .all()
    )
    return [CategoryResponse.model_validate(c) for c in cats]


@router.post(
    "/template-categories", summary="Create a template category (super admin only)"
)
def create_category(
    cat_data: CategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a template category (super admin only)."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only super admins can manage categories"
        )
    existing = db.execute(
        select(OPTemplateCategory).where(OPTemplateCategory.key == cat_data.key)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400, detail="Category with this key already exists"
        )
    cat = OPTemplateCategory(
        key=cat_data.key,
        label_ne=cat_data.label_ne,
        label_en=cat_data.label_en,
        description=cat_data.description or "",
        color=cat_data.color or "purple",
        sort_order=cat_data.sort_order,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return CategoryResponse.model_validate(cat)


@router.put(
    "/template-categories/{category_id}",
    summary="Update a template category (super admin only)",
)
def update_category(
    category_id: UUID,
    cat_data: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a template category (super admin only)."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only super admins can manage categories"
        )
    cat = db.execute(
        select(OPTemplateCategory).where(OPTemplateCategory.id == category_id)
    ).scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    if cat_data.label_ne is not None:
        cat.label_ne = cat_data.label_ne
    if cat_data.label_en is not None:
        cat.label_en = cat_data.label_en
    if cat_data.description is not None:
        cat.description = cat_data.description
    if cat_data.color is not None:
        cat.color = cat_data.color
    if cat_data.sort_order is not None:
        cat.sort_order = cat_data.sort_order
    db.commit()
    db.refresh(cat)
    return CategoryResponse.model_validate(cat)


@router.delete(
    "/template-categories/{category_id}",
    summary="Delete a template category (super admin only)",
)
def delete_category(
    category_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete a template category (super admin only)."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403, detail="Only super admins can manage categories"
        )
    cat = db.execute(
        select(OPTemplateCategory).where(OPTemplateCategory.id == category_id)
    ).scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    db.delete(cat)
    db.commit()
    return {"status": "ok", **i18n_success("success.category_deleted")}
