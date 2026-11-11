"""Compartment / sub-compartment hybrid divide service tests (plan COMPARTMENT_REWIRE, A.1).

Covers: child-persist under parent, division_level, naming pattern, split history
record, once-only + sampling-mutex + lock guards, and the 1-ha minimum piece floor.
"""
import asyncio
import uuid

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Polygon

from app.models.calculation import Calculation
from app.models.compartment import CompartmentSplitHistory
from app.models.forest_block import ForestBlock
from app.models.sampling import SamplingDesign
from app.models.user import User, UserRole
from app.services import compartment_divide_service as svc
from app.services.geometry_edit_service import area_sqm, next_block_index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _square(x, y, size=0.01):
    """~1 ha at equator scale (0.01° ≈ 1112 m)."""
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def _big_square(size=0.05):
    """~31 ha — big enough to split into 2 pieces above the 1-ha floor."""
    return _square(0.0, 0.0, size)


def _make_user(db, email=None):
    user = User(
        email=email or f"cd{uuid.uuid4().hex[:8]}@test.com",
        full_name="Divide Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db, user=None):
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=(user or _make_user(db)).id,
        uploaded_filename="divide-test.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    return calc


def _add_block(db, calc, geom, name="Block-1", is_comp=False, level=1):
    block = ForestBlock(
        calculation_id=calc.id,
        name=name,
        block_name=name,
        geometry=from_shape(geom, srid=4326),
        area_hectares=round(area_sqm(geom) / 10000.0, 4),
        area_sqm=round(area_sqm(geom), 2),
        index=next_block_index(db, str(calc.id)),
        is_compartment=is_comp,
        division_level=level,
        is_locked=False,
        child_count=0,
    )
    db.add(block)
    db.flush()
    return block


def _children(db, calc, level):
    return (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.is_compartment.is_(True),
            ForestBlock.division_level == level,
        )
        .order_by(ForestBlock.display_order)
        .all()
    )


def _comp_total_ha(db, calc):
    rows = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.is_compartment.is_(True),
            ForestBlock.division_level == 1,
        )
        .all()
    )
    return sum(area_sqm(to_shape(r.geometry)) / 10000.0 for r in rows if r.geometry)


def _divide(db, calc, layer_type, parent_id, **kwargs):
    kwargs.setdefault("reassign_trees", False)
    kwargs.setdefault("naming_pattern", "")
    return asyncio.run(svc.divide_compartment(
        db, calc, parent_id, layer_type,
        method=kwargs.pop("method", "strips"),
        n=kwargs.pop("n", None),
        rows=kwargs.pop("rows", None),
        cols=kwargs.pop("cols", None),
        direction=kwargs.pop("direction", "vertical"),
        direction_angle=kwargs.pop("direction_angle", None),
        naming_pattern=kwargs.pop("naming_pattern", ""),
        reassign_trees=kwargs.pop("reassign_trees", False),
        notes=kwargs.pop("notes", None),
        created_by=kwargs.pop("created_by", calc.user_id),
    ))


# ---------------------------------------------------------------------------
# Compartments (division_level 1)
# ---------------------------------------------------------------------------

def test_divide_compartment_creates_children_under_parent(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(), name="ForestBlock")
    result = _divide(db, calc, "compartments", block.id, n=2)

    children = _children(db, calc, 1)
    assert len(children) == 2
    assert result["n_children"] == 2
    for child in children:
        assert child.parent_block_id == block.id
        assert child.is_compartment is True
        assert child.division_level == 1
        assert child.block_name.startswith("ForestBlock-C")
    # parent preserved
    block2 = db.query(ForestBlock).filter(ForestBlock.id == block.id).first()
    assert block2 is not None
    assert _comp_total_ha(db, calc) == pytest.approx(area_sqm(to_shape(block.geometry)) / 10000.0, rel=1e-6)


def test_divide_compartment_children_inherit_auto_block_classification(db):
    """Carving fresh compartments from a block that carries an Auto-Block
    source classification (dominant_slope_band/aspect/canopy_class) must
    give every child the SAME value — dividing changes geometry only, it
    does not reclassify."""
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(), name="ForestBlock")
    block.dominant_slope_band = 3
    db.flush()
    _divide(db, calc, "compartments", block.id, n=2)

    children = _children(db, calc, 1)
    assert len(children) == 2
    for child in children:
        assert child.dominant_slope_band == 3
        assert child.dominant_aspect is None
        assert child.dominant_canopy_class is None


