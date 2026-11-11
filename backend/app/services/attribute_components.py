"""The "Update attribute" command: which attribute components a forest has, whether each is up to date, and running them.

Owner rule 2026-10-10: one command in the workspace triggers whatever attribute components are available -- raster analysis,
inventory analysis, SFM, hazard & erosion -- as needed. A component that is not available for the forest is reported as such and
skipped; it never blocks the others.

Inventory analysis is report-only: re-processing it needs the uploaded inventory file, which the app does not keep, so the
panel sends the user to the Field Inventory step instead of pretending to run it.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Run order: raster, then the classes, then the inventory (SFM and hazard read all three), then SFM and hazard.
ORDER = ("raster", "classification", "inventory", "sfm", "hazard")


def _item(key: str, en: str, ne: str, state: str, reason_en: str = "", reason_ne: str = "", can_run: bool = True, open_step: str = "") -> Dict[str, Any]:
    """``state``: ``up_to_date`` | ``out_of_date`` | ``never`` | ``unavailable``."""
    return {
        "key": key, "label_en": en, "label_ne": ne, "state": state,
        "available": state != "unavailable", "can_run": can_run and state != "unavailable",
        "reason_en": reason_en, "reason_ne": reason_ne, "open_step": open_step,
    }


def _stale(rd: dict, domain: str) -> bool:
    return bool((rd.get("structure_stale") or {}).get(domain))


def components_status(db: Session, calc) -> List[Dict[str, Any]]:
    from app.services.operational_plan.prereq_check import _has_processed_field_inventory, _has_soil_data
    from app.services.unit_analysis_service import analysis_status

    rd = calc.result_data or {}
    out: List[Dict[str, Any]] = []

    st = analysis_status(db, calc.id)
    if st["units"] == 0:
        out.append(_item("raster", "Raster analysis", "र्‍यास्टर विश्लेषण", "unavailable", "No units yet.", "अहिलेसम्म कुनै इकाई छैन।"))
    elif st["ready"]:
        out.append(_item("raster", "Raster analysis", "र्‍यास्टर विश्लेषण", "up_to_date"))
    else:
        why = "The units changed since the last run." if st["stale"] else f"{st['missing']} of {st['units']} units have no results."
        out.append(_item("raster", "Raster analysis", "र्‍यास्टर विश्लेषण", "out_of_date" if st["analysed"] else "never", why, "इकाईहरू परिवर्तन भएका छन् वा नतिजा बाँकी छ।"))

    out.append(_classification_status(db, calc, rd, st["units"]))

    if not _has_processed_field_inventory(db, calc.id):
        out.append(_item(
            "inventory", "Inventory analysis", "सूची विश्लेषण", "unavailable",
            "No field inventory has been uploaded and processed yet. Upload it in the Field Inventory step.",
            "क्षेत्र सूची अझै अपलोड र प्रशोधन भएको छैन। क्षेत्र सूची चरणमा अपलोड गर्नुहोस्।",
            can_run=False, open_step="fieldinventory",
        ))
    else:
        # Refreshable from the stored plots and measurements; the upload file is not needed.
        stale_fi = _stale(rd, "field_inventory")
        out.append(_item(
            "inventory", "Inventory analysis", "सूची विश्लेषण",
            "out_of_date" if stale_fi else "up_to_date",
            "The units changed since the inventory was processed. Updating re-assigns the plots to the current units." if stale_fi else "",
            "इकाई परिवर्तन भएपछि सूची प्रशोधन भएको छैन। अद्यावधिक गर्दा प्लटहरू हालका इकाईमा पुनः मिलाइन्छ।" if stale_fi else "",
        ))

    if st["units"] == 0:
        out.append(_item("sfm", "Sustainable FM", "दिगो वन व्यवस्थापन", "unavailable", "No units yet.", "अहिलेसम्म कुनै इकाई छैन।"))
    else:
        has = bool((rd.get("sfm") or {}).get("blocks"))
        out.append(_item("sfm", "Sustainable FM", "दिगो वन व्यवस्थापन", "up_to_date" if has else "never"))

    if not _has_soil_data(db, calc.id):
        out.append(_item("hazard", "Hazard & erosion", "जोखिम तथा क्षरण", "unavailable", "No soil data covers this forest.", "यस वनमा माटोको तथ्याङ्क उपलब्ध छैन।"))
    else:
        out.append(_item("hazard", "Hazard & erosion", "जोखिम तथा क्षरण", "up_to_date" if _hazard_cached(calc.id) else "never"))

    return sorted(out, key=lambda i: ORDER.index(i["key"]))


async def _run_raster(db: Session, calc) -> Dict[str, Any]:
    """The same engine as the Re-run Analysis button (``reanalysis_service``): whole-forest results plus every unit. The units'
    stored values are also written onto the lists the OP placeholders read (done inside the analysis itself)."""
    from app.services.reanalysis_service import run_reanalysis

    await run_reanalysis(db, calc, dict(calc.analysis_options or {}))
    db.refresh(calc)
    return {}



# The classification columns the table shows, filled from the rasters. Contour band is filled too but is not part of the status.
_CLASS_COLUMNS = (
    "dominant_slope_band", "dominant_aspect", "dominant_canopy_class", "dominant_nasa_quality",
    "dominant_health_class", "dominant_landcover", "dominant_forest_type",
)
_CLASS_MARKER = "attribute_classification"


def _classification_status(db: Session, calc, rd: dict, units: int) -> Dict[str, Any]:
    from sqlalchemy import text

    from app.services.operational_plan.prereq_check import _has_processed_field_inventory

    en, ne = "Classification", "वर्गीकरण"
    if units == 0:
        return _item("classification", en, ne, "unavailable", "No units yet.", "अहिलेसम्म कुनै इकाई छैन।")
    empty = db.execute(
        text(
            "SELECT count(*) FROM forest_blocks b LEFT JOIN raster_layers l ON l.id = b.raster_layer_id "
            "WHERE b.calculation_id = :c AND (b.raster_layer_id IS NULL OR l.promoted_as IS NOT NULL) AND ("
            + " OR ".join(f"b.{c} IS NULL" for c in _CLASS_COLUMNS) + ")"
        ),
        {"c": str(calc.id)},
    ).scalar() or 0
    # Orientation (management / suggested / justification) is decided from the forest type, which comes from the sample plots.
    needs_inventory = not _has_processed_field_inventory(db, calc.id)
    inv_en = " Management orientation also needs the sample field inventory: upload it in the Field Inventory step."
    inv_ne = " अभिमुखीकरणका लागि नमुना क्षेत्र सूची पनि चाहिन्छ: क्षेत्र सूची चरणमा अपलोड गर्नुहोस्।"
    step = "fieldinventory" if needs_inventory else ""
    if rd.get(_CLASS_MARKER) and not _stale(rd, "analysis"):
        return _item(
            "classification", en, ne, "up_to_date",
            inv_en.strip() if needs_inventory else "", inv_ne.strip() if needs_inventory else "", open_step=step,
        )
    return _item(
        "classification", en, ne, "out_of_date" if empty < units else "never",
        f"{empty} of {units} units have empty classes (slope, aspect, canopy, NASA, health, land cover, forest type)."
        + (inv_en if needs_inventory else ""),
        f"{units} मध्ये {empty} इकाईमा वर्ग खाली छन्।" + (inv_ne if needs_inventory else ""),
        open_step=step,
    )


def _run_classification(db: Session, calc) -> Dict[str, Any]:
    """Fill each unit's EMPTY class columns with the dominant class of the rasters inside its own polygon (the same functions the
    Union carve uses). A value already there -- carved, or set by hand in the table -- is never overwritten."""
    from geoalchemy2.shape import to_shape
    from sqlalchemy.orm.attributes import flag_modified

    from app.models.forest_block import ForestBlock
    from app.models.raster_layer import RasterLayer
    from app.services.aspect_vectorize import aspect_dominant_code
    from app.services.auto_block_service import _boundary_shape
    from app.services.canopy_vectorize import canopy_dominant_class
    from app.services.raster_class_vectorize import (
        DEM_ELEVATION, ESA_LANDCOVER, FRTC_FOREST_TYPE, NASA_QUALITY, NDVI_HEALTH,
        band_table_for, dominant_band, dominant_class,
    )
    from app.services.sustainable_fm.sfm_config import resolve_params
    from app.services.sustainable_fm.slope_vectorize import slope_profile

    params = resolve_params(db, calc.id)
    try:
        bands = band_table_for(calc, db, DEM_ELEVATION, _boundary_shape(db, calc, None).wkt, n_bands=3)
    except Exception:  # noqa: BLE001 -- without elevation bands the contour column stays empty; logged
        logger.exception("attribute_components: elevation bands failed")
        bands = None

    rows = (
        db.query(ForestBlock)
        .outerjoin(RasterLayer, RasterLayer.id == ForestBlock.raster_layer_id)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.geometry.isnot(None),
            (ForestBlock.raster_layer_id.is_(None)) | (RasterLayer.promoted_as.isnot(None)),
        )
        .all()
    )
    filled = 0
    for row in rows:
        wkt = to_shape(row.geometry).wkt

        def safe(fn, *a):
            try:
                with db.begin_nested():
                    return fn(*a)
            except Exception:  # noqa: BLE001 -- one raster failing leaves that cell empty; the others still fill
                logger.exception("attribute_components: classification step failed for unit %s", row.id)
                return None

        wanted = {
            "dominant_slope_band": lambda: (slope_profile(wkt, db, params) or {}).get("dominant_band"),
            "dominant_aspect": lambda: aspect_dominant_code(wkt, db),
            "dominant_canopy_class": lambda: canopy_dominant_class(wkt, db),
        }
        for col, fn in wanted.items():
            if getattr(row, col) is None:
                v = safe(fn)
                if v is not None:
                    setattr(row, col, v)
                    filled += 1
        for col, raw_col, spec in (
            ("dominant_nasa_quality", "dominant_nasa_code", NASA_QUALITY),
            ("dominant_health_class", None, NDVI_HEALTH),
            ("dominant_landcover", None, ESA_LANDCOVER),
            ("dominant_forest_type", None, FRTC_FOREST_TYPE),
        ):
            if getattr(row, col) is None or (raw_col and getattr(row, raw_col) is None):
                dom = safe(dominant_class, wkt, db, spec)
                if dom is not None:
                    if dom.code is not None and getattr(row, col) is None:
                        setattr(row, col, dom.code)
                        filled += 1
                    # The raw raster class is kept even when it is the anonymous "unclassified" class (code None): the
                    # table shows it as "0 - Unclassified", never a blank (owner rule 2026-09-30).
                    if raw_col and getattr(row, raw_col) is None and dom.raw_code is not None:
                        setattr(row, raw_col, dom.raw_code)
                        filled += 1
        if bands and row.dominant_contour_band is None:
            dom = safe(dominant_band, wkt, db, DEM_ELEVATION, bands)
            if dom is not None and dom.code is not None:
                row.dominant_contour_band = dom.code
                filled += 1
        db.flush()

    # Management / suggested orientation and its justification come from SFM's own classification; see `_sync_orientation`.
    oriented = _sync_orientation(db, calc)
    filled += oriented
    # build_sfm may have refreshed result_data; read it after, not before.
    rd = dict(calc.result_data or {})
    rd[_CLASS_MARKER] = {"units": len(rows), "filled": filled, "oriented": oriented}
    calc.result_data = rd
    flag_modified(calc, "result_data")
    return {"units": len(rows), "filled": filled, "oriented": oriented}


async def _run_inventory(db: Session, calc) -> Dict[str, Any]:
    """Refresh the processed field inventory from its stored plots and measurements, then clear its stale mark."""
    from app.models.field_inventory import FieldInventoryCalculation
    from app.services.field_inventory_service import FieldInventoryService
    from app.services.forest_units.write import clear_stale_domains

    fi = db.query(FieldInventoryCalculation).filter(FieldInventoryCalculation.calculation_id == calc.id).first()
    if fi is None:
        raise RuntimeError("No field inventory for this forest")
    out = await FieldInventoryService(db).refresh_from_stored(fi.id)
    db.refresh(calc)
    clear_stale_domains(db, calc, ("field_inventory",))
    return out


def _sync_orientation(db: Session, calc) -> int:
    """Write SFM's orientation onto every unit it classified: ``suggested_orientation`` (read-only, always the latest SFM answer) with
    its justification, and ``management_orientation`` ONLY where it is still empty -- a value chosen by hand is never replaced.

    The suggested value used to be written once, when a unit was carved, so it stayed empty on every unit that came later. A unit
    SFM cannot classify (no sample plots, non-forest) keeps both empty; the table says why instead of leaving a bare dash.
    """
    from app.models.forest_block import ForestBlock
    from app.services.forest_units.queries import promoted_or_unlayered
    from app.services.sustainable_fm.sfm_service import build_sfm

    sfm = build_sfm(calc, db, force=True, variant="user")
    by_name = {b.get("block_name"): b for b in sfm.get("blocks", []) if isinstance(b, dict) and b.get("block_name")}
    rows = promoted_or_unlayered(db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id)).all()
    n = 0
    for row in rows:
        info = by_name.get(row.block_name) or by_name.get(row.name)
        ori = (info or {}).get("orientation")
        if not ori:
            continue
        row.suggested_orientation = ori
        row.orientation_justification_en = info.get("orientation_justification_en")
        row.orientation_justification_ne = info.get("orientation_justification_ne")
        if row.management_orientation is None:
            row.management_orientation = ori
        n += 1
    db.flush()
    return n


def _run_sfm(db: Session, calc) -> Dict[str, Any]:
    from app.services.sustainable_fm.sfm_service import build_sfm

    build_sfm(calc, db, force=True)
    return {"oriented": _sync_orientation(db, calc)}


def _run_hazard(db: Session, calc) -> Dict[str, Any]:
    """Recompute soil loss and landslide / stability for real. The workspace only reads cached grids and never computes, so
    dropping the caches alone would leave the hazard columns empty until someone opened the Hazard tab."""
    from app.services.operational_plan import landslide_susceptibility, soil_erosion
    from app.services.operational_plan.data_collector import get_hazard_vuln_data, get_soil_erosion_data

    soil_erosion.clear_cache(calc.id)
    landslide_susceptibility.clear_cache(calc.id)
    soil = get_soil_erosion_data(db, str(calc.id))
    hazard = get_hazard_vuln_data(db, str(calc.id))
    soil_ok, hazard_ok = bool(soil.get("soil_loss_available")), bool(hazard.get("hazard_vuln_available"))
    if not (soil_ok or hazard_ok):
        raise RuntimeError("Hazard & erosion could not be computed for this forest")
    return {"soil_loss": soil_ok, "landslide": hazard_ok}


def _hazard_cached(calc_id: UUID) -> bool:
    from app.services.operational_plan import landslide_susceptibility, soil_erosion

    def _has(root) -> bool:
        d = root / str(calc_id)
        return d.exists() and any(d.iterdir())

    return _has(soil_erosion._CACHE_ROOT) and _has(landslide_susceptibility._CACHE_ROOT)


async def run_components(db: Session, calc, keys: List[str]) -> Dict[str, Any]:
    """Run the requested components that are available, in order. ``{key: {ok, ...}}``; one failing never stops the others."""
    from fastapi.concurrency import run_in_threadpool

    status = {i["key"]: i for i in components_status(db, calc)}
    results: Dict[str, Any] = {}
    sync_runners: Dict[str, Callable[[Session, Any], Dict[str, Any]]] = {"classification": _run_classification, "sfm": _run_sfm, "hazard": _run_hazard}
    for key in ORDER:
        if key not in keys:
            continue
        item = status.get(key)
        if item is None or not item["can_run"]:
            results[key] = {"ok": False, "skipped": True, "reason_en": (item or {}).get("reason_en") or "Not available.", "reason_ne": (item or {}).get("reason_ne", "")}
            continue
        try:
            if key == "raster":
                detail = await _run_raster(db, calc)
            elif key == "inventory":
                detail = await _run_inventory(db, calc)
            else:
                detail = await run_in_threadpool(sync_runners[key], db, calc)
            db.commit()
            results[key] = {"ok": True, **detail}
        except Exception as exc:  # noqa: BLE001 -- reported to the caller and logged; the other components still run
            logger.exception("attribute_components: %s failed", key)
            db.rollback()
            results[key] = {"ok": False, "error": str(exc)[:300]}
    if any(r.get("ok") for r in results.values()):
        _clear_derived_caches(db, calc.id)
    return results


def _clear_derived_caches(db: Session, calc_id: UUID) -> None:
    """The OP data cache and rendered maps were built from the old values."""
    try:
        from app.models.op_data_cache import OpDataCache
        from app.services.management_plan_docx.plan_map_service import clear_map_cache

        db.query(OpDataCache).filter(OpDataCache.calculation_id == calc_id).delete()
        db.commit()
        clear_map_cache(calculation_id=calc_id)
    except Exception:  # noqa: BLE001 -- best effort; the caches rebuild on the next read
        logger.warning("attribute_components: could not clear derived caches", exc_info=True)
        db.rollback()
