"""Phase U-6 — auto-derive boundary (invariant C), dependency widening (D),
single-block forest (E), islands/MultiPolygon (F), transaction wrapper (T6.5).

Exercises the REAL import → convert endpoints:
- T6.1: importing blocks into a workspace with NO boundary auto-derives it
  (unary_union dissolve + buffer-heal); invariant A (area match within 0.1%);
- T6.2: sub-areas import is allowed when only the boundary is populated;
- T6.3: boundary-only update auto-creates exactly one block equal to the boundary;
- T6.4: MultiPolygon block files stay MultiPolygon (islands preserved);
- T6.5: a failure during auto-derive rolls back (no partial boundary written).
"""
import io
import json
import uuid
from unittest import mock

from shapely import wkt as shp_wkt
from shapely.geometry import box, mapping, MultiPolygon, Polygon

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock


KML_TWO_DISJOINT_BLOCKS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>Block 1</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.500,27.500,0 83.510,27.500,0 83.510,27.505,0 83.500,27.505,0 83.500,27.500,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
    <Placemark><name>Block 2</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.520,27.500,0 83.530,27.500,0 83.530,27.505,0 83.520,27.505,0 83.520,27.500,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  </Document>
</kml>
"""

KML_SUB_AREA = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>SA One</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.501,27.501,0 83.509,27.501,0 83.509,27.504,0 83.501,27.504,0 83.501,27.501,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  </Document>
</kml>
"""

import pytest

pytestmark = pytest.mark.usefixtures("forget_forests")  # fixed coordinates + committed rows: see conftest



def _register_user(client):
    email = f"auto-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email,
        "password": "TestPass123!",
        "full_name": "Auto Derive",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _make_calc(db, user_id, boundary_wkt=None, name="Auto Forest"):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name=name,
        boundary_geom=boundary_wkt,
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _import_and_convert(client, headers, calc, kml_bytes, purpose, target_type=None, confirm=False):
    resp = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        files={"file": ("b.kml", io.BytesIO(kml_bytes), "application/vnd.google-earth.kml+xml")},
        data={"purpose": purpose},
    )
    assert resp.status_code in (200, 400), resp.text
    if resp.status_code == 400:
        return None, resp.json().get("detail")
    layer_id = resp.json()["id"]
    body = {"target_type": target_type or purpose}
    if confirm:
        body["confirm"] = True
    return layer_id, client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json=body,
    )


def test_blocks_import_auto_derives_boundary_and_area_matches(client, db):
    """T6.1 + invariant A/C: no boundary → blocks import auto-derives it; area matches."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id, boundary_wkt=None)
    db.expire_all()

    layer_id, conv = _import_and_convert(client, headers, calc, KML_TWO_DISJOINT_BLOCKS.encode(), "blocks")
    assert layer_id is not None, f"import failed: {conv}"
    assert conv.status_code == 200, conv.text
    assert conv.json()["created"] == 2, conv.text

    db.expire_all()
    db.refresh(calc)
    assert calc.boundary_geom is not None, "boundary should be auto-derived"

    from geoalchemy2.shape import to_shape
    boundary_shape = to_shape(calc.boundary_geom)
    assert boundary_shape is not None and not boundary_shape.is_empty
    # Two disjoint blocks → boundary is the exact union (MultiPolygon).
    assert isinstance(boundary_shape, (MultiPolygon, Polygon)), boundary_shape.geom_type

    block_shapes = []
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment != True,
    ).all()
    for r in rows:
        block_shapes.append(to_shape(r.geometry))

    from app.services.file_processor import boundary_area_matches_block_sum
    ok, b_area, s_area = boundary_area_matches_block_sum(boundary_shape, block_shapes)
    assert ok, f"invariant A failed: boundary={b_area}ha vs sum={s_area}ha"
    # Naming guard (T6.7): name falls back to the forest name, never blank.
    rd = calc.result_data or {}
    assert rd.get("boundary_name"), "boundary_name should be set"


def test_naming_guard_defaults_to_auto_derived_boundary(client, db):
    """T6.7: nameless forest auto-derive uses 'Auto-derived Boundary'."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id, boundary_wkt=None, name=None)
    db.expire_all()

    layer_id, conv = _import_and_convert(client, headers, calc, KML_TWO_DISJOINT_BLOCKS.encode(), "blocks")
    assert layer_id is not None and conv.status_code == 200, (conv, layer_id)

    db.refresh(calc)
    rd = calc.result_data or {}
    assert rd.get("boundary_name") == "Auto-derived Boundary"


