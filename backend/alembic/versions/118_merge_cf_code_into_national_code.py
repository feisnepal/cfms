"""One community-forest code: merge ``forest_metadata.cf_code`` into ``cf_national_code``.

The two fields held the same thing -- the code the Division Forest Office assigns, which Schedule 11 of the Community Forestry
Guidelines 2081 defines as the national database code (``PPP/DDD/SS/LL/NNN``). Any value kept only in ``cf_code`` is moved across
first, so nothing is lost.

Revision ID: 118_merge_cf_code_into_national_code
Revises: 117_add_unit_analysis
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op

revision = "118_merge_cf_code_into_national_code"
down_revision = "117_add_unit_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE forest_metadata SET cf_national_code = btrim(cf_code) "
        "WHERE (cf_national_code IS NULL OR btrim(cf_national_code) = '') AND cf_code IS NOT NULL AND btrim(cf_code) <> ''"
    )
    op.drop_constraint("ck_forest_metadata_cf_code_len", "forest_metadata", type_="check")
    op.drop_column("forest_metadata", "cf_code")


def downgrade() -> None:
    op.add_column("forest_metadata", sa.Column("cf_code", sa.String(32), nullable=True))
    op.create_check_constraint("ck_forest_metadata_cf_code_len", "forest_metadata", "char_length(trim(cf_code)) <= 32")
