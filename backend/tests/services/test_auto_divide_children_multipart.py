"""Regression test for a live bug (reported 2026-09-23): "Auto create using
slope" on an existing block/compartment ("auto divide") raised

    geometry has 2 disjoint substantial parts (areas m^2: [...]) but only
    one row is being created for it -- explode into one row per part ...

`auto_block_service.commit_children` folds a below-floor sliver into its
largest (possibly disjoint) neighbour, exactly like `commit_blocks` already
does for the whole-forest case -- but handed the result to
`compartment_divide_service._persist_children`, which (unlike `commit_blocks`)
had no bypass for the resulting `MultiPolygon`, so the model's own
`@validates('geometry')` guard raised instead of persisting it.

A private-land sub-area spanning the parent's full height splits the
divide's `scope` (parent minus private land) into two disjoint regions --
the same shape a scope-carve produces live. A requested child straddling
that gap is what surfaces the bug.

Traced via a temporary `stack_info=True` diagnostic against the live server,
reproduced here directly against `commit_children`.
"""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Polygon, box, mapping

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import auto_block_service as svc
from app.services.forest_units.model import DEPTH_TOP_BLOCK


def _make_calc(db):
    user = User(
        email=f"autodivmp{uuid.uuid4().hex[:8]}@test.com",
        full_name="Auto Divide Multipart Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="auto-divide-mp.csv",
        is_draft=False,
    )
    db.add(calc)
    db.flush()
    calc.boundary_geom = from_shape(box(84.0, 27.0, 84.002, 27.002), srid=4326)
    db.flush()
    return calc


def test_commit_children_folds_a_disjoint_sliver_into_one_multipart_row(db):
    """A private-land strip through the middle of the parent splits its
    divide `scope` into a big west region and a below-floor east sliver. A
    requested child straddling the strip must persist as ONE row (the
    sliver folded in, staying a genuine MultiPolygon), not raise
    MultiPartFeatureError."""
    calc = _make_calc(db)
    parent_geom = box(84.0, 27.0, 84.002, 27.002)
    parent = ForestBlock(
        calculation_id=calc.id,
        name="Block-1",
        block_name="Block-1",
        geometry=from_shape(parent_geom, srid=4326),
        area_hectares=4.5,
        area_sqm=44_400.0,
        index=0,
        is_compartment=False,
        division_level=DEPTH_TOP_BLOCK,
    )
    db.add(parent)
    db.flush()

    # A private-land strip splits the divide's `scope` (parent minus private
    # land) into a big west region and a ~2200 m^2 east sliver (well under
    # the 1 ha floor) -- the same shape a scope-carve produces live.
    private_strip = box(84.00175, 27.0, 84.0019, 27.002)
    calc.result_data = {
        "sub_areas": [
            {
                "id": str(uuid.uuid4()),
                "category": "private_land",
                "isExcluded": False,
                "geometry": mapping(private_strip),
            }
        ]
    }
    db.flush()

    mid_x = 84.0005
    payload = [
        {"index": 1, "name": "SB-1", "geometry": mapping(
            Polygon([(84.0, 27.0), (mid_x, 27.0), (mid_x, 27.002), (84.0, 27.002)])
        )},
        # This one straddles the private-land strip: its scope-clipped
        # remainder is the big-vs-tiny disjoint pair that triggers the fold.
        {"index": 2, "name": "SB-2", "geometry": mapping(
            Polygon([(mid_x, 27.0), (84.002, 27.0), (84.002, 27.002), (mid_x, 27.002)])
        )},
    ]

    result = svc.commit_children(
        db, calc, str(parent.id), payload, source="slope", sliver_area_m2=10_000.0,
    )
    assert result["n_children"] == 2

    children = (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == parent.id)
        .order_by(ForestBlock.index)
        .all()
    )
    assert len(children) == 2
    geoms = [to_shape(c.geometry) for c in children]
    # SB-2 absorbed the disjoint east sliver -- it is a real MultiPolygon,
    # persisted as one row (the documented exception to the single-part
    # invariant), not raised as an error and not silently dropped.
    assert any(g.geom_type == "MultiPolygon" for g in geoms), \
        f"expected one child to be a folded MultiPolygon, got {[g.geom_type for g in geoms]}"
    total_ha = sum(c.area_hectares for c in children)
    assert total_ha > 0
