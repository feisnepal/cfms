"""Forum F1: full-text search column and the starting tags.

Revision ID: 144_forum_search_and_tags
Revises: 143_forum_core
Create Date: 2026-10-27

``search_vector`` is generated from the title and body with the ``simple`` configuration: no stemming and no stop words, so Nepali
(Devanagari) text is indexed as written. One tag per area of the system, as Open Foris does one per tool.
"""
import sqlalchemy as sa
from alembic import op

revision = "144_forum_search_and_tags"
down_revision = "143_forum_core"
branch_labels = None
depends_on = None

STARTING_TAGS = (
    ("map", "Boundary, blocks, compartments and the map workspace"),
    ("user-group", "User group polygons, buildings and the automatic analysis"),
    ("fieldbook", "The field book of boundary points"),
    ("sampling", "Sampling design and plots"),
    ("field-inventory", "Field inventory plots, trees and block summaries"),
    ("biodiversity", "Species records"),
    ("household", "Household data and vulnerability"),
    ("sfm", "Sustainable forest management classification"),
    ("cost-benefit", "Cost-benefit analysis"),
    ("operational-plan", "The operational plan document and its export"),
    ("yearly-plan", "Yearly activities planner"),
    ("ntfp", "Non-timber forest product inventory"),
    ("hazard", "Landslide, soil loss and hazard maps"),
    ("mobile", "Offline and mobile data capture"),
    ("account", "Registration, login and approval"),
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE forum_posts ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title, '') || ' ' || body_md)) STORED"
    )
    op.create_index("ix_forum_posts_search", "forum_posts", ["search_vector"], postgresql_using="gin")
    tags = sa.table("forum_tags", sa.column("name", sa.String), sa.column("description_md", sa.Text))
    op.bulk_insert(tags, [{"name": n, "description_md": d} for n, d in STARTING_TAGS])


def downgrade() -> None:
    op.execute("DELETE FROM forum_tags WHERE name IN (" + ", ".join(f"'{n}'" for n, _ in STARTING_TAGS) + ")")
    op.drop_index("ix_forum_posts_search", table_name="forum_posts")
    op.drop_column("forum_posts", "search_vector")
