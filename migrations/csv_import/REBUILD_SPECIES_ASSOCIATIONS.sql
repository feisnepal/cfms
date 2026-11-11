-- ============================================================================
-- REBUILD FOREST-SPECIES ASSOCIATIONS
-- Description: Populate forest_species_association table from regulation data
-- Date: 2026-02-16
-- Database: cf_db
-- Source: Forest Regulation 2079 - forest_type_and_species.csv
-- ============================================================================

BEGIN;

-- ============================================================================
-- Clear existing associations (if any)
-- ============================================================================

DELETE FROM forest_species_association;

-- ============================================================================
-- Helper function to get species ID by scientific name (approximate match)
-- ============================================================================

CREATE OR REPLACE FUNCTION get_species_id(species_pattern TEXT) RETURNS INTEGER AS $$
DECLARE
    species_id INTEGER;
BEGIN
    SELECT id INTO species_id
    FROM tree_species_coefficients
    WHERE scientific_name ILIKE '%' || species_pattern || '%'
    LIMIT 1;

    RETURN species_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- INSERT FOREST-SPECIES ASSOCIATIONS
-- Based on Forest Regulation 2079 data
-- ============================================================================

-- Class 1: Shorea robusta Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 1, get_species_id('Shorea robusta'), 'DOMINANT', 1 WHERE get_species_id('Shorea robusta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 1, get_species_id('Terminalia alata'), 'ASSOCIATED', 2 WHERE get_species_id('Terminalia alata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 1, get_species_id('Anogeissus latifolia'), 'ASSOCIATED', 3 WHERE get_species_id('Anogeissus latifolia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 1, get_species_id('Haldina cordifolia'), 'ASSOCIATED', 4 WHERE get_species_id('Haldina cordifolia') IS NOT NULL;

-- Class 2: Tropical Mixed Broadleaved Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 2, get_species_id('Terminalia alata'), 'DOMINANT', 1 WHERE get_species_id('Terminalia alata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 2, get_species_id('Bombax ceiba'), 'DOMINANT', 2 WHERE get_species_id('Bombax ceiba') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 2, get_species_id('Syzygium cumini'), 'ASSOCIATED', 3 WHERE get_species_id('Syzygium cumini') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 2, get_species_id('Haldina cordifolia'), 'ASSOCIATED', 4 WHERE get_species_id('Haldina cordifolia') IS NOT NULL;

-- Class 3: Subtropical Mixed Broadleaved Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 3, get_species_id('Schima wallichii'), 'DOMINANT', 1 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 3, get_species_id('Castanopsis indica'), 'DOMINANT', 2 WHERE get_species_id('Castanopsis indica') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 3, get_species_id('Quercus glauca'), 'ASSOCIATED', 3 WHERE get_species_id('Quercus glauca') IS NOT NULL;

-- Class 4: Shorea robusta - Mixed Broadleaved Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 4, get_species_id('Shorea robusta'), 'DOMINANT', 1 WHERE get_species_id('Shorea robusta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 4, get_species_id('Terminalia alata'), 'DOMINANT', 2 WHERE get_species_id('Terminalia alata') IS NOT NULL;

-- Class 7: Cool Temperate Mixed Broadleaved Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 7, get_species_id('Rhododendron arboreum'), 'ASSOCIATED', 1 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 7, get_species_id('Lyonia ovalifolia'), 'ASSOCIATED', 2 WHERE get_species_id('Lyonia ovalifolia') IS NOT NULL;

-- Class 8: Castanopsis Lower Temperate Mixed Broadleaved Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 8, get_species_id('Castanopsis tribuloides'), 'DOMINANT', 1 WHERE get_species_id('Castanopsis tribuloides') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 8, get_species_id('Schima wallichii'), 'ASSOCIATED', 2 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 8, get_species_id('Quercus glauca'), 'ASSOCIATED', 3 WHERE get_species_id('Quercus glauca') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 8, get_species_id('Rhododendron arboreum'), 'ASSOCIATED', 4 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

-- Class 9: Pinus roxburghii Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 9, get_species_id('Lyonia ovalifolia'), 'ASSOCIATED', 1 WHERE get_species_id('Lyonia ovalifolia') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 9, get_species_id('Rhododendron arboreum'), 'ASSOCIATED', 2 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

-- Class 11: Schima Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 11, get_species_id('Schima wallichii'), 'DOMINANT', 1 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 11, get_species_id('Castanopsis indica'), 'ASSOCIATED', 2 WHERE get_species_id('Castanopsis indica') IS NOT NULL;

-- Class 14: Warm Temperate Mixed Broadleaved Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 14, get_species_id('Castanopsis tribuloides'), 'DOMINANT', 1 WHERE get_species_id('Castanopsis tribuloides') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 14, get_species_id('Quercus glauca'), 'DOMINANT', 2 WHERE get_species_id('Quercus glauca') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 14, get_species_id('Schima wallichii'), 'ASSOCIATED', 3 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 14, get_species_id('Rhododendron arboreum'), 'ASSOCIATED', 4 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

-- Class 15: Upper Temperate Quercus Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 15, get_species_id('Rhododendron arboreum'), 'ASSOCIATED', 1 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

-- Class 16: Rhododendron arboreum Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 16, get_species_id('Rhododendron arboreum'), 'DOMINANT', 1 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 16, get_species_id('Lyonia ovalifolia'), 'ASSOCIATED', 2 WHERE get_species_id('Lyonia ovalifolia') IS NOT NULL;

-- Class 18: Dalbergia sissoo-Senegalia catechu Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 18, get_species_id('Bombax ceiba'), 'ASSOCIATED', 1 WHERE get_species_id('Bombax ceiba') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 18, get_species_id('Syzygium cumini'), 'ASSOCIATED', 2 WHERE get_species_id('Syzygium cumini') IS NOT NULL;

-- Class 19: Terminalia - Tropical Mixed Broadleaved Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 19, get_species_id('Terminalia alata'), 'DOMINANT', 1 WHERE get_species_id('Terminalia alata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 19, get_species_id('Shorea robusta'), 'ASSOCIATED', 2 WHERE get_species_id('Shorea robusta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 19, get_species_id('Haldina cordifolia'), 'ASSOCIATED', 3 WHERE get_species_id('Haldina cordifolia') IS NOT NULL;

-- Class 20: Temperate Mixed Broadleaved Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 20, get_species_id('Symplocos'), 'ASSOCIATED', 1 WHERE get_species_id('Symplocos') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 20, get_species_id('Machilus gamblei'), 'ASSOCIATED', 2 WHERE get_species_id('Machilus gamblei') IS NOT NULL;

-- Class 21: Tropical Deciduous Indigenous Riverine Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 21, get_species_id('Bombax ceiba'), 'DOMINANT', 1 WHERE get_species_id('Bombax ceiba') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 21, get_species_id('Syzygium cumini'), 'ASSOCIATED', 2 WHERE get_species_id('Syzygium cumini') IS NOT NULL;

-- Class 22: Tropical Riverine Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 22, get_species_id('Syzygium cumini'), 'ASSOCIATED', 1 WHERE get_species_id('Syzygium cumini') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 22, get_species_id('Ficus'), 'ASSOCIATED', 2 WHERE get_species_id('Ficus') IS NOT NULL;

-- Class 23: Lower Temperate Mixed robusta Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 23, get_species_id('Shorea robusta'), 'DOMINANT', 1 WHERE get_species_id('Shorea robusta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 23, get_species_id('Schima wallichii'), 'DOMINANT', 2 WHERE get_species_id('Schima wallichii') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 23, get_species_id('Castanopsis indica'), 'ASSOCIATED', 3 WHERE get_species_id('Castanopsis indica') IS NOT NULL;

-- Class 24: Pinus roxburghii - Shorea robusta Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 24, get_species_id('Shorea robusta'), 'DOMINANT', 1 WHERE get_species_id('Shorea robusta') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 24, get_species_id('Terminalia alata'), 'ASSOCIATED', 2 WHERE get_species_id('Terminalia alata') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 24, get_species_id('Schima wallichii'), 'ASSOCIATED', 3 WHERE get_species_id('Schima wallichii') IS NOT NULL;

-- Class 25: Lower Temperate Pinus roxburghii - Quercus Forest
INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 25, get_species_id('Rhododendron arboreum'), 'ASSOCIATED', 1 WHERE get_species_id('Rhododendron arboreum') IS NOT NULL;

INSERT INTO forest_species_association (forest_type_id, species_id, association_type, priority)
SELECT 25, get_species_id('Lyonia ovalifolia'), 'ASSOCIATED', 2 WHERE get_species_id('Lyonia ovalifolia') IS NOT NULL;

-- Drop helper function
DROP FUNCTION get_species_id(TEXT);

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    total_associations INTEGER;
    forest_types_with_species INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_associations FROM forest_species_association;
    SELECT COUNT(DISTINCT forest_type_id) INTO forest_types_with_species FROM forest_species_association;

    RAISE NOTICE '=================================================';
    RAISE NOTICE 'SPECIES ASSOCIATIONS REBUILT';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Total associations created: %', total_associations;
    RAISE NOTICE 'Forest types with species: %/25', forest_types_with_species;
    RAISE NOTICE '=================================================';
END $$;

COMMIT;
