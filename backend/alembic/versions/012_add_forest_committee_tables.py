"""add_forest_committee_tables

Revision ID: 012
Revises: a1b2c3d4e5f6
Create Date: 2026-03-26 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
import uuid


# revision identifiers, used by Alembic.
revision = '012'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create forest committee tables"""

    # Create forest_user_committee table (Main Committee - Max 15 members)
    op.create_table(
        'forest_user_committee',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('calculation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('serial_no', sa.Integer(), nullable=False),
        sa.Column('gender', sa.String(length=10), nullable=False),
        sa.Column('position', sa.String(length=50), nullable=False),
        sa.Column('caste_category', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('address', sa.Text(), nullable=False),
        sa.Column('mobile', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['public.users.id']),
        sa.CheckConstraint(
            "gender IN ('महिला', 'पुरूष')",
            name="check_gender_values"
        ),
        sa.CheckConstraint(
            "position IN ('अध्यक्ष', 'उपाध्यक्ष', 'कोषाध्यक्ष', 'सह कोषाध्यक्ष', 'सचिव', 'सह सचिव', 'सदस्य')",
            name="check_position_values"
        ),
        sa.CheckConstraint(
            "caste_category IN ('जनजाती', 'आदिवासी', 'दलित', 'सिमान्तकृत', 'अन्य')",
            name="check_caste_category_values"
        ),
        sa.CheckConstraint(
            "serial_no >= 1 AND serial_no <= 15",
            name="check_serial_no_range"
        ),
        sa.CheckConstraint(
            "mobile IS NULL OR length(mobile) = 10",
            name="check_mobile_length"
        ),
        schema='public'
    )

    # Create advisory_committee table (Advisory Committee - Max 10 members)
    op.create_table(
        'advisory_committee',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('calculation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('serial_no', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('address', sa.Text(), nullable=False),
        sa.Column('mobile', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['public.users.id']),
        sa.CheckConstraint(
            "serial_no >= 1 AND serial_no <= 10",
            name="check_advisory_serial_no_range"
        ),
        sa.CheckConstraint(
            "mobile IS NULL OR length(mobile) = 10",
            name="check_advisory_mobile_length"
        ),
        schema='public'
    )

    # Create financial_committee table (Financial Committee - Max 10 members)
    op.create_table(
        'financial_committee',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('calculation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('serial_no', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('address', sa.Text(), nullable=False),
        sa.Column('mobile', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['public.users.id']),
        sa.CheckConstraint(
            "serial_no >= 1 AND serial_no <= 10",
            name="check_financial_serial_no_range"
        ),
        sa.CheckConstraint(
            "mobile IS NULL OR length(mobile) = 10",
            name="check_financial_mobile_length"
        ),
        schema='public'
    )

    # Create indexes
    op.create_index(
        'idx_forest_committee_calculation_id',
        'forest_user_committee',
        ['calculation_id'],
        schema='public'
    )
    op.create_index(
        'idx_forest_committee_serial_no',
        'forest_user_committee',
        ['calculation_id', 'serial_no'],
        schema='public'
    )

    op.create_index(
        'idx_advisory_committee_calculation_id',
        'advisory_committee',
        ['calculation_id'],
        schema='public'
    )

    op.create_index(
        'idx_financial_committee_calculation_id',
        'financial_committee',
        ['calculation_id'],
        schema='public'
    )


def downgrade() -> None:
    """Drop forest committee tables"""

    # Drop indexes first
    op.drop_index('idx_forest_committee_calculation_id', table_name='forest_user_committee', schema='public')
    op.drop_index('idx_forest_committee_serial_no', table_name='forest_user_committee', schema='public')
    op.drop_index('idx_advisory_committee_calculation_id', table_name='advisory_committee', schema='public')
    op.drop_index('idx_financial_committee_calculation_id', table_name='financial_committee', schema='public')

    # Drop tables
    op.drop_table('forest_user_committee', schema='public')
    op.drop_table('advisory_committee', schema='public')
    op.drop_table('financial_committee', schema='public')
