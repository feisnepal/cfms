"""NTFP inventory: the species to choose from and the sample-plot design (NTFP inventory page, phase 2).

The page itself is phase 5; these endpoints are what it reads. Everything is per forest (``calculation_id``) and follows the sampling API's
rule: the owner or a super admin.
"""
from typing import List, Optional
from uuid import UUID

import io
import os
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.idempotent_route import IdempotentRoute
from app.models.user import User
from app.services import ntfp_design as nd
from app.services import ntfp_design_service as svc
from app.services import ntfp_records_service as records
from app.utils.auth import get_current_user
from app.utils.authz import require_calculation_access

from ..middleware.rate_limit import WorkspaceRateLimiter, import_limiter

MAX_FORM_BYTES = 5 * 1024 * 1024
#: photos are taken in bursts at a plot: far more than the 5 a minute of a form import, still bounded
photo_limiter = WorkspaceRateLimiter(max_requests=30, window_seconds=60, name="ntfp_photo")

router = APIRouter(route_class=IdempotentRoute)


def _invalidate_op_cache(db: Session, calculation_id) -> None:
    """The plan's data (table 39, the NTFP narrative) reads the design and the records: any change to them must clear the forest's OP cache."""
    from app.models.op_data_cache import OpDataCache

    db.query(OpDataCache).filter(OpDataCache.calculation_id == calculation_id).delete(synchronize_session=False)


class SpeciesChoice(BaseModel):
    species_key: str
    plot_sqm: Optional[float] = Field(None, gt=0, description="override the profile's plot size (m2)")
    intensity_pct: Optional[float] = Field(None, gt=0, le=100, description="override the guideline's intensity (% of the area)")
    growth_class: Optional[str] = Field(None, description="needed only for a species without a method card")


class DesignRequest(BaseModel):
    species: List[SpeciesChoice] = Field(..., min_length=1, max_length=60)
    plot_shape: str = Field("square", pattern="^(square|circular)$")
    seed: Optional[int] = Field(None, ge=1, le=2**31 - 1, description="the same seed and inputs give the same plots")
    min_plots: int = Field(nd.MIN_PLOTS_PER_STRATUM, ge=1, le=50)


def _refuse(exc: svc.DesignError) -> HTTPException:
    status = {"no_geometry": 400, "has_records": 409, "no_design": 404, "harvest.nothing_planned": 409, "harvest.no_activity": 500, "mode_conflict": 409, "unknown_plot": 404, "unknown_photo": 404,
              "photo.empty": 400, "photo.wrong_type": 415, "photo.too_large": 413, "photo.too_many": 409}.get(exc.code, 422)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.get("/{calculation_id}/ntfp/species")
