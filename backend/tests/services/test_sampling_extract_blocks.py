"""Sampling unit extraction tests (SAMPLING_PAGE_REWORK, Phase B fix).

Covers ``extract_blocks_from_calculation``:
- DB-stored blocks (workspace flow: forest_blocks with is_compartment=False) are
  returned with their real block names instead of falling back to the whole
  boundary named after the forest.
- DB-stored compartments take priority.
- Legacy upload-mode result_data blocks/compartments still work.
- Whole-boundary fallback only when nothing else exists.
"""
import uuid

from shapely.geometry import Polygon

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services.sampling import extract_blocks_from_calculation


NS = 83.5  # Nepal UTM zone 44 reference longitude (avoids projection-domain errors)
NL = 27.5


def _square(x, y, size=0.01):
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _make_user(db, email=None):
    user = User(
        email=email or f"ext{uuid.uuid4().hex[:8]}@test.com",
        full_name="Extract Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db, boundary=None, forest_name="Test Forest", result_data=None):
    user = _make_user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="extract-test.csv",
        is_draft=False,
        structure_locked=False,
        forest_name=forest_name,
        result_data=result_data or {},
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        from geoalchemy2.shape import from_shape
        calc.boundary_geom = from_shape(boundary, srid=4326)
        db.flush()
    return calc


def _add_db_unit(db, calc, geom, name, is_compartment=False, index=1, code=None):
    from geoalchemy2.shape import from_shape
    from app.utils.geometry_utils import calculate_area_geodesic_from_shapely

    # `geom.area` on an EPSG:4326 geometry is in SQUARE DEGREES, so the previous
    # `geom.area / 10000.0` treated degrees as metres and, after rounding to 4
    # decimals, produced 0.0 — which violates the forest_blocks
    # area_hectares > 0 CHECK. That went unnoticed while the test harness built
    # its schema from Base.metadata, which declares no CHECK constraints; it
    # surfaced as soon as the harness started using the real migrations (H1.6).
    # Use the geodesic helper, matching test_sub_area_reclip.py.
    _sqm, _ha = calculate_area_geodesic_from_shapely(geom)
    row = ForestBlock(
        calculation_id=calc.id,
        name=name,
        block_name=name,
        compartment_code=code,
        geometry=from_shape(geom, srid=4326),
        area_hectares=round(_ha * 0.98, 4),
        index=index,
        is_compartment=is_compartment,
        division_level=1,
    )
    db.add(row)
    db.flush()
    return row


def test_extracts_db_stored_blocks_instead_of_boundary_fallback(db):
    """Workspace-mode forest: blocks live only in forest_blocks (result_data empty)."""
    calc = _make_calc(db, boundary=_square(NS - 0.02, NL - 0.02, size=0.06), forest_name="Gothar CF")
    for i in range(3):
        _add_db_unit(db, calc, _square(NS - 0.02 + i * 0.02, NL - 0.01), f"Block-{i + 1}", index=i + 1)

    units = extract_blocks_from_calculation(db, calc.id)

    assert len(units) == 3
    assert [u[2] for u in units] == ["Block-1", "Block-2", "Block-3"]
    # Real block geometry (not the whole boundary)
    for _, wkt, name, _area in units:
        assert "Gothar" not in name
        assert "POLYGON" in wkt


def test_db_compartments_are_the_sampling_units(db):
    """Compartment-mode forest: the compartments are the sampling units."""
    calc = _make_calc(db, boundary=_square(NS - 0.02, NL - 0.02, size=0.06), forest_name="Phurkecaur")
    _add_db_unit(db, calc, _square(NS, NL), "C1", is_compartment=True, index=1, code="C1")
    _add_db_unit(db, calc, _square(NS + 0.02, NL), "C2", is_compartment=True, index=2, code="C2")

    units = extract_blocks_from_calculation(db, calc.id)

    assert [u[2] for u in units] == ["C1", "C2"]


def test_a_legacy_mixed_forest_samples_its_whole_leaf_view(db):
    """FS-1a.4 (plan A4). A forest holding a plain block beside compartments breaks the structure rule, but its
    block is still forest ground: the old code dropped it silently ('blocks must NOT be used once compartments
    exist'), so no plots were planned there. Sampling now covers the whole leaf view until mixed forests are
    removed (P2/P6)."""
    calc = _make_calc(db, boundary=_square(NS - 0.02, NL - 0.02, size=0.06), forest_name="Phurkecaur")
    _add_db_unit(db, calc, _square(NS, NL), "C1", is_compartment=True, index=1, code="C1")
    _add_db_unit(db, calc, _square(NS + 0.02, NL), "C2", is_compartment=True, index=2, code="C2")
    _add_db_unit(db, calc, _square(NS + 0.03, NL + 0.03), "Block-1", index=3)

    units = extract_blocks_from_calculation(db, calc.id)

    assert [u[2] for u in units] == ["C1", "C2", "Block-1"]


def test_legacy_result_data_blocks_still_work(db):
    """Upload-mode forest: blocks only in result_data, no forest_blocks rows."""
    calc = _make_calc(db, boundary=_square(NS - 0.02, NL - 0.02, size=0.06), result_data={
        "blocks": [
            {"block_name": "North", "geometry": _square(NS, NL).__geo_interface__},
            {"block_name": "South", "geometry": _square(NS, NL + 0.02).__geo_interface__},
        ]
    })

    units = extract_blocks_from_calculation(db, calc.id)

    assert [u[2] for u in units] == ["North", "South"]


def test_fresh_db_blocks_win_over_stale_result_data_compartments(db):
    """Regression (बृन्दाबन): a forest was divided into compartments, then the
    compartments + blocks were deleted in the workspace and blocks auto-created
    fresh. The workspace delete never cleared ``result_data['compartments']``,
    so sampling ran against the 8 deleted compartments (part of the forest)
    instead of the 4 fresh blocks. The DB must win whenever it has any rows.
    """
    stale = {
        "compartments": [
            {"compartment_code": f"OLD-{i}",
             "geometry": _square(NS + i * 0.005, NL, size=0.004).__geo_interface__}
            for i in range(8)
        ],
        "blocks": [
            {"block_name": f"old-blk-{i}",
             "geometry": _square(NS + i * 0.02, NL, size=0.01).__geo_interface__}
            for i in range(4)
        ],
    }
    calc = _make_calc(
        db, boundary=_square(NS - 0.02, NL - 0.02, size=0.09),
        forest_name="Brindaban CF", result_data=stale,
    )
    for i in range(4):
        _add_db_unit(db, calc, _square(NS - 0.02 + i * 0.02, NL), f"blocks-{i + 1}", index=i + 1)

    units = extract_blocks_from_calculation(db, calc.id)

    assert [u[2] for u in units] == ["blocks-1", "blocks-2", "blocks-3", "blocks-4"]


def test_all_units_deleted_falls_to_boundary_not_stale_result_data(db):
    """Workspace forest whose every block/compartment row was deleted: don't
    resurrect the stale result_data arrays — use the whole boundary."""
    calc = _make_calc(
        db, boundary=_square(NS - 0.02, NL - 0.02, size=0.06),
        forest_name="Cleared CF",
        result_data={"compartments": [
            {"compartment_code": "GHOST",
             "geometry": _square(NS, NL, size=0.004).__geo_interface__}
        ]},
    )
    # one row that then gets removed → the calc HAS had forest_blocks structure.
    # The real delete-block / delete-all-blocks routes set this flag when the
    # last unit goes; it is what marks the forest "workspace-managed, now empty".
    row = _add_db_unit(db, calc, _square(NS, NL), "tmp", index=1)
    db.delete(row)
    calc.blocks_cleared_by_user = True
    db.flush()

    units = extract_blocks_from_calculation(db, calc.id)

    assert len(units) == 1
    assert units[0][2] == "Cleared CF - Block 1"


def test_whole_boundary_fallback_when_nothing_else(db):
    """No blocks anywhere: single unit named after the forest (legacy behavior)."""
    calc = _make_calc(db, boundary=_square(NS - 0.02, NL - 0.02, size=0.06), forest_name="Sundar CF")

    units = extract_blocks_from_calculation(db, calc.id)

    assert len(units) == 1
    assert units[0][2] == "Sundar CF - Block 1"


def test_missing_calculation_raises(db):
    import pytest as _pytest
    with _pytest.raises(ValueError):
        extract_blocks_from_calculation(db, uuid.uuid4())
