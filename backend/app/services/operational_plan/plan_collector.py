"""PlanCollector — per-unit operational-plan facts for the ``opsmap:*`` maps.

THEMATIC_MAP_VARIABLES_PLAN §3.4B / P5c. The analysis maps (``thememap:*``)
read the field inventory via ``data_collector``; the plan maps read the
*prescription* tables here:

    proposed_yearly_activities  (block_id / assign_to_all_blocks / year_numbers /
                                 default_quantity / default_yearly_budget)
    activity_year_details       (per-year quantity / budget overrides)
    activity_spatial_assignments (activity → block(s))
    potential_activities         (activity name / programme / unit / is_felling)

``per_unit(db, calc_id)`` → ``{block_name: {...}}`` keyed on **block name**
(same join key the engine already uses), with:

    felling_year         earliest plan year a felling activity touches the block
    felling_series       "Series N" grouping derived from felling_year
    prescribed_harvest   Σ quantity of felling activities on the block (all years)
    aah_ceiling          block AAH over the whole plan period (m³), from the FI
    harvest_vs_aah       prescribed_harvest ÷ aah_ceiling as a percentage
    budget_total         Σ yearly budget over every year each activity applies
    activity_count       distinct proposed activities touching the block
    working_circle       "production" | "protection"

Drawn features + the year axis (small multiples) land in P7.
"""

from __future__ import annotations

import logging
import math
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.constants import AAH_MULTIPLIER
from app.services.forest_units import queries as forest_unit_queries
from app.services.yearly_plan_rules import (
    effective_budget,
    effective_quantity,
    planned_years,
)

logger = logging.getLogger(__name__)

_DEFAULT_PLAN_YEARS = 10


def _block_index(db: Session, calc_id: UUID) -> dict[str, dict]:
    """``{unit_id_str: {name, area_ha, working_circle}}`` for the forest's units.

    The LEAF view (FS-1a.7): every unit that is not divided further. It used to select on the unit's
    depth being zero (top-level blocks only), so a compartment forest returned ``{}`` and every
    plan map / coupe table of a compartment forest came out empty.
    """
    return {
        str(u.id): {
            "name": (u.name or "").strip(),
            "area_ha": u.area_ha,
            "working_circle": u.working_circle,
        }
        for u in forest_unit_queries.units(db, calc_id, forest_unit_queries.View.LEAF)
    }


def _fi_aah_per_ha(db: Session, calc_id: UUID) -> dict[str, float]:
    """``{block_name: aah_m3_per_ha_per_year}`` computed the same way
    ``data_collector._block_row`` does (protection units → 0)."""
    from app.models.field_inventory import (
        FieldInventoryBlockSummary as _BS,
        FieldInventoryCalculation as _FC,
    )
    from app.models.forest_block import ForestBlock

    wc = {
        (nm or "").strip(): (w or "production")
        for nm, w in db.query(ForestBlock.name, ForestBlock.working_circle)
        .filter(ForestBlock.calculation_id == calc_id)
        .all()
    }
    out: dict[str, float] = {}
    q = (
        db.query(
            _BS.block_name,
            _BS.total_growing_stock_m3_per_ha,
            _BS.mai_percent,
            _BS.forest_condition,
        )
        .join(_FC, _BS.field_inventory_calculation_id == _FC.id)
        .filter(_FC.calculation_id == calc_id)
    )
    for bn, gs, mai_pct, cond in q.all():
        name = (bn or "").strip()
        if wc.get(name) == "protection":
            out[name] = 0.0
            continue
        gs = float(gs or 0)
        mai = gs * float(mai_pct or 0) / 100.0
        out[name] = round(mai * AAH_MULTIPLIER.get(cond or "Moderate", 60.0) / 100.0, 3)
    return out


