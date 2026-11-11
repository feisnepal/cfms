"""Add year_number to proposed_yearly_activities

Revision ID: 019_add_year_number_to_proposed_activities
Revises: 018_add_grid_cells
Create Date: 2026-04-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '019_add_year_number_to_proposed_activities'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'proposed_yearly_activities',
        sa.Column('year_number', sa.Integer(), nullable=True),
        schema='public'
    )


def downgrade() -> None:
    op.drop_column(
        'proposed_yearly_activities',
        'year_number',
        schema='public'
    )
