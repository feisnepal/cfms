"""Forest production-water rule tests — gear WEST (most complex gear).

Categories: main, multi, fishing. Rules per category: 40 (rate / ratio / tally
mix). Plus 2 complex fuelwood rules and 2 complex timber rules. Every rule is
tested across variants: normal, no-quoted, no-inventory, empty, word (Nepali),
TFC/class, offset/digit.

Runnable with plain pytest: `python -m pytest backend/tests/gear_rules`.
"""
import pytest

from ._cfmg_rules import (
    GearRules,
    parse_nepali_num,
    type_test,
    make_item,
)

GEAR = GearRules(
    gear="west",
    categories={"main": "main_category", "multi": "multi", "fishing": "fishing"},
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _main_row(stems=10, mult1=0, mult2=0, **kw):
    return {"stems": stems, "numerator": 1, "denominator": 2,
            "main_category": 1, "multi": mult1, "fishing": mult2, **kw}


def _empty(**kw):
    return {"main_category": 0, "multi": 0, "fishing": 0, **kw}


_EXPECT_SEQ = [0]


def _expect(item, rule, category, indicator, tier, *quotes):
    # unique store key per call so identical rule ids never collide in the cache
    _EXPECT_SEQ[0] += 1
    probe = dict(item, id=f"{rule}::{category}::{_EXPECT_SEQ[0]}")
    indicator = float(indicator)
    val, got_tier, got_quotes = GEAR.evaluate(probe, rule, category)
    assert val == pytest.approx(indicator, abs=1e-3), (item["id"], rule, category, val)
    assert got_tier == tier, (item["id"], rule, category, val)
    for q in quotes:
        assert any(q in qq for qq in got_quotes), (item["id"], rule, category, val, q)
    type_test(val, got_tier, got_quotes)


# ---------------------------------------------------------------------------
# rule catalogs (40 per category)
# ---------------------------------------------------------------------------
MAIN_RULES = [("m%02d" % i, kind) for i, kind in enumerate(
    ["rate"] * 24 + ["ratio"] * 8 + ["tally"] * 8)]
MULTI_RULES = [("ml%02d" % i, kind) for i, kind in enumerate(
    ["rate"] * 24 + ["ratio"] * 8 + ["tally"] * 8)]
FISH_RULES = [("f%02d" % i, kind) for i, kind in enumerate(
    ["rate"] * 24 + ["ratio"] * 8 + ["tally"] * 8)]
ALL_RULE_SETS = [("main", MAIN_RULES), ("multi", MULTI_RULES), ("fishing", FISH_RULES)]
FLAT_RULES = [(cat, rid, kind) for cat, rset in ALL_RULE_SETS for rid, kind in rset]

GEAR.register({cat: rset for cat, rset in ALL_RULE_SETS})
GEAR.register(
    {"fishing": [("fw1", "tally"), ("fw2", "ratio")],
     "main": [("tm1", "tfc"), ("tm2", "tfc")]}
)


@pytest.mark.parametrize("category,rule_id,kind", FLAT_RULES)
def test_40_rules_each_with_variants(category, rule_id, kind):
    """Every rule x category: normal / no-quoted / no-inventory / empty / Nepali word."""
    cat_field = GEAR.categories[category]
    rate = GEAR.rates[category]

    def row(**kw):
        base = {"stems": 10, "numerator": 1, "denominator": 2, cat_field: 1}
        base.update(kw)
        return base

    items = {
        "normal": make_item("n", [row(stems=10)]),
        "no_quoted": make_item("q", [row(stems=None, quoted_volume=None)]),
        "no_inv": make_item("i", [dict(row(), stems=0)]),
        "empty": make_item("e", []),
        "word": make_item("w", [row(stems=None, word="बीस")]),
    }
    for name, item in items.items():
        val, tier, quotes = GEAR.lookup(item, rule_id, category)
        assert isinstance(val, float) and isinstance(tier, int) and isinstance(quotes, list)
        if name == "normal":
            if kind == "rate":
                assert val == pytest.approx(10 * rate, abs=1e-3) and tier == 1
            elif kind == "tally":
                assert val == pytest.approx(10, abs=1e-3) and tier == 1
            else:
                assert val == pytest.approx(0.5, abs=1e-3) and tier == 2
        elif name == "word":
            if kind in ("rate", "tally"):
                assert val == pytest.approx(20 * (rate if kind == "rate" else 1), abs=1e-3)
                assert tier == 1
            else:
                assert val == pytest.approx(0.5, abs=1e-3) and tier == 2
        elif name == "empty":
            assert val == 0.0 and tier == 3
        else:  # no_quoted / no_inv
            assert val == 0.0 and tier == 3
            assert any(q in ("NO_QUOTED", "NO_INVENTORY") for q in quotes)


# ---------------------------------------------------------------------------
# 40 explicit main rules — rate kind (m01..m24)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "rate"])
def test_main_rate_rules_value(rule_id):
    item = make_item(rule_id, [_main_row(stems=50, main_category=1)])
    _expect(item, rule_id, "main", 50 * GEAR.rates["main"], 1, "MAIN_RATE")


@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "rate"])
def test_main_rate_rules_no_quoted(rule_id):
    item = make_item(rule_id, [_main_row(stems=None, quoted_volume=None, main_category=1)])
    _expect(item, rule_id, "main", 0.0, 3, "NO_QUOTED")


