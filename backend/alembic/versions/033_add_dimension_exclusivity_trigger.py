"""Add DB trigger enforcing mutually exclusive block/compartment dimensions

Revision ID: 033_add_dimension_exclusivity_trigger
Revises: 032_add_performance_indexes
Create Date: 2026-07-25

"""
from alembic import op

revision = "033_add_dimension_exclusivity_trigger"
down_revision = "028_add_resource_yield_columns"


def upgrade() -> None:
    # Trigger function: prevents compartment creation when sampling designs exist,
    # and sampling design creation when compartments exist.
    op.execute("""
        CREATE OR REPLACE FUNCTION public.check_dimension_exclusivity()
        RETURNS TRIGGER AS $$
        BEGIN
            -- For compartment insert: check no sampling designs exist
            IF TG_TABLE_NAME = 'forest_blocks' AND NEW.is_compartment THEN
                IF EXISTS (
                    SELECT 1 FROM public.sampling_designs
                    WHERE calculation_id = NEW.calculation_id
                    LIMIT 1
                ) THEN
                    RAISE EXCEPTION 'Cannot create compartment: calculation % has block-level sampling designs. Delete sampling designs first.', NEW.calculation_id;
                END IF;
            END IF;

            -- For sampling design insert: check no compartments exist
            IF TG_TABLE_NAME = 'sampling_designs' THEN
                IF EXISTS (
                    SELECT 1 FROM public.forest_blocks
                    WHERE calculation_id = NEW.calculation_id
                    AND is_compartment = TRUE
                    LIMIT 1
                ) THEN
                    RAISE EXCEPTION 'Cannot create sampling design: calculation % has compartments. Delete compartments first.', NEW.calculation_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Trigger on forest_blocks — prevents compartment insert when sampling exists
    op.execute("""
        CREATE TRIGGER trg_check_dimension_before_insert_forest_blocks
        BEFORE INSERT ON public.forest_blocks
        FOR EACH ROW
        WHEN (NEW.is_compartment = TRUE)
        EXECUTE FUNCTION public.check_dimension_exclusivity();
    """)

    # Also fire on UPDATE that changes is_compartment to TRUE
    op.execute("""
        CREATE TRIGGER trg_check_dimension_before_update_forest_blocks
        BEFORE UPDATE OF is_compartment ON public.forest_blocks
        FOR EACH ROW
        WHEN (NEW.is_compartment = TRUE AND (OLD.is_compartment IS DISTINCT FROM TRUE))
        EXECUTE FUNCTION public.check_dimension_exclusivity();
    """)

    # Trigger on sampling_designs — prevents insert when compartments exist
    op.execute("""
        CREATE TRIGGER trg_check_dimension_before_insert_sampling_designs
        BEFORE INSERT ON public.sampling_designs
        FOR EACH ROW
        EXECUTE FUNCTION public.check_dimension_exclusivity();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_check_dimension_before_insert_forest_blocks ON public.forest_blocks")
    op.execute("DROP TRIGGER IF EXISTS trg_check_dimension_before_update_forest_blocks ON public.forest_blocks")
    op.execute("DROP TRIGGER IF EXISTS trg_check_dimension_before_insert_sampling_designs ON public.sampling_designs")
    op.execute("DROP FUNCTION IF EXISTS public.check_dimension_exclusivity()")
