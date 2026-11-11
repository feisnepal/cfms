"""Fix dimension exclusivity trigger — separate branch IFs to avoid NEW.is_compartment error on sampling_designs

Revision ID: 036_fix_dimension_exclusivity_trigger
Revises: 035_add_stand_type_check_constraint
Create Date: 2026-07-25

"""
from alembic import op

revision = "036_fix_dimension_exclusivity_trigger"
down_revision = "035_add_stand_type_check_constraint"


def upgrade() -> None:
    # The original trigger function used a single IF with AND:
    #   IF TG_TABLE_NAME = 'forest_blocks' AND NEW.is_compartment THEN
    # PostgreSQL resolves NEW.is_compartment even when TG_TABLE_NAME is
    # 'sampling_designs' (which has no is_compartment column), causing:
    #   record "new" has no field "is_compartment"
    # Fix: nest the IFs so NEW.is_compartment is only referenced when the
    # outer TG_TABLE_NAME check succeeds.
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
            IF TG_TABLE_NAME = 'sampling_designs' THEN
                IF EXISTS (
                    SELECT 1 FROM public.forest_blocks
                    WHERE calculation_id = NEW.calculation_id
                    AND is_compartment = TRUE
                    LIMIT 1
                ) THEN
                    RAISE EXCEPTION 'Cannot create sampling design: calculation % has compartments. Delete compartments first.', NEW.calculation_id;
                END IF;
                RETURN NEW;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # Restore original trigger function with the AND-based IF
    op.execute("""
        CREATE OR REPLACE FUNCTION public.check_dimension_exclusivity()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_TABLE_NAME = 'forest_blocks' AND NEW.is_compartment THEN
                IF EXISTS (
                    SELECT 1 FROM public.sampling_designs
                    WHERE calculation_id = NEW.calculation_id
                    LIMIT 1
                ) THEN
                    RAISE EXCEPTION 'Cannot create compartment: calculation % has block-level sampling designs. Delete sampling designs first.', NEW.calculation_id;
                END IF;
            END IF;
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
