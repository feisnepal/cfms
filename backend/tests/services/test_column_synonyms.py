"""Other names of a column, and the unit written in a header (hand-typed CSV / Excel files)."""
import pytest

from app.services.upload import column_synonyms as cs


@pytest.mark.parametrize("header, canonical", [
    ("Lon", "longitude"), ("LONG", "longitude"), ("देशान्तर", "longitude"), ("Lat ", "latitude"), ("अक्षाँस", "latitude"), ("अक्षांश", "latitude"),
    ("Plot No", "sample_plot_number"), ("sample plot", "sample_plot_number"), ("प्लट नं", "sample_plot_number"), ("नमुना प्लट", "sample_plot_number"),
    ("Block", "block_name"), ("Compartment", "block_name"), ("ब्लक", "block_name"), ("कम्पार्टमेन्ट", "block_name"),
    ("Pole Dia", "pole_dbh"), ("pole_DBH", "pole_dbh"), ("Pole Diameter", "pole_dbh"), ("पोल व्यास", "pole_dbh"), ("DBH of tree", None),
    ("Tree DBH", "tree_dbh"), ("रूख व्यास", "tree_dbh"), ("रुख व्यास", "tree_dbh"), ("Sapling Dia", "sapling_dbh"), ("लाथ्रा व्यास", "sapling_dbh"),
    ("Seedling DBH", "regen_dbh"), ("विरुवा संख्या", "regen_count"), ("बिरुवा संख्या", "regen_count"), ("Sapling Count", "sapling_count"),
    ("Tree Ht", "tree_height"), ("Pole Height", "pole_height"), ("पोल उचाइ", "pole_height"), ("Tree Species", "tree_species_scientific"),
    ("Pole Scientific Name", "pole_species_scientific"), ("रुख प्रजाति", "tree_species_scientific"), ("Tree Class", "tree_class"),
])
def test_field_inventory_names(header, canonical):
    m = cs.resolve_column(header, "field_inventory")
    assert (m.canonical if m else None) == canonical


@pytest.mark.parametrize("header", ["sp", "name", "unit", "girth", "Tree Girth", "circumference", "remarks"])
def test_ambiguous_or_different_quantities_are_not_guessed(header):
    assert cs.resolve_column(header, "field_inventory") is None


def test_the_unit_in_a_header_is_read_and_does_not_change_the_column():
    m = cs.resolve_column("Pole Dia (mm)", "field_inventory")
    assert (m.canonical, m.unit) == ("pole_dbh", "mm")
    assert cs.resolve_column("Tree Height (ft)", "field_inventory").unit == "ft"
    assert cs.resolve_column("tree_dbh_cm", "field_inventory").unit == "cm"
    assert cs.resolve_column("व्यास (इन्च)", "trees").unit == "in"
    assert cs.resolve_column("Tree DBH", "field_inventory").unit is None  # none written: the convention (cm) applies


@pytest.mark.parametrize("header, canonical", [
    ("Species", "species"), ("प्रजाति", "species"), ("DBH", "dbh_cm"), ("Diameter (cm)", "dbh_cm"), ("व्यास", "dbh_cm"), ("Ht", "height_m"),
    ("Plot", "plot"), ("Tree No", "tree_no"), ("रूख नं", "tree_no"), ("S.N.", "tree_no"), ("Lng", "longitude"), ("Size Class", "class"),
])
def test_loose_tree_list_names(header, canonical):
    m = cs.resolve_column(header, "trees")
    assert m is not None and m.canonical == canonical


@pytest.mark.parametrize("spelling", ["घर नंवर", "घर नंबर", "घर नम्बर", "House No", "house number"])
def test_household_house_number_in_every_spelling(spelling):
    assert cs.resolve_column(spelling, "households").canonical == "house_no"


@pytest.mark.parametrize("header, canonical", [
    ("पुरूष संख्या", "male_count"), ("पुरुष संख्या", "male_count"), ("Female Count", "female_count"), ("महिला संख्या", "female_count"),
    ("अक्षाँस", "latitude"), ("बन पैदाबारको माग (दाउरा) भारी", "firewood_demand_bhari"), ("वन पैदावारको माग (दाउरा) भारी", "firewood_demand_bhari"),
    ("बन पैदाबारको माग (काठ क्यू.फि.)", "timber_demand_cft"), ("जातिय वर्गिकरण", "caste_classification_ne"), ("जातीय वर्गीकरण", "caste_classification_ne"),
    ("सम्पन्नताको स्तर", "prosperity_level"), ("कैफियत", "remarks"), ("Prosperity Level", "prosperity_level"), ("house_no", "house_no"),
])
def test_household_names_nepali_and_english(header, canonical):
    m = cs.resolve_column(header, "households")
    assert m is not None and m.canonical == canonical


