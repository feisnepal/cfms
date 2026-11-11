-- ============================================================================
-- PHASE 2: SPECIES DATABASE - FIRST 20 SPECIES IMPORT (SCHEMA-CORRECTED)
-- Description: Import first 20 researched species + forest associations
-- Date: 2026-02-16
-- Database: cf_db
-- Source: PHASE_2_SPECIES_RESEARCH_TRACKER.md (Day 1 research)
-- Schema: Uses actual forest_species_association columns (role, availability_rank)
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 1: INSERT/UPDATE 20 SPECIES WITH ECOLOGICAL DATA
-- ============================================================================

-- Species 1: Schima wallichii (Chilaune)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Schima wallichii', 'Chilaune', 'Theaceae', 900, 2400, 'Moderate', 'High', FALSE,
 'Timber, fuelwood, fodder (leaves for cattle)',
 'Mid-story to canopy dominant in mid-hill forests', 'Common')
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

-- Species 2: Shorea robusta (Sal)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Shorea robusta', 'Sal, Sakhu', 'Dipterocarpaceae', 150, 1500, 'Moderate', 'High', FALSE,
 'Timber (construction, railway sleepers), resin, leaves (plates)',
 'Dominant canopy species in tropical/subtropical zones', 'Common')
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

-- Species 3: Rhododendron arboreum (Laligurans)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Rhododendron arboreum', 'Laligurans', 'Ericaceae', 1200, 3600, 'Slow', 'Low', FALSE,
 'Ornamental, flowers (juice/pickle), medicinal, fuelwood',
 'Understory to mid-story in mixed forests, dominant in pure stands', 'Common')
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

-- Species 4: Terminalia alata (Saj)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Terminalia alata', 'Saj', 'Combretaceae', 100, 1200, 'Moderate', 'High', FALSE,
 'Timber (construction, furniture), bark (tannin), medicinal',
 'Co-dominant in tropical mixed forests, canopy layer', 'Common')
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

-- Species 5: Pinus roxburghii (Chir Pine)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Pinus roxburghii', 'Sallo', 'Pinaceae', 500, 2000, 'Fast', 'High', FALSE,
 'Timber (construction), resin (turpentine), fuelwood, charcoal',
 'Dominant canopy species, pioneer on degraded land', 'Common')
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

-- Species 6: Myrica esculenta (Kafal) - NITROGEN FIXING
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Myrica esculenta', 'Kafal', 'Myricaceae', 900, 2100, 'Moderate', 'Moderate', TRUE,
 'Edible fruit, fuelwood, bark (medicinal, dye)',
 'Understory to mid-story, nitrogen-fixing pioneer', 'Common')
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

-- Species 7: Bombax ceiba (Silk Cotton)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Bombax ceiba', 'Simal', 'Malvaceae', 100, 1500, 'Fast', 'Moderate', FALSE,
 'Kapok fiber (pillows, mattresses), timber (soft wood), flowers (vegetable), medicinal',
 'Emergent canopy layer in tropical forests, important for wildlife', 'Common')
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

-- Species 8: Anogeissus latifolia (Dhairo)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Anogeissus latifolia', 'Dhairo, Dhaukhair', 'Combretaceae', 200, 1200, 'Moderate', 'High', FALSE,
 'Timber (extremely hard, termite-resistant), gum (commercial), fuelwood',
 'Co-dominant in Sal forests, drought-tolerant', 'Common')
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

-- Species 9: Engelhardia spicata (Mahua)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Engelhardia spicata', 'Mahua, Mauwa', 'Juglandaceae', 900, 2400, 'Moderate', 'Moderate', FALSE,
 'Fuelwood, fodder (leaves), bark (medicinal)',
 'Mid-story species in mixed broadleaf forests', 'Common')
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

-- Species 10: Quercus lanata (Banjh Oak)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Quercus lanata', 'Banjh, Phaledo', 'Fagaceae', 1000, 2400, 'Slow', 'Moderate', FALSE,
 'Fuelwood (excellent quality), fodder (leaves for livestock), charcoal',
 'Mid-story to canopy in lower temperate zones', 'Common')
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

-- NEW SPECIES 11-20

