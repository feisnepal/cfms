"""Backfill activity_drawn_features.calculation_id, set WGS84, and make it NOT NULL.

Revision ID: 089_drawn_feature_calc_id
Revises: 088_add_sub_area_category
Create Date: 2026-09-20

Migration 038 added `activity_drawn_features.calculation_id` as a nullable column and never
filled it, and no writer ever populated it afterwards. Every query that filtered on it
(the workspace's Activity Features layer, collision-check, intersecting) matched nothing:
the layer was permanently empty.

- calculation_id is copied from the owning proposed activity (which always has one).
- Features were stored with SRID 0 (bare WKT), so any ST_Intersects against a block
  (SRID 4326) raised "mixed SRID geometries". Their coordinates are lon/lat, so they are
  stamped 4326.
- NOT NULL, as the model has always declared, so a writer that forgets it fails loudly
  instead of creating a feature nobody can see.

Idempotent. The data fixes are not reverted on downgrade (they only correct wrong values);
downgrade restores the nullable column.
"""
from alembic import op

revision = "089_drawn_feature_calc_id"
down_revision = "088_add_sub_area_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE activity_drawn_features f
           SET calculation_id = a.calculation_id
          FROM proposed_yearly_activities a
         WHERE a.id = f.proposed_activity_id
           AND f.calculation_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE activity_drawn_features
           SET geometry = ST_SetSRID(geometry, 4326)
         WHERE ST_SRID(geometry) = 0
        """
    )
    op.alter_column("activity_drawn_features", "calculation_id", nullable=False)


def downgrade() -> None:
    op.alter_column("activity_drawn_features", "calculation_id", nullable=True)
