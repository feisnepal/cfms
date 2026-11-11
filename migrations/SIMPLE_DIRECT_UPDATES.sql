-- ============================================================================
-- SIMPLE DIRECT DATABASE UPDATES
-- Run these manually in pgAdmin or psql - No complex migration needed!
-- Date: 2026-02-15
-- ============================================================================

-- Start transaction for safety
BEGIN;

-- ============================================================================
-- PART 1: ADD class_number COLUMN (if not exists)
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forest_types' AND column_name = 'class_number'
    ) THEN
        ALTER TABLE forest_types ADD COLUMN class_number INTEGER;
    END IF;
END $$;

-- ============================================================================
-- PART 2: UPDATE EXISTING FOREST TYPES WITH CLASS NUMBERS
-- ============================================================================

UPDATE forest_types SET class_number = 1 WHERE forest_type_name = 'Shorea robusta Forest';
UPDATE forest_types SET class_number = 2 WHERE forest_type_name = 'Tropical Mixed Broadleaved Forest';
UPDATE forest_types SET class_number = 3 WHERE forest_type_name = 'Subtropical Mixed Broadleaved Forest';
UPDATE forest_types SET class_number = 4 WHERE forest_type_name LIKE 'Shorea robusta%Mixed Broadleaved Forest';
UPDATE forest_types SET class_number = 5 WHERE forest_type_name = 'Abies Mixed Forest';
UPDATE forest_types SET class_number = 6 WHERE forest_type_name LIKE 'Upper Temperate Conifer%Forest';
UPDATE forest_types SET class_number = 7 WHERE forest_type_name = 'Cool Temperate Mixed Broadleaved Forest';
UPDATE forest_types SET class_number = 8 WHERE forest_type_name = 'Castanopsis Lower Temperate Mixed Broadleaved Forest';
UPDATE forest_types SET class_number = 9 WHERE forest_type_name = 'Pinus roxburghii Forest';
UPDATE forest_types SET class_number = 10 WHERE forest_type_name = 'Alnus Forest';
UPDATE forest_types SET class_number = 11 WHERE forest_type_name = 'Schima Forest';
UPDATE forest_types SET class_number = 12 WHERE forest_type_name LIKE 'Pinus roxburghii%Mixed Broadleaved Forest';
UPDATE forest_types SET class_number = 13 WHERE forest_type_name = 'Pinus wallichiana Forest';
UPDATE forest_types SET class_number = 14 WHERE forest_type_name = 'Warm Temperate Mixed Broadleaved Forest';
UPDATE forest_types SET class_number = 15 WHERE forest_type_name = 'Upper Temperate Quercus Forest';
UPDATE forest_types SET class_number = 16 WHERE forest_type_name = 'Rhododendron arboreum Forest';
UPDATE forest_types SET class_number = 17 WHERE forest_type_name = 'Temperate Rhododendron Mixed Broadleaved Forest';
UPDATE forest_types SET class_number = 18 WHERE forest_type_name LIKE 'Dalbergia sissoo%Senegalia catechu Forest';
UPDATE forest_types SET class_number = 19 WHERE forest_type_name LIKE 'Terminalia%Tropical Mixed Broadleaved Forest';
UPDATE forest_types SET class_number = 22 WHERE forest_type_name = 'Tropical Riverine Forest';
UPDATE forest_types SET class_number = 21 WHERE forest_type_name LIKE 'Tropical Deciduous%Riverine Forest';
UPDATE forest_types SET class_number = 23 WHERE forest_type_name LIKE 'Lower Temperate Mixed%Forest';
UPDATE forest_types SET class_number = 24 WHERE forest_type_name LIKE 'Pinus roxburghii%Shorea robusta Forest';
UPDATE forest_types SET class_number = 25 WHERE forest_type_name LIKE 'Lower Temperate%Quercus Forest';

-- ============================================================================
-- PART 3: ADD 3 MISSING FOREST TYPES (with pixel_value)
-- ============================================================================

-- Get the next available ID
DO $$
DECLARE
    next_id INTEGER;
    next_pixel INTEGER;
BEGIN
    SELECT COALESCE(MAX(id), 0) + 1 INTO next_id FROM forest_types;

    -- Add Class 20 if not exists
    IF NOT EXISTS (SELECT 1 FROM forest_types WHERE class_number = 20) THEN
        INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value)
        VALUES (next_id, 'Temperate Mixed Broadleaved Forest', 20, 20);
        next_id := next_id + 1;
    END IF;

    -- Add Class 21 if not exists
    IF NOT EXISTS (SELECT 1 FROM forest_types WHERE class_number = 21) THEN
        INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value)
        VALUES (next_id, 'Tropical Deciduous Indigenous Riverine Forest', 21, 21);
        next_id := next_id + 1;
    END IF;

    -- Add Class 23 if not exists
    IF NOT EXISTS (SELECT 1 FROM forest_types WHERE class_number = 23) THEN
        INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value)
        VALUES (next_id, 'Lower Temperate Mixed robusta Forest', 23, 23);
    END IF;
END $$;

-- ============================================================================
-- PART 4: REMOVE GENERIC PLACEHOLDER SPECIES
-- ============================================================================

-- Delete associations first
DELETE FROM forest_species_association
WHERE species_id IN (
    SELECT id FROM tree_species_coefficients
    WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp')
);

-- Delete generic species
DELETE FROM tree_species_coefficients
WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp');

-- ============================================================================
-- PART 5: UPDATE SPECIES SCIENTIFIC NAMES (Taxonomy)
-- ============================================================================

UPDATE tree_species_coefficients SET scientific_name = 'Syzygium cumini'
WHERE scientific_name IN ('Eugenia jambolana', 'Eugenia Jambolana');

UPDATE tree_species_coefficients SET scientific_name = 'Haldina cordifolia'
WHERE scientific_name = 'Adina cordifolia';

-- ============================================================================
-- PART 6: ADD NEW COLUMNS TO tree_species_coefficients
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tree_species_coefficients' AND column_name = 'min_altitude_m') THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN min_altitude_m INTEGER;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tree_species_coefficients' AND column_name = 'max_altitude_m') THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN max_altitude_m INTEGER;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tree_species_coefficients' AND column_name = 'growth_rate') THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN growth_rate VARCHAR(20);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tree_species_coefficients' AND column_name = 'economic_value') THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN economic_value VARCHAR(20);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tree_species_coefficients' AND column_name = 'nitrogen_fixing') THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN nitrogen_fixing BOOLEAN DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tree_species_coefficients' AND column_name = 'main_uses') THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN main_uses TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tree_species_coefficients' AND column_name = 'ecological_role') THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN ecological_role TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tree_species_coefficients' AND column_name = 'rarity_status') THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN rarity_status VARCHAR(20) DEFAULT 'Common';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tree_species_coefficients' AND column_name = 'family') THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN family VARCHAR(100);
    END IF;
END $$;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'PART 1-6 COMPLETED SUCCESSFULLY';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Forest types updated with class numbers';
    RAISE NOTICE 'Missing forest types added';
    RAISE NOTICE 'Generic placeholders removed';
    RAISE NOTICE 'New columns added to species table';
    RAISE NOTICE '=================================================';
END $$;

-- Commit transaction
COMMIT;
