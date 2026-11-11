-- ============================================================================
-- COMPLETE DATABASE UPDATE - Single Transaction
-- Includes: Phase 1A (Critical Fixes) + Phase 1B (Priority Species)
-- Date: 2026-02-15
-- Database: cf_db
-- ============================================================================

BEGIN;

-- ============================================================================
-- BACKUP TABLES FIRST
-- ============================================================================

DROP TABLE IF EXISTS forest_types_backup_20260215;
CREATE TABLE forest_types_backup_20260215 AS SELECT * FROM forest_types;

DROP TABLE IF EXISTS tree_species_coefficients_backup_20260215;
CREATE TABLE tree_species_coefficients_backup_20260215 AS SELECT * FROM tree_species_coefficients;

DROP TABLE IF EXISTS forest_species_association_backup_20260215;
CREATE TABLE forest_species_association_backup_20260215 AS SELECT * FROM forest_species_association;

-- ============================================================================
-- STEP 1: ADD NEW COLUMNS
-- ============================================================================

-- Add class_number to forest_types
ALTER TABLE forest_types ADD COLUMN IF NOT EXISTS class_number INTEGER;

-- Add new columns to tree_species_coefficients
ALTER TABLE tree_species_coefficients ADD COLUMN IF NOT EXISTS min_altitude_m INTEGER;
ALTER TABLE tree_species_coefficients ADD COLUMN IF NOT EXISTS max_altitude_m INTEGER;
ALTER TABLE tree_species_coefficients ADD COLUMN IF NOT EXISTS growth_rate VARCHAR(20);
ALTER TABLE tree_species_coefficients ADD COLUMN IF NOT EXISTS economic_value VARCHAR(20);
ALTER TABLE tree_species_coefficients ADD COLUMN IF NOT EXISTS nitrogen_fixing BOOLEAN DEFAULT FALSE;
ALTER TABLE tree_species_coefficients ADD COLUMN IF NOT EXISTS main_uses TEXT;
ALTER TABLE tree_species_coefficients ADD COLUMN IF NOT EXISTS ecological_role TEXT;
ALTER TABLE tree_species_coefficients ADD COLUMN IF NOT EXISTS rarity_status VARCHAR(20) DEFAULT 'Common';
ALTER TABLE tree_species_coefficients ADD COLUMN IF NOT EXISTS family VARCHAR(100);

-- ============================================================================
-- STEP 2: UPDATE FOREST TYPE CLASS NUMBERS (Forest Regulation 2079)
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
-- STEP 3: INSERT MISSING FOREST TYPES (Classes 20, 21, 23)
-- ============================================================================

INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value)
SELECT COALESCE(MAX(id), 0) + 1, 'Temperate Mixed Broadleaved Forest', 20, 20
FROM forest_types
WHERE NOT EXISTS (SELECT 1 FROM forest_types WHERE class_number = 20);

INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value)
SELECT COALESCE(MAX(id), 0) + 1, 'Tropical Deciduous Indigenous Riverine Forest', 21, 21
FROM forest_types
WHERE NOT EXISTS (SELECT 1 FROM forest_types WHERE class_number = 21);

INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value)
SELECT COALESCE(MAX(id), 0) + 1, 'Lower Temperate Mixed robusta Forest', 23, 23
FROM forest_types
WHERE NOT EXISTS (SELECT 1 FROM forest_types WHERE class_number = 23);

-- ============================================================================
-- STEP 4: REMOVE GENERIC PLACEHOLDER SPECIES
-- ============================================================================

-- Delete associations first (foreign key constraint)
DELETE FROM forest_species_association
WHERE species_id IN (
    SELECT id FROM tree_species_coefficients
    WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp')
);

-- Delete generic species
DELETE FROM tree_species_coefficients
WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp');

-- ============================================================================
-- STEP 5: UPDATE SPECIES TAXONOMY (Modern Scientific Names)
-- ============================================================================

-- Update Eugenia jambolana to Syzygium cumini
UPDATE tree_species_coefficients
SET scientific_name = 'Syzygium cumini',
    local_name = COALESCE(local_name, 'Jamun')
WHERE scientific_name IN ('Eugenia jambolana', 'Eugenia Jambolana');

-- Update Adina cordifolia to Haldina cordifolia
UPDATE tree_species_coefficients
SET scientific_name = 'Haldina cordifolia',
    local_name = COALESCE(local_name, 'Karma')
WHERE scientific_name = 'Adina cordifolia';

-- ============================================================================
-- STEP 6: INSERT 10 PRIORITY SPECIES (Phase 1B)
-- ============================================================================

INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, max_height_m, max_dbh_cm, wood_density_g_cm3,
 biomass_expansion_factor, carbon_fraction, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Castanopsis tribuloides', 'Katus', 'Fagaceae', 10.00, 60, 0.67, 1.45, 0.47, 1200, 2400, 'Moderate', 'High', FALSE, 'Timber and fuelwood', 'Dominant canopy species in mid-hills', 'Common'),
('Quercus glauca', 'Phalant', 'Fagaceae', 20.00, 100, 0.75, 1.40, 0.47, 1500, 2500, 'Slow', 'High', FALSE, 'Timber and fuelwood', 'Dominant temperate broadleaf', 'Common'),
('Lyonia ovalifolia', 'Angeri', 'Ericaceae', 15.00, 40, 0.60, 1.50, 0.47, 1200, 2700, 'Moderate', 'Low', FALSE, 'Fuelwood and fodder', 'Understory species', 'Common'),
('Symplocos ramosissima', 'Kharane', 'Symplocaceae', 12.00, 35, 0.65, 1.48, 0.47, 1000, 2400, 'Moderate', 'Moderate', FALSE, 'Fuelwood and traditional medicine', 'Mid-story species', 'Common'),
('Castanopsis indica', 'Dhale Katus', 'Fagaceae', 25.00, 120, 0.70, 1.42, 0.47, 900, 2200, 'Moderate', 'High', FALSE, 'Timber and construction', 'Dominant broadleaf canopy', 'Common'),
('Machilus gamblei', 'Kawla', 'Lauraceae', 20.00, 80, 0.68, 1.44, 0.47, 1200, 2400, 'Moderate', 'High', FALSE, 'Timber and traditional uses', 'Mid to upper canopy', 'Common'),
('Syzygium cumini', 'Jamun', 'Myrtaceae', 15.00, 70, 0.72, 1.40, 0.47, 100, 1500, 'Fast', 'Moderate', FALSE, 'Fruit and timber', 'Tropical broadleaf', 'Common'),
('Haldina cordifolia', 'Karma', 'Rubiaceae', 25.00, 100, 0.62, 1.46, 0.47, 100, 1200, 'Fast', 'High', FALSE, 'Timber and pulpwood', 'Dominant tropical species', 'Common'),
('Ficus religiosa', 'Peepal', 'Moraceae', 30.00, 150, 0.45, 1.55, 0.47, 100, 1800, 'Fast', 'Moderate', FALSE, 'Sacred tree and shade', 'Ecological keystone', 'Common'),
('Ficus benghalensis', 'Bar', 'Moraceae', 25.00, 200, 0.48, 1.52, 0.47, 100, 1500, 'Moderate', 'Moderate', FALSE, 'Sacred tree and shade', 'Ecological keystone', 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    max_dbh_cm = EXCLUDED.max_dbh_cm,
    wood_density_g_cm3 = EXCLUDED.wood_density_g_cm3,
    biomass_expansion_factor = EXCLUDED.biomass_expansion_factor,
    carbon_fraction = EXCLUDED.carbon_fraction,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    nitrogen_fixing = EXCLUDED.nitrogen_fixing,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role,
    rarity_status = EXCLUDED.rarity_status;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    ft_count INTEGER;
    ft_with_class INTEGER;
    species_count INTEGER;
    placeholders INTEGER;
BEGIN
    SELECT COUNT(*) INTO ft_count FROM forest_types;
    SELECT COUNT(*) INTO ft_with_class FROM forest_types WHERE class_number IS NOT NULL;
    SELECT COUNT(*) INTO species_count FROM tree_species_coefficients;
    SELECT COUNT(*) INTO placeholders FROM tree_species_coefficients
    WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp');

    RAISE NOTICE '=================================================';
    RAISE NOTICE 'DATABASE UPDATE COMPLETED SUCCESSFULLY';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Total forest types: %', ft_count;
    RAISE NOTICE 'Forest types with class numbers: %', ft_with_class;
    RAISE NOTICE 'Total tree species: %', species_count;
    RAISE NOTICE 'Generic placeholders remaining: %', placeholders;

    IF ft_count >= 25 THEN
        RAISE NOTICE 'SUCCESS: At least 25 forest types present';
    ELSE
        RAISE WARNING 'WARNING: Only % forest types (expected 25+)', ft_count;
    END IF;

    IF placeholders = 0 THEN
        RAISE NOTICE 'SUCCESS: All generic placeholders removed';
    ELSE
        RAISE WARNING 'WARNING: Still % placeholders remaining', placeholders;
    END IF;

    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Backup tables: *_backup_20260215';
    RAISE NOTICE '=================================================';
END $$;

COMMIT;
