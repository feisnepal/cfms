-- ============================================================================
-- PHASE 2 SESSION 1: CLASS 20 + NITROGEN-FIXERS (12 Species)
-- Description: Complete Class 20 coverage + add 6 nitrogen-fixing species
-- Date: 2026-02-16
-- Database: cf_db
-- Source: PHASE_2_SPECIES_RESEARCH_TRACKER.md (Session 1)
-- Schema: Uses actual forest_species_association columns (role, availability_rank)
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 1: INSERT 12 NEW SPECIES (21-32)
-- ============================================================================

-- Species 21: Acer campbellii (Campbell's Maple)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Acer campbellii', 'Phalant Maple', 'Sapindaceae', 2400, 3600, 'Moderate', 'Moderate', FALSE,
 'Timber (furniture), fuelwood, ornamental (autumn colors)',
 'Canopy to mid-story in temperate broadleaf forests', 'Common')
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

-- Species 22: Acer sterculiaceum (Hairy Maple)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Acer sterculiaceum', 'Phalant', 'Sapindaceae', 1800, 3000, 'Moderate', 'Moderate', FALSE,
 'Timber (light construction), fuelwood, ornamental',
 'Co-dominant in temperate mixed broadleaf forests', 'Common')
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

-- Species 23: Lindera neesiana (Siltimur)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Lindera neesiana', 'Siltimur', 'Lauraceae', 1800, 3000, 'Moderate', 'Low', FALSE,
 'Medicinal (bark, leaves), fuelwood, aromatic',
 'Understory to mid-story in temperate forests', 'Common')
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

-- Species 24: Litsea monopetala (Kutmero)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Litsea monopetala', 'Kutmero', 'Lauraceae', 1500, 2700, 'Moderate', 'Moderate', FALSE,
 'Medicinal (bark, leaves), aromatic oil, fuelwood',
 'Mid-story in temperate mixed forests', 'Common')
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

-- Species 25: Quercus lamellosa (Lamellate Oak)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Quercus lamellosa', 'Banjh, Phaledo', 'Fagaceae', 1800, 2700, 'Slow', 'High', FALSE,
 'Fuelwood (very high quality), timber (construction), fodder (leaves)',
 'Dominant canopy in temperate mixed broadleaf forests', 'Common')
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

-- Species 26: Magnolia campbellii (Campbell's Magnolia) - RARE
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Magnolia campbellii', 'Champ, Lali Gurans', 'Magnoliaceae', 2400, 3000, 'Slow', 'High', FALSE,
 'Ornamental (spectacular flowers), timber (light construction), medicinal',
 'Emergent layer in temperate forests, rare and valuable', 'RARE - Vulnerable')
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

-- Species 27: Albizia chinensis (Chinese Siris) - NITROGEN FIXING
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Albizia chinensis', 'Siris', 'Fabaceae', 300, 1500, 'Fast', 'High', TRUE,
 'Timber (construction, furniture), fuelwood, soil improvement, shade',
 'Canopy layer, nitrogen-fixing pioneer', 'Common')
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

-- Species 28: Albizia lebbeck (Siris) - NITROGEN FIXING
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Albizia lebbeck', 'Siris, Sirus', 'Fabaceae', 100, 1200, 'Fast', 'High', TRUE,
 'Agroforestry (shade for crops), fuelwood, timber, fodder (pods for livestock)',
 'Canopy layer, nitrogen-fixing, provides dense shade', 'Common')
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

-- Species 29: Albizia procera (White Siris) - NITROGEN FIXING
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Albizia procera', 'Safed Siris', 'Fabaceae', 200, 1000, 'Fast', 'Moderate', TRUE,
 'Fuelwood, soil improvement, shade, fodder (leaves)',
 'Canopy layer, nitrogen-fixing pioneer', 'Common')
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

-- Species 30: Acacia concinna (Shikakai) - NITROGEN FIXING
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Acacia concinna', 'Shikakai', 'Fabaceae', 200, 1000, 'Moderate', 'High', TRUE,
 'MEDICINAL (hair care - pods as shampoo), nitrogen fixation, fodder',
 'Understory/climbing, nitrogen-fixing, supports canopy trees', 'Common')
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

-- Species 31: Bauhinia variegata (Orchid Tree) - NITROGEN FIXING
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Bauhinia variegata', 'Koiralo', 'Fabaceae', 300, 1500, 'Moderate', 'Moderate', TRUE,
 'ORNAMENTAL (beautiful flowers), medicinal (bark, leaves), fodder (leaves), nitrogen fixation',
 'Understory to mid-story, nitrogen-fixing ornamental', 'Common')
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

-- Species 32: Erythrina arborescens (Coral Tree) - NITROGEN FIXING
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Erythrina arborescens', 'Phaledo', 'Fabaceae', 500, 1800, 'Fast', 'High', TRUE,
 'ORNAMENTAL (spectacular red flowers), living fence, shade for coffee/cardamom, soil improvement, fodder',
 'Canopy layer in open forests, nitrogen-fixing ornamental', 'Common')
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
-- STEP 2: ADD FOREST-SPECIES ASSOCIATIONS
-- ============================================================================

-- Helper function to get species ID by scientific name
CREATE OR REPLACE FUNCTION get_species_id(species_name TEXT) RETURNS INTEGER AS $$
DECLARE
    species_id INTEGER;
BEGIN
    SELECT id INTO species_id
    FROM tree_species_coefficients
    WHERE scientific_name = species_name
    LIMIT 1;

    RETURN species_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- CLASS 20: Temperate Mixed Broadleaved Forest (COMPLETE!)
