"""Auto-block / auto-divide error readability (RS-2.6).

The coverage failures of the four carving sources and the `DIVISION_TOO_FEW`
guard must reach the user as a real bilingual sentence. The defect this row
fixes: the previews raise *bare* tokens (`no_slope_coverage`), while the
registry is nested (`blocks.no_slope_coverage`) and `with_message_np` splits on
`.`, so a bare token never resolved — the API answered 400 with the raw
snake_case string in **both** `message` and `message_np`. Three of the four
coverage codes had been registered all along and were unreachable; the fourth
(NASA) was never registered.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.core.exceptions import (
    resolve_bare_service_detail,
    resolve_service_detail,
)

# Every coverage token `auto_block_service` can raise, per source. The four
# carving sources + the divide-path scope guard.
COVERAGE_TOKENS = [
    "no_slope_coverage",
    "no_aspect_coverage",
    "no_canopy_coverage",
    "no_nasa_quality_coverage",
    "no_coverage_in_feature",
]

_BBOX = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])


# ---------------------------------------------------------------------------
# Resolver level: a bare token must become a real bilingual detail
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("token", COVERAGE_TOKENS)
def test_bare_coverage_token_resolves_to_blocks_category(token):
    detail = resolve_bare_service_detail(token)
    assert detail["code"] == f"blocks.{token}"
    # the actual failure this row fixes: not the raw token in either language
    assert detail["message"] != token
    assert detail["message_np"] != token
    assert detail["message"] != detail["message_np"]


def test_no_coverage_code_was_reachable_before_this_row():
    """Guard the defect itself: a bare token must never fall through to the
    passthrough, which is what produced the raw snake_case response."""
    for token in COVERAGE_TOKENS:
        detail = resolve_bare_service_detail(token)
        assert detail.get("code") != token, f"{token} still unresolved"


def test_division_too_few_prefix_resolves_to_editing_category():
    raw = (
        "DIVISION_TOO_FEW: A division needs at least two pieces - "
        "nothing was changed."
    )
    detail = resolve_service_detail(raw)
    assert detail["code"] == "editing.divide_too_few"
    assert detail["message"] != detail["message_np"]
    assert "DIVISION_TOO_FEW" not in detail["message"]
    assert detail["message_np"]
    # the raw text is still available for diagnostics
    assert detail["raw"] == raw


def test_bare_resolver_ignores_dotted_and_prefixed_text():
    """A prefixed guard message must keep going through `resolve_service_detail`."""
    out = resolve_bare_service_detail("PARENT_NOT_FOUND: parent missing")
    assert out["code"] == "blocks.forest_division_not_found"


def test_unknown_bare_token_still_falls_through_instead_of_raising():
    detail = resolve_bare_service_detail("totally_unregistered_token")
    assert detail["code"] == "totally_unregistered_token"
    assert detail["message"] == "totally_unregistered_token"


# ---------------------------------------------------------------------------
# Wire level
# ---------------------------------------------------------------------------
@pytest.fixture()
def nasa_raster(db):
    """A uniform single-class NASA raster: exactly one carveable piece."""
    arr = "ARRAY[" + ",".join(
        "ARRAY[" + ",".join("1" for _ in range(20)) + "]" for _ in range(20)
    ) + "]::double precision[][]"
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rasters.nasa_forest_2020 "
            "(rid serial PRIMARY KEY, rast raster)"
        )
    )
    db.execute(text("DELETE FROM rasters.nasa_forest_2020"))
    db.execute(
        text(
            "INSERT INTO rasters.nasa_forest_2020 (rast) "
            "SELECT ST_SetBandNoDataValue(ST_SetValues(ST_AddBand("
            "  ST_MakeEmptyRaster(20, 20, 84.0, 27.002, 0.0001, -0.0001, 0, 0, 4326),"
            "  '8BUI'::text, 0, 0), 1, 1, 1, "
            f"{arr}), 1, NULL)"
        )
    )
    db.commit()
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.nasa_forest_2020"))
    db.commit()


def _owner(client, db):
    email = f"i18n-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "I18N User"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _make_calc(db, user):
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="i18n-test.csv",
        is_draft=False,
        structure_locked=False,
        result_data={},
    )
    db.add(calc)
    db.flush()
    calc.boundary_geom = from_shape(_BBOX, srid=4326)
    db.flush()
    return calc


def test_api_missing_raster_returns_bilingual_coverage_error(client, db):
    """No NASA raster at all -> 400 with a readable sentence, both languages."""
    headers, user = _owner(client, db)
    calc = _make_calc(db, user)
    db.commit()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "nasa_quality"},
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "blocks.no_nasa_quality_coverage"
    assert detail["message"] != "no_nasa_quality_coverage"
    assert detail["message_np"] != detail["message"]
    assert detail["message_np"]


def test_api_divide_too_few_returns_bilingual_error(client, db, nasa_raster):
    """Rule 17: a source that yields a single piece must say so readably."""
    headers, user = _owner(client, db)
    calc = _make_calc(db, user)
    db.commit()

    parent = ForestBlock(
        calculation_id=calc.id,
        name="Block-1",
        block_name="Block-1",
        geometry=from_shape(_BBOX, srid=4326),
        area_hectares=4.93,
        area_sqm=49320.0,
        index=1,
        is_compartment=False,
        division_level=1,
        is_locked=False,
        child_count=0,
    )
    db.add(parent)
    db.commit()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/blocks/{parent.id}/auto-divide/commit",
        headers=headers,
        json={
            "level": "sub_blocks",
            "blocks": [
                {
                    "index": 1,
                    "name": "C1",
                    "geometry": _BBOX.__geo_interface__,
                }
            ],
        },
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "editing.divide_too_few"
    assert detail["message"] != detail["message_np"]
    assert "DIVISION_TOO_FEW" not in detail["message"]
    # nothing was written
    assert (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == parent.id)
        .count()
        == 0
    )
