"""change_boundary_geom_to_multipolygon

Revision ID: 12a9084b095b
Revises: 5f6a2dd6d50f
Create Date: 2026-01-23 16:49:03.334740

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '12a9084b095b'
down_revision = '5f6a2dd6d50f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Change geometry type constraint from Polygon to accept both Polygon and MultiPolygon
    # Drop the existing type constraint
    op.execute("""
        ALTER TABLE public.calculations
        ALTER COLUMN boundary_geom TYPE geometry(Geometry, 4326);
    """)
    print("Changed boundary_geom to accept Polygon and MultiPolygon geometries")


def downgrade() -> None:
    # Revert to Polygon-only constraint (this will fail if MultiPolygons exist)
    op.execute("""
        ALTER TABLE public.calculations
        ALTER COLUMN boundary_geom TYPE geometry(Polygon, 4326);
    """)
    print("Reverted boundary_geom to Polygon-only")
