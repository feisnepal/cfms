"""FS-4a.19 — importable sub-blocks + replace-safety (block-branch mirror).

Exercises the REAL convert-to-builtin endpoint for the block branch:
- sub_blocks import requires >=1 top-level block and clips to blocks;
- a sub-block import REPLACES the non-compartment derived rows at/below the
  sub level (mirroring sub_compartments) with a T5.3 pre-flight gate;
- on confirm, a snapshot is stored under result_data and can be restored via
  /geometry-import-backup/restore (wrong-file import undo);
- sub-block rows are non-compartment, depth DEPTH_SUB, no compartment_code,
  and attach to their containing top-level block.
"""
import io
import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.services.forest_units.model import DEPTH_SUB, DEPTH_TOP_BLOCK

pytestmark = pytest.mark.usefixtures("forget_forests")  # fixed coordinates + committed rows: see conftest


KML_SUB_BLOCKS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>SB A1</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.501,27.501,0 83.509,27.501,0 83.509,27.504,0 83.501,27.504,0 83.501,27.501,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
    <Placemark><name>SB A2</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.511,27.501,0 83.519,27.501,0 83.519,27.504,0 83.511,27.504,0 83.511,27.501,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  </Document>
</kml>
"""

# Outside any block (block is 83.2-83.9 x 27.2-27.9): clipped away.
# Small (0.02 deg²) so it stays under the 1000-ha import area limit.
KML_SUB_OUTSIDE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>SB Out</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.91,27.71,0 83.93,27.71,0 83.93,27.73,0 83.91,27.73,0 83.91,27.71,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  </Document>
</kml>
"""


def _register_user(client):
    email = f"subblk-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email,
        "password": "TestPass123!",
        "full_name": "Sub Block Import",
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
        forest_name="Sub Block Import Forest",
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
        division_level=DEPTH_TOP_BLOCK,
        is_compartment=False,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def _make_sub_block(db, calc, parent, name="SB-old-1", geom=None):
    db.add(ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        geometry=shp_wkt.dumps(geom or box(83.3, 27.3, 83.6, 27.6)),
        area_hectares=1.0,
        index=1,
        division_level=DEPTH_SUB,
        is_compartment=False,
        parent_block_id=parent.id if parent else None,
    ))
    db.commit()


def _import_layer(client, headers, calc, kml_bytes, purpose):
    resp = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        files={"file": ("sub.kml", io.BytesIO(kml_bytes), "application/vnd.google-earth.kml+xml")},
        data={"purpose": purpose},
    )
    assert resp.status_code in (200, 400), resp.text
    if resp.status_code == 400:
        return None, resp.json().get("detail")
    return resp.json()["id"], None


def _convert(client, headers, calc, layer_id, target_type, **extra):
    body = {"target_type": target_type}
    body.update(extra)
    return client.post(
        f"/api/workspace/{calc.id}/import-layers/{layer_id}/convert-to-builtin",
        headers=headers,
        json=body,
    )


def _derived_sub_block_count(db, calc):
    return db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment == False,
        ForestBlock.division_level >= DEPTH_SUB,
    ).count()


def test_sub_blocks_require_block_present(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_SUB_BLOCKS.encode(), "sub_blocks")
    assert layer_id is not None, err

    # No top-level blocks exist yet → 400 "At least one block must exist".
    resp = _convert(client, headers, calc, layer_id, "sub_blocks", confirm=True)
    assert resp.status_code == 400, resp.text
    assert "block" in resp.json()["detail"].lower(), resp.text


