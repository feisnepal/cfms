"""Natural-key identity for field records (H8.6 · S2-67).

The finding this closes is not "there are duplicates". It is that duplication
in `field_inventory_measurements` was **unmeasurable**: 25,948 rows with `sn`
NULL in every one, a UUID primary key, and 543 plot/species/DBH/height groups
holding more than one row. Two *Shorea robusta* at 24 cm and 18 m in one plot
is ordinary forestry and is also exactly what a replayed sync looks like, and
nothing in the schema could tell them apart.

So the tests that matter here are the ones that would still pass against a
constraint that enforces nothing -- and are written to fail if it does.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.field_inventory import (
    FieldInventoryCalculation,
    FieldInventoryMeasurement,
    FieldInventorySamplePlot,
)

pytestmark = pytest.mark.usefixtures("forget_forests")  # committed forests / rows are purged before and after each test: see conftest (test order is random)


@pytest.fixture()
def owner(db):
    """A user to hang the field-inventory rows off.

    Created here rather than reused from `auth_headers`: that fixture's account
    is shared by the whole suite and one module already broke four unrelated
    authorisation tests by mutating it (see CURRENT_PLAN.md).
    """
    from app.models.user import User

    user = User(
        email=f"naturalkeys-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Natural Keys Fixture",
    )
    db.add(user)
    db.flush()
    return user


def _plot(db, owner, *, block="Block-1", number=1) -> FieldInventorySamplePlot:
    """A sample plot with the parent rows it cannot exist without."""
    from app.models.calculation import Calculation

    # a field inventory belongs to a forest (owner's rule, 2026-09-21; migration 092)
    forest = Calculation(user_id=owner.id, forest_name=f"NK {uuid.uuid4().hex[:6]}")
    db.add(forest)
    db.flush()
    calc = FieldInventoryCalculation(
        status="validated", user_id=owner.id, uploaded_filename="fixture.csv",
        calculation_id=forest.id,
    )
    db.add(calc)
    db.flush()
    plot = FieldInventorySamplePlot(
        field_inventory_calculation_id=calc.id,
        block_name=f"{block}-{uuid.uuid4().hex[:6]}",
        sample_plot_number=number,
        location="SRID=4326;POINT(85.3 27.7)",
    )
    db.add(plot)
    db.flush()
    return plot


def _measure(plot, stand_type="Tree", species="Shorea robusta", **kw):
    return FieldInventoryMeasurement(
        sample_plot_id=plot.id,
        stand_type=stand_type,
        species_scientific=species,
        **kw,
    )


class TestTheConstraintIsReal:
    """A UNIQUE constraint over a nullable column enforces nothing.

    PostgreSQL treats NULLs as distinct, so `UNIQUE (sample_plot_id,
    stand_type, sn)` would have been satisfied by all 25,948 legacy rows while
    stopping nothing at all. That is the shape this repository keeps finding --
    built, reports healthy, guards nothing -- so NOT NULL is asserted directly.
    """

    def test_sn_is_not_nullable(self, db, owner):
        column = next(
            c for c in inspect(db.get_bind()).get_columns("field_inventory_measurements")
            if c["name"] == "sn"
        )
        assert column["nullable"] is False

    def test_both_constraints_exist_in_the_database(self, db, owner):
        found = {
            row[0] for row in db.execute(text("""
                SELECT conname FROM pg_constraint
                WHERE contype = 'u'
                  AND conrelid IN (
                    'field_inventory_measurements'::regclass,
                    'household_information'::regclass)
            """))
        }
        assert "uq_measurement_plot_stand_sn" in found
        assert "uq_household_calculation_house_no" in found


class TestTheModelAgreesWithTheDatabase:
    """A constraint the migration applied and the model does not declare.

    That happened here, and it was invisible: `household_information` defines
    `__table_args__` twice, a class body runs top to bottom, and the second
    assignment silently replaced the first. The constraint reached the database
    through the migration, every behavioural test passed because the database
    enforced it -- and the model carried nothing. `check_schema_drift.py`
    caught it; this keeps it caught without needing the live database to be at
    head.
    """

    @pytest.mark.parametrize("model_path, constraint", [
        ("app.models.field_inventory:FieldInventoryMeasurement",
         "uq_measurement_plot_stand_sn"),
        ("app.models.household_information:HouseholdInformation",
         "uq_household_calculation_house_no"),
    ])
    def test_the_constraint_is_declared_on_the_model(self, model_path, constraint):
        import importlib

        module_name, class_name = model_path.split(":")
        model = getattr(importlib.import_module(module_name), class_name)
        declared = {
            c.name for c in model.__table__.constraints
            if type(c).__name__ == "UniqueConstraint"
        }
        assert constraint in declared, (
            f"{class_name} does not declare {constraint}. If the class defines "
            "__table_args__ more than once, the later one has silently replaced "
            "the earlier."
        )


class TestTheSerialIsAssigned:
    """`sn` was correct from the start and populated in 0 of 25,948 rows.

    It depended on the uploader mapping an SN column, and no upload ever has --
    0 of 20 stored `column_mapping`s carry a `*_sn` key. A field the writer has
    to remember is a field that ends up empty.
    """

    def test_a_new_measurement_gets_one_without_being_asked(self, db, owner):
        plot = _plot(db, owner)
        db.add(_measure(plot))
        db.flush()
        assert db.query(FieldInventoryMeasurement).one().sn == 1

    def test_serials_run_in_sequence_within_a_stand_type(self, db, owner):
        plot = _plot(db, owner)
        for _ in range(3):
            db.add(_measure(plot))
        db.flush()
        serials = sorted(m.sn for m in db.query(FieldInventoryMeasurement).all())
        assert serials == [1, 2, 3]

    def test_a_later_upload_continues_the_sequence(self, db, owner):
        """An incremental add must not restart at 1 and collide."""
        plot = _plot(db, owner)
        db.add(_measure(plot))
        db.flush()
        db.add(_measure(plot))
        db.flush()
        assert sorted(m.sn for m in db.query(FieldInventoryMeasurement).all()) == [1, 2]

    def test_a_supplied_serial_is_kept(self, db, owner):
        """A physical tree tag is identity worth more than a positional number.

        Overwriting it would throw away the only thing that lets a disputed
        measurement be re-checked against the tree in the field.
        """
        plot = _plot(db, owner)
        db.add(_measure(plot, sn=47))
        db.flush()
        assert db.query(FieldInventoryMeasurement).one().sn == 47

    def test_a_plot_assigned_by_relationship_still_gets_a_serial(self, db, owner):
        """`sample_plot_id` may be None while `sample_plot` is set; the FK is
        not populated until flush, so the hook must resolve the id from the
        relationship object itself."""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        plot = _plot(db, owner)
        m = FieldInventoryMeasurement(
            sample_plot=plot,  # relationship, not the FK
            stand_type="Tree",
            species_scientific="Shorea robusta",
        )
        db.add(m)
        db.flush()
        assert m.sn is not None
        db.rollback()

    def test_a_measurement_with_no_plot_is_left_for_the_not_null_guard(self, db, owner):
        """Nothing to scope a serial to -> the row stays `sn=None` and the
        NOT NULL column fails loudly rather than inventing a number."""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        db.add(FieldInventoryMeasurement(
            stand_type="Tree",
            species_scientific="Shorea robusta",
        ))
        with pytest.raises(SAIntegrityError):
            db.flush()
        db.rollback()

    def test_an_assigned_serial_avoids_one_supplied_in_the_same_batch(self, db, owner):
        plot = _plot(db, owner)
        db.add(_measure(plot, sn=1))
        db.add(_measure(plot))
        db.flush()
        assert sorted(m.sn for m in db.query(FieldInventoryMeasurement).all()) == [1, 2]


class TestTheKeyIncludesStandType:
    """The report specifies `UNIQUE (sample_plot_id, sn)`. That would reject
    valid data.

    The upload layout carries four independent serials -- `regen_sn`,
    `sapling_sn`, `pole_sn`, `tree_sn` -- each numbered from 1, and 1,092 of the
    1,105 live plots hold more than one stand type. Without `stand_type` in the
    key, the first plot with both a Pole and a Tree fails to save.
    """

    def test_two_stand_types_may_share_a_serial(self, db, owner):
        plot = _plot(db, owner)
        db.add(_measure(plot, stand_type="Tree", sn=1))
        db.add(_measure(plot, stand_type="Pole", sn=1))
        db.flush()
        assert db.query(FieldInventoryMeasurement).count() == 2

    def test_each_stand_type_is_numbered_from_one(self, db, owner):
        plot = _plot(db, owner)
        db.add(_measure(plot, stand_type="Tree"))
        db.add(_measure(plot, stand_type="Pole"))
        db.flush()
        by_type = {m.stand_type: m.sn for m in db.query(FieldInventoryMeasurement).all()}
        assert by_type == {"Tree": 1, "Pole": 1}


class TestTheDuplicateIsRefused:
    def test_the_same_serial_twice_in_one_plot_and_stand_type(self, db, owner):
        """The row this whole task exists to stop.

        A replayed sync batch inserting the same tree a second time inflates
        stem counts, which propagate through volume, biomass and carbon into a
        document with statutory standing -- and the duplicate is a
        legitimate-looking row that nothing downstream can question.
        """
        plot = _plot(db, owner)
        db.add(_measure(plot, sn=5))
        db.flush()
        db.add(_measure(plot, sn=5))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_the_same_serial_in_a_different_plot_is_fine(self, db, owner):
        first, second = _plot(db, owner, number=1), _plot(db, owner, number=2)
        db.add(_measure(first, sn=1))
        db.add(_measure(second, sn=1))
        db.flush()
        assert db.query(FieldInventoryMeasurement).count() == 2


class TestHouseholds:
    """`house_no` was already NOT NULL and already the key the upload path
    upserts on. It was simply never declared, so nothing stopped a second
    route -- or a replayed sync -- from writing house #14 twice.
    """

    def test_a_duplicate_house_number_is_refused(self, db, owner):
        from app.models.calculation import Calculation
        from app.models.household_information import HouseholdInformation

        calc = Calculation(user_id=owner.id, forest_name="Natural Keys CF")
        db.add(calc)
        db.flush()

        house_no = 9_000 + uuid.uuid4().int % 900
        db.add(HouseholdInformation(
            calculation_id=calc.id, house_no=house_no, surname="Rimal",
            created_by=owner.id,
        ))
        db.flush()
        db.add(HouseholdInformation(
            calculation_id=calc.id, house_no=house_no, surname="Rimal",
            created_by=owner.id,
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestTheErrorIsUsable:
    """A 409 reading "Bad request" tells a user nothing about what to change.

    The handler matches on the CONSTRAINT NAME -- ours, pinned by the migration
    -- rather than on the driver's message, which carries the SQL and bound
    parameters that are deliberately kept out of the response.
    """

    def test_the_constraint_names_map_to_their_own_message(self):
        from app.core.i18n_messages import get_message
        from app.main import _NATURAL_KEY_MESSAGES

        for constraint, code in _NATURAL_KEY_MESSAGES.items():
            entry = get_message(code)
            assert entry["en"] and entry["ne"], constraint
            # The generic fallback is what these exist to replace.
            assert entry["en"] != get_message("general.bad_request")["en"]

    def test_an_unknown_constraint_still_falls_back(self):
        from app.main import _NATURAL_KEY_MESSAGES, _violated_constraint

        class _NoDiag(Exception):
            orig = None

        assert _violated_constraint(_NoDiag()) == ""
        assert _NATURAL_KEY_MESSAGES.get("") is None
