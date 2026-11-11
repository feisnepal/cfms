CREATE OR REPLACE FUNCTION check_dimension_exclusivity()
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
