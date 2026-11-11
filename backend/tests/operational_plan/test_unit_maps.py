"""Single-number field-inventory maps for the workspace: the print map's own colours, dynamic legend, user colours on top."""
from types import SimpleNamespace
from uuid import uuid4

from shapely.geometry import box

from app.core import semantic_palettes as sp
from app.services.operational_plan import thematic_overlay as to
from app.services.operational_plan import unit_maps as um
from app.services.operational_plan import user_map_colours as ucm
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS

UNITS = [{"name": n, "geometry": box(i, 0, i + 1, 1)} for i, n in enumerate("ABCDE")]
STOCK = {"A": 5.0, "B": 20.0, "C": 40.0, "D": 60.0, "E": 90.0}
VALUES = {n: {"total_growing_stock_m3_per_ha": v, "forest_condition": c, "working_circle": "production"}
          for (n, v), c in zip(STOCK.items(), ["Good", "Good", "Moderate", "Weak", "Weak"])}


def test_every_workspace_map_is_a_real_unit_level_field_inventory_placeholder():
    for mid, (spec_key, _s) in um.FI_MAPS.items():
        spec = SPECS[spec_key]
        assert spec.layer == "unit" and spec.source == "field_inventory", mid
        assert ucm.SPEC_TO_ANALYSIS[spec_key] == mid


def test_a_sequential_map_uses_the_print_colour_function_and_lists_only_classes_in_use():
    spec = SPECS["unit__growing_stock"]
    r = um.build_unit_map(UNITS, VALUES, spec, "m³/ha")
    feat, _rows = to._colour_map(UNITS, VALUES, spec)  # the print renderer's own answer
    assert {n: u["color"] for n, u in r["units"].items()} == feat
    assert r["state"] == "ready" and r["token"] == "thememap:unit__growing_stock"
    assert sum(entry["count"] for entry in r["legend"]) == 5 and all(entry["count"] > 0 for entry in r["legend"])
    assert r["units"]["C"]["text"] == "40 m³/ha" and r["units"]["A"]["text"] == "5 m³/ha"
    assert not any("०" <= ch <= "९" for entry in r["legend"] for ch in entry["label_en"])  # ordinary digits in English


def test_a_categorical_map_keys_its_legend_by_category_and_follows_the_users_colour():
    spec = SPECS["unit__forest_condition"]
    default = sp.CATEGORICAL[spec.palette]
    r = um.build_unit_map(UNITS, VALUES, spec)
    assert {entry["key"]: entry["count"] for entry in r["legend"]} == {"Good": 2, "Moderate": 1, "Weak": 2}
    assert r["units"]["A"]["color"] == default["Good"]
    mine = spec.model_copy(update={"colour_overrides": {"Weak": "#123456"}})
    r2 = um.build_unit_map(UNITS, VALUES, mine)
    assert r2["units"]["D"]["color"] == "#123456" and r2["units"]["A"]["color"] == default["Good"]
    assert {entry["key"]: entry["color"] for entry in r2["legend"]}["Weak"] == "#123456" and r2["custom_colours"] is True


def test_a_class_colour_the_user_changed_is_used_by_unit_legend_and_print_map():
    spec = SPECS["unit__growing_stock"]
    r = um.build_unit_map(UNITS, VALUES, spec)
    top = max(r["legend"], key=lambda entry: int(entry["key"]))
    mine = spec.model_copy(update={"colour_overrides": {top["key"]: "#00ff00"}})
    r2 = um.build_unit_map(UNITS, VALUES, mine)
    assert r2["units"]["E"]["color"] == "#00ff00"
    assert {entry["key"]: entry["color"] for entry in r2["legend"]}[top["key"]] == "#00ff00"
    feat, _ = to._colour_map(UNITS, VALUES, mine)
    assert feat["E"] == "#00ff00"  # the print renderer draws the same


def test_units_without_a_summary_are_left_out_and_no_summary_at_all_is_no_data():
    r = um.build_unit_map(UNITS, {"A": VALUES["A"]}, SPECS["unit__growing_stock"])
    assert list(r["units"]) == ["A"]
    assert um.build_unit_map(UNITS, {}, SPECS["unit__growing_stock"]) == {"state": "no_data"}


def test_bivariate_legend_is_not_editable():
    vals = {n: {**v, "tree_per_ha": 10.0 * (i + 1), "pole_per_ha": 1.0 * i} for i, (n, v) in enumerate(VALUES.items())}
    r = um.build_unit_map(UNITS, vals, SPECS["unit__condition_x_stocking"])
    assert r["state"] == "ready" and all(entry["editable"] is False for entry in r["legend"])


