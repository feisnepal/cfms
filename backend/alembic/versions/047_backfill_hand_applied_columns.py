"""Backfill sixteen columns that were hand-applied and never migrated.

Revision ID: 047_backfill_hand_applied
Revises: 046_make_workspace_layers_purpose_nullable
Create Date: 2026-08-20

Why this migration exists (report S1-12, task H1.11)
----------------------------------------------------
Once ``alembic upgrade head`` could build a database from empty (000_base_identity,
task H1.4) and the test harness started using it (H1.6), the schema the models
declare and the schema the migrations produce could finally be compared. Sixteen
columns across four tables were declared by the models and created by no
migration:

    inventory_calculations         grid_origin_x, grid_origin_y,
                                   grid_num_cols, grid_num_rows
    sampling_designs               points_data, result_data
    synthetic_tree_models          excel_size_mb, excel_filename, excel_path
    field_inventory_block_summary  agb_t_per_ha, bgb_t_per_ha,
                                   total_biomass_t_per_ha, carbon_stock_tc_per_ha,
                                   co2_equivalent_tco2_per_ha,
                                   weighted_wood_density,
                                   satellite_volume_m3_per_ha

All sixteen are present in live ``cf_db``, so they were applied to production by
hand and the chain was never updated. Nothing detected the gap because the test
harness built its schema from ``Base.metadata``, which of course agreed with the
models.

Definitions below are taken from the live schema so a migration-built database
matches production. Every column is nullable with no default, matching live, so
this is safe to apply to a populated database.

Safe on existing databases: each column is added only if absent, so applying
this to cf_db (which already has all sixteen) is a no-op.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '047_backfill_hand_applied'
down_revision = '046_make_workspace_layers_purpose_nullable'
branch_labels = None
depends_on = None


# table -> [(column_name, type)] — all nullable, no server default, per live.
COLUMNS: dict[str, list[tuple[str, object]]] = {
    'inventory_calculations': [
        ('grid_origin_x', sa.Float()),
        ('grid_origin_y', sa.Float()),
        ('grid_num_cols', sa.Integer()),
        ('grid_num_rows', sa.Integer()),
    ],
    'sampling_designs': [
        ('points_data', postgresql.JSONB(astext_type=sa.Text())),
        ('result_data', postgresql.JSONB(astext_type=sa.Text())),
    ],
    'synthetic_tree_models': [
        ('excel_size_mb', sa.Float()),
        ('excel_filename', sa.String(length=255)),
        ('excel_path', sa.Text()),
    ],
    'field_inventory_block_summary': [
        ('agb_t_per_ha', sa.Numeric(precision=15, scale=6)),
        ('bgb_t_per_ha', sa.Numeric(precision=15, scale=6)),
        ('total_biomass_t_per_ha', sa.Numeric(precision=15, scale=6)),
        ('carbon_stock_tc_per_ha', sa.Numeric(precision=15, scale=6)),
        ('co2_equivalent_tco2_per_ha', sa.Numeric(precision=15, scale=6)),
        ('weighted_wood_density', sa.Numeric(precision=5, scale=3)),
        ('satellite_volume_m3_per_ha', sa.Numeric(precision=15, scale=6)),
    ],
}


def _existing(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names(schema='public'):
        return set()
    return {c['name'] for c in inspector.get_columns(table, schema='public')}


def upgrade() -> None:
    """Add each column only where it is absent."""
    bind = op.get_bind()
    for table, columns in COLUMNS.items():
        present = _existing(bind, table)
        if not present:
            # Table itself is absent — nothing to backfill onto.
            continue
        for name, coltype in columns:
            if name not in present:
                op.add_column(table, sa.Column(name, coltype, nullable=True),
                              schema='public')


def downgrade() -> None:
    """Drop the columns this revision added, where they exist."""
    bind = op.get_bind()
    for table, columns in COLUMNS.items():
        present = _existing(bind, table)
        if not present:
            continue
        for name, _coltype in reversed(columns):
            if name in present:
                op.drop_column(table, name, schema='public')
