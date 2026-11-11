"""Field book generation, end to end through the database (``generate_fieldbook_points``).

The geometry itself -- outer ring first, clockwise from the north-west vertex, every internal edge once,
junction remarks -- is covered without a database in ``test_fieldbook_sequence.py``. This file covers what only
the database path owns:

- Unit sourcing prefers DB compartments > DB blocks > legacy result_data.
- Sub-areas are sourced live (DB rows, else ``result_data['sub_areas']``) and take part in the same book.
- The new fields (label, outer/internal, junction, adjacent units, remark) are saved and served.
- The exports (CSV / Excel / GPX / GeoJSON) and the OP document table carry them, and the defects found in
  the old CSV (a debug column, latitude/longitude under each other's heading, a zero shown as blank) stay fixed.
"""
import io
import uuid

from shapely.geometry import Polygon, MultiPolygon

from app.models.calculation import Calculation
from app.models.fieldbook import Fieldbook
from app.models.forest_block import ForestBlock
from app.models.forest_sub_area import ForestSubArea
from app.models.user import User, UserRole
from app.services.fieldbook import generate_fieldbook_points, calculate_distance
from app.services.operational_plan.data_collector import _fetch_fieldbook_data


NS = 83.5  # Nepal UTM zone 44 reference longitude (avoids projection-domain errors)
NL = 27.5


def _square(x, y, size=0.01):
    """~1.1km-ish square at this latitude -- edges well over the 50m
    interpolation threshold, so vertex+interpolated point tests exercise both
    code paths against the same fixture."""
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _tiny_square(x, y, size=0.0001):
    """~10m square -- edges under the 50m interpolation threshold."""
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _make_user(db, email=None):
    user = User(
        email=email or f"fbtest{uuid.uuid4().hex[:8]}@test.com",
        full_name="Fieldbook Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db, boundary=None, forest_name="Test Forest", result_data=None):
    user = _make_user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="fieldbook-test.csv",
        is_draft=False,
        structure_locked=False,
        forest_name=forest_name,
        result_data=result_data or {},
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        from geoalchemy2.shape import from_shape
        calc.boundary_geom = from_shape(boundary, srid=4326)
        db.flush()
    return calc


def _add_db_unit(db, calc, geom, name, is_compartment=False, index=1, code=None):
    from geoalchemy2.shape import from_shape
    from app.utils.geometry_utils import calculate_area_geodesic_from_shapely

    _sqm, _ha = calculate_area_geodesic_from_shapely(geom)
    row = ForestBlock(
        calculation_id=calc.id,
        name=name,
        block_name=name,
        compartment_code=code,
        geometry=from_shape(geom, srid=4326),
        area_hectares=round(_ha * 0.98, 4),
        index=index,
        is_compartment=is_compartment,
        division_level=1,
    )
    db.add(row)
    db.flush()
    return row


def _add_subarea(db, calc, geom, name, is_excluded=False, category="conservation"):
    # Valid categories are the 14-value app set (sub_area_service.VALID_CATEGORIES /
    # migration 048), NOT the old 'protected'/'private' strings -- is_excluded is
    # its own real column, unrelated to category text.
    from geoalchemy2.shape import from_shape
    from app.utils.geometry_utils import calculate_area_geodesic_from_shapely

    _sqm, _ha = calculate_area_geodesic_from_shapely(geom)
    row = ForestSubArea(
        calculation_id=calc.id,
        name=name,
        category=category,
        geometry=from_shape(geom, srid=4326),
        area_hectares=round(_ha, 4),
        is_excluded=is_excluded,
    )
    db.add(row)
    db.flush()
    return row


def _result_data_subarea(name, geom, category="religious", is_excluded=False):
    """Matches the exact dict shape `add_sub_area` (api/forests.py) writes into
    `calculation.result_data['sub_areas']` -- the ONLY place this app's live
    sub-area create/delete endpoint ever stores sub-areas (`ForestSubArea(...)`
    is never constructed anywhere in the codebase outside its own model file).
    """
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "category": category,
        "geometry": geom.__geo_interface__,
        "area_hectares": 1.0,
        "isExcluded": is_excluded,
        "is_excluded": is_excluded,
    }