@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "rate"])
def test_main_rate_rules_no_inventory(rule_id):
    item = make_item(rule_id, [_empty()])
    _expect(item, rule_id, "main", 0.0, 3, "NO_INVENTORY")


@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "rate"])
def test_main_rate_rules_empty(rule_id):
    _expect(make_item(rule_id, []), rule_id, "main", 0.0, 3)


@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "rate"])
def test_main_rate_rules_word_nepali(rule_id):
    item = make_item(rule_id, [_main_row(stems=None, word="तीस", main_category=1)])
    _expect(item, rule_id, "main", 30 * GEAR.rates["main"], 1)


@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "rate"])
def test_main_rate_rules_devanagari_digit_word(rule_id):
    item = make_item(rule_id, [_main_row(stems=None, word="१२", main_category=1)])
    _expect(item, rule_id, "main", 12 * GEAR.rates["main"], 1)


@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "rate"])
def test_main_rate_rules_offset_digit_rounding(rule_id):
    # 3-stem rows: stems=3 -> 0.06 but a stray 7th stem -> 3*7=21 -> /3 digit check
    item = make_item(rule_id, [_main_row(stems=7, main_category=1)])
    expected = round(7 * GEAR.rates["main"], 3)
    _expect(item, rule_id, "main", expected, 1)


# ---------------------------------------------------------------------------
# 40 explicit main rules — ratio kind (m25..m32)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "ratio"])
def test_main_ratio_rules_value(rule_id):
    rows = [_main_row(numerator=30, denominator=10, main_category=1)]
    _expect(make_item(rule_id, rows), rule_id, "main", 3.0, 2, "MAIN_RATIO")


@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "ratio"])
def test_main_ratio_rules_zero_denominator(rule_id):
    rows = [_main_row(numerator=5, denominator=0, main_category=1)]
    _expect(make_item(rule_id, rows), rule_id, "main", 0.0, 3, "NO_QUOTED")


# ---------------------------------------------------------------------------
# 40 explicit main rules — tally kind (m33..m40)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "tally"])
def test_main_tally_rules_value(rule_id):
    rows = [_main_row(stems=4, main_category=1), _main_row(stems=6, main_category=1)]
    _expect(make_item(rule_id, rows), rule_id, "main", 10.0, 1, "MAIN_TALLY")


@pytest.mark.parametrize("rule_id", [rid for rid, k in MAIN_RULES if k == "tally"])
def test_main_tally_rules_empty(rule_id):
    _expect(make_item(rule_id, []), rule_id, "main", 0.0, 3)


