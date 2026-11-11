"""Add op_templates table for template save/load feature

Revision ID: 019
Revises: 018
Create Date: 2026-05-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
import json


revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('op_templates',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True, server_default=''),
        sa.Column('tree', JSONB, nullable=False, default=list),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('source_calculation_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('public.users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='public'
    )

    conn = op.get_bind()
    from app.services.operational_plan.seed_data import get_full_seed_document
    from app.services.operational_plan.auto_numbering import recompute_numbers
    seed_tree = get_full_seed_document()
    recompute_numbers(seed_tree, language="NP")
    tree_json = json.dumps([n.model_dump() for n in seed_tree])

    conn.execute(
        sa.text(
            "INSERT INTO public.op_templates (name, description, tree, is_system, is_default) "
            "VALUES (:name, :desc, CAST(:tree AS jsonb), true, true)"
        ).bindparams(name="पूर्वनिर्धारित प्रणाली टेम्पलेट", desc="Default system template with all 18 standard sections, preambles, and appendix items", tree=tree_json)
    )


def downgrade() -> None:
    op.drop_table('op_templates', schema='public')
