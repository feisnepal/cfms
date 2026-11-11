"""Add user group extent tables

Revision ID: 010
Revises: 009
Create Date: 2026-03-20

Adds tables for User Group Map feature:
- user_group_extents: Store extent boundary polygons
- user_group_buildings: Store settlement and building statistics
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import geoalchemy2

# revision identifiers
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create user_group_extents table
    #
    # H1.4 / S1-12: calculation_id and user_id were declared sa.Integer() with
    # foreign keys to calculations.id and users.id, both of which are UUID. This
    # migration could therefore never execute — PostgreSQL rejects the FK with
    # DatatypeMismatch. It was never run anywhere: live cf_db has
    # user_group_extents.calculation_id as uuid (matching models/user_group.py:28),
    # and user_group_buildings does not exist in production at all. Corrected to
    # UUID rather than left alone, because there is no applied history to rewrite.
    op.create_table(
        'user_group_extents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('calculation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('extent_geometry', geoalchemy2.Geometry(
            geometry_type='MULTIPOLYGON', srid=4326, from_text='ST_GeomFromEWKT',
            name='geometry'
        ), nullable=False),
        sa.Column('source_type', sa.String(50), nullable=True),
        sa.Column('buffer_distance_m', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['calculation_id'], ['calculations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for user_group_extents
    op.create_index(
        'idx_user_group_extents_geom',
        'user_group_extents',
        ['extent_geometry'],
        postgresql_using='gist'
    )
    op.create_index(
        'idx_user_group_extents_calc',
        'user_group_extents',
        ['calculation_id']
    )
    op.create_index(
        op.f('ix_user_group_extents_id'),
        'user_group_extents',
        ['id']
    )

    # Create user_group_buildings table
    op.create_table(
        'user_group_buildings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('extent_id', sa.Integer(), nullable=False),
        sa.Column('settlement_id', sa.Integer(), nullable=True),
        sa.Column('settlement_name', sa.String(255), nullable=True),
        sa.Column('building_count', sa.Integer(), nullable=True),
        sa.Column('total_building_area_m2', sa.Numeric(12, 2), nullable=True),
        sa.Column('direction_from_forest', sa.String(20), nullable=True),
        sa.Column('buildings_geojson', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('settlement_location', geoalchemy2.Geometry(
            geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT',
            name='geometry'
        ), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['extent_id'], ['user_group_extents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for user_group_buildings
    op.create_index(
        'idx_user_group_buildings_extent',
        'user_group_buildings',
        ['extent_id']
    )
    op.create_index(
        'idx_user_group_buildings_settlement',
        'user_group_buildings',
        ['settlement_id']
    )
    op.create_index(
        op.f('ix_user_group_buildings_id'),
        'user_group_buildings',
        ['id']
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_user_group_buildings_settlement', 'user_group_buildings')
    op.drop_index('idx_user_group_buildings_extent', 'user_group_buildings')
    op.drop_index(op.f('ix_user_group_buildings_id'), 'user_group_buildings')

    # Drop tables
    op.drop_table('user_group_buildings')

    op.drop_index('idx_user_group_extents_calc', 'user_group_extents')
    op.drop_index('idx_user_group_extents_geom', 'user_group_extents')
    op.drop_index(op.f('ix_user_group_extents_id'), 'user_group_extents')

    op.drop_table('user_group_extents')