# ---------------------------------------------------------------------------
# multi rules (40) — a representative full sweep on ml01 rate
# ---------------------------------------------------------------------------
def test_multi_rate_value():
    _expect(make_item("ml01", [_main_row(stems=100, multi=1)]), "ml01", "multi",
            100 * GEAR.rates["multi"], 1, "MULTI_RATE")


def test_multi_rate_devnagari_word():
    item = make_item("ml01", [_main_row(stems=None, word="पचास", multi=1)])
    _expect(item, "ml01", "multi", 50 * GEAR.rates["multi"], 1)


def test_multi_rate_no_inventory():
    _expect(make_item("ml01", [_empty()]), "ml01", "multi", 0.0, 3, "NO_INVENTORY")


def test_multi_rate_no_quoted():
    item = make_item("ml01", [_main_row(stems=None, quoted_volume=None, multi=1)])
    _expect(item, "ml01", "multi", 0.0, 3, "NO_QUOTED")


def test_multi_ratio_value():
    rows = [_main_row(numerator=40, denominator=80, multi=1)]
    _expect(make_item("ml25", rows), "ml25", "multi", 0.5, 2, "MULTI_RATIO")


def test_multi_ratio_zero_denominator():
    rows = [_main_row(numerator=40, denominator=0, multi=1)]
    _expect(make_item("ml25", rows), "ml25", "multi", 0.0, 3)


def test_multi_tally_value():
    rows = [_main_row(stems=2, multi=1), _main_row(stems=8, multi=1)]
    _expect(make_item("ml33", rows), "ml33", "multi", 10.0, 1, "MULTI_TALLY")


# ---------------------------------------------------------------------------
# fishing rules (40) — f01 rate sweep + f25 ratio + f33 tally
# ---------------------------------------------------------------------------
def test_fishing_rate_value():
    _expect(make_item("f01", [_main_row(stems=200, fishing=1)]), "f01", "fishing",
            200 * GEAR.rates["fishing"], 1, "FISHING_RATE")


def test_fishing_rate_word():
    item = make_item("f01", [_main_row(stems=None, word="एक", fishing=1)])
    _expect(item, "f01", "fishing", 1 * GEAR.rates["fishing"], 1)


def test_fishing_rate_no_quoted():
    item = make_item("f01", [_main_row(stems=None, quoted_volume=None, fishing=1)])
    _expect(item, "f01", "fishing", 0.0, 3, "NO_QUOTED")


def test_fishing_ratio_value():
    rows = [_main_row(numerator=10, denominator=25, fishing=1)]
    _expect(make_item("f25", rows), "f25", "fishing", 0.4, 2)


def test_fishing_ratio_zero_denominator():
    rows = [_main_row(numerator=10, denominator=0, fishing=1)]
    _expect(make_item("f25", rows), "f25", "fishing", 0.0, 3)


def test_fishing_tally_value():
    rows = [_main_row(stems=5, fishing=1), _main_row(stems=5, fishing=1)]
    _expect(make_item("f33", rows), "f33", "fishing", 10.0, 1)


# ---------------------------------------------------------------------------
# complex rules — fuelwood (2)
# ---------------------------------------------------------------------------
FUELWOOD = [("fw1", "tally"), ("fw2", "ratio")]


@pytest.mark.parametrize("rule_id,kind", FUELWOOD)
def test_fuelwood_rules_shape(rule_id, kind):
    rows = [_main_row(stems=12, fishing=1)]
    val, tier, quotes = GEAR.lookup(make_item(rule_id, rows), rule_id, "fishing")
    type_test(val, tier, quotes)


def test_fuelwood_tally_multi_rows():
    rows = [_main_row(stems=9, fishing=1), _main_row(stems=9, fishing=1)]
    _expect(make_item("fw1", rows), "fw1", "fishing", 18.0, 1)


