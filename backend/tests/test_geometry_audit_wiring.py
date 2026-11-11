"""Geometry writes are recorded (H8.7 · S2-68).

`geometry_audits` held **0 rows after five months** of production use. The audit
report called that "built, never wired". It was worse, and in four independent
ways -- each of which alone would have produced an empty table:

1. `log_geometry_audit` was wired, but only to
   `POST /calculations/{id}/edit-boundary`, and the frontend's `editBoundary()`
   is called by no component. The one audited path was dead.
2. The function had never inserted a row in its life. `:prev_geom::jsonb` made
   SQLAlchemy's bind parser stop at the first colon pair, so PostgreSQL received
   `:prev_geom` unsubstituted and answered `syntax error at or near ":"`.
3. It inserted into a `metadata` column the table does not have.
4. `ALLOWED_LAYER_TYPES` rejected `boundary`, `compartments` and
   `sub_compartments` -- three of the five names the write path uses -- and
   `log_geometry_audit` RAISES on an unknown type, so wiring it naively would
   have taken down the first boundary edit a user attempted.

The audit is now taken in `_write_geometry`, the single point every geometry
write in `editing.py` passes through, rather than at twelve endpoints that must
each remember.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.request_context import RequestIdentity, reset_identity, set_identity
from app.services.audit_service import ALLOWED_LAYER_TYPES, log_geometry_audit


@pytest.fixture()
def owner(db):
    from app.models.user import User

    user = User(
        email=f"audit-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Audit Fixture",
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def calc(db, owner):
    from app.models.calculation import Calculation

    c = Calculation(user_id=owner.id, forest_name=f"Audit CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    return c


def _audit_rows(db, calc_id) -> list:
    return db.execute(text("""
        SELECT layer_type, operation, feature_id, previous_geometry,
               new_geometry, user_id, new_properties
        FROM geometry_audits WHERE calculation_id = :c ORDER BY id
    """), {"c": str(calc_id)}).fetchall()


class TestTheFunctionWorksAtAll:
    """It never had. Every call raised before reaching PostgreSQL's planner."""

    def test_a_row_can_be_written(self, db, calc, owner):
        audit_id = log_geometry_audit(
            db=db, calculation_id=str(calc.id), layer_type="blocks",
            operation="UPDATE", feature_id="f1", previous_geometry=None,
            new_geometry={"type": "Point", "coordinates": [84.1, 28.3]},
            user_id=str(owner.id), metadata={"probe": True},
        )
        assert isinstance(audit_id, int)
        rows = _audit_rows(db, calc.id)
        assert len(rows) == 1
        db.rollback()

    def test_the_layer_types_the_write_path_uses_are_accepted(self, db, calc, owner):
        """`compartments` and `boundary` used to raise ValueError.

        `log_geometry_audit` raises on an unknown layer type, so this was not a
        cosmetic mismatch -- it would have failed the user's write.
        """
        for layer in ("boundary", "blocks", "compartments", "sub_compartments", "sub_areas"):
            assert layer in ALLOWED_LAYER_TYPES, layer
            log_geometry_audit(
                db=db, calculation_id=str(calc.id), layer_type=layer,
                operation="UPDATE", feature_id="f", previous_geometry=None,
                new_geometry={"type": "Point", "coordinates": [84.0, 28.0]},
                user_id=str(owner.id),
            )
        assert len(_audit_rows(db, calc.id)) == 5
        db.rollback()

    def test_the_before_and_after_are_both_stored(self, db, calc, owner):
        """An audit that cannot say what changed only records that something did."""
        before = {"type": "Point", "coordinates": [84.0, 28.0]}
        after = {"type": "Point", "coordinates": [84.5, 28.5]}
        log_geometry_audit(
            db=db, calculation_id=str(calc.id), layer_type="blocks",
            operation="UPDATE", feature_id="f1",
            previous_geometry=before, new_geometry=after, user_id=str(owner.id),
        )
        row = _audit_rows(db, calc.id)[0]
        assert row[3]["coordinates"] == [84.0, 28.0]
        assert row[4]["coordinates"] == [84.5, 28.5]
        db.rollback()


class TestItRecordsWhoAndFromWhere:
    def test_identity_reaches_the_audit_row(self, db, calc, owner):
        """The point of the request context: `_write_geometry` is four frames
        below the endpoint and has no Request."""
        from app.api.editing import _audit_geometry_write

        token = set_identity(RequestIdentity(
            user_id=str(owner.id), ip_address="10.9.8.7",
            client_type="mobile", user_agent="CFMS-Field/2.1",
        ))
        try:
            _audit_geometry_write(
                db, calc, "compartments", "feat-9", None,
                {"type": "Point", "coordinates": [84.2, 28.2]},
            )
        finally:
            reset_identity(token)

        rows = _audit_rows(db, calc.id)
        assert len(rows) == 1
        props = rows[0][6] or {}
        assert props.get("ip_address") == "10.9.8.7"
        assert props.get("client_type") == "mobile"
        assert props.get("correlation_id")      # H3.9 ties the row to its logs
        db.rollback()

    def test_no_user_means_no_row_rather_than_a_false_one(self, db, calc):
        """`geometry_audits.user_id` is NOT NULL.

        Inventing a user to satisfy the constraint would put a false name on a
        permanent record, which is worse than the gap it papers over.
        """
        from app.api.editing import _audit_geometry_write

        token = set_identity(RequestIdentity(ip_address="10.0.0.1"))
        try:
            _audit_geometry_write(db, calc, "blocks", "f", None,
                                  {"type": "Point", "coordinates": [84.0, 28.0]})
        finally:
            reset_identity(token)
        assert _audit_rows(db, calc.id) == []


