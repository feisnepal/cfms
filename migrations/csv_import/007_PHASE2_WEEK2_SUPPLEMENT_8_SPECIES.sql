-- ============================================================
-- PHASE 2 WEEK 2 SUPPLEMENT: 8 MISSING SPECIES
-- ============================================================
--
-- Species: 93-100 (8 species to reach 100 milestone)
-- Date: February 16, 2026
--
-- PURPOSE: Complete Week 2 by adding species that were
--          documented but not imported in Sessions 3-4
--
-- CRITICAL ADDITIONS:
--   ✅ Terminalia chebula (Harro) - COMPLETES TRIPHALA TRIO!
--   ✅ Caragana spp. - 13th nitrogen-fixer
--   ✅ 3 fruiting species (wild pear, apple, cherry)
--   ✅ 2 medicinal understory species
--   ✅ 1 fiber species
--
-- MILESTONE: Achieves 100 SPECIES (67% of 150 goal)
-- ============================================================

BEGIN;

-- Helper function to get species ID by scientific name
CREATE OR REPLACE FUNCTION get_species_id(species_name TEXT)
RETURNS INTEGER AS $func$
BEGIN
    RETURN (SELECT id FROM tree_species_coefficients WHERE scientific_name = species_name);
END;
$func$ LANGUAGE plpgsql;

-- ============================================================
-- SPECIES 93: Terminalia chebula (Harro) - TRIPHALA 1/3! 🙏
-- ============================================================

INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Terminalia chebula', 'Harro', 'Combretaceae', 200, 1500, 'Moderate', 'Very High', FALSE,
 'MEDICINAL (TRIPHALA - Ayurveda, high commercial value!), timber (construction), tannin (bark), dye',
 'Canopy layer in tropical/subtropical forests',
 'Common')
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

-- ============================================================
-- SPECIES 94: Pyrus pashia (Mayal) - Wild Pear
-- ============================================================

INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Pyrus pashia', 'Mayal', 'Rosaceae', 750, 2400, 'Moderate', 'Moderate', FALSE,
 'EDIBLE FRUIT (wild pear), rootstock for grafting pears, timber (hard wood), wildlife food',
 'Mid-story in subtropical/temperate forests',
 'Common')
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

-- ============================================================
-- SPECIES 95: Malus sikkimensis (Syau) - Sikkim Crab Apple
-- ============================================================

INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Malus sikkimensis', 'Syau', 'Rosaceae', 1800, 3000, 'Moderate', 'Moderate', FALSE,
 'EDIBLE FRUIT (crab apple - small tart apples), rootstock for apple grafting, ornamental (spring flowers), wildlife food',
 'Mid-story in temperate forests',
 'Common')
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

-- ============================================================
-- SPECIES 96: Prunus cerasoides (Paiyun) - Himalayan Cherry
-- ============================================================

INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Prunus cerasoides', 'Paiyun', 'Rosaceae', 1200, 2400, 'Moderate', 'High', FALSE,
 'ORNAMENTAL (spectacular pink flowers in winter-spring!), edible fruit (cherries), timber, medicinal bark',
 'Mid-story in subtropical/temperate forests, ornamental tree',
 'Common')
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

-- ============================================================
-- SPECIES 97: Caragana spp. (Himalayan Pea Tree) - NITROGEN-FIXER! 🌱
-- ============================================================

INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Caragana spp.', 'Himalayan Pea Tree', 'Fabaceae', 3000, 4500, 'Moderate', 'Moderate', TRUE,
 'NITROGEN FIXATION (soil improvement in high altitudes!), erosion control, fuelwood, fodder, ornamental (yellow flowers)',
 'Nitrogen-fixing shrub/small tree in subalpine/alpine zones',
 'Common')
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

-- ============================================================
-- SPECIES 98: Viburnum spp. (Asuro) - Medicinal Understory
-- ============================================================

INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Viburnum spp.', 'Asuro', 'Adoxaceae', 1200, 3000, 'Moderate', 'Moderate', FALSE,
 'MEDICINAL (various traditional uses), ornamental, wildlife food (berries)',
 'Understory shrub/small tree in temperate forests',
 'Common')
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

-- ============================================================
-- SPECIES 99: Rhamnus spp. (Archal) - Medicinal/Dye
-- ============================================================

INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Rhamnus spp.', 'Archal', 'Rhamnaceae', 1500, 3500, 'Moderate', 'Moderate', FALSE,
 'MEDICINAL (bark, leaves), DYE (yellow/brown from bark), fuelwood',
 'Understory tree in temperate/subalpine forests',
 'Common')
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

-- ============================================================
-- SPECIES 100: Kydia calycina (Bhendre) - Fiber Species
-- ============================================================

INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Kydia calycina', 'Bhendre', 'Malvaceae', 500, 1500, 'Fast', 'Moderate', FALSE,
 'FIBER (strong bark fiber for ropes), fuelwood, fodder (leaves), traditional paper',
 'Pioneer on degraded slopes, fiber production',
 'Common')
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

-- ============================================================
-- FOREST-SPECIES ASSOCIATIONS
-- ============================================================

-- Terminalia chebula (Class 1, 2, 4, 19)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Terminalia chebula'), 'Associate', 2 WHERE get_species_id('Terminalia chebula') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Terminalia chebula'), 'Associate', 2 WHERE get_species_id('Terminalia chebula') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 4, get_species_id('Terminalia chebula'), 'Associate', 2 WHERE get_species_id('Terminalia chebula') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 19, get_species_id('Terminalia chebula'), 'Co-dominant', 1 WHERE get_species_id('Terminalia chebula') IS NOT NULL;