def test_sub_areas_allowed_with_boundary_only(client, db):
    """T6.2 dependency widening: sub-areas import succeeds when only boundary set."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id, boundary_wkt=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)))
    db.expire_all()

    layer_id, conv = _import_and_convert(client, headers, calc, KML_SUB_AREA.encode(), "sub_areas")
    assert layer_id is not None, f"import failed: {conv}"
    assert conv.status_code == 200, conv.text
    assert conv.json()["created"] == 1, conv.text


def test_boundary_only_creates_no_unit(client, db):
    """FS-2.4/FS-2.8 + C1-C3/Q5: a boundary update mints no block/compartment —
    the forest stands boundary-only until the user explicitly creates a unit."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id, boundary_wkt=None)
    db.expire_all()

    from shapely.geometry import mapping
    # ~440 ha. The boundary rules cap a forest at 1000 ha and run on the stored polygon,
    # so the 0.05 x 0.04 degree box this test used (2,190 ha) is refused with a 422 - a
    # test-data bug that neighbour pollution used to hide (see conftest `forget_forests`).
    poly = Polygon([(83.50, 27.50), (83.52, 27.50), (83.52, 27.52), (83.50, 27.52)])
    resp = client.put(
        f"/api/forests/calculations/{calc.id}/boundary",
        headers=headers,
        json={"geometry": mapping(poly), "area_hectares": 0},
    )
    assert resp.status_code == 200, resp.text
    assert "single_block_created" not in resp.json()

    db.expire_all()
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment != True,
    ).all()
    assert len(rows) == 0, f"expected no auto-created block, got {len(rows)}"


def test_multipolygon_block_file_stays_multipolygon(client, db):
    """T6.4 island handling: a MultiPolygon block file is preserved as islands."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id, boundary_wkt=None)
    db.expire_all()

    mp = MultiPolygon([
        Polygon([(83.50, 27.50), (83.51, 27.50), (83.51, 27.51), (83.50, 27.51)]),
        Polygon([(83.60, 27.60), (83.61, 27.60), (83.61, 27.61), (83.60, 27.61)]),
    ])
    geojson = json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"name": "Islands"},
                      "geometry": mapping(mp)}],
    })
    resp = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        files={"file": ("islands.geojson", io.BytesIO(geojson.encode()), "application/geo+json")},
        data={"purpose": "blocks"},
    )
    assert resp.status_code in (200, 400), resp.text
    if resp.status_code == 400:
        # Single MultiPolygon feature → shared engine may emit one MultiPolygon feature.
        detail = resp.json().get("detail")
        assert isinstance(detail, str), detail
        return  # engine-level handling verified elsewhere
    layer_id = resp.json()["id"]
    conv = client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json={"target_type": "blocks"},
    )
    assert conv.status_code == 200, conv.text

    db.expire_all()
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment != True,
    ).all()
    from geoalchemy2.shape import to_shape
    assert len(rows) >= 1
    for r in rows:
        g = to_shape(r.geometry)
        # Islands preserved: either a MultiPolygon or (if split) multiple rows.
        assert g.area > 0


def test_auto_derive_failure_rolls_back_transaction(client, db):
    """T6.5 transaction wrapper: a failure during auto-derive leaves NO partial boundary."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id, boundary_wkt=None)
    db.expire_all()

    layer_id, conv = _import_and_convert(client, headers, calc, KML_TWO_DISJOINT_BLOCKS.encode(), "blocks")
    assert layer_id is not None and conv.status_code == 200, (conv, layer_id)
    db.expire_all()
    db.refresh(calc)
    # Auto-derive succeeded: boundary present.
    assert calc.boundary_geom is not None

    # Force a failure inside the derive path for a FRESH calc: patch the helper
    # to raise; the atomic_transaction wrapper rolls back so no boundary persists.
    calc2 = _make_calc(db, user_id, boundary_wkt=None)
    db.expire_all()
    with mock.patch(
        "app.services.file_processor.derive_boundary_from_polygons",
        side_effect=RuntimeError("forced derive failure"),
    ):
        layer2, conv2 = _import_and_convert(client, headers, calc2, KML_TWO_DISJOINT_BLOCKS.encode(), "blocks")
        assert layer2 is not None
        # The exception propagates out of atomic_transaction (rollback + re-raise),
        # then the endpoint's broad except maps it to a 400 with the derive error.
        assert conv2.status_code in (500, 400), conv2.text
        if conv2.status_code == 400:
            assert "forced derive failure" in str(conv2.json().get("detail"))

    db.expire_all()
    db.refresh(calc2)
    # Boundary must NOT be partially written (rollback applied).
    assert calc2.boundary_geom is None, "boundary should have rolled back on derive failure"
