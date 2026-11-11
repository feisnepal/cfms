"""Deleting a forest deletes ALL of its data -- rows and files (work package FD, FD-7).

Owner's rule, 2026-09-21 (replaces the 2026-08-27 "archive, never destroy" rule):
if a forest is deleted, every piece of data associated with it must be deleted.

Why this test is written the way it is
--------------------------------------
77,560 trees once outlived the forests they belonged to, because two foreign keys were
``ON DELETE SET NULL``. A test that checks a hand-kept list of tables would have missed that, and
would miss the next table someone adds. So this test does not list tables. It:

1. builds a forest with data in the tables that matter (units, inventory + trees + correction log,
   field inventory + plot + measurement + summary, sampling design, cache row, and the per-forest
   folders on disk);
2. **walks the live foreign-key graph** from that forest -- children, grandchildren, and so on --
   and records the primary key of every row that hangs off it;
3. deletes the forest through the API;
4. asserts that **not one** of those rows survives, that no per-forest folder remains, and that a
   second forest with its own data is untouched.

A table added tomorrow with a non-cascading link is caught by step 4 without anyone updating this
file. The schema half of the rule lives in ``test_forest_delete_schema_rule.py``.

Never point this at a real forest: it creates and deletes its own scratch forests in the test database.
"""

from __future__ import annotations

import os
import shutil
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.field_inventory import (
    FieldInventoryBlockSummary,
    FieldInventoryCalculation,
    FieldInventoryMeasurement,
    FieldInventorySamplePlot,
)
from app.models.forest_block import ForestBlock
from app.models.inventory import InventoryCalculation, TreeCorrectionLog
from app.models.sampling import SamplingDesign
from app.services.forest_purge import forest_folders_on_disk

# Tables that carry a forest id on purpose (see app/core/forest_delete_rules.py).
from app.core.forest_delete_rules import FOREST_DELETE_EXCEPTIONS


def _login(client, db):
    from app.models.user import User

    email = f"purge-{uuid.uuid4().hex[:10]}@example.com"
    client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "TestPass123!",
            "full_name": "Purge Tester",
        },
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _seed_forest(db, user, name):
    """A scratch forest with data in the tables that matter, plus files on disk."""
    forest = Calculation(user_id=user.id, forest_name=name)
    forest.map_lifecycle_status = "draft"
    db.add(forest)
    db.flush()

    for i, geom in enumerate(
        (box(84.0, 28.0, 84.02, 28.02), box(84.02, 28.0, 84.04, 28.02))
    ):
        db.add(
            ForestBlock(
                calculation_id=forest.id,
                name=f"Block-{i + 1}",
                block_name=f"Block-{i + 1}",
                geometry=shp_wkt.dumps(geom),
                area_hectares=100.0,
                index=i,
                division_level=1,
                is_compartment=False,
            )
        )

    inv = InventoryCalculation(
        user_id=user.id,
        calculation_id=forest.id,
        uploaded_filename="trees.csv",
        status="completed",
    )
    db.add(inv)
    db.flush()
    for k in range(3):
        db.execute(
            text(
                "INSERT INTO public.inventory_trees (id, inventory_calculation_id, species, dia_cm, location) "
                "VALUES (:id, :inv, 'Shorea robusta', :dia, ST_GeomFromText(:loc, 4326))"
            ),
            {
                "id": str(uuid.uuid4()),
                "inv": str(inv.id),
                "dia": 20.0 + k,
                "loc": f"POINT({84.0 + k / 1000} 28.0)",
            },
        )
    db.add(
        TreeCorrectionLog(
            inventory_calculation_id=inv.id,
            tree_row_number=1,
            original_x=84.0,
            original_y=28.0,
            corrected_x=84.001,
            corrected_y=28.001,
            distance_moved_meters=5.0,
            correction_reason="out_of_boundary",
        )
    )

    fi = FieldInventoryCalculation(
        user_id=user.id,
        calculation_id=forest.id,
        uploaded_filename="fi.csv",
        status="completed",
    )
    db.add(fi)
    db.flush()
    plot = FieldInventorySamplePlot(
        field_inventory_calculation_id=fi.id,
        block_name="Block-1",
        sample_plot_number=1,
        location="SRID=4326;POINT(84.01 28.01)",
    )
    db.add(plot)
    db.flush()
    db.add(
        FieldInventoryMeasurement(
            sample_plot_id=plot.id,
            stand_type="Tree",
            sn=1,
            species_scientific="Shorea robusta",
            dbh_cm=30,
            height_m=18,
            count=1,
            net_volume=1.0,
            gross_volume=1.0,
            basal_area_m2=0.07,
            firewood_m3=0,
        )
    )
    db.add(
        FieldInventoryBlockSummary(
            field_inventory_calculation_id=fi.id,
            block_name="Block-1",
            total_sample_plots=1,
            total_growing_stock_m3_per_ha=80.0,
            forest_condition="Moderate",
            mai_percent=3.0,
        )
    )

    db.add(SamplingDesign(calculation_id=forest.id, sampling_type="systematic"))
    db.commit()
    # The cache model deletes its own row whenever another model of the forest changes (an
    # after_flush hook), so it is inserted last and directly, after everything else is committed.
    db.execute(
        text(
            "INSERT INTO public.op_data_cache (calculation_id, data) VALUES (:c, '{\"seeded\": true}'::jsonb)"
        ),
        {"c": str(forest.id)},
    )
    db.commit()
    return forest


