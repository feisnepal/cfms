"""GET /dbh-classes/systems must serve every system, in full, from the table (P2).

What was wrong
--------------
The endpoint returned `system_name` and `class_count` and nothing else, so there
was nothing in the response to render a control from. That is why the frontend
carries its own hardcoded class arrays in `constants/dbhClasses.ts` -- not
oversight, but the only way to get the data. Worse, the endpoint took no database
session and read the constants in `dbh_classifier.py`, so an API documented as
database-backed was serving code.

So the test asserts the two things that would each independently have caught it:

  * the response carries full class definitions, and
  * they came from `dbh_class_systems`, asserted **against the table** rather than
    against the code, because a test that compares the API to the same constants
    the API used to serve would pass against the old implementation.

`harvesting_cfmg` is included deliberately (plan D6): it is the CFMG harvest
grouping -- Regeneration / Advance Growth / Mature Tree -- and it is the one the
owner works in, so it must not be the one filtered out.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.dbh_classifier import DbhClassRegistry

# The five systems, with their expected class keys. Asserted against the table
# below as well as against the response, so a change to either is visible.
EXPECTED_SYSTEMS = {
    "guideline_2061": ["0_4", "4_10", "10_20", "20_30", "30_40", "40_50", "50_60", "60_plus"],
    "dfo_export": ["10_20", "20_30", "30_40", "40_50", "50_60", "60_plus"],
    "harvesting_cfmg": ["regeneration", "advance_growth", "mature_tree"],
    "guideline_simple": ["seedling", "sapling", "pole", "tree"],
    "validation": ["regeneration", "sapling", "pole", "tree"],
}

# The order the endpoint serves them in (see SYSTEM_ORDER).
EXPECTED_ORDER = [
    "guideline_2061",
    "dfo_export",
    "harvesting_cfmg",
    "guideline_simple",
    "validation",
]


@pytest.fixture()
def systems(client, auth_headers):
    # The registry caches for 5 minutes, so without this a row created or deleted
    # by an earlier test lingers in the response and these assertions depend on
    # test order. The cache is an optimisation; a test asserting what the endpoint
    # returns must not be at the mercy of it.
    DbhClassRegistry.invalidate_cache()
    r = client.get("/api/dbh-classes/systems", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


def _table_keys(db) -> dict[str, list[str]]:
    rows = db.execute(
        text("SELECT system_name, class_defs FROM dbh_class_systems "
             "WHERE is_active = true")
    ).fetchall()
    return {r[0]: [d.get("key") for d in (r[1] or [])] for r in rows}


class TestAllFiveSystems:
    def test_returns_the_five_shipped_systems(self, systems):
        """The five the plan names, all present.

        Asserted by membership rather than by `len == 5`, because
        `dbh_class_systems` has admin CRUD and a test fixture in
        `test_dbh_classes_auth.py` inserts a `custom_*` row into the session
        database and never removes it. A hardcoded count would make this suite
        order-dependent for a reason that has nothing to do with what it tests.
        """
        names = {s["system_name"] for s in systems}
        for expected in EXPECTED_SYSTEMS:
            assert expected in names, f"{expected} missing from the response"

    def test_returns_every_system_the_table_has(self, systems, db):
        table = _table_keys(db)
        assert {s["system_name"] for s in systems} == set(table), (
            "the response and the table disagree about which systems exist"
        )

    def test_a_custom_system_does_not_break_the_endpoint(self, db, client, auth_headers):
        """A user-created system must be served, not rejected as drift.

        `dbh_class_systems` supports admin CRUD, so an extra system is a supported
        state. The drift check initially raised on any system the code had no
        fallback for, which turned this into a 500 on a read endpoint the app needs
        on every page -- and was caught by `test_dbh_classes_auth.py`, whose
        fixture creates exactly this.
        """
        DbhClassRegistry.invalidate_cache()
        name = "custom_drift_probe"
        db.execute(
            text(
                "INSERT INTO dbh_class_systems "
                "(system_name, version, description, class_defs, is_active, is_system_default) "
                "VALUES (:n, '1.0', 'probe', CAST(:c AS jsonb), true, false)"
            ),
            {
                "n": name,
                "c": '[{"key":"a","lower":0,"upper":10,'
                     '"label_en":"A","label_np":"A"}]',
            },
        )
        db.commit()
        try:
            r = client.get("/api/dbh-classes/systems", headers=auth_headers)
            assert r.status_code == 200, r.text
            served = {s["system_name"] for s in r.json()}
            assert name in served, "a custom system must be served, not dropped"
        finally:
            db.execute(
                text("DELETE FROM dbh_class_systems WHERE system_name = :n"), {"n": name}
            )
            db.commit()

    @pytest.mark.parametrize("system", sorted(EXPECTED_SYSTEMS))
    def test_each_system_has_its_expected_keys(self, systems, system):
        got = next(s for s in systems if s["system_name"] == system)
        assert [c["key"] for c in got["classes"]] == EXPECTED_SYSTEMS[system]

    def test_harvesting_cfmg_is_exposed(self, systems):
        """Plan D6. The CFMG harvest grouping must not be the filtered-out one."""
        got = next(
            (s for s in systems if s["system_name"] == "harvesting_cfmg"), None
        )
        assert got is not None, "harvesting_cfmg missing from the response"
        assert [c["key"] for c in got["classes"]] == [
            "regeneration", "advance_growth", "mature_tree",
        ]


class TestTheResponseMatchesTheTable:
    """Asserted against the table, not against the code the API used to serve."""

    def test_keys_match_the_table(self, systems, db):
        table = _table_keys(db)
        for s in systems:
            assert [c["key"] for c in s["classes"]] == table[s["system_name"]], (
                f"{s['system_name']}: response keys differ from the table"
            )

    def test_class_count_matches_the_classes_actually_sent(self, systems):
        for s in systems:
            assert s["class_count"] == len(s["classes"]), (
                f"{s['system_name']}: class_count says {s['class_count']} but "
                f"{len(s['classes'])} classes were sent. A count that "
                "contradicts its own payload is worse than no count."
            )


class TestCompleteEnoughToRenderFrom:
    """Everything a renderer needs, per class, and nothing it must guess."""

    REQUIRED = ("key", "lower", "upper", "label_en", "label_np", "stand_type")

    def test_every_class_carries_every_field(self, systems):
        for s in systems:
            for c in s["classes"]:
                missing = [k for k in self.REQUIRED if k not in c]
                assert not missing, f"{s['system_name']}/{c.get('key')}: missing {missing}"

    def test_stand_type_is_present_where_the_system_defines_it(self, systems):
        by_system = {s["system_name"]: s for s in systems}
        for key in ("0_4", "4_10", "10_20", "30_40", "40_50"):
            cls = next(c for c in by_system["guideline_2061"]["classes"] if c["key"] == key)
            assert cls["stand_type"], f"guideline_2061/{key} has no stand_type"

    def test_an_open_top_class_sends_upper_as_null_not_missing(self, systems):
        by_system = {s["system_name"]: s for s in systems}
        top = next(
            c for c in by_system["guideline_2061"]["classes"] if c["key"] == "60_plus"
        )
        assert "upper" in top
        assert top["upper"] is None, (
            "the top class has no upper bound; that must arrive as null so the UI "
            "can tell 'unbounded' from 'incomplete'"
        )

    def test_labels_are_present_in_both_languages(self, systems):
        for s in systems:
            for c in s["classes"]:
                assert c["label_en"], f"{s['system_name']}/{c['key']} has no label_en"
                assert c["label_np"], f"{s['system_name']}/{c['key']} has no label_np"

    def test_ranges_are_ordered_and_non_overlapping(self, systems):
        for s in systems:
            prev_upper = None
            for c in s["classes"]:
                assert c["lower"] is not None
                if prev_upper is not None:
                    assert c["lower"] >= prev_upper, (
                        f"{s['system_name']}: {c['key']} starts at {c['lower']} "
                        f"but the previous class ended at {prev_upper}"
                    )
                prev_upper = c["upper"]


class TestOrdering:
    def test_systems_come_back_in_the_canonical_order(self, systems):
        # Only the shipped systems are orderable. `dbh_class_systems` supports
        # admin CRUD, so an extra system is a legitimate state and is appended
        # rather than slotted into the order -- see DbhClassRegistry._ordered_systems.
        known = [
            s["system_name"] for s in systems if s["system_name"] in EXPECTED_ORDER
        ]
        assert known == EXPECTED_ORDER, f"shipped systems out of order: {known}"

    def test_order_is_stable_across_calls(self, client, auth_headers):
        first = client.get("/api/dbh-classes/systems", headers=auth_headers).json()
        second = client.get("/api/dbh-classes/systems", headers=auth_headers).json()
        assert [s["system_name"] for s in first] == [s["system_name"] for s in second]

    def test_classes_within_a_system_keep_their_order(self, systems):
        # These are ranges; a reordered list still "looks right" in a test that
        # only compares sets, and renders wrong in a table.
        by_system = {s["system_name"]: s for s in systems}
        keys = [c["key"] for c in by_system["guideline_2061"]["classes"]]
        assert keys == EXPECTED_SYSTEMS["guideline_2061"]


class TestSingleSystemRoute:
    def test_one_system_returns_the_same_classes_as_the_list(self, client, auth_headers):
        listed = client.get("/api/dbh-classes/systems", headers=auth_headers).json()
        one = client.get(
            "/api/dbh-classes/systems/harvesting_cfmg", headers=auth_headers
        )
        assert one.status_code == 200, one.text
        from_list = next(s for s in listed if s["system_name"] == "harvesting_cfmg")
        assert one.json()["classes"] == from_list["classes"], (
            "the list and the single-system route disagree, so the UI would show "
            "one thing in a picker and another when a system is selected"
        )

    def test_unknown_system_is_a_404(self, client, auth_headers):
        r = client.get("/api/dbh-classes/systems/nope", headers=auth_headers)
        assert r.status_code == 404
