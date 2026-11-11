"""`dbh_class_keys.json` is what the database actually holds.

DBH_SSOT_PLAN P4. The plan's second test is "every class key the API returns has a
`dbhClass.*` label in both `en` and `ne`", and that test has to live in the
frontend, where the bundles are. Which leaves it unable to see the table it is
about -- a frontend test can only check the keys it was handed, so the moment
somebody adds a class to `dbh_class_systems` and changes nothing else, the
frontend suite stays green and renders an untranslated class.

So the join needs a contract artefact: `dbh_class_keys.json` at the repo root,
holding each system's keys and bounds and **no labels**. This module is what makes
it trustworthy -- it asserts the fixture against the live table, so the fixture
cannot go stale without a backend test failing. Labels are deliberately absent
from the fixture, because a fixture carrying them would be a second copy of the
words, and the bundle is meant to be the only place they live.

Two things are asserted, and the second is the one that was actually broken:

1. keys, order and bounds match the table, per system, so a new class or a moved
   boundary fails here;
2. **every class in every system has a non-empty `label_en` and `label_np`.**
   This is not a formality. `validation` was the only one of the five systems
   with no Nepali labels at all -- 4 of 4 empty -- so a Nepali user opening that
   picker saw four blank rows until migration `104` filled them. A test that only
   checked structure would have passed straight through that, because a class with
   no label is structurally perfectly valid.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "dbh_class_keys.json"
# The five systems `SYSTEM_ORDER` in app/core/dbh_classifier.py serves.
EXPECTED_SYSTEMS = {
    "guideline_2061",
    "guideline_simple",
    "harvesting_cfmg",
    "dfo_export",
    "validation",
}

# The system the frontend renders a class list from, per plan D4.
RENDERED_SYSTEM = "guideline_2061"


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    assert FIXTURE_PATH.exists(), f"{FIXTURE_PATH} is missing; P4 needs it"
    with io.open(FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def table(db) -> dict[str, list[dict[str, Any]]]:
    """Every system in `dbh_class_systems`, as the API serves it.

    Function-scoped, because `conftest.db` is -- a module-scoped fixture cannot
    depend on it, and pytest says so loudly rather than quietly sharing a session.
    """
    from sqlalchemy import text

    rows = db.execute(
        text("SELECT system_name, class_defs FROM dbh_class_systems ORDER BY id")
    ).mappings()
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        defs = row["class_defs"]
        if isinstance(defs, str):
            defs = json.loads(defs)
        out[row["system_name"]] = list(defs)
    return out


def test_fixture_covers_exactly_the_five_systems(fixture):
    assert set(fixture) == EXPECTED_SYSTEMS, (
        "the fixture and the table disagree about which systems exist; "
        f"fixture={sorted(fixture)}"
    )


def test_fixture_carries_no_labels(fixture):
    """A label in the fixture would be a second copy of the words."""
    for name, system in fixture.items():
        for cls in system["classes"]:
            assert set(cls) == {"key", "lower", "upper"}, f"{name}.{cls.get('key')}"


def test_keys_and_bounds_match_the_table(fixture, table):
    for name, system in fixture.items():
        expected = [
            {"key": c["key"], "lower": c["lower"], "upper": c["upper"]}
            for c in system["classes"]
        ]
        actual = [
            {"key": c["key"], "lower": c["lower"], "upper": c["upper"]}
            for c in table[name]
        ]
        assert actual == expected, (
            f"{name} has drifted from dbh_class_keys.json.\n"
            f"  fixture: {expected}\n  table:   {actual}\n"
            "Regenerate the fixture, and if a class was added, add its i18n key "
            "to en.json and ne.json -- the frontend test will not see this one."
        )


def test_order_matches_too(fixture, table):
    """Bounds alone are not enough: the UI renders classes in the table's order."""
    for name, system in fixture.items():
        assert [c["key"] for c in table[name]] == [c["key"] for c in system["classes"]], (
            f"{name} class order differs between the fixture and the table"
        )


def test_every_class_has_both_labels(table):
    """The defect migration 104 fixed, asserted so it cannot come back.

    A class with an empty `label_np` is structurally fine, so a structure-only
    check passes over it -- and a Nepali user sees a blank row in the picker.
    """
    empty: list[str] = []
    for name, defs in table.items():
        for cls in defs:
            key = cls["key"]
            if not (cls.get("label_en") or "").strip():
                empty.append(f"{name}.{key}.label_en")
            if not (cls.get("label_np") or "").strip():
                empty.append(f"{name}.{key}.label_np")
    assert not empty, (
        "classes with no label -- a Nepali user sees a blank row for each:\n  "
        + "\n  ".join(sorted(empty))
    )


def test_rendered_system_is_the_one_the_frontend_joins_on(fixture):
    """`guideline_2061` is the join; the other four are rendered from API labels.

    The five systems reuse key *names* for different bands -- `regeneration` is
    0-10 cm in `harvesting_cfmg` and 1-4 cm in `validation` -- so one
    `dbhClass.<name>` i18n key cannot serve them all. This test exists to make
    that reasoning checkable rather than a comment nobody re-reads.
    """
    assert RENDERED_SYSTEM in fixture
    assert fixture[RENDERED_SYSTEM]["classes"], "the rendered system has no classes"

    regeneration = {c["upper"] for c in fixture["harvesting_cfmg"]["classes"] if c["key"] == "regeneration"}
    assert regeneration == {10}, "CFMG regeneration is expected to end at 10 cm"

    no_timber = [
        c["key"]
        for c in fixture[RENDERED_SYSTEM]["classes"]
        if c["upper"] is not None and c["upper"] <= 10
    ]
    assert no_timber == ["0_4", "4_10"], (
        "the classes carrying no harvestable volume changed; the frontend derives "
        "this set from CFMG's regeneration bound and must be told"
    )
