"""A workspace layer as a GeoPackage: the features the workspace shows, written as they are shown."""

from __future__ import annotations

import os
import tempfile

import pytest

from app.services.layer_gpkg_export import (
    MAX_FEATURES,
    NothingToExport,
    TooManyFeatures,
    build_geopackage,
    describe,
    group_features,
    safe_layer_name,
)


def _poly(x, name, **props):
    ring = [[x, 27.0], [x + 0.01, 27.0], [x + 0.01, 27.01], [x, 27.01], [x, 27.0]]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {"name": name, **props}}


def _point(x, name):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, 27.0]}, "properties": {"name": name}}


def _line(name):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[85.0, 27.0], [85.1, 27.1]]}, "properties": {"name": name}}


def _write(content: bytes) -> str:
    handle, path = tempfile.mkstemp(suffix=".gpkg")
    os.close(handle)
    with open(path, "wb") as fh:
        fh.write(content)
    return path


def _read(content: bytes, layer=None):
    import geopandas as gpd

    path = _write(content)
    try:
        return gpd.read_file(path, layer=layer), describe(path)
    finally:
        os.remove(path)


def test_the_file_is_a_real_geopackage_with_the_layers_features_and_columns():
    feats = [_poly(85.0, "a", area_hectares=12.5, tree_count=3), _poly(85.1, "b", area_hectares=7.0, tree_count=5)]
    gdf, layers = _read(build_geopackage(feats, "Compartments"))
    assert layers == [("Compartments", "MultiPolygon", 2)]
    assert list(gdf["name"]) == ["a", "b"]
    assert list(gdf["tree_count"]) == [3, 5]
    assert gdf["area_hectares"].tolist() == [12.5, 7.0]
    assert str(gdf.crs).endswith("4326")


def test_nepali_names_and_values_survive():
    feats = [_poly(85.0, "बनस्खन्डी - ख", natural_name="जोर्छाङ्गा खोला")]
    gdf, _ = _read(build_geopackage(feats, "उप-कम्पार्टमेन्ट"))
    assert gdf["name"].iloc[0] == "बनस्खन्डी - ख"
    assert gdf["natural_name"].iloc[0] == "जोर्छाङ्गा खोला"


def test_a_layer_that_mixes_geometry_kinds_becomes_one_layer_per_kind():
    feats = [_point(85.0, "p1"), _point(85.1, "p2"), _line("l1"), _poly(85.2, "a1")]
    _, layers = _read(build_geopackage(feats, "Activity Features"))
    assert layers == [("Activity_Features_points", "MultiPoint", 2), ("Activity_Features_lines", "MultiLineString", 1), ("Activity_Features_polygons", "MultiPolygon", 1)]


def test_single_and_multi_geometries_of_one_kind_share_a_layer():
    multi = {
        "type": "Feature",
        "geometry": {"type": "MultiPolygon", "coordinates": [[[[85.5, 27.0], [85.51, 27.0], [85.51, 27.01], [85.5, 27.0]]]]},
        "properties": {"name": "m"},
    }
    _, layers = _read(build_geopackage([_poly(85.0, "a"), multi], "Blocks"))
    assert layers == [("Blocks", "MultiPolygon", 2)]


def test_columns_are_typed_from_their_values_and_empty_cells_stay_empty():
    feats = [_poly(85.0, "a", n=1, ratio=0.5, flag=True, note="x"), _poly(85.1, "b", n=None, ratio=2, flag=False)]
    gdf, _ = _read(build_geopackage(feats, "L"))
    assert gdf["n"].tolist()[0] == 1 and gdf["n"].isna().tolist() == [False, True]
    assert gdf["ratio"].tolist() == [0.5, 2.0]
    assert gdf["flag"].tolist() == [1, 0]
    assert gdf["note"].tolist()[0] == "x"


def test_nested_values_are_kept_as_json_text():
    feats = [_poly(85.0, "a", years=[1, 2, 3], extra={"k": "v"})]
    gdf, _ = _read(build_geopackage(feats, "L"))
    assert gdf["years"].iloc[0] == "[1, 2, 3]"
    assert gdf["extra"].iloc[0] == '{"k": "v"}'


def test_property_names_are_made_safe_and_unique_and_never_take_a_reserved_name():
    feats = [{"type": "Feature", "geometry": _poly(85.0, "a")["geometry"], "properties": {"fid": 1, "geometry": "g", "a b": 1, "a_b": 2, "": 3}}]
    gdf, _ = _read(build_geopackage(feats, "L"))
    cols = [c for c in gdf.columns if c != "geometry"]
    assert len(cols) == len(set(c.lower() for c in cols)) == 5
    assert "a_b" in cols and "a_b_2" in cols


def test_features_without_a_geometry_are_left_out_and_an_all_empty_layer_is_refused():
    feats = [_poly(85.0, "a"), {"type": "Feature", "geometry": None, "properties": {"name": "ghost"}}]
    gdf, layers = _read(build_geopackage(feats, "L"))
    assert layers == [("L", "MultiPolygon", 1)] and list(gdf["name"]) == ["a"]
    with pytest.raises(NothingToExport):
        build_geopackage([{"type": "Feature", "geometry": None, "properties": {}}], "L")
    with pytest.raises(NothingToExport):
        build_geopackage([], "L")


