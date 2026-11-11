-- ============================================================================
-- MIGRATION: Phase 1A - Critical Fix
-- Description: Remove generic placeholders, add missing forest types,
--              update forest type class numbers
-- Date: 2026-02-15
-- Database: cf_db (PostgreSQL)
-- Estimated Time: 2-5 minutes
-- ============================================================================

-- Start transaction
BEGIN;

-- ============================================================================
-- STEP 1: CREATE BACKUP TABLES
-- ============================================================================

-- Backup forest_types table
DROP TABLE IF EXISTS forest_types_backup_20260215;
CREATE TABLE forest_types_backup_20260215 AS
SELECT * FROM forest_types;

-- Backup tree_species_coefficients table
DROP TABLE IF EXISTS tree_species_coefficients_backup_20260215;
CREATE TABLE tree_species_coefficients_backup_20260215 AS
SELECT * FROM tree_species_coefficients;

-- Backup forest_species_association table
DROP TABLE IF EXISTS forest_species_association_backup_20260215;
CREATE TABLE forest_species_association_backup_20260215 AS
SELECT * FROM forest_species_association;

-- Log backup completion
DO $$
BEGIN
    RAISE NOTICE 'Backup tables created successfully with suffix _backup_20260215';
END $$;


-- ============================================================================
-- STEP 2: ADD class_number COLUMN TO forest_types (if not exists)
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forest_types'
        AND column_name = 'class_number'
    ) THEN
        ALTER TABLE forest_types ADD COLUMN class_number INTEGER;
        RAISE NOTICE 'Added class_number column to forest_types';
    ELSE
        RAISE NOTICE 'class_number column already exists in forest_types';
    END IF;
END $$;


-- ============================================================================
-- STEP 3: REMOVE GENERIC PLACEHOLDER SPECIES
-- ============================================================================

-- Delete species associations for generic placeholders
DELETE FROM forest_species_association
WHERE species_id IN (
    SELECT id FROM tree_species_coefficients
    WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp')
);

-- Delete generic placeholder species
DELETE FROM tree_species_coefficients
WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp');

-- Log deletion
DO $$
DECLARE
    deleted_count INTEGER;
BEGIN
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RAISE NOTICE 'Removed % generic placeholder species', deleted_count;
END $$;


-- ============================================================================
-- STEP 4: UPDATE EXISTING SPECIES SCIENTIFIC NAMES (Synonyms)
-- ============================================================================

-- Update Eugenia jambolana to Syzygium cumini (modern taxonomy)
UPDATE tree_species_coefficients
SET scientific_name = 'Syzygium cumini',
    local_name = COALESCE(local_name, 'Jamun')
WHERE scientific_name = 'Eugenia Jambolana' OR scientific_name = 'Eugenia jambolana';

-- Update Adina cordifolia to Haldina cordifolia (modern taxonomy)
UPDATE tree_species_coefficients
SET scientific_name = 'Haldina cordifolia',
    local_name = COALESCE(local_name, 'Karma')
WHERE scientific_name = 'Adina cordifolia';

-- Standardize Acacia catechu to Senegalia catechu (modern taxonomy)
-- Note: Keeping both as they're commonly used interchangeably
UPDATE tree_species_coefficients
SET local_name = 'Khayar'
WHERE scientific_name IN ('Acacia catechu', 'Senegalia catechu')
AND (local_name IS NULL OR local_name = 'Unknown');

-- Log updates
DO $$
BEGIN
    RAISE NOTICE 'Updated species scientific names to current taxonomy';
END $$;


-- ============================================================================
-- STEP 5: UPDATE FOREST TYPE CLASS NUMBERS (Regulation 2079)
-- ============================================================================

-- Update existing forest types with class numbers
UPDATE forest_types SET class_number = 1
WHERE forest_type_name = 'Shorea robusta Forest';

UPDATE forest_types SET class_number = 2
WHERE forest_type_name = 'Tropical Mixed Broadleaved Forest';

UPDATE forest_types SET class_number = 3
WHERE forest_type_name = 'Subtropical Mixed Broadleaved Forest';