-- Species 11: Castanopsis indica (Dhale Katus)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Castanopsis indica', 'Dhale Katus', 'Fagaceae', 1000, 2300, 'Moderate', 'High', FALSE,
 'Timber (construction, furniture), fuelwood, edible nuts',
 'Co-dominant with Schima in subtropical forests', 'Common')
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

-- Species 12: Pinus wallichiana (Blue Pine)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Pinus wallichiana', 'Gobre Salla', 'Pinaceae', 1800, 3300, 'Moderate', 'High', FALSE,
 'Timber (construction, furniture), resin, cones (edible seeds), ornamental',
 'Dominant canopy in upper temperate zones, climax species', 'Common')
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

-- Species 13: Alnus nepalensis (Nepal Alder) - NITROGEN FIXING
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Alnus nepalensis', 'Utis', 'Betulaceae', 500, 3000, 'Fast', 'Moderate', TRUE,
 'Fuelwood, timber (light construction), soil improvement, fodder',
 'Pioneer species, nitrogen-fixing, stabilizes slopes', 'Common')
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

-- Species 14: Betula utilis (Himalayan Birch)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Betula utilis', 'Bhojpatra', 'Betulaceae', 2400, 4500, 'Slow', 'Low', FALSE,
 'Bark (paper, roofing, medicinal manuscripts), medicinal (bark), fuelwood',
 'Subalpine/treeline species, pioneer on moraines', 'Common')
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

-- Species 15: Quercus semecarpifolia (Kharsu Oak)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Quercus semecarpifolia', 'Kharsu', 'Fagaceae', 2400, 3600, 'Slow', 'Moderate', FALSE,
 'Fuelwood (excellent quality), fodder (leaves), charcoal',
 'Dominant evergreen oak in subalpine zones', 'Common')
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

-- Species 16: Tsuga dumosa (Himalayan Hemlock)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Tsuga dumosa', 'Thingure Salla', 'Pinaceae', 2400, 3600, 'Slow', 'Moderate', FALSE,
 'Timber (construction), fuelwood, bark (tannin)',
 'Shade-tolerant understory to mid-story in mixed forests', 'Common')
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

-- Species 17: Abies spectabilis (Himalayan Fir)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Abies spectabilis', 'Talis Patra, Gobrey Salla', 'Pinaceae', 2400, 4000, 'Moderate', 'High', FALSE,
 'Timber (construction, paper pulp), medicinal (resin), religious (incense)',
 'Dominant canopy in subalpine forests', 'Common')
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

-- Species 18: Dalbergia sissoo (Sissoo) - NITROGEN FIXING
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Dalbergia sissoo', 'Sissoo, Sisau', 'Fabaceae', 100, 1200, 'Fast', 'High', TRUE,
 'Timber (furniture, cabinets, musical instruments), agroforestry, shade',
 'Dominant in riverine and plantation forests', 'Common')
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

-- Species 19: Taxus wallichiana (Himalayan Yew) - RARE/PROTECTED
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Taxus wallichiana', 'Lauth Salla, Dhengre Salla', 'Taxaceae', 1800, 3300, 'Slow', 'High', FALSE,
 'MEDICINAL (Taxol for cancer treatment), religious/cultural',
 'Understory species in temperate forests, shade-tolerant', 'RARE - PROTECTED')
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

