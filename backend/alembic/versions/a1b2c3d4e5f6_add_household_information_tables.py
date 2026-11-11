"""add_household_information_tables

Revision ID: a1b2c3d4e5f6
Revises: 011
Create Date: 2026-03-23 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
import uuid


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create caste_classification and household_information tables"""

    # Create caste_classification table
    op.create_table(
        'caste_classification',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('classification_ne', sa.String(length=100), nullable=False),
        sa.Column('caste_ne', sa.String(length=100), nullable=False),
        sa.Column('surname_ne', sa.String(length=100), nullable=False),
        sa.Column('classification_en', sa.String(length=100), nullable=True),
        sa.Column('caste_en', sa.String(length=100), nullable=True),
        sa.Column('surname_en', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('surname_ne', name='uq_surname_ne'),
        schema='public'
    )

    # Create household_information table
    op.create_table(
        'household_information',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('calculation_id', UUID(as_uuid=True), nullable=False),

        # Basic Info
        sa.Column('house_no', sa.Integer(), nullable=False),
        sa.Column('surname', sa.String(length=100), nullable=False),
        sa.Column('household_head_male', sa.String(length=200), nullable=True),
        sa.Column('household_head_female', sa.String(length=200), nullable=True),
        sa.Column('address_tole', sa.String(length=200), nullable=True),
        sa.Column('latitude', sa.Numeric(10, 8), nullable=True),
        sa.Column('longitude', sa.Numeric(11, 8), nullable=True),

        # Population
        sa.Column('female_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('male_count', sa.Integer(), nullable=False, server_default='0'),

        # Land & Occupation
        sa.Column('land_area', sa.Numeric(10, 4), nullable=True),
        sa.Column('land_unit', sa.String(length=20), nullable=True),
        sa.Column('forest_based_occupation', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('other_occupation', sa.Boolean(), nullable=False, server_default='false'),

        # Livestock
        sa.Column('cow_ox_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('buffalo_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('goat_sheep_count', sa.Integer(), nullable=False, server_default='0'),

        # Forest Product Demands
        sa.Column('timber_demand_cft', sa.Numeric(10, 2), nullable=False, server_default='5'),
        sa.Column('pole_demand', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('firewood_demand_bhari', sa.Numeric(10, 2), nullable=True),
        sa.Column('grass_demand_bhari', sa.Numeric(10, 2), nullable=True),
        sa.Column('bedding_demand_bhari', sa.Numeric(10, 2), nullable=True),

        # Flags
        sa.Column('firewood_auto_calculated', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('grass_auto_calculated', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('bedding_auto_calculated', sa.Boolean(), nullable=False, server_default='true'),

        # Classification
        sa.Column('caste_classification_ne', sa.String(length=100), nullable=True),
        sa.Column('caste_classification_en', sa.String(length=100), nullable=True),
        sa.Column('caste_classification_manual', sa.Boolean(), nullable=False, server_default='false'),

        # Other Info
        sa.Column('other_group_membership', sa.Boolean(), nullable=True),
        sa.Column('prosperity_level', sa.String(length=50), nullable=False, server_default='मध्यम'),
        sa.Column('prosperity_auto_suggested', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('remarks', sa.Text(), nullable=True),

        # Metadata
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['public.users.id']),
        sa.CheckConstraint('female_count >= 0', name='check_female_count_positive'),
        sa.CheckConstraint('male_count >= 0', name='check_male_count_positive'),
        sa.CheckConstraint('cow_ox_count >= 0', name='check_cow_ox_count_positive'),
        sa.CheckConstraint('buffalo_count >= 0', name='check_buffalo_count_positive'),
        sa.CheckConstraint('goat_sheep_count >= 0', name='check_goat_sheep_count_positive'),
        sa.CheckConstraint('timber_demand_cft >= 0', name='check_timber_positive'),
        sa.CheckConstraint('pole_demand >= 0', name='check_pole_positive'),
        sa.CheckConstraint(
            "land_unit IN ('ropani', 'kaththa') OR land_unit IS NULL",
            name='check_land_unit_valid'
        ),
        sa.CheckConstraint(
            "prosperity_level IN ('सम्पन्न', 'मध्यम', 'विपन्न', 'अति विपन्न')",
            name='check_prosperity_level_valid'
        ),
        schema='public'
    )

    # Create indexes
    op.create_index(
        'idx_household_calculation_id',
        'household_information',
        ['calculation_id'],
        schema='public'
    )
    op.create_index(
        'idx_household_surname',
        'household_information',
        ['surname'],
        schema='public'
    )
    op.create_index(
        'idx_caste_surname',
        'caste_classification',
        ['surname_ne'],
        schema='public'
    )


def downgrade() -> None:
    """Drop household_information and caste_classification tables"""

    # Drop indexes
    op.drop_index('idx_household_calculation_id', table_name='household_information', schema='public')
    op.drop_index('idx_household_surname', table_name='household_information', schema='public')
    op.drop_index('idx_caste_surname', table_name='caste_classification', schema='public')

    # Drop tables
    op.drop_table('household_information', schema='public')
    op.drop_table('caste_classification', schema='public')