def test_a_layer_too_large_for_one_request_is_refused():
    with pytest.raises(TooManyFeatures):
        build_geopackage([{"x": i} for i in range(MAX_FEATURES + 1)], "L")


def test_layer_names_are_safe_in_any_script():
    assert safe_layer_name("Activity Features") == "Activity_Features"
    assert safe_layer_name("उप-कम्पार्टमेन्ट") == "उप_कम्पार्टमेन्ट"
    assert safe_layer_name("  ") == "layer"
    assert safe_layer_name("2026 plots") == "layer_2026_plots"
    assert safe_layer_name(None) == "layer"
    assert len(safe_layer_name("x" * 200)) == 60


def test_grouping_ignores_unknown_geometry_kinds():
    groups = group_features([_poly(85.0, "a"), {"geometry": {"type": "GeometryCollection", "coordinates": [1]}}, _point(85.0, "p")])
    assert set(groups) == {"polygons", "points"}


# ---- symbology -----------------------------------------------------------------------------------------------------------------------------


def _sym(fill="#228b22", stroke="#006400", weight=2, fill_op=0.5, dash=None, radius=6):
    return {"fill": fill, "fillOpacity": fill_op, "stroke": stroke, "strokeOpacity": 1, "weight": weight, "dashArray": dash, "radius": radius}


def _styled(feature, sym):
    return {**feature, "_symbol": sym}


def _styles(content: bytes):
    import sqlite3
    from xml.etree import ElementTree

    path = _write(content)
    try:
        con = sqlite3.connect(path)
        rows = con.execute("SELECT f_table_name, f_geometry_column, useAsDefault, styleQML FROM layer_styles").fetchall()
        con.close()
    finally:
        os.remove(path)
    for _, _, _, qml in rows:  # the QML must be well-formed XML once its DOCTYPE is set aside
        ElementTree.fromstring(qml.split("'SYSTEM'>", 1)[1])
    return rows


def test_a_layer_whose_features_share_one_look_gets_one_plain_style_and_no_extra_fields():
    feats = [_styled(_poly(85.0, "a"), _sym()), _styled(_poly(85.1, "b"), _sym())]
    content = build_geopackage(feats, "Compartments")
    ((table, geom_col, default, qml),) = _styles(content)
    assert (table, default) == ("Compartments", 1)
    assert "34,139,34,128" in qml and 'class="SimpleFill"' in qml and "data_defined_properties" in qml and 'name="field"' not in qml
    gdf, _ = _read(content)
    assert not [c for c in gdf.columns if c.startswith("symbol_")]
    import pyogrio

    path = _write(content)
    try:
        assert pyogrio.read_info(path, layer="Compartments")["geometry_name"] == geom_col
    finally:
        os.remove(path)


def test_a_layer_whose_features_differ_in_colour_writes_the_colours_as_fields_the_style_reads():
    feats = [_styled(_poly(85.0, "a"), _sym(fill="#ff0000")), _styled(_poly(85.1, "b"), _sym(fill="#0000ff", weight=4))]
    content = build_geopackage(feats, "Blocks")
    ((_, _, _, qml),) = _styles(content)
    assert 'value="symbol_fill"' in qml and 'value="symbol_outline"' in qml and 'value="symbol_width"' in qml
    gdf, _ = _read(content)
    assert gdf["symbol_fill"].tolist() == ["255,0,0,128", "0,0,255,128"]
    assert gdf["symbol_width"].tolist() == [2.0, 4.0]


def test_the_style_fields_never_overwrite_a_property_of_the_same_name():
    feats = [_styled(_poly(85.0, "a", symbol_fill="mine"), _sym(fill="#ff0000")), _styled(_poly(85.1, "b", symbol_fill="yours"), _sym(fill="#0000ff"))]
    content = build_geopackage(feats, "L")
    ((_, _, _, qml),) = _styles(content)
    gdf, _ = _read(content)
    assert gdf["symbol_fill"].tolist() == ["mine", "yours"]
    assert 'value="symbol_fill_"' in qml and gdf["symbol_fill_"].tolist() == ["255,0,0,128", "0,0,255,128"]


def test_each_geometry_kind_gets_its_own_style_and_lines_and_points_use_their_own_symbols():
    feats = [_styled(_point(85.0, "p"), _sym(radius=5)), _styled(_line("l"), _sym(stroke="#8b4513", dash="5, 5")), _styled(_poly(85.2, "a"), _sym())]
    rows = {r[0]: r[3] for r in _styles(build_geopackage(feats, "Activity Features"))}
    assert set(rows) == {"Activity_Features_points", "Activity_Features_lines", "Activity_Features_polygons"}
    assert 'class="SimpleMarker"' in rows["Activity_Features_points"] and 'value="10.0"' in rows["Activity_Features_points"]
    assert 'class="SimpleLine"' in rows["Activity_Features_lines"] and 'value="dash"' in rows["Activity_Features_lines"]


def test_no_symbols_means_no_style_table_and_the_file_is_as_before():
    import sqlite3

    path = _write(build_geopackage([_poly(85.0, "a")], "L"))
    try:
        con = sqlite3.connect(path)
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
    finally:
        os.remove(path)
    assert "layer_styles" not in names