class TestItNeverBreaksTheWrite:
    """The trade S2-68 names: an audit that can fail the operation it records is
    worse than no audit."""

    def test_a_broken_audit_does_not_propagate(self, db, calc, owner, monkeypatch):
        from app.api import editing

        def _boom(**_kw):
            raise RuntimeError("audit table is on fire")

        monkeypatch.setattr(
            "app.services.audit_service.log_geometry_audit", _boom, raising=True)

        token = set_identity(RequestIdentity(user_id=str(owner.id)))
        try:
            # Must not raise.
            editing._audit_geometry_write(
                db, calc, "blocks", "f", None,
                {"type": "Point", "coordinates": [84.0, 28.0]})
        finally:
            reset_identity(token)

    def test_an_unreadable_previous_geometry_does_not_stop_the_write(self, db, calc):
        """`_read_geometry_for_audit` runs BEFORE a write the user asked for."""
        from app.api.editing import _read_geometry_for_audit

        assert _read_geometry_for_audit(db, calc, "blocks", "not-a-uuid") is None


class TestThePreviousGeometryIsActuallyRead:
    """The `previous` side of the audit row is the code the diff gate found
    least covered: only the missing-blocks branch was ever exercised. The
    boundary and sub_areas branches -- and the present-geometry branches of
    both -- never ran in a test."""

    def test_boundary_previous_geometry_is_read(self, db, owner):
        from sqlalchemy import func
        from app.api.editing import _read_geometry_for_audit
        from app.models.calculation import Calculation

        WKT = "POLYGON((84.0 28.0, 84.1 28.0, 84.1 28.1, 84.0 28.1, 84.0 28.0))"
        c = Calculation(
            user_id=owner.id, forest_name=f"AuditB {uuid.uuid4().hex[:6]}",
            boundary_geom=func.ST_GeomFromText(WKT, 4326),
        )
        db.add(c)
        db.commit()

        prev = _read_geometry_for_audit(db, c, "boundary", "boundary")
        assert prev is not None
        assert prev["coordinates"][0][0][0] == 84.0

    def test_boundary_with_no_geometry_is_none(self, db, calc):
        from app.api.editing import _read_geometry_for_audit

        assert _read_geometry_for_audit(db, calc, "boundary", "boundary") is None

    def test_sub_area_previous_geometry_is_read(self, db, owner):
        from sqlalchemy import func
        from app.api.editing import _read_geometry_for_audit
        from app.models.calculation import Calculation
        from app.models.forest_sub_area import ForestSubArea

        c = Calculation(user_id=owner.id, forest_name=f"AuditS {uuid.uuid4().hex[:6]}")
        db.add(c)
        db.commit()
        WKT = "POLYGON((84.0 28.0, 84.1 28.0, 84.1 28.1, 84.0 28.1, 84.0 28.0))"
        sub = ForestSubArea(
            calculation_id=c.id,
            name="Conservation",
            category="conservation",
            area_hectares=1.2,
            geometry=func.ST_GeomFromText(WKT, 4326),
        )
        db.add(sub)
        db.commit()

        prev = _read_geometry_for_audit(db, c, "sub_areas", str(sub.id))
        assert prev is not None
        assert prev["coordinates"][0][0][0] == 84.0

    def test_sub_area_with_no_matching_row_is_none(self, db, calc):
        from app.api.editing import _read_geometry_for_audit

        assert _read_geometry_for_audit(db, calc, "sub_areas", str(uuid.uuid4())) is None


class TestTheWiringItself:
    def test_the_single_write_point_audits(self):
        """Pins WHERE the audit is taken.

        Moving it back to the endpoints would restore the original defect: an
        audit that must be remembered twelve times is remembered some of them.
        """
        import inspect

        from app.api.editing import _write_geometry

        src = inspect.getsource(_write_geometry)
        assert "_audit_geometry_write" in src
        assert "_read_geometry_for_audit" in src

    def test_every_persist_helper_goes_through_it(self):
        """If a persist helper stopped calling `_write_geometry`, its endpoints
        would silently stop being audited."""
        import inspect

        from app.api import editing

        for name in ("_persist_geometry", "_persist_geometry_batch"):
            src = inspect.getsource(getattr(editing, name))
            assert "_write_geometry" in src, f"{name} no longer writes through the audited path"
