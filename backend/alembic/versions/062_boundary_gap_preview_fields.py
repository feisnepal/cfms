"""Boundary overlap & gap preview: audit + dispute gap fields (PB-2).

Revision ID: 062_boundary_gap_preview_fields
Revises: 061_inventory_row_errors
Create Date: 2026-08-27

The boundary-overlap preview now reports GAPS (unclaimed bands between the
proposed boundary and an adjoining forest) alongside overlaps, and lets the
user decide to include a gap or file a gap-based dispute. These columns hold
the decision trail:

  - ``forest_boundary_audits.gap_included_ha``       total ha absorbed via
                                                      "include gap".
  - ``forest_boundary_audits.gap_forest_ids``         which neighbour(s)' gap(s)
                                                      were included.
  - ``forest_boundary_audits.dispute_reason_type``    overlap | gap when the
                                                      audit trails a dispute.
  - ``boundary_disputes.gap_geometry``                the disputed unclaimed band
                                                      (for a gap dispute).
  - ``boundary_disputes.dispute_reason_type``         overlap | gap.

All columns are nullable so existing rows and existing call paths (which only
ever reason about overlaps) are untouched.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from geoalchemy2 import Geometry

revision = "062_boundary_gap_preview_fields"
down_revision = "061_inventory_row_errors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forest_boundary_audits",
        sa.Column("gap_included_ha", sa.Numeric(10, 4), nullable=True),
        schema="public",
    )
    op.add_column(
        "forest_boundary_audits",
        sa.Column("gap_forest_ids", postgresql.JSONB, nullable=True),
        schema="public",
    )
    op.add_column(
        "forest_boundary_audits",
        sa.Column("dispute_reason_type", sa.String(16), nullable=True),
        schema="public",
    )
    op.add_column(
        "boundary_disputes",
        sa.Column(
            "gap_geometry", Geometry(geometry_type="GEOMETRY", srid=4326), nullable=True
        ),
        schema="public",
    )
    op.add_column(
        "boundary_disputes",
        sa.Column("dispute_reason_type", sa.String(16), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column("boundary_disputes", "dispute_reason_type", schema="public")
    op.drop_column("boundary_disputes", "gap_geometry", schema="public")
    op.drop_column("forest_boundary_audits", "dispute_reason_type", schema="public")
    op.drop_column("forest_boundary_audits", "gap_forest_ids", schema="public")
    op.drop_column("forest_boundary_audits", "gap_included_ha", schema="public")