def list_species(
    calculation_id: UUID,
    q: Optional[str] = Query(None, max_length=80),
    with_card: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The NTFP profiles (the 30 priority species and the Annex-2 method cards) with their regulation price lines and, for this forest's
    size, the guideline's default plot size and intensity."""
    calc = require_calculation_access(db, str(calculation_id), current_user)
    area_ha = None
    try:
        strata = svc.forest_strata(db, calc)["strata"]
        area_ha = sum(g.area for g in strata.values()) / 10_000.0
    except svc.DesignError:
        pass  # no boundary yet: the catalogue is still useful, only the defaults are missing
    return {"forest_area_ha": area_ha, "species": svc.species_catalogue(db, area_ha, q, with_card)}


@router.post("/{calculation_id}/ntfp/design/preview")
def preview_design(
    calculation_id: UUID,
    body: DesignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lay the plots out without storing anything."""
    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        return svc.run(db, calc, [s.model_dump() for s in body.species], body.plot_shape, body.seed, body.min_plots)
    except svc.DesignError as exc:
        raise _refuse(exc)


@router.post("/{calculation_id}/ntfp/design")
def create_design(
    calculation_id: UUID,
    body: DesignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lay the plots out and store the design, replacing the forest's earlier one."""
    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        data = svc.run(db, calc, [s.model_dump() for s in body.species], body.plot_shape, body.seed, body.min_plots)
    except svc.DesignError as exc:
        raise _refuse(exc)
    try:
        svc.save(db, calc, current_user.id, data)
    except svc.DesignError as exc:
        db.rollback()
        raise _refuse(exc)
    _invalidate_op_cache(db, calc.id)
    db.commit()
    return svc.load(db, calc.id)


@router.get("/{calculation_id}/ntfp/design")
def get_design(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = require_calculation_access(db, str(calculation_id), current_user)
    return {"design": svc.load(db, calc.id)}


@router.delete("/{calculation_id}/ntfp/design")
def delete_design(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        removed = svc.delete(db, calc.id)
    except svc.DesignError as exc:
        db.rollback()
        raise _refuse(exc)
    _invalidate_op_cache(db, calc.id)
    db.commit()
    if removed:
        from app.services import ntfp_plot_extras as extras

        extras.remove_forest_photos(calc.id)   # the photo rows went with the plots; the files go now that the delete is committed
    return {"deleted": removed}


@router.get("/{calculation_id}/ntfp/form")
def download_form(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The Excel field form for this forest's design: one row per plot and species, the method card of each species, and a weights sheet."""
    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        data = records.form_bytes(db, calc)
    except svc.DesignError as exc:
        raise _refuse(exc)
    name = f"{(calc.forest_name or 'Forest').strip()}_NTFP_Form_{date.today():%Y%m%d}.xlsx"
    return StreamingResponse(
        io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=NTFP_Form.xlsx; filename*=UTF-8''{quote(name)}"},
    )


@router.post("/{calculation_id}/ntfp/upload")
def upload_form(
    calculation_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bring the filled form back. Any error and nothing is written: the answer lists every finding with its sheet and row."""
    import_limiter.check(current_user.id)
    calc = require_calculation_access(db, str(calculation_id), current_user)
    if os.path.splitext(file.filename or "")[1].lower() != ".xlsx":
        raise HTTPException(status_code=400, detail={"code": "file.wrong_type", "message": "Upload the .xlsx form from this page."})
    data = file.file.read(MAX_FORM_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail={"code": "file.empty", "message": "The file is empty."})
    if len(data) > MAX_FORM_BYTES:
        raise HTTPException(status_code=413, detail={"code": "file.too_large", "message": "The form is larger than 5 MB."})
    try:
        result = records.import_form(db, calc, current_user.id, data)
    except svc.DesignError as exc:
        raise _refuse(exc)
    if not result["ok"]:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "form.invalid", "message": "Nothing was imported: the form has mistakes.", "findings": result["findings"]})
    _invalidate_op_cache(db, calc.id)
    db.commit()
    return result


class WeightEntry(BaseModel):
    sample_no: Optional[int] = Field(None, ge=1, le=10_000)
    part_group: Optional[str] = Field(None, max_length=2)
    fresh_weight_g: Optional[float] = None
    dry_weight_g: Optional[float] = None
    notes: Optional[str] = Field(None, max_length=500)


class SpeciesEntry(BaseModel):
    species_key: str = Field(..., max_length=120)
    visit_date: Optional[str] = Field(None, max_length=10)
    count_total: Optional[int] = None
    count_mature: Optional[int] = None
    count_small: Optional[int] = None
    clumps: Optional[int] = None
    tillers: Optional[int] = None
    notes: Optional[str] = Field(None, max_length=500)
    weights: List[WeightEntry] = Field(default_factory=list, max_length=300)


class PlotEntryRequest(BaseModel):
    entries: List[SpeciesEntry] = Field(..., min_length=1, max_length=60)


@router.put("/{calculation_id}/ntfp/plots/{plot_number}/observations")
def put_plot_observations(
    calculation_id: UUID,
    plot_number: int,
    body: PlotEntryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Type in what was found in one sample plot (the map's bottom sheet). Same checks as the form; any error and nothing is written. A forest's records are
    either uploaded or entered this way, never both: 409 ``mode_conflict`` until the other kind is deleted."""
    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        result = records.save_plot(db, calc, current_user.id, plot_number, [e.model_dump() for e in body.entries])
    except svc.DesignError as exc:
        db.rollback()
        raise _refuse(exc)
    if not result["ok"]:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "plot.invalid", "message": "Nothing was saved: check the entries.", "findings": result["findings"]})
    _invalidate_op_cache(db, calc.id)
    db.commit()
    return result


class PresenceRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    accuracy_m: Optional[float] = Field(None, ge=0, le=100_000)


@router.post("/{calculation_id}/ntfp/plots/{plot_number}/presence")
def post_presence(
    calculation_id: UUID,
    plot_number: int,
    body: PresenceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The "I am here" check: compare the phone's position (and its accuracy) with the plot's and keep the verdict: at / far / uncertain. Never refuses the survey."""
    from app.services import ntfp_plot_extras as extras

    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        out = extras.record_presence(db, calc, plot_number, body.latitude, body.longitude, body.accuracy_m)
    except svc.DesignError as exc:
        db.rollback()
        raise _refuse(exc)
    db.commit()
    return out


@router.get("/{calculation_id}/ntfp/plots/extras")
def get_all_plot_extras(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per plot: the verdict of its last position check and its photo count (for the map)."""
    from app.services import ntfp_plot_extras as extras

    calc = require_calculation_access(db, str(calculation_id), current_user)
    return extras.all_extras(db, calc.id)


@router.get("/{calculation_id}/ntfp/plots/{plot_number}/extras")
def get_plot_extras(
    calculation_id: UUID,
    plot_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One plot's last position check and its photos."""
    from app.services import ntfp_plot_extras as extras

    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        return extras.plot_extras(db, calc.id, plot_number)
    except svc.DesignError as exc:
        raise _refuse(exc)


@router.post("/{calculation_id}/ntfp/plots/{plot_number}/photos")
def post_plot_photo(
    calculation_id: UUID,
    plot_number: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None, max_length=300),
    latitude: Optional[float] = Form(None, ge=-90, le=90),
    longitude: Optional[float] = Form(None, ge=-180, le=180),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A photo taken at the plot: JPEG, PNG or WebP (the bytes are checked, not the name), up to 10 MB and 10 a plot."""
    from app.services import ntfp_plot_extras as extras

    photo_limiter.check(current_user.id)
    calc = require_calculation_access(db, str(calculation_id), current_user)
    data = file.file.read(extras.MAX_PHOTO_BYTES + 1)
    try:
        out = extras.add_photo(db, calc, current_user.id, plot_number, file.filename or "photo", data, caption, latitude, longitude)
    except svc.DesignError as exc:
        db.rollback()
        raise _refuse(exc)
    db.commit()
    return out


@router.get("/{calculation_id}/ntfp/photos/{photo_id}")
def get_plot_photo(
    calculation_id: UUID,
    photo_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The photo file."""
    from app.services import ntfp_plot_extras as extras

    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        f = extras.photo_file(db, calc.id, photo_id)
    except svc.DesignError as exc:
        raise _refuse(exc)
    return FileResponse(f["path"], media_type=f["content_type"], headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/{calculation_id}/ntfp/photos/{photo_id}")
def delete_plot_photo(
    calculation_id: UUID,
    photo_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services import ntfp_plot_extras as extras

    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        extras.delete_photo(db, calc.id, photo_id)
    except svc.DesignError as exc:
        db.rollback()
        raise _refuse(exc)
    db.commit()
    return {"deleted": True}


@router.get("/{calculation_id}/ntfp/observations")
def get_records(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    calc = require_calculation_access(db, str(calculation_id), current_user)
    return records.list_records(db, calc.id)


@router.delete("/{calculation_id}/ntfp/observations")
def delete_records(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete every recorded count and weight of the forest (the design stays)."""
    calc = require_calculation_access(db, str(calculation_id), current_user)
    n = records.delete_records(db, calc.id)
    _invalidate_op_cache(db, calc.id)
    db.commit()
    return {"deleted": n}


@router.get("/{calculation_id}/ntfp/results")
def get_results(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Frequency, density, importance value, conversion factor, yield and stock per species, from the records uploaded so far."""
    from app.services import ntfp_analysis_service as analysis_svc

    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        return analysis_svc.results(db, calc)
    except svc.DesignError as exc:
        raise _refuse(exc)


class HarvestRow(BaseModel):
    species_key: str
    part_group: str = Field(..., min_length=1, max_length=2)
    annual_quantity: float = Field(..., ge=0, le=1e9)
    unit: str = Field("kg", pattern="^(kg|piece)$")
    weight_basis: str = Field("dry", pattern="^(fresh|dry)$")
    price_override: Optional[float] = Field(None, ge=0, le=1e7)
    notes: Optional[str] = Field(None, max_length=500)


class HarvestPlanRequest(BaseModel):
    rows: List[HarvestRow] = Field(..., max_length=500)


@router.get("/{calculation_id}/ntfp/harvest-plan")
def get_harvest_plan(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The surveyed (species, part) rows with their stock and rate, the owner's planned annual harvest of each, and the totals."""
    from app.services import ntfp_harvest_service as harvest

    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        return harvest.list_plan(db, calc)
    except svc.DesignError as exc:
        raise _refuse(exc)


@router.put("/{calculation_id}/ntfp/harvest-plan")
def put_harvest_plan(
    calculation_id: UUID,
    body: HarvestPlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the harvest plan. The cost-benefit analysis picks it up on its next re-populate."""
    from app.services import ntfp_harvest_service as harvest

    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        harvest.save_plan(db, calc, current_user.id, [r.model_dump() for r in body.rows])
        out = harvest.list_plan(db, calc)
    except svc.DesignError as exc:
        db.rollback()
        raise _refuse(exc)
    _invalidate_op_cache(db, calc.id)
    db.commit()
    return out


@router.post("/{calculation_id}/ntfp/harvest-plan/yearly-plan")
def harvest_plan_to_yearly_plan(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Make the yearly plan's NTFP collection line (total kg a year) unless the owner already has one."""
    from app.services import ntfp_harvest_service as harvest

    calc = require_calculation_access(db, str(calculation_id), current_user)
    try:
        out = harvest.to_yearly_plan(db, calc)
    except svc.DesignError as exc:
        db.rollback()
        raise _refuse(exc)
    _invalidate_op_cache(db, calc.id)
    db.commit()
    return out


@router.get("/{calculation_id}/ntfp/profiles/{species_key:path}")
def get_card(
    calculation_id: UUID,
    species_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One species' method card with every value and its source: the chosen value, and the other sources' values beside it."""
    from app.services import ntfp_card_service as cards

    require_calculation_access(db, str(calculation_id), current_user)
    out = cards.card(db, species_key)
    if out is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_species", "message": f"No NTFP profile named {species_key!r}."})
    return out


@router.get("/{calculation_id}/ntfp/sources")
def get_sources(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The documents method-card values come from, and the leads not yet read."""
    from app.services import ntfp_card_service as cards

    require_calculation_access(db, str(calculation_id), current_user)
    return {"sources": cards.sources(db)}


# ── the expert review of the provisional method cards: super admin only, and not tied to one forest ─────────────────────────────

def _require_super_admin(user: User) -> None:
    from app.models.user import UserRole

    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail={"code": "super_admin_only", "message": "Only a super admin reviews the method cards."})


class ReviewRow(BaseModel):
    species_key: str
    confirmed: bool = False
    growth_class: Optional[str] = None
    sampling_method: Optional[str] = None
    plot_min_sqm: Optional[float] = Field(None, ge=0)
    plot_max_sqm: Optional[float] = Field(None, ge=0)
    n_individuals_min: Optional[float] = Field(None, ge=0)
    n_individuals_max: Optional[float] = Field(None, ge=0)
    maturity: Optional[str] = Field(None, max_length=255)
    conversion_factor: Optional[float] = Field(None, ge=0, le=1)
    sample_fraction_pct: Optional[float] = Field(None, ge=0, le=100)
    aah_pct_min: Optional[float] = Field(None, ge=0, le=100)
    aah_pct_max: Optional[float] = Field(None, ge=0, le=100)
    procedure: Optional[str] = Field(None, max_length=2000)


class ReviewRequest(BaseModel):
    rows: List[ReviewRow] = Field(..., min_length=1, max_length=400)


@router.get("/ntfp-cards/review")
def get_review_queue(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The provisional cards waiting for a reviewer."""
    from app.services import ntfp_card_service as cards

    _require_super_admin(current_user)
    return {"cards": cards.review_queue(db)}


@router.post("/ntfp-cards/review")
def post_review(body: ReviewRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Confirm or correct cards. Each edit becomes an expert-confirmed value under a review source that names the reviewer; all or nothing."""
    from app.services import ntfp_card_service as cards

    _require_super_admin(current_user)
    reviewer = (current_user.full_name or current_user.email or "").strip()
    try:
        out = cards.apply_review(db, [r.model_dump(exclude_none=True) for r in body.rows], reviewer)
    except cards.ReviewError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": "review_invalid", "message": str(exc)})
    db.commit()
    return {**out, "remaining": len(cards.review_queue(db))}
