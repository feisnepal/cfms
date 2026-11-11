"""Create op_template_categories table for controlled category vocabulary

Revision ID: 031_add_template_categories_table
Revises: 030_add_template_versions_table
Create Date: 2026-06-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "031_add_template_categories_table"
down_revision = "030_add_template_versions_table"


def upgrade():
    op.create_table(
        "op_template_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("label_ne", sa.String(255), nullable=False),
        sa.Column("label_en", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True, server_default=""),
        sa.Column("color", sa.String(20), nullable=True, server_default="purple"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="public",
    )

    op.execute("""
        INSERT INTO public.op_template_categories (id, key, label_ne, label_en, description, color, sort_order)
        VALUES
            (gen_random_uuid(), 'normal_forest', 'सामान्य वन', 'Normal Forest', 'General forest management plan', 'green', 1),
            (gen_random_uuid(), 'community_forest', 'सामुदायिक वन', 'Community Forest', 'Community-managed forest plan', 'blue', 2),
            (gen_random_uuid(), 'leasehold_forest', 'भाडापट्टी वन', 'Leasehold Forest', 'Leasehold/production forest plan', 'orange', 3),
            (gen_random_uuid(), 'collaborative_forest', 'सहकारी वन', 'Collaborative Forest', 'Multi-stakeholder collaborative forest plan', 'purple', 4),
            (gen_random_uuid(), 'religious_forest', 'धार्मिक वन', 'Religious Forest', 'Religious/cultural forest plan', 'red', 5),
            (gen_random_uuid(), 'other', 'अन्य', 'Other', 'Other forest types', 'default', 99)
    """)


def downgrade():
    op.drop_table("op_template_categories", schema="public")
