"""Per-step workflow readiness. WORKSPACE_FLOW_NAV_PLAN P3, phase 3.

Three things are being tested, and the third is the one that matters most.

1. **The step rules exist and are honest.** A step in the frontend registry with
   no rule here would report "not done" forever and read as the user's problem.
   The registry and `STEP_PREREQS` are cross-checked by a frontend test; here we
   check the rules are well-formed and that `check` is really being consulted.

2. **Completion is delegated, not reimplemented.** `_has_map_complete` and
   `_has_plan_submission` are the two predicates that had no equivalent, and both
   encode a decision worth stating:
     - "map finished" is the owner's definition, and its third clause ("no unsaved
       edits") is *not* server-checkable — it lives in the browser. The predicate
       covers the two clauses it can, and says so.
     - "submitted" means a submission row exists, not that it is current. A plan
       can be submitted, edited and submitted again; both are true records.

3. **Staleness is flagged, never enforced.** `step_flags` marks a step whose
   completion predates a later geometry change. It does not clear the step, does
   not un-complete it, and returns nothing at all when there is no clock to
   compare against.
"""
from __future__ import annotations

import uuid

import pytest

from app.services.operational_plan.workflow_readiness import (
    NON_TRACKED,
    STEP_PREREQS,
    step_flags,
    step_readiness,
    workflow_readiness,
)

# `forest_blocks` has NOT NULL geometry and area, and the geometry column is
# inserted through ST_GeomFromEWKT, so a bare WKT string is what the model wants.
_SQ = "SRID=4326;POLYGON((0 0, 0.001 0, 0.001 0.001, 0 0))"


def _block(calc_id, name, block_name=None, natural_name=None, index=0):
    from app.models.forest_block import ForestBlock

    return ForestBlock(
        calculation_id=calc_id,
        name=name,
        geometry=_SQ,
        area_hectares=1.0,
        index=index,
        block_name=block_name,
        natural_name=natural_name,
    )


@pytest.fixture()
def calc(db):
    from app.models.user import User
    from app.models.calculation import Calculation

    owner = User(
        email=f"wfready-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Workflow Readiness Fixture",
    )
    db.add(owner)
    db.flush()
    c = Calculation(
        user_id=owner.id, forest_name=f"Workflow CF {uuid.uuid4().hex[:6]}", geometry_version=4
    )
    db.add(c)
    db.commit()
    return c


# ── the step rules ────────────────────────────────────────────────────────
def test_every_step_id_matches_the_frontend_registry():
    """A rule naming a step the rail does not show is dead; a step with no rule
    reports "not done" forever. The companion frontend test asserts the other
    direction."""
    frontend_ids = {
        "unified", "usergroup", "fieldbook", "sampling", "fieldinventory", "forestmetadata",
        "biodiversity", "treemapping", "ntfp", "detaildescription", "areadetail",
        "analysis", "hazarderosion", "sustainablefm", "cba", "yearly", "mgmtplan",
        "issuesubmit",
    }
    assert set(STEP_PREREQS) == frontend_ids


def test_no_step_rule_is_empty():
    for step_id, tags in STEP_PREREQS.items():
        assert tags, f"{step_id} has no prerequisite tags and would never complete"


def test_the_trial_page_is_not_tracked():
    # Optional, so "done" is not a state the workflow waits for (D13).
    assert "treemodel" in NON_TRACKED
    assert "treemodel" not in STEP_PREREQS


def test_plan_needs_activities_and_a_drawn_feature():
    # "Desktop work after all data is collected" — activities alone are not
    # enough; the plan draws on the map.
    assert STEP_PREREQS["mgmtplan"] == ("proposed_activities", "activity_drawn_features")


def test_cost_benefit_does_not_depend_on_the_plan():
    # The plan document CONSUMES CBA's output. An earlier draft had this
    # inverted, which would make the flow circular.
    assert "mgmtplan" not in STEP_PREREQS["cba"]


# ── reporting ─────────────────────────────────────────────────────────────
def test_reports_every_step_and_nothing_done_on_an_empty_forest(db, calc):
    out = step_readiness(db, calc.id)
    assert set(out) == set(STEP_PREREQS)
    for step_id, state in out.items():
        assert state["done"] is False, f"{step_id} claims done on an empty forest"
        assert state["status"] in ("available", "partial", "unavailable")
        # Bilingual: an English-only reason would be invisible in Nepali.
        assert isinstance(state["reason_en"], str)
        assert isinstance(state["reason_ne"], str)


