"""Phase U-5 (Tasks 5.2/5.3) — importable compartments/sub-compartments + replace-safety.

Exercises the REAL convert-to-builtin endpoint:
- compartments import clips to boundary ∪ blocks and REPLACES derived state;
- sub_compartments import requires >=1 compartment and clips to compartments;
- T5.3 pre-flight gate: with existing derived state and confirm=false, the endpoint
  returns needs_confirmation + a replace summary and writes NOTHING;
- T5.3 backup: on confirm, a snapshot is stored under result_data and can be
  restored via /geometry-import-backup/restore (wrong-file import undo);
- cascade: sub-compartments outside the new compartment boundaries are flagged.
"""
import io
import re
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock


KML_COMPARTMENTS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>Comp A</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.500,27.500,0 83.510,27.500,0 83.510,27.505,0 83.500,27.505,0 83.500,27.500,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
    <Placemark><name>Comp B</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.511,27.500,0 83.521,27.500,0 83.521,27.505,0 83.511,27.505,0 83.511,27.500,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  </Document>
</kml>
"""

KML_SUB_COMPARTMENTS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>SC A1</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.501,27.501,0 83.509,27.501,0 83.509,27.504,0 83.501,27.504,0 83.501,27.501,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  </Document>
</kml>
"""

# This sub-compartment is OUTSIDE the compartment above (83.50-83.52 x 27.50-27.505).
KML_SUB_OUTSIDE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>SC Out</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      83.90,27.70,0 83.95,27.70,0 83.95,27.75,0 83.90,27.75,0 83.90,27.70,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  </Document>
</kml>
"""

import pytest

pytestmark = pytest.mark.usefixtures("forget_forests")  # fixed coordinates + committed rows: see conftest



def _register_user(client):
    email = f"comp-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email,
        "password": "TestPass123!",
        "full_name": "Comp Import",
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
        forest_name="Comp Import Forest",
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


def _import_layer(client, headers, calc, kml_bytes, purpose):
    resp = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        files={"file": ("comp.kml", io.BytesIO(kml_bytes), "application/vnd.google-earth.kml+xml")},
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


def _derived_compartment_count(db, calc):
    return db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment == True,
    ).count()


def test_compartments_import_replaces_derived_with_confirm(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    # Simulate existing derived compartments (from an earlier split).
    for i, (name, geom) in enumerate([("C-old-1", box(83.3, 27.3, 83.6, 27.6))], start=1):
        db.add(ForestBlock(
            id=uuid.uuid4(),
            calculation_id=calc.id,
            name=name,
            geometry=shp_wkt.dumps(geom),
            area_hectares=1.0,
            index=i,
            division_level=1,
            is_compartment=True,
        ))
    db.commit()
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_COMPARTMENTS.encode(), "compartments")
    assert layer_id is not None, err

    # T5.3 pre-flight: no confirm → summary, nothing written.
    pre = _convert(client, headers, calc, layer_id, "compartments")
    assert pre.status_code == 200, pre.text
    pre_body = pre.json()
    assert pre_body.get("needs_confirmation") is True, pre_body
    assert pre_body["replace_summary"]["compartments"] >= 1, pre_body
    assert _derived_compartment_count(db, calc) == 1  # unchanged

    # Confirm → replace happens; imported prepared compartments become the truth.
    resp = _convert(client, headers, calc, layer_id, "compartments", confirm=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("created", 0) == 2, body

    db.expire_all()
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment == True,
    ).all()
    # 2 imported compartments + 1 remainder compartment (BLOCK_BOUNDARY_INVARIANT:
    # uncovered boundary area is auto-filled so total compartment area = boundary).
    assert len(rows) == 3, [r.name for r in rows]
    names = sorted(r.name for r in rows)
    # The two imported names survive; the auto-filled remainder is named C<N> (C1, C2 ...).
    assert {"Comp A", "Comp B"} <= set(names), names
    remainder = [n for n in names if n not in ("Comp A", "Comp B")]
    assert len(remainder) == 1 and re.fullmatch(r"C\d+", remainder[0]), names
    assert all((r.division_level or 0) == 1 for r in rows)

    # Backup recorded (T5.3) → restorable.
    db.refresh(calc)
    backups = (calc.result_data or {}).get("_geometry_import_backups") or []
    assert backups, "no backup recorded"
    assert backups[-1]["target_type"] == "compartments"
    assert backups[-1]["items"], "backup empty"
    assert backups[-1]["items"][0]["name"] == "C-old-1"


def test_compartments_import_without_existing_derived_no_confirm_needed(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_COMPARTMENTS.encode(), "compartments")
    assert layer_id is not None, err

    # No existing derived state → no pre-flight gate; direct convert succeeds.
    resp = _convert(client, headers, calc, layer_id, "compartments", confirm=True)
    assert resp.status_code == 200, resp.text
    assert resp.json().get("created", 0) == 2


def test_restore_backup_undoes_replace(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    db.add(ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name="C-old-1",
        geometry=shp_wkt.dumps(box(83.3, 27.3, 83.6, 27.6)),
        area_hectares=1.0,
        index=1,
        division_level=1,
        is_compartment=True,
    ))
    db.commit()
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_COMPARTMENTS.encode(), "compartments")
    assert layer_id is not None, err
    resp = _convert(client, headers, calc, layer_id, "compartments", confirm=True)
    assert resp.status_code == 200, resp.text
    # 2 imported + 1 remainder compartment (BLOCK_BOUNDARY_INVARIANT auto-fill).
    assert _derived_compartment_count(db, calc) == 3

    # Wrong-file import → restore the backup.
    restore = client.post(
        f"/api/workspace/{calc.id}/geometry-import-backup/restore",
        headers=headers,
        json={"target_type": "compartments"},
    )
    assert restore.status_code == 200, restore.text
    assert restore.json()["restored"] >= 1

    db.expire_all()
    rows = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment == True,
    ).all()
    assert len(rows) == 1, [r.name for r in rows]
    assert rows[0].name == "C-old-1"


def test_sub_compartments_require_compartment_present(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_SUB_COMPARTMENTS.encode(), "sub_compartments")
    assert layer_id is not None, err

    # No compartments exist yet → 400 "At least one compartment must exist".
    resp = _convert(client, headers, calc, layer_id, "sub_compartments", confirm=True)
    assert resp.status_code == 400, resp.text
    assert "compartment" in resp.json()["detail"].lower(), resp.text


def test_sub_compartments_import_into_existing_compartments(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    db.add(ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name="Comp A",
        geometry=shp_wkt.dumps(box(83.3, 27.3, 83.6, 27.6)),
        area_hectares=1.0,
        index=1,
        division_level=1,
        is_compartment=True,
    ))
    db.commit()
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_SUB_COMPARTMENTS.encode(), "sub_compartments")
    assert layer_id is not None, err

    resp = _convert(client, headers, calc, layer_id, "sub_compartments", confirm=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("created", 0) == 1, body

    db.expire_all()
    sub = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.is_compartment == True,
        ForestBlock.division_level >= 2,
    ).first()
    assert sub is not None
    assert sub.parent_block_id is not None, "sub-compartment should attach to a compartment"


def test_cascade_flag_for_outside_sub_compartments(client, db):
    headers, user_id = _register_user(client)
    calc = _make_calc(db, user_id)
    _make_block(db, calc)
    # Existing derived compartment + a sub-compartment that will fall OUTSIDE
    # the new imported compartments.
    comp = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name="C-old-1",
        geometry=shp_wkt.dumps(box(83.3, 27.3, 83.6, 27.6)),
        area_hectares=1.0,
        index=1,
        division_level=1,
        is_compartment=True,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    db.add(ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name="SC-far",
        geometry=shp_wkt.dumps(box(83.9, 27.7, 83.95, 27.75)),
        area_hectares=0.2,
        index=1,
        division_level=2,
        is_compartment=True,
        parent_block_id=comp.id,
    ))
    db.commit()
    db.expire_all()

    layer_id, err = _import_layer(client, headers, calc, KML_COMPARTMENTS.encode(), "compartments")
    assert layer_id is not None, err

    pre = _convert(client, headers, calc, layer_id, "compartments")
    assert pre.status_code == 200, pre.text
    pre_body = pre.json()
    assert pre_body.get("needs_confirmation") is True, pre_body
    # The far sub-compartment is flagged in the cascade list.
    cascade = pre_body["replace_summary"].get("cascade_flags") or []
    assert cascade, f"expected a cascade flag, got {pre_body}"
