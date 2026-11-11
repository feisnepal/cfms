"""
Ownership isolation tests for workspace layer endpoints.

Regression guard: workspace layers are scoped to a calculation. Only the
calculation owner (or SUPER_ADMIN) may list / read / duplicate / delete /
update / import layers. Before this test existed, ANY authenticated user who
knew a calculation_id could read and modify another user's imported layers.
"""
import sys
import os
import io
import json
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.calculation import Calculation
from app.models.workspace_layer import WorkspaceLayer

WS = "/api/v1/workspace"


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


def _make_owner_calc(db, user_id):
    calc = Calculation(user_id=user_id, forest_name="Owner Forest", block_name="B1")
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _make_layer(db, calc):
    layer = WorkspaceLayer(
        calculation_id=calc.id,
        name="Sensitive Layer",
        purpose="custom",
        source_format="geojson",
        feature_count=1,
        file_size_bytes=100,
        geometry_types=["Polygon"],
        layer_data={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                    },
                    "properties": {"name": "secret", "featureId": "imported-0"},
                }
            ],
        },
        is_draft=True,
    )
    db.add(layer)
    db.commit()
    db.refresh(layer)
    return layer


def _fixture(client, db):
    """Create owner + attacker users, an owner calc, and one sensitive layer."""
    owner_headers, owner_id = _user(client, "owner")
    attacker_headers, _ = _user(client, "attacker")
    calc = _make_owner_calc(db, owner_id)
    layer = _make_layer(db, calc)
    return owner_headers, attacker_headers, calc, layer


class TestWorkspaceOwnership:
    def test_non_owner_cannot_list_layers(self, client, db):
        _, attacker, calc, _ = _fixture(client, db)
        resp = client.get(f"{WS}/{calc.id}/import-layers", headers=attacker)
        assert resp.status_code == 403, resp.text

    def test_non_owner_cannot_read_features(self, client, db):
        _, attacker, calc, layer = _fixture(client, db)
        resp = client.get(f"{WS}/{calc.id}/import-layers/{layer.id}/features", headers=attacker)
        assert resp.status_code == 403, resp.text

    def test_non_owner_cannot_duplicate_layer(self, client, db):
        _, attacker, calc, layer = _fixture(client, db)
        resp = client.post(
            f"{WS}/{calc.id}/import-layers/duplicate",
            json={"source_layer_id": layer.id, "new_name": "stolen copy"},
            headers=attacker,
        )
        assert resp.status_code == 403, resp.text

    def test_non_owner_cannot_delete_layer(self, client, db):
        _, attacker, calc, layer = _fixture(client, db)
        resp = client.delete(f"{WS}/{calc.id}/import-layers/{layer.id}", headers=attacker)
        assert resp.status_code == 403, resp.text

    def test_non_owner_cannot_update_feature(self, client, db):
        _, attacker, calc, layer = _fixture(client, db)
        resp = client.patch(
            f"{WS}/{calc.id}/import-layers/{layer.id}/features/0",
            json={"properties": {"name": "hacked"}},
            headers=attacker,
        )
        assert resp.status_code == 403, resp.text

    def test_non_owner_cannot_import(self, client, db):
        _, attacker, calc, _ = _fixture(client, db)
        resp = client.post(
            f"{WS}/{calc.id}/import-layer",
            files={"file": ("x.geojson", io.BytesIO(b'{"type":"FeatureCollection"}'), "application/geo+json")},
            data={"purpose": "custom"},
            headers=attacker,
        )
        assert resp.status_code == 403, resp.text

    def test_owner_can_list_and_read_own_layers(self, client, db):
        owner, _, calc, layer = _fixture(client, db)
        list_resp = client.get(f"{WS}/{calc.id}/import-layers", headers=owner)
        assert list_resp.status_code == 200, list_resp.text
        assert any(l["id"] == layer.id for l in list_resp.json())

        feat_resp = client.get(f"{WS}/{calc.id}/import-layers/{layer.id}/features", headers=owner)
        assert feat_resp.status_code == 200, feat_resp.text
        assert feat_resp.json()["features"][0]["properties"]["name"] == "secret"

    def test_import_without_purpose_persists_unassigned(self, client, db):
        """'Skip / Assign Purpose Later': no purpose field -> the layer stays
        unassigned (purpose is None) in the list response. The frontend "Unassigned"
        badge and "Assign Purpose" context-menu action both key off a falsy purpose.
        Regression guard for the workspace_layers column default that coerced None
        to 'custom' (a truthy, assigned-looking purpose)."""
        owner, _, calc, _ = _fixture(client, db)
        geojson = json.dumps({
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Unassigned Area"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[85.300, 27.600], [85.305, 27.600], [85.305, 27.605], [85.300, 27.605], [85.300, 27.600]]],
                    },
                }
            ],
        })
        resp = client.post(
            f"{WS}/{calc.id}/import-layer",
            files={"file": ("area.geojson", geojson.encode(), "application/geo+json")},
            headers=owner,
        )
        assert resp.status_code == 200, resp.text
        layer_id = resp.json()["id"]

        list_resp = client.get(f"{WS}/{calc.id}/import-layers", headers=owner)
        assert list_resp.status_code == 200, list_resp.text
        layer = next(l for l in list_resp.json() if l["id"] == layer_id)
        assert layer["purpose"] is None, layer["purpose"]

    def test_unknown_calculation_returns_404(self, client, db):
        _, attacker, _, _ = _fixture(client, db)
        resp = client.get(f"{WS}/{uuid4()}/import-layers", headers=attacker)
        assert resp.status_code == 404, resp.text


