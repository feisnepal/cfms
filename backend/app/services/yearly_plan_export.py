"""One exporter for the yearly plan (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.7, F8).

The same table exported from the map workspace and from the legacy page is identical — the same
bytes for the same data — because it is built here, on the server, from the saved data (never from a
page's unsaved state), by the same query that feeds the operational plan's ``ya_*`` variables.

Two tables:

* **Yearly plan** — one row per plan line, every activity (spatial and not).
* **Activity features** — one row per drawn place.

Rules kept from the legacy CSV: the quantity / budget cells list only the years above 0
(``Y1:5, Y2:5``); the total is the ten-year sum; a line with nothing planned prints ``None``; every
cell is quoted. Changes made on purpose: quantities are not rounded, the two hard-coded English headers
are translated (D12), the location cells are blank for an activity that needs no map (D26), digits are
always ASCII, and the row order is fixed (programme, then activity).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from ..models.calculation import Calculation
from ..models.forest_block import ForestBlock
from ..models.yearly_activities import (
    ActivityDrawnFeature,
    ActivitySpatialAssignment,
    PotentialActivity,
)
from . import yearly_plan_service as plan
from .operational_plan.feature_kinds import KINDS, resolve_feature_kind

BOM = "﻿"  # so Excel reads Devanagari correctly

HEADERS: Dict[str, Dict[str, List[str]]] = {
    "plan": {
        "en": [
            "S.No",
            "Activity",
            "Programme",
            "Unit",
            "Quantity",
            "Budget",
            "Total budget (10 years)",
            "Location type",
            "Location details",
            "Spatial features",
        ],
        "ne": [
            "क्र.सं.",
            "कार्य",
            "कार्यक्रम",
            "इकाई",
            "परिमाण",
            "बजेट",
            "कुल बजेट (१० वर्ष)",
            "स्थानको प्रकार",
            "स्थानको विवरण",
            "नक्सामा देखाइएका ठाउँ",
        ],
    },
    "features": {
        "en": [
            "S.No",
            "Activity",
            "Programme",
            "Name",
            "Geometry",
            "Symbol",
            "Years",
            "Blocks",
            "Sub-areas",
            "Length (km)",
            "Area (ha)",
        ],
        "ne": [
            "क्र.सं.",
            "कार्य",
            "कार्यक्रम",
            "नाम",
            "आकार",
            "चिन्ह",
            "वर्षहरू",
            "ब्लक",
            "उप-क्षेत्र",
            "लम्बाइ (कि.मि.)",
            "क्षेत्रफल (हे.)",
        ],
    },
}
NONE_WORD = "None"  # as the legacy file prints it, in either language
ALL_BLOCKS = {"en": "All Blocks", "ne": "सबै ब्लक"}
NO_SPECIFIC = {"en": "No specific location", "ne": "कुनै निश्चित स्थान छैन"}
DRAWN_ON_MAP = {"en": "Drawn on the map", "ne": "नक्सामा कोरिएको"}
GEOMETRY_WORD = {
    "en": {"point": "Point", "line": "Line", "polygon": "Area"},
    "ne": {"point": "बिन्दु", "line": "रेखा", "polygon": "क्षेत्र"},
}


def _lang(lang: str) -> str:
    return "ne" if str(lang).lower().startswith("ne") else "en"


def _num(value: float) -> str:
    """A plain ASCII number: ``5``, ``0.5``, ``250000`` — never rounded, never grouped."""
    text = format(Decimal(str(value)), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def to_csv(headers: List[str], rows: List[List[Any]]) -> str:
    """Every cell quoted (as the legacy file), inner quotes doubled, ``\\n`` line ends, BOM first."""

    def cell(value: Any) -> str:
        return '"' + str(value).replace('"', '""') + '"'

    lines = [",".join(cell(h) for h in headers)] + [
        ",".join(cell(c) for c in row) for row in rows
    ]
    return BOM + "\n".join(lines) + "\n"


def filename(calc: Calculation, kind: str, ext: str = "csv") -> str:
    """The project's standard ``{ForestName}_{Module}_{Type}_{YYYYMMDD}.{ext}``."""
    name = re.sub(r"\s+", "_", (calc.forest_name or "forest").strip()) or "forest"
    stamp = datetime.now().strftime("%Y%m%d")
    return f"{name}_YearlyActivity_{kind}_{stamp}.{ext}"


def _sort_key(line: Dict[str, Any]) -> Tuple[str, str]:
    return (line.get("program") or "", line.get("activity") or "")


def _assignment_names(
    db: Session, calc: Calculation, line_ids: List[UUID]
) -> Dict[str, Dict[str, List[str]]]:
    out: Dict[str, Dict[str, List[str]]] = {}
    if not line_ids:
        return out
    sub_names = {
        str(sa.get("id")): sa.get("name") or ""
        for sa in (calc.result_data or {}).get("sub_areas", []) or []
    }
    rows = (
        db.query(ActivitySpatialAssignment, ForestBlock.name)
        .outerjoin(ForestBlock, ForestBlock.id == ActivitySpatialAssignment.block_id)
        .filter(ActivitySpatialAssignment.proposed_activity_id.in_(line_ids))
        .all()
    )
    for assignment, block_name in rows:
        entry = out.setdefault(
            str(assignment.proposed_activity_id),
            {"all": [], "blocks": [], "sub_areas": []},
        )
        if assignment.assignment_type == "all_blocks":
            entry["all"].append("all")
        elif assignment.assignment_type == "sub_area":
            entry["sub_areas"].append(sub_names.get(str(assignment.sub_area_id), ""))
        elif block_name:
            entry["blocks"].append(block_name)
    return out


