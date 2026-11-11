-- ============================================================================
-- CLEAN DATABASE IMPORT - FIXED VERSION
-- Description: Replace all forest types with 25 AUTHORIZED types
-- Date: 2026-02-16
-- Database: cf_db
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 0: CREATE BACKUPS
-- ============================================================================

DROP TABLE IF EXISTS forest_types_backup_20260216;
CREATE TABLE forest_types_backup_20260216 AS SELECT * FROM forest_types;

DROP TABLE IF EXISTS tree_species_coefficients_backup_20260216;
CREATE TABLE tree_species_coefficients_backup_20260216 AS SELECT * FROM tree_species_coefficients;

DROP TABLE IF EXISTS forest_species_association_backup_20260216;
CREATE TABLE forest_species_association_backup_20260216 AS SELECT * FROM forest_species_association;

-- ============================================================================
-- STEP 1: ADD class_number COLUMN (if not exists)
-- ============================================================================

ALTER TABLE forest_types ADD COLUMN IF NOT EXISTS class_number INTEGER;

-- ============================================================================
-- STEP 2: CLEAR OUT ALL FOREST TYPE DATA
-- ============================================================================

-- Delete all forest-species associations (foreign key constraint)
DELETE FROM forest_species_association WHERE forest_type_id IS NOT NULL;

-- Delete all existing forest types
DELETE FROM forest_types;

-- ============================================================================
-- STEP 3: INSERT 25 AUTHORIZED FOREST TYPES
-- ============================================================================

INSERT INTO forest_types (id, forest_type_name, class_number, pixel_value) VALUES
(1, 'Shorea robusta Forest', 1, 1),
(2, 'Tropical Mixed Broadleaved Forest', 2, 2),
(3, 'Subtropical Mixed Broadleaved Forest', 3, 3),
(4, 'Shorea robusta - Mixed Broadleaved Forest', 4, 4),
(5, 'Abies Mixed Forest', 5, 5),
(6, 'Upper Temperate Coniferous Forest', 6, 6),
(7, 'Cool Temperate Mixed Broadleaved Forest', 7, 7),
(8, 'Castanopsis Lower Temperate Mixed Broadleaved Forest', 8, 8),
(9, 'Pinus roxburghii Forest', 9, 9),
(10, 'Alnus Forest', 10, 10),
(11, 'Schima Forest', 11, 11),
(12, 'Pinus roxburghii - Mixed Broadleaved Forest', 12, 12),
(13, 'Pinus wallichiana Forest', 13, 13),
(14, 'Warm Temperate Mixed Broadleaved Forest', 14, 14),
(15, 'Upper Temperate Quercus Forest', 15, 15),
(16, 'Rhododendron arboreum Forest', 16, 16),
(17, 'Temperate Rhododendron Mixed Broadleaved Forest', 17, 17),
(18, 'Dalbergia sissoo-Senegalia catechu Forest', 18, 18),
(19, 'Terminalia - Tropical Mixed Broadleaved Forest', 19, 19),
(20, 'Temperate Mixed Broadleaved Forest', 20, 20),
(21, 'Tropical Deciduous Indigenous Riverine Forest', 21, 21),
(22, 'Tropical Riverine Forest', 22, 22),
(23, 'Lower Temperate Mixed robusta Forest', 23, 23),
(24, 'Pinus roxburghii - Shorea robusta Forest', 24, 24),
(25, 'Lower Temperate Pinus roxburghii - Quercus Forest', 25, 25);

-- ============================================================================
-- STEP 4: ADD NEW COLUMNS TO tree_species_coefficients (ONLY NEW ONES)
-- ============================================================================

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
-- STEP 5: REMOVE GENERIC PLACEHOLDER SPECIES
-- ============================================================================

-- Delete associations for generic placeholders
DELETE FROM forest_species_association
WHERE species_id IN (
    SELECT id FROM tree_species_coefficients
    WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp')
);

-- Delete generic placeholder species
DELETE FROM tree_species_coefficients
WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp');

