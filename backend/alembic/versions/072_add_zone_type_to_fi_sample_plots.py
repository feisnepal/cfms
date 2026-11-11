"""Add zone_type to field_inventory_sample_plots.

Revision ID: 072_add_zone_type_to_fi_sample_plots
Revises: 071_drop_op_template_legacy_flags
Create Date: 2026-09-01

Protected-area sampling stratification (design item #1).

A sample plot falls in one of two sampling strata:

    productive  -- the operable forest, sampled at the regular intensity
    protected   -- a protection sub-area, sampled growing-stock-only at ~0.1%

The distinction was computed at sampling-design time (`zone_type` in the
design's per-point assignment) but lost once field data was imported:
`field_inventory_sample_plots` had only `block_name` + `sample_plot_number`.
Without it the growing-stock / MAI / allowable-cut math cannot keep the
protection stratum out of yield regulation, and protected-stratum growing
stock cannot be reported on its own.

This column is populated by point-in-polygon against the parent forest's
protected sub-areas during field-inventory processing. NULL means the plot
is not stratified -- the forest has no protected sub-areas, or the plot was
imported before this column existed. Consumers must treat NULL as
'productive'.
"""
from alembic import op
import sqlalchemy as sa

revision = "072_add_zone_type_to_fi_sample_plots"
down_revision = "071_drop_op_template_legacy_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "field_inventory_sample_plots",
        sa.Column("zone_type", sa.String(length=20), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("field_inventory_sample_plots", "zone_type", schema="public")