def test_every_template_household_header_still_resolves_to_its_own_column():
    from app.services.upload.household_table import HOUSEHOLD_HEADER_MAP
    for nepali, canonical in HOUSEHOLD_HEADER_MAP.items():
        m = cs.resolve_column(nepali, "households")
        assert m is not None and m.canonical == canonical, nepali


def test_two_headers_for_one_column_leave_the_second_to_the_user():
    matches, clashes = cs.plan_columns(["Lon", "Longitude", "Lat"], "field_inventory")
    assert [m.canonical for m in matches] == ["longitude", "latitude"]
    assert clashes == [("Longitude", "Lon")]


def test_a_name_that_two_columns_claim_resolves_to_neither(monkeypatch):
    monkeypatch.setitem(cs._PURPOSE_TABLES, "_t", {"a": ("foo", "only a"), "b": ("foo", "only b")})
    assert cs.resolve_column("foo", "_t") is None  # both claim it: a guess
    assert cs.resolve_column("only a", "_t").canonical == "a" and cs.resolve_column("only b", "_t").canonical == "b"
    cs._BUILT.pop("_t", None)


def test_no_name_is_claimed_by_two_columns_today():
    for purpose in ("field_inventory", "trees", "households"):
        cs._table(purpose)
        assert cs._AMBIGUOUS[purpose] == {}, cs._AMBIGUOUS[purpose]


def test_field_inventory_upload_reads_nepali_and_unit_headers():
    """The old normaliser split Nepali words at their vowel marks, so none of its Nepali synonyms ever matched."""
    import pandas as pd
    from app.services.upload.fi_columns import normalise_columns

    df = pd.DataFrame(columns=["देशान्तर", "अक्षांश", "प्लट नं", "ब्लक", "Pole Dia (cm)", "पोल व्यास", "Tree Ht"])
    _, plan = normalise_columns(df)
    got = dict(plan)
    assert got["देशान्तर"] == "longitude" and got["अक्षांश"] == "latitude" and got["ब्लक"] == "block_name"
    assert got["प्लट नं"] == "sample_plot_number"
    assert got["Pole Dia (cm)"] == "pole_dbh"
    assert "पोल व्यास" not in got  # same target as 'Pole Dia (cm)': the second one is left to the user, not silently dropped
    assert got["Tree Ht"] == "tree_height"
    assert dict(normalise_columns(pd.DataFrame(columns=["SP"]))[1]) == {"SP": "sample_plot_number"}  # the older table still applies


# The schema still lists a few names that are too ambiguous to rename a column by. They stay as WEAK classification signals; this list is
# the complete set, so any new disagreement between the schema's aliases and the shared module fails here instead of drifting.
_KNOWN_SCHEMA_ONLY_ALIASES = {
    ("field_inventory", "block", "unit"),
    ("trees", "species", "sp"), ("trees", "plot", "block"),
    ("sample_plots", "block", "unit"),
    ("activities", "activity", "name"), ("activities", "unit", "unit"),  # the schema's unit is the forest unit; इकाई is the unit of measure
}


def test_the_schema_aliases_and_the_shared_module_do_not_drift():
    from app.services.upload import schema

    disagreements = set()
    for pid in ("field_inventory", "trees", "activities", "sample_plots"):
        for col in schema.get(pid).columns:
            for name in (col.name, *col.aliases):
                m = cs.resolve_column(name, pid)
                if (cs.schema_column(pid, m.canonical) if m else None) != col.name:
                    disagreements.add((pid, col.name, name))
    assert disagreements == _KNOWN_SCHEMA_ONLY_ALIASES


@pytest.mark.parametrize("header, canonical", [
    ("क्र.सं.", "serial_no"), ("कार्यक्रमको नाम", "activity"), ("इकाई", "unit_of_measure"), ("दर (हजारमा)", "rate"), ("बर्ष", "year"),
    ("वर्ष", "year"), ("जम्मा", "total"), ("Activity Name", "activity"), ("Unit of Measure", "unit_of_measure"), ("Total", "total"),
])
def test_activity_table_columns(header, canonical):
    m = cs.resolve_column(header, "activities")
    assert m is not None and m.canonical == canonical


def test_a_rate_in_thousands_carries_its_scale():
    m = cs.resolve_column("दर (हजारमा)", "activities")
    assert (m.canonical, m.unit) == ("rate", "thousand")


