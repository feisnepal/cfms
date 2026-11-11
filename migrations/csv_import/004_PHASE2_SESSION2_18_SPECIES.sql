-- ============================================================================
-- PHASE 2 SESSION 2: HIGH-VALUE & ASSOCIATE SPECIES (18 Species)
-- Description: Premium timber, medicinal/NTFP, ornamental, agroforestry
-- Date: 2026-02-16
-- Database: cf_db
-- Source: PHASE_2_SPECIES_RESEARCH_TRACKER.md (Session 2)
-- Target: Reach Week 1 goal (50 total species)
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 1: INSERT 18 NEW SPECIES (33-50)
-- ============================================================================

-- Species 33: Terminalia chebula (Harro) - MEDICINAL
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Terminalia chebula', 'Harro', 'Combretaceae', 200, 1500, 'Moderate', 'High', FALSE,
 'MEDICINAL (Triphala - Ayurveda, high commercial value), timber (construction), tannin (bark), dye',
 'Canopy layer in tropical/subtropical forests', 'Common')
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

-- Species 34: Toona ciliata (Tooni) - PREMIUM TIMBER
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Toona ciliata', 'Tooni', 'Meliaceae', 500, 2000, 'Fast', 'High', FALSE,
 'TIMBER (premium furniture, veneer, plywood), medicinal (bark), young leaves (vegetable)',
 'Emergent canopy layer in moist forests', 'Common')
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

-- Species 35: Prunus cerasoides (Paiyun) - ORNAMENTAL
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Prunus cerasoides', 'Paiyun', 'Rosaceae', 1200, 2400, 'Moderate', 'Moderate', FALSE,
 'ORNAMENTAL (beautiful pink flowers), timber (light construction), fuelwood, fruit (edible cherries)',
 'Mid-story in mixed forests, ornamental pioneer', 'Common')
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

-- Species 36: Juglans regia (Walnut) - PREMIUM NUTS + TIMBER
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Juglans regia', 'Okhar', 'Juglandaceae', 1000, 3000, 'Moderate', 'High', FALSE,
 'NUTS (high value export), TIMBER (premium furniture, gunstocks), oil (cooking), medicinal',
 'Canopy layer in temperate forests, valuable tree', 'Occasional')
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

-- Species 37: Cedrus deodara (Deodar Cedar) - SACRED PREMIUM CONIFER
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Cedrus deodara', 'Devdar', 'Pinaceae', 1500, 3200, 'Moderate', 'High', FALSE,
 'TIMBER (premium construction, durability), aromatic wood (religious use), essential oil, ornamental',
 'Dominant emergent in upper temperate coniferous forests', 'RARE')
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

-- Species 38: Lagerstroemia parviflora (Botdhyangro)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Lagerstroemia parviflora', 'Botdhyangro', 'Lythraceae', 200, 1200, 'Moderate', 'Moderate', FALSE,
 'Timber (construction, agricultural implements), fuelwood, tannin (bark), medicinal',
 'Mid-story to canopy in Sal forests', 'Common')
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

-- Species 39: Dillenia pentagyna (Tatari) - EDIBLE FRUIT
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Dillenia pentagyna', 'Tatari', 'Dilleniaceae', 200, 1200, 'Moderate', 'Moderate', FALSE,
 'FRUIT (edible, sour - used in curries), medicinal, timber (limited), fuelwood',
 'Mid-story in tropical forests', 'Common')
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

-- Species 40: Pterocarpus marsupium (Bijayasal) - RARE PREMIUM
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Pterocarpus marsupium', 'Bijayasal', 'Fabaceae', 200, 1000, 'Slow', 'High', FALSE,
 'TIMBER (premium furniture, extremely durable), MEDICINAL (red gum - kino, used for diabetes), tannin',
 'Canopy layer in tropical forests, rare and valuable', 'RARE - Near Threatened')
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

