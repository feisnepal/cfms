"""potential_activities.map_geom: the shape an activity is drawn as, when it differs from its kind's.

Revision ID: 124_potential_activity_map_geom
Revises: 123_yearly_plan_status
Create Date: 2026-10-15

Owner decisions 2026-10-14/15 (ACTIVITY_KIND_CATEGORY_TABLE_DRAFT.md): the shape belongs to the activity, not to its unit. The kind
already gives the shape for most activities; four activities need their own, and one is not a place at all.

  21  signboard: field marking of the block   -> line     (the kind says point)
  28  monitoring_point: forest measurement    -> polygon  (the kind says point)
  96  land-use status                         -> polygon  (no kind)
  97  protection of hazard-affected areas     -> polygon  (no kind)
   8  forest plan preparation and review      -> not mappable (requires_map = false)
"""

import sqlalchemy as sa
from alembic import op

revision = "124_potential_activity_map_geom"
down_revision = "123_yearly_plan_status"
branch_labels = None
depends_on = None

SHAPES = {21: "line", 28: "polygon", 96: "polygon", 97: "polygon"}


def upgrade() -> None:
    op.add_column("potential_activities", sa.Column("map_geom", sa.String(10), nullable=True))
    op.create_check_constraint(
        "chk_potential_activity_map_geom", "potential_activities", "map_geom IS NULL OR map_geom IN ('point', 'line', 'polygon')"
    )
    bind = op.get_bind()
    for activity_id, shape in SHAPES.items():
        bind.execute(sa.text("UPDATE potential_activities SET map_geom = :g WHERE id = :i"), {"g": shape, "i": activity_id})
    bind.execute(sa.text("UPDATE potential_activities SET requires_map = false WHERE id = 8"))


def downgrade() -> None:
    op.execute("UPDATE potential_activities SET requires_map = true WHERE id = 8")
    op.drop_constraint("chk_potential_activity_map_geom", "potential_activities", type_="check")
    op.drop_column("potential_activities", "map_geom")