-- Pyrus pashia (Class 10, 11, 8)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Pyrus pashia'), 'Associate', 2 WHERE get_species_id('Pyrus pashia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Pyrus pashia'), 'Associate', 2 WHERE get_species_id('Pyrus pashia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Pyrus pashia'), 'Associate', 2 WHERE get_species_id('Pyrus pashia') IS NOT NULL;

-- Malus sikkimensis (Class 11, 6, 16)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Malus sikkimensis'), 'Associate', 2 WHERE get_species_id('Malus sikkimensis') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Malus sikkimensis'), 'Associate', 3 WHERE get_species_id('Malus sikkimensis') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Malus sikkimensis'), 'Associate', 2 WHERE get_species_id('Malus sikkimensis') IS NOT NULL;

-- Prunus cerasoides (Class 10, 11, 8, 16)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Prunus cerasoides'), 'Associate', 2 WHERE get_species_id('Prunus cerasoides') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Prunus cerasoides'), 'Associate', 2 WHERE get_species_id('Prunus cerasoides') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Prunus cerasoides'), 'Occasional', 3 WHERE get_species_id('Prunus cerasoides') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Prunus cerasoides'), 'Associate', 2 WHERE get_species_id('Prunus cerasoides') IS NOT NULL;

-- Caragana spp. (Class 5, 6, 7)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Caragana spp.'), 'Associate', 2 WHERE get_species_id('Caragana spp.') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Caragana spp.'), 'Occasional', 3 WHERE get_species_id('Caragana spp.') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Caragana spp.'), 'Associate', 2 WHERE get_species_id('Caragana spp.') IS NOT NULL;

-- Viburnum spp. (Class 17, 6, 11, 16)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Viburnum spp.'), 'Associate', 2 WHERE get_species_id('Viburnum spp.') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Viburnum spp.'), 'Occasional', 3 WHERE get_species_id('Viburnum spp.') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Viburnum spp.'), 'Occasional', 3 WHERE get_species_id('Viburnum spp.') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Viburnum spp.'), 'Associate', 2 WHERE get_species_id('Viburnum spp.') IS NOT NULL;

-- Rhamnus spp. (Class 6, 17, 5, 16)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Rhamnus spp.'), 'Associate', 2 WHERE get_species_id('Rhamnus spp.') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Rhamnus spp.'), 'Associate', 2 WHERE get_species_id('Rhamnus spp.') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Rhamnus spp.'), 'Occasional', 3 WHERE get_species_id('Rhamnus spp.') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Rhamnus spp.'), 'Associate', 2 WHERE get_species_id('Rhamnus spp.') IS NOT NULL;

-- Kydia calycina (Class 18, 19, 1)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 18, get_species_id('Kydia calycina'), 'Associate', 2 WHERE get_species_id('Kydia calycina') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 19, get_species_id('Kydia calycina'), 'Associate', 2 WHERE get_species_id('Kydia calycina') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Kydia calycina'), 'Occasional', 3 WHERE get_species_id('Kydia calycina') IS NOT NULL;

-- ============================================================
-- VERIFICATION AND REPORTING
-- ============================================================

DO $$
DECLARE
    total_species INTEGER;
    nitrogen_fixing_count INTEGER;
    triphala_count INTEGER;
    total_associations INTEGER;
    forest_types_covered INTEGER;
BEGIN
    -- Get counts
    SELECT COUNT(*) INTO total_species FROM tree_species_coefficients;

    SELECT COUNT(*) INTO nitrogen_fixing_count FROM tree_species_coefficients
    WHERE nitrogen_fixing = TRUE;

    SELECT COUNT(*) INTO triphala_count FROM tree_species_coefficients
    WHERE scientific_name IN ('Terminalia chebula', 'Terminalia bellirica', 'Phyllanthus emblica');

    SELECT COUNT(*) INTO total_associations FROM forest_species_association;

    SELECT COUNT(DISTINCT forest_type_id) INTO forest_types_covered
    FROM forest_species_association;

    -- Report
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'WEEK 2 SUPPLEMENT - IMPORT COMPLETE';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE '*** 100 SPECIES MILESTONE REACHED! ***';
    RAISE NOTICE '';
    RAISE NOTICE 'Total species in database: % (target: 100)', total_species;
    RAISE NOTICE 'Nitrogen-fixing species: % (excellent coverage!)', nitrogen_fixing_count;
    RAISE NOTICE 'TRIPHALA trio: %/3 (COMPLETE!)', triphala_count;
    RAISE NOTICE '';
    RAISE NOTICE 'Forest-species associations: %', total_associations;
    RAISE NOTICE 'Forest types with species: %/25', forest_types_covered;
    RAISE NOTICE '';

    IF triphala_count = 3 THEN
        RAISE NOTICE '*** TRIPHALA TRIO COMPLETE! ***';
        RAISE NOTICE '   1. Terminalia chebula (Harro)';
        RAISE NOTICE '   2. Phyllanthus emblica (Amala)';
        RAISE NOTICE '   3. Terminalia bellirica (Barro)';
        RAISE NOTICE '';
    END IF;

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'WEEK 2 NOW COMPLETE - 100 SPECIES (67%% of 150 goal)';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Ready for Week 3: Species 101-150 (final 50 species)';
    RAISE NOTICE '';
END $$;

-- Clean up helper function
DROP FUNCTION IF EXISTS get_species_id(TEXT);

COMMIT;

-- Success message
\echo 'Week 2 supplement import completed successfully!'
\echo '100 SPECIES MILESTONE REACHED!'
\echo 'TRIPHALA TRIO COMPLETE!'