def _points(db, calc_id):
    return db.query(Fieldbook).filter(Fieldbook.calculation_id == calc_id).order_by(Fieldbook.point_number).all()


# ---------------------------------------------------------------------------
# helpers specific to this file
# ---------------------------------------------------------------------------

def _tiling_boundary(*geoms):
    """The forest boundary for units that tile it exactly (the real shape of a forest)."""
    from shapely.ops import unary_union
    return unary_union(list(geoms))


def _names(db, calc_id):
    return {p.block_name for p in _points(db, calc_id) if p.block_name}


def _gen(db, calc, spacing=0):
    return generate_fieldbook_points(db, calc.id, interpolation_distance=spacing, extract_elevation=False)


# ---------------------------------------------------------------------------
# A -- unit sourcing
# ---------------------------------------------------------------------------

def test_sources_from_compartments_when_present(db):
    c1, c2 = _square(NS, NL), _square(NS + 0.02, NL)
    calc = _make_calc(db, boundary=_tiling_boundary(c1, c2), forest_name="Compartment CF")
    _add_db_unit(db, calc, c1, "C1", is_compartment=True, index=1, code="C1")
    _add_db_unit(db, calc, c2, "C2", is_compartment=True, index=2, code="C2")

    resp = _gen(db, calc)

    assert resp.unit_type == "compartment"
    assert resp.unit_count == 2
    assert _names(db, calc.id) == {"C1", "C2"}


def test_a_legacy_mixed_forest_gets_fieldbook_points_for_its_whole_leaf_view(db):
    """FS-1a.4: a plain block beside compartments (a legacy mixed forest) is still forest ground, so it gets
    fieldbook points too - it used to be dropped silently."""
    c1, c2, b1 = _square(NS, NL), _square(NS + 0.02, NL), _square(NS + 0.03, NL + 0.03)
    calc = _make_calc(db, boundary=_tiling_boundary(c1, c2, b1), forest_name="Mixed CF")
    _add_db_unit(db, calc, c1, "C1", is_compartment=True, index=1, code="C1")
    _add_db_unit(db, calc, c2, "C2", is_compartment=True, index=2, code="C2")
    _add_db_unit(db, calc, b1, "Block-1", index=3)

    resp = _gen(db, calc)

    assert resp.unit_count == 3
    assert _names(db, calc.id) == {"C1", "C2", "Block-1"}


def test_sources_from_blocks_when_no_compartments(db):
    b1, b2 = _square(NS, NL), _square(NS + 0.02, NL)
    calc = _make_calc(db, boundary=_tiling_boundary(b1, b2), forest_name="Block CF")
    _add_db_unit(db, calc, b1, "Block-1", index=1)
    _add_db_unit(db, calc, b2, "Block-2", index=2)

    resp = _gen(db, calc)

    assert resp.unit_type == "block"
    assert resp.unit_count == 2
    assert _names(db, calc.id) == {"Block-1", "Block-2"}


def test_legacy_result_data_fallback_when_no_db_rows(db):
    """Upload-mode forest: no forest_blocks rows at all, blocks only in
    result_data. Must still work (mirrors extract_blocks_from_calculation)."""
    north, south = _square(NS, NL), _square(NS, NL + 0.02)
    calc = _make_calc(
        db, boundary=_tiling_boundary(north, south),
        result_data={
            "blocks": [
                {"block_name": "North", "geometry": north.__geo_interface__},
                {"block_name": "South", "geometry": south.__geo_interface__},
            ]
        },
    )

    resp = _gen(db, calc)

    assert resp.unit_type == "block"
    assert _names(db, calc.id) == {"North", "South"}


# ---------------------------------------------------------------------------
# B -- interpolation threshold
# ---------------------------------------------------------------------------

