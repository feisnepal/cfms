"""NTFP sampling design for a forest: what to sample, where, and the stored result (NTFP inventory, phase 2).

The maths is ``ntfp_design``; the species' plot sizes and the guideline's intensities are ``core/ntfp_methods`` and the table
``ntfp_method_profile``. This module joins them to a forest: the strata are the forest's leaf units clipped to the forest area (boundary
minus private land), or the whole forest area when it has no units.

Defaults, when the user names only a species: the plot size is the LARGER end of the guideline's range for the species (a trees' 100-500 m2
gives 500; herbs' 4-25 give 25) and the intensity the HIGHER end of Table 4's range for the forest's size. Both can be overridden per species.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from geoalchemy2.shape import from_shape
from shapely.geometry import Point, mapping
from sqlalchemy.orm import Session

from app.core.ntfp_methods import GROWTH_FORMS, below_guideline, intensity_pct
from app.core.ntfp_price import prices_for
from app.core.ntfp_schedule7 import designated_entries
from app.core.species_synonyms import canonical_key
from app.models.calculation import Calculation
from app.models.ntfp_method import NtfpMethodProfile, NtfpSamplePlot, NtfpSamplingDesign
from app.services import ntfp_design as nd
from app.services.forest_units import area_model
from app.services.forest_units import queries as unit_queries
from app.services.strip_geometry import Metric

logger = logging.getLogger(__name__)

WHOLE_FOREST = "forest"


class DesignError(ValueError):
    """The request cannot be designed (unknown species, no geometry, ...). ``code`` is a stable key for the client."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def forest_strata(db: Session, calc: Calculation) -> Dict[str, Any]:
    """``(metric, {name: area in metres})``: the leaf units clipped to the forest area, or the forest area as one stratum."""
    area = area_model.forest_area_geom(calc)
    if area is None or area.is_empty:
        raise DesignError("no_geometry", "The forest has no boundary yet.")
    metric = Metric.for_geometry(area)
    area_m = metric.to_m(area)
    strata: Dict[str, Any] = {}
    try:
        rows = unit_queries.unit_rows(db, calc.id, unit_queries.View.LEAF)
    except Exception:  # noqa: BLE001 -- a forest without unit rows is designed as one stratum
        logger.warning("[ntfp_design] unit lookup failed; one stratum", exc_info=True)
        rows = []
    from geoalchemy2.shape import to_shape
    for row in rows:
        if row.geometry is None:
            continue
        piece = metric.to_m(to_shape(row.geometry)).intersection(area_m)
        if piece.is_empty or piece.area <= 0:
            continue
        name = (row.block_name or row.name or str(row.id)).strip()
        strata[name] = piece if name not in strata else strata[name].union(piece)
    if not strata:
        strata[WHOLE_FOREST] = area_m
    return {"metric": metric, "strata": strata}


def _profile_rows(db: Session, keys: List[str]) -> Dict[str, NtfpMethodProfile]:
    rows = db.query(NtfpMethodProfile).filter(NtfpMethodProfile.species_key.in_(keys), NtfpMethodProfile.is_active.is_(True)).all()
    return {r.species_key: r for r in rows}


def _resolve_key(key: str) -> str:
    """A species named by any of its Latin synonyms resolves to the canonical key (``np:`` keys are Nepali names and stay as they are)."""
    key = key.strip()
    return key if key.startswith("np:") or not key else (canonical_key(key) or key)


def build_specs(db: Session, requested: List[dict], forest_area_ha: float) -> List[nd.SpeciesSpec]:
    """``[{species_key, plot_sqm?, intensity_pct?, growth_class?}]`` -> specs. A species with no method card needs its growth class (and
    then takes the guideline's plot size for it); one with a card takes the card's."""
    keys = [_resolve_key(str(r.get("species_key") or "")) for r in requested]
    profiles = _profile_rows(db, keys)
    specs: List[nd.SpeciesSpec] = []
    for r in requested:
        key = _resolve_key(str(r.get("species_key") or ""))
        prof = profiles.get(key)
        if prof is None:
            raise DesignError("unknown_species", f"No NTFP profile named {key!r}.")
        growth = r.get("growth_class") or prof.growth_class
        if growth not in GROWTH_FORMS:
            raise DesignError("growth_class_needed", f"{prof.nepali_name} has no method card: choose its growth class.")
        plot = r.get("plot_sqm")
        if plot is None:
            plot = float(prof.plot_max_sqm) if prof.plot_max_sqm is not None else GROWTH_FORMS[growth][2]
        pct = r.get("intensity_pct")
        if pct is None:
            pct = intensity_pct(growth, forest_area_ha)[1]
        if float(plot) <= 0 or float(pct) <= 0 or float(pct) > 100:
            raise DesignError("bad_number", f"Plot size and intensity must be positive (intensity at most 100 %): {prof.nepali_name}.")
        specs.append(nd.SpeciesSpec(species_key=key, plot_sqm=float(plot), intensity_pct=float(pct), growth_class=growth, label=prof.nepali_name))
    return specs


