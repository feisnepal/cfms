"""VR-3 — the locked-vertex guard as seen through the HTTP API.

Every request here is crafted by hand.  That is the point: the browser hides
locked vertices, so the only way to move one is to skip the browser, and until
VR-3 the API accepted it.  These tests are the enforcement, not a UI mirror.

Blocks tile the boundary exactly, so a block's outer ring lies ON the forest
boundary (shell → locked) while the shared edge between the two blocks is
interior (shared → editable).
"""
import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box
from sqlalchemy import text

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.services.forest_units.model import DEPTH_TOP_BLOCK


BOUNDARY = box(83.0, 27.0, 84.0, 28.0)
# Two blocks tiling the LEFT half; their shared edge x=83.5 runs from y=27.0 to
# y=28.0, so its endpoints sit on the boundary and its interior does not.
A = box(83.0, 27.0, 83.5, 28.0)
B = box(83.5, 27.0, 84.0, 28.0)

pytestmark = pytest.mark.usefixtures("forget_forests")  # fixed coordinates + committed rows: see conftest



def _register(client):
    email = f"vr3-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "VR3 Guard",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _calc(db, user_id, boundary=BOUNDARY):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="VR3 Forest",
        boundary_geom=shp_wkt.dumps(boundary) if boundary is not None else None,
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _block(db, calc, geom, name="B", index=0, **kwargs):
    block = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        geometry=shp_wkt.dumps(geom),
        area_hectares=1.0,
        index=index,
        division_level=kwargs.pop("division_level", DEPTH_TOP_BLOCK),
        **kwargs,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def _url(calc_id):
    return f"/api/v1/calculations/{calc_id}/geometry"


def _stored(db, block_id):
    row = db.execute(text(
        "SELECT ST_AsText(geometry) AS g FROM forest_blocks WHERE id = :id"
    ), {"id": str(block_id)}).first()
    return row.g if row else None


