"""RS-2.1 gate: migration ``105_add_raster_dominant_columns`` columns round-trip
through the ORM and survive a split/cut/merge via ``CHILD_INHERITED_COLUMNS``.

The seven columns -- ``dominant_health_class`` / ``dominant_nasa_quality`` /
``dominant_landcover`` / ``dominant_elevation_zone`` and the read-only
``elevation_min_m`` / ``elevation_mean_m`` / ``elevation_max_m`` trio -- are
additive metadata on ``public.forest_blocks``. This proves the *model* half of
RS-2.1 (the migration itself is applied by the conftest harness's
``alembic upgrade head``); inheritance follows the same ``CHILD_INHERITED_COLUMNS``
path as the 084/085 ``dominant_slope_band`` / ``dominant_aspect`` /
``dominant_canopy_class`` columns.
"""
import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon

from app.models.forest_block import CHILD_INHERITED_COLUMNS
from app.models.forest_block import ForestBlock
from app.models.forest_block import child_inherit_kwargs
from app.models.calculation import Calculation
from app.models.user import User, UserRole

NEW_COLUMNS = (
    "dominant_health_class",
    "dominant_nasa_quality",
    "dominant_landcover",
    "dominant_elevation_zone",
    "elevation_min_m",
    "elevation_mean_m",
    "elevation_max_m",
)


def _make_user(db, email=None):
    user = User(
        email=email or f"rs21{uuid.uuid4().hex[:8]}@test.com",
        full_name="RS-2.1 Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db):
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=_make_user(db).id,
        uploaded_filename="rs21-test.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    return calc


def _add_block(db, calc, parent=None, name="Block-1"):
    geom = Polygon([(0.0, 0.0), (0.01, 0.0), (0.01, 0.01), (0.0, 0.01)])
    block = ForestBlock(
        calculation_id=calc.id,
        parent_block_id=parent.id if parent is not None else None,
        name=name,
        block_name=name,
        geometry=from_shape(geom, srid=4326),
        area_hectares=1.0,
        area_sqm=10000.0,
        index=0,
        is_compartment=parent is not None,
        division_level=1 if parent is None else parent.division_level + 1,
        is_locked=False,
        child_count=0,
    )
    db.add(block)
    db.flush()
    return block


def test_new_raster_columns_are_registered_for_child_inheritance(db):
    for col in NEW_COLUMNS:
        assert col in CHILD_INHERITED_COLUMNS, f"{col} missing from CHILD_INHERITED_COLUMNS"


def test_raster_columns_round_trip_through_the_orm(db):
    calc = _make_calc(db)
    block = _add_block(db, calc)
    block.dominant_health_class = 4
    block.dominant_nasa_quality = 2
    block.dominant_landcover = 50
    block.dominant_elevation_zone = 3
    block.elevation_min_m = 721.5
    block.elevation_mean_m = 1042.3
    block.elevation_max_m = 1568.0
    db.commit()
    db.expire_all()

    row = db.query(ForestBlock).filter(ForestBlock.id == block.id).one()
    assert row.dominant_health_class == 4
    assert row.dominant_nasa_quality == 2
    assert row.dominant_landcover == 50
    assert row.dominant_elevation_zone == 3
    assert float(row.elevation_min_m) == 721.5
    assert float(row.elevation_mean_m) == 1042.3
    assert float(row.elevation_max_m) == 1568.0


def test_a_child_inherits_all_seven_raster_columns(db):
    """A split/cut/merge child starts from the parent's values, the same path
    dominant_slope_band / dominant_aspect / dominant_canopy_class already take."""
    calc = _make_calc(db)
    parent = _add_block(db, calc, name="Parent")
    parent.dominant_nasa_quality = 1
    parent.dominant_health_class = 5
    parent.dominant_landcover = 10
    parent.dominant_elevation_zone = 2
    parent.elevation_min_m = 500.0
    parent.elevation_mean_m = 750.0
    parent.elevation_max_m = 1000.0
    db.flush()

    inherited = child_inherit_kwargs(parent)
    # The snapshot is taken before any child exists -- no relationship load.
    assert inherited["dominant_nasa_quality"] == 1
    assert inherited["dominant_health_class"] == 5
    assert inherited["dominant_landcover"] == 10
    assert inherited["dominant_elevation_zone"] == 2
    assert inherited["elevation_min_m"] == 500.0
    assert inherited["elevation_mean_m"] == 750.0
    assert inherited["elevation_max_m"] == 1000.0

    child = _add_block(db, calc, parent=parent, name="Child")
    for col in NEW_COLUMNS:
        assert getattr(child, col) is None, f"{col} should start NULL before kwargs"
    for key, value in inherited.items():
        setattr(child, key, value)
    db.flush()

    assert child.dominant_nasa_quality == 1
    assert child.elevation_min_m == 500.0


def test_compartment_tree_carries_all_seven_raster_fields(client, db, auth_headers):
    """RS-2.2: the compartment-tree node surfaces all seven migration-105
    fields, not just the pre-existing 084/085 dominant_* columns."""
    user = db.query(User).filter(User.email == "testuser@example.com").one()
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    block = _add_block(db, calc)
    block.is_compartment = True
    block.dominant_health_class = 4
    block.dominant_nasa_quality = 2
    block.dominant_landcover = 50
    block.dominant_elevation_zone = 3
    block.elevation_min_m = 721.5
    block.elevation_mean_m = 1042.3
    block.elevation_max_m = 1568.0
    db.commit()

    tree = client.get(
        f"/api/compartments/calculations/{calc.id}/compartment-tree",
        headers=auth_headers,
    ).json()
    nodes = tree["blocks"]
    assert len(nodes) == 1
    node = nodes[0]
    assert node["dominant_health_class"] == 4
    assert node["dominant_nasa_quality"] == 2
    assert node["dominant_landcover"] == 50
    assert node["dominant_elevation_zone"] == 3
    assert node["elevation_min_m"] == 721.5
    assert node["elevation_mean_m"] == 1042.3
    assert node["elevation_max_m"] == 1568.0