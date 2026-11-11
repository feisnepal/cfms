"""Satellite volume must find geometry on either forest stream.

The bug this guards
-------------------
`satellite_volume_m3_per_ha` was NULL for **every row in the table** (0 of 26) and
the UI showed an empty column with no error anywhere. The AGB raster it depends
on was present and working throughout -- 4,186 tiles.

The cause was a geometry lookup that read `calculations.result_data->'blocks'`
and expected a `wkt` key. It was wrong twice over:

  * On a **compartments** forest, `result_data->'blocks'` is an *empty list* --
    the units live under `result_data->'compartments'` instead. So the lookup
    matched nothing and every unit came back NULL.
  * Where `result_data->'blocks'` *is* populated, entries carry GeoJSON under a
    `geometry` key, not WKT under `wkt`, so `block_json.get("wkt")` was None
    anyway.

Both failures were silent: a missing geometry was a logged warning, and the
column simply rendered empty.

`forest_blocks` is the right source and is what the fix uses. It holds real
PostGIS geometry and carries **both** streams in one table -- a block forest and a
compartment forest both keep their units there, separated by `division_level` and
`parent_block_id`. Resolving a name there works whichever stream the forest uses,
with no branching and no chance of mixing them.

The fixtures below build a **compartments** forest deliberately: empty
`result_data['blocks']`, geometry only in `forest_blocks`. That is the shape that
broke, and a test built on the blocks stream would have passed against the old
code.
"""
from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.user import User
from app.services.field_inventory_service import FieldInventoryService

# A small polygon in the Kathmandu valley, well inside the AGB raster footprint
# so the raster actually answers and the test is not asserting on a NULL.
TEST_POLYGON_WKT = (
    "POLYGON((84.19 27.70, 84.20 27.70, 84.20 27.71, 84.19 27.71, 84.19 27.70))"
)


@pytest.fixture()
def compartment_forest(db):
    """A compartments-stream forest: `result_data['blocks']` is empty.

    Returns `(calculation_id, [unit_name, ...])`.
    """
    user = User(
        email=f"satvol-{uuid.uuid4().hex[:10]}@test.local",
        hashed_password="x",
        full_name="Satellite Volume Test",
    )
    db.add(user)
    db.flush()

    calc = Calculation(
        user_id=user.id,
        uploaded_filename="satellite.csv",
        forest_name="Satellite Volume CF",
        # The whole point: an EMPTY blocks list, as a compartments forest has.
        result_data={"draft": True, "blocks": [], "compartments": [
            {"block_name": n, "geometry": {"type": "Polygon", "coordinates": []}}
            for n in ("A-C1", "A-C2")
        ]},
    )
    db.add(calc)
    db.flush()

    names = ["A-C1", "A-C2", "A-C1-SC1"]
    for i, name in enumerate(names):
        db.execute(
            text(
                # child_count / display_order are set explicitly rather than
                # left to their defaults: production declares defaults for both,
                # the test database does not, and a column that is NOT NULL in
                # one and defaulted in the other is exactly the kind of drift
                # that makes a fixture pass in CI and fail locally.
                "INSERT INTO forest_blocks "
                "(calculation_id, name, geometry, area_hectares, \"index\", "
                " is_compartment, is_locked, child_count, display_order, "
                " working_circle, division_level) "
                "VALUES (CAST(:c AS uuid), :n, "
                "        ST_GeomFromText(:g, 4326), 10.0, :i, true, false, 0, :i, "
                "        'production', :lvl)"
            ),
            {
                "c": str(calc.id),
                "n": name,
                "g": TEST_POLYGON_WKT,
                "i": i,
                # A parent compartment and a sub-compartment: both streams'
                # shapes in one forest, which is what makes the single-table
                # lookup the right answer.
                "lvl": 2 if name.endswith("SC1") else 1,
            },
        )
    db.commit()
    return calc.id, names


class TestGeometryResolution:
    def test_finds_units_that_exist_only_in_forest_blocks(self, db, compartment_forest):
        calc_id, names = compartment_forest
        svc = FieldInventoryService(db)
        for name in names:
            wkt = svc._resolve_unit_geometry_wkt(calc_id, name)
            assert wkt, f"{name} is in forest_blocks but was not resolved"
            assert "POLYGON" in wkt.upper()

    def test_does_not_depend_on_result_data_blocks(self, db, compartment_forest):
        """The regression, stated as an assertion.

        `result_data->'blocks'` is empty for this forest. If the lookup ever goes
        back to reading it, the column goes empty again and nothing raises.
        """
        calc_id, _ = compartment_forest
        blocks_len = db.execute(
            text(
                "SELECT jsonb_array_length(COALESCE(result_data->'blocks', '[]'::jsonb)) "
                "FROM calculations WHERE id = CAST(:c AS uuid)"
            ),
            {"c": str(calc_id)},
        ).scalar()
        assert blocks_len == 0, "fixture must have an empty blocks list to be meaningful"

        svc = FieldInventoryService(db)
        assert svc._resolve_unit_geometry_wkt(calc_id, "A-C1"), (
            "geometry resolved although result_data->'blocks' is empty -- correct. "
            "If this fails, the lookup has gone back to reading result_data."
        )

    def test_resolves_a_sub_compartment_and_its_parent_separately(self, db, compartment_forest):
        """Level 1 and level 2 units coexist; both must resolve.

        Guards against a "fix" that only handles whichever shape it was tested
        against.
        """
        calc_id, _ = compartment_forest
        svc = FieldInventoryService(db)
        parent = svc._resolve_unit_geometry_wkt(calc_id, "A-C1")
        child = svc._resolve_unit_geometry_wkt(calc_id, "A-C1-SC1")
        assert parent and child

    def test_an_unknown_unit_returns_none_and_warns(self, db, compartment_forest):
        """A silent None is how this bug stayed invisible for so long."""
        calc_id, _ = compartment_forest
        svc = FieldInventoryService(db)
        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r.getMessage())
        logger = logging.getLogger('app.services.field_inventory_service')
        logger.addHandler(handler)
        try:
            result = svc._resolve_unit_geometry_wkt(calc_id, 'NO-SUCH-UNIT')
        finally:
            logger.removeHandler(handler)
        assert result is None
        assert any('SATELLITE_VOLUME' in m for m in records), (
            'an unresolved unit must log which calculation and unit it was '
            'looking for, or the next occurrence is undiagnosable'
        )


class TestSatelliteVolume:
    def test_a_compartment_forest_now_produces_a_volume(self, db, compartment_forest):
        """The end-to-end proof: the value that was always NULL.

        Skipped if the AGB raster is not loaded in this database, because the
        geometry resolution -- the thing that was broken -- is asserted above
        without needing the raster.
        """
        calc_id, names = compartment_forest
        has_raster = db.execute(
            text("SELECT to_regclass('rasters.agb_2022_nepal') IS NOT NULL")
        ).scalar()
        if not has_raster:
            pytest.skip("AGB raster not loaded in this database")

        svc = FieldInventoryService(db)
        for name in names:
            volume = svc._calculate_satellite_volume_for_block(calc_id, name)
            assert volume is not None, f"{name} produced no satellite volume"
            assert volume > 0
