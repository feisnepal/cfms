"""dbh_class_systems must agree with the definitions in the code (P1, plan D2).

Why this is a hard failure and not a warning
--------------------------------------------
A DBH class boundary decides which class a stem falls into, and every
per-hectare figure downstream is built from those classes. If the table and the
code disagree, the code is not "a bit out of date" -- the report is wrong, and
nothing in the output says so.

The previous behaviour was to catch every failure in `reload_from_db` and fall
back to the code defaults. That is why the drift could go unnoticed: the code
kept working, on the fallback, and produced confident, plausible, correct-looking
numbers. A warning nobody reads is the same as no warning. So D2 says fail fast.

What is compared, and what deliberately is not
----------------------------------------------
Keys, their **order**, and their **ranges**. Not labels: labels are display text,
they are expected to be edited, and they are translated per user. A translated
label is not drift. A moved boundary is.

The comparison runs on the rows just read from the database, never on the cache.
Comparing the cache against the database answers "is the cache stale?" and calls
that drift; comparing a fresh read against a *previously cached* fallback is
stale-vs-fresh and could pass while the table is wrong. Both sides of the
comparison here come from the same moment.
"""
from __future__ import annotations

import copy

import pytest
from sqlalchemy import text

from app.core.dbh_classifier import (
    _FALLBACK_CLASS_DEFS,
    DbhClassDef,
    DbhClassDriftError,
    DbhClassRegistry,
)


def _defs(system: str) -> list[DbhClassDef]:
    return DbhClassRegistry._dicts_to_defs(_FALLBACK_CLASS_DEFS[system])


class TestTheSeededTableAgrees:
    """The guard must pass on the real seeded data, or it is just noise."""

    def test_no_drift_on_the_shipped_systems(self):
        # Exercised in memory first: every shipped system must be self-consistent.
        for system in _FALLBACK_CLASS_DEFS:
            DbhClassRegistry.assert_no_drift({system: _defs(system)})

    def test_the_database_table_agrees_with_the_code(self, db):
        rows = db.execute(
            text("SELECT system_name, class_defs FROM dbh_class_systems "
                 "WHERE is_active = true")
        ).fetchall()
        if not rows:
            pytest.skip("dbh_class_systems is not seeded in this database")
        loaded = {r[0]: DbhClassRegistry._dicts_to_defs(r[1]) for r in rows}
        DbhClassRegistry.assert_no_drift(loaded)


