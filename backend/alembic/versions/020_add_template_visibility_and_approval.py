"""Add visibility, approval, tags, and summaries to op_templates

Revision ID: 020
Revises: 019
Create Date: 2026-05-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('op_templates', sa.Column('visibility', sa.String(20), nullable=False, server_default='private'), schema='public')
    op.add_column('op_templates', sa.Column('tags', JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")), schema='public')
    op.add_column('op_templates', sa.Column('sections_summary', JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")), schema='public')
    op.add_column('op_templates', sa.Column('variables_summary', JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")), schema='public')
    op.add_column('op_templates', sa.Column('approval_status', sa.String(20), nullable=False, server_default='none'), schema='public')
    op.add_column('op_templates', sa.Column('approval_note', sa.Text(), nullable=True, server_default=''), schema='public')
    op.add_column('op_templates', sa.Column('approved_by', UUID(as_uuid=True), sa.ForeignKey('public.users.id'), nullable=True), schema='public')
    op.add_column('op_templates', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True), schema='public')

    # Update the system template to approved/global
    op.execute("""
        UPDATE public.op_templates
        SET visibility = 'global', approval_status = 'approved', tags = '["default", "system"]'::jsonb
        WHERE is_system = true
    """)


def downgrade() -> None:
    op.drop_column('op_templates', 'approved_at', schema='public')
    op.drop_column('op_templates', 'approved_by', schema='public')
    op.drop_column('op_templates', 'approval_note', schema='public')
    op.drop_column('op_templates', 'approval_status', schema='public')
    op.drop_column('op_templates', 'variables_summary', schema='public')
    op.drop_column('op_templates', 'sections_summary', schema='public')
    op.drop_column('op_templates', 'tags', schema='public')
    op.drop_column('op_templates', 'visibility', schema='public')
