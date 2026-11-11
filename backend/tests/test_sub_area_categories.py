"""
Sub-area category catalogue tests — backend SSOT.

Verifies:
- `SubAreaCategory.catalog()` returns the official 13-value List A with
  EN/NP labels, colors and the private_land-only exclusion rule.
- `GET /api/forests/sub-area-categories` serves that catalogue.
- The catalogue stays consistent with `SubAreaCategory.valid_categories()`.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.schemas.forest import SubAreaCategory, SubAreaCategoryItem

OFFICIAL_13 = [
    "protected", "plantation", "pro-poor", "religious", "biodiversity",
    "tourist", "office", "private_land", "agroforestry", "tree_strata",
    "water_hole", "wildlife_corridor", "encroached",
]

# Retired List B keys that must NOT appear in the catalogue (D1)
LEGACY_LIST_B = [
    "road", "stream", "river", "degraded", "settlement", "agriculture",
    "water_body", "cliff", "wetland", "grassland", "shrubland", "conservation",
]


def test_catalog_has_exactly_official_13():
    cat = SubAreaCategory.catalog()
    keys = [c["key"] for c in cat]
    assert sorted(keys) == sorted(OFFICIAL_13)
    for legacy in LEGACY_LIST_B:
        assert legacy not in keys


def test_catalog_entries_complete_and_consistent():
    cat = SubAreaCategory.catalog()
    assert set(c["key"] for c in cat) == set(SubAreaCategory.valid_categories())
    for entry in cat:
        assert entry["label"], entry["key"]
        assert entry["label_np"], entry["key"]
        assert entry["color"].startswith("#")
        assert isinstance(entry["is_excluded"], bool)


def test_is_excluded_only_private_land():
    for entry in SubAreaCategory.catalog():
        assert entry["is_excluded"] == (entry["key"] == "private_land"), entry["key"]


def test_sub_area_category_item_schema():
    entry = SubAreaCategory.catalog()[0]
    item = SubAreaCategoryItem(**entry)
    assert item.key == entry["key"]


def test_sub_area_categories_endpoint(client, auth_headers):
    resp = client.get("/api/forests/sub-area-categories", headers=auth_headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, list)
    assert len(payload) == 13
    keys = [c["key"] for c in payload]
    assert sorted(keys) == sorted(OFFICIAL_13)
    excluded = [c["key"] for c in payload if c["is_excluded"]]
    assert excluded == ["private_land"]


def test_sub_area_categories_endpoint_requires_auth(client):
    resp = client.get("/api/forests/sub-area-categories")
    assert resp.status_code in (401, 403)


def test_total_excluded_area_derives_from_category():
    from app.api.forests import calculate_total_excluded_area

    # private_land is excluded even when the legacy flag is absent.
    sa_private = {"id": "p1", "category": "private_land", "area_hectares": 4.5}
    sa_office = {"id": "o1", "category": "office", "area_hectares": 1.0}
    # legacy flag is honored but never overrides category on a private_land entry.
    sa_private_flag_false = {"id": "p2", "category": "private_land", "area_hectares": 2.0, "is_excluded": False}
    assert calculate_total_excluded_area([sa_private]) == 4.5
    assert calculate_total_excluded_area([sa_office]) == 0.0
    assert calculate_total_excluded_area([sa_private, sa_office]) == 4.5
    assert calculate_total_excluded_area([sa_private_flag_false]) == 2.0

    # isExcluded camelCase alias still honored for non-private categories.
    sa_other = {"id": "x1", "category": "biodiversity", "area_hectares": 3.0, "isExcluded": True}
    assert calculate_total_excluded_area([sa_other]) == 3.0


def test_block_excluded_areas_derives_from_category():
    from app.api.forests import calculate_block_excluded_areas

    blocks = [{"block_id": "b1"}, {"block_id": "b2"}]
    sa_private = {
        "id": "p1", "category": "private_land", "area_hectares": 5.0,
        "block_id": "b1", "blockBreakdown": [{"blockId": "b1", "area": 5.0}],
    }
    sa_office = {
        "id": "o1", "category": "office", "area_hectares": 1.0,
        "block_id": "b2", "blockBreakdown": [{"blockId": "b2", "area": 1.0}],
    }
    result = calculate_block_excluded_areas(blocks, [sa_private, sa_office])
    assert result["b1"] == 5.0
    assert result["b2"] == 0.0