def _live_features(
    db: Session, line_ids: List[UUID]
) -> Dict[str, List[ActivityDrawnFeature]]:
    out: Dict[str, List[ActivityDrawnFeature]] = {}
    if not line_ids:
        return out
    for f in (
        db.query(ActivityDrawnFeature)
        .filter(
            ActivityDrawnFeature.proposed_activity_id.in_(line_ids),
            ActivityDrawnFeature.deleted_at.is_(None),
        )
        .order_by(ActivityDrawnFeature.created_at)
    ):
        out.setdefault(str(f.proposed_activity_id), []).append(f)
    return out


def plan_table(
    db: Session, calc: Calculation, lang: str = "en"
) -> Tuple[List[str], List[List[Any]]]:
    """The yearly-plan table: every activity, one row per plan line."""
    lg = _lang(lang)
    lines = sorted(plan.plan_view(db, calc), key=_sort_key)
    ids = [UUID(item["id"]) for item in lines]
    assignments = _assignment_names(db, calc, ids)
    features = _live_features(db, ids)

    rows: List[List[Any]] = []
    for idx, line in enumerate(lines, start=1):
        qty = ", ".join(
            f"Y{y['year']}:{_num(y['quantity'])}"
            for y in line["years"]
            if y["quantity"] > 0
        )
        bud = ", ".join(
            f"Y{y['year']}:{_num(y['budget'])}"
            for y in line["years"]
            if y["budget"] > 0
        )
        total = _num(sum(y["budget"] for y in line["years"]))
        assign = assignments.get(line["id"], {"all": [], "blocks": [], "sub_areas": []})

        mode = line["location_mode"]
        if mode == "not_applicable":
            loc_type, loc_details = (
                "",
                "",
            )  # an activity that needs no map has no location (D26)
        elif assign["sub_areas"]:
            loc_type, loc_details = "sub_areas", ", ".join(
                s for s in assign["sub_areas"] if s
            )
        elif assign["blocks"]:
            loc_type, loc_details = "blocks", ", ".join(assign["blocks"])
        elif assign["all"] or mode == "whole_forest":
            loc_type, loc_details = "all", ALL_BLOCKS[lg]
        elif mode == "places":
            # places are drawn: say where they fall (derived from the geometry, D13), never "no specific location"
            loc_type = "places"
            loc_details = (
                ", ".join(line.get("location_units") or []) or DRAWN_ON_MAP[lg]
            )
        else:
            loc_type, loc_details = (
                "none",
                NO_SPECIFIC[lg],
            )  # a mappable activity, nothing chosen yet

        names = ", ".join(
            (f.properties or {}).get("name")
            or (f.properties or {}).get("label")
            or "Unnamed"
            for f in features.get(line["id"], [])
        )
        rows.append(
            [
                idx,
                line["activity"] or "",
                line["program"] or "",
                line["unit"] or "",
                qty or NONE_WORD,
                bud or NONE_WORD,
                total,
                loc_type,
                loc_details,
                names or NONE_WORD,
            ]
        )
    return HEADERS["plan"][lg], rows


def features_table(
    db: Session, calc: Calculation, lang: str = "en"
) -> Tuple[List[str], List[List[Any]]]:
    """The spatial table: one row per drawn place, with its derived blocks and measured length / area."""
    from geoalchemy2.shape import to_shape

    lg = _lang(lang)
    lines = {item["id"]: item for item in plan.plan_view(db, calc)}
    masters = {
        m.id: m
        for m in db.query(PotentialActivity).filter(
            PotentialActivity.id.in_(
                {v["potential_activity_id"] for v in lines.values()} or {-1}
            )
        )
    }
    feats = _live_features(db, [UUID(i) for i in lines])
    flat = [(lines[lid], f) for lid, group in feats.items() for f in group]
    flat.sort(
        key=lambda pair: (
            pair[0].get("program") or "",
            pair[0].get("activity") or "",
            pair[1].created_at,
        )
    )

    rows: List[List[Any]] = []
    for idx, (line, feature) in enumerate(flat, start=1):
        props = feature.properties or {}
        master = masters.get(line["potential_activity_id"])
        kind = resolve_feature_kind(
            props.get("kind"), getattr(master, "map_kind", None), feature.feature_type
        )
        kind_label = ""
        if kind in KINDS:
            kind_label = KINDS[kind].label_ne if lg == "ne" else KINDS[kind].label_en
        try:
            location = plan.derive_location(db, calc, to_shape(feature.geometry).wkt)
        except Exception:  # noqa: BLE001 -- location is a convenience column
            location = {"blocks": [], "sub_areas": []}
        length_km = props.get("geo_length_km")
        area_ha = props.get("geo_area_ha")
        rows.append(
            [
                idx,
                line["activity"] or "",
                line["program"] or "",
                props.get("name") or "",
                GEOMETRY_WORD[lg].get(feature.feature_type, feature.feature_type),
                kind_label,
                ", ".join(f"Y{y}" for y in (props.get("years") or [])),
                ", ".join(location["blocks"]),
                ", ".join(location["sub_areas"]),
                _num(length_km) if length_km else "",
                _num(area_ha) if area_ha else "",
            ]
        )
    return HEADERS["features"][lg], rows
