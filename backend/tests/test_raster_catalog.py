"""
Raster catalog endpoint tests.

The workspace lets users search + add read-only raster overlays. The catalog
is served by GET /api/calculations/{id}/raster-layers from the SSOT
TileService.RASTER_METADATA — owner-gated like every other calculation-scoped
endpoint.
"""
import sys
import os
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.calculation import Calculation

from app.services.tile_service import TileService
from app.services.raster_class_vectorize import NASA_QUALITY
from app.core.forest_types import NASA_FOREST_QUALITY


def _user(client, tag):
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
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _owner_calc(client, db):
    owner = _user(client, "owner")
    me = client.get("/api/auth/me", headers=owner)
    assert me.status_code == 200, me.text
    calc = Calculation(user_id=me.json()["id"], forest_name="Forest", block_name="B1")
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return owner, calc


class TestRasterCatalog:
    def test_owner_gets_full_catalog(self, client, db):
        owner, calc = _owner_calc(client, db)
        resp = client.get(f"/api/calculations/{calc.id}/raster-layers", headers=owner)
        assert resp.status_code == 200, resp.text
        layers = resp.json()["layers"]
        assert len(layers) == len(TileService.RASTER_METADATA)
        ids = {l["id"] for l in layers}
        assert {"slope", "landcover", "soil_ph", "biomass"} <= ids

    def test_catalog_metadata_matches_ssot(self, client, db):
        owner, calc = _owner_calc(client, db)
        resp = client.get(f"/api/calculations/{calc.id}/raster-layers", headers=owner)
        layers = {l["id"]: l for l in resp.json()["layers"]}
        for layer_id, meta in TileService.RASTER_METADATA.items():
            assert layers[layer_id]["name"] == meta["name"]
            assert layers[layer_id]["description"] == meta["description"]
            assert layers[layer_id]["source"] == meta.get("source")
            assert layers[layer_id]["resolution"] == meta.get("resolution")

    def test_non_owner_gets_403(self, client, db):
        _, calc = _owner_calc(client, db)
        attacker = _user(client, "attacker")
        resp = client.get(f"/api/calculations/{calc.id}/raster-layers", headers=attacker)
        assert resp.status_code == 403, resp.text

    def test_unknown_calculation_gets_404(self, client, db):
        owner, _ = _owner_calc(client, db)
        resp = client.get(f"/api/calculations/{uuid4()}/raster-layers", headers=owner)
        assert resp.status_code == 404, resp.text

    def test_unauthenticated_gets_401(self, client, db):
        resp = client.get("/api/calculations/00000000-0000-0000-0000-000000000000/raster-layers")
        assert resp.status_code in (401, 403), resp.text


class TestNasaCatalogMatchesTheRaster:
    """RS-2.8 - the catalog text must describe the raster that actually exists.

    The old description read "Primary vs Secondary forest (IPCC Tier 1)", i.e.
    a 2-class scheme, and every test in this file still passed: they assert the
    endpoint *serves* RASTER_METADATA, never that RASTER_METADATA is *true*. So
    this class pins the prose to the authoritative class vocabulary instead.
    """

    DESC = TileService.RASTER_METADATA["nasa_forest_2020"]["description"]

    def test_every_carved_class_code_appears(self):
        # codes=(0, 1, 2, 3): all four are carved geometry, so all four belong
        # in the catalog text.
        for code in NASA_QUALITY.codes:
            assert str(code) in self.DESC, f"class {code} missing from catalog description"

    def test_all_three_forest_classes_are_distinguishable(self):
        # The regression: "Primary vs Secondary" collapsed Young and Old
        # secondary into one bucket. Each of the three must be nameable.
        assert "Primary" in self.DESC
        assert "Young" in self.DESC
        assert "Old" in self.DESC

    def test_class_zero_is_documented_as_mapped_not_nodata(self):
        # D39/D41: the live band declares no NoData, so 0 is a real mapped
        # class (non-forest) and describing it as NoData would be a lie.
        assert "0 = Non-forest" in self.DESC
        assert "not NoData" in self.DESC

    def test_catalog_class_names_come_from_the_shared_vocabulary(self):
        # Ties the prose to the SSOT the rest of the product uses, so the
        # catalog and NASA_FOREST_QUALITY cannot drift apart silently: the
        # distinguishing word of each class must appear in BOTH.
        for code, head in {1: "Primary", 2: "Young", 3: "Old"}.items():
            assert head in NASA_FOREST_QUALITY[code].name_en
            assert head in self.DESC, f"class {code} ({head}) missing from catalog"

    def test_description_is_not_the_stale_two_class_text(self):
        assert "Primary vs Secondary" not in self.DESC

    def test_endpoint_serves_the_corrected_description(self, client, db):
        owner, calc = _owner_calc(client, db)
        resp = client.get(f"/api/calculations/{calc.id}/raster-layers", headers=owner)
        layers = {l["id"]: l for l in resp.json()["layers"]}
        assert layers["nasa_forest_2020"]["description"] == self.DESC
