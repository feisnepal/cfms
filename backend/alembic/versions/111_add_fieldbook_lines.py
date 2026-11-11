"""Field book: group points into lines, so nothing has to guess which points to join.

Revision ID: 111_add_fieldbook_lines
Revises: 110_add_fieldbook_boundary_class
Create Date: 2026-10-04

Owner's rule: the outer points form a closed outline that draws as a polygon; the internal points are open
lines that are not closed. The numbering alone cannot say that: ``I5`` and ``I6`` may be the end of one internal
edge and the start of a different one, and a consumer that simply joined them in order would draw a line that
does not exist.

* ``line_id`` -- the line that first reached the point (``O-1`` an outer ring, ``I-3`` an internal edge,
  ``L-1`` a free-standing loop such as a sub-area inside a unit).
* ``lines``   -- every line the point is on and its place in each (``{"I-2": 5, "O-1": 12}``): a junction belongs
  to every line that meets there, so each line can be rebuilt end to end, shared end points included.

Additive and nullable; field books made before this read as ungrouped until regenerated.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "111_add_fieldbook_lines"
down_revision = "110_add_fieldbook_boundary_class"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fieldbook", sa.Column("line_id", sa.String(length=12), nullable=True), schema="public")
    op.add_column(
        "fieldbook", sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema="public"
    )


def downgrade() -> None:
    op.drop_column("fieldbook", "lines", schema="public")
    op.drop_column("fieldbook", "line_id", schema="public")
