"""POST /api/v1/workspace/{id}/export-geopackage: a layer's features, as a downloadable .gpkg named by the project's convention."""

from __future__ import annotations

import os
import re
import tempfile
import uuid
from urllib.parse import unquote

from app.models.calculation import Calculation
from app.models.user import User

BASE = "/api/v1/workspace"


def _login(client, db):
    email = f"gp-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Gpkg Tester"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, db.query(User).filter(User.email == email).first()


def _calc(db, user, name="बनस्खन्डी"):
    calc = Calculation(user_id=user.id, uploaded_filename="x.csv", forest_name=name)
    db.add(calc)
    db.commit()
    return calc


def _feature(name):
    ring = [[85.0, 27.0], [85.01, 27.0], [85.01, 27.01], [85.0, 27.01], [85.0, 27.0]]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {"name": name, "area_hectares": 4.5}}


def _read(content: bytes):
    import geopandas as gpd

    handle, path = tempfile.mkstemp(suffix=".gpkg")
    os.close(handle)
    with open(path, "wb") as fh:
        fh.write(content)
    try:
        return gpd.read_file(path)
    finally:
        os.remove(path)


def test_the_owner_gets_a_geopackage_named_by_the_convention(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    res = client.post(f"{BASE}/{calc.id}/export-geopackage", headers=headers, json={"layer_name": "Sub-Compartments", "features": [_feature("a"), _feature("b")]})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/geopackage+sqlite3")
    disposition = res.headers["content-disposition"]
    name = unquote(re.search(r"filename\*=UTF-8''([^;]+)", disposition).group(1))
    assert re.fullmatch(r"बनस्खन्डी_Sub_Compartments_Spatial_\d{8}\.gpkg", name), name
    gdf = _read(res.content)
    assert list(gdf["name"]) == ["a", "b"] and gdf["area_hectares"].tolist() == [4.5, 4.5]


def test_a_layer_with_nothing_to_draw_is_refused_in_plain_words(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    res = client.post(f"{BASE}/{calc.id}/export-geopackage", headers=headers, json={"layer_name": "L", "features": [{"type": "Feature", "geometry": None, "properties": {}}]})
    assert res.status_code == 400
    assert "no features with a geometry" in res.json()["detail"]


def test_another_users_forest_is_not_exported(client, db):
    owner_headers, owner = _login(client, db)
    calc = _calc(db, owner)
    other_headers, _ = _login(client, db)
    res = client.post(f"{BASE}/{calc.id}/export-geopackage", headers=other_headers, json={"layer_name": "L", "features": [_feature("a")]})
    assert res.status_code == 403


def test_it_needs_a_login_and_a_forest_that_exists(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    assert client.post(f"{BASE}/{calc.id}/export-geopackage", json={"layer_name": "L", "features": [_feature("a")]}).status_code in (401, 403)
    missing = uuid.uuid4()
    assert client.post(f"{BASE}/{missing}/export-geopackage", headers=headers, json={"layer_name": "L", "features": [_feature("a")]}).status_code == 404


def test_a_malformed_request_is_a_422_not_a_crash(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    assert client.post(f"{BASE}/{calc.id}/export-geopackage", headers=headers, json={"layer_name": "L"}).status_code == 422