def test_never_raises_without_a_database():
    # A readiness strip that 500s takes the workspace down with it.
    out = step_readiness(None, None)
    assert set(out) == set(STEP_PREREQS)
    assert all(s["done"] is False for s in out.values())


def test_workflow_readiness_reports_the_geometry_clock(db, calc):
    out = workflow_readiness(db, calc.id)
    assert out["geometry_version"] == 4
    assert out["map_finished"] is False
    assert out["tracked_count"] == len(STEP_PREREQS)
    assert out["done_count"] == 0
    assert "treemodel" in out["non_tracked"]


# ── the two new predicates ────────────────────────────────────────────────
def test_map_complete_needs_a_boundary_and_named_blocks(db, calc):
    from sqlalchemy import text

    from app.services.operational_plan.prereq_check import _has_map_complete

    # No boundary at all.
    assert _has_map_complete(db, calc.id) is False

    db.execute(
        text("UPDATE calculations SET boundary_geom = ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 0))', 4326) WHERE id = :c"),
        {"c": str(calc.id)},
    )
    db.commit()
    # Boundary but no blocks: vacuously every block is named.
    assert _has_map_complete(db, calc.id) is True

    
    db.add(_block(calc.id, "geom-1", block_name="Block-1"))
    db.commit()
    assert _has_map_complete(db, calc.id) is True

    db.add(_block(calc.id, "geom-2", block_name=None, index=1))
    db.commit()
    assert _has_map_complete(db, calc.id) is False, "an unnamed block means the map is not finished"

    db.add(_block(calc.id, "geom-3", block_name="   ", index=2))
    db.commit()
    assert _has_map_complete(db, calc.id) is False, "whitespace is not a name"


def test_natural_name_does_not_count_as_naming_a_block(db, calc):
    from sqlalchemy import text

    from app.services.operational_plan.prereq_check import _has_map_complete

    db.execute(
        text("UPDATE calculations SET boundary_geom = ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 0))', 4326) WHERE id = :c"),
        {"c": str(calc.id)},
    )
    # `natural_name` is a best-effort geographic label, not the user's serial.
    db.add(_block(calc.id, "geom-1", natural_name="Ridge"))
    db.commit()
    assert _has_map_complete(db, calc.id) is False


def test_plan_submission_predicate(db, calc):
    from app.services.document_integrity import record_submission
    from app.services.operational_plan.prereq_check import _has_plan_submission

    assert _has_plan_submission(db, calc.id) is False
    record_submission(db, submitted_to="District Forest Office", calculation_id=calc.id,
                      reference_no="DFO/1")
    assert _has_plan_submission(db, calc.id) is True


def test_submission_predicate_survives_a_missing_table(monkeypatch):
    """Migration 097 may not have been applied on a given database. That is a
    "not done", never a 500 on the workspace."""
    from app.services.operational_plan.prereq_check import _has_plan_submission

    class _Boom:
        def execute(self, *a, **k):
            raise RuntimeError('relation "document_submissions" does not exist')

    assert _has_plan_submission(_Boom(), uuid.uuid4()) is False


# ── tree mapping: a predicate that could never be true ────────────────────
def test_tree_mapping_is_done_when_a_mapping_record_exists(db, calc):
    """Regression, and the failure was invisible rather than loud.

    This predicate read `result_data['tree_mapping_analysis']`, which nothing
    writes: the OP collector builds that section in memory and caches it in
    `op_data_cache`. So it reported "not done" for every forest — and since P5c
    this signal *locks the Tree Mapping Results pane*, which put the analysis
    tables out of reach with a hint ("run the tree-mapping analysis") pointing at
    an action that does not exist anywhere in the app.

    The assertion that matters is the second one: a forest with a real mapping
    must be done *without* that key, because the key is what was missing.
    """
    from app.models.inventory import InventoryCalculation
    from app.services.operational_plan.prereq_check import _has_tree_mapping

    assert _has_tree_mapping(db, calc.id) is False

    db.add(
        InventoryCalculation(
            calculation_id=calc.id,
            user_id=calc.user_id,
            uploaded_filename="stems.csv",
            status="completed",
        )
    )
    db.commit()

    assert _has_tree_mapping(db, calc.id) is True
    rd = calc.result_data or {}
    assert "tree_mapping_analysis" not in rd, (
        "if this ever becomes true the predicate is reading a different thing "
        "again -- the mapping record is what the pane needs"
    )


