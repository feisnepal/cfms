"""Total Tree Export can be limited to selected blocks (``unit_ids``).

Covers the request half of the feature: ``_unit_scope_config`` turns a selection
into generator config, and refuses ids that are not units of THIS calculation
instead of silently exporting a different area. The raster clip itself needs the
canopy TIFF and is not exercised here.
"""
import uuid

import pytest
from fastapi import HTTPException
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon

from app.api.all_tree_exports import _unit_scope_config
from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.schemas.all_tree_export import GenerateAllTreesRequest


def _calc(db):
    user = User(
        email=f"scope{uuid.uuid4().hex[:8]}@test.com",
        full_name="Scope Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="scope-test.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    return calc


def _block(db, calc, x0, name):
    geom = Polygon([(x0, 0.0), (x0 + 0.01, 0.0), (x0 + 0.01, 0.01), (x0, 0.01)])
    block = ForestBlock(
        calculation_id=calc.id,
        name=name,
        block_name=name,
        geometry=from_shape(geom, srid=4326),
        area_hectares=1.0,
        area_sqm=10000.0,
        index=0,
        is_compartment=False,
        division_level=1,
        is_locked=False,
        child_count=0,
    )
    db.add(block)
    db.flush()
    return block


def test_no_selection_means_whole_boundary(db):
    calc = _calc(db)
    assert _unit_scope_config(db, calc.id, None) == {}
    assert _unit_scope_config(db, calc.id, []) == {}


def test_selected_units_become_sorted_string_ids(db):
    calc = _calc(db)
    a, b = _block(db, calc, 0.0, "Block-1"), _block(db, calc, 0.05, "Block-2")
    out = _unit_scope_config(db, calc.id, [b.id, a.id, a.id])
    assert out == {"unit_ids": sorted([str(a.id), str(b.id)])}


def test_unit_of_another_forest_is_refused(db):
    mine, other = _calc(db), _calc(db)
    foreign = _block(db, other, 0.0, "Block-X")
    with pytest.raises(HTTPException) as exc:
        _unit_scope_config(db, mine.id, [foreign.id])
    assert exc.value.status_code == 400


def test_unknown_id_is_refused_not_dropped(db):
    calc = _calc(db)
    real = _block(db, calc, 0.0, "Block-1")
    with pytest.raises(HTTPException) as exc:
        _unit_scope_config(db, calc.id, [real.id, uuid.uuid4()])
    assert exc.value.status_code == 400


def test_request_schema_accepts_unit_ids_and_defaults_to_none():
    assert GenerateAllTreesRequest().unit_ids is None
    uid = uuid.uuid4()
    assert GenerateAllTreesRequest(unit_ids=[uid]).unit_ids == [uid]
