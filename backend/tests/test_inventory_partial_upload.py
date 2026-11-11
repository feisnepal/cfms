"""One bad row must not delete the whole upload (H8.3 / S3-66).

`InventoryService._store_trees_simple` built one `InventoryTree` per row inside
a single `try` with no per-row guard. A value that would not parse as a float
anywhere in the file raised out of the loop, and the caller responded to that
exception by deleting the entire `InventoryCalculation` -- cascading away every
tree already inserted from earlier batches in the same upload. Uploading 5,000
trees where row 4,999 has a typo destroyed all 5,000.

This is the same shape S3-66 describes for a device syncing field records --
one bad record rejecting a whole batch -- realised through the confirmed real
data-entry path (CSV/Excel/GPKG upload) rather than a JSON bulk-array endpoint.
"""
from __future__ import annotations

import uuid

import pandas as pd
import pytest

from app.middleware.rate_limit import import_limiter
from app.models.inventory import InventoryCalculation, InventoryTree
from app.services.inventory import InventoryService

REQUIRED_COLUMNS = [
    "stem_volume", "branch_volume", "tree_volume", "gross_volume",
    "net_volume", "net_volume_cft", "firewood_m3", "firewood_chatta",
    "remark", "grid_cell_id",
]


def _row(dia_cm="30.5", lon=84.1, lat=28.2, remark=None, tree_class=None):
    row = {
        "species": "Shorea robusta", "dia_cm": dia_cm, "height_m": 12.0,
        "tree_class": tree_class, "longitude": lon, "latitude": lat,
    }
    for col in REQUIRED_COLUMNS:
        row[col] = 0.0 if col not in ("remark", "grid_cell_id") else None
    row["remark"] = remark
    return row