def test_tree_mapping_ignores_a_stale_result_data_key(db, calc):
    """The mirror image: the old key must not be able to fake readiness. A
    forest with no mapping stays not-done even if something writes the key."""
    from app.services.operational_plan.prereq_check import _has_tree_mapping
    from app.models.calculation import Calculation

    calc.result_data = {"tree_mapping_analysis": {"sm_total_trees_analyzed": 10}}
    db.commit()

    assert _has_tree_mapping(db, calc.id) is False

    db.query(Calculation).filter(Calculation.id == calc.id).update(
        {Calculation.result_data: None}
    )
    db.commit()


def test_tree_mapping_readiness_reaches_the_step_not_just_the_predicate(db, calc):
    """The predicate alone is not the user-visible symptom; the step is. This
    asserts the wiring so a future refactor cannot leave the predicate correct
    and the step still locked."""
    from app.models.inventory import InventoryCalculation
    from app.services.operational_plan.workflow_readiness import step_readiness

    assert step_readiness(db, calc.id)["treemapping"]["done"] is False

    db.add(
        InventoryCalculation(
            calculation_id=calc.id,
            user_id=calc.user_id,
            uploaded_filename="stems.csv",
            status="completed",
        )
    )
    db.commit()

    state = step_readiness(db, calc.id)["treemapping"]
    assert state["done"] is True
    assert state["status"] == "available"
    assert state["reason_en"] == ""


# ── readiness must not poison the caller's session ────────────────────────
def test_readiness_leaves_the_session_usable_for_later_writes(db, calc):
    """A readiness read is not a read-only operation from the caller's point of
    view: the readiness strip is fetched on workspace load, and the same request
    often goes on to save something.

    Several predicates issue raw SQL against national tables that may be absent
    (`rasters.dem`, `base.mmu` / `soil.soilgrids`, `geology.geology`). A failed
    statement aborts the transaction, and every later statement then fails with
    InFailedSqlTransaction. The savepoint was supposed to absorb that, but the
    predicates swallow their own errors — so the savepoint block exited normally
    and SQLAlchemy tried to RELEASE it, which is illegal in an aborted
    transaction. The release failed, the failure was swallowed as "unmet", and
    the session stayed aborted. This asserts the connection is still usable.
    """
    from app.models.inventory import InventoryCalculation
    from app.services.operational_plan.workflow_readiness import step_readiness

    step_readiness(db, calc.id)

    # Every step ran; the session must still accept a write.
    db.add(
        InventoryCalculation(
            calculation_id=calc.id,
            user_id=calc.user_id,
            uploaded_filename="stems.csv",
            status="completed",
        )
    )
    db.commit()
    assert db.query(InventoryCalculation).filter(
        InventoryCalculation.calculation_id == calc.id
    ).count() == 1


# ── staleness: flag, never enforce ─────────────────────────────────────────
def _ready(**steps):
    return {"steps": {k: {"done": True, "status": "available"} for k in steps}}


def test_flags_a_step_whose_completion_predates_a_geometry_change():
    readiness = {"geometry_version": 9, "steps": {"sampling": {"done": True}}}
    flags = step_flags(readiness, {"sampling": 7})
    assert flags == [{"step": "sampling", "reason": "geometry_changed", "seen": "7"}]


def test_does_not_flag_when_the_version_has_not_moved():
    readiness = {"geometry_version": 7, "steps": {"sampling": {"done": True}}}
    assert step_flags(readiness, {"sampling": 7}) == []


def test_does_not_flag_a_step_that_is_not_done_yet():
    # Nothing to be stale *relative to*.
    readiness = {"geometry_version": 9, "steps": {"sampling": {"done": False}}}
    assert step_flags(readiness, {"sampling": 7}) == []


def test_does_not_flag_a_step_the_server_does_not_know():
    readiness = {"geometry_version": 9, "steps": {}}
    assert step_flags(readiness, {"gone": 1}) == []


