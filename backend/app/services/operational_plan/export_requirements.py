"""Mandatory steps that must be complete before the Operational Plan can be exported.

Owner rule 2026-10-10: raster attributes on the sub-units -> sampling -> field inventory ->
biodiversity -> households -> Forest User Committee -> Metadata form. Stem mapping and the other
committees are optional. This is the ONE place that list lives; the export endpoint refuses on it
and the workspace shows it as a checklist, so the two cannot disagree.

Only the export is gated. The step pages stay open (see ``workflow_readiness``: sequence, never
enforce) -- this module answers "what is still missing", nothing more.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Metadata fields that may not be blank. The filing identifiers (codes, serial number) and the
# division / address lines are left optional: a forest office assigns them, not the user group.
REQUIRED_METADATA_FIELDS: Tuple[str, ...] = (
    "forest_name", "group_name", "province", "district", "palika", "ward", "fy_start", "fy_end",
)


def _raster_attributes(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    """"Run analysis" has been run on the CURRENT units: every unit (any level) has its analysis row and the forest is not
    flagged as changed since (``unit_analysis_service.analysis_status``)."""
    from app.services.unit_analysis_service import analysis_status

    st = analysis_status(db, calc_id)
    return bool(st["ready"]), {k: st[k] for k in ("units", "analysed", "missing", "stale")}


def _sampling(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    from app.models.sampling import SamplingDesign

    n = db.query(SamplingDesign.id).filter(SamplingDesign.calculation_id == calc_id).count()
    return n > 0, {}


def _field_inventory(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    from .prereq_check import _has_processed_field_inventory

    return _has_processed_field_inventory(db, calc_id), {}


def _biodiversity(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    from .prereq_check import _has_biodiversity_data

    return _has_biodiversity_data(db, calc_id), {}


def _households(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    # household_aggregate is the one place that answers "are there household totals" (rows replace a summary).
    from app.services.household_aggregate import get_aggregate

    return get_aggregate(db, calc_id) is not None, {}


def _yearly_activities(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    from .prereq_check import _has_proposed_activities

    return _has_proposed_activities(db, calc_id), {}


def _cba(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    """The base scenario has a calculated result (the rail's Cost-Benefit step asks the same question)."""
    from .prereq_check import _has_cba_result

    return _has_cba_result(db, calc_id), {}


def _sub_areas_planned(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    """Every sub-area (private land excepted) is tied to the yearly plan (owner rule 2026-10-08). Used to be a second,
    separate check made after this list was green; it is part of the list now."""
    from app.models.calculation import Calculation
    from app.services.sub_area_plan import sub_area_plan_status, sub_areas_needing_plan

    calc = db.get(Calculation, calc_id)
    missing = sub_areas_needing_plan(sub_area_plan_status(db, calc)) if calc else []
    return not missing, {"count": len(missing), "names": [(m["name"] or m["id"] or "?") for m in missing[:10]]}


def _committee(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    from app.models.forest_committee import ForestUserCommittee

    n = db.query(ForestUserCommittee.id).filter(ForestUserCommittee.calculation_id == calc_id).count()
    return n > 0, {"members": n}


def _metadata(db: Session, calc_id: UUID) -> Tuple[bool, Dict[str, Any]]:
    from app.models.forest_metadata import ForestMetadata

    row = db.query(ForestMetadata).filter(ForestMetadata.calculation_id == calc_id).first()
    blank = [
        f for f in REQUIRED_METADATA_FIELDS
        if row is None or not str(getattr(row, f, None) or "").strip()
    ]
    return not blank, {"blank_fields": blank}


# requirement key -> the rail step (context id of ``calcContexts.ts``) where it is done. Checked against ``STEP_PREREQS``
# by a test, so a rename of a step cannot leave a dead link here.
STEP_FOR: Dict[str, str] = {
    "raster": "unified", "sampling": "sampling", "field_inventory": "fieldinventory", "biodiversity": "biodiversity",
    "households": "usergroup", "yearly_activities": "yearly", "sub_areas_planned": "yearly", "cba": "cba",
    "committee": "usergroup", "metadata": "forestmetadata",
}

# key, English, Nepali, how to fix (EN, NE), check
_Req = Tuple[str, str, str, str, str, Callable[[Session, UUID], Tuple[bool, Dict[str, Any]]]]
REQUIREMENTS: List[_Req] = [
    ("raster", "Analysis run on every unit", "सबै इकाईमा विश्लेषण सञ्चालन",
     "Run the analysis so every block, compartment, sub-block and sub-compartment has its results.",
     "प्रत्येक इकाईको नतिजा पाउन विश्लेषण चलाउनुहोस्।", _raster_attributes),
    ("sampling", "Sample plots created", "नमुना प्लट सिर्जना",
     "Create the sampling design and its plots.", "नमुना डिजाइन र प्लटहरू बनाउनुहोस्।", _sampling),
    ("field_inventory", "Field inventory done", "क्षेत्र सूची सम्पन्न",
     "Enter and process the plot measurements.", "प्लट मापन भरेर प्रशोधन गर्नुहोस्।", _field_inventory),
    ("biodiversity", "Biodiversity recorded", "जैविक विविधता अभिलेख",
     "Record at least one species.", "कम्तीमा एक प्रजाति अभिलेख गर्नुहोस्।", _biodiversity),
    ("households", "Household data or summary", "घरधुरी विवरण वा सारांश",
     "Upload household data or enter the household summary.",
     "घरधुरी विवरण अपलोड गर्नुहोस् वा सारांश भर्नुहोस्।", _households),
    ("yearly_activities", "Yearly activities plan", "वार्षिक कार्यक्रम योजना",
     "Add the proposed yearly activities.", "प्रस्तावित वार्षिक कार्यक्रमहरू थप्नुहोस्।", _yearly_activities),
    ("sub_areas_planned", "Every sub-area is in the yearly plan", "प्रत्येक उप-क्षेत्र वार्षिक योजनामा",
     "Give each sub-area (private land excepted) at least one planned activity.",
     "प्रत्येक उप-क्षेत्र (निजी जग्गा बाहेक) मा कम्तीमा एक योजनाबद्ध कार्यक्रम राख्नुहोस्।", _sub_areas_planned),
    ("cba", "Cost-benefit analysis calculated", "लागत-लाभ विश्लेषण गणना",
     "Open Cost-Benefit and calculate the base scenario.",
     "लागत-लाभ खोलेर आधार परिदृश्यको गणना गर्नुहोस्।", _cba),
    ("committee", "Forest User Committee", "वन उपभोक्ता समिति",
     "Fill in the Forest User Committee form.", "वन उपभोक्ता समिति फारम भर्नुहोस्।", _committee),
    ("metadata", "Metadata form", "मेटाडाटा फारम",
     "Complete every required field of the metadata form.", "मेटाडाटा फारमका सबै आवश्यक क्षेत्र भर्नुहोस्।", _metadata),
]


def export_requirements(db: Session, calc_id: UUID) -> Dict[str, Any]:
    """``{ready, items:[{key, done, label_en, label_ne, hint_en, hint_ne, detail}]}``.

    Each check runs in a savepoint: a failing query reports that item as not done instead of
    aborting the transaction for the rest.
    """
    items: List[Dict[str, Any]] = []
    for key, en, ne, hint_en, hint_ne, check in REQUIREMENTS:
        done, detail = False, {}
        try:
            with db.begin_nested():
                done, detail = check(db, calc_id)
        except Exception:  # noqa: BLE001 -- reported as not done; logged so it is not silent
            logger.exception("export_requirements: %s check failed", key)
        items.append({
            "key": key, "step": STEP_FOR.get(key), "done": bool(done), "label_en": en, "label_ne": ne,
            "hint_en": hint_en, "hint_ne": hint_ne, "detail": detail,
        })
    return {"ready": all(i["done"] for i in items), "items": items}


def assert_export_ready(db: Session, calc_id: UUID) -> None:
    """The export gate: 409 listing every incomplete step."""
    from fastapi import HTTPException

    result = export_requirements(db, calc_id)
    if not result["ready"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "EXPORT_REQUIREMENTS_INCOMPLETE", "items": [i for i in result["items"] if not i["done"]]},
        )