def test_fuelwood_ratio_harvestable_share():
    rows = [_main_row(numerator=60, denominator=100, fishing=1)]
    _expect(make_item("fw2", rows), "fw2", "fishing", 0.6, 2)


# ---------------------------------------------------------------------------
# complex rules — timber (2)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rule_id", ["tm1", "tm2"])
def test_timber_rules_shape(rule_id):
    rows = [_main_row(stems=4, main_category=1, area_ha=1.0, forest_class=1)]
    val, tier, quotes = GEAR.lookup(make_item(rule_id, rows), rule_id, "main")
    type_test(val, tier, quotes)


def test_timber_tfc_class1():
    rows = [_main_row(area_ha=5.0, forest_class=1, main_category=1)]
    _expect(make_item("tm1", rows), "tm1", "main", 5.0 * GEAR.tfc[1], 1, "TFC_CLASS_1")


def test_timber_tfc_class2_offset():
    rows = [_main_row(area_ha=5.0, forest_class=2, main_category=1)]
    _expect(make_item("tm2", rows), "tm2", "main", 5.0 * GEAR.tfc[2], 1,
            "TFC_CLASS_2", "CLASS_2_FACTOR")


def test_timber_tfc_no_quoted_volume():
    rows = [_main_row(area_ha=2.0, forest_class=1, quoted_volume=None, main_category=1)]
    _expect(make_item("tm1", rows), "tm1", "main", 2.0 * GEAR.tfc[1], 1, "NO_QUOTED")


# ---------------------------------------------------------------------------
# dimension tests
# ---------------------------------------------------------------------------
def test_dimension_rules_per_category_40():
    for category, rules in ALL_RULE_SETS:
        assert len(rules) == 40, category


def test_dimension_count_table_width_matches_rows():
    gear2 = GearRules(gear="west", categories=GEAR.categories)
    gear2.load([make_item("A", [_main_row(stems=1, main_category=1)]),
                make_item("B", [_main_row(stems=2, multi=1, main_category=0)]),
                make_item("C", [_main_row(stems=3, fishing=1, main_category=0)])])
    table = gear2.get_count_table("main")
    assert table == {"A": 1, "B": 0, "C": 0}


def test_dimension_item_field_lengths():
    item = make_item("x", [_main_row(stems=1, main_category=1)] * 7)
    assert len(item["rows"]) == 7
    for row in item["rows"]:
        assert len(row) >= 5  # stems/numerator/denominator/categories + extras


# ---------------------------------------------------------------------------
# store / lookup semantics
# ---------------------------------------------------------------------------
def test_store_lookup_recompute_equals_cached():
    item = make_item("store1", [_main_row(stems=20, main_category=1)])
    first = GEAR.lookup(item, "m01", "main")
    second = GEAR.lookup(item, "m01", "main")
    assert first == second
    val, tier, _ = first
    assert val == pytest.approx(20 * GEAR.rates["main"])


def test_store_isolated_per_key():
    a = make_item("isoA", [_main_row(stems=5, main_category=1)])
    b = make_item("isoB", [_main_row(stems=5, main_category=1)])
    va, ta, _ = GEAR.lookup(a, "m01", "main")
    vb, tb, _ = GEAR.lookup(b, "m02", "main")
    assert ta == tb == 1
    assert va == vb


# ---------------------------------------------------------------------------
# type tests
# ---------------------------------------------------------------------------
def test_type_indicator_float_tier_int_quotes_list():
    for category, rules in ALL_RULE_SETS:
        for rid, kind in rules[:3]:
            val, tier, quotes = GEAR.lookup(
                make_item(f"t-{category}-{rid}", [_main_row(stems=2)]), rid, category)
            type_test(val, tier, quotes)


def test_type_nepali_parser_roundtrip():
    for word, expected in [("बीस", 20), ("१२", 12), ("शून्य", 0), ("सय", 100)]:
        assert parse_nepali_num(word) == expected