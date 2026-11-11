"""Build and cache the per-forest SFM classification block (P2).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §3.5 / §5 P2.

:func:`build_sfm` iterates the forest's leaf units (``forest_blocks`` — read
fresh, never the stale ``result_data['blocks']`` array), classifies each
(``zone_classifier`` → ``species_assemblage`` → ``forest_type_classifier``),
carries forward any per-block ``override_type_no``, and writes
``calculation.result_data['sfm']`` the SQLAlchemy-safe way. Prescription / yield
/ orientation / felling series are left ``None`` here — P3 fills them.

Cache key = ``params_hash`` + an ``input_token`` (geometry version + inventory
completion times). :func:`invalidate_sfm` drops the block so the next
:func:`get_sfm` rebuilds — called from the analysis / field-inventory pipelines
when geometry or inventory changes.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.services.forest_units import queries as forest_unit_queries
from app.core.constants import SFM_MIN_PLOTS_PER_BLOCK
from app.services.sustainable_fm.block_status import (
    INVENTORY_MISSING,
    LAND_CLASSES,
    NON_FOREST,
    PROVISIONAL,
    block_state,
)
from app.services.sustainable_fm.forest_type_classifier import classify
from app.services.sustainable_fm.orientation import ORIENTATION_LABEL_NE
from app.services.sustainable_fm.orientation import propose as orientation_propose
from app.services.sustainable_fm.prescription import build_card, load_prescriptions
from app.services.sustainable_fm.sfm_config import (
    SfmParams,
    params_hash,
    resolve_params,
)
from app.services.sustainable_fm.sfm_narration import all_blocks as narration_all
from app.services.sustainable_fm.sampling_defaults import sfm_sampling_plan
from app.services.sustainable_fm.species_assemblage import (
    SfmBlockInputs,
    resolve_block_inputs,
)
from app.services.sustainable_fm.yield_regulation import build_series
from app.services.sustainable_fm.zone_classifier import (
    ZoneResult,
    classify_block,
    classify_block_with_override,
)

logger = logging.getLogger(__name__)

SFM_RESULT_KEY = "sfm"
SFM_USER_KEY = "sfm_user"
SFM_BLOCK_VERSION = 1


# ─────────────────────────────────────────────────────────────────────────────
# Change detection
# ─────────────────────────────────────────────────────────────────────────────
def _input_token(calc: Calculation, db: Session) -> str:
    """A cheap signature of everything ``build_sfm`` reads *except* its own
    output: the geometry clock + the latest stem-mapping / field-inventory
    completion timestamps."""
    geo = getattr(calc, "geometry_version", 0) or 0
    row = db.execute(
        text(
            "SELECT "
            "(SELECT max(completed_at) FROM inventory_calculations "
            "  WHERE calculation_id = :cid), "
            "(SELECT max(completed_at) FROM field_inventory_calculations "
            "  WHERE calculation_id = :cid)"
        ),
        {"cid": str(calc.id)},
    ).first()
    stem = row[0].isoformat() if row and row[0] else "-"
    fi = row[1].isoformat() if row and row[1] else "-"
    return f"g{geo}|s{stem}|f{fi}"


def _leaf_units(calc: Calculation, db: Session) -> list[ForestBlock]:
    """Operable units: every unit of this forest that is not divided further (the leaf view of
    ``forest_units`` - leaf blocks / compartments / sub-units)."""
    return forest_unit_queries.unit_rows(db, calc.id, forest_unit_queries.View.LEAF)


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation
# ─────────────────────────────────────────────────────────────────────────────
def _inputs_dict(inp: SfmBlockInputs) -> dict[str, Any]:
    d = dataclasses.asdict(inp)  # SpeciesShare lists become plain dicts
    return d


def _zone_dict(z) -> dict[str, Any]:
    return {
        "sfm_zone": z.sfm_zone,
        "inner_terai": z.inner_terai,
        "dom_phys": z.dom_phys,
        "slope_band": z.slope_band,
        "slope_band_area_pct": {str(k): v for k, v in z.slope_band_area_pct.items()},
        "mean_altitude_m": z.mean_altitude_m,
    }


# Degree ranges for the 1-4 slope band scale -- mirrors
# slope_vectorize.BAND_LABELS (duplicated, not imported, to keep this a
# narration-only concern with no dependency on the vectorization module).
_BAND_LABEL: dict[int, tuple[str, str]] = {
    1: ("< १९°", "< 19°"),
    2: ("१९–३१°", "19–31°"),
    3: ("३१–४५°", "31–45°"),
    4: ("> ४५°", "> 45°"),
}
# Mirrors forest_type_classifier._ZONE_NE / _GROUP_NE (private there, small
# enough to duplicate rather than export for one caller).
_ZONE_LABEL_NE = {
    "LOWLAND_SAL": "तराई/चुरे",
    "HILL": "पहाड",
    "TEMPERATE": "शितोष्ण",
    "HIGH_MOUNTAIN": "उच्च पहाड",
}
_GROUP_LABEL_NE = {
    "SAL": "साल",
    "SISSOO_KHAIR": "सिसौ/खयर",
    "RIVERINE_ASSOC": "नदीतटीय प्रजाति",
    "PINE_ROX": "खोटे सल्ला",
    "PINE_WALL": "गोब्रे सल्ला",
    "PINE_PATULA": "पाटे सल्ला",
    "HILL_BROADLEAF": "पहाडी चौडापाते",
    "TEMPERATE_BROADLEAF": "शितोष्ण चौडापाते",
    "TEMPERATE_CONIFER": "शितोष्ण कोणधारी",
}


def _full_orientation_reason(
    b: dict[str, Any], row, justification: dict[str, str]
) -> tuple[str, str]:
    """Assemble the complete, auditable reasoning chain behind this block's
    suggested orientation: dominant species/data source -> zone + altitude ->
    slope band -> forest type (by name, not just a number) + its base
    orientation -> the specific rule that produced the final value (from
    ``orientation.propose()``'s own justification). Owner request,
    2026-09-15 ("we need every detail... the logic... the decision") -- a
    one-clause justification wasn't enough to audit a Production vs
    Conservation split at a glance."""
    zone = b.get("_zone") or {}
    inputs = b.get("inputs") or {}
    type_no = b.get("effective_type_no")

    species = inputs.get("dominant_group")
    species_ne = _GROUP_LABEL_NE.get(species, species) if species else None
    dominant_species = inputs.get("dominant_species") or []
    top_species = dominant_species[0] if dominant_species else None
    share_pct = top_species.get("share_pct") if isinstance(top_species, dict) else None

    zone_key = zone.get("sfm_zone")
    zone_ne = _ZONE_LABEL_NE.get(zone_key, zone_key or "अज्ञात")
    alt = zone.get("mean_altitude_m")

    band = zone.get("slope_band")
    band_ne, band_en = _BAND_LABEL.get(band, ("अज्ञात", "unknown"))

    name_ne = getattr(row, "name_ne", None) or ""
    name_en = getattr(row, "name_en", None) or ""
    base = getattr(row, "orientation", None) or "Production"

    if species and share_pct is not None:
        species_clause_ne = f"{species_ne} प्रधान ({share_pct:.0f}%)"
        species_clause_en = f"{species} dominant ({share_pct:.0f}%)"
    elif species:
        species_clause_ne = f"{species_ne} प्रधान"
        species_clause_en = f"{species} dominant"
    else:
        species_clause_ne = "प्रजाति डेटा उपलब्ध छैन"
        species_clause_en = "no species data"

    source = inputs.get("source")
    source_clause_ne = {
        "stem_mapping": "पूर्ण गणना",
        "field_inventory": "क्षेत्र सूची",
        "prior": "प्रारम्भिक अनुमान",
    }.get(source, source or "अज्ञात स्रोत")
    source_clause_en = {
        "stem_mapping": "full census",
        "field_inventory": "field inventory",
        "prior": "prior estimate",
    }.get(source, source or "unknown source")

    zone_clause_ne = f"{zone_ne} क्षेत्र" + (
        f" (उचाइ {alt:.0f}मी)" if alt is not None else ""
    )
    zone_clause_en = f"{zone_key or 'unknown'} zone" + (
        f" (alt. {alt:.0f}m)" if alt is not None else ""
    )

    slope_clause_ne = f"भिरालो वर्ग {band} ({band_ne})" if band else "भिरालो अज्ञात"
    slope_clause_en = f"slope band {band} ({band_en})" if band else "slope unknown"

    base_label_ne = ORIENTATION_LABEL_NE.get(base, base)
    type_clause_ne = f"सि.नं. {type_no} — {name_ne} (आधार: {base_label_ne})"
    type_clause_en = f"type {type_no} — {name_en} (base: {base})"

    full_ne = (
        f"{species_clause_ne} ({source_clause_ne}) · {zone_clause_ne} · "
        f"{slope_clause_ne} · {type_clause_ne} → {justification['justification_ne']}"
    )
    full_en = (
        f"{species_clause_en} ({source_clause_en}) · {zone_clause_en} · "
        f"{slope_clause_en} · {type_clause_en} → {justification['justification_en']}"
    )
    return full_ne, full_en


# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────
def _baseline_zone(
    unit: ForestBlock, wkt: str, db: Session, params: SfmParams
) -> ZoneResult:
    """Zone provider for the immutable **baseline** — raster-only, unchanged."""
    return classify_block(wkt, db, params)


def _user_zone(
    unit: ForestBlock, wkt: str, db: Session, params: SfmParams
) -> ZoneResult:
    """Zone provider for the **user** variant: use the workspace's manual
    ``dominant_slope_band`` when set, otherwise fall back to the raster exactly
    like the baseline — so the diff is only the user's own edits."""
    band = getattr(unit, "dominant_slope_band", None)
    if band is None:
        return classify_block(wkt, db, params)
    return classify_block_with_override(wkt, db, params, int(band))


def _build(
    calc: Calculation,
    db: Session,
    *,
    params: SfmParams,
    h: str,
    token: str,
    result_key: str,
    zone_provider,
    force: bool,
) -> dict[str, Any]:
    """The shared dual-variant SFM build (SV-1.2).

    ``zone_provider(unit, wkt, db, params) -> ZoneResult`` decides raster vs
    manual per block; ``result_key`` is ``SFM_RESULT_KEY`` (baseline) or
    ``SFM_USER_KEY`` (user variant). The user blob carries a ``|user``-suffixed
    ``input_token`` so the two caches never cross-hit. Per-block overrides are
    single-sourced in the baseline blob: the user variant builds its carry from
    the baseline blocks first (SV-1.4), so SFM-tab PATCH overrides reach it
    identically. Writes + commits when it rebuilds.
    """
    rd = calc.result_data or {}
    cached = rd.get(result_key)
    cache_token = token if result_key == SFM_RESULT_KEY else f"{token}|user"
    if (
        not force
        and isinstance(cached, dict)
        and cached.get("params_hash") == h
        and cached.get("input_token") == cache_token
    ):
        return cached

    carry = {
        b.get("block_name"): b
        for b in (cached.get("blocks", []) if isinstance(cached, dict) else [])
        if isinstance(b, dict)
    }
    if result_key == SFM_USER_KEY:
        # SV-1.4 — overrides are single-sourced in the baseline blob: the SFM-tab
        # PATCH handler (`patch_block`) writes them there and nowhere else, so the
        # user variant must carry the same overrides forward (baseline wins). A
        # user-variant first build therefore inherits existing SFM-tab overrides
        # instead of starting from an empty carry.
        base = rd.get(SFM_RESULT_KEY)
        if isinstance(base, dict):
            for b in base.get("blocks", []):
                name = (b.get("block_name") or "").strip()
                if name:
                    carry[name] = b

    zone_by_block: dict[str, Any] = {}
    blocks_out: list[dict[str, Any]] = []
    unit_by_name: dict[str, ForestBlock] = {}
    for unit in _leaf_units(calc, db):
        wkt = db.execute(
            text("SELECT ST_AsText(geometry) FROM forest_blocks WHERE id = :id"),
            {"id": str(unit.id)},
        ).scalar()
        if not wkt:
            continue
        zone = zone_provider(unit, wkt, db, params)
        inp = resolve_block_inputs(calc, unit, params, db, zone=zone)
        unit_by_name[inp.block_name] = unit

        prev = carry.get((unit.block_name or unit.name or "").strip(), {})
        # per-block overrides survive a rebuild
        patch: dict[str, Any] = {}
        if prev.get("override_crown_density_pct") is not None:
            patch["crown_density_pct"] = int(prev["override_crown_density_pct"])
        if prev.get("override_origin") in ("natural", "plantation"):
            patch["origin"] = prev["override_origin"]
        if patch:
            inp = dataclasses.replace(inp, **patch)

        cls = classify(zone, inp, params)
        override = prev.get("override_type_no")

        # What the block IS before it can have a type: forest land with plots of its own, forest land without any,
        # or not forest land at all. The land class is ESA's suggestion unless the user set it.
        user_class = prev.get("override_land_class")
        land_class = user_class if user_class in LAND_CLASSES else inp.land_class_suggestion
        state = block_state(land_class, inp.plot_count)
        proposed: Optional[int] = cls.proposed_type_no
        estimate: Optional[int] = None
        confidence, needs_review = cls.confidence, cls.needs_review
        reasons_ne, reasons_en = cls.reasons_ne, cls.reasons_en
        if state == NON_FOREST:
            proposed, override, confidence, needs_review = None, None, 0.0, False
            reasons_ne = f"वन जमिन होइन ({land_class})"
            reasons_en = f"Not forest land ({land_class}): no forest type"
        elif state == INVENTORY_MISSING:
            estimate, proposed, confidence, needs_review = cls.proposed_type_no, None, 0.0, True
            reasons_ne = "यस ब्लकमा नमुना प्लट छैन: वन प्रकार निर्धारण गर्न सकिँदैन"
            reasons_en = "No sample plots in this block: its forest type cannot be determined"
        elif state == PROVISIONAL:
            needs_review = True
            reasons_ne += f" · नमुना प्लट {inp.plot_count} (<{SFM_MIN_PLOTS_PER_BLOCK}), अस्थायी"
            reasons_en += f" · {inp.plot_count} plots (< {SFM_MIN_PLOTS_PER_BLOCK}): provisional"
        effective = override or proposed

        zone_by_block[inp.block_name] = _zone_dict(zone)
        blocks_out.append(
            {
                "block_name": inp.block_name,
                "area_ha": inp.area_ha,
                "inputs": _inputs_dict(inp),
                "proposed_type_no": proposed,
                "estimate_type_no": estimate,  # the raster prior, shown only as an estimate; never the type
                "state": state,
                "plot_count": inp.plot_count,
                "land_class": land_class,
                "land_class_source": "user" if user_class in LAND_CLASSES else "esa",
                "land_class_suggestion": inp.land_class_suggestion,
                "override_land_class": user_class if user_class in LAND_CLASSES else None,
                "confidence": confidence,
                "needs_review": needs_review,
                "reasons_ne": reasons_ne,
                "reasons_en": reasons_en,
                "override_type_no": override,
                "override_crown_density_pct": prev.get("override_crown_density_pct"),
                "override_origin": prev.get("override_origin"),
                "wc_accept": bool(prev.get("wc_accept")),
                "effective_type_no": effective,
                "prescription": None,
                "orientation": None,
                "orientation_justification_ne": None,
                "orientation_justification_en": None,
                "working_circle_proposal": None,
                "felling_series_id": None,
            }
        )

    sources = {b["inputs"]["source"] for b in blocks_out}
    source = sources.pop() if len(sources) == 1 else ("mixed" if sources else "prior")

    # ── P3 second pass: prescription · orientation · felling series · sampling
    prescriptions = load_prescriptions(db)
    for b in blocks_out:
        b["_zone"] = zone_by_block.get(b["block_name"], {})
    user_variant = result_key == SFM_USER_KEY
    typed = [b for b in blocks_out if b["effective_type_no"] is not None]
    for b in blocks_out:
        if b["effective_type_no"] is None:  # non-forest, or no plots: nothing to prescribe
            manual = (
                getattr(unit_by_name.get(b["block_name"]), "management_orientation", None) or None
                if user_variant
                else None
            )
            b["orientation"] = manual  # the user's own decision still stands in the "my adjustments" variant
            b["working_circle_proposal"] = None
            b["orientation_justification_ne"] = b["orientation_justification_en"] = None
            continue
        row = prescriptions.get(b["effective_type_no"])
        ori, wc_prop, justification = orientation_propose(
            b["effective_type_no"], b["_zone"], row, params
        )
        if user_variant:
            unit = unit_by_name.get(b["block_name"])
            manual = getattr(unit, "management_orientation", None) or None
            if manual:
                ori = manual  # the band (already inside _zone) still drove wc_prop/justification
        b["orientation"] = ori
        full_ne, full_en = _full_orientation_reason(b, row, justification)
        b["orientation_justification_ne"] = full_ne
        b["orientation_justification_en"] = full_en
        b["working_circle_proposal"] = wc_prop

    felling_series, forest_summary = build_series(
        typed, prescriptions, calc, db, params
    )
    series_by_type = {s["type_no"]: s for s in felling_series}
    for b in blocks_out:
        if b["effective_type_no"] is None:
            b["felling_series_id"] = None
            b["prescription"] = None
            continue
        s = series_by_type.get(b["effective_type_no"])
        row = prescriptions.get(b["effective_type_no"])
        b["felling_series_id"] = s["id"] if s else None
        b["prescription"] = build_card(
            row,
            (s["branch"] if s else "default"),
            gs_ge40_m3_per_ha=(b.get("inputs") or {}).get("gs_ge40_m3_per_ha"),
            pct=(s["pct"] if s else None),
            params=params,
        )

    for b in blocks_out:
        b["_wkt"] = None  # sampling needs a wkt; look it up once below
    _wkts = {
        r.bn: r.wkt
        for r in db.execute(
            text(
                "SELECT COALESCE(block_name, name) AS bn, ST_AsText(geometry) AS wkt "
                "FROM forest_blocks WHERE calculation_id = :cid"
            ),
            {"cid": str(calc.id)},
        ).fetchall()
    }
    for b in blocks_out:
        b["_wkt"] = _wkts.get(b["block_name"])
    forest_summary["sampling_plan"] = sfm_sampling_plan(typed, calc, db, params)
    forest_summary["inventory_gaps"] = [
        {"block_name": b["block_name"], "area_ha": b["area_ha"], "state": b["state"], "plot_count": b["plot_count"]}
        for b in blocks_out
        if b["state"] in (INVENTORY_MISSING, PROVISIONAL)
    ]

    for b in blocks_out:  # drop the private helpers before persisting
        b.pop("_zone", None)
        b.pop("_wkt", None)

    sfm = {
        "version": SFM_BLOCK_VERSION,
        "params_hash": h,
        "input_token": cache_token,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "zone_by_block": zone_by_block,
        "blocks": blocks_out,
        "felling_series": felling_series,
        "forest_summary": forest_summary,
    }
    sfm["narration"] = narration_all(sfm)

    new_rd = dict(rd)
    new_rd[result_key] = sfm
    calc.result_data = new_rd
    db.add(calc)
    db.commit()
    return sfm


def build_sfm(
    calc: Calculation,
    db: Session,
    *,
    force: bool = False,
    variant: str = "baseline",
) -> dict[str, Any]:
    """Return the SFM result for ``variant`` (``baseline`` | ``user``),
    rebuilding it when stale/absent (or ``force``). Writes + commits when it
    rebuilds. ``baseline`` is the exact current path (key ``sfm``, raster zones,
    original cache token); ``user`` classifies from the workspace columns under
    ``sfm_user`` with a ``|user``-suffixed token."""
    params = resolve_params(db, calc.id)
    h = params_hash(params)
    token = _input_token(calc, db)
    if variant == "user":
        return _build(
            calc,
            db,
            params=params,
            h=h,
            token=token,
            result_key=SFM_USER_KEY,
            zone_provider=_user_zone,
            force=force,
        )
    return _build(
        calc,
        db,
        params=params,
        h=h,
        token=token,
        result_key=SFM_RESULT_KEY,
        zone_provider=_baseline_zone,
        force=force,
    )


def get_sfm(calc: Calculation, db: Session) -> dict[str, Any]:
    """The cached SFM block, built on first access / after invalidation."""
    return build_sfm(calc, db)


# ─────────────────────────────────────────────────────────────────────────────
# Variant comparison (SV-1.5)
# ─────────────────────────────────────────────────────────────────────────────
def compare_variants(
    baseline: dict[str, Any], user: dict[str, Any]
) -> dict[str, Any]:
    """Diff the baseline vs user variant (SV-1.5 ``GET /sustainable-fm/compare``).

    Per-block entries are emitted **only for blocks that differ** (band,
    orientation, effective type, prescription name, working-circle proposal or
    stratum). No per-block ``area_ha`` in Phase 1 — a band override never
    changes block area. Forest-level deltas: production/protection ha, total
    annual harvest m³, per felling series, sampling intensities.
    """
    base_by = {b["block_name"]: b for b in baseline.get("blocks", [])}
    user_by = {b["block_name"]: b for b in user.get("blocks", [])}
    base_zone = baseline.get("zone_by_block", {})
    user_zone = user.get("zone_by_block", {})
    base_samp = {
        s["block_name"]: s
        for s in (baseline.get("forest_summary", {}) or {}).get("sampling_plan", [])
    }
    user_samp = {
        s["block_name"]: s
        for s in (user.get("forest_summary", {}) or {}).get("sampling_plan", [])
    }

    blocks_diff: list[dict[str, Any]] = []
    for name, ub in user_by.items():
        bb = base_by.get(name)
        if bb is None:
            continue
        row: dict[str, Any] = {"block_name": name}
        changed = False

        def _pair(getter):
            nonlocal changed
            bv, uv = getter(bb), getter(ub)
            if bv != uv:
                changed = True
            return bv, uv

        b_band = (base_zone.get(name) or {}).get("slope_band")
        u_band = (user_zone.get(name) or {}).get("slope_band")
        if b_band != u_band:
            row["slope_band"] = {"before": b_band, "after": u_band}
            changed = True
        row["slope_source"] = (
            "workspace"
            if u_band is not None and u_band != b_band
            else "raster"
        )

        b_samp = base_samp.get(name) or {}
        u_samp = user_samp.get(name) or {}
        if (b_samp.get("stratum"), b_samp.get("intensity_pct")) != (
            u_samp.get("stratum"),
            u_samp.get("intensity_pct"),
        ):
            row["stratum"] = {
                "before": {
                    "stratum": b_samp.get("stratum"),
                    "intensity_pct": b_samp.get("intensity_pct"),
                },
                "after": {
                    "stratum": u_samp.get("stratum"),
                    "intensity_pct": u_samp.get("intensity_pct"),
                },
            }
            changed = True

        b_ori = bb.get("orientation")
        u_ori = ub.get("orientation")
        if b_ori != u_ori:
            row["orientation"] = {"before": b_ori, "after": u_ori}
            changed = True
        row["orientation_source"] = (
            "workspace" if u_ori != b_ori and u_ori is not None else "raster"
        )

        b_type, u_type = bb.get("effective_type_no"), ub.get("effective_type_no")
        if b_type != u_type:
            row["type_no"] = {"before": b_type, "after": u_type}
            changed = True
        b_pres = (bb.get("prescription") or {}).get("type_name_en")
        u_pres = (ub.get("prescription") or {}).get("type_name_en")
        if b_pres != u_pres:
            row["prescription"] = {"before": b_pres, "after": u_pres}
            changed = True

        b_wc = (bb.get("working_circle_proposal") or {}).get("target")
        u_wc = (ub.get("working_circle_proposal") or {}).get("target")
        if b_wc != u_wc:
            row["working_circle"] = {"before": b_wc, "after": u_wc}
            changed = True

        row["area_source"] = "shared"  # band override never changes block area
        if changed:
            blocks_diff.append(row)

    base_sum = baseline.get("forest_summary", {}) or {}
    user_sum = user.get("forest_summary", {}) or {}
    base_series = {s["type_no"]: s for s in baseline.get("felling_series", [])}
    user_series = {s["type_no"]: s for s in user.get("felling_series", [])}

    def forest_delta(base, user, key):
        bv, uv = base.get(key), user.get(key)
        return {"before": bv, "after": uv} if bv != uv else None

    felling_delta = []
    for t in sorted(set(base_series) | set(user_series)):
        bv = (base_series.get(t) or {}).get("annual_harvest_m3")
        uv = (user_series.get(t) or {}).get("annual_harvest_m3")
        if bv != uv:
            felling_delta.append(
                {
                    "type_no": t,
                    "branch": (user_series.get(t) or {}).get("branch")
                    or (base_series.get(t) or {}).get("branch"),
                    "annual_harvest_m3": {"before": bv, "after": uv},
                }
            )

    sampling_delta = []
    for name in sorted(set(base_samp) | set(user_samp)):
        b, u = base_samp.get(name) or {}, user_samp.get(name) or {}
        if (b.get("stratum"), b.get("intensity_pct")) != (
            u.get("stratum"),
            u.get("intensity_pct"),
        ):
            sampling_delta.append(
                {
                    "block_name": name,
                    "stratum": {"before": b.get("stratum"), "after": u.get("stratum")},
                    "intensity_pct": {
                        "before": b.get("intensity_pct"),
                        "after": u.get("intensity_pct"),
                    },
                }
            )

    forest = {
        k: forest_delta(base_sum, user_sum, k)
        for k in ("production_area_ha", "protection_area_ha", "total_annual_harvest_m3")
    }
    forest = {k: v for k, v in forest.items() if v is not None}
    if felling_delta:
        forest["felling_series"] = felling_delta
    if sampling_delta:
        forest["sampling"] = sampling_delta

    return {
        "baseline": baseline,
        "user": user,
        "blocks": blocks_diff,
        "forest": forest,
        "identical": not blocks_diff and not forest,
    }


def invalidate_sfm(calculation_id, db: Session) -> None:
    """Drop ``result_data['sfm']`` **and** ``result_data['sfm_user']`` so the
    next access rebuilds both. Called from the analysis / field-inventory
    pipelines. Best-effort — never raises."""
    try:
        calc = db.get(Calculation, str(calculation_id))
        if calc is None or not isinstance(calc.result_data, dict):
            return
        if (
            SFM_RESULT_KEY not in calc.result_data
            and SFM_USER_KEY not in calc.result_data
        ):
            return
        new_rd = dict(calc.result_data)
        new_rd.pop(SFM_RESULT_KEY, None)
        new_rd.pop(SFM_USER_KEY, None)
        calc.result_data = new_rd
        db.add(calc)
        db.commit()
    except (
        Exception
    ):  # noqa: BLE001 -- an invalidation failure must not fail the pipeline
        logger.warning(
            "Could not invalidate SFM block for calc %s", calculation_id, exc_info=True
        )
        db.rollback()


__all__ = [
    "SFM_RESULT_KEY",
    "SFM_USER_KEY",
    "build_sfm",
    "get_sfm",
    "compare_variants",
    "invalidate_sfm",
]