UPDATE forest_types SET class_number = 4
WHERE forest_type_name = 'Shorea robusta - Mixed Broadleaved Forest'
   OR forest_type_name = 'Shorea robusta-Mixed Broadleaved Forest';

UPDATE forest_types SET class_number = 5
WHERE forest_type_name = 'Abies Mixed Forest';

UPDATE forest_types SET class_number = 6
WHERE forest_type_name = 'Upper Temperate Coniferous Forest'
   OR forest_type_name = 'Upper Temperate Conifer Forest';

UPDATE forest_types SET class_number = 7
WHERE forest_type_name = 'Cool Temperate Mixed Broadleaved Forest';

UPDATE forest_types SET class_number = 8
WHERE forest_type_name = 'Castanopsis Lower Temperate Mixed Broadleaved Forest';

UPDATE forest_types SET class_number = 9
WHERE forest_type_name = 'Pinus roxburghii Forest';

UPDATE forest_types SET class_number = 10
WHERE forest_type_name = 'Alnus Forest';

UPDATE forest_types SET class_number = 11
WHERE forest_type_name = 'Schima Forest';

UPDATE forest_types SET class_number = 12
WHERE forest_type_name = 'Pinus roxburghii - Mixed Broadleaved Forest'
   OR forest_type_name = 'Pinus roxburghii-Mixed Broadleaved Forest';

UPDATE forest_types SET class_number = 13
WHERE forest_type_name = 'Pinus wallichiana Forest';

UPDATE forest_types SET class_number = 14
WHERE forest_type_name = 'Warm Temperate Mixed Broadleaved Forest';

UPDATE forest_types SET class_number = 15
WHERE forest_type_name = 'Upper Temperate Quercus Forest';

UPDATE forest_types SET class_number = 16
WHERE forest_type_name = 'Rhododendron arboreum Forest';

UPDATE forest_types SET class_number = 17
WHERE forest_type_name = 'Temperate Rhododendron Mixed Broadleaved Forest';

UPDATE forest_types SET class_number = 18
WHERE forest_type_name = 'Dalbergia sissoo-Senegalia catechu Forest';

UPDATE forest_types SET class_number = 19
WHERE forest_type_name = 'Terminalia - Tropical Mixed Broadleaved Forest'
   OR forest_type_name = 'Terminalia-Tropical Mixed Broadleaved Forest';

UPDATE forest_types SET class_number = 22
WHERE forest_type_name = 'Tropical Riverine Forest';

UPDATE forest_types SET class_number = 21
WHERE forest_type_name = 'Tropical Deciduous Riverine Forest'
   OR forest_type_name = 'Tropical Deciduous Indigenous Riverine Forest';

UPDATE forest_types SET class_number = 23
WHERE forest_type_name = 'Lower Temperate Mixed Broadleaved Forest'
   OR forest_type_name = 'Lower Temperate Mixed robusta Forest';

UPDATE forest_types SET class_number = 24
WHERE forest_type_name = 'Pinus roxburghii - Shorea robusta Forest'
   OR forest_type_name = 'Pinus roxburghii-Shorea robusta Forest';

UPDATE forest_types SET class_number = 25
WHERE forest_type_name = 'Lower Temperate Quercus Forest'
   OR forest_type_name = 'Lower Temperate Pinus roxburghii - Quercus Forest';

-- Log updates
DO $$
BEGIN
    RAISE NOTICE 'Updated forest type class numbers';
END $$;


-- ============================================================================
-- STEP 6: ADD MISSING FOREST TYPES
-- ============================================================================

-- Insert Class 20: Temperate Mixed Broadleaved Forest (if not exists)
INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value)
SELECT
    COALESCE((SELECT MAX(id) FROM forest_types), 0) + 1,
    'Temperate Mixed Broadleaved Forest',
    20,
    20
WHERE NOT EXISTS (
    SELECT 1 FROM forest_types WHERE class_number = 20
);