-- Species 20: Terminalia bellirica (Barro)
INSERT INTO tree_species_coefficients
(scientific_name, local_name, family, min_altitude_m, max_altitude_m,
 growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
('Terminalia bellirica', 'Barro', 'Combretaceae', 200, 1500, 'Moderate', 'High', FALSE,
 'Timber (construction, furniture), medicinal (Triphala - Ayurveda), fruits (dye, tannin)',
 'Emergent canopy layer in tropical/subtropical forests', 'Common')
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
-- STEP 2: POPULATE FOREST-SPECIES ASSOCIATIONS
-- Clear existing and rebuild from research
-- Schema: role (Dominant/Co-dominant/Associate/Occasional), availability_rank (1-4)
-- ============================================================================

-- Clear existing associations
DELETE FROM forest_species_association;

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
-- CLASS 1: Shorea robusta Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Shorea robusta'), 'Dominant', 1 WHERE get_species_id('Shorea robusta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Terminalia alata'), 'Associate', 2 WHERE get_species_id('Terminalia alata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 1, get_species_id('Anogeissus latifolia'), 'Associate', 3 WHERE get_species_id('Anogeissus latifolia') IS NOT NULL;

-- ============================================================================
-- CLASS 2: Tropical Mixed Broadleaved Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Terminalia alata'), 'Dominant', 1 WHERE get_species_id('Terminalia alata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 2, get_species_id('Bombax ceiba'), 'Co-dominant', 2 WHERE get_species_id('Bombax ceiba') IS NOT NULL;

-- ============================================================================
-- CLASS 3: Subtropical Mixed Broadleaved Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Schima wallichii'), 'Dominant', 1 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Castanopsis indica'), 'Co-dominant', 1 WHERE get_species_id('Castanopsis indica') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Engelhardia spicata'), 'Associate', 2 WHERE get_species_id('Engelhardia spicata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 3, get_species_id('Myrica esculenta'), 'Associate', 2 WHERE get_species_id('Myrica esculenta') IS NOT NULL;

-- ============================================================================
-- CLASS 4: Shorea robusta - Mixed Broadleaved Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 4, get_species_id('Shorea robusta'), 'Dominant', 1 WHERE get_species_id('Shorea robusta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 4, get_species_id('Terminalia alata'), 'Co-dominant', 1 WHERE get_species_id('Terminalia alata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 4, get_species_id('Anogeissus latifolia'), 'Associate', 2 WHERE get_species_id('Anogeissus latifolia') IS NOT NULL;

-- ============================================================================
-- CLASS 5: Abies Mixed Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Abies spectabilis'), 'Dominant', 1 WHERE get_species_id('Abies spectabilis') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Betula utilis'), 'Associate', 2 WHERE get_species_id('Betula utilis') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Tsuga dumosa'), 'Associate', 2 WHERE get_species_id('Tsuga dumosa') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 5, get_species_id('Taxus wallichiana'), 'Occasional', 4 WHERE get_species_id('Taxus wallichiana') IS NOT NULL;

-- ============================================================================
-- CLASS 6: Upper Temperate Coniferous Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Pinus wallichiana'), 'Dominant', 1 WHERE get_species_id('Pinus wallichiana') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Tsuga dumosa'), 'Associate', 2 WHERE get_species_id('Tsuga dumosa') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Abies spectabilis'), 'Associate', 2 WHERE get_species_id('Abies spectabilis') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Taxus wallichiana'), 'Occasional', 4 WHERE get_species_id('Taxus wallichiana') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 6, get_species_id('Quercus semecarpifolia'), 'Associate', 3 WHERE get_species_id('Quercus semecarpifolia') IS NOT NULL;

-- ============================================================================
-- CLASS 7: Cool Temperate Mixed Broadleaved Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Rhododendron arboreum'), 'Associate', 2 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 7, get_species_id('Taxus wallichiana'), 'Occasional', 4 WHERE get_species_id('Taxus wallichiana') IS NOT NULL;

-- ============================================================================
-- CLASS 8: Castanopsis Lower Temperate Mixed Broadleaved Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Castanopsis tribuloides'), 'Dominant', 1 WHERE get_species_id('Castanopsis tribuloides') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Schima wallichii'), 'Associate', 2 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Engelhardia spicata'), 'Associate', 3 WHERE get_species_id('Engelhardia spicata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 8, get_species_id('Rhododendron arboreum'), 'Associate', 3 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

