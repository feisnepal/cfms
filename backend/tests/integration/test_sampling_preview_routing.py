"""Sampling preview endpoint + deterministic create-from-preview tests
(SAMPLING_PAGE_REWORK, Phase F).

Proves at the API boundary:
  - POST /sampling/preview routes to the same engine as create (per mode) with
    preview=True, returns the preview response shape, and writes no design.
  - Guards mirror create (404 / 400 no boundary / 423 structure lock / 400
    existing design).
  - POST /sampling/create with a captured `preview` payload replays the EXACT
    previewed plot locations (deterministic — F.3).
"""
import uuid
from decimal import Decimal

from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.sampling import SamplingDesign
from app.schemas.sampling import SamplingGenerateResponse
from app.services.sampling import SamplingPreviewResult
from sqlalchemy import text

BOUNDARY = box(83.4, 27.4, 83.6, 27.6)


def _register(client):
    email = f"preview-route-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Preview Route",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _register_and_uid(client):
    headers = _register(client)
    me = client.get("/api/auth/me", headers=headers)
    return headers, me.json()["id"]


def _calc(db, user_id, forest_name="Preview Forest", boundary=True):
    calc = Calculation(
        id=uuid.uuid4(), user_id=user_id, forest_name=forest_name,
        boundary_geom=shp_wkt.dumps(BOUNDARY) if boundary else None,
        is_draft=True,
        result_data={},
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _unit(db, calc, name, index=0, is_compartment=False):
    block = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name=name,
        block_name=name,
        compartment_code=name if is_compartment else None,
        geometry=shp_wkt.dumps(BOUNDARY.buffer(-0.01 - 0.005 * index)),
        area_hectares=5.0, index=index,
        is_compartment=is_compartment,
        division_level=1,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def _preview_result(calculation_id, sampling_type="systematic", intensity="2.0"):
    resp = SamplingGenerateResponse(
        sampling_design_id=uuid.uuid4(),
        calculation_id=calculation_id,
        sampling_type=sampling_type,
        total_points=4, total_blocks=2,
        forest_area_hectares=Decimal("10"),
        requested_intensity_percent=Decimal(intensity),
        actual_intensity_per_hectare=Decimal("0.4"),
    )
    return SamplingPreviewResult(
        response=resp,
        points_geojson={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [83.5, 27.5]},
                "properties": {"plot_number": 1, "block_name": "Block-1", "zone_type": "productive"},
            }],
        },
        area_basis="full_area",
    )


def test_preview_guideline_engine_called_with_preview(monkeypatch, client, db):
    headers, uid = _register_and_uid(client)
    calc = _calc(db, uid)
    _unit(db, calc, "Block-1", index=0)
    _unit(db, calc, "Block-2", index=1)

    captured = {}
    def fake_guideline(db, calculation_id, **kwargs):
        captured["kwargs"] = kwargs
        return _preview_result(calculation_id, intensity="0.5")
    fake_intensity = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("intensity must NOT be called"))

    monkeypatch.setattr("app.api.sampling.create_sampling_design_guideline_2061", fake_guideline)
    monkeypatch.setattr("app.api.sampling.create_sampling_design", fake_intensity)

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/preview",
        json={"sampling_method": "guideline_2061", "productive_intensity": "0.5"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["kwargs"]["preview"] is True
    data = resp.json()
    assert data["preview_token"]
    assert data["total_points"] == 4
    assert data["total_units"] == 2
    assert data["area_basis"] == "full_area"
    assert data["sampling_points_geojson"]["type"] == "FeatureCollection"
    assert len(data["sampling_points_geojson"]["features"]) == 1
    assert data["boundary_layer"]["geometry"] is not None
    assert data["forest_blocks_layer"]["features"][0]["properties"]["name"] == "Block-1"
    assert data["filter_settings"]["filter_tree_cover"] is True  # default


def test_preview_block_random_routes_to_intensity(monkeypatch, client, db):
    """Block forest + random → preview uses the intensity engine (manual)."""
    headers, uid = _register_and_uid(client)
    calc = _calc(db, uid)
    _unit(db, calc, "Block-1", index=0)

    captured = {}
    def fake_intensity(db, calculation_id, **kwargs):
        captured["kwargs"] = kwargs
        return _preview_result(calculation_id, sampling_type="random", intensity="0.5")
    fake_guideline = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("guideline must NOT be called"))

    monkeypatch.setattr("app.api.sampling.create_sampling_design", fake_intensity)
    monkeypatch.setattr("app.api.sampling.create_sampling_design_guideline_2061", fake_guideline)

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/preview",
        json={"sampling_method": "manual", "sampling_type": "random", "sampling_intensity_percent": 0.5, "min_distance_meters": 30},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["kwargs"]["preview"] is True
    assert captured["kwargs"]["sampling_type"] == "random"
    data = resp.json()
    assert data["sampling_type"] == "random"