class TestWorkspaceRecomputeGeo:
    def _legacy_layer(self, db, calc):
        """Layer as it existed BEFORE auto-computation: no geo_* fields."""
        layer = WorkspaceLayer(
            calculation_id=calc.id,
            name="Legacy Layer",
            purpose="custom",
            source_format="geojson",
            feature_count=2,
            file_size_bytes=200,
            geometry_types=["Polygon", "Point"],
            layer_data={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                        },
                        "properties": {"name": "poly"},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [2.0, 3.0]},
                        "properties": {"name": "pt"},
                    },
                ],
            },
            is_draft=True,
        )
        db.add(layer)
        db.commit()
        db.refresh(layer)
        return layer

    def _owner_calc(self, client, db):
        owner_headers, owner_id = _user(client, "owner")
        calc = _make_owner_calc(db, owner_id)
        return owner_headers, calc

    def test_backfills_geo_on_existing_layers(self, client, db):
        owner, calc = self._owner_calc(client, db)
        layer = self._legacy_layer(db, calc)

        resp = client.post(f"{WS}/{calc.id}/import-layers/recompute-geo", headers=owner)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["layers_updated"] == 1
        assert body["features_updated"] == 2

        db.expire_all()
        fresh = db.get(WorkspaceLayer, layer.id)
        feats = fresh.layer_data["features"]
        assert feats[0]["properties"]["geo_area_ha"] > 0
        assert feats[1]["properties"]["geo_centroid_lat"] == 3.0
        assert feats[1]["properties"]["geo_centroid_lng"] == 2.0

    def test_strips_spoofed_geo_before_recompute(self, client, db):
        owner, calc = self._owner_calc(client, db)
        layer = self._legacy_layer(db, calc)
        # simulate a layer whose stored geo_* was tampered with
        layer.layer_data["features"][0]["properties"]["geo_area_ha"] = 99999.0
        db.add(layer)
        db.commit()

        resp = client.post(f"{WS}/{calc.id}/recompute-geo", headers=owner)
        # wrong path on purpose — ensure this is the layer endpoint
        assert resp.status_code == 404, resp.text

        resp = client.post(f"{WS}/{calc.id}/import-layers/recompute-geo", headers=owner)
        assert resp.status_code == 200, resp.text
        db.expire_all()
        fresh = db.get(WorkspaceLayer, layer.id)
        stored = fresh.layer_data["features"][0]["properties"]["geo_area_ha"]
        assert stored != 99999.0
        assert stored > 0

    def test_non_owner_cannot_backfill(self, client, db):
        _, attacker, calc, _ = _fixture(client, db)
        resp = client.post(f"{WS}/{calc.id}/import-layers/recompute-geo", headers=attacker)
        assert resp.status_code == 403, resp.text

    def test_no_layers_returns_zero(self, client, db):
        owner_headers, owner_id = _user(client, "owner")
        calc = _make_owner_calc(db, owner_id)
        resp = client.post(f"{WS}/{calc.id}/import-layers/recompute-geo", headers=owner_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["layers_updated"] == 0
        assert body["features_updated"] == 0


class TestWorkspaceRename:
    """Rename is name-only: purpose (and all other metadata) must never change."""

    def test_owner_can_rename_layer(self, client, db):
        owner, _, calc, layer = _fixture(client, db)
        resp = client.patch(
            f"{WS}/{calc.id}/import-layers/{layer.id}",
            json={"name": "Renamed Layer"},
            headers=owner,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Renamed Layer"
        assert body["old_name"] == "Sensitive Layer"
        assert body["purpose"] == "custom"

        db.expire_all()
        fresh = db.get(WorkspaceLayer, layer.id)
        assert fresh.name == "Renamed Layer"
        assert fresh.purpose == "custom"

    def test_rename_does_not_change_purpose(self, client, db):
        owner, _, calc, layer = _fixture(client, db)
        resp = client.patch(
            f"{WS}/{calc.id}/import-layers/{layer.id}",
            json={"name": "New Name", "purpose": "boundary", "source_format": "shp"},
            headers=owner,
        )
        assert resp.status_code == 200, resp.text
        db.expire_all()
        fresh = db.get(WorkspaceLayer, layer.id)
        assert fresh.name == "New Name"
        # Extra/malicious fields in the payload must be ignored — purpose is immutable.
        assert fresh.purpose == "custom"
        assert fresh.source_format == "geojson"

    def test_non_owner_cannot_rename_layer(self, client, db):
        _, attacker, calc, layer = _fixture(client, db)
        resp = client.patch(
            f"{WS}/{calc.id}/import-layers/{layer.id}",
            json={"name": "stolen"},
            headers=attacker,
        )
        assert resp.status_code == 403, resp.text

    def test_unknown_calculation_returns_404(self, client, db):
        owner, _, _, layer = _fixture(client, db)
        resp = client.patch(
            f"{WS}/{uuid4()}/import-layers/{layer.id}",
            json={"name": "x"},
            headers=owner,
        )
        assert resp.status_code == 404, resp.text

    def test_unknown_layer_returns_404(self, client, db):
        owner, _, calc, _ = _fixture(client, db)
        resp = client.patch(
            f"{WS}/{calc.id}/import-layers/999999",
            json={"name": "x"},
            headers=owner,
        )
        assert resp.status_code == 404, resp.text

    def test_empty_name_rejected(self, client, db):
        owner, _, calc, layer = _fixture(client, db)
        for bad in ["", "   "]:
            resp = client.patch(
                f"{WS}/{calc.id}/import-layers/{layer.id}",
                json={"name": bad},
                headers=owner,
            )
            assert resp.status_code == 422, resp.text

    def test_renamed_layer_appears_in_list(self, client, db):
        owner, _, calc, layer = _fixture(client, db)
        client.patch(
            f"{WS}/{calc.id}/import-layers/{layer.id}",
            json={"name": "Fresh Name"},
            headers=owner,
        )
        resp = client.get(f"{WS}/{calc.id}/import-layers", headers=owner)
        assert resp.status_code == 200, resp.text
        entry = next(l for l in resp.json() if l["id"] == layer.id)
        assert entry["name"] == "Fresh Name"
        assert entry["purpose"] == "custom"
