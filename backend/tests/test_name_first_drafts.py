"""
Name-first draft creation tests (NAME_FIRST_CREATION_PLAN.md, Phase 1).

Covers the name-only draft endpoint:
- POST /api/v1/forests/drafts/create-name-only   — create a draft by name only
- Backward compatibility: the generic save-draft endpoint still works unchanged

Key assertions:
- A name-only draft is created with islands_count=0, total_area=0.0, is_draft=True
- Same-name create updates the existing draft (dedupe), never creates a second one
- Validation: empty / over-long names are rejected by the schema
- Generic save-draft still accepts the prior shape (islands required as default [])
"""
import sys
import os
import json
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.calculation import Calculation

FS = "/api/v1/forests"
LEGACY = "/api/forests"

import pytest

pytestmark = pytest.mark.usefixtures("forget_forests")  # fixed coordinates + committed rows: see conftest



def _user(client, tag):
    """Register + login a fresh user; return (auth_headers, user_id)."""
    email = f"{tag}_{uuid4().hex}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "Passw0rd!x", "full_name": "Test"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "Passw0rd!x"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


class TestCreateNameOnly:
    def test_creates_draft_by_name_only(self, client, db):
        headers, uid = _user(client, "nameonly")
        resp = client.post(
            f"{FS}/drafts/create-name-only",
            json={"forest_name": "Sundari Community Forest"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["forest_name"] == "Sundari Community Forest"
        assert body["islands_count"] == 0
        assert body["total_area"] == 0.0
        assert body["mode"] == "manual"

        calc = db.query(Calculation).filter(Calculation.id == body["id"]).first()
        assert calc is not None
        assert calc.is_draft is True
        assert calc.boundary_geom is None
        assert calc.draft_data["islands"] == []
        assert calc.uploaded_filename == "draft"

    def test_duplicate_name_updates_existing_draft(self, client, db):
        headers, uid = _user(client, "dup")
        name = f"Unique Forest {uuid4().hex[:8]}"
        r1 = client.post(
            f"{FS}/drafts/create-name-only",
            json={"forest_name": name},
            headers=headers,
        )
        assert r1.status_code == 200, r1.text
        first_id = r1.json()["id"]

        r2 = client.post(
            f"{FS}/drafts/create-name-only",
            json={"forest_name": name},
            headers=headers,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["id"] == first_id

        # Only one draft row exists for that user+name
        count = db.query(Calculation).filter(
            Calculation.user_id == uid,
            Calculation.forest_name == name,
            Calculation.is_draft == True,
        ).count()
        assert count == 1

    def test_empty_name_rejected(self, client):
        headers, _ = _user(client, "empty")
        resp = client.post(
            f"{FS}/drafts/create-name-only",
            json={"forest_name": ""},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    def test_overlong_name_rejected(self, client):
        headers, _ = _user(client, "long")
        resp = client.post(
            f"{FS}/drafts/create-name-only",
            json={"forest_name": "x" * 256},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    def test_missing_name_rejected(self, client):
        headers, _ = _user(client, "missing")
        resp = client.post(
            f"{FS}/drafts/create-name-only",
            json={},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    def test_requires_auth(self, client):
        resp = client.post(
            f"{FS}/drafts/create-name-only",
            json={"forest_name": "No Auth Forest"},
        )
        assert resp.status_code in (401, 403), resp.text

    def test_legacy_prefix_alias(self, client):
        """The /api (non-v1) shim must also serve the endpoint."""
        headers, _ = _user(client, "legacy")
        resp = client.post(
            f"{LEGACY}/drafts/create-name-only",
            json={"forest_name": "Legacy Alias Forest"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["islands_count"] == 0


class TestSetForestBoundary:
    """Phase 2 — PUT /calculations/{id}/boundary works on a name-only draft."""

    def _draft(self, client, tag, name=None):
        headers, uid = _user(client, tag)
        r = client.post(
            f"{FS}/drafts/create-name-only",
            json={"forest_name": name or f"Boundary Forest {uuid4().hex[:8]}"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        return headers, uid, r.json()["id"]

    # ~0.02° ≈ 2 km square — a plausible community forest, under the 1000 ha cap.
    def _poly(self, lon=84.0, lat=28.0, d=0.02):
        return {
            "type": "Polygon",
            "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]],
        }

    def test_set_boundary_on_draft(self, client, db):
        headers, _, draft_id = self._draft(client, "setboundary")
        resp = client.put(
            f"{FS}/calculations/{draft_id}/boundary",
            json={"geometry": self._poly()},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["area_hectares"] > 0

        calc = db.query(Calculation).filter(Calculation.id == draft_id).first()
        assert calc is not None
        assert calc.boundary_geom is not None
        assert calc.result_data["geometry"]["type"] == "Polygon"
        assert calc.result_data["area_hectares"] == body["area_hectares"]
        # Keep-as-draft semantics (approved): still a draft after boundary set
        assert calc.is_draft is True
        assert calc.draft_data is not None

    def test_boundary_without_area_computed_server_side(self, client, db):
        """area_hectares is computed server-side when the client omits it (was 0)."""
        headers, _, draft_id = self._draft(client, "autoboundary")
        resp = client.put(
            f"{FS}/calculations/{draft_id}/boundary",
            json={"geometry": self._poly()},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        area = resp.json()["area_hectares"]
        assert area > 0, "server must compute geodesic area, not default to 0"

        calc = db.query(Calculation).filter(Calculation.id == draft_id).first()
        assert calc.result_data["area_hectares"] == area

    def test_explicit_area_is_honored(self, client, db):
        headers, _, draft_id = self._draft(client, "explicitarea")
        resp = client.put(
            f"{FS}/calculations/{draft_id}/boundary",
            json={"geometry": self._poly(), "area_hectares": 123.5},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["area_hectares"] == 123.5

        calc = db.query(Calculation).filter(Calculation.id == draft_id).first()
        assert calc.result_data["area_hectares"] == 123.5

    def test_missing_geometry_400(self, client, db):
        headers, _, draft_id = self._draft(client, "nogeom")
        resp = client.put(
            f"{FS}/calculations/{draft_id}/boundary",
            json={},
            headers=headers,
        )
        assert resp.status_code == 400, resp.text

    def test_other_user_cannot_set_boundary(self, client, db):
        headers, _, draft_id = self._draft(client, "boundaryowner")
        other_headers, _ = _user(client, "boundaryattacker")
        resp = client.put(
            f"{FS}/calculations/{draft_id}/boundary",
            json={"geometry": self._poly()},
            headers=other_headers,
        )
        assert resp.status_code == 404, resp.text


class TestMergeForestBoundary:
    """Phase 3 — POST /calculations/{id}/merge-forest-boundary unions pieces."""

    def _draft(self, client, tag, name=None):
        headers, uid = _user(client, tag)
        r = client.post(
            f"{FS}/drafts/create-name-only",
            json={"forest_name": name or f"Merge Forest {uuid4().hex[:8]}"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        return headers, uid, r.json()["id"]

    # ~0.02° ≈ 2 km squares: keeps each piece well under the 1000 ha
    # forest-boundary limit while still exercising the union / area maths.
    def _poly(self, lon=84.0, lat=28.0, w=0.02, h=0.02):
        return {
            "type": "Polygon",
            "coordinates": [[[lon, lat], [lon + w, lat], [lon + w, lat + h], [lon, lat + h], [lon, lat]]],
        }

    def test_merge_two_pieces_single_boundary(self, client, db):
        headers, _, draft_id = self._draft(client, "mergetwo")
        resp = client.post(
            f"{FS}/calculations/{draft_id}/merge-forest-boundary",
            json={"geometries": [self._poly(84.0, 28.0), self._poly(85.0, 28.0)]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["area_hectares"] > 0

        calc = db.query(Calculation).filter(Calculation.id == draft_id).first()
        assert calc.boundary_geom is not None
        assert calc.result_data["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert calc.result_data["area_hectares"] == body["area_hectares"]
        assert calc.is_draft is True  # keep-as-draft semantics

    def test_merge_single_piece(self, client, db):
        headers, _, draft_id = self._draft(client, "mergesingle")
        resp = client.post(
            f"{FS}/calculations/{draft_id}/merge-forest-boundary",
            json={"geometries": [self._poly(84.0, 28.0)]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["area_hectares"] > 0

    def test_merge_area_is_sum_of_pieces(self, client, db):
        """Two side-by-side unit-deg squares => combined geodesic area."""
        headers, _, draft_id = self._draft(client, "mergesum")
        single = client.post(
            f"{FS}/calculations/{draft_id}/merge-forest-boundary",
            json={"geometries": [self._poly(84.0, 28.0)]},
            headers=headers,
        ).json()["area_hectares"]

        two = client.post(
            f"{FS}/calculations/{draft_id}/merge-forest-boundary",
            json={"geometries": [self._poly(84.0, 28.0), self._poly(85.0, 28.0)]},
            headers=headers,
        ).json()["area_hectares"]
        # non-overlapping adjacent pieces => union ≈ sum (small tolerance)
        assert abs(two - 2 * single) / (2 * single) < 0.01

    def test_empty_geometries_422(self, client, db):
        headers, _, draft_id = self._draft(client, "mergeempty")
        resp = client.post(
            f"{FS}/calculations/{draft_id}/merge-forest-boundary",
            json={"geometries": []},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    def test_other_user_cannot_merge(self, client, db):
        headers, _, draft_id = self._draft(client, "mergeowner")
        other_headers, _ = _user(client, "mergeattacker")
        resp = client.post(
            f"{FS}/calculations/{draft_id}/merge-forest-boundary",
            json={"geometries": [self._poly()]},
            headers=other_headers,
        )
        assert resp.status_code == 404, resp.text


class TestSaveDraftUnchanged:
    def test_save_draft_with_islands_still_works(self, client, db):
        headers, _ = _user(client, "saveislands")
        resp = client.post(
            f"{FS}/save-draft",
            json={
                "forest_name": "Island Forest",
                "islands": [
                    {
                        "id": "island-1",
                        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                        "area": 5.5,
                    }
                ],
                "mode": "manual",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["islands_count"] == 1
        assert body["total_area"] == 5.5

    def test_save_draft_with_empty_islands(self, client):
        """islands is now optional (default []); name-only via save-draft also works."""
        headers, _ = _user(client, "saveempty")
        resp = client.post(
            f"{FS}/save-draft",
            json={
                "forest_name": "Empty Island Forest",
                "islands": [],
                "mode": "manual",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["islands_count"] == 0

    def test_save_draft_omitting_islands_defaults_empty(self, client):
        headers, _ = _user(client, "saveomit")
        resp = client.post(
            f"{FS}/save-draft",
            json={
                "forest_name": "Omitted Island Forest",
                "mode": "manual",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["islands_count"] == 0


class TestListExposesDraftData:
    """Phase 7 — the /calculations list must expose draft_data so the client can
    tell a boundary-less (name-only) draft from a legacy island-bearing one."""

    def test_list_returns_draft_data_for_name_only_draft(self, client, db):
        headers, _ = _user(client, "listdraft")
        name = f"List Forest {uuid4().hex[:8]}"
        resp = client.post(
            f"{FS}/drafts/create-name-only",
            json={"forest_name": name},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        draft_id = resp.json()["id"]

        listing = client.get("/api/v1/forests/calculations", headers=headers)
        assert listing.status_code == 200, listing.text
        mine = [c for c in listing.json() if c["id"] == draft_id]
        assert len(mine) == 1
        assert mine[0]["is_draft"] is True
        assert mine[0]["draft_data"]["islands_count"] == 0

    def test_list_returns_draft_data_for_island_draft(self, client, db):
        headers, _ = _user(client, "listislands")
        name = f"Island List Forest {uuid4().hex[:8]}"
        resp = client.post(
            f"{FS}/save-draft",
            json={
                "forest_name": name,
                "islands": [
                    {
                        "id": "island-1",
                        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                        "area": 5.5,
                    }
                ],
                "mode": "manual",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        draft_id = resp.json()["id"]

        listing = client.get("/api/v1/forests/calculations", headers=headers)
        assert listing.status_code == 200, listing.text
        mine = [c for c in listing.json() if c["id"] == draft_id]
        assert len(mine) == 1
        assert mine[0]["draft_data"]["islands_count"] == 1

    def test_import_block_before_boundary_skips_distance_gate(self, client, db):
        """Purpose-first: a Block layer can be imported before a boundary exists.

        validate_layer_distance is deferred (no boundary to measure against),
        so a shapefile/GeoJSON Block import into a name-only draft must succeed.
        """
        headers, _ = _user(client, "blockfirst")
        name = f"Block-First Forest {uuid4().hex[:8]}"
        resp = client.post(f"{FS}/drafts/create-name-only", json={"forest_name": name}, headers=headers)
        assert resp.status_code == 200, resp.text
        draft_id = resp.json()["id"]

        geojson = json.dumps({
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Block A"},
                    "geometry": {"type": "Polygon", "coordinates": [[[85.30, 27.60], [85.40, 27.60], [85.40, 27.70], [85.30, 27.70], [85.30, 27.60]]]},
                }
            ],
        })
        files = {"file": ("block.geojson", geojson, "application/geo+json")}
        import_resp = client.post(
            f"/api/v1/workspace/{draft_id}/import-layer",
            data={"purpose": "blocks"},
            files=files,
            headers=headers,
        )
