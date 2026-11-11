"""persist_boundary — no unit is auto-created from a boundary write.

FS-2.4 / FS-2.8 + C1-C3 / Q5 ("no automatic single block for a new forest"):
a boundary write is a boundary write. The first unit is the user's explicit
choice (createSingleBlock / whole-forest auto-create / root-divide) — the
service never silently mints a block, no matter how many times the boundary
is (re)saved.
"""
import uuid

from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services.boundary_write_service import persist_boundary


def _make_user(db):
    user = User(
        email=f"bws{uuid.uuid4().hex[:8]}@test.com",
        full_name="Boundary Write Service Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db, blocks_cleared_by_user=False):
    user = _make_user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="bws-test.csv",
        is_draft=False,
        structure_locked=False,
        blocks_cleared_by_user=blocks_cleared_by_user,
    )
    db.add(calc)
    db.flush()
    return calc


def _n_blocks(db, calc):
    return (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.is_compartment != True,  # noqa: E712
            ForestBlock.division_level == 1,
        )
        .count()
    )


def test_persist_boundary_never_auto_creates_a_unit(db):
    """A boundary write on a unit-less forest mints nothing — the boundary
    stands alone until the user explicitly creates a unit."""
    calc = _make_calc(db, blocks_cleared_by_user=False)
    poly = box(80.0, 27.0, 80.01, 27.01)

    result = persist_boundary(db, calc, poly, clip_against_neighbours=False)
    db.commit()

    assert "single_block_created" not in result
    assert _n_blocks(db, calc) == 0


def test_persist_boundary_never_mints_on_repeated_saves(db):
    """Repeated edit/save cycles must not resurrect a unit on a unit-less
    forest — the flag is irrelevant now, the mint is gone entirely."""
    calc = _make_calc(db, blocks_cleared_by_user=False)
    poly_a = box(80.0, 27.0, 80.01, 27.01)
    poly_b = box(80.0, 27.0, 80.02, 27.02)

    persist_boundary(db, calc, poly_a, clip_against_neighbours=False)
    db.commit()
    assert _n_blocks(db, calc) == 0

    persist_boundary(db, calc, poly_b, clip_against_neighbours=False)
    db.commit()
    assert _n_blocks(db, calc) == 0


def test_persist_boundary_cleared_flag_is_equally_noop(db):
    """blocks_cleared_by_user no longer gates anything (there is nothing to
    gate) — kept for schema stability until P6 drops the column."""
    calc = _make_calc(db, blocks_cleared_by_user=True)
    poly = box(80.0, 27.0, 80.01, 27.01)

    result = persist_boundary(db, calc, poly, clip_against_neighbours=False)
    db.commit()

    assert "single_block_created" not in result
    assert _n_blocks(db, calc) == 0