def test_category_value_keys_are_accepted_as_saved_colours_and_junk_is_not():
    ok = {"mode": "indexed", "colors": {"Weak": "#112233", "3": "#445566", "bad key!": "#000000", "Good": "red"}}
    assert ucm.indexed_overrides(ok) == {"Weak": "#112233", "3": "#445566"}


def test_routes_unknown_map_404_and_nothing_stored_is_not_computed(client, auth_headers, db):
    from sqlalchemy import text

    from app.models.user import User

    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"), {"i": cid, "u": uid})
    db.commit()
    assert client.get(f"/api/calculations/{cid}/unit-maps/unit__nope", headers=auth_headers).status_code == 404
    assert client.get(f"/api/calculations/{cid}/unit-maps/unit__growing_stock", headers=auth_headers).json()["state"] in ("not_computed", "no_data")
    assert client.get(f"/api/calculations/{cid}/field-inventory-units", headers=auth_headers).json()["state"] == "not_computed"


def test_the_values_endpoint_drops_empties_and_rounds(monkeypatch):
    monkeypatch.setattr(
        to, "_load_unit_values",
        lambda db, cid: {"A": {"total_growing_stock_m3_per_ha": 80.123456, "forest_condition": "Weak", "basal_area_m2_per_ha": None}},
    )
    out = um.unit_values(SimpleNamespace(), uuid4())
    row = out["units"]["A"]
    # empties dropped, numbers rounded; the condition also carries its cause (English and Nepali) for the table
    assert {k: v for k, v in row.items() if not k.startswith("fi_condition_why")} == {"fi_stock": 80.12, "fi_condition": "Weak"}
    assert row["fi_condition_why"].startswith("growing stock 80 m³/ha (50–200)")
    assert row["fi_condition_why_ne"]


def test_each_unit_and_each_legend_class_carries_an_area_in_hectares():
    r = um.build_unit_map(UNITS, VALUES, SPECS["unit__growing_stock"], "m³/ha")
    assert all(u["area_ha"] > 0 for u in r["units"].values())
    total = sum(u["area_ha"] for u in r["units"].values())
    assert abs(sum(entry["area_ha"] for entry in r["legend"]) - total) < 0.05  # the classes cover the units exactly once
    cat = um.build_unit_map(UNITS, VALUES, SPECS["unit__forest_condition"])
    by_class = {entry["key"]: entry["area_ha"] for entry in cat["legend"]}
    expect_good = sum(u["area_ha"] for n, u in cat["units"].items() if VALUES[n]["forest_condition"] == "Good")
    assert abs(by_class["Good"] - expect_good) < 0.01


def test_the_condition_reason_map_colours_by_pair_and_says_why():
    from app.services.operational_plan import unit_maps as um
    from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as S

    rec = {"forest_condition": "Moderate", "regeneration_condition": "Weak", "regeneration_per_ha": 1500, "sapling_per_ha": 500,
           "total_growing_stock_m3_per_ha": 85}
    r = um.build_unit_map([{"name": "A", "geometry": None}], {"A": {**rec, "condition_pair": "Moderate|Weak"}}, S["unit__condition_reason"])
    u = r["units"]["A"]
    assert u["text"] == "F Mod · R Weak" and u["color"] == "#fbe08a" and r["legend"][0]["key"] == "Moderate|Weak"
    assert "1,500/ha" in u["reason"] and "≥5,000" in u["reason"] and "50–200" in u["reason"] and "forest Moderate" in u["reason"]
    assert "कमजोर" in u["reason_ne"]


def test_the_pole_tree_map_colours_by_tree_share_and_lists_both_size_groups():
    from app.services.operational_plan import unit_maps as um

    rec = {"pole_per_ha": 300, "tree_per_ha": 80, "pole_total_m3_per_ha": 40.0, "tree_total_m3_per_ha": 120.0,
           "total_growing_stock_m3_per_ha": 160.0, "mai_total_m3_per_ha": 4.8, "aah_total_m3_per_ha": 1.6, "tree_share_pct": 75.0}
    en, _ne = um.pole_tree_detail(rec)
    assert "Poles 10–30 cm: 300 stems/ha · GS 40.0 · MAI 1.20 · AAH 0.40" in en
    assert "Trees 30+ cm: 80 stems/ha · GS 120.0 · MAI 3.60 · AAH 1.20" in en
