"""The workspace's field-inventory chart: same numbers / classes / colours as the print placeholder, any class may be empty."""
from types import SimpleNamespace
from uuid import uuid4

from shapely.geometry import box

from app.core import semantic_palettes as sp
from app.services.operational_plan import field_glyphs as fg
from app.services.operational_plan import thematic_overlay as to
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS

SPEC = SPECS[fg.SPEC_KEY]
KEYS = list(sp.CATEGORICAL["dbh_classes"].keys())


def _rec(timber: dict, plots=5):
    return {"total_sample_plots": plots, "dbh_class_breakdown": {k: {"timber_m3_per_ha": v, "count_per_ha": 1} for k, v in timber.items()}}


UNITS = [
    {"name": "A", "geometry": box(0, 0, 1, 1)},
    {"name": "B", "geometry": box(1, 0, 2, 1)},
    {"name": "C", "geometry": box(2, 0, 3, 1)},  # no field inventory at all
    {"name": "D", "geometry": box(3, 0, 4, 1)},
]
VALUES = {
    "A": _rec({"20_30": 10.0, "30_40": 20.0, "40_50": 30.0}),  # 60 total, 30 of it >= 40 cm
    "B": _rec({"20_30": 5.0}),                                  # young: nothing >= 40 cm
    "D": _rec({}),                                              # a summary, but no timber
}


def test_the_numbers_totals_and_share_at_or_above_40_cm():
    r = fg.build_timber_glyphs(UNITS, VALUES, SPEC)
    by = {u["name"]: u for u in r["units"]}
    assert r["state"] == "ready" and sorted(by) == ["A", "B", "D"]  # C has no summary: left out
    assert by["A"]["total_m3_per_ha"] == 60.0 and by["A"]["ge40_pct"] == 50.0
    assert [s["key"] for s in by["A"]["segments"]] == ["20_30", "30_40", "40_50"]
    assert by["B"]["ge40_pct"] == 0.0
    assert by["D"]["total_m3_per_ha"] == 0.0 and by["D"]["ge40_pct"] is None and by["D"]["segments"] == []
    assert r["max_total"] == 60.0


def test_a_class_the_forest_does_not_have_never_appears_anywhere():
    r = fg.build_timber_glyphs(UNITS, VALUES, SPEC)
    assert [c["key"] for c in r["legend"]] == ["20_30", "30_40", "40_50"]  # 0_4, 4_10, 10_20, 50_60, 60_plus: absent, no hole
    full = fg.build_timber_glyphs(UNITS, {"A": _rec({k: 1.0 for k in KEYS})}, SPEC)
    assert [c["key"] for c in full["legend"]] == KEYS  # and any class appears the moment it has timber


def test_the_colours_are_the_placeholders_and_follow_the_users_own():
    default = sp.CATEGORICAL["dbh_classes"]
    r = fg.build_timber_glyphs(UNITS, VALUES, SPEC)
    assert {s["key"]: s["color"] for s in r["units"][0]["segments"]} == {k: default[k] for k in ("20_30", "30_40", "40_50")}
    assert r["custom_colours"] is False
    mine = SPEC.model_copy(update={"colour_overrides": {str(KEYS.index("40_50")): "#123456"}})
    r2 = fg.build_timber_glyphs(UNITS, VALUES, mine)
    seg = {s["key"]: s["color"] for s in r2["units"][0]["segments"]}
    assert seg["40_50"] == "#123456" and seg["30_40"] == default["30_40"] and r2["custom_colours"] is True
    assert {c["key"]: c["color"] for c in r2["legend"]}["40_50"] == "#123456"  # the legend follows too


def test_the_print_placeholder_draws_the_same_colours():
    mine = SPEC.model_copy(update={"colour_overrides": {"5": "#123456"}})
    comps = to._composition("A", VALUES, mine)  # the print map's own function
    assert comps[5][2] == "#123456" and comps[4][2] == sp.CATEGORICAL["dbh_classes"][KEYS[4]]


def test_the_chart_colour_choice_is_read_like_the_hazard_ones():
    saved = {"analysis:chart_timber": {"mode": "indexed", "colors": {"5": "#123456"}}}

    class _Q:
        def filter(self, *a, **k): return self
        def first(self): return SimpleNamespace(result_data={"layer_renderers": saved})

    class _Db:
        def query(self, *a, **k): return _Q()

    out = to._with_user_colours(_Db(), uuid4(), SPEC)
    assert out.colour_overrides == {"5": "#123456"}


def test_no_units_means_no_data_not_an_error():
    assert fg.build_timber_glyphs(UNITS, {}, SPEC) == {"state": "no_data", "kind": "timber-by-size"}


def test_route_unknown_kind_404_and_not_computed_for_a_forest_without_inventory(client, auth_headers, db):
    from sqlalchemy import text

    from app.models.user import User

    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"), {"i": cid, "u": uid})
    db.commit()
    assert client.get(f"/api/calculations/{cid}/field-glyphs/pie", headers=auth_headers).status_code == 404
    got = client.get(f"/api/calculations/{cid}/field-glyphs/timber-by-size", headers=auth_headers).json()
    assert got["state"] in ("not_computed", "no_data")