@pytest.fixture()
def owner(db):
    from app.models.user import User

    user = User(
        email=f"h83-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash", full_name="H8.3 Fixture",
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def inventory_run(db, owner):
    from app.models.calculation import Calculation

    # an inventory belongs to a forest (owner's rule, 2026-09-21; migration 092)
    forest = Calculation(user_id=owner.id, forest_name=f"PU {uuid.uuid4().hex[:6]}")
    db.add(forest)
    db.flush()
    inv = InventoryCalculation(
        user_id=owner.id, uploaded_filename="h8-3-probe.csv",
        needs_compartment_assignment=False, calculation_id=forest.id,
    )
    db.add(inv)
    db.flush()
    return inv


class TestAOneBadRowDoesNotDestroyTheBatch:
    def test_the_good_rows_survive_a_bad_one(self, db, inventory_run):
        """The defect itself, reproduced directly.

        Five good rows and one whose diameter will not parse as a float --
        modelled on the exact failure `_safe_float` raises in production.
        """
        rows = [_row() for _ in range(5)]
        rows.insert(3, _row(dia_cm="not-a-number"))  # row 5 of 6 (1-indexed data)
        df = pd.DataFrame(rows)

        service = InventoryService(db)
        import asyncio

        result = asyncio.run(service._store_trees_simple(
            inventory_run.id, df, "species", "dia_cm", "height_m",
            "tree_class", "longitude", "latitude",
        ))

        assert result["inserted_count"] == 5
        assert len(result["row_errors"]) == 1
        assert "dia_cm" in result["row_errors"][0]["reason"]

        stored = db.query(InventoryTree).filter(
            InventoryTree.inventory_calculation_id == inventory_run.id
        ).count()
        assert stored == 5, "the five good rows must actually be in the database"

    def test_the_bad_rows_reason_names_the_row_and_the_column(self, db, inventory_run):
        """A person fixing the file needs to find the row, not re-read all of it."""
        rows = [_row(), _row(dia_cm="???"), _row()]
        df = pd.DataFrame(rows)
        service = InventoryService(db)
        import asyncio

        result = asyncio.run(service._store_trees_simple(
            inventory_run.id, df, "species", "dia_cm", "height_m",
            "tree_class", "longitude", "latitude",
        ))
        err = result["row_errors"][0]
        assert err["row_number"] == 3  # header=row 1, data starts at row 2
        assert "dia_cm" in err["reason"]

    def test_a_file_that_is_entirely_bad_still_fails(self, db, inventory_run):
        """Not every failure should become a silent partial success. A file
        with nothing usable in it must still be reported as a failure, not
        committed as an inventory of zero trees."""
        rows = [_row(dia_cm="x"), _row(dia_cm="y")]
        df = pd.DataFrame(rows)
        service = InventoryService(db)
        import asyncio

        with pytest.raises(Exception):
            asyncio.run(service._store_trees_simple(
                inventory_run.id, df, "species", "dia_cm", "height_m",
                "tree_class", "longitude", "latitude",
            ))

    def test_the_inventory_calculation_is_not_deleted_on_partial_failure(
        self, db, inventory_run
    ):
        """The severest part of the original defect: `process_inventory_simple`
        deletes the whole `InventoryCalculation` on any exception from the
        store step. With the store step no longer raising for a partial
        failure, the parent record -- and the trees already stored -- survive.
        """
        rows = [_row(), _row(dia_cm="bad"), _row()]
        df = pd.DataFrame(rows)
        service = InventoryService(db)
        import asyncio

        asyncio.run(service._store_trees_simple(
            inventory_run.id, df, "species", "dia_cm", "height_m",
            "tree_class", "longitude", "latitude",
        ))
        db.commit()
        still_there = db.query(InventoryCalculation).filter(
            InventoryCalculation.id == inventory_run.id
        ).first()
        assert still_there is not None


class TestTreeClassAcceptsRomanNumeralsAndLetters:
    """The reported defect: `_store_trees_simple` re-parsed the tree-class
    column with `int(float(class_val))` -- numeric "1"-"4" only, no fallback.
    `calculate_tree_volumes` runs moments earlier on the SAME column and
    already accepts roman numerals ("I"-"IV") and letters ("a"-"d", any
    case), falling back to 'b' rather than raising. A file using either of
    those -- both legitimate, already-supported formats -- had every single
    row raise the identical ValueError at the storage step and get skipped,
    which is indistinguishable from "all 14,239 rows failed to parse; nothing
    was stored" with the whole upload aborted (inserted_count == 0).
    """

    def test_roman_numeral_class_no_longer_fails_every_row(self, db, inventory_run):
        rows = [_row(tree_class=c) for c in ("I", "II", "III", "IV")]
        df = pd.DataFrame(rows)
        service = InventoryService(db)
        import asyncio

        result = asyncio.run(service._store_trees_simple(
            inventory_run.id, df, "species", "dia_cm", "height_m",
            "tree_class", "longitude", "latitude",
        ))
        assert result["row_errors"] == []
        assert result["inserted_count"] == 4

    def test_letter_class_no_longer_fails_every_row(self, db, inventory_run):
        rows = [_row(tree_class=c) for c in ("a", "B", "c", "D")]
        df = pd.DataFrame(rows)
        service = InventoryService(db)
        import asyncio

        result = asyncio.run(service._store_trees_simple(
            inventory_run.id, df, "species", "dia_cm", "height_m",
            "tree_class", "longitude", "latitude",
        ))
        assert result["row_errors"] == []
        assert result["inserted_count"] == 4

    def test_the_stored_class_is_the_normalized_letter(self, db, inventory_run):
        df = pd.DataFrame([_row(tree_class="II")])
        service = InventoryService(db)
        import asyncio

        asyncio.run(service._store_trees_simple(
            inventory_run.id, df, "species", "dia_cm", "height_m",
            "tree_class", "longitude", "latitude",
        ))
        db.commit()
        stored = db.query(InventoryTree).filter(
            InventoryTree.inventory_calculation_id == inventory_run.id
        ).first()
        assert stored.tree_class == "b"

    def test_an_unrecognized_class_value_falls_back_rather_than_failing(
        self, db, inventory_run
    ):
        """Not every possible typo can be recognized -- the point is that one
        can no longer take the whole batch down (H8.3's own point, applied to
        this column specifically)."""
        df = pd.DataFrame([_row(tree_class="Pole")])
        service = InventoryService(db)
        import asyncio

        result = asyncio.run(service._store_trees_simple(
            inventory_run.id, df, "species", "dia_cm", "height_m",
            "tree_class", "longitude", "latitude",
        ))
        assert result["row_errors"] == []
        assert result["inserted_count"] == 1

    def test_all_rows_failing_now_names_the_actual_reason(self, db, inventory_run):
        """The other half of the report: even when every row genuinely does
        fail, the error must say why, not just how many -- `row_errors` was
        already being collected and then discarded on this path."""
        rows = [_row(dia_cm="not-a-number") for _ in range(5)]
        df = pd.DataFrame(rows)
        service = InventoryService(db)
        import asyncio

        # The inner ValueError is re-wrapped by the method's own
        # `except Exception as e: raise Exception(f"Failed to store trees in
        # database: {e}")` -- assert on the outer type actually raised.
        with pytest.raises(Exception) as exc:
            asyncio.run(service._store_trees_simple(
                inventory_run.id, df, "species", "dia_cm", "height_m",
                "tree_class", "longitude", "latitude",
            ))
        assert "All 5 rows failed to parse" in str(exc.value)
        assert "dia_cm" in str(exc.value)


class TestRowErrorsSurfaceOnTheRecord:
    def test_none_when_every_row_parsed(self):
        """None, not an empty list -- so a client checking `if row_errors`
        does not have to special-case an empty list as "clean"."""
        from app.schemas.inventory import InventoryCalculationResponse

        assert InventoryCalculationResponse.model_fields["row_errors"].default is None

    def test_the_column_exists_on_the_model(self):
        assert "row_errors" in InventoryCalculation.__table__.c


class TestUploadEndpointsAreRateLimited:
    """Source-inspection, in the style of the H7.4 ordering tests: the shape
    that matters is which endpoints call the limiter, not the limiter's own
    mechanics (covered already by `test_rate_limit_identity.py`).

    A large file already costs real processing time on a blocking session
    (S1-17); this is what bounds how often one user can start that.
    """

    def test_inventory_upload_and_process_are_limited(self):
        import inspect

        from app.api import inventory as inventory_api

        assert "import_limiter.check" in inspect.getsource(inventory_api.upload_inventory)
        assert "import_limiter.check" in inspect.getsource(inventory_api.process_inventory)

    def test_field_inventory_upload_and_process_are_limited(self):
        import inspect

        from app.api import field_inventory as field_inventory_api

        assert "import_limiter.check" in inspect.getsource(
            field_inventory_api.upload_field_inventory
        )
        assert "import_limiter.check" in inspect.getsource(
            field_inventory_api.process_field_inventory
        )

    def test_household_upload_is_limited(self):
        import inspect

        from app.api import household_info

        assert "import_limiter.check" in inspect.getsource(
            household_info.upload_household_data
        )

    def test_the_limiter_actually_rejects_a_burst(self):
        """Not just present in source -- functions. Uses the real shared
        `import_limiter` instance the four endpoints above call, at its real
        5/min budget, and resets the probe identity afterward so this test
        cannot poison another test's window.
        """
        probe_user = uuid.uuid4()
        try:
            for _ in range(5):
                import_limiter.check(probe_user)
            with pytest.raises(Exception) as exc:
                import_limiter.check(probe_user)
            assert getattr(exc.value, "http_status", None) == 429
        finally:
            import_limiter.reset(probe_user)


class TestStoreTreesHandlesOptionalAndExtraColumns:
    """The `_store_trees_simple` loop's branch lines (extra-column capture,
    NaN height, nullable polygon_boundary) never ran in the bug-reproduction
    tests above -- their rows carried no extra columns, a valid height, and no
    polygon_boundary. These pin that each optional path really executes.

    These are the lines the diff-coverage gate reported as uncovered; they are
    covered here by real data rather than by source inspection.
    """

    def _build_df(self):
        rows = [
            dict(_row(), extra_num=3.5, extra_nan=float("nan"), extra_pure=5,
                 polygon_boundary="P001"),
            dict(_row(), height_m=float("nan"), polygon_boundary=float("nan"),
                 extra_pure=5),
            dict(_row(), polygon_boundary="P002", extra_pure=5),
        ]
        return pd.DataFrame(rows)

    def test_extra_columns_and_nullable_fields_are_stored(self, db, inventory_run):
        import asyncio

        df = self._build_df()
        service = InventoryService(db)
        result = asyncio.run(service._store_trees_simple(
            inventory_run.id, df, "species", "dia_cm", "height_m",
            "tree_class", "longitude", "latitude",
        ))

        assert result["inserted_count"] == 3
        assert result["row_errors"] == []

        stored = db.query(InventoryTree).filter(
            InventoryTree.inventory_calculation_id == inventory_run.id
        ).order_by(InventoryTree.row_number).all()
        assert len(stored) == 3

        first, second, third = stored
        # Row 1: an extra numeric column is preserved as a Python float via
        # numpy .item(), a NaN extra column is stored as None (not dropped),
        # and polygon_boundary is turned into the tree's block_name string.
        assert first.extra_columns["extra_num"] == 3.5
        assert first.extra_columns["extra_nan"] is None
        assert first.block_name == "P001"
        assert first.height_m is not None

        # Row 2: a NaN height becomes None, and a NaN polygon_boundary no
        # longer reaches the string cast (which would have produced "nan").
        assert second.height_m is None
        assert second.block_name is None

        # Row 3: the non-None string branch writes block_name again.
        assert third.block_name == "P002"