-- Insert Class 21: Tropical Deciduous Indigenous Riverine Forest (if not exists)
INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value)
SELECT
    COALESCE((SELECT MAX(id) FROM forest_types), 0) + 1,
    'Tropical Deciduous Indigenous Riverine Forest',
    21,
    21
WHERE NOT EXISTS (
    SELECT 1 FROM forest_types WHERE class_number = 21
);

-- Insert Class 23: Lower Temperate Mixed robusta Forest (if not exists)
INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value)
SELECT
    COALESCE((SELECT MAX(id) FROM forest_types), 0) + 1,
    'Lower Temperate Mixed robusta Forest',
    23,
    23
WHERE NOT EXISTS (
    SELECT 1 FROM forest_types WHERE class_number = 23
);

-- Log insertions
DO $$
DECLARE
    total_forest_types INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_forest_types FROM forest_types;
    RAISE NOTICE 'Total forest types now: %', total_forest_types;
END $$;


-- ============================================================================
-- STEP 7: STANDARDIZE FOREST TYPE NAMES (Remove inconsistent hyphens)
-- ============================================================================

UPDATE forest_types
SET forest_type_name = 'Shorea robusta - Mixed Broadleaved Forest'
WHERE forest_type_name = 'Shorea robusta-Mixed Broadleaved Forest';

UPDATE forest_types
SET forest_type_name = 'Pinus roxburghii - Mixed Broadleaved Forest'
WHERE forest_type_name = 'Pinus roxburghii-Mixed Broadleaved Forest';

UPDATE forest_types
SET forest_type_name = 'Pinus roxburghii - Shorea robusta Forest'
WHERE forest_type_name = 'Pinus roxburghii-Shorea robusta Forest';

UPDATE forest_types
SET forest_type_name = 'Terminalia - Tropical Mixed Broadleaved Forest'
WHERE forest_type_name = 'Terminalia-Tropical Mixed Broadleaved Forest';

UPDATE forest_types
SET forest_type_name = 'Dalbergia sissoo - Senegalia catechu Forest'
WHERE forest_type_name = 'Dalbergia sissoo-Senegalia catechu Forest';


-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Count forest types
DO $$
DECLARE
    ft_count INTEGER;
    missing_class_numbers INTEGER;
BEGIN
    SELECT COUNT(*) INTO ft_count FROM forest_types;
    SELECT COUNT(*) INTO missing_class_numbers
    FROM forest_types WHERE class_number IS NULL;

    RAISE NOTICE '=================================================';
    RAISE NOTICE 'VERIFICATION RESULTS:';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Total forest types: %', ft_count;
    RAISE NOTICE 'Forest types without class numbers: %', missing_class_numbers;

    IF ft_count >= 25 THEN
        RAISE NOTICE 'SUCCESS: At least 25 forest types present';
    ELSE
        RAISE WARNING 'WARNING: Only % forest types (expected 25)', ft_count;
    END IF;

    IF missing_class_numbers = 0 THEN
        RAISE NOTICE 'SUCCESS: All forest types have class numbers';
    ELSE
        RAISE WARNING 'WARNING: % forest types missing class numbers', missing_class_numbers;
    END IF;
END $$;

-- Verify generic placeholders removed
DO $$
DECLARE
    placeholder_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO placeholder_count
    FROM tree_species_coefficients
    WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp');

    IF placeholder_count = 0 THEN
        RAISE NOTICE 'SUCCESS: All generic placeholders removed';
    ELSE
        RAISE WARNING 'WARNING: Still % generic placeholders remaining', placeholder_count;
    END IF;
END $$;


-- ============================================================================
-- COMMIT TRANSACTION
-- ============================================================================

COMMIT;

-- Final success message
DO $$
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'PHASE 1A MIGRATION COMPLETED SUCCESSFULLY';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Backup tables created with suffix: _backup_20260215';
    RAISE NOTICE 'To rollback, run: 000_rollback_phase_1.sql';
    RAISE NOTICE 'Next step: Run 002_phase_1b_add_priority_species.sql';
    RAISE NOTICE '=================================================';
END $$;