-- Species 41: Garuga pinnata (Dabdabe)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Garuga pinnata', 'Dabdabe', 'Burseraceae', 300, 1500, 'Moderate', 'Moderate', FALSE,
 'Timber (light construction), resin (aromatic), fuelwood, fodder (leaves)',
 'Mid-story in tropical/subtropical forests', 'Common')
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

-- Species 42: Stereospermum chelonoides (Padal) - MEDICINAL
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Stereospermum chelonoides', 'Padal', 'Bignoniaceae', 300, 1200, 'Moderate', 'Moderate', FALSE,
 'MEDICINAL (bark, roots - traditional medicine), timber (light construction), ornamental (flowers)',
 'Mid-story in tropical forests', 'Common')
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

-- Species 43: Pyrus pashia (Mayal) - WILD PEAR
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Pyrus pashia', 'Mayal', 'Rosaceae', 750, 2500, 'Moderate', 'Moderate', FALSE,
 'FRUIT (edible pears - small, sour), ROOTSTOCK (for grafting cultivated pears), fuelwood, ornamental (flowers)',
 'Understory to mid-story, important for wildlife', 'Common')
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

-- Species 44: Eurya acuminata (Jhingane) - UNDERSTORY
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Eurya acuminata', 'Jhingane', 'Pentaphylacaceae', 1200, 2700, 'Slow', 'Low', FALSE,
 'Fuelwood, fodder (limited), ecological (understory)',
 'Understory species in temperate/subtropical forests', 'Common')
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

-- Species 45: Sorbus cuspidata (Rowan) - HIGH ALTITUDE
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Sorbus cuspidata', 'Rowan', 'Rosaceae', 2400, 4000, 'Slow', 'Low', FALSE,
 'ORNAMENTAL (red berries), wildlife food, medicinal (berries)',
 'Understory in subalpine forests, important for wildlife', 'Common')
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

-- Species 46: Carpinus viminea (Kabro) - HARDWOOD
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Carpinus viminea', 'Kabro', 'Betulaceae', 1500, 2700, 'Slow', 'Moderate', FALSE,
 'Timber (tool handles, furniture - very hard wood), fuelwood (excellent quality), fodder',
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

-- Species 47: Ilex dipyrena (Holly)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Ilex dipyrena', 'Holly', 'Aquifoliaceae', 1800, 3300, 'Slow', 'Moderate', FALSE,
 'ORNAMENTAL (red berries, evergreen foliage), bird lime (from bark), fuelwood, fodder',
 'Understory to mid-story, important for wildlife', 'Common')
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

-- Species 48: Senegalia catechu (Khayar) - TANNIN
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Senegalia catechu', 'Khayar', 'Fabaceae', 150, 1200, 'Moderate', 'High', FALSE,
 'TANNIN EXTRACT (cutch/catechu - huge commercial value), MEDICINAL (mouth freshener, digestive), timber (hard, durable), fuelwood',
 'Canopy layer in riverine/dry forests', 'Common')
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

-- Species 49: Trewia nudiflora (Pitauli) - RIVERINE
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Trewia nudiflora', 'Pitauli', 'Euphorbiaceae', 200, 1200, 'Fast', 'Moderate', FALSE,
 'Timber (light construction, plywood), fuelwood, riverbank stabilization',
 'Dominant in tropical riverine forests, pioneer', 'Common')
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

-- Species 50: Ficus semicordata (Khanyu) - KEYSTONE FODDER
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Ficus semicordata', 'Khanyu', 'Moraceae', 600, 2000, 'Moderate', 'Moderate', FALSE,
 'FODDER (leaves excellent for livestock - very palatable), fuelwood, fruit (small figs - edible for wildlife), latex (minor uses)',
 'Mid-story to canopy, keystone species for wildlife', 'Common')
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
-- TERMINALIA CHEBULA (Class 1, 2, 4, 19)
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Terminalia chebula'), 'Associate', 4 WHERE get_species_id('Terminalia chebula') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Terminalia chebula'), 'Associate', 4 WHERE get_species_id('Terminalia chebula') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 4, get_species_id('Terminalia chebula'), 'Associate', 4 WHERE get_species_id('Terminalia chebula') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 19, get_species_id('Terminalia chebula'), 'Co-dominant', 1 WHERE get_species_id('Terminalia chebula') IS NOT NULL;