def test_interpolation_above_threshold_inserted(db):
    big = _square(NS, NL, size=0.01)  # edges ~1.1km >> 50m
    calc = _make_calc(db, boundary=big, forest_name="Big Block CF")
    _add_db_unit(db, calc, big, "Block-1", index=1)

    resp = _gen(db, calc, spacing=50.0)

    assert resp.interpolated_points > 0
    assert any(p.point_type == "interpolated" for p in _points(db, calc.id))


def test_interpolation_below_threshold_not_inserted(db):
    small = _tiny_square(NS, NL, size=0.0001)  # edges ~10m < 50m
    calc = _make_calc(db, boundary=small, forest_name="Small Block CF")
    _add_db_unit(db, calc, small, "Block-1", index=1)

    resp = _gen(db, calc, spacing=50.0)

    assert resp.interpolated_points == 0
    assert resp.total_vertices == 4


def test_single_block_points_all_carry_block_identity(db):
    """Regression (old §2 item 9): every point -- vertex or interpolated -- of a one-block forest carries
    that block's identity."""
    big = _square(NS, NL, size=0.01)
    calc = _make_calc(db, boundary=big, forest_name="Lone Block CF")
    _add_db_unit(db, calc, big, "Block-1", index=1)

    resp = _gen(db, calc, spacing=50.0)

    assert resp.interpolated_points > 0
    pts = _points(db, calc.id)
    assert all(p.block_name == "Block-1" and p.block_number is not None for p in pts)


# ---------------------------------------------------------------------------
# the new fields are saved
# ---------------------------------------------------------------------------

def _two_blocks(db, name="Adjacent CF"):
    mid, size = NS + 0.01, 0.01
    a = Polygon([(NS, NL), (mid, NL), (mid, NL + size), (NS, NL + size)])
    b = Polygon([(mid, NL), (mid + size, NL), (mid + size, NL + size), (mid, NL + size)])
    calc = _make_calc(db, boundary=_tiling_boundary(a, b), forest_name=name)
    _add_db_unit(db, calc, a, "Block-1", index=1)
    _add_db_unit(db, calc, b, "Block-2", index=2)
    return calc


def test_points_are_saved_outer_first_with_labels_classes_and_remarks(db):
    calc = _two_blocks(db)
    resp = _gen(db, calc, spacing=50.0)
    pts = _points(db, calc.id)

    assert resp.outer_points + resp.internal_points == resp.total_points == len(pts)
    classes = [p.boundary_class for p in pts]
    assert classes == ["outer"] * resp.outer_points + ["internal"] * resp.internal_points
    assert pts[0].point_label == "O1" and pts[resp.outer_points].point_label == "I1"
    assert [p.point_number for p in pts] == list(range(1, len(pts) + 1))
    assert all(p.remarks for p in pts)
    assert all(p.remarks.startswith(p.boundary_class) for p in pts)
    # the two places the shared edge meets the outer ring separate BOTH blocks
    junctions = [p for p in pts if p.is_junction]
    assert len(junctions) == resp.junction_points == 2
    assert all(p.adjacent_units == ["Block-1", "Block-2"] and p.junction_degree == 2 for p in junctions)
    assert all(p.remarks == "outer: Block-1, Block-2" for p in junctions)


def test_the_shared_edge_has_one_set_of_points_not_two(db):
    calc = _two_blocks(db)
    _gen(db, calc, spacing=50.0)
    internal = [p for p in _points(db, calc.id) if p.boundary_class == "internal"]
    coords = [(p.longitude, p.latitude) for p in internal]
    assert len(coords) == len(set(coords))
    assert all(p.adjacent_units == ["Block-1", "Block-2"] for p in internal)
    # ~1.1 km edge at 50 m: about 22 points once, not 44
    assert 18 <= len(internal) <= 24


def test_navigation_points_at_the_next_labelled_point(db):
    calc = _two_blocks(db)
    _gen(db, calc, spacing=50.0)
    pts = {p.point_label: p for p in _points(db, calc.id)}
    checked = 0
    for p in pts.values():
        if p.next_point_label:
            q = pts[p.next_point_label]
            d = calculate_distance(float(p.longitude), float(p.latitude), float(q.longitude), float(q.latitude))
            assert abs(d - float(p.distance_to_next)) < 0.05
            checked += 1
    assert checked >= len(pts) - 2


