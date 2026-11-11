"""Every workspace chart: same data as its print placeholder, the right shape, and an honest handling of empty / missing data."""
from uuid import uuid4

import pytest
from shapely.geometry import box

from app.core import semantic_palettes as sp
from app.services.operational_plan import field_glyphs as fg
from app.services.operational_plan import thematic_overlay as to
from app.services.operational_plan import user_map_colours as ucm
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS

UNITS = [{"name": n, "geometry": box(i, 0, i + 1, 1)} for i, n in enumerate("ABC")]


def _rec(reg=3000, sap=500, pole=100, tree=80, **over):
    bd = {"0_4": {"count_per_ha": reg, "timber_m3_per_ha": 0}, "4_10": {"count_per_ha": sap, "timber_m3_per_ha": 0},
          "20_30": {"count_per_ha": pole, "timber_m3_per_ha": 10.0}, "40_50": {"count_per_ha": tree, "timber_m3_per_ha": 30.0}}
    return {"total_sample_plots": 5, "dbh_class_breakdown": bd, "regeneration_per_ha": reg, "pole_per_ha": pole, "tree_per_ha": tree,
            "_timber_total": 40.0, "_firewood_total": 20.0, "agb_t_per_ha": 100.0, "bgb_t_per_ha": 25.0,
            "forest_condition": "Good", "regeneration_condition": "Weak", "mai_percent": 3.0,
            "basal_area_m2_per_ha": 18.0, "carbon_stock_tc_per_ha": 60.0, **over}


VALUES = {"A": _rec(), "B": _rec(reg=2000, tree=10, forest_condition="Weak", mai_percent=2.0, basal_area_m2_per_ha=5.0), "C": {"total_sample_plots": 0}}


def _build(slug, values=VALUES, spec=None):
    return fg.build_glyphs(UNITS, values, spec or SPECS[fg.CHARTS[slug]["spec"]], slug)


def test_every_chart_is_bound_to_a_real_unit_level_field_inventory_placeholder():
    assert len(fg.CHARTS) == 11 and fg.KINDS == tuple(fg.CHARTS)
    for slug, meta in fg.CHARTS.items():
        spec = SPECS[meta["spec"]]
        assert spec.layer == "unit" and spec.source == "field_inventory" and spec.viz == meta["kind"].replace("triplebar", "stackbar"), slug
        if meta["kind"] not in ("radar", "sparkline"):
            assert ucm.SPEC_TO_ANALYSIS[meta["spec"]] == meta["id"], slug


@pytest.mark.parametrize("slug", [k for k in fg.CHARTS if k != "species-pie"])  # species has its own tests (test_species_maps)
def test_each_chart_returns_the_units_that_have_a_summary_and_a_legend(slug):
    r = _build(slug)
    assert r["state"] == "ready" and r["kind"] == slug and r["token"] == f"thememap:{fg.CHARTS[slug]['spec']}"
    assert [u["name"] for u in r["units"]] == ["A", "B"] or [u["name"] for u in r["units"]] == ["A", "B", "C"]
    assert r["legend"]


def test_the_components_are_the_print_functions_own_answer():
    r = _build("timber-firewood")
    comps = to._composition("A", VALUES, SPECS["unit__timber_firewood__stackbar"])
    assert [(s["value"], s["color"]) for s in r["units"][0]["segments"]] == [(v, c) for _l, v, c in comps]
    assert [s["label_en"] for s in r["units"][0]["segments"]] == ["Timber", "Firewood"]


def test_the_ternary_always_carries_its_three_corners_even_when_a_part_is_zero():
    vals = {"A": _rec(reg=0, pole=0, tree=50)}
    u = fg.build_glyphs(UNITS, vals, SPECS["unit__regen_pole_tree__ternary"], "regen-pole-tree")
    assert [s["key"] for s in u["units"][0]["segments"]] == ["regeneration_per_ha", "pole_per_ha", "tree_per_ha"]
    assert [c["key"] for c in u["legend"]] == ["regeneration_per_ha", "pole_per_ha", "tree_per_ha"]


def test_the_sparkline_keeps_every_class_so_the_curve_is_a_curve():
    u = _build("reverse-j")["units"][0]
    assert [s["key"] for s in u["segments"]] == list(sp.CATEGORICAL["dbh_classes"].keys())  # zero classes included


def test_the_radar_axes_are_scaled_over_all_units_like_the_print_map():
    r = _build("health-radar")
    a, b = r["units"][0]["radar"], r["units"][1]["radar"]
    assert len(a) == len(b) == len(to._RADAR_AXES) == len(r["legend"])
    assert a[0] == 1.0 and b[0] == 0.0  # condition: Good is the top of the range, Weak the bottom
    assert a[3] == 1.0 and b[3] == 0.0  # basal area: the larger unit is 1, the smaller 0
    assert r["editable"] is False and r["units"][0]["segments"] == []


def test_a_chart_with_user_colours_carries_them_in_units_and_legend():
    spec = SPECS["unit__timber_firewood__stackbar"].model_copy(update={"colour_overrides": {"1": "#123456"}})
    r = fg.build_glyphs(UNITS, VALUES, spec, "timber-firewood")
    assert r["custom_colours"] is True
    assert {s["key"]: s["color"] for s in r["units"][0]["segments"]}["_firewood_total"] == "#123456"
    assert {c["key"]: c["color"] for c in r["legend"]}["_firewood_total"] == "#123456"


def test_compact_labels_say_the_same_thing_at_two_zoom_levels():
    t = _build("timber-by-size")["units"][0]
    assert t["text_short"] == "40" and t["text_long"] == "40 m³/ha · 75% ≥40"
    s = _build("dbh-stems")["units"][0]
    assert s["text_short"] == "3,680" and s["text_long"] == "3,680 stems/ha"
    assert _build("dbh-pie")["units"][0]["text_short"] == ""  # a pie carries no number at low zoom
    b = _build("biomass-split")["units"][0]
    assert b["text_long"] == "125 t/ha · 20% below"


def test_no_summary_at_all_is_no_data():
    assert fg.build_glyphs(UNITS, {}, SPECS["unit__dbh_class_count__pie"], "dbh-pie") == {"state": "no_data", "kind": "dbh-pie"}


def test_the_route_serves_every_slug_and_rejects_others(client, auth_headers, db):
    from sqlalchemy import text

    from app.models.user import User

    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"), {"i": cid, "u": uid})
    db.commit()
    for slug in fg.KINDS:
        got = client.get(f"/api/calculations/{cid}/field-glyphs/{slug}", headers=auth_headers).json()
        assert got["state"] in ("not_computed", "no_data"), slug
    assert client.get(f"/api/calculations/{cid}/field-glyphs/donut", headers=auth_headers).status_code == 404


def test_the_gs_mai_aah_chart_has_three_bars_over_the_six_classes_from_10_cm():
    vals = {"A": {**VALUES["A"], "total_growing_stock_m3_per_ha": 100.0, "mai_total_m3_per_ha": 3.0, "aah_total_m3_per_ha": 1.5}}
    u = _build("dbh-gs-mai-aah", values=vals)["units"][0]
    assert [b["key"] for b in u["bars"]] == ["gs", "mai", "aah"]
    assert all(s["key"] in ("10_20", "20_30", "30_40", "40_50", "50_60", "60_plus") for s in u["bars"][0]["segments"])
    gs, mai, aah = (b["total"] for b in u["bars"])
    assert u["text_long"].startswith("GS ")
    assert gs > 0 and 0 < aah <= mai < gs  # MAI and AAH are a share of the stock, shared out in proportion to it