def per_unit(db: Session, calc_id: UUID) -> dict[str, dict]:
    """Per-block plan facts, keyed by block name. Empty dict when no plan."""
    try:
        from app.models.yearly_activities import (
            ActivitySpatialAssignment,
            ActivityYearDetail,
            PotentialActivity,
            ProposedYearlyActivity,
        )
    except Exception:  # noqa: BLE001 -- model set optional in some builds
        return {}

    blocks = _block_index(db, calc_id)
    if not blocks:
        return {}

    pas = (
        db.query(ProposedYearlyActivity)
        .filter(ProposedYearlyActivity.calculation_id == calc_id)
        .all()
    )
    # No proposed activities → still return the block skeleton (working_circle
    # + zeros), so `opsmap:forest__working_circles` renders from geometry alone.
    if not pas:
        return {
            b["name"]: {
                "working_circle": b["working_circle"],
                "area_ha": b["area_ha"],
                "activity_count": 0,
                "budget_total": 0.0,
                "prescribed_harvest": 0.0,
                "felling_year": None,
                "felling_series": None,
                "aah_ceiling": 0.0,
                "harvest_vs_aah": None,
            }
            for b in blocks.values()
            if b["name"]
        }

    pot = {
        p.id: p
        for p in db.query(PotentialActivity).filter(
            PotentialActivity.id.in_({pa.potential_activity_id for pa in pas})
        )
    }
    year_details: dict[str, list] = {}
    for yd in db.query(ActivityYearDetail).filter(
        ActivityYearDetail.proposed_activity_id.in_({pa.id for pa in pas})
    ):
        year_details.setdefault(str(yd.proposed_activity_id), []).append(yd)
    spatial: dict[str, list] = {}
    for sa in db.query(ActivitySpatialAssignment).filter(
        ActivitySpatialAssignment.proposed_activity_id.in_({pa.id for pa in pas})
    ):
        spatial.setdefault(str(sa.proposed_activity_id), []).append(sa)

    # accumulate
    acc: dict[str, dict] = {
        b["name"]: {
            "working_circle": b["working_circle"],
            "area_ha": b["area_ha"],
            "activity_count": 0,
            "budget_total": 0.0,
            "prescribed_harvest": 0.0,
            "_felling_years": [],
        }
        for b in blocks.values()
        if b["name"]
    }
    all_names = list(acc)
    plan_years_seen: set[int] = set()

    for pa in pas:
        target_ids: set[str] = set()
        if pa.assign_to_all_blocks:
            target_ids = set(blocks)
        if pa.block_id:
            target_ids.add(str(pa.block_id))
        for sa in spatial.get(str(pa.id), []):
            if sa.assignment_type == "all_blocks":
                target_ids = set(blocks)
            elif sa.block_id:
                target_ids.add(str(sa.block_id))
        target_names = [
            blocks[t]["name"] for t in target_ids if t in blocks and blocks[t]["name"]
        ]
        if not target_names and pa.assign_to_all_blocks:
            target_names = all_names
        if not target_names:
            continue

        yd_by_year = {yd.year_number: yd for yd in year_details.get(str(pa.id), [])}
        # years by effective values (a real 0 / 0 year is NOT planned) — the same rule the OP
        # collector uses; ``year_numbers`` is no longer a source (YEARLY_ACTIVITIES plan F11)
        years = planned_years(pa.default_quantity, pa.default_yearly_budget, yd_by_year)
        if not years:
            continue
        plan_years_seen.update(years)

        p = pot.get(pa.potential_activity_id)
        is_fell = bool(getattr(p, "is_felling", False))

        for nm in target_names:
            rec = acc.get(nm)
            if rec is None:
                continue
            rec["activity_count"] += 1
            for y in years:
                yd = yd_by_year.get(y)
                budget = float(effective_budget(yd, pa.default_yearly_budget))
                rec["budget_total"] += budget
                if is_fell:
                    qty = float(effective_quantity(yd, pa.default_quantity))
                    rec["prescribed_harvest"] += qty
                    rec["_felling_years"].append(y)

    plan_years = max(plan_years_seen) if plan_years_seen else _DEFAULT_PLAN_YEARS
    period = max(1, plan_years // 3)
    aah_ph = _fi_aah_per_ha(db, calc_id)

    out: dict[str, dict] = {}
    for nm, rec in acc.items():
        fy = min(rec["_felling_years"]) if rec["_felling_years"] else None
        aah_ceiling = round((aah_ph.get(nm, 0.0)) * rec["area_ha"] * plan_years, 2)
        ph = round(rec["prescribed_harvest"], 2)
        out[nm] = {
            "working_circle": rec["working_circle"],
            "activity_count": rec["activity_count"],
            "budget_total": round(rec["budget_total"], 2),
            "prescribed_harvest": ph,
            "felling_year": fy,
            "felling_series": (f"श्रृंखला-{math.ceil(fy / period)}" if fy else None),
            "aah_ceiling": aah_ceiling,
            "harvest_vs_aah": (
                round(100.0 * ph / aah_ceiling, 1) if aah_ceiling else None
            ),
        }
    return out


# ── P7 — drawn features + the 1..10 year axis ───────────────────────────
def features(db: Session, calc_id: UUID, year=None, kind=None) -> list[dict]:
    """All drawn point/line/polygon features of the plan's activities, shaped
    for ``thematic_overlay._draw_activity_features`` (canonical ``kind``)."""
    try:
        from app.services.management_plan_docx.plan_map_service import (
            _get_activity_features,
        )
    except Exception:  # noqa: BLE001
        return []
    drawn = _get_activity_features(db, calc_id, year=year, kind=kind)
    return drawn + _stored_strips(db, calc_id, year=year, kind=kind)


def _stored_strips(db: Session, calc_id: UUID, year=None, kind=None) -> list[dict]:
    """The fire lines and river banks made in the sub-areas layer (``result_data['sub_areas']``, category ``fire_line`` /
    ``river_bank``), shaped like drawn features. A fire line is drawn as its centreline (the strip is a few metres wide, invisible at
    forest scale); a river bank as its polygon. They belong to no plan year, so a year-filtered map has none."""
    if year is not None or kind not in (None, "fire_line", "river_bank"):
        return []
    try:
        from shapely.geometry import shape

        from app.models.calculation import Calculation

        row = db.query(Calculation.result_data).filter(Calculation.id == calc_id).first()
        subs = ((row[0] or {}) if row else {}).get("sub_areas") or []
    except Exception:  # noqa: BLE001 -- a map without them is better than no map; the cause is logged
        logger.exception("plan_collector: could not read the stored fire lines / river banks")
        return []
    out: list[dict] = []
    for sa in subs:
        cat = sa.get("category")
        if cat not in ("fire_line", "river_bank") or (kind is not None and cat != kind):
            continue
        raw = sa.get("centerline") if cat == "fire_line" and sa.get("centerline") else sa.get("geometry")
        try:
            geom = shape(raw)
        except Exception:  # noqa: BLE001 -- one unreadable strip must not drop the rest
            logger.warning("plan_collector: strip %s has unreadable geometry", sa.get("id"), exc_info=True)
            continue
        if geom.is_empty:
            continue
        out.append({
            "geometry": geom,
            "feature_type": "line" if cat == "fire_line" else "polygon",
            "kind": cat,
            "raw_kind": cat,
            "label": sa.get("name") or "",
            "years": [],
            "activity_name": "",
        })
    return out


def by_year(db: Session, calc_id: UUID) -> dict[int, dict]:
    """``{y: {coupe_blocks, budget, activity_count, feature_kinds}}`` for
    ``y`` in ``1..plan_years`` — the basis for the year small-multiples."""
    try:
        from app.models.yearly_activities import (
            ActivityYearDetail,
            PotentialActivity,
            ProposedYearlyActivity,
        )
    except Exception:  # noqa: BLE001
        return {}

    blocks = _block_index(db, calc_id)
    pas = (
        db.query(ProposedYearlyActivity)
        .filter(ProposedYearlyActivity.calculation_id == calc_id)
        .all()
    )
    pot = {
        p.id: p
        for p in db.query(PotentialActivity).filter(
            PotentialActivity.id.in_({pa.potential_activity_id for pa in pas} or {None})
        )
    }
    yd_map: dict[str, dict[int, object]] = {}
    for yd in db.query(ActivityYearDetail).filter(
        ActivityYearDetail.proposed_activity_id.in_({pa.id for pa in pas} or {None})
    ):
        yd_map.setdefault(str(yd.proposed_activity_id), {})[yd.year_number] = yd

    planned_by_line: dict[str, list[int]] = {
        str(pa.id): planned_years(
            pa.default_quantity, pa.default_yearly_budget, yd_map.get(str(pa.id), {})
        )
        for pa in pas
    }
    seen_years: set[int] = set()
    for line_years in planned_by_line.values():
        seen_years.update(line_years)
    plan_years = max(seen_years) if seen_years else _DEFAULT_PLAN_YEARS
    plan_years = max(1, min(plan_years, 20))

    result: dict[int, dict] = {
        y: {
            "coupe_blocks": [],
            "budget": 0.0,
            "activity_count": 0,
            "feature_kinds": {},
        }
        for y in range(1, plan_years + 1)
    }

    for pa in pas:
        years = [y for y in planned_by_line[str(pa.id)] if 1 <= y <= plan_years]
        p = pot.get(pa.potential_activity_id)
        is_fell = bool(getattr(p, "is_felling", False))
        target_names: list[str] = []
        if pa.block_id and str(pa.block_id) in blocks:
            target_names = [blocks[str(pa.block_id)]["name"]]
        elif pa.assign_to_all_blocks:
            target_names = [b["name"] for b in blocks.values() if b["name"]]
        for y in years:
            slot = result.get(y)
            if slot is None:
                continue
            slot["activity_count"] += 1
            yd = yd_map.get(str(pa.id), {}).get(y)
            slot["budget"] += float(effective_budget(yd, pa.default_yearly_budget))
            if is_fell:
                for nm in target_names:
                    if nm not in slot["coupe_blocks"]:
                        slot["coupe_blocks"].append(nm)

    for y, feat in _features_by_year(db, calc_id, plan_years).items():
        if y in result:
            result[y]["feature_kinds"] = feat

    for y in result:
        result[y]["budget"] = round(result[y]["budget"], 2)
    return result


def _features_by_year(db: Session, calc_id: UUID, plan_years: int) -> dict[int, dict]:
    """``{y: {kind: count}}`` — drawn features scheduled that plan year."""
    feats = features(db, calc_id)
    out: dict[int, dict] = {}
    for f in feats:
        years = f.get("years") or list(range(1, plan_years + 1))
        for y in years:
            if 1 <= y <= plan_years:
                d = out.setdefault(y, {})
                k = f.get("kind") or "other"
                d[k] = d.get(k, 0) + 1
    return out


def qa_missing_map(db: Session, calc_id: UUID) -> dict[str, bool]:
    """``{block_name: True}`` for blocks that carry an activity with
    ``requires_map=True`` but no drawn feature — S19 QA map."""
    try:
        from app.models.yearly_activities import (
            ActivityDrawnFeature,
            PotentialActivity,
            ProposedYearlyActivity,
        )
    except Exception:  # noqa: BLE001
        return {}

    blocks = _block_index(db, calc_id)
    has_feature = {
        str(pid)
        for (pid,) in db.query(ActivityDrawnFeature.proposed_activity_id)
        .filter(
            ActivityDrawnFeature.calculation_id == calc_id,
            ActivityDrawnFeature.deleted_at.is_(None),
        )
        .distinct()
    }
    rows = (
        db.query(ProposedYearlyActivity, PotentialActivity)
        .join(
            PotentialActivity,
            ProposedYearlyActivity.potential_activity_id == PotentialActivity.id,
        )
        .filter(
            ProposedYearlyActivity.calculation_id == calc_id,
            PotentialActivity.requires_map.is_(True),
        )
        .all()
    )
    flagged: dict[str, bool] = {}
    for pa, _pot in rows:
        if str(pa.id) in has_feature:
            continue
        if pa.block_id and str(pa.block_id) in blocks:
            nm = blocks[str(pa.block_id)]["name"]
            if nm:
                flagged[nm] = True
        elif pa.assign_to_all_blocks:
            for b in blocks.values():
                if b["name"]:
                    flagged[b["name"]] = True
    return flagged
