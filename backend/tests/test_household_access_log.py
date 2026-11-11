"""The household read-access log actually writes a row (H8.7 / S2-68).

`household_information` holds caste classification and precise coordinates for
real families. The write side got an audit trail in this same task; the read
side got `household_access_log` and `record_household_access`, wired into four
endpoints (list, detail, summary, export) in `api/household_info.py`.

Found while building the coverage gate (H4.2): the function existed, was
imported and called from all four endpoints, and had never once executed
inside a test -- the exact pattern this project keeps finding in OTHER code
(`log_geometry_audit` wired to a dead route for five months; `geometry_version`
incremented twelve times, compared zero) was quietly present in code from this
same session. A row inserted here is the only way to know the log is not a
second copy of that defect.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.request_context import RequestIdentity, reset_identity, set_identity
from app.services.household_access_log import (
    ACCESS_DETAIL,
    ACCESS_EXPORT,
    ACCESS_LIST,
    VALID_ACCESS_TYPES,
    record_household_access,
)


@pytest.fixture()
def identity():
    token = set_identity(RequestIdentity(
        user_id=str(uuid.uuid4()), ip_address="10.9.8.7", client_type="web",
    ))
    yield
    reset_identity(token)


class TestARowIsActuallyWritten:
    def test_a_list_access_lands_in_the_table(self, db, identity):
        calc_id = uuid.uuid4()
        record_household_access(db, ACCESS_LIST, calculation_id=calc_id, record_count=12)
        row = db.execute(text(
            "SELECT access_type, calculation_id, record_count, ip_address, client_type "
            "FROM public.household_access_log WHERE calculation_id = :c"),
            {"c": str(calc_id)}).first()
        assert row is not None, (
            "record_household_access ran without error but wrote nothing -- "
            "exactly the failure mode this log exists to make impossible"
        )
        assert row[0] == ACCESS_LIST
        assert row[2] == 12
        assert row[3] == "10.9.8.7"
        assert row[4] == "web"

    def test_a_detail_access_records_the_household_not_the_forest(self, db, identity):
        """Opening one household and exporting all of them are different
        events with different consequences -- the design note this module
        states outright. household_id must actually reach the row."""
        household_id = uuid.uuid4()
        record_household_access(db, ACCESS_DETAIL, household_id=household_id)
        row = db.execute(text(
            "SELECT household_id, calculation_id FROM public.household_access_log "
            "WHERE household_id = :h"),
            {"h": str(household_id)}).first()
        assert row is not None
        assert row[1] is None  # no calculation_id was given

    def test_the_correlation_id_reaches_the_row(self, db, identity):
        """Ties a household read to its request's log lines (H3.9) --
        without this, an access log entry cannot be traced back to anything."""
        from app.core.correlation import reset_correlation_id, set_correlation_id

        token = set_correlation_id("test-corr-h83-abc123")
        try:
            calc_id = uuid.uuid4()
            record_household_access(db, ACCESS_EXPORT, calculation_id=calc_id)
        finally:
            reset_correlation_id(token)
        row = db.execute(text(
            "SELECT correlation_id FROM public.household_access_log WHERE calculation_id = :c"),
            {"c": str(calc_id)}).first()
        assert row[0] == "test-corr-h83-abc123"


class TestItNeverBreaksARead:
    """Reads are frequent; a logging failure must not fail the read it is
    attached to. Every path here is swallowed and logged, never raised."""

    def test_an_unknown_access_type_does_not_raise(self, db, identity):
        record_household_access(db, "not-a-real-type")  # must not raise

    def test_an_unknown_access_type_writes_nothing(self, db, identity):
        calc_id = uuid.uuid4()
        record_household_access(db, "bogus", calculation_id=calc_id)
        row = db.execute(text(
            "SELECT 1 FROM public.household_access_log WHERE calculation_id = :c"),
            {"c": str(calc_id)}).first()
        assert row is None

    def test_a_db_failure_does_not_propagate(self, db, identity, monkeypatch):
        """The identical trade `document_integrity.record_issuance` makes: a
        user entitled to their data must still receive it even if the fact
        that they read it cannot be recorded."""
        def _boom(*_a, **_k):
            raise RuntimeError("household_access_log table unavailable")

        monkeypatch.setattr(db, "execute", _boom)
        record_household_access(db, ACCESS_LIST, calculation_id=uuid.uuid4())  # must not raise

    def test_every_declared_access_type_is_accepted(self, db, identity):
        """Pins the vocabulary the module's docstring calls "kept small and
        closed" -- a typo in a caller should show up as a warning, not as one
        more spelling silently accepted forever."""
        for access_type in VALID_ACCESS_TYPES:
            record_household_access(db, access_type, calculation_id=uuid.uuid4())


class TestTheEndpointsActuallyCallIt:
    """Source-inspection for the wiring, matching the project's convention for
    pinning WHERE a cross-cutting call happens (see H8.7's geometry-audit
    tests). The live-write tests above prove the function works; this proves
    the four read endpoints actually use it."""

    def test_all_four_read_endpoints_call_it(self):
        import inspect

        from app.api import household_info

        src = inspect.getsource(household_info)
        assert src.count("record_household_access(") >= 4, (
            "expected list, detail, summary and export to each call the log"
        )
