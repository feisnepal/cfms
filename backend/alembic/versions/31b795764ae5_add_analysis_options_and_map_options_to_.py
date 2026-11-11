"""add_analysis_options_and_map_options_to_calculations

Revision ID: 31b795764ae5
Revises: 7c7fdcb9a324
Create Date: 2026-02-11 18:34:40.595393

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '31b795764ae5'
down_revision = '7c7fdcb9a324'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add analysis_options and map_options JSONB fields to calculations table"""
    # Add analysis_options column to store user's selected analysis flags
    op.add_column(
        'calculations',
        sa.Column('analysis_options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema='public'
    )

    # Add map_options column to store user's selected map types
    op.add_column(
        'calculations',
        sa.Column('map_options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema='public'
    )

    print("Added analysis_options and map_options columns to calculations table successfully")


def downgrade() -> None:
    """Remove analysis_options and map_options columns"""
    # Drop map_options column
    op.drop_column('calculations', 'map_options', schema='public')

    # Drop analysis_options column
    op.drop_column('calculations', 'analysis_options', schema='public')

    print("Dropped analysis_options and map_options columns from calculations table successfully")
