"""User Group Boundary — P0 backend readiness.

USER_GROUP_BOUNDARY_PLAN.md P0:
  - GET .../user-group/extent (thin Feature, all-null when none)
  - POST .../user-group/import on the Forest-Boundary engine (point/line/polygon,
    CSV point sheet), replaces the current extent
  - single-extent invariant on redraw
  - calc-ownership check on every /user-group/* route
"""

import io
import json
import uuid

import pytest
from shapely.geometry import box
from shapely import wkt as shp_wkt

from app.models.calculation import Calculation, CalculationStatus
from app.models.user_group import UserGroupExtent

import pytest as _pytest_for_limit

pytestmark = _pytest_for_limit.mark.usefixtures("relax_user_group_limit")

NEPAL = box(83.0, 27.0, 84.0, 28.0)


def _register(client):
    email = f"ug-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "TestPass123!",
            "full_name": "UG Repro",
        },
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    return headers, me.json()["id"]


def _calc(db, user_id, boundary=NEPAL):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="UG Repro Forest",
        boundary_geom=shp_wkt.dumps(boundary),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _poly_geojson():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [83.20, 27.20],
                            [83.60, 27.20],
                            [83.60, 27.60],
                            [83.20, 27.60],
                            [83.20, 27.20],
                        ]
                    ],
                },
            }
        ],
    }


def _point_csv():
    return (
        "name,lat,lon\n"
        "a,27.20,83.20\n"
        "b,27.20,83.60\n"
        "c,27.60,83.60\n"
        "d,27.60,83.20\n"
    )


def _upload(client, url, headers, *, filename, content, field="file"):
    if isinstance(content, str):
        content = content.encode()
    return client.post(
        url,
        headers=headers,
        files={field: (filename, io.BytesIO(content), "application/octet-stream")},
    )


# ---------------------------------------------------------------------------


def test_get_extent_returns_all_null_when_none(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    r = client.get(f"/api/calculations/{calc.id}/user-group/extent", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "extent_id": None,
        "source_type": None,
        "buffer_distance_m": None,
        "area_hectares": None,
        "geometry": None,
    }


    def test_manual_draw_twice_adds_a_second_row(self, client, db):
        """P7a, inverting the P0 single-row invariant: each polygon is its own row.

        This test used to read `assert len(rows) == 1, "redraw must replace, not
        stack"`. That invariant is what made it impossible to draw a second
        user-group boundary - and because `user_group_buildings.extent_id` is
        `ondelete="CASCADE"`, replacing the row also destroyed the first
        boundary's ANALYSIS, silently. The owner's model (2026-09-28) is one polygon
        per row with its own attribute row, so a second draw now appends.
        """
        calc = _calc(db, uid)
        g1 = {
            "type": "Polygon",
            "coordinates": [
                [[83.1, 27.1], [83.3, 27.1], [83.3, 27.3], [83.1, 27.3], [83.1, 27.1]]
            ],
        }
        g2 = {
            "type": "Polygon",
            "coordinates": [
                [[83.5, 27.5], [83.8, 27.5], [83.8, 27.8], [83.5, 27.8], [83.5, 27.5]]
            ],
        }

        r1 = client.post(
            f"/api/calculations/{calc.id}/user-group/manual",
            headers=headers,
            json={"geometry": g1},
        )
        assert r1.status_code == 200, r1.text
        r2 = client.post(
            f"/api/calculations/{calc.id}/user-group/manual",
            headers=headers,
            json={"geometry": g2},
        )
        assert r2.status_code == 200, r2.text

        rows = (
            db.query(UserGroupExtent)
            .filter(UserGroupExtent.calculation_id == calc.id)
            .order_by(UserGroupExtent.created_at.asc())
            .all()
        )
        assert len(rows) == 2, (
            f"each polygon is its own row, so a second draw must add one "
            f"(got {len(rows)} rows)"
        )
        # They are DISTINCT rows, not one row rewritten - which is what the old
        # replace-on-draw did, destroying the first row's analysis via CASCADE.
        assert str(rows[0].id) != str(rows[1].id)

        # The union is the whole group, so the layer read reports both polygons.
        ext = client.get(
            f"/api/calculations/{calc.id}/user-group/extent", headers=headers
        ).json()
        assert ext["polygon_count"] == 2
        assert set(ext["extent_ids"]) == {str(r1.json()["extent_id"]),
                                          str(r2.json()["extent_id"])}
        # Contract preserved: the union is still returned as a MultiPolygon.
        assert ext["geometry"]["type"] == "MultiPolygon"


def test_import_geojson_polygon_sets_extent(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    r = _upload(
        client,
        f"/api/calculations/{calc.id}/user-group/import",
        headers,
        filename="extent.geojson",
        content=json.dumps(_poly_geojson()),
    )
    assert r.status_code == 200, r.text
    ext = client.get(
        f"/api/calculations/{calc.id}/user-group/extent", headers=headers
    ).json()
    assert ext["geometry"]["type"] == "MultiPolygon"
    assert ext["source_type"] == "uploaded"


def test_import_csv_point_sheet_is_polygonised(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    r = _upload(
        client,
        f"/api/calculations/{calc.id}/user-group/import",
        headers,
        filename="points.csv",
        content=_point_csv(),
    )
    assert r.status_code == 200, r.text
    ext = client.get(
        f"/api/calculations/{calc.id}/user-group/extent", headers=headers
    ).json()
    assert ext["geometry"]["type"] == "MultiPolygon"
    assert ext["area_hectares"] and ext["area_hectares"] > 0


def test_import_replaces_a_prior_manual_extent(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    client.post(
        f"/api/calculations/{calc.id}/user-group/manual",
        headers=headers,
        json={
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [83.1, 27.1],
                        [83.3, 27.1],
                        [83.3, 27.3],
                        [83.1, 27.3],
                        [83.1, 27.1],
                    ]
                ],
            }
        },
    )
    _upload(
        client,
        f"/api/calculations/{calc.id}/user-group/import",
        headers,
        filename="extent.geojson",
        content=json.dumps(_poly_geojson()),
    )
    rows = (
        db.query(UserGroupExtent)
        .filter(UserGroupExtent.calculation_id == calc.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].source_type == "uploaded"


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("get", {}),
        (
            "post_json",
            {
                "json": {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[83.1, 27.1], [83.3, 27.1], [83.3, 27.3], [83.1, 27.1]]
                        ],
                    }
                }
            },
        ),
    ],
)
def test_non_owner_is_forbidden(client, db, method, kwargs):
    owner_headers, owner_id = _register(client)
    calc = _calc(db, owner_id)
    other_headers, _ = _register(client)

    if method == "get":
        r = client.get(
            f"/api/calculations/{calc.id}/user-group/extent", headers=other_headers
        )
    else:
        r = client.post(
            f"/api/calculations/{calc.id}/user-group/manual",
            headers=other_headers,
            **kwargs,
        )
    assert r.status_code == 403, r.text


def test_import_by_non_owner_is_forbidden(client, db):
    _, owner_id = _register(client)
    calc = _calc(db, owner_id)
    other_headers, _ = _register(client)
    r = _upload(
        client,
        f"/api/calculations/{calc.id}/user-group/import",
        other_headers,
        filename="extent.geojson",
        content=json.dumps(_poly_geojson()),
    )
    assert r.status_code == 403, r.text