-- ============================================================================
-- STEP 6: UPDATE SPECIES TAXONOMY
-- ============================================================================

UPDATE tree_species_coefficients
SET scientific_name = 'Syzygium cumini',
    local_name = COALESCE(local_name, 'Jamun')
WHERE scientific_name IN ('Eugenia jambolana', 'Eugenia Jambolana');

UPDATE tree_species_coefficients
SET scientific_name = 'Haldina cordifolia',
    local_name = COALESCE(local_name, 'Karma')
WHERE scientific_name = 'Adina cordifolia';

-- ============================================================================
-- STEP 7: INSERT 10 PRIORITY SPECIES (SIMPLIFIED - ONLY BASIC COLUMNS)
-- ============================================================================

-- Only insert into columns that definitely exist or were just added
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Castanopsis tribuloides', 'Katus', 'Fagaceae', 1200, 2400, 'Moderate', 'High', FALSE, 'Timber and fuelwood', 'Dominant canopy species in mid-hills', 'Common'),
('Quercus glauca', 'Phalant', 'Fagaceae', 1500, 2500, 'Slow', 'High', FALSE, 'Timber and fuelwood', 'Dominant temperate broadleaf', 'Common'),
('Lyonia ovalifolia', 'Angeri', 'Ericaceae', 1200, 2700, 'Moderate', 'Low', FALSE, 'Fuelwood and fodder', 'Understory species', 'Common'),
('Symplocos ramosissima', 'Kharane', 'Symplocaceae', 1000, 2400, 'Moderate', 'Moderate', FALSE, 'Fuelwood and traditional medicine', 'Mid-story species', 'Common'),
('Castanopsis indica', 'Dhale Katus', 'Fagaceae', 900, 2200, 'Moderate', 'High', FALSE, 'Timber and construction', 'Dominant broadleaf canopy', 'Common'),
('Machilus gamblei', 'Kawla', 'Lauraceae', 1200, 2400, 'Moderate', 'High', FALSE, 'Timber and traditional uses', 'Mid to upper canopy', 'Common'),
('Syzygium cumini', 'Jamun', 'Myrtaceae', 100, 1500, 'Fast', 'Moderate', FALSE, 'Fruit and timber', 'Tropical broadleaf', 'Common'),
('Haldina cordifolia', 'Karma', 'Rubiaceae', 100, 1200, 'Fast', 'High', FALSE, 'Timber and pulpwood', 'Dominant tropical species', 'Common'),
('Ficus religiosa', 'Peepal', 'Moraceae', 100, 1800, 'Fast', 'Moderate', FALSE, 'Sacred tree and shade', 'Ecological keystone', 'Common'),
('Ficus benghalensis', 'Bar', 'Moraceae', 100, 1500, 'Moderate', 'Moderate', FALSE, 'Sacred tree and shade', 'Ecological keystone', 'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
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
    RAISE NOTICE 'CLEAN IMPORT COMPLETED SUCCESSFULLY';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Total forest types: % (Expected: 25)', ft_count;
    RAISE NOTICE 'Forest types with class numbers: %', ft_with_class;
    RAISE NOTICE 'Total tree species: %', species_count;
    RAISE NOTICE 'Generic placeholders remaining: %', placeholders;

    IF ft_count = 25 THEN
        RAISE NOTICE 'SUCCESS: Exactly 25 forest types present';
    ELSE
        RAISE WARNING 'WARNING: Expected 25 forest types but got %', ft_count;
    END IF;

    IF ft_with_class = 25 THEN
        RAISE NOTICE 'SUCCESS: All 25 forest types have class numbers';
    ELSE
        RAISE WARNING 'WARNING: Only % forest types have class numbers', ft_with_class;
    END IF;

    IF placeholders = 0 THEN
        RAISE NOTICE 'SUCCESS: All generic placeholders removed';
    ELSE
        RAISE WARNING 'WARNING: Still % placeholders remaining', placeholders;
    END IF;

    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Backup tables: *_backup_20260216';
    RAISE NOTICE '=================================================';
END $$;

COMMIT;
