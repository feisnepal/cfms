"""Forest summary panel: the plan decisions (and, in later tasks, the summary and its export).

Access is `require_panel_access` (owner, a DFO of the owner's organisation, super admin). Nothing here starts a computation.
"""
from __future__ import annotations

import logging
from typing import Optional

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.user import User
from ..services import decision_registry as reg
from ..services import forest_decision_service as svc
from ..services import household_aggregate
from ..services import translation_service
from ..services.operational_plan import forest_summary as fsum
from ..services.operational_plan.data_collector import collect_all_op_data, read_op_data_cache
from ..utils.auth import get_current_active_user
from ..utils.authz import decisions_closed, require_panel_access
from ..utils.file_export import build_disposition

logger = logging.getLogger(__name__)

router = APIRouter()


class DecisionAnswer(BaseModel):
    choice: str
    scope: Optional[str] = None  # a block id, for per-block decisions
    value: Optional[str] = None  # the orientation, when choice is "custom"
    note: Optional[str] = None


@router.get("/{calculation_id}/decisions")
def get_decisions(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Every question with its answer (who, when) and the count still open. Reads stored data only."""
    calc = require_panel_access(db, calculation_id, current_user)
    return svc.list_decisions(db, calc)


@router.put("/{calculation_id}/decisions/{key}")
def put_decision(
    calculation_id: str,
    key: str,
    body: DecisionAnswer,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Record an answer. 423 once the DFO has approved the map (or while it is being calculated)."""
    calc = require_panel_access(db, calculation_id, current_user)
    if decisions_closed(calc):
        raise HTTPException(
            status_code=423,
            detail={
                "error": "decisions_locked",
                "message": "The map is approved or being calculated - decisions are read-only.",
                "code": "decisions.locked",
            },
            headers={"X-Locked-Reason": calc.map_lifecycle_status},
        )
    try:
        svc.save_decision(db, calc, current_user, key, body.choice, body.scope, body.value, body.note)
    except reg.DecisionError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return svc.list_decisions(db, calc)


def _unit_areas(db: Session, calculation_id) -> dict:
    """Name -> hectares of the forest's leaf units, from the forest_blocks table (the authoritative source)."""
    from ..services.forest_units import queries as unit_queries

    return {u.name: u.area_ha for u in unit_queries.units(db, calculation_id, unit_queries.View.LEAF) if u.name}


def _load_summary(db: Session, calc, area: str, lang: str, translate):
    """The summary dict for `calc` from the cached OP data, or ``None`` when nothing is cached (never collects)."""
    from ..models.op_data_cache import OpDataCache

    op = read_op_data_cache(db, str(calc.id))
    if op is None:
        return None
    summary = fsum.build_summary(op, household_aggregate.get_aggregate(db, calc.id), area, _unit_areas(db, calc.id))
    cached = db.query(OpDataCache.updated_at).filter(OpDataCache.calculation_id == calc.id).scalar()
    summary["basis"]["collected_at"] = cached.isoformat() if cached else None
    summary["verdict"] = fsum.build_verdict(summary.pop("verdict_inputs"), translate, lang)
    summary["state"] = "ready"
    summary["forest_name"] = (op.get("basic_info") or {}).get("forest_name")
    return summary


def _summary_response(db: Session, calc, area: str, lang: str):
    # Nothing collected since the last change: the panel asks the user (or itself) to POST .../refresh; a GET never collects.
    summary = _load_summary(db, calc, area, lang, translation_service.make_translator(db, lang))
    if summary is None:
        return {"state": "not_collected", "area": area, "tiles": [], "themes": [], "verdict": None, "basis": None}
    summary.pop("forest_name", None)
    return summary


@router.get("/{calculation_id}/forest-summary")
def get_forest_summary(
    calculation_id: str,
    area: str = Query(default=fsum.FOREST, pattern="^(forest|user_group)$"),
    lang: str = Query(default="en", pattern="^(en|ne)$"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """The forest-wide summary (verdict, headline tiles, themes) from the cached OP data. Reads stored data only."""
    calc = require_panel_access(db, calculation_id, current_user)
    return _summary_response(db, calc, area, lang)


@router.post("/{calculation_id}/forest-summary/refresh")
def refresh_forest_summary(
    calculation_id: str,
    area: str = Query(default=fsum.FOREST, pattern="^(forest|user_group)$"),
    lang: str = Query(default="en", pattern="^(en|ne)$"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Prepare the OP data once (seconds on a cold cache) and return the summary. The only call here that collects."""
    calc = require_panel_access(db, calculation_id, current_user)
    collect_all_op_data(db, str(calc.id))
    return _summary_response(db, calc, area, lang)


@router.get("/{calculation_id}/forest-summary/export")
def export_forest_summary(
    calculation_id: str,
    area: str = Query(default=fsum.FOREST, pattern="^(forest|user_group)$"),
    lang: str = Query(default="en", pattern="^(en|ne)$"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """The summary as a plain-text file (UTF-8 with a BOM so Notepad shows Nepali), for readers outside the workspace.
    Built from the same data, verdict and wording as the panel. 409 until the summary has been prepared."""
    calc = require_panel_access(db, calculation_id, current_user)
    translate = translation_service.make_translator(db, lang)
    summary = _load_summary(db, calc, area, lang, translate)
    if summary is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "summary.not_collected", "message": "The summary has not been prepared yet. Open the Forest summary first."},
        )
    forest_name = calc.forest_name or summary.get("forest_name") or "Forest"
    text = fsum.export_text(summary, svc.list_decisions(db, calc), translate, forest_name=forest_name,
                            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"), lang=lang)
    _, disposition = build_disposition(forest_name, "ForestSummary", "Report", "txt")
    return Response(content=("﻿" + text).encode("utf-8"), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": disposition})