def test_regenerating_replaces_the_old_book(db):
    calc = _two_blocks(db)
    _gen(db, calc, spacing=50.0)
    n1 = len(_points(db, calc.id))
    _gen(db, calc, spacing=50.0)
    assert len(_points(db, calc.id)) == n1


def test_the_api_schema_serialises_the_new_fields(db):
    from app.schemas.fieldbook import FieldbookPoint
    calc = _two_blocks(db)
    _gen(db, calc)
    row = next(p for p in _points(db, calc.id) if p.is_junction)
    out = FieldbookPoint.model_validate(row)
    assert out.point_label.startswith("O") and out.boundary_class == "outer"
    assert out.adjacent_units == ["Block-1", "Block-2"] and out.is_junction is True


# ---------------------------------------------------------------------------
# sub-areas take part
# ---------------------------------------------------------------------------

def test_a_sub_area_corner_on_a_block_corner_keeps_both_columns_on_one_row(db):
    block = _square(NS, NL, size=0.01)
    calc = _make_calc(db, boundary=block, forest_name="Mixed CF")
    _add_db_unit(db, calc, block, "Block-1", index=1)
    # the sub-area's corner exactly touches the block's (NS, NL) corner from outside-left... inside the block here
    _add_subarea(db, calc, Polygon([(NS, NL), (NS + 0.005, NL), (NS + 0.005, NL + 0.005), (NS, NL + 0.005)]), "Protected A")

    _gen(db, calc)

    pts = _points(db, calc.id)
    shared = [p for p in pts if p.block_name == "Block-1" and p.sub_area_name == "Protected A"]
    assert shared
    coords = [(p.longitude, p.latitude) for p in pts]
    assert len(coords) == len(set(coords))


def test_result_data_subareas_are_used_even_with_workspace_managed_blocks(db):
    """Regression for the real bug found in user testing: `add_sub_area` writes sub-areas ONLY to
    result_data['sub_areas'] -- ForestSubArea DB rows are never created by live code. A sub-area that exists only
    there must still surface its name AND category (and now its unit) on the generated points."""
    block = _square(NS, NL, size=0.03)
    calc = _make_calc(
        db, boundary=block, forest_name="Real World CF",
        result_data={"sub_areas": [
            _result_data_subarea("Kalika Mandir", _square(NS + 0.01, NL + 0.01, size=0.005), category="religious", is_excluded=False),
        ]},
    )
    _add_db_unit(db, calc, block, "Block-1", index=1)

    _gen(db, calc)

    sub = [p for p in _points(db, calc.id) if p.sub_area_name]
    assert len(sub) == 4, "the sub-area's 4 corners must all carry its name"
    assert all(p.sub_area_name == "Kalika Mandir" and p.sub_area_category == "religious" and p.is_excluded is False for p in sub)
    assert all(p.boundary_class == "internal" for p in sub)
    assert all(p.adjacent_units == ["Block-1"] for p in sub)          # the unit it lies in
    assert all(p.remarks == "internal: Block-1; sub-area: Kalika Mandir" for p in sub)


def test_a_multipolygon_legacy_block_is_walked_as_independent_rings(db):
    """A legacy result_data block whose own geometry is a MultiPolygon (two disjoint parts) is two rings --
    never one ring with a fabricated edge across the gap."""
    part_a, part_b = _square(NS, NL, size=0.005), _square(NS + 0.05, NL, size=0.005)
    multi = MultiPolygon([part_a, part_b])
    calc = _make_calc(db, boundary=multi, result_data={"blocks": [{"block_name": "Island Block", "geometry": multi.__geo_interface__}]})

    resp = _gen(db, calc)

    assert resp.total_vertices == 8
    assert all(float(p.distance_to_next) < 2000 for p in _points(db, calc.id))
    expected = sum(
        calculate_distance(float(a[0]), float(a[1]), float(b[0]), float(b[1]))
        for ring in (list(part_a.exterior.coords)[:-1], list(part_b.exterior.coords)[:-1])
        for a, b in zip(ring, ring[1:] + ring[:1])
    )
    assert abs(float(resp.total_perimeter_meters) - expected) < 1.0


