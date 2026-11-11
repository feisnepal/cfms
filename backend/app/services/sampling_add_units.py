"""Add polygons to the forest's ONE sampling design, and take one polygon's plots out again.

A forest keeps a single design. Sampling is done in rounds: the user ticks some polygons now, others later. So a later round
APPENDS its plots to the existing design (existing plots do not move, new ones are numbered after them) instead of making a
second design. A polygon that already has plots cannot be sampled again; to sample it again its plots must first be deleted
(``remove_unit_plots``), which is only allowed while no field inventory exists - exactly the rule for deleting a single plot.

Both functions write nothing outside ``sampling_designs`` and do not commit: the caller commits.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

from shapely import wkt as shapely_wkt
from shapely.geometry import MultiPoint, Point
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.sampling import SamplingDesign
from app.services import optimistic_lock

SQM_PER_HA = 10_000.0


def _points_of(db: Session, design_id) -> List[Any]:
    row = db.execute(
        text("SELECT ST_AsText(points_geometry) AS wkt FROM public.sampling_designs WHERE id = :d"), {"d": str(design_id)}
    ).first()
    if not row or not row.wkt:
        return []
    return list(shapely_wkt.loads(row.wkt).geoms)


def _write_points(db: Session, design: SamplingDesign, points: List[Any], assignments: List[dict]) -> None:
    wkt = MultiPoint(points).wkt if points else None
    db.execute(
        text("UPDATE public.sampling_designs SET points_geometry = CASE WHEN :wkt IS NULL THEN NULL ELSE ST_GeomFromText(:wkt, 4326) END, "
             "points_block_assignment = CAST(:a AS jsonb), total_points = :n, points_data = NULL WHERE id = :d"),
        {"wkt": wkt, "a": json.dumps(assignments), "n": len(points), "d": str(design.id)},
    )


def merge_preview_into_design(db: Session, design: SamplingDesign, features: Iterable[Any], preview: Any) -> Dict[str, Any]:
    """Append the previewed plots (``features``: GeoJSON points with ``block_number`` / ``block_name`` / ``zone_type``) to ``design``.

    ``preview`` is the captured preview (its ``blocks_info`` and sampled-area figures). Raises ``ValueError`` if a feature lands in a
    polygon that already has plots - the caller checks first, this is the last line of defence.
    """
    old_assign: List[dict] = list(design.points_block_assignment or [])
    already = {a.get("block_name") for a in old_assign if a.get("block_name")}
    old_points = _points_of(db, design.id)

    new_points, new_assign = [], []
    for f in features:
        coords = (f.geometry or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        props = f.properties or {}
        name = props.get("block_name")
        if name in already:
            raise ValueError(f"UNIT_ALREADY_SAMPLED: {name}")
        new_points.append(Point(float(coords[0]), float(coords[1])))
        new_assign.append(
            {
                "point_index": len(old_points) + len(new_points) - 1,
                "block_number": props.get("block_number"),
                "block_name": name,
                "zone_type": props.get("zone_type", "productive"),
            }
        )
    if not new_points:
        raise ValueError("PREVIEW_EMPTY: पूर्वावलोकन नमूना बिन्दुहरू फेला परेन (कृपया पुन: पूर्वावलोकन गर्नुहोस्)")

    all_points = old_points + new_points
    _write_points(db, design, all_points, old_assign + new_assign)

    # the stored summary the sampling screen shows on revisit
    rd = dict(design.result_data or {})
    infos = {str(b.get("block_name")): dict(b) for b in (rd.get("blocks_info") or [])}
    for b in preview.blocks_info or []:
        d = b.model_dump(mode="json") if hasattr(b, "model_dump") else dict(b)
        name = str(d.get("block_name"))
        # only the polygons this round actually sampled replace their entry; the others keep what they had
        if int(d.get("samples_generated") or 0) > 0 or name not in infos:
            infos[name] = d
    forest_ha = float(rd.get("forest_area_hectares") or getattr(preview, "forest_area_hectares", 0) or 0)
    sampled_ha = float(rd.get("total_sampled_area_hectares") or 0) + float(getattr(preview, "total_sampled_area_hectares", 0) or 0)
    rd["blocks_info"] = list(infos.values())
    rd["total_points"] = len(all_points)
    rd["total_sampled_area_hectares"] = round(sampled_ha, 6)
    if forest_ha > 0:
        rd["actual_intensity_per_hectare"] = len(all_points) / forest_ha
        rd["sampling_percentage"] = round(100.0 * sampled_ha / forest_ha, 6)
    design.result_data = rd
    optimistic_lock.record_derived_write(db, "sampling", design.id, "sampling: polygons added")
    db.add(design)
    return {"added": len(new_points), "total_points": len(all_points), "units": sorted({a["block_name"] for a in new_assign if a["block_name"]})}


def remove_unit_plots(db: Session, design: SamplingDesign, unit_name: str) -> Dict[str, Any]:
    """Delete every plot of one polygon. The remaining plots stay numbered 1..N without a gap (plot numbers are positional
    everywhere else); the stored per-polygon summary says the polygon has no plots now.

    Raises ``LookupError`` when the polygon has no plots and ``ValueError("LAST_PLOT")`` when it would empty the whole design (delete
    the design instead).
    """
    assign = list(design.points_block_assignment or [])
    drop = {a.get("point_index") for a in assign if a.get("block_name") == unit_name and a.get("point_index") is not None}
    if not drop:
        raise LookupError(unit_name)
    points = _points_of(db, design.id)
    if len(drop) >= len(points):
        raise ValueError("LAST_PLOT")

    keep_index = [i for i in range(len(points)) if i not in drop]
    new_of = {old: new for new, old in enumerate(keep_index)}
    new_assign = []
    for a in assign:
        pi = a.get("point_index")
        if pi in drop or pi not in new_of:
            continue
        a = dict(a)
        a["point_index"] = new_of[pi]
        new_assign.append(a)
    _write_points(db, design, [points[i] for i in keep_index], new_assign)

    rd = dict(design.result_data or {})
    infos = []
    for b in rd.get("blocks_info") or []:
        b = dict(b)
        if str(b.get("block_name")) == unit_name:
            b["samples_generated"] = 0
        infos.append(b)
    if infos:
        rd["blocks_info"] = infos
    rd["total_points"] = len(keep_index)
    design.result_data = rd
    optimistic_lock.record_derived_write(db, "sampling", design.id, "sampling: polygon plots removed")
    db.add(design)
    return {"removed": len(drop), "remaining_points": len(keep_index)}
