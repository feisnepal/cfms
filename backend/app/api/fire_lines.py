"""Fire lines and river banks in the map workspace: the tick-list, the drawn strips and their widths (FIRELINE_RIVERBANK_PLAN.md).

Every candidate is created automatically (``services/fire_line_service`` / ``river_bank_service``); these routes are where the owner
unticks the ones that are not wanted, draws one of their own with a width for every segment, and re-widens one afterwards. The two
kinds share every handler; only the kind (category, keys, default width) differs.

* ``GET    /{id}/{kind}``                 the tick-list and the totals - stored data only, nothing is computed here
* ``POST   /{id}/{kind}/decisions``       tick / untick (a batch: select all, select none)
* ``POST   /{id}/{kind}/regenerate``      run the sync now
* ``POST   /{id}/{kind}/preview``         a drawn line + its widths -> the strip it would be; saves nothing
* ``POST   /{id}/{kind}``                 create the drawn line (``client_id`` makes a replay harmless)
* ``PATCH  /{id}/{kind}/{strip}/widths``  change the widths of an existing strip

with ``{kind}`` = ``fire-lines`` or ``river-banks``, and, for fire lines only:

* ``GET    /{id}/fire-lines/plan-options``  the activities a fire line can be planned with
* ``POST   /{id}/fire-lines/plan``          give the fire lines yearly-plan lines (km from the strip's own length)

Office work in the workspace, like the editing routes (see ``EXEMPT`` in ``scripts/check_idempotency_coverage.py``).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.calculation import Calculation
from ..models.user import User
from ..services import fire_line_service as fls
from ..utils.auth import get_current_active_user
from ..utils.authz import is_owner_or_admin

logger = logging.getLogger(__name__)

router = APIRouter()

Widths = Union[float, List[float]]


class Change(BaseModel):
    unit_key: str
    included: bool


class DecisionsBody(BaseModel):
    changes: List[Change] = Field(..., min_length=1)


class RegenerateBody(BaseModel):
    force: bool = True


class DrawnBody(BaseModel):
    centerline: Dict[str, Any] = Field(..., description="GeoJSON LineString")
    widths_m: Widths = Field(..., description="metres PER SIDE: one number, or one per segment")
    name: Optional[str] = None
    client_id: Optional[str] = Field(None, description="chosen by the client; a replay with the same id returns the first result")


class WidthsBody(BaseModel):
    widths_m: Widths


class PlanBody(BaseModel):
    potential_activity_id: int
    strip_ids: Optional[List[str]] = Field(None, description="only these fire lines; default all")
    include_roads: bool = Field(False, description="existing roads are skipped unless asked for")


_HTTP = {"not_found": 404, "no_forest": 409, "outside_forest": 422}


def _http(exc: fls.FireLineError) -> HTTPException:
    return HTTPException(status_code=_HTTP.get(exc.code, 400), detail={"code": exc.code, "message": str(exc)})


def _calc(db: Session, calculation_id: UUID, user: User, write: bool) -> Calculation:
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calculation not found")
    if not is_owner_or_admin(calc, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    if write and calc.structure_locked:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail={"code": "structure_locked", "message": "The forest structure is locked"})
    return calc


def _register(prefix: str, kind: fls.StripKind) -> None:
    """The six handlers of one kind, under ``/{id}/{prefix}``."""
    base = "/{calculation_id}/" + prefix

    def list_strips(calculation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
        calc = _calc(db, calculation_id, current_user, write=False)
        return fls.summarize(calc.result_data or {}, kind)

    def decide(calculation_id: UUID, body: DecisionsBody, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_active_user)):
        _calc(db, calculation_id, current_user, write=True)
        try:
            result = fls.apply_decisions(db, calculation_id, [c.model_dump() for c in body.changes], kind)
        except fls.FireLineError as exc:
            db.rollback()
            raise _http(exc) from exc
        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        return {"result": result, **fls.summarize(calc.result_data or {}, kind)}

    def regenerate(calculation_id: UUID, body: RegenerateBody = RegenerateBody(), db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_active_user)):
        _calc(db, calculation_id, current_user, write=True)
        result = fls.run_sync(kind, db, calculation_id, force=body.force)
        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        return {"result": result, **fls.summarize(calc.result_data or {}, kind)}

    def preview(calculation_id: UUID, body: DrawnBody, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_active_user)):
        _calc(db, calculation_id, current_user, write=False)
        try:
            return fls.preview_drawn(db, calculation_id, body.centerline, body.widths_m, kind)
        except fls.FireLineError as exc:
            raise _http(exc) from exc

    def create(calculation_id: UUID, body: DrawnBody, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_active_user)):
        _calc(db, calculation_id, current_user, write=True)
        try:
            return fls.create_drawn(db, calculation_id, body.centerline, body.widths_m, body.name, body.client_id, kind)
        except fls.FireLineError as exc:
            db.rollback()
            raise _http(exc) from exc

    def widths(calculation_id: UUID, strip_id: str, body: WidthsBody, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_active_user)):
        _calc(db, calculation_id, current_user, write=True)
        try:
            return fls.update_widths(db, calculation_id, strip_id, body.widths_m, kind)
        except fls.FireLineError as exc:
            db.rollback()
            raise _http(exc) from exc

    tag = kind.category
    router.add_api_route(base, list_strips, methods=["GET"], name=f"{tag}_list")
    router.add_api_route(base + "/decisions", decide, methods=["POST"], name=f"{tag}_decide")
    router.add_api_route(base + "/regenerate", regenerate, methods=["POST"], name=f"{tag}_regenerate")
    router.add_api_route(base + "/preview", preview, methods=["POST"], name=f"{tag}_preview")
    router.add_api_route(base, create, methods=["POST"], status_code=status.HTTP_201_CREATED, name=f"{tag}_create")
    router.add_api_route(base + "/{strip_id}/widths", widths, methods=["PATCH"], name=f"{tag}_widths")


# The fixed paths below must be registered BEFORE the generic /{strip_id}/widths pattern is ever matched; they do not collide
# (different methods / depth), but the fire-line plan routes are registered first to keep the order obvious.
@router.get("/{calculation_id}/fire-lines/plan-options")
def plan_options(calculation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    _calc(db, calculation_id, current_user, write=False)
    return {"activities": fls.plan_options(db)}


@router.post("/{calculation_id}/fire-lines/plan")
def plan_fire_lines(calculation_id: UUID, body: PlanBody, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_active_user)):
    """Give the fire lines a line in the yearly plan, starting at each strip's own length (km) so the plan and the map agree."""
    _calc(db, calculation_id, current_user, write=True)
    try:
        return fls.plan_fire_lines(db, calculation_id, body.potential_activity_id, body.strip_ids, body.include_roads)
    except fls.FireLineError as exc:
        db.rollback()
        raise _http(exc) from exc


_register("fire-lines", fls.FIRE_KIND)
_register("river-banks", fls.RIVER_KIND)
