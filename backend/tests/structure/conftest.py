"""Pytest wiring for the forest-structure fixtures (see fixtures.py)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests._purge import purge_calculations

from . import fixtures


@pytest.fixture()
def make_forest(db):
    """``make_forest("F4")`` builds a scratch forest; every forest built is removed afterwards.

    The test database is built once per session and ``db.commit()`` persists, so a fixture forest left
    behind would show up as a *neighbour* in later tests (boundary-overlap gate, clipping). Teardown
    removes the calculations and any global potential-activity row a builder created.
    """
    built = []

    def _make(key: str):
        forest = fixtures.build(db, key)
        built.append(forest)
        return forest

    yield _make

    db.rollback()
    purge_calculations(db, [f.calc_id for f in built])
    for f in built:
        for pid in f.created_potential_activity_ids:
            db.execute(
                text("DELETE FROM potential_activities WHERE id = :i"), {"i": pid}
            )
    db.commit()
