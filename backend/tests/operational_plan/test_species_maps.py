"""Species per unit: the data, the two new map variables, the dynamic palette, the workspace map and chart."""
from uuid import uuid4

from shapely.geometry import box

from app.core import semantic_palettes as sp
from app.services.operational_plan import field_glyphs as fg
from app.services.operational_plan import thematic_overlay as to
from app.services.operational_plan import unit_maps as um
from app.services.operational_plan import unit_species as us
from app.services.operational_plan import user_map_colours as ucm
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS

DOM = SPECS["unit__species_dominant"]
PIE = SPECS["unit__species_composition__pie"]
UNITS = [{"name": n, "geometry": box(i, 0, i + 1, 1)} for i, n in enumerate("ABC")]


def _shares(*pairs):
    return us.shares_from_rows([{"sci": s, "local": l, "vol": v, "n": 1} for s, l, v in pairs])


A = _shares(("Shorea robusta", "Sal, Sakhu", 60.0), ("Terminalia alata", "Saj, Asna", 40.0))
B = _shares(("Terminalia alata", "Saj, Asna", 70.0), ("Shorea robusta", "Sal, Sakhu", 30.0))
C = _shares(*[(f"Genus{i} sp", None, 10.0 - i) for i in range(8)])  # eight species: more than the pie names
VALUES = {n: {"total_sample_plots": 4, "species_shares": sh, "dominant_species": sh[0]["key"]} for n, sh in zip("ABC", (A, B, C))}


def test_the_new_map_variables_exist_on_the_page_with_descriptions():
    for key in ("unit__species_dominant", "unit__species_composition__pie"):
        spec = SPECS[key]
        assert spec.section == "S5" and spec.source == "field_inventory" and spec.layer == "unit"
        assert spec.description_en and spec.description_ne and spec.label_en and spec.label_ne


def test_shares_are_by_volume_with_the_first_local_name_and_a_stable_key():
    assert [(s["key"], s["name"], s["value"]) for s in A] == [("shorea_robusta", "Sal", 60.0), ("terminalia_alata", "Saj", 40.0)]
    assert us.species_key("Terminalia alata Roxb.") == "terminalia_alata_roxb" and us.species_key("") == "unknown"


def test_with_no_volumes_the_shares_fall_back_to_stem_counts():
    s = us.shares_from_rows([{"sci": "A a", "local": None, "vol": 0, "n": 3}, {"sci": "B b", "local": "Bee", "vol": 0, "n": 1}])
    assert [(x["name"], x["value"]) for x in s] == [("A a", 75.0), ("Bee", 25.0)]
    assert us.shares_from_rows([]) == []


def test_the_dynamic_palette_is_this_forests_own_species_largest_first_at_most_ten():
    classes = us.scheme(VALUES)
    assert len(classes) <= 10 and classes[0]["key"] in ("shorea_robusta", "terminalia_alata")
    assert len({c["color"] for c in classes}) == len(classes)  # one colour each
    palette = list(sp.CATEGORICAL["species_qual"].values())
    assert [c["color"] for c in classes] == palette[: len(classes)]


def test_the_dominant_species_map_colours_each_unit_by_its_species_and_follows_the_users_colour():
    r = um.build_unit_map(UNITS, VALUES, DOM)
    assert r["state"] == "ready" and sum(x["count"] for x in r["legend"]) == 3
    assert r["units"]["A"]["text"] == "Sal" and r["units"]["B"]["text"] == "Saj"  # the label is the NAME, never the internal key
    cols = {n: u["color"] for n, u in r["units"].items()}
    assert cols["A"] != cols["B"]  # Sal-dominated vs Saj-dominated
    mine = DOM.model_copy(update={"colour_overrides": {"shorea_robusta": "#123456"}})
    r2 = um.build_unit_map(UNITS, VALUES, mine)
    assert r2["units"]["A"]["color"] == "#123456" and r2["units"]["B"]["color"] == cols["B"]
    assert {x["key"]: x["color"] for x in r2["legend"]}["shorea_robusta"] == "#123456"
    feat, _rows = to._colour_map(UNITS, VALUES, mine)  # the print renderer draws the same
    assert feat["A"] == "#123456"


def test_the_pie_names_the_top_five_and_lumps_the_rest_as_other_species():
    r = fg.build_glyphs(UNITS, VALUES, PIE, "species-pie")
    c = next(u for u in r["units"] if u["name"] == "C")
    assert len(c["segments"]) == 6 and c["segments"][-1]["key"] == "other_species"
    assert abs(sum(s["value"] for s in c["segments"]) - 100.0) < 0.1
    assert r["shape"] == "pie" and r["editable"] is True and r["max_total"] == 100.0
    assert [x["key"] for x in r["legend"]][-1] == "other_species"
    assert all(x["override_key"] == x["key"] for x in r["legend"])  # a saved colour is keyed by the species, not a position
    assert next(u for u in r["units"] if u["name"] == "A")["text_long"] == "Sal 60%"


def test_the_pie_colours_follow_the_users_colour_by_species_key_and_match_the_print_glyph():
    mine = PIE.model_copy(update={"colour_overrides": {"terminalia_alata": "#123456", "other_species": "#654321"}})
    r = fg.build_glyphs(UNITS, VALUES, mine, "species-pie")
    seg = {s["key"]: s["color"] for s in next(u for u in r["units"] if u["name"] == "B")["segments"]}
    assert seg["terminalia_alata"] == "#123456"
    comps = to._composition("B", VALUES, mine)  # the print map's own function
    assert ("Saj", 70.0, "#123456") in [(n, v, c) for n, v, c in comps]
    legend = to._glyph_legend(mine, VALUES)
    assert "#123456" in [row[0] for row in legend] and "#654321" in [row[0] for row in legend]


def test_species_maps_are_known_to_the_colour_registry_and_the_workspace():
    assert ucm.SPEC_TO_ANALYSIS["unit__species_dominant"] == "fi_species" and um.FI_MAPS["fi_species"][0] == "unit__species_dominant"
    assert ucm.SPEC_TO_ANALYSIS["unit__species_composition__pie"] == "chart_species"
    assert fg.CHARTS["species-pie"]["spec"] == "unit__species_composition__pie"


def test_saved_species_colours_are_accepted_keys():
    assert ucm.indexed_overrides({"mode": "indexed", "colors": {"terminalia_alata": "#112233", "other_species": "#445566"}}) == {
        "terminalia_alata": "#112233", "other_species": "#445566"}
