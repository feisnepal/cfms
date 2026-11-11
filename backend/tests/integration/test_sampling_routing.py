"""Sampling create-endpoint routing tests (SAMPLING_PAGE_REWORK, Phase C.2/C.3).

Proves the mode-driven routing contract at the API boundary (the heavy point
generation is monkeypatched because raster data is unavailable in the test DB):
  - Compartment forest + (manual/systematic) → intensity engine with 2.0%.
  - Block forest + guideline → Guideline-2061 engine.
  - Block forest + (manual/random) → intensity engine random fallback 0.5%.
Only the create endpoint's routing decision is exercised; unit extraction and
per-compartment grids are covered by test_sampling_extract_blocks.py.
"""
import uuid
from decimal import Decimal

from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.schemas.sampling import SamplingGenerateResponse

BOUNDARY = box(83.4, 27.4, 83.6, 27.6)


def _register(client):
    email = f"sampling-route-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Sampling Route",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {resp.json()['access_token']}"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, me.json()["id"]


def _calc(db, user_id, forest_name="Routing Forest"):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name=forest_name,
        boundary_geom=shp_wkt.dumps(BOUNDARY),
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _unit(db, calc, geom, name, is_compartment=False, index=0):
    block = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        block_name=name,
        compartment_code=name if is_compartment else None,
        geometry=shp_wkt.dumps(geom),
        area_hectares=5.0,
        index=index,
        is_compartment=is_compartment,
        division_level=1,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def _response(calculation_id, sampling_type="systematic", intensity="2.0"):
    return SamplingGenerateResponse(
        sampling_design_id=uuid.uuid4(),
        calculation_id=calculation_id,
        sampling_type=sampling_type,
        total_points=4,
        total_blocks=2,
        forest_area_hectares=Decimal("10"),
        requested_intensity_percent=Decimal(intensity),
        actual_intensity_per_hectare=Decimal("0.4"),
    )


def test_compartment_routes_to_intensity_engine(monkeypatch, client, db):
    """Compartment forest → manual+systematic+2.0% hits create_sampling_design."""
    headers, uid = _register(client)
    calc = _calc(db, uid, "Compartment Forest")
    _unit(db, calc, BOUNDARY.buffer(-0.01), "C1", is_compartment=True, index=1)
    _unit(db, calc, BOUNDARY.buffer(-0.02), "C2", is_compartment=True, index=2)

    captured = {}
    def fake_intensity(db, calculation_id, **kwargs):
        captured["kwargs"] = kwargs
        return _response(calculation_id)
    fake_guideline = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("guideline must NOT be called"))

    monkeypatch.setattr("app.api.sampling.create_sampling_design", fake_intensity)
    monkeypatch.setattr("app.api.sampling.create_sampling_design_guideline_2061", fake_guideline)

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/create",
        json={"sampling_method": "manual", "sampling_type": "systematic", "sampling_intensity_percent": 2.0},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["kwargs"]["sampling_type"] == "systematic"
    assert float(captured["kwargs"]["sampling_intensity_percent"]) == 2.0


def test_block_systematic_routes_to_guideline(monkeypatch, client, db):
    """Block forest + default/systematic → Guideline-2061 engine."""
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _unit(db, calc, BOUNDARY.buffer(-0.01), "Block-1", index=1)
    _unit(db, calc, BOUNDARY.buffer(-0.02), "Block-2", index=2)

    captured = {}
    def fake_guideline(db, calculation_id, **kwargs):
        captured["kwargs"] = kwargs
        return _response(calculation_id, intensity="0.5")
    fake_intensity = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("intensity must NOT be called"))

    monkeypatch.setattr("app.api.sampling.create_sampling_design_guideline_2061", fake_guideline)
    monkeypatch.setattr("app.api.sampling.create_sampling_design", fake_intensity)

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/create",
        json={"sampling_method": "guideline_2061", "productive_intensity": "0.5"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["kwargs"]["productive_intensity"] == 0.5
    assert "sampling_intensity_percent" not in captured["kwargs"]


def test_block_random_routes_to_intensity_fallback(monkeypatch, client, db):
    """Block forest + random → intensity engine random fallback 0.5%."""
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _unit(db, calc, BOUNDARY.buffer(-0.01), "Block-1", index=1)

    captured = {}
    def fake_intensity(db, calculation_id, **kwargs):
        captured["kwargs"] = kwargs
        return _response(calculation_id, sampling_type="random", intensity="0.5")
    fake_guideline = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("guideline must NOT be called"))

    monkeypatch.setattr("app.api.sampling.create_sampling_design", fake_intensity)
    monkeypatch.setattr("app.api.sampling.create_sampling_design_guideline_2061", fake_guideline)

    resp = client.post(
        f"/api/calculations/{calc.id}/sampling/create",
        json={"sampling_method": "manual", "sampling_type": "random", "sampling_intensity_percent": 0.5, "min_distance_meters": 30},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["kwargs"]["sampling_type"] == "random"
    assert float(captured["kwargs"]["sampling_intensity_percent"]) == 0.5
    assert captured["kwargs"]["min_distance_meters"] == 30