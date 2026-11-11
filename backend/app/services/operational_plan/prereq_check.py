"""PrerequisiteChecker — resolves a spec's ``requires`` tags for a forest.

THEMATIC_MAP_VARIABLES_PLAN §3.9.1. Drives the reference-page "Copyable?"
column and the renderer's missing-data behaviour.

    check(db, calc_id, ["field_inventory", "sub_areas"])
      -> PrereqResult(status="partial", unmet=["sub_areas"],
                      reason_en="This forest has no sub-areas.",
                      hint_en="Draw or import sub-areas in the workspace.")

Without a calc (``db`` / ``calc_id`` None) it degrades to a *generic*
requirement description — used by the standalone reference page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

_Predicate = Callable[[Session, UUID], bool]


# ── DB predicates ────────────────────────────────────────────────────────
def _has_processed_field_inventory(db: Session, calc_id: UUID) -> bool:
    from app.models.field_inventory import FieldInventoryCalculation

    row = (
        db.query(FieldInventoryCalculation.status)
        .filter(FieldInventoryCalculation.calculation_id == calc_id)
        .first()
    )
    return bool(row) and str(row[0]).lower() in (
        "completed",
        "complete",
        "done",
        "success",
        "processed",
    )


def _result_data(db: Session, calc_id: UUID) -> dict:
    from app.models.calculation import Calculation

    row = db.query(Calculation.result_data).filter(Calculation.id == calc_id).first()
    return (row[0] or {}) if row else {}


def _has_sub_areas(db: Session, calc_id: UUID) -> bool:
    # the zones only: an automatically made fire line must not mark the Area detail step complete
    from app.core.sub_area_kinds import real_sub_areas

    return bool(real_sub_areas(_result_data(db, calc_id).get("sub_areas")))


def _has_protected_sub_area(db: Session, calc_id: UUID) -> bool:
    subs = _result_data(db, calc_id).get("sub_areas", []) or []
    return any(s.get("category") == "protected" for s in subs)


def _has_strips(db: Session, calc_id: UUID, category: str) -> bool:
    """A fire line / river bank made in the sub-areas layer (stored in ``result_data['sub_areas']``)."""
    return any(sa.get("category") == category for sa in _result_data(db, calc_id).get("sub_areas") or [])


def _has_fire_line_features(db: Session, calc_id: UUID) -> bool:
    return _has_strips(db, calc_id, "fire_line") or _has_activity_drawn_features(db, calc_id)


def _has_river_bank_features(db: Session, calc_id: UUID) -> bool:
    return _has_strips(db, calc_id, "river_bank") or _has_activity_drawn_features(db, calc_id)


def _has_compartments(db: Session, calc_id: UUID) -> bool:
    from app.models.forest_block import ForestBlock

    # FS-1c.1 straggler fix: this used to infer "compartments exist" from a depth test
    # (a positive depth meant a compartment or sub-unit, back when blocks sat at 0). Migration 094 puts top-level
    # blocks at depth 1 too, so that proxy would silently start matching every forest. The real question --
    # is this the compartment branch -- is `is_compartment`, not a depth.
    return (
        db.query(ForestBlock.id)
        .filter(ForestBlock.calculation_id == calc_id, ForestBlock.is_compartment.is_(True))
        .first()
        is not None
    )


def _has_sampling_design(db: Session, calc_id: UUID) -> bool:
    try:
        from app.models.sampling import SamplingDesign
    except Exception:  # noqa: BLE001 -- model name may differ across builds
        return False
    return (
        db.query(SamplingDesign.id)
        .filter(SamplingDesign.calculation_id == calc_id)
        .first()
        is not None
    )


def _has_tree_mapping(db: Session, calc_id: UUID) -> bool:
    """A tree-mapping record exists for this forest.

    This used to read ``result_data['tree_mapping_analysis']`` — a key nothing
    ever wrote. The OP collector builds that section in memory
    (``collect_all_op_data``) and caches it in ``op_data_cache``; it does not
    persist it onto the calculation, and no commit ever has. So the predicate was
    False for every forest, which was invisible until P5c made this signal gate
    the Tree Mapping Results pane: the pane is locked, the hint tells the user to
    "run the tree-mapping analysis", and there is no such action anywhere in the
    app. What the pane needs is the mapping record itself — the same row the map
    and the Data pane draw the stems from.
    """
    try:
        from app.models.inventory import InventoryCalculation
    except Exception:  # noqa: BLE001
        return False
    # Deliberately not filtered by owner or status: this asks "is there tree
    # mapping for this forest", and `check_tree_mapping_exists` -- which the Data
    # pane gates the whole step on -- answers it the same way.
    return (
        db.query(InventoryCalculation.id)
        .filter(InventoryCalculation.calculation_id == calc_id)
        .first()
        is not None
    )


def _has_ntfp_design(db: Session, calc_id: UUID) -> bool:
    """The NTFP survey has sample plots laid out (what the NTFP plot map draws); findings are not needed."""
    try:
        from app.models.ntfp_method import NtfpSamplingDesign
    except Exception:  # noqa: BLE001 -- the model is part of this build; an import failure is "no design", not a crash of the whole strip
        return False
    return db.query(NtfpSamplingDesign.id).filter(NtfpSamplingDesign.calculation_id == calc_id).first() is not None


def _has_ntfp_survey(db: Session, calc_id: UUID) -> bool:
    """The NTFP resource survey has records: at least one count (zero included) was brought in from the field, by upload or on the map.

    An optional step (owner, 2026-10-22): a saved design alone is a plan for the survey, not the survey, so it does not make the step green.
    """
    try:
        from app.models.ntfp_method import NtfpObservation, NtfpSamplePlot, NtfpSamplingDesign
    except Exception:  # noqa: BLE001 -- the model is part of this build; an import failure is "no survey", not a crash of the whole strip
        return False
    return (
        db.query(NtfpObservation.id)
        .join(NtfpSamplePlot, NtfpObservation.plot_id == NtfpSamplePlot.id)
        .join(NtfpSamplingDesign, NtfpSamplePlot.design_id == NtfpSamplingDesign.id)
        .filter(NtfpSamplingDesign.calculation_id == calc_id)
        .first()
        is not None
    )


def _has_sfm_data(db: Session, calc_id: UUID) -> bool:
    return bool((_result_data(db, calc_id).get("sfm") or {}).get("blocks"))


def _has_user_group_extent(db: Session, calc_id: UUID) -> bool:
    try:
        from app.models.user_group import UserGroupExtent
    except Exception:  # noqa: BLE001
        return False
    return (
        db.query(UserGroupExtent.id)
        .filter(UserGroupExtent.calculation_id == calc_id)
        .first()
        is not None
    )


def _has_forest_metadata(db: Session, calc_id: UUID) -> bool:
    """Every field of the forest metadata record is filled (owner, 2026-10-11: the whole form is mandatory)."""
    try:
        from app.models.forest_metadata import ForestMetadata
    except Exception:  # noqa: BLE001 -- model name may differ across builds
        return False
    row = db.query(ForestMetadata).filter(ForestMetadata.calculation_id == calc_id).first()
    from app.services.forest_metadata_service import EDITABLE_FIELDS

    return bool(row and all((getattr(row, f, None) or "").strip() for f in EDITABLE_FIELDS))


def _has_household_data(db: Session, calc_id: UUID) -> bool:
    """Household rows OR a totals-only summary (`household_aggregate.get_aggregate` is the one place that answers this)."""
    from app.services.household_aggregate import get_aggregate

    return get_aggregate(db, calc_id) is not None


def _has_executive_committee(db: Session, calc_id: UUID) -> bool:
    """At least one member of the main (executive) user committee. The advisory and financial committees are optional."""
    try:
        from app.models.forest_committee import ForestUserCommittee
    except Exception:  # noqa: BLE001 -- model name may differ across builds
        return False
    return db.query(ForestUserCommittee.id).filter(ForestUserCommittee.calculation_id == calc_id).first() is not None


def _has_fieldbook(db: Session, calc_id: UUID) -> bool:
    """A generated field book = rows in the `fieldbook` table (the map layer's own data).

    This used to read only `result_data["fieldbook"|"fieldbook_points"]`, which the
    generator no longer writes, so a completed field book never turned its step green.
    The legacy keys still count, for forests that carry them.
    """
    try:
        from app.models.fieldbook import Fieldbook
    except Exception:  # noqa: BLE001 -- model name may differ across builds
        Fieldbook = None  # type: ignore[assignment]
    if Fieldbook is not None:
        if db.query(Fieldbook.id).filter(Fieldbook.calculation_id == calc_id).first() is not None:
            return True
    rd = _result_data(db, calc_id)
    return bool(rd.get("fieldbook") or rd.get("fieldbook_points"))


def _has_biodiversity_data(db: Session, calc_id: UUID) -> bool:
    """At least one species recorded for this forest.

    Biodiversity is field data (owner decision D-record, 2026-09-26: it is
    collected during the field-inventory visit), but it lives in its own table
    rather than in `result_data`, so it cannot be inferred the way
    `_has_fieldbook` and `_has_sfm_data` are.
    """
    try:
        from app.models.biodiversity import CalculationBiodiversity
    except Exception:  # noqa: BLE001 -- model name may differ across builds
        return False
    return (
        db.query(CalculationBiodiversity.id)
        .filter(CalculationBiodiversity.calculation_id == calc_id)
        .first()
        is not None
    )


def _has_map_complete(db: Session, calc_id: UUID) -> bool:
    """D11 — "map work finished".

    The owner's definition, adopted verbatim: a boundary exists AND every block is
    named/numbered. The third clause of that definition — "no unsaved geometry
    edits" — is **not** checkable here: unsaved edits live in the browser, not in
    the database. The client contributes that half from its own dirty flag, which
    is why the workflow's map step is a conjunction of this predicate and the
    client's, rather than this predicate alone.

    `block_name` is the user-editable serial ("Block-1", "Block-2", ...);
    `natural_name` is a best-effort geographic label and deliberately does not
    count as "named".
    """
    from sqlalchemy import text

    try:
        row = db.execute(
            text(
                """
            SELECT
              EXISTS (SELECT 1 FROM calculations
                       WHERE id = :cid AND boundary_geom IS NOT NULL) AS has_boundary,
              EXISTS (SELECT 1 FROM forest_blocks
                       WHERE calculation_id = :cid
                         AND (block_name IS NULL OR btrim(block_name) = '')) AS any_unnamed
        """
            ),
            {"cid": str(calc_id)},
        ).first()
        return bool(row) and bool(row[0]) and not bool(row[1])
    except Exception:  # noqa: BLE001
        return False


def _has_plan_submission(db: Session, calc_id: UUID) -> bool:
    """A submission to a receiving office has been recorded (D8).

    The last step of the cycle. Append-only by migration 097, so "exists" is the
    only question — and deliberately not "is current": a plan may be submitted,
    then edited, then submitted again, and both are true records.
    """
    from sqlalchemy import text

    try:
        return (
            db.execute(
                text(
                    "SELECT 1 FROM public.document_submissions "
                    "WHERE calculation_id = :cid LIMIT 1"
                ),
                {"cid": str(calc_id)},
            ).first()
            is not None
        )
    except Exception:  # noqa: BLE001 -- table absent on an un-migrated database
        return False


def _has_proposed_activities(db: Session, calc_id: UUID) -> bool:
    try:
        from app.models.yearly_activities import ProposedYearlyActivity
    except Exception:  # noqa: BLE001
        return False
    return (
        db.query(ProposedYearlyActivity.id)
        .filter(ProposedYearlyActivity.calculation_id == calc_id)
        .first()
        is not None
    )


def _yearly_activities_done(db: Session, calc_id: UUID) -> bool:
    """The owner pressed Done on the yearly-activities step (it reopens itself when the plan changes)."""
    try:
        from app.models.yearly_activities import YearlyPlanStatus
    except Exception:  # noqa: BLE001
        return False
    row = db.query(YearlyPlanStatus.is_done).filter(YearlyPlanStatus.calculation_id == calc_id).first()
    return bool(row and row[0])


def _has_activity_drawn_features(db: Session, calc_id: UUID) -> bool:
    try:
        from app.models.yearly_activities import ActivityDrawnFeature
    except Exception:  # noqa: BLE001
        return False
    return (
        db.query(ActivityDrawnFeature.id)
        .filter(
            ActivityDrawnFeature.calculation_id == calc_id,
            ActivityDrawnFeature.deleted_at.is_(None),
        )
        .first()
        is not None
    )


def _has_raster_coverage(db: Session, calc_id: UUID) -> bool:
    """The national DEM raster covers this forest → S9 zonal stats can run."""
    from sqlalchemy import text

    try:
        q = text(
            "SELECT 1 FROM rasters.dem r, calculations c "
            "WHERE c.id = :cid AND ST_Intersects(r.rast, c.boundary_geom) LIMIT 1"
        )
        return db.execute(q, {"cid": str(calc_id)}).first() is not None
    except Exception:  # noqa: BLE001
        return False


def _boundary_wkt(db: Session, calc_id: UUID) -> Optional[str]:
    from sqlalchemy import text

    try:
        row = db.execute(
            text("SELECT ST_AsText(boundary_geom) FROM calculations WHERE id = :c"),
            {"c": str(calc_id)},
        ).first()
        return row[0] if row else None
    except Exception:  # noqa: BLE001
        return None


def _has_road_layer(db: Session, calc_id: UUID) -> bool:
    """The road vector layer (``infrastructure.road``) reaches this forest."""
    from app.services.operational_plan.raster_zonal import has_road_layer

    w = _boundary_wkt(db, calc_id)
    return bool(w) and has_road_layer(db, w)


def _has_hydro_layer(db: Session, calc_id: UUID) -> bool:
    """A river / drainage line (``river.river84``) crosses this forest."""
    from app.services.operational_plan.raster_zonal import has_hydro_layer

    w = _boundary_wkt(db, calc_id)
    return bool(w) and has_hydro_layer(db, w)


def _has_soil_data(db: Session, calc_id: UUID) -> bool:
    """A ``soil.soilgrids`` row (via ``base.mmu``) covers this forest — needed
    for the RUSLE K factor / the soil-loss map / the FS c′-φ′-γ lookups."""
    from sqlalchemy import text

    try:
        q = text(
            "SELECT 1 FROM base.mmu m "
            "JOIN soil.soilgrids sg ON sg.mmuid = m.mmuid, calculations c "
            "WHERE c.id = :cid AND ST_Intersects(m.geom, c.boundary_geom) LIMIT 1"
        )
        return db.execute(q, {"cid": str(calc_id)}).first() is not None
    except Exception:  # noqa: BLE001
        return False


def _has_geology(db: Session, calc_id: UUID) -> bool:
    """A ``geology.geology`` polygon covers this forest — the lithology factor
    of the Landslide Susceptibility Index."""
    from sqlalchemy import text

    try:
        q = text(
            "SELECT 1 FROM geology.geology g, calculations c "
            "WHERE c.id = :cid AND ST_Intersects(g.geom, c.boundary_geom) LIMIT 1"
        )
        return db.execute(q, {"cid": str(calc_id)}).first() is not None
    except Exception:  # noqa: BLE001
        return False


def _has_household_data(db: Session, calc_id: UUID) -> bool:
    """Something to rank for the household-vulnerability maps: household records, or -- when there are none --
    building footprints from the user-group analysis (owner, 2026-10-05). Coordinates no longer matter: the
    analysis places households on building footprints."""
    try:
        from app.models.household_information import HouseholdInformation
        from app.models.user_group import UserGroupBuilding, UserGroupExtent
    except Exception:  # noqa: BLE001
        return False
    if db.query(HouseholdInformation.id).filter(HouseholdInformation.calculation_id == calc_id).first():
        return True
    return (
        db.query(UserGroupBuilding.id)
        .join(UserGroupExtent, UserGroupExtent.id == UserGroupBuilding.extent_id)
        .filter(UserGroupExtent.calculation_id == calc_id, UserGroupBuilding.building_count > 0)
        .first()
        is not None
    )


def _has_cba_result(db: Session, calc_id: UUID) -> bool:
    """The base scenario has a calculated result (same scenario the OP reads: ``get_cost_benefit_data``). The export gate
    (``export_requirements``) and the Cost-Benefit step in the rail both ask this, so they cannot disagree."""
    from app.models.cost_benefit import CBAResult, CostBenefitAnalysis

    row = (
        db.query(CBAResult.npv)
        .join(CostBenefitAnalysis, CostBenefitAnalysis.id == CBAResult.cba_id)
        .filter(CostBenefitAnalysis.calculation_id == calc_id, CostBenefitAnalysis.is_base_scenario.is_(True))
        .first()
    )
    return row is not None and row[0] is not None


@dataclass(frozen=True)
class _Tag:
    predicate: Optional[_Predicate]  # None => capability not in the system yet
    reason_en: str
    reason_ne: str
    hint_en: str
    hint_ne: str


_TAGS: dict[str, _Tag] = {
    "cba_calculated": _Tag(
        _has_cba_result,
        "The cost-benefit analysis has not been calculated for this forest.",
        "यस वनको लागत-लाभ विश्लेषणको गणना गरिएको छैन।",
        "Open Cost-Benefit and calculate the base scenario.",
        "लागत-लाभ खोलेर आधार परिदृश्यको गणना गर्नुहोस्।",
    ),
    "field_inventory": _Tag(
        _has_processed_field_inventory,
        "No field inventory has been processed for this forest.",
        "यस वनको क्षेत्र सर्वेक्षण प्रशोधन भइसकेको छैन।",
        "Upload and process a field inventory for this forest.",
        "यस वनको लागि क्षेत्र सर्वेक्षण अपलोड गरी प्रशोधन गर्नुहोस्।",
    ),
    "sub_areas": _Tag(
        _has_sub_areas,
        "This forest has no sub-areas.",
        "यस वनमा उप-क्षेत्र छैन।",
        "Draw or import sub-areas in the workspace.",
        "कार्यक्षेत्रमा उप-क्षेत्र कोर्नुहोस् वा आयात गर्नुहोस्।",
    ),
    "protected_sub_area": _Tag(
        _has_protected_sub_area,
        "This forest has no protected sub-area.",
        "यस वनमा संरक्षित उप-क्षेत्र छैन।",
        "Add a sub-area with category 'protected'.",
        "'संरक्षित' श्रेणीको उप-क्षेत्र थप्नुहोस्।",
    ),
    "compartments": _Tag(
        _has_compartments,
        "This forest is block-mode, not compartment-mode.",
        "यो वन ब्लक मोडमा छ, कम्पार्टमेन्ट मोडमा छैन।",
        "Divide the forest into compartments in the workspace.",
        "कार्यक्षेत्रमा वनलाई कम्पार्टमेन्टमा विभाजन गर्नुहोस्।",
    ),
    "sampling": _Tag(
        _has_sampling_design,
        "No sampling design has been created for this forest.",
        "यस वनको लागि नमूना योजना बनाइएको छैन।",
        "Create a sampling design in the Sampling tab.",
        "स्याम्पलिङ ट्याबमा नमूना योजना बनाउनुहोस्।",
    ),
    "tree_mapping": _Tag(
        _has_tree_mapping,
        "Tree-mapping analysis has not been run for this forest.",
        "यस वनको रूख म्यापिङ विश्लेषण चलाइएको छैन।",
        "Run the tree-mapping analysis.",
        "रूख म्यापिङ विश्लेषण चलाउनुहोस्।",
    ),
    "ntfp_design": _Tag(
        _has_ntfp_design,
        "No NTFP sample plots have been laid out for this forest.",
        "यस वनको गैरकाष्ठ वन पैदावार नमूना प्लट बनाइएको छैन।",
        "Open the NTFP inventory page: choose the species and lay out the plots.",
        "गैरकाष्ठ वन पैदावार पेज खोल्नुहोस्: प्रजाति छान्नुहोस् र प्लट बनाउनुहोस्।",
    ),
    "ntfp_survey": _Tag(
        _has_ntfp_survey,
        "No NTFP survey records have been brought in for this forest.",
        "यस वनको गैरकाष्ठ वन पैदावार सर्वेक्षणका अभिलेख ल्याइएको छैन।",
        "Open the NTFP inventory page: choose the species, lay out the plots and bring in what was found. This step is optional.",
        "गैरकाष्ठ वन पैदावार पेज खोल्नुहोस्: प्रजाति छान्नुहोस्, प्लट बनाउनुहोस् र भेटिएको कुरा ल्याउनुहोस्। यो चरण ऐच्छिक हो।",
    ),
    "sfm_data": _Tag(
        _has_sfm_data,
        "Sustainable forest management classification has not been built for this forest.",
        "यस वनको दिगो वन व्यवस्थापन वर्गीकरण बनाइएको छैन।",
        "Open the Sustainable Forest Management tab so the classification builds.",
        "दिगो वन व्यवस्थापन ट्याब खोल्नुहोस् — वर्गीकरण स्वतः बन्नेछ।",
    ),
    "user_group_extent": _Tag(
        _has_user_group_extent,
        "No user-group boundary has been drawn for this forest.",
        "यस वनको उपभोक्ता समूह सिमाना कोरिएको छैन।",
        "Draw or import the user-group boundary layer.",
        "उपभोक्ता समूह सिमाना तह कोर्नुहोस् वा आयात गर्नुहोस्।",
    ),
    "fieldbook": _Tag(
        _has_fieldbook,
        "No fieldbook survey has been uploaded for this forest.",
        "यस वनको फिल्डबुक सर्वेक्षण अपलोड गरिएको छैन।",
        "Upload the GPS fieldbook.",
        "जीपीएस फिल्डबुक अपलोड गर्नुहोस्।",
    ),
    "biodiversity_data": _Tag(
        _has_biodiversity_data,
        "No biodiversity records have been entered for this forest.",
        "यस वनका लागि जैविक विविधताको अभिलेख प्रविष्ट गरिएको छैन।",
        "Record the species found on the field-inventory visit.",
        "क्षेत्र सर्वेक्षण भ्रमणमा भेटिएका प्रजातिहरू अभिलेख गर्नुहोस्।",
    ),
    "household_data": _Tag(
        _has_household_data,
        "No household information has been entered: upload the household list, or enter just the totals.",
        "घरधुरी विवरण प्रविष्ट गरिएको छैन: घरधुरी सूची अपलोड गर्नुहोस्, वा जम्मा मात्र प्रविष्ट गर्नुहोस्।",
        "Right-click the User Group Boundary layer and choose Household data.",
        "उपभोक्ता समूह सीमा तहमा दायाँ क्लिक गरी घरधुरी तथ्याङ्क छान्नुहोस्।",
    ),
    "executive_committee": _Tag(
        _has_executive_committee,
        "The executive committee has not been entered.",
        "कार्यसमिति प्रविष्ट गरिएको छैन।",
        "Right-click the User Group Boundary layer and choose Executive committee.",
        "उपभोक्ता समूह सीमा तहमा दायाँ क्लिक गरी कार्यसमिति छान्नुहोस्।",
    ),
    "forest_metadata": _Tag(
        _has_forest_metadata,
        "The forest metadata is incomplete: every field of the form is required.",
        "वनको मेटाडाटा अपूरो छ: फारमका सबै महल अनिवार्य छन्।",
        "Fill in every field of the Forest Metadata step.",
        "वन मेटाडाटा चरणका सबै महल भर्नुहोस्।",
    ),
    "map_complete": _Tag(
        _has_map_complete,
        "The map is not finished: the boundary is missing, or some blocks are unnamed.",
        "नक्सा पूरा भएको छैन: सीमा छैन, वा केही ब्लकको नाम दिइएको छैन।",
        "Draw the boundary and give every block a name or number.",
        "सीमा कोर्नुहोस् र हरेक ब्लकलाई नाम वा नम्बर दिनुहोस्।",
    ),
    "plan_submitted": _Tag(
        _has_plan_submission,
        "This plan has not been submitted to a receiving office.",
        "यो योजना कुनै कार्यालयमा पेस गरिएको छैन।",
        "Export the .docx, print it, and submit it to the District Forest Office.",
        "'.docx' निर्यात गरी छापेर जिल्ला वन कार्यालयमा पेस गर्नुहोस्।",
    ),
    "proposed_activities": _Tag(
        _has_proposed_activities,
        "No operational-plan activities have been entered yet.",
        "कार्ययोजनाका क्रियाकलापहरू अझै प्रविष्ट गरिएका छैनन्।",
        "Add proposed activities in the Operational Plan tab.",
        "कार्ययोजना ट्याबमा प्रस्तावित क्रियाकलापहरू थप्नुहोस्।",
    ),
    "yearly_activities_done": _Tag(
        _yearly_activities_done,
        "The yearly activities have not been marked done.",
        "वार्षिक क्रियाकलाप सकिएको जनाइएको छैन।",
        "Add the yearly activities, then press Done on the Yearly Activities step.",
        "वार्षिक क्रियाकलाप थपेपछि वार्षिक क्रियाकलाप चरणमा 'सकियो' थिच्नुहोस्।",
    ),
    "activity_drawn_features": _Tag(
        _has_activity_drawn_features,
        "Activities exist but none carry a drawn map feature.",
        "क्रियाकलापहरू छन् तर कुनैमा नक्सामा कोरिएको सुविधा छैन।",
        "Draw point/line/polygon features on the activities that need them.",
        "आवश्यक क्रियाकलापहरूमा बिन्दु/रेखा/बहुभुज सुविधा कोर्नुहोस्।",
    ),
    "fire_line_features": _Tag(
        _has_fire_line_features,
        "No fire line has been made or drawn.",
        "कुनै आगो नियन्त्रण रेखा बनाइएको वा कोरिएको छैन।",
        "Make the fire lines in the sub-areas layer (Fire lines panel), or draw them on an activity.",
        "उप-क्षेत्र तहको 'अग्नी रेखा' प्यानलमा बनाउनुहोस्, वा क्रियाकलापमा कोर्नुहोस्।",
    ),
    "river_bank_features": _Tag(
        _has_river_bank_features,
        "No river bank has been made or drawn.",
        "कुनै खोला किनार बनाइएको वा कोरिएको छैन।",
        "Make the river banks in the sub-areas layer, or draw them on an activity.",
        "उप-क्षेत्र तहमा खोला किनार बनाउनुहोस्, वा क्रियाकलापमा कोर्नुहोस्।",
    ),
    # S9 zonal stats over rasters.* — computed live per unit (P6z). Gated only
    # on the national DEM raster actually covering this forest.
    "raster_zonal": _Tag(
        _has_raster_coverage,
        "The terrain rasters do not cover this forest's location.",
        "भू-बनोट रास्टरहरूले यस वनको स्थान समेट्दैनन्।",
        "Zonal terrain maps need a forest inside the national raster coverage.",
        "क्षेत्रगत भू-बनोट नक्साका लागि वन राष्ट्रिय रास्टर क्षेत्रभित्र हुनुपर्छ।",
    ),
    "roads": _Tag(
        _has_road_layer,
        "No road / trail is mapped near this forest.",
        "यस वन नजिक कुनै सडक/गोरेटो नक्सांकित छैन।",
        "The national road layer does not reach this location.",
        "राष्ट्रिय सडक तह यस स्थानसम्म पुग्दैन।",
    ),
    "hydro": _Tag(
        _has_hydro_layer,
        "No river / stream line crosses this forest.",
        "यस वनमा कुनै नदी/खोला रेखा पर्दैन।",
        "The river-network layer has nothing inside this boundary.",
        "नदी-सञ्जाल तहमा यस सिमानाभित्र केही छैन।",
    ),
    "soil_data": _Tag(
        _has_soil_data,
        "No soil data covers this forest's location.",
        "यस वनको स्थानमा माटो तथ्याङ्क उपलब्ध छैन।",
        "The RUSLE soil-loss map needs a forest inside the national soil-grid coverage.",
        "RUSLE माटो क्षय नक्साका लागि वन राष्ट्रिय माटो-ग्रिड क्षेत्रभित्र हुनुपर्छ।",
    ),
    "geology": _Tag(
        _has_geology,
        "No geology / lithology polygon covers this forest's location.",
        "यस वनको स्थानमा भूगर्भ/शिलावर्ग बहुभुज उपलब्ध छैन।",
        "The landslide-susceptibility map needs a forest inside the national geology coverage.",
        "पहिरो संवेदनशीलता नक्साका लागि वन राष्ट्रिय भूगर्भ क्षेत्रभित्र हुनुपर्छ।",
    ),
    "household_data": _Tag(
        _has_household_data,
        "No household data and no building footprints exist for this forest.",
        "यस वनको लागि घरधुरी विवरण र भवन खाका दुवै छैनन्।",
        "Draw the user-group boundary (its buildings are used), or enter the household data.",
        "उपभोक्ता समूहको सिमाना कोर्नुहोस् (यसका भवन प्रयोग हुन्छन्) वा घरधुरी विवरण प्रविष्ट गर्नुहोस्।",
    ),
    # Capability not in the system yet — always 🔴, cannot be enabled by the user.
    "flow_accumulation": _Tag(
        None,
        "Hydrological flow-accumulation is not computed for this system.",
        "जलधार प्रवाह-संकलन यस प्रणालीमा गणना गरिएको छैन।",
        "This map type is not available yet.",
        "यो नक्सा प्रकार अझै उपलब्ध छैन।",
    ),
    "road_network": _Tag(
        None,
        "No road / trail network layer is available.",
        "सडक/गोरेटो सञ्जाल तह उपलब्ध छैन।",
        "This map type is not available yet.",
        "यो नक्सा प्रकार अझै उपलब्ध छैन।",
    ),
    "two_inventory_cycles": _Tag(
        None,
        "Needs a prior inventory to compare against (future capability).",
        "तुलना गर्न अघिल्लो सर्वेक्षण चाहिन्छ (भविष्यको क्षमता)।",
        "This map type is not available yet.",
        "यो नक्सा प्रकार अझै उपलब्ध छैन।",
    ),
    "demand_model": _Tag(
        None,
        "Needs a settlement demand-allocation model (not built yet).",
        "बस्ती माग-वितरण मोडेल चाहिन्छ (अझै बनेको छैन)।",
        "This map type is not available yet.",
        "यो नक्सा प्रकार अझै उपलब्ध छैन।",
    ),
}


@dataclass
class PrereqResult:
    status: str = "available"  # "available" 🟢 | "partial" 🟡 | "unavailable" 🔴
    met: bool = True
    unmet: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    reason_en: str = ""
    reason_ne: str = ""
    hint_en: str = ""
    hint_ne: str = ""

    @property
    def copyable(self) -> bool:
        return not self.unavailable


def describe_tag(tag: str) -> dict:
    """Generic (no-forest) description of one ``requires`` tag."""
    t = _TAGS.get(tag)
    if t is None:
        return {
            "tag": tag,
            "available_capability": True,
            "label_en": tag.replace("_", " "),
            "label_ne": tag.replace("_", " "),
        }
    return {
        "tag": tag,
        "available_capability": t.predicate is not None,
        "label_en": t.reason_en,
        "label_ne": t.reason_ne,
        "hint_en": t.hint_en,
        "hint_ne": t.hint_ne,
    }


def check(
    db: Optional[Session], calc_id: Optional[UUID], requires: list[str]
) -> PrereqResult:
    """Evaluate every ``requires`` tag. With no db/calc_id, a tag counts as
    *unmet-generic* (status "partial") unless its capability is missing (🔴)."""
    if not requires:
        return PrereqResult()

    generic = db is None or calc_id is None
    unmet: list[str] = []
    unavailable: list[str] = []
    reasons_en: list[str] = []
    reasons_ne: list[str] = []
    hints_en: list[str] = []
    hints_ne: list[str] = []

    for tag in requires:
        t = _TAGS.get(tag)
        if t is None:
            unmet.append(tag)
            reasons_en.append(f"Unknown prerequisite: {tag}.")
            reasons_ne.append(f"अज्ञात पूर्वसर्त: {tag}।")
            continue
        if t.predicate is None:
            unavailable.append(tag)
            reasons_en.append(t.reason_en)
            reasons_ne.append(t.reason_ne)
            hints_en.append(t.hint_en)
            hints_ne.append(t.hint_ne)
            continue
        if generic:
            # requirement text only — the reference page shows this when the
            # user is not working against a specific forest.
            continue
        # Each predicate runs inside a SAVEPOINT that is always ROLLED BACK.
        #
        # Catching the exception in Python is not enough on its own: several
        # predicates issue raw SQL against national tables that may not exist on a
        # given deployment (`rasters.dem`, `base.mmu` / `soil.soilgrids`,
        # `geology.geology`). A failed statement ABORTS the transaction, and every
        # subsequent query in it then fails with InFailedSqlTransaction — so one
        # missing raster table silently turned every later tag into "unmet" and
        # left the caller's session unusable.
        #
        # `with db.begin_nested()` does NOT fix that, which is the subtle part: the
        # predicates swallow their own database errors, so the block usually exits
        # NORMALLY, and a normally-exiting savepoint is RELEASEd — which cannot
        # succeed while the transaction is aborted. The release raised, the raise
        # was caught as "unmet", and the transaction stayed aborted. The symptom
        # was a readiness read poisoning the caller's session, so the next write in
        # the same request failed with InFailedSqlTransaction.
        #
        # `ROLLBACK TO SAVEPOINT` *is* legal in an aborted transaction and clears
        # the aborted state. These predicates only read, so discarding the
        # savepoint's work unconditionally costs nothing.
        ok = False
        savepoint = None
        try:
            savepoint = db.begin_nested()
            ok = t.predicate(db, calc_id)
        except Exception:  # noqa: BLE001 -- a broken check must not 500 the map
            ok = False
        finally:
            if savepoint is not None:
                try:
                    savepoint.rollback()
                except Exception:  # noqa: BLE001
                    pass
        if not ok:
            unmet.append(tag)
            reasons_en.append(t.reason_en)
            reasons_ne.append(t.reason_ne)
            hints_en.append(t.hint_en)
            hints_ne.append(t.hint_ne)

    if unavailable:
        status = "unavailable"
    elif generic and not unmet:
        # generic view, no missing capability: it *would* need data → amber.
        status = "partial"
        for tag in requires:
            t = _TAGS[tag]
            reasons_en.append(f"Requires: {t.reason_en}")
            reasons_ne.append(f"आवश्यक: {t.reason_ne}")
            hints_en.append(t.hint_en)
            hints_ne.append(t.hint_ne)
    elif unmet:
        status = "partial"
    else:
        status = "available"

    return PrereqResult(
        status=status,
        met=(status == "available"),
        unmet=unmet,
        unavailable=unavailable,
        reason_en=" ".join(dict.fromkeys(reasons_en)),
        reason_ne=" ".join(dict.fromkeys(reasons_ne)),
        hint_en=" ".join(dict.fromkeys(hints_en)),
        hint_ne=" ".join(dict.fromkeys(hints_ne)),
    )


def check_spec(db, calc_id, spec) -> PrereqResult:
    """Convenience: :func:`check` for a :class:`ThematicMapSpec`."""
    return check(db, calc_id, list(getattr(spec, "requires", []) or []))


# back-compat exports for P1 tests
_CHECKS = {
    k: (v.predicate, v.reason_en, v.reason_ne) for k, v in _TAGS.items() if v.predicate
}
NOT_AVAILABLE_TAGS = frozenset(k for k, v in _TAGS.items() if v.predicate is None)
