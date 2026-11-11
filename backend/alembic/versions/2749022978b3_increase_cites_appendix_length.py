"""increase_cites_appendix_length

Revision ID: 2749022978b3
Revises: 048860bbe041
Create Date: 2026-02-07 20:42:32.639827

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2749022978b3'
down_revision = '048860bbe041'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Increase cites_appendix column from VARCHAR(20) to VARCHAR(50)
    op.alter_column(
        'biodiversity_species',
        'cites_appendix',
        type_=sa.String(50),
        existing_type=sa.String(20),
        schema='public'
    )
    print("Increased cites_appendix column length to 50 characters")


def downgrade() -> None:
    # Revert back to VARCHAR(20)
    op.alter_column(
        'biodiversity_species',
        'cites_appendix',
        type_=sa.String(20),
        existing_type=sa.String(50),
        schema='public'
    )