def test_no_clock_means_no_flags():
    assert step_flags({"geometry_version": None, "steps": {}}, {"sampling": 1}) == []


def test_staleness_never_clears_completion():
    """The flag is advisory. A stale step is still done — the user decides
    whether to revisit it, which is the whole governing rule."""
    readiness = {"geometry_version": 9, "steps": {"sampling": {"done": True}}}
    flagged = step_flags(readiness, {"sampling": 1})
    assert flagged
    assert readiness["steps"]["sampling"]["done"] is True



def test_forest_metadata_step_needs_every_field_filled(db, calc):
    """Forest Metadata is its own step and the whole form is mandatory (owner, 2026-10-11)."""
    from app.services.forest_metadata_service import EDITABLE_FIELDS
    from app.models.forest_metadata import ForestMetadata
    from app.services.operational_plan.prereq_check import _has_forest_metadata

    assert _has_forest_metadata(db, calc.id) is False  # no record yet
    row = ForestMetadata(calculation_id=calc.id, forest_name="X", group_name="Test CFUG")
    db.add(row)
    db.commit()
    assert _has_forest_metadata(db, calc.id) is False  # most of the form is still empty
    for f in EDITABLE_FIELDS:
        setattr(row, f, "x")
    row.ward = "  "  # whitespace is not an entry
    db.commit()
    assert _has_forest_metadata(db, calc.id) is False
    row.ward = "4"
    db.commit()
    assert _has_forest_metadata(db, calc.id) is True


def test_user_group_step_needs_the_boundary_households_and_the_executive_committee():
    from app.services.operational_plan.workflow_readiness import STEP_PREREQS

    assert STEP_PREREQS["usergroup"] == ("user_group_extent", "household_data", "executive_committee")


def test_household_and_committee_predicates(db, calc):
    from app.models.forest_committee import ForestUserCommittee
    from app.services.operational_plan.prereq_check import _has_executive_committee, _has_household_data

    assert _has_household_data(db, calc.id) is False
    assert _has_executive_committee(db, calc.id) is False
    db.add(ForestUserCommittee(
        calculation_id=calc.id, serial_no=1, gender="पुरूष", position="अध्यक्ष", caste_category="जनजाती", name="Test Chair", address="Test Village",
        created_by=calc.user_id,
    ))
    db.commit()
    assert _has_executive_committee(db, calc.id) is True


# ── the NTFP step (optional, owner 2026-10-22) ────────────────────────────
def test_the_ntfp_step_is_tracked_and_is_done_only_when_survey_records_exist(db, calc):
    """A saved design is a plan for the survey, not the survey: the step turns green when a count has been brought in (zero counts too)."""
    from shapely.geometry import Point
    from geoalchemy2.shape import from_shape

    from app.models.ntfp_method import NtfpObservation, NtfpSamplePlot, NtfpSamplingDesign
    from app.services.operational_plan.prereq_check import _has_ntfp_survey

    assert STEP_PREREQS["ntfp"] == ("ntfp_survey",)
    assert _has_ntfp_survey(db, calc.id) is False
    design = NtfpSamplingDesign(calculation_id=calc.id, plot_shape="square", seed=1, min_plots=3, species=[], layout={}, strata=[], transects={}, warnings=[])
    db.add(design)
    db.flush()
    plot = NtfpSamplePlot(design_id=design.id, plot_number=1, stratum="a", transect=1, location=from_shape(Point(84.0, 28.0), srid=4326), species_keys=["x"])
    db.add(plot)
    db.flush()
    assert _has_ntfp_survey(db, calc.id) is False                          # a design with plots, nothing recorded yet
    assert step_readiness(db, calc.id)["ntfp"]["done"] is False
    db.add(NtfpObservation(plot_id=plot.id, species_key="x", count_total=0))   # looked for, none found: still a record
    db.flush()
    assert _has_ntfp_survey(db, calc.id) is True
    out = step_readiness(db, calc.id)["ntfp"]
    assert out["done"] is True and out["reason_en"] is not None
    db.rollback()


def test_the_ntfp_step_says_in_both_languages_what_to_do_and_that_it_is_optional(db, calc):
    out = step_readiness(db, calc.id)["ntfp"]
    assert out["done"] is False
    assert "optional" in out["hint_en"].lower() and out["hint_ne"] and out["reason_ne"]
