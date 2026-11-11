"""Create the foundational tables no migration ever created.

Revision ID: 000_base_identity
Revises:
Create Date: 2026-08-20

Why this migration exists (report S1-12, task H1.4)
---------------------------------------------------
Before this revision, NO migration in the chain created **five** foundational
tables that the rest of the schema depends on:

    organizations, users, calculations,
    potential_activities, proposed_yearly_activities, activity_year_details

``001_create_forest_managers`` opens with a foreign key to ``public.users.id``;
``5f6a2dd6d50f`` alters ``public.calculations``; and 32 later revisions add
columns to ``calculations`` alone. ``alembic upgrade head`` against an empty
database therefore failed on the first step, which meant:

* no environment could be provisioned from migrations (no staging, no DR);
* ``tests/conftest.py`` had to build its schema from ``Base.metadata`` with a
  ``create_all`` loop instead, so CI exercised a schema Alembic never produced;
* ``alembic check`` compared models against a database Alembic never built.

The prior comment in ``conftest.py`` described this as an *ordering* defect
("001 references public.users which a later migration creates"). That diagnosis
was wrong: no migration created these tables at all. This is a missing
foundational revision, not a misordering — which is why the fix is a new base
rather than a reshuffle of ``down_revision`` pointers.

Column definitions were captured from the live ``cf_db`` schema (not from
``Base.metadata``) so a migration-built database matches production exactly.
``Base.metadata`` is deliberately not the source here: it is what the broken
test harness already trusted, and the point of this change is to stop.

Only the **original** columns are created here. Columns that later revisions add
are deliberately omitted, or those revisions would fail with "column already
exists". Verified counts of columns added downstream: ``calculations`` 32,
``proposed_yearly_activities`` 4, ``activity_year_details`` 2,
``potential_activities`` 1.

Two foreign keys are deliberately NOT created here — ``proposed_yearly_activities``
``block_id`` → ``forest_blocks`` and ``sub_area_id`` → ``forest_sub_areas``. Those
target tables are created by revision ``013``, downstream of this one. The columns
exist here; the constraints are added by the tail revision ``047_base_deferred_fks``
so the final schema still matches ``Base.metadata``.

``calculations.application_id`` is created as a plain column with no foreign key,
matching ``models/calculation.py:48``. The live database carries a legacy FK to an
``applications`` table that is not part of the modelled schema.

Safety on existing databases
----------------------------
Alembic records only the current head in ``alembic_version`` and infers that
every ancestor is applied. A database stamped at a later revision (``cf_db`` is
at ``046``) therefore treats this one as already applied and will not re-run it.
The operations are additionally idempotent — ``checkfirst`` on enum creation and
an inspector guard on each table — so a partially-built database is repaired
rather than aborted.
"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '000_base_identity'
down_revision = None
branch_labels = None
depends_on = None


# Enum types are created explicitly with checkfirst, and the columns declare
# create_type=False. Letting create_table emit the types implicitly makes any
# re-run fail on an already-existing type.
USER_ROLE = postgresql.ENUM(
    'GUEST', 'USER', 'ORG_ADMIN', 'SUPER_ADMIN',
    name='userrole', create_type=False,
)
USER_STATUS = postgresql.ENUM(
    'PENDING', 'ACTIVE', 'SUSPENDED',
    name='userstatus', create_type=False,
)
SUBSCRIPTION_TYPE = postgresql.ENUM(
    'BASIC', 'PREMIUM', 'ENTERPRISE',
    name='subscriptiontype', create_type=False,
)
CALCULATION_STATUS = postgresql.ENUM(
    'PROCESSING', 'COMPLETED', 'FAILED', 'PENDING',
    name='calculationstatus', create_type=False,
)


def upgrade() -> None:
    """Create the foundational tables, in dependency order."""
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # H1.4 / S1-12: widen alembic_version.version_num.
    #
    # Alembic creates that column as VARCHAR(32). Eleven revision ids in this
    # chain are longer — the worst are 42 characters — so a from-empty build
    # died with StringDataRightTruncation the moment it tried to stamp
    # `019_add_year_number_to_proposed_activities`. Live cf_db carries a
    # hand-widened VARCHAR(64); this makes that change reproducible.
    #
    # Safe to run here: Alembic creates alembic_version before invoking the
    # first migration, so the table exists by the time this executes.
    # ------------------------------------------------------------------
    bind.execute(sa.text(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"
    ))

    USER_ROLE.create(bind, checkfirst=True)
    USER_STATUS.create(bind, checkfirst=True)
    SUBSCRIPTION_TYPE.create(bind, checkfirst=True)
    CALCULATION_STATUS.create(bind, checkfirst=True)

    existing = set(sa.inspect(bind).get_table_names(schema='public'))

    if 'organizations' not in existing:
        op.create_table(
            'organizations',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('contact_email', sa.String(length=255), nullable=False),
            sa.Column('contact_phone', sa.String(length=20), nullable=True),
            sa.Column('subscription_type', SUBSCRIPTION_TYPE, nullable=False),
            sa.Column('max_users', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            schema='public',
        )
        op.create_index('ix_organizations_name', 'organizations', ['name'],
                        unique=True, schema='public')

    if 'users' not in existing:
        op.create_table(
            'users',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('hashed_password', sa.String(length=255), nullable=False),
            sa.Column('full_name', sa.String(length=255), nullable=False),
            sa.Column('phone', sa.String(length=20), nullable=True),
            sa.Column('role', USER_ROLE, nullable=False),
            sa.Column('status', USER_STATUS, nullable=False),
            sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=True),
            sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
            # users.unified_shell_opt_out is NOT created here — revision
            # 043_map_unification_flags adds it (U01/U08).
            sa.ForeignKeyConstraint(['organization_id'], ['public.organizations.id'],
                                    name='users_organization_id_fkey'),
            sa.PrimaryKeyConstraint('id'),
            schema='public',
        )
        op.create_index('ix_users_email', 'users', ['email'],
                        unique=True, schema='public')

    # ------------------------------------------------------------------
    # calculations — the central entity. 32 further columns are added by
    # downstream revisions and must NOT appear here.
    # ------------------------------------------------------------------
    if 'calculations' not in existing:
        op.create_table(
            'calculations',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
            # No FK: models/calculation.py:48 declares this as a plain column.
            sa.Column('application_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('uploaded_filename', sa.String(length=255), nullable=True),
            sa.Column('boundary_geom',
                      geoalchemy2.types.Geometry(geometry_type='GEOMETRY', srid=4326,
                                                 spatial_index=False),
                      nullable=True),
            sa.Column('result_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column('status', CALCULATION_STATUS, nullable=False),
            sa.Column('processing_time_seconds', sa.Integer(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=True),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['public.users.id'],
                                    name='calculations_user_id_fkey'),
            sa.PrimaryKeyConstraint('id'),
            schema='public',
        )
        # idx_calculations_user_id / _status / _created_at are deliberately NOT
        # created here — revision 032_add_performance_indexes owns them, and
        # creating them early makes that revision fail with DuplicateTable.
        op.create_index('idx_calculations_boundary_geom', 'calculations',
                        ['boundary_geom'], schema='public', postgresql_using='gist')

    # ------------------------------------------------------------------
    # Yearly-activity catalogue and proposals.
    # ------------------------------------------------------------------
    if 'potential_activities' not in existing:
        op.create_table(
            'potential_activities',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('sn', sa.String(), nullable=True),
            sa.Column('project_name', sa.String(), nullable=True),
            # Column name is misspelled in production; preserved deliberately so
            # a migration-built database matches live. Renaming is a separate change.
            sa.Column('progarms', sa.String(), nullable=True),
            sa.Column('activities', sa.String(), nullable=True),
            sa.Column('unit', sa.String(), nullable=True),
            sa.Column('quantity', sa.String(), nullable=True),
            sa.Column('yearly_budget', sa.String(), nullable=True),
            sa.Column('is_default', sa.String(), nullable=True),
            sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('display_order', sa.Integer(), server_default=sa.text('0'),
                      nullable=False),
            sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'),
                      nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            schema='public',
        )
        op.create_index('idx_potential_activities_default', 'potential_activities',
                        ['is_default'], schema='public')

    if 'proposed_yearly_activities' not in existing:
        op.create_table(
            'proposed_yearly_activities',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('calculation_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('potential_activity_id', sa.Integer(), nullable=False),
            # FKs to forest_blocks / forest_sub_areas are added by
            # 047_base_deferred_fks — those tables are created by revision 013.
            sa.Column('block_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('sub_area_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('default_quantity', sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column('default_yearly_budget', sa.Numeric(precision=12, scale=2),
                      nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=50),
                      server_default=sa.text("'proposed'"), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['calculation_id'], ['public.calculations.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['potential_activity_id'],
                                    ['public.potential_activities.id'],
                                    ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            schema='public',
        )
        op.create_index('idx_proposed_activities_calculation',
                        'proposed_yearly_activities', ['calculation_id'], schema='public')
        op.create_index('idx_proposed_activities_block', 'proposed_yearly_activities',
                        ['block_id'], schema='public')
        op.create_index('idx_proposed_activities_sub_area', 'proposed_yearly_activities',
                        ['sub_area_id'], schema='public')
        op.create_index('idx_proposed_activities_status', 'proposed_yearly_activities',
                        ['status'], schema='public')

    if 'activity_year_details' not in existing:
        op.create_table(
            'activity_year_details',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('proposed_activity_id', postgresql.UUID(as_uuid=True),
                      nullable=False),
            sa.Column('year_number', sa.Integer(), nullable=False),
            sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('yearly_budget', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('target_completion_month', sa.String(length=20), nullable=True),
            sa.Column('actual_quantity', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('actual_budget', sa.Numeric(precision=12, scale=2), nullable=True),
            sa.Column('status', sa.String(length=50),
                      server_default=sa.text("'planned'"), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['proposed_activity_id'],
                                    ['public.proposed_yearly_activities.id'],
                                    ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('proposed_activity_id', 'year_number',
                                name='unique_activity_year'),
            schema='public',
        )
        op.create_index('idx_activity_year_proposed', 'activity_year_details',
                        ['proposed_activity_id'], schema='public')
        # idx_activity_year_detail_activity is owned by revision 018_add_indexes.
        op.create_index('idx_activity_year_number', 'activity_year_details',
                        ['year_number'], schema='public')
        op.create_index('idx_activity_year_status', 'activity_year_details',
                        ['status'], schema='public')


def downgrade() -> None:
    """Drop in reverse dependency order, then the enum types."""
    bind = op.get_bind()

    op.drop_table('activity_year_details', schema='public')
    op.drop_table('proposed_yearly_activities', schema='public')
    op.drop_table('potential_activities', schema='public')
    op.drop_table('calculations', schema='public')

    op.drop_index('ix_users_email', table_name='users', schema='public')
    op.drop_table('users', schema='public')

    op.drop_index('ix_organizations_name', table_name='organizations', schema='public')
    op.drop_table('organizations', schema='public')

    # Enums last — the columns using them are gone by this point.
    CALCULATION_STATUS.drop(bind, checkfirst=True)
    SUBSCRIPTION_TYPE.drop(bind, checkfirst=True)
    USER_STATUS.drop(bind, checkfirst=True)
    USER_ROLE.drop(bind, checkfirst=True)