# ---------------------------------------------------------------------------
# OP variables
# ---------------------------------------------------------------------------

def test_op_fieldbook_variables_resolve_and_use_the_new_labels(db):
    calc = _two_blocks(db, name="Variables CF")
    _add_subarea(db, calc, _square(NS + 0.002, NL + 0.002, size=0.002), "Temple Grove", category="conservation")

    resp = _gen(db, calc)
    data = _fetch_fieldbook_data(db, calc.id)

    assert data["available"] is True
    assert data["total_points"] == resp.total_points
    assert isinstance(data["block_summary"], list) and data["block_summary"]
    labels = [row["बिन्दु_नं"] for row in data["points"]]
    assert labels[0] == "O1" and any(str(l).startswith("I") for l in labels)
    assert "ब्लकको_नाम" not in data["points"][0]            # replaced by the remark: it already names the units
    assert any("Block-1, Block-2" in row["कैफियत"] for row in data["points"])
    assert any("Temple Grove" in row.get("उप-क्षेत्र", "") and "conservation" in row.get("उप-क्षेत्र", "") for row in data["points"])
    # the document's perimeter is the forest's outer boundary
    assert abs(data["perimeter_m"] - float(resp.total_perimeter_meters)) < 2.0


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def _forest_with_subarea(db):
    from app.services.export import (
        export_fieldbook_csv, export_fieldbook_excel, export_fieldbook_gpx, export_fieldbook_geojson,
    )
    block = _square(NS, NL, size=0.03)
    calc = _make_calc(
        db, boundary=block, forest_name="Export CF",
        result_data={"sub_areas": [
            _result_data_subarea("Kalika Mandir", _square(NS + 0.01, NL + 0.01, size=0.002), category="religious", is_excluded=False),
        ]},
    )
    _add_db_unit(db, calc, block, "Block-1", index=1)
    _gen(db, calc)
    return calc, export_fieldbook_csv, export_fieldbook_excel, export_fieldbook_gpx, export_fieldbook_geojson


def _csv_rows(csv_bytes):
    import csv
    return list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))


def test_export_csv_has_labels_and_class_and_none_of_the_old_defects(db):
    calc, export_csv, _, _, _ = _forest_with_subarea(db)
    rows = _csv_rows(export_csv(db, calc.id))
    header, data = rows[0], rows[1:]
    text = "\n".join(",".join(r) for r in rows)

    assert "Kalika Mandir" in text and "religious" in text
    # the debug column is gone
    assert "TEST_NEW_CODE_LOADED" not in header and all(r[0] != "YES" for r in data)
    # labels + outer/internal + adjacent units + next point
    col = {h.split("(")[-1].rstrip(")").strip(): i for i, h in enumerate(header)}
    assert data[0][0] == "O1"
    assert data[0][col["Outer/Internal"]] == "outer"
    assert "Remarks" in col and "Next Point" in col
    assert data[0][col["Remarks"]].startswith("outer")
    assert any(r[0].startswith("I") and r[col["Outer/Internal"]] == "internal" for r in data)
    # ONE column says what a point is and which units it separates: no separate Block / Adjacent Units column
    assert not any("Block" in h or "Adjacent" in h or "Separates" in h for h in header), header
    # latitude / longitude: each value sits under its own heading
    lat_i, lon_i = col["Latitude"], col["Longitude"]
    assert 27 < float(data[0][lat_i]) < 28 and 83 < float(data[0][lon_i]) < 84


def test_export_csv_keeps_a_real_zero_instead_of_blanking_it(db):
    from app.services.fieldbook_record import csv_text
    assert csv_text("azimuth", 0.0) == "0.00" and csv_text("azimuth", None) == "" and csv_text("distance", 12.345) == "12.35"


