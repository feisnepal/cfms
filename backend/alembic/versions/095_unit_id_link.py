"""Add unit_id to inventory_trees / field_inventory_sample_plots (D10, FS-1d).

Revision ID: 095_unit_id_link
Revises: 094_forest_units_depth_from_one
Create Date: 2026-09-22

The owner's D10 answer: the user chooses the Blocks-or-Compartments stream
before any data upload, and trees/plots link to that stream's unit. Until now
that link was a display-only string (``block_name``) -- the three existing
FKs on ``inventory_trees`` (``block_id``, ``forest_block_id``,
``compartment_id``) and the unmapped ``compartment_id``/``compartment_code``
on ``field_inventory_sample_plots`` are all dead: nothing writes or reads
them for a real decision. They are legacy and are dropped later, in P6
(migration 097) -- untouched here.

This migration adds a fifth, NEW column, ``unit_id``, distinct from those
dead ones: a FK straight at ``forest_blocks.id`` (any depth -- a leaf
sub-block/sub-compartment or a top-level block/compartment), nullable,
``ON DELETE SET NULL`` (a deleted unit must not take the tree/plot row with
it -- ``block_name``/``extra_columns`` remain as the display fallback and are
never removed in this phase). Semantics: the leaf unit whose geometry
contained the point as of the last assignment. FS-1d.3/1d.4 wire real writers
(tree/plot assignment); FS-1d.5 wires the by-location re-assignment hook.
This migration only adds the column and best-effort backfills it by name.

Backfill
--------
Join each tree/plot to its owning calculation through the existing
``inventory_calculations``/``field_inventory_calculations`` join table (its
own ``calculation_id`` can be NULL -- an orphaned upload, see
``FOREST_STRUCTURE_IMPLEMENTATION_PLAN.md`` report -- those rows are skipped,
not failed), then match ``forest_blocks.block_name`` to the tree/plot's own
``block_name`` string within that calculation. A tree/plot whose name does
not match any unit in its own forest (misspelled/renamed/deleted unit) is
left with ``unit_id IS NULL`` -- FS-1d.3 assigns fresh trees by point-in-
-polygon, not by name, so this is a one-time best-effort catch-up, not the
live assignment path. Both backfills report matched/skipped/unmatched counts
via ``RAISE NOTICE`` rather than failing the migration.

FS-1d.9 -- exclusivity-trigger narrowing
-----------------------------------------
Report finding F9/V1: the live trigger (migration 033, last touched by 037)
blocks *every* compartment INSERT once the forest has any sampling design --
including a compartment forest that already has compartments and is simply
adding another one (a divide, a new top-level compartment). It was only ever
meant to stop a *block* forest from being converted into a compartment forest
out from under an existing block-level sampling design. Narrowed here to
fire only when the forest has **no compartment yet** (i.e. this INSERT would
be the one establishing the compartment stream for the first time); a forest
already committed to the compartment branch is exempt, matching the
compartment-mode sampling allowance already carved out in migration 037.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '095_unit_id_link'
down_revision = '094_forest_units_depth_from_one'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. inventory_trees.unit_id -----------------------------------
    op.add_column(
        'inventory_trees',
        sa.Column(
            'unit_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('forest_blocks.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index(
        'idx_inventory_trees_unit_id', 'inventory_trees', ['unit_id']
    )

    op.execute("""
        WITH matched AS (
            SELECT DISTINCT ON (it.id) it.id AS tree_id, fb.id AS unit_id
            FROM public.inventory_trees it
            JOIN public.inventory_calculations ic ON ic.id = it.inventory_calculation_id
            JOIN public.forest_blocks fb
                ON fb.calculation_id = ic.calculation_id
               AND fb.block_name = it.block_name
            WHERE ic.calculation_id IS NOT NULL
              AND it.block_name IS NOT NULL
            ORDER BY it.id, fb.id
        )
        UPDATE public.inventory_trees it
        SET unit_id = matched.unit_id
        FROM matched
        WHERE it.id = matched.tree_id;
    """)

    op.execute("""
        DO $$
        DECLARE
            total int;
            matched_ct int;
            no_calc int;
        BEGIN
            SELECT count(*) INTO total FROM public.inventory_trees;
            SELECT count(*) INTO matched_ct FROM public.inventory_trees WHERE unit_id IS NOT NULL;
            SELECT count(*) INTO no_calc FROM public.inventory_trees it
                JOIN public.inventory_calculations ic ON ic.id = it.inventory_calculation_id
                WHERE ic.calculation_id IS NULL;
            RAISE NOTICE 'inventory_trees.unit_id backfill: % / % matched by name (% rows skipped, orphaned calculation_id)',
                matched_ct, total, no_calc;
        END $$;
    """)

    # --- 2. field_inventory_sample_plots.unit_id ------------------------
    op.add_column(
        'field_inventory_sample_plots',
        sa.Column(
            'unit_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('forest_blocks.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index(
        'idx_field_inventory_plots_unit_id', 'field_inventory_sample_plots', ['unit_id']
    )

    op.execute("""
        WITH matched AS (
            SELECT DISTINCT ON (p.id) p.id AS plot_id, fb.id AS unit_id
            FROM public.field_inventory_sample_plots p
            JOIN public.field_inventory_calculations fic ON fic.id = p.field_inventory_calculation_id
            JOIN public.forest_blocks fb
                ON fb.calculation_id = fic.calculation_id
               AND fb.block_name = p.block_name
            WHERE fic.calculation_id IS NOT NULL
            ORDER BY p.id, fb.id
        )
        UPDATE public.field_inventory_sample_plots p
        SET unit_id = matched.unit_id
        FROM matched
        WHERE p.id = matched.plot_id;
    """)

    op.execute("""
        DO $$
        DECLARE
            total int;
            matched_ct int;
            no_calc int;
        BEGIN
            SELECT count(*) INTO total FROM public.field_inventory_sample_plots;
            SELECT count(*) INTO matched_ct FROM public.field_inventory_sample_plots WHERE unit_id IS NOT NULL;
            SELECT count(*) INTO no_calc FROM public.field_inventory_sample_plots p
                JOIN public.field_inventory_calculations fic ON fic.id = p.field_inventory_calculation_id
                WHERE fic.calculation_id IS NULL;
            RAISE NOTICE 'field_inventory_sample_plots.unit_id backfill: % / % matched by name (% rows skipped, orphaned calculation_id)',
                matched_ct, total, no_calc;
        END $$;
    """)

    # --- 3. FS-1d.9: narrow the exclusivity trigger ---------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION public.check_dimension_exclusivity()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_TABLE_NAME = 'forest_blocks' THEN
                IF NEW.is_compartment THEN
                    IF NOT EXISTS (
                        SELECT 1 FROM public.forest_blocks
                        WHERE calculation_id = NEW.calculation_id
                          AND is_compartment = TRUE
                        LIMIT 1
                    ) AND EXISTS (
                        SELECT 1 FROM public.sampling_designs
                        WHERE calculation_id = NEW.calculation_id
                        LIMIT 1
                    ) THEN
                        RAISE EXCEPTION 'Cannot create compartment: calculation % has block-level sampling designs. Delete sampling designs first.', NEW.calculation_id;
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # --- 3. Restore the pre-095 (unnarrowed) exclusivity check ----------
    op.execute("""
        CREATE OR REPLACE FUNCTION public.check_dimension_exclusivity()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_TABLE_NAME = 'forest_blocks' THEN
                IF NEW.is_compartment THEN
                    IF EXISTS (
                        SELECT 1 FROM public.sampling_designs
                        WHERE calculation_id = NEW.calculation_id
                        LIMIT 1
                    ) THEN
                        RAISE EXCEPTION 'Cannot create compartment: calculation % has block-level sampling designs. Delete sampling designs first.', NEW.calculation_id;
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # --- 2. field_inventory_sample_plots.unit_id ------------------------
    op.drop_index('idx_field_inventory_plots_unit_id', table_name='field_inventory_sample_plots')
    op.drop_column('field_inventory_sample_plots', 'unit_id')

    # --- 1. inventory_trees.unit_id --------------------------------------
    op.drop_index('idx_inventory_trees_unit_id', table_name='inventory_trees')
    op.drop_column('inventory_trees', 'unit_id')