def run(db: Session, calc: Calculation, requested: List[dict], shape: str = "square", seed: Optional[int] = None,
        min_plots: int = nd.MIN_PLOTS_PER_STRATUM) -> Dict[str, Any]:
    """Compute a design (nothing is stored). Returns the result as plain data with WGS84 geometry."""
    if not requested:
        raise DesignError("no_species", "Choose at least one species.")
    ctx = forest_strata(db, calc)
    metric, strata = ctx["metric"], ctx["strata"]
    forest_ha = sum(g.area for g in strata.values()) / 10_000.0
    specs = build_specs(db, requested, forest_ha)
    try:
        result = nd.design(strata, specs, seed=seed, shape=shape, min_plots=min_plots)
    except ValueError as exc:
        raise DesignError("bad_request", str(exc)) from exc
    data = _to_data(metric, result, shape, min_plots, forest_ha)
    for sp in data["species"]:   # a species surveyed more lightly than the guideline allows is marked, so the plan can say so
        sp["below_guideline"] = below_guideline(sp["growth_class"], forest_ha, float(sp["intensity_pct"]))
    return data


def _to_data(metric: Metric, result: nd.DesignResult, shape: str, min_plots: int, forest_ha: float) -> Dict[str, Any]:
    plots = []
    for p in result.plots:
        pt = metric.to_wgs(Point(p.x, p.y))
        plots.append({"plot_number": p.number, "stratum": p.stratum, "transect": p.transect, "longitude": pt.x, "latitude": pt.y,
                      "species_keys": list(p.species_keys)})
    lines = []
    for s in result.strata:
        for i, ln in enumerate(s.transects, 1):
            lines.append({"type": "Feature", "geometry": mapping(metric.to_wgs(ln)), "properties": {"stratum": s.name, "transect": i}})
    return {
        "plot_shape": shape, "seed": result.seed, "min_plots": min_plots, "forest_area_ha": round(forest_ha, 4),
        "species": result.species, "layout": result.layout, "warnings": result.warnings, "plots": plots,
        "strata": [{"name": s.name, "area_ha": round(s.area_ha, 4), "plots_wanted": s.plots_wanted, "plots_laid": s.plots_laid,
                    "spacing_m": round(s.spacing_m, 2), "warnings": s.warnings} for s in result.strata],
        "transects": {"type": "FeatureCollection", "features": lines},
    }


def _refuse_if_recorded(db: Session, design: NtfpSamplingDesign) -> None:
    """Replacing or deleting a design deletes its plots, and with them every count and weight recorded in them. Refuse while any exist."""
    from app.models.ntfp_method import NtfpObservation

    n = (db.query(NtfpObservation.id).join(NtfpSamplePlot, NtfpObservation.plot_id == NtfpSamplePlot.id)
         .filter(NtfpSamplePlot.design_id == design.id).count())
    if n:
        raise DesignError("has_records", f"This design has {n} recorded observations. Delete the records first (they would be lost with the plots).")


def save(db: Session, calc: Calculation, user_id, data: Dict[str, Any]) -> NtfpSamplingDesign:
    """Store a computed design, replacing the forest's earlier one. The caller commits."""
    old = db.query(NtfpSamplingDesign).filter(NtfpSamplingDesign.calculation_id == calc.id).first()
    if old is not None:
        _refuse_if_recorded(db, old)
        db.delete(old)
        db.flush()
    row = NtfpSamplingDesign(
        calculation_id=calc.id, created_by=user_id, plot_shape=data["plot_shape"], seed=data["seed"], min_plots=data["min_plots"],
        species=data["species"], layout=data["layout"], strata=data["strata"], transects=data["transects"], warnings=data["warnings"],
    )
    db.add(row)
    db.flush()
    for p in data["plots"]:
        db.add(NtfpSamplePlot(
            design_id=row.id, plot_number=p["plot_number"], stratum=p["stratum"], transect=p["transect"],
            location=from_shape(Point(p["longitude"], p["latitude"]), srid=4326), species_keys=p["species_keys"],
        ))
    return row


