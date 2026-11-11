"""Strips (fire line) are rendered everywhere a sub-area is, but are not a user-pickable category."""
import re
from pathlib import Path

from app.core import constants
from app.core.semantic_palettes import CATEGORICAL
from app.core.sub_area_kinds import STRIP_CATALOG, STRIP_CATEGORIES, is_strip, real_sub_areas
from app.schemas.forest import SubAreaCategory
from app.services.sub_area_plan import SUB_AREA_PLAN_EXEMPT_CATEGORIES

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src"


def test_strip_catalog_matches_strip_categories():
    assert [c["key"] for c in STRIP_CATALOG] == list(STRIP_CATEGORIES)
    for c in STRIP_CATALOG:
        assert c["is_strip"] is True and c["is_excluded"] is False
        assert c["label"] and c["label_np"] and re.fullmatch(r"#[0-9a-f]{6}", c["color"])


def test_a_strip_is_not_a_user_pickable_category():
    user_keys = {c["key"] for c in SubAreaCategory.catalog()}
    assert not user_keys & set(STRIP_CATEGORIES)
    assert not set(SubAreaCategory.valid_categories()) & set(STRIP_CATEGORIES)


def test_palette_has_every_strip_with_the_catalog_colour():
    palette = CATEGORICAL["subarea_category"]
    for c in STRIP_CATALOG:
        assert palette[c["key"]] == c["color"]


def test_strips_need_no_yearly_plan_line():
    assert set(STRIP_CATEGORIES) <= SUB_AREA_PLAN_EXEMPT_CATEGORIES
    assert "private_land" in SUB_AREA_PLAN_EXEMPT_CATEGORIES


def test_real_sub_areas_drops_only_strips():
    subs = [{"id": 1, "category": "plantation"}, {"id": 2, "category": "fire_line"}, {"id": 3, "category": "private_land"}]
    assert [s["id"] for s in real_sub_areas(subs)] == [1, 3]
    assert is_strip(subs[1]) and not is_strip(subs[0])
    assert real_sub_areas(None) == []


def test_fire_line_constants():
    assert constants.FIRE_LINE_SIDE_M == 1.5
    assert constants.STRIP_MIN_LENGTH_M == 10.0


def test_frontend_lists_the_same_strips():
    src = (FRONTEND / "lib" / "subAreaCategories.ts").read_text(encoding="utf-8")
    block = src[src.index("STRIP_CATEGORIES"):]
    for c in STRIP_CATALOG:
        assert f"key: '{c['key']}'" in block, c["key"]
        assert c["label"] in block and c["label_np"] in block and c["color"] in block
    palette = (FRONTEND / "lib" / "semanticPalettes.ts").read_text(encoding="utf-8")
    for c in STRIP_CATALOG:
        assert f"{c['key']}: '{c['color']}'" in palette


def test_a_fire_line_cannot_be_promoted_to_a_protection_unit():
    from types import SimpleNamespace

    import pytest

    from app.services.protection_unit_service import promote_subarea_to_unit

    calc = SimpleNamespace(structure_locked=False, result_data={"sub_areas": [{"id": "s1", "category": "fire_line"}]})
    with pytest.raises(ValueError, match="NOT_PROTECTED"):
        promote_subarea_to_unit(None, calc, "s1")
