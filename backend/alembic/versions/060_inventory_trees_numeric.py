"""The same quantity, stored two different ways, made one (H6.2 · S3-16).

Revision ID: 060_inventory_trees_numeric
Revises: 059_document_issuance_integrity
Create Date: 2026-08-27

The defect, in its sharpest form
--------------------------------
S3-16 says "the *same quantity* stored as `Float` in one table and `Numeric` in
another will not compare equal". That is not abstract here. Nine quantities are
stored both ways:

    quantity            field_inventory_measurements   inventory_trees
    height_m            Numeric(10,2)                  Float
    stem_volume         Numeric(15,6)                  Float
    branch_volume       Numeric(15,6)                  Float
    tree_volume         Numeric(15,6)                  Float
    gross_volume        Numeric(15,6)                  Float
    net_volume          Numeric(15,6)                  Float
    net_volume_cft      Numeric(15,6)                  Float
    firewood_m3         Numeric(15,6)                  Float
    firewood_chatta     Numeric(15,6)                  Float

plus tree diameter, which is `dbh_cm Numeric(10,2)` in one and `dia_cm Float`
in the other -- the same measurement under two names and two types.

Both tables feed the same volume, biomass and carbon totals in an operational
plan. Binary floating point cannot represent 0.1 exactly, so accumulation over
tens of thousands of trees drifts, and the two paths disagree by amounts nobody
can see or explain. `inventory_trees` holds 113,451 rows.

The precisions are copied from the columns they must agree with, not chosen
afresh: agreement is the entire point.

Why only these, and not the other 52 Float columns
---------------------------------------------------
The report classifies numeric columns as (a) measurement, (b) derived or
statistical, (c) monetary -- and asks for (a) and (c) to be migrated.

* **(c) monetary: none.** No `Float` column in this schema is monetary; the
  money is already `Numeric`. That risk was closed before this task existed.
* **(b) derived: left alone deliberately.** Percentages, min/max summaries,
  file sizes in MB, confidence scores, and the allometric coefficients
  (`a`, `b`, `c`, `s`, `m`, `bg` in `tree_species_coefficients`) are statistical
  quantities where `Float` is correct and `Numeric` would imply a precision the
  values do not have. Migrating them would be churn through pandas paths for no
  correctness gain.

Reading these columns now yields `Decimal`
-------------------------------------------
That is the point -- and it is also the risk. Writes were already safe: both
`inventory.py` and `field_inventory_service.py` coerce with `float()` before
storing. Reads in `api/compartments.py` were already wrapped in `float(...)`,
because the twin columns were `Numeric` and that lesson was learned once
already. The remaining read sites are coerced in the same commit.
"""
import sqlalchemy as sa
from alembic import op

revision = "060_inventory_trees_numeric"
down_revision = "059_document_issuance_integrity"
branch_labels = None
depends_on = None

# (column, precision, scale) — copied from field_inventory_measurements.
VOLUME_COLUMNS = [
    "stem_volume", "branch_volume", "tree_volume", "gross_volume",
    "net_volume", "net_volume_cft", "firewood_m3", "firewood_chatta",
]


def upgrade() -> None:
    # Tree diameter: `dia_cm` here, `dbh_cm` there. Same measurement, and now
    # the same type and precision.
    op.alter_column("inventory_trees", "dia_cm",
                    existing_type=sa.Float(), type_=sa.Numeric(10, 2),
                    existing_nullable=False, schema="public",
                    postgresql_using="dia_cm::numeric(10,2)")
    op.alter_column("inventory_trees", "height_m",
                    existing_type=sa.Float(), type_=sa.Numeric(10, 2),
                    existing_nullable=True, schema="public",
                    postgresql_using="height_m::numeric(10,2)")

    for column in VOLUME_COLUMNS:
        op.alter_column("inventory_trees", column,
                        existing_type=sa.Float(), type_=sa.Numeric(15, 6),
                        existing_nullable=True, schema="public",
                        postgresql_using=f"{column}::numeric(15,6)")


def downgrade() -> None:
    op.alter_column("inventory_trees", "dia_cm",
                    existing_type=sa.Numeric(10, 2), type_=sa.Float(),
                    existing_nullable=False, schema="public",
                    postgresql_using="dia_cm::double precision")
    op.alter_column("inventory_trees", "height_m",
                    existing_type=sa.Numeric(10, 2), type_=sa.Float(),
                    existing_nullable=True, schema="public",
                    postgresql_using="height_m::double precision")
    for column in VOLUME_COLUMNS:
        op.alter_column("inventory_trees", column,
                        existing_type=sa.Numeric(15, 6), type_=sa.Float(),
                        existing_nullable=True, schema="public",
                        postgresql_using=f"{column}::double precision")