class TestDriftIsCaught:
    """The negative cases are the point. A guard that cannot fail is decoration."""

    def test_a_moved_boundary_is_drift(self):
        system = "guideline_2061"
        drifted = copy.deepcopy(_defs(system))
        # Looked up by key rather than by index, so the test does not depend on
        # the class order staying exactly as it is today -- which is the very
        # thing `test_reordered_classes_are_drift` deliberately changes.
        target = next(d for d in drifted if d.key == "20_30")
        target.lower = 999
        with pytest.raises(DbhClassDriftError) as exc:
            DbhClassRegistry.assert_no_drift({system: drifted})
        assert "range differs" in str(exc.value)
        assert "20_30" in str(exc.value)

    def test_a_renamed_class_is_drift(self):
        system = "guideline_2061"
        drifted = copy.deepcopy(_defs(system))
        drifted[0].key = "seedling_renamed"
        with pytest.raises(DbhClassDriftError) as exc:
            DbhClassRegistry.assert_no_drift({system: drifted})
        assert "keys differ" in str(exc.value)

    def test_a_dropped_class_is_drift(self):
        system = "guideline_2061"
        drifted = copy.deepcopy(_defs(system))[:-1]
        with pytest.raises(DbhClassDriftError):
            DbhClassRegistry.assert_no_drift({system: drifted})

    def test_reordered_classes_are_drift(self):
        """Order matters: these classes are ranges, and ranges have an order.

        Same eight keys, same boundaries, shuffled -- and the report changes,
        because anything that renders them in sequence now reads down the wrong
        column.
        """
        system = "guideline_2061"
        drifted = copy.deepcopy(_defs(system))
        drifted[1], drifted[2] = drifted[2], drifted[1]
        with pytest.raises(DbhClassDriftError) as exc:
            DbhClassRegistry.assert_no_drift({system: drifted})
        assert "keys differ" in str(exc.value)

    def test_an_extra_class_is_drift(self):
        system = "guideline_2061"
        drifted = copy.deepcopy(_defs(system))
        drifted.append(
            DbhClassDef(key="70_plus", lower=70, upper=None,
                        label_en="X", label_np="X")
        )
        with pytest.raises(DbhClassDriftError):
            DbhClassRegistry.assert_no_drift({system: drifted})

    def test_a_system_the_code_does_not_know_is_not_drift(self):
        """An admin-created system is a supported thing, not a defect.

        `dbh_class_systems` has PUT, DELETE, versions and an audit history, so
        creating a system is a supported action. The first version of this check
        raised `DbhClassDriftError` for a system absent from the shipped defaults,
        and that was wrong: it turned "an admin added a custom system" into a 500
        on a read endpoint the app needs on every page. Drift means the code and
        the table disagree about something *both* describe.

        This test exists to hold that correction in place. The existing
        `test_dbh_classes_auth.py` suite caught the original mistake, because its
        `custom_system` fixture inserts exactly such a row.
        """
        unknown = [DbhClassDef(key="a", lower=0, upper=1, label_en="A", label_np="A")]
        DbhClassRegistry.assert_no_drift({"custom_abc123": unknown})

    def test_a_custom_system_alongside_a_drifted_one_still_raises(self):
        """Unknown systems are ignored; real drift among known ones still raises.

        Guards against "fixing" the correction by swallowing everything.
        """
        drifted = copy.deepcopy(_defs("guideline_2061"))
        drifted[0].lower = -5
        unknown = [DbhClassDef(key="a", lower=0, upper=1, label_en="A", label_np="A")]
        with pytest.raises(DbhClassDriftError) as exc:
            DbhClassRegistry.assert_no_drift(
                {"custom_abc123": unknown, "guideline_2061": drifted}
            )
        assert "guideline_2061" in str(exc.value)

    def test_every_offending_system_is_listed_not_just_the_first(self):
        drifted = copy.deepcopy(_defs("guideline_2061"))
        drifted[0].lower = -5
        other = copy.deepcopy(_defs("dfo_export"))
        other[0].upper = 15
        with pytest.raises(DbhClassDriftError) as exc:
            DbhClassRegistry.assert_no_drift(
                {"guideline_2061": drifted, "dfo_export": other}
            )
        message = str(exc.value)
        assert "guideline_2061" in message
        assert "dfo_export" in message


class TestLabelsAreNotDrift:
    """A translated label is not a defect. Failing on it would break i18n."""

    def test_a_changed_label_passes(self):
        system = "guideline_2061"
        relabelled = copy.deepcopy(_defs(system))
        for d in relabelled:
            d.label_np = "बदलियो"  # changed
            d.label_en = "Relabelled"
        DbhClassRegistry.assert_no_drift({system: relabelled})

    def test_a_changed_stand_type_passes(self):
        """stand_type is descriptive grouping, not a boundary.

        It feeds reporting categories, so it is worth noticing if it moves, but
        it does not change which class a stem falls into, so it is not drift.
        """
        system = "guideline_2061"
        restyled = copy.deepcopy(_defs(system))
        for d in restyled:
            d.stand_type = "Something Else"
        DbhClassRegistry.assert_no_drift({system: restyled})


class TestNoHalfUpdatedRegistry:
    """A failed load must not leave a partially-updated cache behind."""

    def test_the_cache_is_not_touched_when_drift_is_found(self, db):
        rows = db.execute(
            text("SELECT system_name, class_defs FROM dbh_class_systems "
                 "WHERE is_active = true")
        ).fetchall()
        if not rows:
            pytest.skip("dbh_class_systems is not seeded in this database")

        # A drifted copy of the table, without touching the real one.
        defs = copy.deepcopy(rows[0][1])
        first = defs[0]
        first["lower"] = 99

        original = DbhClassRegistry._cache
        try:
            DbhClassRegistry._cache = {}
            with pytest.raises(DbhClassDriftError):
                DbhClassRegistry.assert_no_drift(
                    {rows[0][0]: DbhClassRegistry._dicts_to_defs(defs)}
                )
            assert DbhClassRegistry._cache == {}, (
                "the cache was populated despite the drift check failing; a "
                "later caller would read definitions that never passed the check"
            )
        finally:
            DbhClassRegistry._cache = original


class TestEmptyAndUnset:
    def test_no_loaded_systems_is_not_drift(self):
        DbhClassRegistry.assert_no_drift({})

    def test_none_falls_back_to_the_cache_and_passes_when_clean(self):
        original = DbhClassRegistry._cache
        try:
            DbhClassRegistry._cache = {"guideline_2061": _defs("guideline_2061")}
            DbhClassRegistry.assert_no_drift()
        finally:
            DbhClassRegistry._cache = original
