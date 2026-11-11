"""GET /api/operational-plans/map-variables (+ preview.png) — P3 / §3.9.

Uses the real client + auth harness. Availability is exercised without a
calc_id (generic) — the per-forest path is covered by the overlay tests.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_BASE = "/api/operational-plans/map-variables"


def test_list_is_authed(client):
    assert client.get(_BASE).status_code in (401, 403)


def test_list_returns_thememap_and_legacy(client, auth_headers):
    r = client.get(_BASE, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 40
    keys = {v["key"] for v in body["variables"]}
    assert "thememap:unit__growing_stock" in keys
    assert "map:boundary" in keys
    assert "S3" in body["sections"] and body["sections"]["S3"]["en"]


def test_each_item_has_metadata_and_availability(client, auth_headers):
    body = client.get(_BASE, headers=auth_headers).json()
    for v in body["variables"]:
        assert v["label_ne"] and v["label_en"]
        assert v["section_ne"] and v["section_en"]
        assert v["preview_url"].endswith("/preview.png") or ".png?" in v["preview_url"]
        a = v["availability"]
        assert a["status"] in ("available", "partial", "unavailable")
        assert isinstance(a["copyable"], bool)
        if v["family"] == "thememap":
            assert v["description_en"] and v["palette_swatch"]


def test_generic_availability_is_amber_or_red_not_green(client, auth_headers):
    # no calc_id → nothing can be confirmed 🟢; field-inventory maps are amber,
    # geometry-only maps (unit__area) are green (requires: []).
    body = client.get(_BASE, headers=auth_headers).json()
    by_key = {v["key"]: v for v in body["variables"]}
    assert by_key["thememap:unit__growing_stock"]["availability"]["status"] == "partial"
    assert by_key["thememap:unit__area"]["availability"]["status"] == "available"


def test_family_filter(client, auth_headers):
    body = client.get(_BASE + "?family=thememap", headers=auth_headers).json()
    assert body["variables"]
    assert all(v["family"] == "thememap" for v in body["variables"])


def test_preview_png_from_fixture(client, auth_headers):
    r = client.get(
        f"{_BASE}/thememap:unit__forest_condition/preview.png", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(r.content) > 4000


def test_preview_unknown_spec_404(client, auth_headers):
    r = client.get(f"{_BASE}/thememap:unit__nope/preview.png", headers=auth_headers)
    assert r.status_code == 404


def test_preview_legacy_without_calc_returns_placeholder_png(client, auth_headers):
    r = client.get(f"{_BASE}/map:boundary/preview.png", headers=auth_headers)
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_forests_endpoint_is_authed_and_well_shaped(client, auth_headers):
    assert client.get(f"{_BASE}/forests").status_code in (401, 403)
    r = client.get(f"{_BASE}/forests", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("forests"), list)
    for f in body["forests"]:
        assert set(f) >= {"calc_id", "forest_name", "status", "has_field_inventory"}
        assert f["status"] == "completed"
        assert isinstance(f["has_field_inventory"], bool)


def test_variable_catalog_still_lists_thememap_keys(client, auth_headers):
    r = client.get("/api/operational-plans/variables", headers=auth_headers)
    assert r.status_code == 200
    keys = {v["key"] for v in r.json()["variables"]}
    assert "thememap:unit__carbon" in keys
    assert "map:activity_features" not in keys  # dropped in P3
