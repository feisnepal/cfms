"""VR-6 (D6) — sub-areas are re-clipped when the boundary reshapes.

Sub-areas are cut-outs subtracted from productive area in every report.  When
the boundary moves inward, a sub-area sticking out past the new edge keeps
subtracting land the forest no longer contains.  Nothing repaired that: the
legacy clipping code never runs on the single-authority edit path.
"""
import uuid

import pytest
from shapely.geometry import Polygon, box, mapping

from app.models.calculation import Calculation
from app.models.forest_sub_area import ForestSubArea
from app.models.user import User, UserRole
from app.services.sub_area_reclip_service import (
    MIN_KEPT_AREA_M2,
    reclip_sub_areas_to_boundary,
)


BOUNDARY = box(85.760, 27.410, 85.770, 27.420)
# Shrunk on the east side — anything past x=85.765 is now outside.
SHRUNK = box(85.760, 27.410, 85.765, 27.420)


def _make_calc(db, sub_areas):
    user = User(
        email=f"vr6{uuid.uuid4().hex[:8]}@test.com",
        full_name="VR-6 Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="vr6-reclip.csv",
        is_draft=False,
        structure_locked=False,
        result_data={"sub_areas": sub_areas},
    )
    db.add(calc)
    db.flush()
    return calc


def _sa(name, poly, **extra):
    """Build a sub-area with its REAL geodesic area.

    An invented `area_hectares` makes "the area shrank" unassertable: the first
    version of these tests declared 1.0 ha for a 4.4 ha polygon, so the clipped
    remnant (1.09 ha) looked like a growth.
    """
    from app.utils.geometry_utils import calculate_area_geodesic_from_shapely
    sqm, ha = calculate_area_geodesic_from_shapely(poly)
    d = {
        "id": str(uuid.uuid4()),
        "name": name,
        "category": "water_body",
        "geometry": mapping(poly),
        "area_hectares": round(ha, 4),
        "area_sqm": round(sqm, 2),
    }
    d.update(extra)
    return d


def _add_row(db, calc, sa):
    from geoalchemy2.shape import from_shape
    from shapely.geometry import shape
    row = ForestSubArea(
        id=sa["id"],
        calculation_id=calc.id,
        name=sa["name"],
        category=sa["category"],
        geometry=from_shape(shape(sa["geometry"]), srid=4326),
        area_hectares=sa["area_hectares"],
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------

def test_a_sub_area_fully_inside_is_left_alone(db):
    inside = _sa("pond", box(85.761, 27.411, 85.762, 27.412))
    calc = _make_calc(db, [inside])
    before = calc.result_data["sub_areas"][0]["geometry"]

    out = reclip_sub_areas_to_boundary(db, calc, SHRUNK)

    assert out["clipped"] == []
    assert out["dropped"] == []
    assert out["unchanged"] == 1
    assert calc.result_data["sub_areas"][0]["geometry"] == before


def test_a_sub_area_straddling_the_new_edge_is_clipped(db):
    straddling = _sa("river", box(85.764, 27.411, 85.768, 27.412))
    calc = _make_calc(db, [straddling])
    _add_row(db, calc, straddling)
    old_area = straddling["area_hectares"]

    out = reclip_sub_areas_to_boundary(db, calc, SHRUNK)

    assert out["clipped"] == ["river"]
    kept = calc.result_data["sub_areas"][0]
    # The remnant must stop at the new edge.
    from shapely.geometry import shape
    assert shape(kept["geometry"]).bounds[2] == pytest.approx(85.765, abs=1e-9)
    # …and its recorded area must follow, or reports keep the old number.
    assert kept["area_hectares"] < old_area
    assert kept["area_sqm"] > 0


def test_a_sub_area_now_fully_outside_is_dropped(db):
    outside = _sa("quarry", box(85.766, 27.411, 85.768, 27.412))
    calc = _make_calc(db, [outside])
    _add_row(db, calc, outside)

    out = reclip_sub_areas_to_boundary(db, calc, SHRUNK)

    assert out["dropped"] == ["quarry"]
    assert calc.result_data["sub_areas"] == []
    # The spatial row must go too — two stores, one fact.
    remaining = db.query(ForestSubArea).filter(
        ForestSubArea.calculation_id == calc.id,
    ).count()
    assert remaining == 0


def test_a_sliver_remnant_is_dropped_not_kept(db):
    """A remnant below 1 m² is float noise along the edge, not a feature."""
    sliver = _sa("edge-sliver", Polygon([
        (85.764999995, 27.411), (85.768, 27.411), (85.768, 27.412), (85.764999995, 27.412),
    ]))
    calc = _make_calc(db, [sliver])
    out = reclip_sub_areas_to_boundary(db, calc, SHRUNK)
    assert out["dropped"] == ["edge-sliver"]
    assert MIN_KEPT_AREA_M2 == 1.0


def test_the_row_store_is_updated_alongside_result_data(db):
    straddling = _sa("river", box(85.764, 27.411, 85.768, 27.412))
    calc = _make_calc(db, [straddling])
    row = _add_row(db, calc, straddling)
    before_ha = row.area_hectares

    reclip_sub_areas_to_boundary(db, calc, SHRUNK)
    db.flush()
    db.refresh(row)

    assert row.area_hectares < before_ha, "ForestSubArea row must follow result_data"


def test_excluded_metrics_are_recomputed(db):
    straddling = _sa("river", box(85.764, 27.411, 85.768, 27.412))
    calc = _make_calc(db, [straddling])
    reclip_sub_areas_to_boundary(db, calc, SHRUNK)
    assert "total_excluded_area" in calc.result_data


def test_no_sub_areas_is_a_no_op(db):
    calc = _make_calc(db, [])
    out = reclip_sub_areas_to_boundary(db, calc, SHRUNK)
    assert out == {"clipped": [], "dropped": [], "unchanged": 0}


def test_an_unchanged_boundary_clips_nothing(db):
    inside = _sa("pond", box(85.761, 27.411, 85.762, 27.412))
    straddling = _sa("river", box(85.764, 27.411, 85.7649, 27.412))
    calc = _make_calc(db, [inside, straddling])

    out = reclip_sub_areas_to_boundary(db, calc, BOUNDARY)

    assert out["clipped"] == []
    assert out["dropped"] == []
    assert out["unchanged"] == 2