def test_export_excel_has_the_classification_columns_and_summary(db):
    from openpyxl import load_workbook
    calc, _, export_excel, _, _ = _forest_with_subarea(db)
    wb = load_workbook(io.BytesIO(export_excel(db, calc.id)))
    ws = wb["Points"]
    headers = [c.value for c in ws[1]]
    for h in ("सीमा (Outer/Internal)", "जंक्सन (Junction)", "कैफियत (Remarks)", "अर्को बिन्दु (Next Point)",
              "उप-क्षेत्रको नाम (Sub-area Name)", "उप-क्षेत्रको प्रकार (Sub-area Category)"):
        assert h in headers, h
    assert not any("Block" in h or "Adjacent" in h for h in headers), headers
    cls_col = headers.index("सीमा (Outer/Internal)") + 1
    labels = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    classes = [ws.cell(row=r, column=cls_col).value for r in range(2, ws.max_row + 1)]
    assert labels[0] == "O1" and classes[0] == "outer"
    assert "internal" in classes
    names = [ws.cell(row=r, column=headers.index("उप-क्षेत्रको नाम (Sub-area Name)") + 1).value for r in range(2, ws.max_row + 1)]
    assert "Kalika Mandir" in names
    summary = {ws2.value: ws2.offset(column=1).value for ws2 in wb["Summary"]["A"] if ws2.value}
    assert summary["Outer boundary points (O)"] and summary["Internal boundary points (I)"]
    assert summary["Outer Perimeter (m)"] > 0


def test_export_gpx_names_points_by_label_and_describes_them(db):
    calc, _, _, export_gpx, _ = _forest_with_subarea(db)
    text = export_gpx(db, calc.id).decode("utf-8")
    assert "<name>O1</name>" in text and "<name>I1</name>" in text
    assert "Kalika Mandir" in text and "Category: religious" in text
    assert "outer: Block-1" in text


def test_export_geojson_has_labels_classes_and_correct_coordinate_order(db):
    calc, _, _, _, export_geojson = _forest_with_subarea(db)
    all_features = export_geojson(db, calc.id)["features"]
    # the export holds the points AND the lines joining them; this test is about the points
    features = [f for f in all_features if f["properties"]["layer"] == "point"]
    assert features and len(features) < len(all_features)
    first = features[0]["properties"]
    assert first["point"] == "O1" and first["boundary"] == "outer"
    assert any(f["properties"]["boundary"] == "internal" for f in features)
    sub = [f for f in features if f["properties"].get("sub_area") == "Kalika Mandir"]
    assert sub and all(f["properties"]["sub_area_category"] == "religious" for f in sub)
    assert all("Block-1" in f["properties"]["remarks"] for f in sub)       # the remark names the unit
    # RFC 7946: [longitude, latitude]
    for f in features:
        lon, lat = f["geometry"]["coordinates"]
        assert 83 < lon < 84 and 27 < lat < 28, f"coordinates look swapped: {lon}, {lat}"


def test_export_excel_has_a_junctions_sheet_listing_only_the_junction_points(db):
    from openpyxl import load_workbook
    from app.services.export import export_fieldbook_excel
    calc = _two_blocks(db, name="Junction Sheet CF")
    resp = _gen(db, calc, spacing=50.0)

    wb = load_workbook(io.BytesIO(export_fieldbook_excel(db, calc.id)))
    assert "Junctions" in wb.sheetnames
    ws = wb["Junctions"]
    rows = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
    assert len(rows) == resp.junction_points == 2
    assert all(r[1] == "outer" and r[3] == "outer: Block-1, Block-2" and str(r[2]) == "2" for r in rows)
    # every junction in the sheet is a point of the main sheet
    main = {c.value for c in wb["Points"]["A"]}
    assert all(r[0] in main for r in rows)


def test_a_forest_without_junctions_has_no_junctions_sheet(db):
    from openpyxl import load_workbook
    from app.services.export import export_fieldbook_excel
    block = _square(NS, NL, size=0.01)
    calc = _make_calc(db, boundary=block, forest_name="One Block CF")
    _add_db_unit(db, calc, block, "Block-1", index=1)
    _gen(db, calc)
    assert "Junctions" not in load_workbook(io.BytesIO(export_fieldbook_excel(db, calc.id))).sheetnames
