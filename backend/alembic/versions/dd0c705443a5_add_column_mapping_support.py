"""add_column_mapping_support

Adds support for flexible column mapping in tree inventory CSV uploads:
1. column_mapping_preferences table - stores user's preferred column mappings
2. column_mapping field in calculations - stores the actual mapping used for each upload

Revision ID: dd0c705443a5
Revises: 31b795764ae5
Create Date: 2026-02-12 11:20:38.746760

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'dd0c705443a5'
down_revision = '31b795764ae5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add column mapping support:
    1. Create column_mapping_preferences table for user preferences
    2. Add column_mapping JSONB field to calculations table
    """

    # Create column_mapping_preferences table
    op.create_table(
        'column_mapping_preferences',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('original_column', sa.String(length=255), nullable=False),
        sa.Column('mapped_to', sa.String(length=100), nullable=False),
        sa.Column('times_used', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['public.users.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'original_column',
                           name='uq_user_original_column'),
        schema='public'
    )

    # Create indexes for performance
    op.create_index('idx_column_mapping_user', 'column_mapping_preferences',
                    ['user_id'], unique=False, schema='public')
    op.create_index('idx_column_mapping_last_used', 'column_mapping_preferences',
                    ['user_id', 'last_used_at'], unique=False, schema='public')

    # Add column_mapping JSONB field to calculations table
    op.add_column('calculations',
                  sa.Column('column_mapping', postgresql.JSONB(astext_type=sa.Text()),
                           nullable=True),
                  schema='public')

    # Add comment for documentation
    op.execute("""
        COMMENT ON TABLE public.column_mapping_preferences IS
        'Stores user preferences for CSV column mappings to improve future upload experience';
    """)

    op.execute("""
        COMMENT ON COLUMN public.calculations.column_mapping IS
        'Stores the actual column mapping used for this calculation (JSON format)';
    """)

    print("Created column_mapping_preferences table successfully")
    print("Added column_mapping field to calculations table")


def downgrade() -> None:
    """
    Rollback column mapping support:
    1. Remove column_mapping field from calculations table
    2. Drop column_mapping_preferences table
    """

    # Remove column_mapping field from calculations
    op.drop_column('calculations', 'column_mapping', schema='public')

    # Drop indexes
    op.drop_index('idx_column_mapping_last_used', table_name='column_mapping_preferences',
                  schema='public')
    op.drop_index('idx_column_mapping_user', table_name='column_mapping_preferences',
                  schema='public')

    # Drop column_mapping_preferences table
    op.drop_table('column_mapping_preferences', schema='public')

    print("Removed column mapping support from database")
