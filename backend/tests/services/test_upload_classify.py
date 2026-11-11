"""Content-based upload classification — the endpoint and the pure scorer (UP-4.2a)."""

import io
import json
import zipfile

from app.services.upload.classify import classify_upload, read_signals


# ── scoring ───────────────────────────────────────────────────────────────
def test_household_columns_identify_a_household_sheet():
    r = classify_upload(filename="upload", columns=["Household Head", "Ward", "Members", "Settlement"])
    assert r.best == "households"
    assert "columns" in r.candidates[0].reasons


def test_nepali_household_headers_work_through_aliases():
    r = classify_upload(filename="upload", columns=["घरमूलीको नाम", "वडा", "सदस्य"])
    assert r.best == "households"


def test_tree_columns_identify_a_tree_list_not_a_household_sheet():
    r = classify_upload(
        filename="upload", columns=["species", "dbh_cm", "height_m", "longitude", "latitude"]
    )
    assert r.best == "trees"
    assert all(c.purpose_id != "households" for c in r.candidates)


def test_field_inventory_columns_win_over_generic_plot_columns():
    r = classify_upload(filename="upload", columns=["block", "plot_number", "regen_species", "pole_species"])
    assert r.best == "field_inventory"


def test_a_name_match_beats_columns():
    r = classify_upload(filename="Blocks", columns=["whatever", "noise"])
    assert r.best == "blocks"
    assert "name" in r.candidates[0].reasons


def test_geometry_type_prunes_a_polygon_only_purpose_for_a_line_file():
    r = classify_upload(filename="Trails", layer_names=["roads"], geometry_type="MULTILINESTRING")
    assert r.best == "roads"
    # boundary is polygon-only: its geometry mismatch is recorded and it does not win
    boundary = next((c for c in r.candidates if c.purpose_id == "forest_boundary"), None)
    assert boundary is None or "geometry_mismatch" in boundary.reasons


def test_activities_identified_by_columns():
    r = classify_upload(filename="upload", columns=["activity", "year", "unit", "kind"])
    assert r.best == "activities"


def test_unknown_file_returns_no_best():
    r = classify_upload(filename="upload", columns=["a", "b", "c"])
    assert r.best is None or r.best not in ("households", "trees")


# ── signal extraction ─────────────────────────────────────────────────────
def test_read_signals_csv_columns():
    sig = read_signals(b"Household Head,Ward\nRam,3\n", "h.csv")
    assert sig["columns"] == ["Household Head", "Ward"]


def test_read_signals_zip_lists_shapefile_layers():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("roads.shp", b"x")
        zf.writestr("roads.dbf", b"x")
        zf.writestr("readme.txt", b"x")
    sig = read_signals(buf.getvalue(), "pack.zip")
    assert sig["layer_names"] == ["roads"]


def test_read_signals_geojson_properties_and_geometry():
    gj = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[85.0, 27.0]]},
                    "properties": {"activity": "fire line", "year": 2},
                }
            ],
        }
    ).encode()
    sig = read_signals(gj, "a.geojson")
    assert "activity" in sig["columns"]
    assert sig["geometry_type"] == "LINESTRING"


def test_read_signals_gpx_line():
    gpx = b'<?xml version="1.0"?><gpx><trk><trkseg></trkseg></trk></gpx>'
    assert read_signals(gpx, "walk.gpx")["geometry_type"] == "LINESTRING"


def test_read_signals_never_raises_on_garbage():
    assert read_signals(b"\x00\x01\x02", "weird.gpkg") == {}


def test_a_bare_polygon_with_a_name_column_is_not_called_anything():
    """e2e finding: a one-column GeoJSON polygon was called 'Planned activities' because 'name' is an alias of 'activity'."""
    r = classify_upload(filename="area.geojson", columns=["name"], geometry_type="POLYGON")
    assert r.best is None


def test_the_real_household_template_is_identified_in_nepali_and_english_spellings():
    for first in ("घर नंवर", "घर नंबर", "घर नम्बर"):
        assert classify_upload(filename="data1.csv", columns=[first, "थर", "महिला संख्या", "पुरूष संख्या"]).best == "households"
    assert classify_upload(filename="x.csv", columns=["house_no", "surname", "female_count", "male_count"]).best == "households"


def test_household_columns_outweigh_a_misleading_file_name():
    r = classify_upload(filename="forest_boundary", columns=["घर नंबर", "थर", "महिला संख्या", "पुरूष संख्या"])
    assert r.best == "households"


def _tab(columns, lat="lat", lon="lon"):
    return classify_upload(filename="data", columns=columns, lat_col=lat, lon_col=lon)


def test_a_table_of_coordinates_and_bookkeeping_is_a_list_of_boundary_points():
    assert _tab(["Point", "Lat", "Lon"], "Lat", "Lon").best == "forest_boundary"
    assert _tab(["Waypoint", "Latitude", "Longitude", "Ele", "Time"], "Latitude", "Longitude").best == "forest_boundary"
    assert _tab(["lat", "lon"]).best == "forest_boundary"


def test_coordinates_in_a_tree_plot_or_household_table_are_not_a_boundary():
    assert _tab(["species", "dbh_cm", "height_m", "lat", "lon"]).best == "trees"
    assert _tab(["plot_no", "lat", "lon"]).best == "sample_plots"
    assert _tab(["घर नंबर", "थर", "महिला संख्या", "पुरूष संख्या", "lat", "lon"]).best == "households"


def test_coordinates_with_columns_we_do_not_know_are_still_a_boundary_when_nothing_is_about_trees_plots_or_households():
    assert _tab(["code", "local_name", "lat", "lon"]).best == "forest_boundary"


def test_any_tree_plot_or_household_column_rules_a_table_out_as_a_boundary():
    for extra in ("species_local", "DBH", "Height", "plot", "house_no", "ward", "Diameter (cm)", "tree_no"):
        assert _tab([extra, "lat", "lon"]).best != "forest_boundary", extra


def _fi(columns):
    lat = next((c for c in columns if c in ("latitude", "lat")), None)
    lon = next((c for c in columns if c in ("longitude", "lon")), None)
    return classify_upload(filename="inventory_data", columns=columns, lat_col=lat, lon_col=lon)


def test_a_field_inventory_with_a_plot_number_and_stand_measurements_is_not_called_sample_plots():
    """Owner report: a real field inventory was classified as sample plots. Locations carry no species, dbh or height."""
    header = ["block_name", "sample_plot_number", "longitude", "latitude", "tree_species_scientific", "tree_dbh_cm", "tree_height_m", "tree_class"]
    assert _fi(header).best == "field_inventory"


def test_any_single_stand_type_is_enough_for_a_field_inventory():
    for stand in ("regen_species_scientific", "sapling_species_scientific", "pole_species_scientific", "tree_species_scientific"):
        assert _fi(["sample_plot_number", "longitude", "latitude", stand]).best == "field_inventory", stand


def test_a_sample_plot_location_file_stays_sample_plots():
    assert _fi(["plot_no", "lat", "lon", "block", "radius_m"]).best == "sample_plots"
    assert _fi(["sample_plot_number", "longitude", "latitude"]).best == "sample_plots"


def test_stem_mapping_without_a_plot_number_stays_trees():
    assert _fi(["species", "dbh_cm", "height_m", "latitude", "longitude"]).best == "trees"