def _make_folders(forest_id):
    """Create the per-forest cache folders (with a file in each) and return their paths."""
    from app.services.management_plan_docx.plan_map_service import MAP_CACHE_DIR
    from app.services.operational_plan.landslide_susceptibility import (
        _CACHE_ROOT as HAZARD_ROOT,
    )
    from app.services.operational_plan.soil_erosion import _CACHE_ROOT as SOIL_ROOT

    paths = [
        os.path.join(MAP_CACHE_DIR, str(forest_id)),
        str(SOIL_ROOT / str(forest_id)),
        str(HAZARD_ROOT / str(forest_id)),
    ]
    for p in paths:
        os.makedirs(p, exist_ok=True)
        with open(os.path.join(p, "cache.bin"), "wb") as fh:
            fh.write(b"x")
    return paths


# --- walking the foreign-key graph ----------------------------------------------------------------


def _foreign_keys(db):
    """[(child_table, child_col, parent_table)] for every single-column FK in `public`."""
    rows = db.execute(
        text(
            """
        SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1
          AND c.connamespace = 'public'::regnamespace
    """
        )
    ).fetchall()
    return [
        (r[0].replace("public.", ""), r[1], r[2].replace("public.", "")) for r in rows
    ]


def _primary_keys(db):
    """{table: pk_column} for tables with a single-column primary key."""
    rows = db.execute(
        text(
            """
        SELECT tc.table_name, min(kcu.column_name)
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
        GROUP BY tc.table_name HAVING count(*) = 1
    """
        )
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def rows_hanging_off(db, forest_id):
    """{table: {pk as text}} -- every row reachable from the forest by following foreign keys down."""
    fks, pks = _foreign_keys(db), _primary_keys(db)
    found = {"calculations": {str(forest_id)}}
    changed = True
    while changed:
        changed = False
        for child, col, parent in fks:
            if parent not in found or child not in pks:
                continue
            pk = pks[child]
            got = db.execute(
                text(
                    f'SELECT "{pk}"::text FROM public."{child}" WHERE "{col}"::text = ANY(:ids)'
                ),
                {"ids": list(found[parent])},
            ).fetchall()
            new = {r[0] for r in got} - found.get(child, set())
            if new:
                found.setdefault(child, set()).update(new)
                changed = True
    return found


def _survivors(db, found):
    """{table: count} of the recorded rows that still exist."""
    pks = _primary_keys(db)
    alive = {}
    for table, ids in found.items():
        n = db.execute(
            text(
                f'SELECT count(*) FROM public."{table}" WHERE "{pks[table]}"::text = ANY(:ids)'
            ),
            {"ids": list(ids)},
        ).scalar()
        if n:
            alive[table] = n
    return alive


# --- the tests ------------------------------------------------------------------------------------


def test_deleting_a_forest_deletes_every_row_and_file_that_belonged_to_it(client, db):
    headers, user = _login(client, db)
    doomed = _seed_forest(db, user, f"Scratch doomed {uuid.uuid4().hex[:6]}")
    bystander = _seed_forest(db, user, f"Scratch bystander {uuid.uuid4().hex[:6]}")
    doomed_id, bystander_id = str(doomed.id), str(bystander.id)
    folders = _make_folders(doomed_id) + _make_folders(bystander_id)

    try:
        found = rows_hanging_off(db, doomed_id)
        # the seed really reached the tables that matter, including grandchildren of the forest
        for table in (
            "forest_blocks",
            "inventory_calculations",
            "inventory_trees",
            "tree_correction_logs",
            "field_inventory_calculations",
            "field_inventory_sample_plots",
            "field_inventory_measurements",
            "field_inventory_block_summary",
            "sampling_designs",
            "op_data_cache",
        ):
            assert found.get(table), f"the test seed put nothing in {table}"
        bystander_before = rows_hanging_off(db, bystander_id)

        resp = client.delete(f"/api/forests/calculations/{doomed_id}", headers=headers)
        assert resp.status_code == 204, resp.text
        db.expire_all()

        # 1. not one row that hung off the forest survives -- children and grandchildren alike
        assert _survivors(db, found) == {}, "rows of a deleted forest were left behind"

        # 2. no per-forest folder on disk remains
        assert forest_folders_on_disk(doomed_id) == []

        # 3. tables that carry a forest id but have no foreign key hold nothing for it, except the
        #    documented exceptions
        for (table,) in db.execute(
            text(
                "SELECT DISTINCT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'calculation_id'"
            )
        ).fetchall():
            if table in FOREST_DELETE_EXCEPTIONS:
                continue
            n = db.execute(
                text(
                    f'SELECT count(*) FROM public."{table}" WHERE calculation_id::text = :c'
                ),
                {"c": doomed_id},
            ).scalar()
            assert n == 0, f"{table} still holds {n} row(s) of the deleted forest"

        # 4. nothing was archived -- the archive table itself no longer exists (migration 093)
        assert (
            db.execute(text("SELECT to_regclass('public.deleted_calculations')")).scalar()
            is None
        )

        # 5. the other forest is completely untouched
        assert _survivors(db, bystander_before) == {
            t: len(v) for t, v in bystander_before.items()
        }
        assert forest_folders_on_disk(
            bystander_id
        ), "the other forest's folders were removed"
    finally:
        for p in folders:
            shutil.rmtree(p, ignore_errors=True)
        # scratch data of the bystander forest lives in the disposable test database


def test_an_inventory_cannot_be_left_without_a_forest(db):
    """The two links that used to leak are now NOT NULL, so a forest-less inventory cannot exist."""
    for table in ("inventory_calculations", "field_inventory_calculations"):
        nullable = db.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = 'calculation_id'"
            ),
            {"t": table},
        ).scalar()
        assert nullable == "NO", f"{table}.calculation_id must be NOT NULL"
