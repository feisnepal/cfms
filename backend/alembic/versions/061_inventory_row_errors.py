"""One bad row must not delete the whole upload (H8.3 / S3-66).

Revision ID: 061_inventory_row_errors
Revises: 060_inventory_trees_numeric
Create Date: 2026-08-27

The defect this closes
-----------------------
`InventoryService._store_trees_simple` builds one `InventoryTree` per CSV row
inside a single `try` with no per-row guard. A bad value anywhere -- a
diameter column that will not parse as a float, on row 4,999 of a 5,000-row
file -- raises out of the loop. The caller, `process_inventory_simple`, catches
that exception and **deletes the entire `InventoryCalculation`**, cascading
away every tree already inserted from earlier batches in the same upload.

So the failure mode was not "this file needs a fix and a retry": it was
"upload 5,000 trees, one typo destroys all 5,000, start over." That is the
same shape S3-66 describes for a device syncing field records -- one bad
record rejecting a whole batch -- just realised through the confirmed real
data-entry path (CSV/Excel/GPKG upload) rather than the JSON bulk-array
endpoint the finding was originally framed around.

This migration adds nowhere to fail into: `row_errors` records which rows were
skipped and why, so the upload keeps what parsed and reports what did not,
instead of silently keeping nothing.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "061_inventory_row_errors"
down_revision = "060_inventory_trees_numeric"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inventory_calculations",
        sa.Column("row_errors", postgresql.JSONB, nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("inventory_calculations", "row_errors", schema="public")