-- ============================================================================
-- CLASS 9: Pinus roxburghii Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 9, get_species_id('Pinus roxburghii'), 'Dominant', 1 WHERE get_species_id('Pinus roxburghii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 9, get_species_id('Myrica esculenta'), 'Associate', 2 WHERE get_species_id('Myrica esculenta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 9, get_species_id('Quercus lanata'), 'Associate', 2 WHERE get_species_id('Quercus lanata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 9, get_species_id('Rhododendron arboreum'), 'Associate', 3 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

-- ============================================================================
-- CLASS 10: Alnus Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Alnus nepalensis'), 'Dominant', 1 WHERE get_species_id('Alnus nepalensis') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 10, get_species_id('Betula utilis'), 'Associate', 2 WHERE get_species_id('Betula utilis') IS NOT NULL;

-- ============================================================================
-- CLASS 11: Schima Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Schima wallichii'), 'Dominant', 1 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Castanopsis indica'), 'Associate', 2 WHERE get_species_id('Castanopsis indica') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Myrica esculenta'), 'Associate', 3 WHERE get_species_id('Myrica esculenta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 11, get_species_id('Engelhardia spicata'), 'Associate', 3 WHERE get_species_id('Engelhardia spicata') IS NOT NULL;

-- ============================================================================
-- CLASS 12: Pinus roxburghii - Mixed Broadleaved Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 12, get_species_id('Pinus roxburghii'), 'Dominant', 1 WHERE get_species_id('Pinus roxburghii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 12, get_species_id('Quercus lanata'), 'Associate', 2 WHERE get_species_id('Quercus lanata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 12, get_species_id('Myrica esculenta'), 'Associate', 3 WHERE get_species_id('Myrica esculenta') IS NOT NULL;

-- ============================================================================
-- CLASS 13: Pinus wallichiana Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 13, get_species_id('Pinus wallichiana'), 'Dominant', 1 WHERE get_species_id('Pinus wallichiana') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 13, get_species_id('Quercus semecarpifolia'), 'Associate', 2 WHERE get_species_id('Quercus semecarpifolia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 13, get_species_id('Abies spectabilis'), 'Associate', 2 WHERE get_species_id('Abies spectabilis') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 13, get_species_id('Betula utilis'), 'Associate', 3 WHERE get_species_id('Betula utilis') IS NOT NULL;

-- ============================================================================
-- CLASS 14: Warm Temperate Mixed Broadleaved Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 14, get_species_id('Castanopsis tribuloides'), 'Dominant', 1 WHERE get_species_id('Castanopsis tribuloides') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 14, get_species_id('Schima wallichii'), 'Associate', 2 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 14, get_species_id('Rhododendron arboreum'), 'Associate', 3 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

-- ============================================================================
-- CLASS 15: Upper Temperate Quercus Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 15, get_species_id('Quercus semecarpifolia'), 'Dominant', 1 WHERE get_species_id('Quercus semecarpifolia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 15, get_species_id('Rhododendron arboreum'), 'Associate', 2 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 15, get_species_id('Taxus wallichiana'), 'Occasional', 4 WHERE get_species_id('Taxus wallichiana') IS NOT NULL;

-- ============================================================================
-- CLASS 16: Rhododendron arboreum Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 16, get_species_id('Rhododendron arboreum'), 'Dominant', 1 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

-- ============================================================================
-- CLASS 17: Temperate Rhododendron Mixed Broadleaved Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Rhododendron arboreum'), 'Dominant', 1 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Quercus semecarpifolia'), 'Associate', 2 WHERE get_species_id('Quercus semecarpifolia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 17, get_species_id('Tsuga dumosa'), 'Associate', 3 WHERE get_species_id('Tsuga dumosa') IS NOT NULL;

-- ============================================================================
-- CLASS 18: Dalbergia sissoo-Senegalia catechu Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 18, get_species_id('Dalbergia sissoo'), 'Dominant', 1 WHERE get_species_id('Dalbergia sissoo') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 18, get_species_id('Bombax ceiba'), 'Associate', 2 WHERE get_species_id('Bombax ceiba') IS NOT NULL;

-- ============================================================================
-- CLASS 19: Terminalia - Tropical Mixed Broadleaved Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 19, get_species_id('Terminalia alata'), 'Dominant', 1 WHERE get_species_id('Terminalia alata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 19, get_species_id('Terminalia bellirica'), 'Co-dominant', 1 WHERE get_species_id('Terminalia bellirica') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 19, get_species_id('Anogeissus latifolia'), 'Associate', 2 WHERE get_species_id('Anogeissus latifolia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 19, get_species_id('Shorea robusta'), 'Associate', 3 WHERE get_species_id('Shorea robusta') IS NOT NULL;

-- ============================================================================
-- CLASS 21: Tropical Deciduous Indigenous Riverine Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 21, get_species_id('Bombax ceiba'), 'Dominant', 1 WHERE get_species_id('Bombax ceiba') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 21, get_species_id('Dalbergia sissoo'), 'Associate', 2 WHERE get_species_id('Dalbergia sissoo') IS NOT NULL;

-- ============================================================================
-- CLASS 22: Tropical Riverine Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 22, get_species_id('Bombax ceiba'), 'Associate', 2 WHERE get_species_id('Bombax ceiba') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 22, get_species_id('Dalbergia sissoo'), 'Associate', 2 WHERE get_species_id('Dalbergia sissoo') IS NOT NULL;

-- ============================================================================
-- CLASS 23: Lower Temperate Mixed robusta Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 23, get_species_id('Shorea robusta'), 'Dominant', 1 WHERE get_species_id('Shorea robusta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 23, get_species_id('Schima wallichii'), 'Co-dominant', 1 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 23, get_species_id('Castanopsis indica'), 'Associate', 2 WHERE get_species_id('Castanopsis indica') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 23, get_species_id('Myrica esculenta'), 'Associate', 3 WHERE get_species_id('Myrica esculenta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 23, get_species_id('Quercus lanata'), 'Associate', 3 WHERE get_species_id('Quercus lanata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 23, get_species_id('Engelhardia spicata'), 'Associate', 4 WHERE get_species_id('Engelhardia spicata') IS NOT NULL;

-- ============================================================================
-- CLASS 24: Pinus roxburghii - Shorea robusta Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 24, get_species_id('Pinus roxburghii'), 'Dominant', 1 WHERE get_species_id('Pinus roxburghii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 24, get_species_id('Shorea robusta'), 'Co-dominant', 1 WHERE get_species_id('Shorea robusta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 24, get_species_id('Terminalia alata'), 'Associate', 2 WHERE get_species_id('Terminalia alata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 24, get_species_id('Schima wallichii'), 'Associate', 3 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 24, get_species_id('Anogeissus latifolia'), 'Associate', 4 WHERE get_species_id('Anogeissus latifolia') IS NOT NULL;

-- ============================================================================
-- CLASS 25: Lower Temperate Pinus roxburghii - Quercus Forest
-- ============================================================================
INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 25, get_species_id('Pinus roxburghii'), 'Dominant', 1 WHERE get_species_id('Pinus roxburghii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 25, get_species_id('Quercus lanata'), 'Co-dominant', 1 WHERE get_species_id('Quercus lanata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 25, get_species_id('Rhododendron arboreum'), 'Associate', 2 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, role, availability_rank)
SELECT 25, get_species_id('Myrica esculenta'), 'Associate', 3 WHERE get_species_id('Myrica esculenta') IS NOT NULL;

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
BEGIN
    SELECT COUNT(*) INTO total_species FROM tree_species_coefficients;
    SELECT COUNT(*) INTO total_associations FROM forest_species_association;
    SELECT COUNT(DISTINCT forest_type_id) INTO forest_types_covered FROM forest_species_association;
    SELECT COUNT(*) INTO nitrogen_fixers FROM tree_species_coefficients WHERE nitrogen_fixing = TRUE;

    RAISE NOTICE '================================================';
    RAISE NOTICE 'PHASE 2 - FIRST 20 SPECIES IMPORT COMPLETE';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Total species in database: %', total_species;
    RAISE NOTICE 'Total forest-species associations: %', total_associations;
    RAISE NOTICE 'Forest types with species data: %/25', forest_types_covered;
    RAISE NOTICE 'Nitrogen-fixing species: %', nitrogen_fixers;
    RAISE NOTICE '================================================';

    -- Show species count by role
    RAISE NOTICE 'Association role breakdown:';
    RAISE NOTICE '  Dominant associations: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Dominant');
    RAISE NOTICE '  Co-dominant associations: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Co-dominant');
    RAISE NOTICE '  Associate associations: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Associate');
    RAISE NOTICE '  Occasional associations: %', (SELECT COUNT(*) FROM forest_species_association WHERE role = 'Occasional');
    RAISE NOTICE '================================================';
END $$;

COMMIT;