def load(db: Session, calc_id: UUID) -> Optional[Dict[str, Any]]:
    """The stored design in the same shape :func:`run` returns, or None."""
    from geoalchemy2.shape import to_shape

    row = db.query(NtfpSamplingDesign).filter(NtfpSamplingDesign.calculation_id == calc_id).first()
    if row is None:
        return None
    plots = db.query(NtfpSamplePlot).filter(NtfpSamplePlot.design_id == row.id).order_by(NtfpSamplePlot.plot_number).all()
    out = []
    for p in plots:
        pt = to_shape(p.location)
        out.append({"plot_number": p.plot_number, "stratum": p.stratum, "transect": p.transect, "longitude": pt.x, "latitude": pt.y,
                    "species_keys": list(p.species_keys or [])})
    return {
        "id": str(row.id), "plot_shape": row.plot_shape, "seed": row.seed, "min_plots": row.min_plots, "species": row.species,
        "layout": row.layout, "strata": row.strata, "transects": row.transects, "warnings": row.warnings, "plots": out,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def delete(db: Session, calc_id: UUID) -> bool:
    row = db.query(NtfpSamplingDesign).filter(NtfpSamplingDesign.calculation_id == calc_id).first()
    if row is None:
        return False
    _refuse_if_recorded(db, row)
    db.delete(row)
    return True


def species_catalogue(db: Session, forest_area_ha: Optional[float] = None, query: Optional[str] = None, with_card: bool = False) -> List[dict]:
    """The profiles a user picks from, each with its regulation price lines and (given the forest's area) the guideline's default plot size
    and intensity."""
    q = db.query(NtfpMethodProfile).filter(NtfpMethodProfile.is_active.is_(True))
    if with_card:
        q = q.filter(NtfpMethodProfile.has_method_card.is_(True))
    if query:
        like = f"%{query.strip()}%"
        q = q.filter((NtfpMethodProfile.nepali_name.ilike(like)) | (NtfpMethodProfile.scientific_name.ilike(like)))
    from app.services import ntfp_card_service as cards

    extra = cards.chosen_by_species(db, ("aah_pct", "season"))
    out = []
    for r in q.order_by(NtfpMethodProfile.priority_serial.is_(None), NtfpMethodProfile.priority_serial, NtfpMethodProfile.nepali_name).all():
        entries = designated_entries(r.regulation_name) if r.regulation_name else []
        default_plot = default_pct = None
        if r.growth_class in GROWTH_FORMS:
            default_plot = float(r.plot_max_sqm) if r.plot_max_sqm is not None else GROWTH_FORMS[r.growth_class][2]
            if forest_area_ha is not None:
                default_pct = intensity_pct(r.growth_class, forest_area_ha)[1]
        out.append({
            "card_status": r.card_status, "aah": [v for v in extra.get(r.species_key, []) if v["field"] == "aah_pct"],
            "season": [v for v in extra.get(r.species_key, []) if v["field"] == "season"],
            "species_key": r.species_key, "scientific_name": r.scientific_name, "aliases": r.aliases or [], "nepali_name": r.nepali_name, "priority_serial": r.priority_serial,
            "has_method_card": r.has_method_card, "growth_class": r.growth_class, "life_form_ne": r.life_form_ne, "part_ne": r.part_ne,
            "part_groups": r.part_groups or [], "sampling_method": r.sampling_method,
            "plot_min_sqm": float(r.plot_min_sqm) if r.plot_min_sqm is not None else None,
            "plot_max_sqm": float(r.plot_max_sqm) if r.plot_max_sqm is not None else None,
            "altitude_min_m": r.altitude_min_m, "altitude_max_m": r.altitude_max_m,
            "conversion_factor": float(r.conversion_factor) if r.conversion_factor is not None else None,
            "regulation": [{"group": e["group"], "group_ne": e["group_ne"], "price": e["price"], "unit": e["unit"]} for e in entries],
            # per part harvested: Schedule-7 where it has a line, otherwise an estimate that says so (core/ntfp_price.py)
            "prices": prices_for(r.species_key, r.scientific_name, r.regulation_name, r.part_groups, r.parts_used_ne),
            "default_plot_sqm": default_plot, "default_intensity_pct": default_pct,
        })
    return out
