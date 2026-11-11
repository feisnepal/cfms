"""The same quantity, stored two ways, now compares equal (H6.2 / S3-16).

The report's claim is specific: a quantity stored as `Float` in one table and
`Numeric` in another cannot be relied upon to compare equal. In this schema that
was not hypothetical -- ten quantities were stored both ways, and both tables
feed the same statutory volume and carbon totals in an operational plan.

The test that carries the task is `TestTheTwinsAgree`: it writes a decimal
figure and asserts it comes back identical, with no tolerance. Before migration
060 it fails on the very first value, 0.1, which binary floating point cannot
represent.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.models.field_inventory import FieldInventoryMeasurement
from app.models.inventory import InventoryTree

@pytest.fixture()
def owner(db):
    from app.models.user import User

    user = User(
        email=f"numeric-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="H6.2 Fixture",
    )
    db.add(user)
    db.flush()
    return user


# The ten quantities stored as Float on `inventory_trees` and Numeric on
# `field_inventory_measurements`. Left: the name on InventoryTree; right: the
# name on FieldInventoryMeasurement. Tree diameter differs in name only.
TWINS = [
    ("dia_cm", "dbh_cm"),
    ("height_m", "height_m"),
    ("stem_volume", "stem_volume"),
    ("branch_volume", "branch_volume"),
    ("tree_volume", "tree_volume"),
    ("gross_volume", "gross_volume"),
    ("net_volume", "net_volume"),
    ("net_volume_cft", "net_volume_cft"),
    ("firewood_m3", "firewood_m3"),
    ("firewood_chatta", "firewood_chatta"),
]


class TestTheColumnTypes:
    def test_every_twin_is_numeric_on_both_sides(self):
        """The defect itself: one quantity, two types."""
        mismatched = []
        for tree_col, meas_col in TWINS:
            a = InventoryTree.__table__.c[tree_col].type
            b = FieldInventoryMeasurement.__table__.c[meas_col].type
            if isinstance(a, sa.Float) or isinstance(b, sa.Float):
                mismatched.append(f"{tree_col}/{meas_col}")
        assert not mismatched, f"still Float: {mismatched}"

    def test_the_precisions_match_exactly(self):
        """Matching the type but not the scale would still lose the agreement:
        Numeric(15,6) and Numeric(10,2) round the same input differently."""
        for tree_col, meas_col in TWINS:
            a = InventoryTree.__table__.c[tree_col].type
            b = FieldInventoryMeasurement.__table__.c[meas_col].type
            assert (a.precision, a.scale) == (b.precision, b.scale), (
                f"{tree_col} is Numeric({a.precision},{a.scale}) but "
                f"{meas_col} is Numeric({b.precision},{b.scale})"
            )

    def test_raw_coordinates_are_deliberately_left_float(self):
        """Not everything should migrate. `original_x`/`original_y` are the
        as-imported coordinate pair, not a statutory figure, and the whole
        geospatial stack around them is double precision."""
        for name in ("original_x", "original_y"):
            assert isinstance(InventoryTree.__table__.c[name].type, sa.Float)


class TestTheTwinsAgree:
    """The claim in S3-16, executed against the live database."""

    # 0.1 is the classic: unrepresentable in binary floating point. 0.615, 8.475
    # and 2.675 round the *wrong way* through float, against what a person
    # reading the figure would expect. The last exercises the full 15,6 width.
    VALUES = [
        Decimal("0.100000"),
        Decimal("0.615000"),
        Decimal("8.475000"),
        Decimal("2.675000"),
        Decimal("1234567.891234"),
    ]

    @pytest.fixture()
    def inventory_run(self, db, owner):
        """A parent row for the probe. `inventory_calculation_id` is NOT NULL.

        Created inside the transaction the test rolls back, so nothing this
        module writes ever reaches the table permanently.
        """
        from app.models.calculation import Calculation

        # an inventory belongs to a forest (owner's rule, 2026-09-21; migration 092)
        forest = Calculation(user_id=owner.id, forest_name=f"NP {uuid.uuid4().hex[:6]}")
        db.add(forest)
        db.flush()
        run_id = uuid.uuid4()
        db.execute(
            sa.text(
                """
            INSERT INTO public.inventory_calculations
                (id, user_id, calculation_id, uploaded_filename, needs_compartment_assignment, version)
            VALUES (CAST(:id AS uuid), CAST(:uid AS uuid), CAST(:cid AS uuid), 'h6-2-probe.csv', false, 1)
        """
            ),
            {"id": str(run_id), "uid": str(owner.id), "cid": str(forest.id)},
        )
        return run_id

    @pytest.mark.parametrize("value", VALUES)
    def test_a_volume_survives_the_round_trip_intact(self, db, inventory_run, value):
        """Write, read back, compare exactly. No tolerance.

        A tolerance would defeat the purpose: the question is whether the value
        stored is the value given, not whether it is close to it.

        Against the old `Float` column this fails on every one of these values.
        psycopg2 hands back a Python `float`, and comparing a float to a Decimal
        compares the float's *exact* binary value -- 0.1 stored as a double is
        0.1000000000000000055511151231257827..., which is not the figure a
        forester wrote on a tally sheet.
        """
        row_id = uuid.uuid4()
        db.execute(
            sa.text(
                """
            INSERT INTO public.inventory_trees
                (id, inventory_calculation_id, species, dia_cm, net_volume, location)
            VALUES (CAST(:id AS uuid), CAST(:run AS uuid), 'H6.2 probe', 30.00, :v,
                    ST_SetSRID(ST_MakePoint(84.0, 28.0), 4326)::geography)
        """
            ),
            {"id": str(row_id), "run": str(inventory_run), "v": value},
        )
        got = db.execute(
            sa.text(
                "SELECT net_volume FROM public.inventory_trees "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(row_id)},
        ).scalar()
        db.rollback()  # a probe never outlives the test that made it
        assert got == value, f"{value} came back as {got}"

    def test_the_two_paths_sum_to_different_totals(self, db):
        """The consequence, rather than the mechanism.

        Ten thousand trees at 0.1 m3 is 1000 m3 exactly. Down the float path it
        is not -- and the two tables then disagree about a forest's harvestable
        volume by an amount nobody can account for.
        """
        exact = db.execute(
            sa.text(
                "SELECT SUM(v) FROM (SELECT CAST(0.1 AS numeric(15,6)) AS v "
                "FROM generate_series(1, 10000)) s"
            )
        ).scalar()
        drifting = db.execute(
            sa.text(
                "SELECT SUM(v) FROM (SELECT CAST(0.1 AS double precision) AS v "
                "FROM generate_series(1, 10000)) s"
            )
        ).scalar()
        assert exact == Decimal("1000.000000")
        assert drifting != 1000.0, (
            "if this ever passes, the float path stopped drifting and this "
            "task's premise needs re-checking"
        )


class TestReadsStillHandFloatsToTheirConsumers:
    """Storage is exact; the boundaries convert.

    `json.dumps` refuses a Decimal outright and pandas types a Decimal column as
    `object`, so the export and GeoJSON paths must convert. These are the sites
    that were reading the columns bare.
    """

    def test_the_export_helper_converts(self):
        from app.services.inventory import _f

        assert _f(Decimal("12.34")) == 12.34
        assert isinstance(_f(Decimal("12.34")), float)

    def test_it_preserves_none(self):
        """A tree with no recorded height must not export as 0 -- an absent
        measurement and a measurement of zero are different facts."""
        from app.services.inventory import _f

        assert _f(None) is None

    def test_the_geojson_helper_converts(self):
        from app.api.inventory import _f

        assert isinstance(_f(Decimal("1.5")), float)
        assert _f(None) is None

    def test_a_coerced_value_is_json_serialisable(self):
        """The failure this prevents: `TypeError: Object of type Decimal is not
        JSON serializable`, raised out of the GeoJSON branch of the export."""
        import json

        from app.services.inventory import _f

        with pytest.raises(TypeError):
            json.dumps({"net_volume": Decimal("1.5")})
        assert json.dumps({"net_volume": _f(Decimal("1.5"))}) == '{"net_volume": 1.5}'

    def test_the_api_schema_accepts_a_decimal(self):
        """`InventoryTreeResponse` declares `float`, and Pydantic coerces, so
        the API contract is unchanged by the migration. Pinned here because a
        later move to strict mode would break every tree response at once."""
        from app.schemas.inventory import InventoryTreeResponse

        model = InventoryTreeResponse(
            id=uuid.uuid4(),
            species="Shorea robusta",
            local_name=None,
            dia_cm=Decimal("30.50"),
            height_m=Decimal("12.25"),
            tree_class=None,
            stem_volume=Decimal("1.234560"),
            branch_volume=None,
            tree_volume=None,
            gross_volume=None,
            net_volume=None,
            net_volume_cft=None,
            firewood_m3=None,
            firewood_chatta=None,
            remark=None,
            grid_cell_id=None,
            longitude=None,
            latitude=None,
        )
        assert model.dia_cm == 30.5
        assert isinstance(model.dia_cm, float)


class TestNoReadSiteWasMissed:
    def test_every_bare_read_of_a_migrated_column_is_coerced(self):
        """The failure mode this guards is the one that recurs in this project:
        a change applied at some call sites and not others.

        A bare `tree.net_volume` handed to `json.dumps` raises; handed to pandas
        it silently produces an object column. Neither surfaces until somebody
        runs an export, so the check lives here rather than in discovery.

        This walks the AST rather than matching text, which is not fussiness:
        the columns are named in dozens of SQL strings, and a text scan reports
        every one of them. A gate that cries wolf is a gate people switch off.
        """
        import ast
        import pathlib

        columns = {c for c, _ in TWINS}
        offenders = []
        root = pathlib.Path(__file__).resolve().parents[1] / "app"

        for path in sorted(root.rglob("*.py")):
            # The field-inventory modules read the *other* side of each twin --
            # columns that have been Numeric since they were created. Those code
            # paths have run against Decimal for their whole life and are proven
            # by use; nothing about them changed here. This gate is for code
            # that was written against Float and might still assume it.
            if "models" in path.parts or "field_inventory" in path.name:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents = {}
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    parents[child] = node

            for node in ast.walk(tree):
                if not (isinstance(node, ast.Attribute) and node.attr in columns):
                    continue
                # `InventoryTree.net_volume` names a column; it does not read a
                # value. Model classes are the only capitalised names here - including
                # the private aliases (`FieldInventoryMeasurement as _M`), so a leading
                # underscore is not a reason to treat one as an instance.
                if isinstance(node.value, ast.Name) and node.value.id.lstrip("_")[:1].isupper():
                    continue

                parent = parents.get(node)
                # float(x) / _f(x) -- already converted.
                if (isinstance(parent, ast.Call)
                        and isinstance(parent.func, ast.Name)
                        and parent.func.id in (
                            # already converted
                            "float", "_f", "Decimal", "str", "round",
                            # formatters: they take the number and emit text, so
                            # a Decimal is not merely safe here, it is preferable
                            # -- the digits printed are the digits stored.
                            "_csv_num", "format_devanagari",
                        )):
                    continue
                # A truthiness or None test: `if tree.height_m`, `x if tree.dia_cm else 0`,
                # `tree.net_volume or 0`. The value is not being handed onward.
                if isinstance(parent, (ast.Compare, ast.BoolOp, ast.UnaryOp)):
                    continue
                if isinstance(parent, ast.IfExp) and parent.test is node:
                    continue
                # A keyword argument: Pydantic and SQLAlchemy both coerce.
                if isinstance(parent, ast.keyword):
                    continue

                offenders.append(
                    f"{path.relative_to(root)}:{node.lineno}: "
                    f"bare read of .{node.attr}"
                )

        assert not offenders, (
            "these read a Numeric column without converting:\n  "
            + "\n  ".join(offenders)
        )
