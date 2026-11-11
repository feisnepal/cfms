"""Golden-snapshot comparison for the structure work (FS-0.5).

Normal run: build every fixture, snapshot it, compare with ``golden/current.json``. A difference in a
cell listed in ``golden/allowlist.json`` is an *expected change of the current phase* and is reported but
does not fail; any other difference fails.

Re-baseline after a phase (review the diff first!)::

    STRUCTURE_GOLDEN_UPDATE=1 venv/Scripts/python.exe -m pytest tests/structure/test_golden.py

then clear the allowlist. The first run with no golden file also writes it.
"""

from __future__ import annotations

import os

import pytest

from app.models.calculation import Calculation

from . import fixtures, golden

KEYS = list(fixtures.BUILDERS)


@pytest.mark.parametrize("key", KEYS)
def test_golden_snapshot(make_forest, db, key):
    forest = make_forest(key)
    calc = db.query(Calculation).filter(Calculation.id == forest.calc_id).first()
    actual = golden.snapshot(db, calc)

    stored = golden.load_golden()
    if os.environ.get("STRUCTURE_GOLDEN_UPDATE") == "1" or key not in stored:
        stored[key] = actual
        golden.save_golden(stored)
        return

    unexpected, allowed = golden.diff(stored[key], actual, key, golden.load_allowlist())
    if allowed:
        print(
            f"\n{key}: {len(allowed)} allowlisted change(s): {[a[0] for a in allowed]}"
        )
    assert (
        not unexpected
    ), f"{key}: structure output changed outside the allowlist: " + "; ".join(
        f"{probe}: was {was!r}, now {now!r}" for probe, was, now in unexpected
    )
