"""NTFP inventory API, phase 2: species catalogue and sample-plot design (``app/api/ntfp.py``)."""
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.ntfp_method import NtfpMethodProfile, NtfpSamplePlot, NtfpSamplingDesign

BOUNDARY = box(83.40, 27.40, 83.41, 27.41)  # about 100 ha


def _register(client):
    email = f"ntfp-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Ntfp Tester"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    return headers, client.get("/api/auth/me", headers=headers).json()["id"]


def _calc(db, user_id, boundary=True):
    calc = Calculation(id=uuid.uuid4(), user_id=user_id, forest_name="NTFP Forest", is_draft=True, result_data={},
                       boundary_geom=shp_wkt.dumps(BOUNDARY) if boundary else None)
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _seed_profiles(db):
    """The migration seeds these; a test database built from the models alone does not."""
    if db.query(NtfpMethodProfile).count():
        return
    from app.core.ntfp_methods import profiles

    cols = {c.name for c in NtfpMethodProfile.__table__.columns}
    for row in profiles():
        db.add(NtfpMethodProfile(**{k: v for k, v in row.items() if k in cols}))
    db.commit()


BODY = {"species": [{"species_key": "zanthoxylum armatum", "intensity_pct": 0.5}, {"species_key": "bombax ceiba", "intensity_pct": 0.5}], "seed": 4}


def test_catalogue_lists_profiles_with_defaults_for_the_forests_size(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    r = client.get(f"/api/calculations/{calc.id}/ntfp/species", headers=headers, params={"with_card": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert 50 < body["forest_area_ha"] < 150
    timur = next(s for s in body["species"] if s["species_key"] == "zanthoxylum armatum")
    assert timur["default_plot_sqm"] == 25 and timur["default_intensity_pct"] == 0.5  # a forest of about 108 ha: Table 4's 100-500 ha row
    assert timur["regulation"] and timur["growth_class"] == "shrub"


def test_preview_stores_nothing_and_create_replaces(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    url = f"/api/calculations/{calc.id}/ntfp/design"
    pre = client.post(url + "/preview", json=BODY, headers=headers)
    assert pre.status_code == 200, pre.text
    assert db.query(NtfpSamplingDesign).filter_by(calculation_id=calc.id).count() == 0
    assert client.get(url, headers=headers).json() == {"design": None}

    made = client.post(url, json=BODY, headers=headers)
    assert made.status_code == 200, made.text
    design = made.json()
    assert design["seed"] == 4 and len(design["plots"]) == len(pre.json()["plots"])
    assert [(p["longitude"], p["latitude"]) for p in design["plots"]] == [(p["longitude"], p["latitude"]) for p in pre.json()["plots"]]  # the preview is the design

    again = client.post(url, json={**BODY, "seed": 9}, headers=headers)
    assert again.status_code == 200
    assert db.query(NtfpSamplingDesign).filter_by(calculation_id=calc.id).count() == 1
    assert client.get(url, headers=headers).json()["design"]["seed"] == 9

    assert client.delete(url, headers=headers).json() == {"deleted": True}
    assert client.get(url, headers=headers).json() == {"design": None}


def test_deleting_the_forest_deletes_its_design(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    assert client.post(f"/api/calculations/{calc.id}/ntfp/design", json=BODY, headers=headers).status_code == 200
    design_id = db.query(NtfpSamplingDesign).filter_by(calculation_id=calc.id).one().id
    db.expire_all()
    db.delete(db.get(Calculation, calc.id))
    db.commit()
    assert db.query(NtfpSamplingDesign).filter_by(id=design_id).count() == 0
    assert db.query(NtfpSamplePlot).filter_by(design_id=design_id).count() == 0


def test_refusals(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    url = f"/api/calculations/{calc.id}/ntfp/design/preview"
    r = client.post(url, json={"species": [{"species_key": "no such species"}]}, headers=headers)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_species"
    r = client.post(url, json={"species": [{"species_key": "amomum subulatum"}]}, headers=headers)  # known only from a season table: no card, no growth class
    assert r.status_code == 422 and r.json()["detail"]["code"] == "growth_class_needed"
    assert client.post(url, json={"species": []}, headers=headers).status_code == 422
    nobound = _calc(db, uid, boundary=False)
    r = client.post(f"/api/calculations/{nobound.id}/ntfp/design/preview", json=BODY, headers=headers)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "no_geometry"


def test_another_users_forest_is_refused_and_a_stranger_gets_nothing(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    other_headers, _ = _register(client)
    calc = _calc(db, uid)
    base = f"/api/calculations/{calc.id}/ntfp"
    assert client.get(base + "/design", headers=other_headers).status_code == 403
    assert client.post(base + "/design", json=BODY, headers=other_headers).status_code == 403
    assert client.get(base + "/design").status_code in (401, 403)
