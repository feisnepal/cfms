"""Field book: say which points are OUTER, which are INTERNAL, and which units each separates.

Revision ID: 110_add_fieldbook_boundary_class
Revises: 109_add_sub_area_category_to_block
Create Date: 2026-10-04

The field book used to be one run of ``P1..Pn`` walked unit by unit. A surveyor could not tell the outer
boundary from the internal ones, the numbering was not a route, and which units meet at a point lived only
in a comma-joined name. The rewrite (``services/fieldbook_sequence.py``) numbers the OUTER ring first and the
INTERNAL boundaries after it, each edge once, so the book needs to store:

* ``point_label``      -- ``O1``.. for outer, ``I1``.. for internal (what people read and quote)
* ``boundary_class``   -- ``outer`` | ``internal``
* ``junction_degree``  -- how many units meet at the point
* ``is_junction``      -- outer: the boundary plus two or more units; internal: three or more units
* ``adjacent_units``   -- names of the units the point separates (JSON list, sorted by unit number)
* ``next_point_label`` -- the point ``azimuth_to_next`` / ``distance_to_next`` lead to

Additive and nullable: existing field books keep working and read as unclassified until regenerated.
``point_number`` stays the unique running order 1..N (outer points first), so nothing keyed on it breaks.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "110_add_fieldbook_boundary_class"
down_revision = "109_add_sub_area_category_to_block"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fieldbook", sa.Column("point_label", sa.String(length=12), nullable=True), schema="public")
    op.add_column("fieldbook", sa.Column("boundary_class", sa.String(length=10), nullable=True), schema="public")
    op.add_column("fieldbook", sa.Column("junction_degree", sa.Integer(), nullable=True), schema="public")
    op.add_column("fieldbook", sa.Column("is_junction", sa.Boolean(), nullable=True), schema="public")
    op.add_column(
        "fieldbook", sa.Column("adjacent_units", postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema="public"
    )
    op.add_column("fieldbook", sa.Column("next_point_label", sa.String(length=12), nullable=True), schema="public")
    op.create_index(
        "idx_fieldbook_boundary_class", "fieldbook", ["calculation_id", "boundary_class"], unique=False, schema="public"
    )


def downgrade() -> None:
    op.drop_index("idx_fieldbook_boundary_class", table_name="fieldbook", schema="public")
    for col in ("next_point_label", "adjacent_units", "is_junction", "junction_degree", "boundary_class", "point_label"):
        op.drop_column("fieldbook", col, schema="public")