def _user(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["id"]


# ---------------------------------------------------------------------------
# Locked shell vertices
# ---------------------------------------------------------------------------

def test_moving_a_shell_vertex_is_refused_with_vertex_locked(client, db):
    headers = _register(client)
    calc = _calc(db, _user(client, headers))
    a = _block(db, calc, A, name="A", index=0)
    _block(db, calc, B, name="B", index=1)
    db.expire_all()
    before = _stored(db, a.id)

    # (83.0, 27.0) is a corner of the forest boundary → shell → locked.
    attacked = {
        "type": "Polygon",
        "coordinates": [[[83.05, 27.05], [83.5, 27.0], [83.5, 28.0], [83.0, 28.0], [83.05, 27.05]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        json={"layer_type": "blocks", "feature_id": str(a.id), "geometry": attacked},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "VERTEX_LOCKED"
    assert detail["locked_indices"], "the response must say WHICH vertices are locked"

    db.expire_all()
    assert _stored(db, a.id) == before, "a refused edit must not have been persisted"


def test_a_shared_moves_partner_cannot_smuggle_a_locked_move(client, db):
    """The propagation payload is the less obvious route to the same violation."""
    headers = _register(client)
    calc = _calc(db, _user(client, headers))
    a = _block(db, calc, A, name="A", index=0)
    b = _block(db, calc, B, name="B", index=1)
    db.expire_all()
    before_b = _stored(db, b.id)

    legit_a = {
        "type": "Polygon",
        "coordinates": [[[83.0, 27.0], [83.5, 27.0], [83.5, 28.0], [83.0, 28.0], [83.0, 27.0]]],
    }
    # B's (84.0, 27.0) is on the boundary — moving it via shared_moves is the
    # same violation, just posted under a different key.
    attacked_b = {
        "type": "Polygon",
        "coordinates": [[[83.5, 27.0], [83.95, 27.05], [84.0, 28.0], [83.5, 28.0], [83.5, 27.0]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        json={
            "layer_type": "blocks",
            "feature_id": str(a.id),
            "geometry": legit_a,
            "shared_moves": [{"feature_id": str(b.id), "geometry": attacked_b}],
        },
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "VERTEX_LOCKED"
    db.expire_all()
    assert _stored(db, b.id) == before_b


def test_an_unchanged_resubmit_is_accepted(client, db):
    """Round-trip drift must not read as a locked-vertex move (1 mm epsilon)."""
    headers = _register(client)
    calc = _calc(db, _user(client, headers))
    a = _block(db, calc, A, name="A", index=0)
    _block(db, calc, B, name="B", index=1)
    db.expire_all()

    same = {
        "type": "Polygon",
        "coordinates": [[[83.0, 27.0], [83.5, 27.0], [83.5, 28.0], [83.0, 28.0], [83.0, 27.0]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        json={"layer_type": "blocks", "feature_id": str(a.id), "geometry": same},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Rule A — the forest boundary
# ---------------------------------------------------------------------------

def test_boundary_edit_is_refused_while_blocks_exist(client, db):
    headers = _register(client)
    calc = _calc(db, _user(client, headers))
    _block(db, calc, A, name="A", index=0)
    db.expire_all()

    reshaped = {
        "type": "Polygon",
        "coordinates": [[[83.0, 27.0], [84.1, 27.0], [84.0, 28.0], [83.0, 28.0], [83.0, 27.0]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        json={"layer_type": "boundary", "feature_id": "boundary", "geometry": reshaped},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "BOUNDARY_LOCKED_BY_STRUCTURE"


def test_boundary_edit_is_accepted_with_no_structure(client, db):
    """Rule A's other half — and it must write the FULL boundary, not just the geom."""
    headers = _register(client)
    calc = _calc(db, _user(client, headers))
    db.expire_all()

    reshaped = {
        "type": "Polygon",
        "coordinates": [[[83.0, 27.0], [84.0, 27.0], [84.0, 28.1], [83.0, 28.0], [83.0, 27.0]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        json={"layer_type": "boundary", "feature_id": "boundary", "geometry": reshaped},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    db.expire_all()
    row = db.query(Calculation).filter(Calculation.id == calc.id).first()
    rd = row.result_data or {}
    assert rd.get("geometry"), "result_data.geometry must follow boundary_geom"
    assert rd.get("area_hectares"), "area must be recomputed, not left stale"
    # Geodesic, not the caller's number: ~1 deg x ~1 deg near the equator.
    assert rd["area_hectares"] > 0


def test_put_boundary_is_gated_too(client, db):
    """A rule enforced on one route only is not enforced at all."""
    headers = _register(client)
    calc = _calc(db, _user(client, headers))
    _block(db, calc, A, name="A", index=0)
    db.expire_all()

    reshaped = {
        "type": "Polygon",
        "coordinates": [[[83.0, 27.0], [84.2, 27.0], [84.0, 28.0], [83.0, 28.0], [83.0, 27.0]]],
    }
    resp = client.put(
        f"/api/forests/calculations/{calc.id}/boundary",
        json={"geometry": reshaped, "area_hectares": 123.0},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


def test_put_boundary_still_allows_an_unchanged_save(client, db):
    """Idempotent saves and area-only updates must keep working."""
    # A realistic forest (~440 ha): the boundary rules cap one at 1000 ha, and the
    # 1-degree BOUNDARY the rest of this file uses (~1.09 M ha) is refused with a 422.
    forest = box(83.0, 27.0, 83.02, 27.02)
    headers = _register(client)
    calc = _calc(db, _user(client, headers), boundary=forest)
    _block(db, calc, box(83.0, 27.0, 83.01, 27.02), name="A", index=0)
    db.expire_all()

    same = {
        "type": "Polygon",
        "coordinates": [[[83.0, 27.0], [83.02, 27.0], [83.02, 27.02], [83.0, 27.02], [83.0, 27.0]]],
    }
    resp = client.put(
        f"/api/forests/calculations/{calc.id}/boundary",
        json={"geometry": same, "area_hectares": 123.0},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# VR-6 — coverage invariant on the vertex path, sub-area re-clip on boundary
# ---------------------------------------------------------------------------

def test_a_vertex_edit_runs_the_coverage_invariant(client, db):
    """D5: the coverage invariant fired only after cut and merge.

    A vertex edit could pull a block's edge inward and leave the forest
    boundary untiled — no warning, no auto-heal, no rejection.  With one block
    covering only half the boundary, the invariant must notice the uncovered
    remainder and fill it.
    """
    from app.models.forest_block import ForestBlock

    headers = _register(client)
    calc = _calc(db, _user(client, headers))
    a = _block(db, calc, A, name="A", index=0)
    db.expire_all()
    before = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()
    assert before == 1

    # Re-save A unchanged: legal, and enough to run the invariant, which should
    # observe that the right half of the boundary is covered by nothing.
    same = {
        "type": "Polygon",
        "coordinates": [[[83.0, 27.0], [83.5, 27.0], [83.5, 28.0], [83.0, 28.0], [83.0, 27.0]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        json={"layer_type": "blocks", "feature_id": str(a.id), "geometry": same},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    db.expire_all()
    after = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()
    assert after > before, "uncovered boundary area must be filled by the invariant"


def test_boundary_edit_reclips_a_protruding_sub_area(client, db):
    """D6: a sub-area past the new edge kept subtracting land the forest lost."""
    import uuid as _uuid
    from sqlalchemy.orm import attributes as _attrs
    from shapely.geometry import shape as _shape2
    from app.utils.geometry_utils import calculate_area_geodesic_from_shapely

    headers = _register(client)
    calc = _calc(db, _user(client, headers))
    river = {
        "type": "Polygon",
        "coordinates": [[[83.4, 27.4], [83.8, 27.4], [83.8, 27.5], [83.4, 27.5], [83.4, 27.4]]],
    }
    # Record the REAL geodesic area.  Inventing one makes "the area shrank"
    # unassertable — a declared 100 ha on a genuinely ~21 900 ha polygon made
    # the correctly-halved result look like growth.
    _sqm, _ha = calculate_area_geodesic_from_shapely(_shape2(river))
    original_ha = round(_ha, 4)
    calc.result_data = {
        "sub_areas": [{
            "id": str(_uuid.uuid4()),
            "name": "river",
            "category": "water_body",
            "geometry": river,
            "area_hectares": original_ha,
        }],
    }
    _attrs.flag_modified(calc, "result_data")
    db.commit()
    db.expire_all()

    shrunk = {
        "type": "Polygon",
        "coordinates": [[[83.0, 27.0], [83.5, 27.0], [83.5, 28.0], [83.0, 28.0], [83.0, 27.0]]],
    }
    resp = client.post(
        f"{_url(calc.id)}/edit-geometry",
        json={"layer_type": "boundary", "feature_id": "boundary", "geometry": shrunk},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sub_areas_clipped"] == ["river"], body
    assert "SUB_AREAS_CLIPPED" in body["warnings"]

    db.expire_all()
    row = db.query(Calculation).filter(Calculation.id == calc.id).first()
    sa = (row.result_data or {}).get("sub_areas", [])[0]
    from shapely.geometry import shape as _shape
    assert _shape(sa["geometry"]).bounds[2] <= 83.5 + 1e-9, "remnant must stop at the new edge"
    assert sa["area_hectares"] < original_ha, "the recorded area must follow the clip"
    # Boundary stops at x=83.5, halving a river that ran 83.4→83.8.
    assert sa["area_hectares"] == pytest.approx(original_ha / 4, rel=0.05)
