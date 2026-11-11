"""The dimension-exclusivity DB trigger, narrowed in migration 095 (F9/V1, FS-1d.9).

Before 095, ``check_dimension_exclusivity()`` rejected EVERY compartment INSERT once the
forest had any ``sampling_designs`` row -- including a forest already on the compartment
stream simply adding one more (चुरे's real situation: reproduced 2026-09-21). Migration 095
narrows the check to fire only when the forest has **no compartment yet** -- i.e. this
INSERT would be the one establishing the compartment stream for the first time, which is
still exactly the scenario the trigger exists to guard.
"""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy.exc import DBAPIError

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.sampling import SamplingDesign

from . import fixtures


def _calc(db, forest):
    return db.query(Calculation).filter(Calculation.id == forest.calc_id).first()


def _new_compartment(calc_id, geom: Polygon, name: str) -> ForestBlock:
    return ForestBlock(
        calculation_id=calc_id,
        name=name,
        geometry=from_shape(geom, srid=4326),
        area_hectares=1.0,
        area_sqm=10000.0,
        index=99,
        is_compartment=True,
        division_level=1,
    )


def test_a_compartment_forest_with_sampling_can_still_add_a_compartment(db, make_forest):
    """The fix: चुरे's real situation. F2 already has 3 parentless compartments."""
    f = make_forest("F2")
    calc = _calc(db, f)
    db.add(SamplingDesign(calculation_id=calc.id, sampling_type="systematic"))
    db.flush()

    new_geom = fixtures.rect(30, 0, 40, 10)  # a fresh strip beside F2's existing units
    db.add(_new_compartment(calc.id, new_geom, f"{uuid.uuid4().hex[:6]}-extra"))
    db.flush()  # must NOT raise

    count = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc.id, ForestBlock.is_compartment.is_(True))
        .count()
    )
    assert count == 4


def test_a_block_forest_with_sampling_still_cannot_start_a_compartment_set(db, make_forest):
    """The guard's real purpose, preserved: a BLOCK forest with sampling may not be
    converted into a compartment forest out from under it -- no compartment exists yet,
    so the narrowed trigger still fires."""
    f = make_forest("F1")
    calc = _calc(db, f)
    db.add(SamplingDesign(calculation_id=calc.id, sampling_type="systematic"))
    db.flush()

    new_geom = fixtures.rect(0, 0, 5, 5)
    db.add(_new_compartment(calc.id, new_geom, "first-compartment"))
    try:
        db.flush()
        raised = False
    except DBAPIError as exc:
        # The trigger's RAISE EXCEPTION surfaces as a generic psycopg2 InternalError
        # (SQLSTATE P0001), not a constraint IntegrityError -- confirm it is really
        # this guard and not some other DB error before treating it as a pass.
        raised = "block-level sampling designs" in str(exc)
    db.rollback()
    assert raised, "the first compartment on a sampled block forest must still be rejected"