def test_the_classifier_sees_an_activity_table_by_its_nepali_headers():
    from app.services.upload.classify import classify_upload

    c = classify_upload(filename="x.xlsx", columns=["क्र.सं.", "कार्यक्रमको नाम", "इकाई", "दर (हजारमा)", "बर्ष", "जम्मा"])
    assert c.best == "activities"


def test_coordinates_and_remarks_alone_do_not_make_a_household_list():
    from app.services.upload.classify import classify_upload

    c = classify_upload(filename="plots.csv", columns=["lon", "lat", "remarks", "plot", "block"])
    assert c.best != "households"


def test_a_unit_written_in_the_header_is_applied_and_reported():
    import pandas as pd
    from app.services.upload.fi_columns import normalise_columns, normalise_columns_with_units

    df = pd.DataFrame({"Plot No": [1, 2], "Tree DBH (mm)": [250.0, "abc"], "Tree Height (ft)": [65.6168, 32.8084], "Pole Dia (cm)": [20, 25],
                       "Sapling Dia (in)": [2.0, 3.0]})
    out, renames, conv = normalise_columns_with_units(df)
    assert list(out["tree_dbh"])[0] == pytest.approx(25.0) and out["tree_dbh"].iloc[1] == "abc"  # text is left for the validator to report
    assert list(out["tree_height"]) == pytest.approx([20.0, 10.0])
    assert list(out["pole_dbh"]) == [20, 25]  # cm is the convention: unchanged
    assert list(out["sapling_dbh"]) == pytest.approx([5.08, 7.62])
    assert {c[0] for c in conv} == {"Tree DBH (mm)", "Tree Height (ft)", "Sapling Dia (in)"}
    assert normalise_columns(df)[0]["tree_dbh"].iloc[0] == pytest.approx(25.0)  # the later processing read sees the same numbers


def test_no_unit_written_means_no_conversion():
    import pandas as pd
    from app.services.upload.fi_columns import normalise_columns_with_units

    out, _, conv = normalise_columns_with_units(pd.DataFrame({"Tree DBH": [250.0, 260.0, 270.0]}))
    assert conv == [] and list(out["Tree DBH"]) == [250.0, 260.0, 270.0]  # a guess is the value check's job, not ours


def test_the_report_names_the_conversion():
    import pandas as pd
    from app.services.upload.field_inventory_findings import enrich_report

    report = {"errors": [], "warnings": [], "info": [], "summary": {"total_rows": 1}}
    findings = enrich_report(report, pd.DataFrame({"tree_dbh": [25.0]}), "f.csv", converted=[("Tree DBH (mm)", "mm", 0.1)])
    assert any(f.code == "field_inventory.units_converted" for f in findings)


def test_the_household_header_row_is_found_with_other_spellings_and_english_names():
    from app.services.upload.household_table import HOUSEHOLD_HEADER_MAP, locate_table

    rows = [["Household list", None, None], ["घर नंबर", "थर", "पुरुष संख्या", "महिला संख्या", "मेरो कोलम"], ["१", "शर्मा", 2, 3, "x"]]
    t = locate_table(rows, HOUSEHOLD_HEADER_MAP)
    assert t is not None and t.header_row_number == 2 and t.first_data_row_number == 3
    assert t.unrecognised == ["मेरो कोलम"]
    english = [["House No", "Surname", "Male Count", "Female Count"], ["1", "Sharma", 2, 3]]
    assert locate_table(english, HOUSEHOLD_HEADER_MAP).header_row_number == 1


def test_a_land_column_names_its_unit_in_any_spelling():
    for h, unit in (("जमिन (ropani)", "ropani"), ("Land (Kattha)", "kattha"), ("जमिन (रोपनी)", "ropani"), ("जमिन (kaththa)", "kattha")):
        m = cs.resolve_column(h, "households")
        assert (m.canonical, m.unit) == ("land_area", unit), h


@pytest.mark.parametrize("purpose", ["field_inventory", "trees", "sample_plots"])
@pytest.mark.parametrize("header, canonical", [
    ("Easting", "longitude"), ("Northing", "latitude"), ("X", "longitude"), ("Y", "latitude"), ("UTM Easting", "longitude"), ("x_coord", "longitude"),
    ("North", "latitude"), ("East", "longitude"),
])
def test_utm_headed_columns_are_the_coordinate_columns(purpose, header, canonical):
    m = cs.resolve_column(header, purpose)
    assert m is not None and cs.schema_column(purpose, m.canonical) == canonical


def test_households_do_not_take_x_and_y_as_their_coordinates():
    assert cs.resolve_column("x", "households") is None and cs.resolve_column("Northing", "households") is None