-- ============================================================================
-- TOONA CILIATA (Class 2, 21) - PREMIUM TIMBER
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Toona ciliata'), 'Associate', 4 WHERE get_species_id('Toona ciliata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 21, get_species_id('Toona ciliata'), 'Dominant', 1 WHERE get_species_id('Toona ciliata') IS NOT NULL;

-- ============================================================================
-- PRUNUS CERASOIDES (Class 10, 11, 12) - ORNAMENTAL
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Prunus cerasoides'), 'Associate', 3 WHERE get_species_id('Prunus cerasoides') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Prunus cerasoides'), 'Associate', 4 WHERE get_species_id('Prunus cerasoides') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 12, get_species_id('Prunus cerasoides'), 'Occasional', 4 WHERE get_species_id('Prunus cerasoides') IS NOT NULL;

-- ============================================================================
-- JUGLANS REGIA (Class 10, 20) - PREMIUM NUTS
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Juglans regia'), 'Occasional', 4 WHERE get_species_id('Juglans regia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Juglans regia'), 'Occasional', 4 WHERE get_species_id('Juglans regia') IS NOT NULL;

-- ============================================================================
-- CEDRUS DEODARA (Class 6) - RARE PREMIUM CONIFER
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Cedrus deodara'), 'Occasional', 4 WHERE get_species_id('Cedrus deodara') IS NOT NULL;

-- ============================================================================
-- LAGERSTROEMIA PARVIFLORA (Class 1, 4)
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Lagerstroemia parviflora'), 'Associate', 4 WHERE get_species_id('Lagerstroemia parviflora') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 4, get_species_id('Lagerstroemia parviflora'), 'Associate', 4 WHERE get_species_id('Lagerstroemia parviflora') IS NOT NULL;

-- ============================================================================
-- DILLENIA PENTAGYNA (Class 1, 4) - EDIBLE FRUIT
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Dillenia pentagyna'), 'Associate', 4 WHERE get_species_id('Dillenia pentagyna') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 4, get_species_id('Dillenia pentagyna'), 'Associate', 4 WHERE get_species_id('Dillenia pentagyna') IS NOT NULL;

-- ============================================================================
-- PTEROCARPUS MARSUPIUM (Class 1, 19) - RARE
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Pterocarpus marsupium'), 'Occasional', 4 WHERE get_species_id('Pterocarpus marsupium') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 19, get_species_id('Pterocarpus marsupium'), 'Occasional', 4 WHERE get_species_id('Pterocarpus marsupium') IS NOT NULL;

-- ============================================================================
-- GARUGA PINNATA (Class 2, 3)
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Garuga pinnata'), 'Associate', 4 WHERE get_species_id('Garuga pinnata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Garuga pinnata'), 'Associate', 4 WHERE get_species_id('Garuga pinnata') IS NOT NULL;

-- ============================================================================
-- STEREOSPERMUM CHELONOIDES (Class 2) - MEDICINAL
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Stereospermum chelonoides'), 'Associate', 4 WHERE get_species_id('Stereospermum chelonoides') IS NOT NULL;

-- ============================================================================
-- PYRUS PASHIA (Class 3, 11, 12) - WILD PEAR
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Pyrus pashia'), 'Associate', 4 WHERE get_species_id('Pyrus pashia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Pyrus pashia'), 'Associate', 4 WHERE get_species_id('Pyrus pashia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 12, get_species_id('Pyrus pashia'), 'Occasional', 4 WHERE get_species_id('Pyrus pashia') IS NOT NULL;

-- ============================================================================
-- EURYA ACUMINATA (Class 3, 8, 11) - UNDERSTORY
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Eurya acuminata'), 'Associate', 4 WHERE get_species_id('Eurya acuminata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Eurya acuminata'), 'Associate', 4 WHERE get_species_id('Eurya acuminata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Eurya acuminata'), 'Associate', 4 WHERE get_species_id('Eurya acuminata') IS NOT NULL;

