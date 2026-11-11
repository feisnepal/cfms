"""Allow sampling designs when compartments exist (compartment-mode sampling)

Now that sampling designs can be created in compartment-mode forests,
remove the trigger branch that blocked sampling_design INSERT when
compartments exist. The one-way gate (compartments → sampling designs)
still works: you cannot create compartments if sampling designs exist.

Revision ID: 037_allow_compartment_sampling
Revises: 036_fix_dimension_exclusivity_trigger
Create Date: 2026-07-25
"""
from alembic import op

revision = "037_allow_compartment_sampling"
down_revision = "036_fix_dimension_exclusivity_trigger"


def upgrade() -> None:
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


def downgrade() -> None:
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
