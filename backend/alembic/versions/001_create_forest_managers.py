"""Create forest_managers table

Revision ID: 001
Revises:
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
# H1.4 / S1-12: was None. This migration's FK to public.users.id requires the
# users table, which no revision created — see 000_base_identity.
down_revision = '000_base_identity'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create forest_managers table for user-forest assignments"""
    op.create_table(
        'forest_managers',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('community_forest_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('assigned_date', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['public.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'community_forest_id', name='uq_user_forest'),
        schema='public'
    )

    # Create indexes
    op.create_index('idx_forest_managers_user', 'forest_managers', ['user_id'], unique=False, schema='public')
    op.create_index('idx_forest_managers_forest', 'forest_managers', ['community_forest_id'], unique=False, schema='public')

    print("Created forest_managers table successfully")


def downgrade() -> None:
    """Drop forest_managers table"""
    op.drop_index('idx_forest_managers_forest', table_name='forest_managers', schema='public')
    op.drop_index('idx_forest_managers_user', table_name='forest_managers', schema='public')
    op.drop_table('forest_managers', schema='public')