def test_divide_compartment_writes_history(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square())
    result = _divide(db, calc, "compartments", block.id, n=2, notes="note1")

    hist = db.query(CompartmentSplitHistory).filter(
        CompartmentSplitHistory.id == result["split_history_id"]
    ).first()
    assert hist is not None
    assert hist.parent_block_id == block.id
    assert hist.split_method == "strips"
    assert hist.number_of_compartments == 2
    assert hist.notes == "note1"


def test_divide_compartment_grid_uses_rows_cols(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(size=0.08))
    result = _divide(db, calc, "compartments", block.id, method="grid", rows=2, cols=2)
    assert result["n_children"] == 4


def test_divide_compartment_rejects_non_block_parent(db):
    calc = _make_calc(db)
    comp = _add_block(db, calc, _big_square(), is_comp=True, level=1)
    with pytest.raises(ValueError, match="forest blocks"):
        _divide(db, calc, "compartments", comp.id, n=2)


def test_every_block_can_own_compartments(db):
    """FS-4a.5: the old calc-wide ``_check_once_only`` restriction ("at most ONE
    block in the calculation may own a compartment set") is gone -- a legacy
    chain-model rule with no meaning once compartments never nest under a block
    (D6/D1). Matches ``auto_block_service``'s own precedent
    (``test_every_block_can_own_compartments`` for the natural-feature divide,
    which already carried this exact removal)."""
    calc = _make_calc(db)
    b1 = _add_block(db, calc, _big_square(), name="B1")
    b2 = _add_block(db, calc, _big_square(size=0.04), name="B2")
    r1 = _divide(db, calc, "compartments", b1.id, n=2)
    r2 = _divide(db, calc, "compartments", b2.id, n=2)
    assert len(r1["children"]) == 2
    assert len(r2["children"]) == 2


def test_dividing_the_same_parent_twice_is_still_refused(db):
    """What the old rule's SAME-parent case protected against still holds: a
    second divide on a parent that already has children would stack a second
    generation on top of the first, silently orphaning it."""
    calc = _make_calc(db)
    b1 = _add_block(db, calc, _big_square(), name="B1")
    _divide(db, calc, "compartments", b1.id, n=2)
    with pytest.raises(ValueError, match="already has sub-divisions"):
        _divide(db, calc, "compartments", b1.id, n=2)


def test_sampling_mutex_rejects_divide(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square())
    db.add(SamplingDesign(calculation_id=calc.id, sampling_type="systematic"))
    db.flush()
    with pytest.raises(ValueError, match="sampling designs"):
        _divide(db, calc, "compartments", block.id, n=2)


# ---------------------------------------------------------------------------
# Sub-compartments (division_level+1)
# ---------------------------------------------------------------------------

def test_divide_sub_compartment_level_two(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(size=0.09), name="ForestBlock")
    _divide(db, calc, "compartments", block.id, method="grid", rows=2, cols=1)
    parent = _children(db, calc, 1)[0]
    parent_name = parent.block_name

    result = _divide(db, calc, "sub_compartments", parent.id, n=2)
    subs = _children(db, calc, 2)
    assert len(subs) == 2
    assert subs[0].division_level == 2
    assert subs[0].parent_block_id == parent.id
    assert subs[0].block_name.startswith(parent_name + "-SC")


def test_divide_sub_compartment_rejects_non_compartment(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square())
    with pytest.raises(ValueError, match="Can only sub-divide compartments"):
        _divide(db, calc, "sub_compartments", block.id, n=2)


def test_divide_sub_compartment_locked_rejected(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(size=0.09))
    _divide(db, calc, "compartments", block.id, method="grid", rows=2, cols=1)
    parent = _children(db, calc, 1)[0]
    parent.is_locked = True
    db.flush()
    with pytest.raises(ValueError, match="locked"):
        _divide(db, calc, "sub_compartments", parent.id, n=2)


# ---------------------------------------------------------------------------
# Piece validity / floor
# ---------------------------------------------------------------------------

def test_tolerance_violation_rejected(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(size=0.001))  # ~1.2 ha
    with pytest.raises(ValueError, match="[Ee]qual-area division violates"):
        _divide(db, calc, "compartments", block.id, n=2)