-- ============================================================================

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Acer campbellii'), 'Dominant', 1 WHERE get_species_id('Acer campbellii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Acer sterculiaceum'), 'Dominant', 1 WHERE get_species_id('Acer sterculiaceum') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Quercus lamellosa'), 'Dominant', 1 WHERE get_species_id('Quercus lamellosa') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Lindera neesiana'), 'Associate', 2 WHERE get_species_id('Lindera neesiana') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Litsea monopetala'), 'Associate', 2 WHERE get_species_id('Litsea monopetala') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Symplocos ramosissima'), 'Associate', 2 WHERE get_species_id('Symplocos ramosissima') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Machilus gamblei'), 'Associate', 3 WHERE get_species_id('Machilus gamblei') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Magnolia campbellii'), 'Occasional', 4 WHERE get_species_id('Magnolia campbellii') IS NOT NULL;

-- ============================================================================
-- ADDITIONAL ASSOCIATIONS FOR ACER SPECIES
-- ============================================================================

-- Acer campbellii in other forest types
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Acer campbellii'), 'Associate', 3 WHERE get_species_id('Acer campbellii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Acer campbellii'), 'Associate', 3 WHERE get_species_id('Acer campbellii') IS NOT NULL;

-- Acer sterculiaceum in Class 7
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Acer sterculiaceum'), 'Dominant', 1 WHERE get_species_id('Acer sterculiaceum') IS NOT NULL;

-- ============================================================================
-- NITROGEN-FIXING SPECIES ASSOCIATIONS
-- ============================================================================

-- Albizia chinensis (Class 2, 18, 21)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Albizia chinensis'), 'Associate', 3 WHERE get_species_id('Albizia chinensis') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 18, get_species_id('Albizia chinensis'), 'Associate', 3 WHERE get_species_id('Albizia chinensis') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 21, get_species_id('Albizia chinensis'), 'Associate', 3 WHERE get_species_id('Albizia chinensis') IS NOT NULL;

-- Albizia lebbeck (Class 2, 18, 21)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Albizia lebbeck'), 'Associate', 3 WHERE get_species_id('Albizia lebbeck') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 18, get_species_id('Albizia lebbeck'), 'Associate', 3 WHERE get_species_id('Albizia lebbeck') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 21, get_species_id('Albizia lebbeck'), 'Dominant', 1 WHERE get_species_id('Albizia lebbeck') IS NOT NULL;

-- Albizia procera (Class 2, 18)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Albizia procera'), 'Associate', 4 WHERE get_species_id('Albizia procera') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 18, get_species_id('Albizia procera'), 'Associate', 4 WHERE get_species_id('Albizia procera') IS NOT NULL;

-- Acacia concinna (Class 1, 18)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Acacia concinna'), 'Occasional', 4 WHERE get_species_id('Acacia concinna') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 18, get_species_id('Acacia concinna'), 'Associate', 3 WHERE get_species_id('Acacia concinna') IS NOT NULL;

-- Bauhinia variegata (Class 2, 3, 11)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Bauhinia variegata'), 'Associate', 4 WHERE get_species_id('Bauhinia variegata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Bauhinia variegata'), 'Associate', 4 WHERE get_species_id('Bauhinia variegata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Bauhinia variegata'), 'Associate', 4 WHERE get_species_id('Bauhinia variegata') IS NOT NULL;

-- Erythrina arborescens (Class 3, 9, 11)
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Erythrina arborescens'), 'Associate', 4 WHERE get_species_id('Erythrina arborescens') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 9, get_species_id('Erythrina arborescens'), 'Occasional', 4 WHERE get_species_id('Erythrina arborescens') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Erythrina arborescens'), 'Associate', 4 WHERE get_species_id('Erythrina arborescens') IS NOT NULL;

-- Drop helper function
DROP FUNCTION get_species_id(TEXT);

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    total_species INTEGER;
    total_associations INTEGER;
    forest_types_covered INTEGER;
    nitrogen_fixers INTEGER;
    class20_species INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_species FROM tree_species_coefficients;
    SELECT COUNT(*) INTO total_associations FROM forest_species_association;
    SELECT COUNT(DISTINCT forest_type_id) INTO forest_types_covered FROM forest_species_association;
    SELECT COUNT(*) INTO nitrogen_fixers FROM tree_species_coefficients WHERE nitrogen_fixing = TRUE;
    SELECT COUNT(*) INTO class20_species FROM forest_species_association WHERE forest_type_id = 20;

    RAISE NOTICE '================================================';
    RAISE NOTICE 'PHASE 2 SESSION 1 - IMPORT COMPLETE';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Total species in database: %', total_species;
    RAISE NOTICE 'Total forest-species associations: %', total_associations;
    RAISE NOTICE 'Forest types with species data: %/25', forest_types_covered;
    RAISE NOTICE 'Nitrogen-fixing species: %', nitrogen_fixers;
    RAISE NOTICE 'Class 20 species count: %', class20_species;
    RAISE NOTICE '================================================';

    -- Show species count by role
    RAISE NOTICE 'Association role breakdown:';
    RAISE NOTICE '  Dominant: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Dominant');
    RAISE NOTICE '  Co-dominant: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Co-dominant');
    RAISE NOTICE '  Associate: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Associate');
    RAISE NOTICE '  Occasional: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Occasional');
    RAISE NOTICE '================================================';

    -- Check if ALL 25 forest types are covered
    IF forest_types_covered = 25 THEN
        RAISE NOTICE '*** SUCCESS: ALL 25 FOREST TYPES NOW HAVE SPECIES! ***';
    ELSE
        RAISE NOTICE 'WARNING: Only % forest types covered (target: 25)', forest_types_covered;
    END IF;
    RAISE NOTICE '================================================';
END $$;

COMMIT;