def test_preview_unknown_calc_404(client, db):
    headers = _register(client)
    resp = client.post(
        f"/api/calculations/{uuid.uuid4()}/sampling/preview",
        json={"sampling_method": "guideline_2061"},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text


def test_preview_no_boundary_400(client, db):
    headers, uid = _register_and_uid(client)
    calc = _calc(db, uid, boundary=False)
    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/preview",
        json={"sampling_method": "guideline_2061"},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text


def test_preview_existing_design_400(client, db):
    headers, uid = _register_and_uid(client)
    calc = _calc(db, uid)
    db.add(SamplingDesign(
        calculation_id=calc.id, sampling_type="systematic",
        total_points=1, intensity_per_hectare=Decimal("0.4"),
    ))
    db.commit()

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/preview",
        json={"sampling_method": "guideline_2061"},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "sampling.design_already_exists"
    assert "already exists" in detail["message"]
    assert detail["message_np"]


def test_preview_structure_locked_423(client, db):
    headers, uid = _register_and_uid(client)
    calc = _calc(db, uid)
    calc.structure_locked = True
    db.commit()

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/preview",
        json={"sampling_method": "guideline_2061"},
        headers=headers,
    )
    assert resp.status_code == 423, resp.text


def test_preview_writes_no_design_row(monkeypatch, client, db):
    """Real preview (intensity engine, full-area) must not persist a design."""
    headers, uid = _register_and_uid(client)
    calc = _calc(db, uid)
    _unit(db, calc, "Block-1", index=0)

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/preview",
        json={"sampling_method": "manual", "sampling_type": "systematic", "sampling_intensity_percent": 2.0, "filter_tree_cover": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calc.id).count() == 0


def test_preview_then_create_replays_exact_points(client, db):
    """Deterministic F.3: create from the captured preview persists the EXACT
    previewed plot locations (no re-generation)."""
    headers, uid = _register_and_uid(client)
    calc = _calc(db, uid)
    _unit(db, calc, "Block-1", index=0)
    _unit(db, calc, "Block-2", index=1)

    # 1) Preview (real intensity engine, full-area systematic)
    body = {"sampling_method": "manual", "sampling_type": "systematic", "sampling_intensity_percent": 2.0, "filter_tree_cover": False}
    p = client.post(f"/api/calculations/{calc.id}/sampling/preview", json=body, headers=headers)
    assert p.status_code == 200, p.text
    prev = p.json()
    preview_coords = [
        tuple(f["geometry"]["coordinates"]) for f in prev["sampling_points_geojson"]["features"]
    ]
    assert preview_coords

    # 2) Create with the captured preview payload
    create_body = dict(body)
    create_body["preview"] = {
        "preview_token": prev["preview_token"],
        "total_points": prev["total_points"],
        "total_blocks": prev["total_blocks"],
        "forest_area_hectares": prev["forest_area_hectares"],
        "requested_intensity_percent": prev["requested_intensity_percent"],
        "actual_intensity_per_hectare": prev["actual_intensity_per_hectare"],
        "plot_area_sqm": prev["plot_area_sqm"],
        "total_sampled_area_hectares": prev["total_sampled_area_hectares"],
        "sampling_percentage": prev["sampling_percentage"],
        "blocks_info": prev["blocks_info"],
        "sampling_points_geojson": prev["sampling_points_geojson"],
        "area_basis": prev["area_basis"],
    }
    c = client.post(f"/api/calculations/{calc.id}/sampling/create", json=create_body, headers=headers)
    assert c.status_code == 200, c.text
    design_id = c.json()["sampling_design_id"]

    # 3) The persisted geometry must equal the previewed coordinates (plus the
    #    geojson features rebuilt with block/zone properties, in order).
    row = db.execute(
        text("SELECT ST_AsText(points_geometry) as wkt, points_block_assignment FROM public.sampling_designs WHERE id = :id"),
        {"id": str(design_id)},
    ).first()
    assert row and row.wkt.startswith("MULTIPOINT")
    inner = row.wkt[len("MULTIPOINT"):].strip()
    if inner.startswith("(("):
        tokens = [t.strip("()") for t in inner[1:-1].split("),(")]
    else:
        tokens = inner.strip("()").split(",")
    created_coords = [
        tuple(map(float, pair.strip().split()))
        for pair in tokens
    ]
    assert len(created_coords) == len(preview_coords)
    for a, b in zip(created_coords, preview_coords):
        assert abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9, f"{a} != {b}"

    assignments = row.points_block_assignment or []
    assert len(assignments) == len(created_coords)
    assert all("block_name" in a for a in assignments)
    assert all("zone_type" in a for a in assignments)