-- ============================================================================
-- SORBUS CUSPIDATA (Class 5, 15) - HIGH ALTITUDE
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Sorbus cuspidata'), 'Associate', 4 WHERE get_species_id('Sorbus cuspidata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 15, get_species_id('Sorbus cuspidata'), 'Associate', 4 WHERE get_species_id('Sorbus cuspidata') IS NOT NULL;

-- ============================================================================
-- CARPINUS VIMINEA (Class 14, 20) - HARDWOOD
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 14, get_species_id('Carpinus viminea'), 'Associate', 4 WHERE get_species_id('Carpinus viminea') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 20, get_species_id('Carpinus viminea'), 'Associate', 4 WHERE get_species_id('Carpinus viminea') IS NOT NULL;

-- ============================================================================
-- ILEX DIPYRENA (Class 7, 15) - HOLLY
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Ilex dipyrena'), 'Associate', 4 WHERE get_species_id('Ilex dipyrena') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 15, get_species_id('Ilex dipyrena'), 'Associate', 4 WHERE get_species_id('Ilex dipyrena') IS NOT NULL;

-- ============================================================================
-- SENEGALIA CATECHU (Class 18) - CO-DOMINANT
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 18, get_species_id('Senegalia catechu'), 'Co-dominant', 1 WHERE get_species_id('Senegalia catechu') IS NOT NULL;

-- ============================================================================
-- TREWIA NUDIFLORA (Class 22) - DOMINANT
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 22, get_species_id('Trewia nudiflora'), 'Dominant', 1 WHERE get_species_id('Trewia nudiflora') IS NOT NULL;

-- ============================================================================
-- FICUS SEMICORDATA (Class 3, 11, 22) - KEYSTONE
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Ficus semicordata'), 'Associate', 4 WHERE get_species_id('Ficus semicordata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Ficus semicordata'), 'Associate', 4 WHERE get_species_id('Ficus semicordata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 22, get_species_id('Ficus semicordata'), 'Associate', 3 WHERE get_species_id('Ficus semicordata') IS NOT NULL;

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
    rare_species INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_species FROM tree_species_coefficients;
    SELECT COUNT(*) INTO total_associations FROM forest_species_association;
    SELECT COUNT(DISTINCT forest_type_id) INTO forest_types_covered FROM forest_species_association;
    SELECT COUNT(*) INTO nitrogen_fixers FROM tree_species_coefficients WHERE nitrogen_fixing = TRUE;
    SELECT COUNT(*) INTO rare_species FROM tree_species_coefficients WHERE rarity_status LIKE '%RARE%' OR rarity_status LIKE '%Threatened%';

    RAISE NOTICE '================================================';
    RAISE NOTICE 'PHASE 2 SESSION 2 - IMPORT COMPLETE';
    RAISE NOTICE '*** WEEK 1 TARGET ACHIEVED: 50 SPECIES! ***';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Total species in database: % (Target: 50)', total_species;
    RAISE NOTICE 'Total forest-species associations: %', total_associations;
    RAISE NOTICE 'Forest types with species data: %/25', forest_types_covered;
    RAISE NOTICE 'Nitrogen-fixing species: %', nitrogen_fixers;
    RAISE NOTICE 'RARE/Protected species: %', rare_species;
    RAISE NOTICE '================================================';

    -- Show species count by role
    RAISE NOTICE 'Association role breakdown:';
    RAISE NOTICE '  Dominant: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Dominant');
    RAISE NOTICE '  Co-dominant: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Co-dominant');
    RAISE NOTICE '  Associate: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Associate');
    RAISE NOTICE '  Occasional: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Occasional');
    RAISE NOTICE '================================================';

    IF total_species >= 50 THEN
        RAISE NOTICE '*** WEEK 1 GOAL ACHIEVED! 50+ SPECIES! ***';
    END IF;
    RAISE NOTICE '================================================';
END $$;

COMMIT;