def test_purpose_mismatch_rejected(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    db.expire_all()

    # Imported as 'blocks', converted as 'sub_blocks' → 400 purpose mismatch.
    layer_id, err = _import_layer(client, headers, calc, KML_SUB_BLOCKS.encode(), "blocks")
    assert layer_id is not None, err
    resp = _convert(client, headers, calc, layer_id, "sub_blocks", confirm=True)
    assert resp.status_code == 400, resp.text


def test_sub_blocks_import_replaces_derived_with_confirm(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    block = _make_block(db, calc)
    _make_sub_block(db, calc, block, "SB-old-1")
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_SUB_BLOCKS.encode(), "sub_blocks")
    assert layer_id is not None, err

    # T5.3 pre-flight: no confirm → summary, nothing written.
    pre = _convert(client, headers, calc, layer_id, "sub_blocks")
    assert pre.status_code == 200, pre.text
    pre_body = pre.json()
    assert pre_body.get("needs_confirmation") is True, pre_body
    assert pre_body["replace_summary"]["sub_blocks"] >= 1, pre_body
    assert _derived_sub_block_count(db, calc) == 1  # unchanged

    # Confirm → replace happens; imported sub-blocks become the truth.
    resp = _convert(client, headers, calc, layer_id, "sub_blocks", confirm=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("created", 0) == 2, body

    db.expire_all()
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment == False,
        ForestBlock.division_level >= DEPTH_SUB,
    ).all()
    assert len(rows) == 2, [r.name for r in rows]
    assert {r.name for r in rows} == {"SB A1", "SB A2"}
    assert all((r.division_level or 0) == DEPTH_SUB for r in rows)
    assert all(r.compartment_code is None for r in rows), "a sub-block is never coded"
    assert all(r.parent_block_id == block.id for r in rows), "sub-blocks attach to the top-level block"

    # Backup recorded (T5.3) → restorable.
    db.refresh(calc)
    backups = (calc.result_data or {}).get("_geometry_import_backups") or []
    assert backups, "no backup recorded"
    assert backups[-1]["target_type"] == "sub_blocks"
    assert backups[-1]["items"], "backup empty"
    assert backups[-1]["items"][0]["name"] == "SB-old-1"


def test_sub_blocks_import_without_existing_derived_no_confirm_needed(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_SUB_BLOCKS.encode(), "sub_blocks")
    assert layer_id is not None, err

    # No existing derived state → no pre-flight gate; direct convert succeeds.
    resp = _convert(client, headers, calc, layer_id, "sub_blocks", confirm=True)
    assert resp.status_code == 200, resp.text
    assert resp.json().get("created", 0) == 2


def test_restore_backup_undoes_sub_block_replace(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    block = _make_block(db, calc)
    _make_sub_block(db, calc, block, "SB-old-1")
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_SUB_BLOCKS.encode(), "sub_blocks")
    assert layer_id is not None, err
    resp = _convert(client, headers, calc, layer_id, "sub_blocks", confirm=True)
    assert resp.status_code == 200, resp.text
    assert resp.json().get("created", 0) == 2
    assert _derived_sub_block_count(db, calc) == 2

    # Wrong-file import → restore the backup.
    restore = client.post(
        f"/api/workspace/{calc.id}/geometry-import-backup/restore",
        headers=headers,
        json={"target_type": "sub_blocks"},
    )
    assert restore.status_code == 200, restore.text
    assert restore.json()["restored"] >= 1

    db.expire_all()
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment == False,
        ForestBlock.division_level >= DEPTH_SUB,
    ).all()
    assert len(rows) == 1, [r.name for r in rows]
    assert rows[0].name == "SB-old-1"
    assert rows[0].compartment_code is None
    # Restore mirrors sub_compartments: only ids inside the backup are re-linked,
    # so the (non-backed-up) top-level block parent is dropped. Parent re-attach
    # is the same restore gap the compartment-branch has.
    assert rows[0].parent_block_id is None


def test_sub_block_outside_blocks_clipped_away(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_SUB_OUTSIDE.encode(), "sub_blocks")
    assert layer_id is not None, err

    resp = _convert(client, headers, calc, layer_id, "sub_blocks", confirm=True)
    # Everything is outside every block → clipped away → created_count == 0 → 400.
    assert resp.status_code == 400, resp.text
    assert "outside" in resp.json().get("detail", "").lower(), resp.text


# FS-4a.19 multipart regression: a single source feature that is a 3-part
# MultiPolygon (three disjoint substantial islands, like the island-clustered
# hull a user drew) must become ONE ForestBlock row per part on convert, NEVER a
# single MultiPolygon row (the ORM @validates('geometry') guard rejects that
# with MultiPartFeatureError, and the ST_GeomFromText sites in the old code
# persisted it silently as one corrupt row).
GEOJSON_SUB_BLOCK_MULTIPART = """{
  "type": "FeatureCollection",
  "features": [
    {"type": "Feature",
     "properties": {"name": "MP 1"},
     "geometry": {"type": "MultiPolygon", "coordinates": [
       [[[83.310, 27.310, 0], [83.320, 27.310, 0], [83.320, 27.318, 0], [83.310, 27.318, 0], [83.310, 27.310, 0]]],
       [[[83.410, 27.310, 0], [83.420, 27.310, 0], [83.420, 27.318, 0], [83.410, 27.318, 0], [83.410, 27.310, 0]]],
       [[[83.510, 27.310, 0], [83.520, 27.310, 0], [83.520, 27.318, 0], [83.510, 27.318, 0], [83.510, 27.310, 0]]]
     ]}}
  ]
}
"""


def test_multipart_feature_explodes_into_one_row_per_sub_block(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    block = _make_block(db, calc)
    db.expire_all()

    resp = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        files={"file": ("mp.geojson", io.BytesIO(GEOJSON_SUB_BLOCK_MULTIPART.encode()), "application/geo+json")},
        data={"purpose": "sub_blocks"},
    )
    assert resp.status_code in (200, 400), resp.text
    if resp.status_code == 400:
        raise AssertionError(resp.text)
    layer_id = resp.json()["id"]

    converted = _convert(client, headers, calc, layer_id, "sub_blocks", confirm=True)
    assert converted.status_code == 200, converted.text
    assert converted.json().get("created", 0) == 3, converted.text

    db.expire_all()
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment == False,
        ForestBlock.division_level >= DEPTH_SUB,
    ).all()
    assert len(rows) == 3, [r.name for r in rows]
    assert {r.name for r in rows} == {"MP 1 1", "MP 1 2", "MP 1 3"}
    assert all((r.division_level or 0) == DEPTH_SUB for r in rows)
    assert all(r.compartment_code is None for r in rows)
    assert all(r.parent_block_id == block.id for r in rows)
    # Each row is a single substantial part — never a MultiPolygon.
    from geoalchemy2.shape import to_shape as _toshape

    for r in rows:
        g = _toshape(r.geometry)
        assert g.geom_type == "Polygon", g.geom_type
        assert g.area > 1e-9