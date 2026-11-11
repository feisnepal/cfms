"""Phase U-3 integration tests — KML sub-areas import → convert regression (Task 3.2).

Goal: reproduce and guard the reported "No valid geometries to convert"
(workspace.py convert-to-builtin) when importing a KML polygon as sub_areas.

Known ruled out (see plan audit): the empty-clip theory — clip_to_region returns
the geometry unchanged for an empty region, and validate_first_layer requires
blocks first. These tests exercise the REAL import → convert path end to end and
assert:
- a well-formed KML polygon inside the boundary/blocks converts cleanly;
- the diagnostics path (diag counters + clear error message) is reachable.
"""
import io
import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box
from sqlalchemy import text

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock


KML_POLY = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>SubArea One</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              83.50,27.50,0
              83.505,27.50,0
              83.505,27.505,0
              83.50,27.505,0
              83.50,27.50,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>SubArea Two</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              83.51,27.50,0
              83.515,27.50,0
              83.515,27.505,0
              83.51,27.505,0
              83.51,27.50,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
"""


def _register_user(client):
    email = f"kml-repro-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email,
        "password": "TestPass123!",
        "full_name": "KML Repro",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _make_calc(db, user_id):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="KML Repro Forest",
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _make_block(db, calc):
    block = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name="Block 1",
        geometry=shp_wkt.dumps(box(83.2, 27.2, 83.9, 27.9)),
        area_hectares=1.0,
        index=0,
        division_level=1,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def _import_and_convert(client, headers, calc, kml_bytes):
    resp = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        files={"file": ("subareas.kml", io.BytesIO(kml_bytes), "application/vnd.google-earth.kml+xml")},
        data={"purpose": "sub_areas"},
    )
    assert resp.status_code in (200, 400), resp.text
    if resp.status_code == 400:
        return None, resp.json().get("detail")

    layer_id = resp.json()["id"]
    convert_resp = client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json={"target_type": "sub_areas"},
    )
    return layer_id, convert_resp


def test_kml_polygon_import_and_convert_succeeds(client, db):
    """A well-formed KML polygon inside the boundary/blocks converts cleanly."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    db.expire_all()

    layer_id, result = _import_and_convert(client, headers, calc, KML_POLY.encode("utf-8"))
    assert layer_id is not None, f"import failed: {result}"
    assert result.status_code == 200, result.text
    body = result.json()
    assert body.get("created", 0) >= 1
    assert body.get("import_summary", {}).get("imported", 0) >= 1


def test_kml_repro_needs_block_first(client, db):
    """Importing sub-areas with NO block AND NO boundary present fails with the
    dependency guard, not 'No valid geometries to convert' (rules out the
    empty-clip theory). With T6.2 widening, either a Block/Compartment layer OR
    the forest boundary satisfies the dependency — so this test uses a boundary-less
    workspace to assert the guard still fires when truly nothing exists."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    calc.boundary_geom = None  # no boundary, no blocks → dependency not satisfied
    db.commit()
    db.expire_all()

    resp = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        files={"file": ("subareas.kml", io.BytesIO(KML_POLY.encode("utf-8")), "application/vnd.google-earth.kml+xml")},
        data={"purpose": "sub_areas"},
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "imports.boundary_required_first"
    assert "Block or Compartment" in detail["message"]
    assert detail["message_np"]


def test_clear_all_subareas_endpoint(client, db):
    """DELETE /calculations/{id}/sub-areas clears ALL sub-areas from result_data,
    resets excluded/effective areas, and mirrors forest_sub_areas table."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    calc.result_data = {
        "sub_areas": [
            {"id": str(uuid.uuid4()), "name": "SA One", "area_hectares": 2.0, "category": "excluded", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
            {"id": str(uuid.uuid4()), "name": "SA Two", "area_hectares": 3.0, "category": "buffer_strip", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
        ],
        "sub_areas_count": 2,
        "area_hectares": 100.0,
        "excluded_area_hectares": 2.0,
        "effective_area_hectares": 98.0,
        "blocks": [],
    }
    db.commit()
    db.expire_all()

    resp = client.delete(f"/api/forests/calculations/{calc.id}/sub-areas", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_count"] == 2, body

    db.expire_all()
    calc = db.get(Calculation, calc.id)
    rd = calc.result_data or {}
    assert rd.get("sub_areas", []) == []
    assert rd.get("sub_areas_count") == 0
    assert rd.get("excluded_area_hectares") == 0.0
    assert rd.get("effective_area_hectares") == 100.0


def test_clear_all_subareas_empty_ok(client, db):
    """Clearing when no sub-areas exist is a no-op success."""
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    calc.result_data = {"sub_areas": []}
    db.commit()
    db.expire_all()

    resp = client.delete(f"/api/forests/calculations/{calc.id}/sub-areas", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_count"] == 0, resp.text