def test_min_area_floor_respected(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(size=0.02))  # ~5 ha → 2 pieces ~2.5 ha each
    result = _divide(db, calc, "compartments", block.id, n=2)
    assert result["n_children"] == 2


# ---------------------------------------------------------------------------
# Preview (dry-run, labelled pieces)
# ---------------------------------------------------------------------------

def _preview(db, calc, layer_type, parent_id, **kwargs):
    return asyncio.run(svc.preview_divide_compartment(
        db, calc, parent_id, layer_type,
        method=kwargs.pop("method", "strips"),
        n=kwargs.pop("n", None),
        rows=kwargs.pop("rows", None),
        cols=kwargs.pop("cols", None),
        direction=kwargs.pop("direction", "vertical"),
        direction_angle=kwargs.pop("direction_angle", None),
        naming_pattern=kwargs.pop("naming_pattern", ""),
    ))


def test_preview_no_persist_and_labelled(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(), name="ForestBlock")
    result = _preview(db, calc, "compartments", block.id, n=2)
    assert result["success"] is True
    assert len(result["pieces"]) == 2
    for piece in result["pieces"]:
        assert piece["name"].startswith("ForestBlock-C")
        assert "area_hectares" in piece
        assert "geometry" in piece
    # no children persisted
    children = _children(db, calc, 1)
    assert len(children) == 0


def test_preview_sub_compartment_default_name(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(size=0.09), name="ForestBlock")
    _divide(db, calc, "compartments", block.id, method="grid", rows=2, cols=1)
    parent = _children(db, calc, 1)[0]
    result = _preview(db, calc, "sub_compartments", parent.id, n=2)
    assert result["success"] is True
    assert result["pieces"][0]["name"].startswith(parent.block_name + "-SC")


def test_preview_grid_equal_area_on_irregular(db):
    """Equal-area grid (rows strips → cols strips) yields equal cells even on an
    irregular L-shape — must NOT hit TOLERANCE_EXCEEDED (was a plain cell-clipping
    grid that produced unequal cells and failed ±5%)."""
    calc = _make_calc(db)
    outer = _square(0.0, 0.0, 0.05)
    notch = Polygon([(0.0, 0.0), (0.02, 0.0), (0.02, 0.02), (0.0, 0.02)])
    block = _add_block(db, calc, outer.difference(notch), name="Irregular")
    result = _preview(db, calc, "compartments", block.id, method="grid", rows=2, cols=4)
    assert result["success"] is True, result["warnings"]
    assert len(result["pieces"]) == 8
    areas = [p["area_hectares"] for p in result["pieces"]]
    assert (max(areas) - min(areas)) / max(areas) < 0.01  # within 1%, not just the ±5% gate


def test_preview_too_few_pieces_reason(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square())
    result = _preview(db, calc, "compartments", block.id, n=1)  # 1 strip → 1 piece
    assert result["success"] is False
    assert result["reason"] == "TOO_FEW_PIECES"


def test_divide_with_custom_angle(db):
    """Direction in degrees (legacy 0=N-S, 90=E-W) produces equal pieces + history records the angle."""
    calc = _make_calc(db)
    block = _add_block(db, calc, _big_square(), name="ForestBlock")
    preview = _preview(db, calc, "compartments", block.id, n=2, direction_angle=30.0)
    assert preview["success"] is True
    assert len(preview["pieces"]) == 2
    result = _divide(db, calc, "compartments", block.id, n=2, direction_angle=30.0)
    assert result
    children = _children(db, calc, 1)
    assert len(children) == 2
    hist = db.query(CompartmentSplitHistory).filter(
        CompartmentSplitHistory.calculation_id == calc.id
    ).first()
    assert hist.split_direction == 30.0


def test_preview_angle_equals_strips_equal_area(db):
    """Angle preview reports tolerance success on a shape where grid fails — angle rescues irregular blocks."""
    calc = _make_calc(db)
    outer = _square(0.0, 0.0, 0.05)
    notch = Polygon([(0.0, 0.0), (0.02, 0.0), (0.02, 0.02), (0.0, 0.02)])
    block = _add_block(db, calc, outer.difference(notch), name="Irregular")
    result = _preview(db, calc, "compartments", block.id, n=2, direction_angle=45.0)
    assert result["success"] is True
    assert len(result["pieces"]) == 2