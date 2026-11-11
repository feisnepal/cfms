"""A submitted document is recorded, and the record cannot be quietly edited.

WORKSPACE_FLOW_NAV_PLAN P1, owner decisions D8 and D17.

`document_issuances` (migration 059) records that bytes were produced — a
sha256, a quotable verification code, and provenance binding the figures to the
geometry version and inventory runs behind them. It records nothing about what
happened next. A plan could be exported, printed, handed to a District Forest
Office, and the system could not tell that from a plan downloaded three times and
never submitted.

Three things are worth testing here beyond "the row is written":

1. **The append-only posture is real, not a convention.** Migration 059 installs
   RULES refusing UPDATE and DELETE. This table installs the same, and a test that
   does not attempt the write cannot tell the difference.
2. **A bad channel is rejected loudly.** `record_issuance` deliberately swallows
   its own failure, because denying somebody a document they are entitled to is
   worse than an unrecorded issuance. A submission is the opposite: the user has
   just asserted that a cycle is closed. Silently dropping it would leave them
   believing the work is submitted when the system has no record of it.
3. **`plan.status` is NOT touched.** Per D17 the status projection is P6's job.
   If a test here asserted it, P6 would have nothing left to do and the two
   writers would already have drifted.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services.document_integrity import list_submissions, record_submission


@pytest.fixture()
def owner(db):
    from app.models.user import User

    user = User(
        email=f"subm-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Submission Fixture",
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def plan(db, owner):
    from app.models.calculation import Calculation
    from app.models.operational_plan import OperationalPlan

    calc = Calculation(
        user_id=owner.id, forest_name=f"Submission CF {uuid.uuid4().hex[:6]}"
    )
    db.add(calc)
    db.flush()
    op = OperationalPlan(calculation_id=calc.id, forest_name=calc.forest_name, status="draft")
    db.add(op)
    db.commit()
    return op


# ── writing ───────────────────────────────────────────────────────────────
def test_records_a_submission(db, plan):
    new_id = record_submission(
        db, submitted_to="District Forest Office", plan_id=plan.id,
        calculation_id=plan.calculation_id, reference_no="DFO/2083/114",
    )
    assert new_id is not None
    row = db.execute(
        text("SELECT submitted_to, channel, reference_no, plan_id FROM public.document_submissions WHERE id = :i"),
        {"i": str(new_id)},
    ).first()
    assert row[0] == "District Forest Office"
    assert row[1] == "hand_delivery"  # the statutory route is a printed copy
    assert row[2] == "DFO/2083/114"
    assert str(row[3]) == str(plan.id)


def test_default_channel_is_hand_delivery(db, plan):
    new_id = record_submission(db, submitted_to="DFO", plan_id=plan.id)
    assert db.execute(
        text("SELECT channel FROM public.document_submissions WHERE id = :i"),
        {"i": str(new_id)},
    ).first()[0] == "hand_delivery"


def test_blank_reference_is_stored_as_null_not_empty_string(db, plan):
    """An empty string would read as "the office gave us a blank reference"."""
    new_id = record_submission(db, submitted_to="DFO", plan_id=plan.id, reference_no="   ")
    assert db.execute(
        text("SELECT reference_no FROM public.document_submissions WHERE id = :i"),
        {"i": str(new_id)},
    ).first()[0] is None


def test_rejects_an_unknown_channel(db, plan):
    with pytest.raises(ValueError, match="unknown submission channel"):
        record_submission(db, submitted_to="DFO", plan_id=plan.id, channel="carrier-pigeon")


def test_rejects_a_blank_receiving_office(db, plan):
    with pytest.raises(ValueError, match="submitted_to is required"):
        record_submission(db, submitted_to="   ", plan_id=plan.id)


def test_rejection_does_not_write_a_row(db, plan):
    before = _count(db)
    with pytest.raises(ValueError):
        record_submission(db, submitted_to="", plan_id=plan.id)
    assert _count(db) == before


def _count(db) -> int:
    return db.execute(text("SELECT count(*) FROM public.document_submissions")).scalar() or 0


# ── append-only ───────────────────────────────────────────────────────────
def test_update_is_refused(db, plan):
    """Same posture as document_issuances: a RULE, not a convention."""
    new_id = record_submission(db, submitted_to="DFO", plan_id=plan.id, reference_no="ORIGINAL")
    db.execute(
        text("UPDATE public.document_submissions SET reference_no = 'TAMPERED' WHERE id = :i"),
        {"i": str(new_id)},
    )
    db.commit()
    assert db.execute(
        text("SELECT reference_no FROM public.document_submissions WHERE id = :i"),
        {"i": str(new_id)},
    ).first()[0] == "ORIGINAL"


def test_delete_is_refused(db, plan):
    new_id = record_submission(db, submitted_to="DFO", plan_id=plan.id)
    db.execute(text("DELETE FROM public.document_submissions WHERE id = :i"), {"i": str(new_id)})
    db.commit()
    assert db.execute(
        text("SELECT count(*) FROM public.document_submissions WHERE id = :i"),
        {"i": str(new_id)},
    ).scalar() == 1


# ── reading ───────────────────────────────────────────────────────────────
def test_lists_newest_first(db, plan):
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for i in range(3):
        record_submission(
            db, submitted_to=f"Office {i}", plan_id=plan.id,
            reference_no=f"REF-{i}", submitted_at=base + timedelta(days=i),
        )
    rows = list_submissions(db, plan_id=plan.id)
    assert [r["reference_no"] for r in rows] == ["REF-2", "REF-1", "REF-0"]


def test_lists_are_scoped_to_the_plan(db, plan):
    other_id = record_submission(db, submitted_to="Somewhere else", plan_id=None)
    record_submission(db, submitted_to="This office", plan_id=plan.id)
    rows = list_submissions(db, plan_id=plan.id)
    assert len(rows) == 1
    assert rows[0]["submitted_to"] == "This office"
    assert str(other_id) not in {r["id"] for r in rows}


def test_empty_list_not_an_error(db, plan):
    assert list_submissions(db, plan_id=plan.id) == []


def test_list_never_raises_on_a_broken_query():
    """A read must not 500 the page that shows whether a cycle is closed.

    Uses a stub session rather than monkeypatching `Session.execute`, which would
    mutate the class globally and break every other lazy load in the run.
    """
    class _Boom:
        def execute(self, *a, **k):
            raise RuntimeError("connection lost")

    assert list_submissions(_Boom(), plan_id=None) == []


# ── the D17 boundary ──────────────────────────────────────────────────────
def test_recording_a_submission_does_not_touch_plan_status(db, plan):
    """P1 records the fact. The `status` projection is P6's, and only P6's.

    If this ever starts passing because `record_submission` set `status`, then
    P6 has two writers for one field and they will drift.
    """
    assert plan.status == "draft"
    record_submission(db, submitted_to="DFO", plan_id=plan.id)
    db.refresh(plan)
    assert plan.status == "draft", (
        "status must stay a projection written in one place (P6), not a side "
        "effect of recording the row"
    )


# ── the documented delete-rule exception ──────────────────────────────────
def test_table_is_a_documented_forest_delete_exception():
    """`scripts/report_orphans.py` and the schema-rule test read this dict; a new
    exception is an owner decision, so the reason has to be present."""
    from app.core.forest_delete_rules import FOREST_DELETE_EXCEPTIONS

    assert "document_submissions" in FOREST_DELETE_EXCEPTIONS
    reason = FOREST_DELETE_EXCEPTIONS["document_submissions"]
    assert "097" in reason and "reference" in reason.lower()


# ── regression guard ──────────────────────────────────────────────────────
def test_endpoint_name_does_not_shadow_the_service_function():
    """The GET endpoint is `list_plan_submissions` on purpose.

    Naming it `list_submissions` binds the module-level name to the endpoint, and
    the endpoint body — which calls the service — then recurses into itself. It
    type-checks, lints as a duplicate rather than an error, and fails at runtime
    on first call. Guard the binding directly.
    """
    from app.api import operational_plans as api

    assert api.list_plan_submissions is not api.list_submissions
    assert api.list_submissions is list_submissions
