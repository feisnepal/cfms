-- ============================================================================
-- MIGRATION: Phase 1B - Add Priority Species
-- Description: Add species characteristic columns and insert 10 high-priority
--              species with complete ecological data
-- Date: 2026-02-15
-- Database: cf_db (PostgreSQL)
-- Estimated Time: 2-3 minutes
-- Pre-requisite: 001_phase_1a_critical_fix.sql must be run first
-- ============================================================================

-- Start transaction
BEGIN;

-- ============================================================================
-- STEP 1: ADD NEW COLUMNS TO tree_species_coefficients
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'PHASE 1B: Adding Species Characteristic Columns';
    RAISE NOTICE '=================================================';
END $$;

-- Add max_height_m column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'max_height_m'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN max_height_m DECIMAL(5,2);
        RAISE NOTICE 'Added column: max_height_m';
    ELSE
        RAISE NOTICE 'Column max_height_m already exists';
    END IF;
END $$;

-- Add max_dbh_cm column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'max_dbh_cm'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN max_dbh_cm DECIMAL(6,2);
        RAISE NOTICE 'Added column: max_dbh_cm';
    ELSE
        RAISE NOTICE 'Column max_dbh_cm already exists';
    END IF;
END $$;

-- Add min_altitude_m column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'min_altitude_m'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN min_altitude_m INTEGER;
        RAISE NOTICE 'Added column: min_altitude_m';
    ELSE
        RAISE NOTICE 'Column min_altitude_m already exists';
    END IF;
END $$;

-- Add max_altitude_m column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'max_altitude_m'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN max_altitude_m INTEGER;
        RAISE NOTICE 'Added column: max_altitude_m';
    ELSE
        RAISE NOTICE 'Column max_altitude_m already exists';
    END IF;
END $$;

-- Add growth_rate column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'growth_rate'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN growth_rate VARCHAR(20);
        RAISE NOTICE 'Added column: growth_rate';
    ELSE
        RAISE NOTICE 'Column growth_rate already exists';
    END IF;
END $$;

-- Add economic_value column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'economic_value'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN economic_value VARCHAR(20);
        RAISE NOTICE 'Added column: economic_value';
    ELSE
        RAISE NOTICE 'Column economic_value already exists';
    END IF;
END $$;

-- Add nitrogen_fixing column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'nitrogen_fixing'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN nitrogen_fixing BOOLEAN DEFAULT FALSE;
        RAISE NOTICE 'Added column: nitrogen_fixing';
    ELSE
        RAISE NOTICE 'Column nitrogen_fixing already exists';
    END IF;
END $$;

-- Add main_uses column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'main_uses'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN main_uses TEXT;
        RAISE NOTICE 'Added column: main_uses';
    ELSE
        RAISE NOTICE 'Column main_uses already exists';
    END IF;
END $$;

-- Add ecological_role column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'ecological_role'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN ecological_role TEXT;
        RAISE NOTICE 'Added column: ecological_role';
    ELSE
        RAISE NOTICE 'Column ecological_role already exists';
    END IF;
END $$;

-- Add rarity_status column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'rarity_status'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN rarity_status VARCHAR(20) DEFAULT 'Common';
        RAISE NOTICE 'Added column: rarity_status';
    ELSE
        RAISE NOTICE 'Column rarity_status already exists';
    END IF;
END $$;

-- Add family column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tree_species_coefficients'
        AND column_name = 'family'
    ) THEN
        ALTER TABLE tree_species_coefficients ADD COLUMN family VARCHAR(100);
        RAISE NOTICE 'Added column: family';
    ELSE
        RAISE NOTICE 'Column family already exists';
    END IF;
END $$;


-- ============================================================================
-- STEP 2: INSERT 10 HIGH-PRIORITY SPECIES
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Inserting 10 High-Priority Species';
    RAISE NOTICE '=================================================';
END $$;

-- Species 1: Castanopsis tribuloides
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Castanopsis tribuloides', 'Katus', 'Fagaceae', 10.00, NULL,
     570, 2240, 'Moderate', 'Medium', FALSE,
     'Timber, edible nuts, pioneer species for plantations',
     'Canopy species in subtropical forests, broad-leaved evergreen forests',
     'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Castanopsis tribuloides (Katus)'; END $$;

-- Species 2: Castanopsis indica
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Castanopsis indica', 'Katus/Dhalne Katus', 'Fagaceae', 30.00, NULL,
     600, 2400, 'Moderate', 'Medium',
     FALSE, 'Timber, aboveground biomass, carbon storage',
     'Important biomass contributor in subtropical and temperate forests',
     'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Castanopsis indica (Katus)'; END $$;

-- Species 3: Quercus lanata
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Quercus lanata', 'Dhalne Banj', 'Fagaceae', 25.00, NULL,
     1000, 2500, 'Slow', 'Medium',
     FALSE, 'Fodder, fuelwood, timber, carbon storage',
     'Dominant in pine-oak mixed forests, fodder production',
     'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Quercus lanata (Dhalne Banj)'; END $$;

-- Species 4: Myrica esculenta
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Myrica esculenta', 'Kaphal', 'Myricaceae', 12.00, 40.00,
     900, 2100, 'Moderate', 'High',
     TRUE, 'Edible fruit (bayberry), fodder, medicine, timber',
     'Widespread associate in subtropical and temperate forests, nitrogen fixer',
     'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    max_dbh_cm = EXCLUDED.max_dbh_cm,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    nitrogen_fixing = EXCLUDED.nitrogen_fixing,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Myrica esculenta (Kaphal)'; END $$;

-- Species 5: Engelhardia spicata
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Engelhardia spicata', 'Mauwa', 'Juglandaceae', 20.00, 60.00,
     600, 2000, 'Moderate', 'Medium',
     FALSE, 'Timber (light construction), fodder, fuelwood',
     'Common associate in subtropical and lower temperate mixed forests',
     'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    max_dbh_cm = EXCLUDED.max_dbh_cm,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Engelhardia spicata (Mauwa)'; END $$;

-- Species 6: Terminalia chebula
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Terminalia chebula', 'Harro', 'Combretaceae', 30.00, 100.00,
     200, 1500, 'Moderate', 'Very High',
     FALSE, 'Medicinal (myrobalan - Ayurvedic), tannin, timber, dye',
     'Important medicinal tree in tropical and subtropical forests',
     'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    max_dbh_cm = EXCLUDED.max_dbh_cm,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Terminalia chebula (Harro)'; END $$;

-- Species 7: Toona ciliata (Cedrela toona)
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Toona ciliata', 'Tooni', 'Meliaceae', 35.00, 150.00,
     200, 1500, 'Fast', 'Very High',
     FALSE, 'High-value timber (furniture, carving), plantation species',
     'Riverine and moist forest associate, valuable timber species',
     'Occasional')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    max_dbh_cm = EXCLUDED.max_dbh_cm,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role,
    rarity_status = EXCLUDED.rarity_status;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Toona ciliata (Tooni)'; END $$;

-- Species 8: Betula utilis
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Betula utilis', 'Bhojpatra', 'Betulaceae', 20.00, 80.00,
     3000, 4500, 'Moderate', 'High',
     FALSE, 'Bark (traditional writing material, sacred texts), timber, medicine',
     'High altitude forests, associate with Abies and Rhododendron, cultural importance',
     'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    max_dbh_cm = EXCLUDED.max_dbh_cm,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Betula utilis (Bhojpatra)'; END $$;

-- Species 9: Acer spp.
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Acer spp.', 'Kimbu', 'Aceraceae', 25.00, 60.00,
     2000, 3500, 'Moderate', 'Medium',
     FALSE, 'Timber, fuelwood, ornamental',
     'Dominant in cool and temperate mixed broadleaved forests',
     'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    max_dbh_cm = EXCLUDED.max_dbh_cm,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Acer spp. (Kimbu)'; END $$;

-- Species 10: Rhododendron campanulatum
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Rhododendron campanulatum', 'Chimal/Gurans', 'Ericaceae', 5.00, NULL,
     3000, 4500, 'Slow', 'Low',
     FALSE, 'Ornamental, medicine, fuelwood',
     'Alpine and subalpine associate with Abies spectabilis',
     'Common')
ON CONFLICT (scientific_name) DO UPDATE SET
    local_name = EXCLUDED.local_name,
    family = EXCLUDED.family,
    max_height_m = EXCLUDED.max_height_m,
    min_altitude_m = EXCLUDED.min_altitude_m,
    max_altitude_m = EXCLUDED.max_altitude_m,
    growth_rate = EXCLUDED.growth_rate,
    economic_value = EXCLUDED.economic_value,
    main_uses = EXCLUDED.main_uses,
    ecological_role = EXCLUDED.ecological_role;

DO $$ BEGIN RAISE NOTICE 'Inserted/Updated: Rhododendron campanulatum (Chimal)'; END $$;


-- ============================================================================
-- STEP 3: UPDATE EXISTING SPECIES WITH NEW DATA
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Updating Existing Species with Characteristics';
    RAISE NOTICE '=================================================';
END $$;

-- Update Shorea robusta
UPDATE tree_species_coefficients SET
    family = 'Dipterocarpaceae',
    max_height_m = 40.00,
    max_dbh_cm = 200.00,
    min_altitude_m = 0,
    max_altitude_m = 1400,
    growth_rate = 'Fast',
    economic_value = 'Very High',
    nitrogen_fixing = FALSE,
    main_uses = 'Timber (construction, furniture), resin, fuelwood',
    ecological_role = 'Dominant in Terai forests (1.4M ha), carbon sequestration, forms pure stands',
    rarity_status = 'Common'
WHERE scientific_name = 'Shorea robusta';

-- Update Pinus roxburghii
UPDATE tree_species_coefficients SET
    family = 'Pinaceae',
    max_height_m = 50.00,
    max_dbh_cm = 300.00,
    min_altitude_m = 500,
    max_altitude_m = 2300,
    growth_rate = 'Moderate',
    economic_value = 'High',
    nitrogen_fixing = FALSE,
    main_uses = 'Timber, furniture, resin (turpentine), fuelwood',
    ecological_role = 'Pioneer species in subtropical hills, 8.54% of forest cover, soil stabilizer',
    rarity_status = 'Common'
WHERE scientific_name = 'Pinus roxburghii';

-- Update Schima wallichii
UPDATE tree_species_coefficients SET
    family = 'Theaceae',
    max_height_m = 47.00,
    max_dbh_cm = 250.00,
    min_altitude_m = 750,
    max_altitude_m = 2400,
    growth_rate = 'Moderate',
    economic_value = 'Medium',
    nitrogen_fixing = FALSE,
    main_uses = 'Timber, reforestation, agroforestry, fuelwood',
    ecological_role = 'Common in disturbed and secondary forests, pioneer species, 100% seedling survival',
    rarity_status = 'Common'
WHERE scientific_name = 'Schima wallichii';

-- Update Alnus nepalensis
UPDATE tree_species_coefficients SET
    family = 'Betulaceae',
    max_height_m = 30.00,
    max_dbh_cm = 200.00,
    min_altitude_m = 500,
    max_altitude_m = 3600,
    growth_rate = 'Very Fast',
    economic_value = 'High',
    nitrogen_fixing = TRUE,
    main_uses = 'Timber, fuelwood, green manure, agroforestry, soil improvement',
    ecological_role = 'Pioneer species, nitrogen fixer (Frankia), soil improver, mean annual increment 2.7m height',
    rarity_status = 'Common'
WHERE scientific_name = 'Alnus nepalensis';

-- Update Terminalia alata
UPDATE tree_species_coefficients SET
    family = 'Combretaceae',
    max_height_m = 35.00,
    max_dbh_cm = 200.00,
    min_altitude_m = 0,
    max_altitude_m = 1400,
    growth_rate = 'Moderate',
    economic_value = 'High',
    nitrogen_fixing = FALSE,
    main_uses = 'Timber (construction, underwater, veneer), tannin, fodder',
    ecological_role = 'One of 3 most important Terai species, soil conservation, carbon sequestration',
    rarity_status = 'Common'
WHERE scientific_name = 'Terminalia alata';

-- Update Dalbergia sissoo
UPDATE tree_species_coefficients SET
    family = 'Fabaceae',
    max_height_m = 30.00,
    max_dbh_cm = 80.00,
    min_altitude_m = 0,
    max_altitude_m = 1500,
    growth_rate = 'Very Fast',
    economic_value = 'Very High',
    nitrogen_fixing = TRUE,
    main_uses = 'High-value timber (furniture, rosewood), erosion control',
    ecological_role = 'Riverine pioneer, soil stabilizer, nitrogen fixer, fast growth (3.7m/year young)',
    rarity_status = 'Common'
WHERE scientific_name = 'Dalbergia sissoo';

DO $$ BEGIN RAISE NOTICE 'Updated existing species with characteristics'; END $$;


-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

DO $$
DECLARE
    total_species INTEGER;
    species_with_characteristics INTEGER;
    species_with_altitude INTEGER;
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'VERIFICATION RESULTS:';
    RAISE NOTICE '=================================================';

    SELECT COUNT(*) INTO total_species FROM tree_species_coefficients;
    RAISE NOTICE 'Total species in database: %', total_species;

    SELECT COUNT(*) INTO species_with_characteristics
    FROM tree_species_coefficients
    WHERE max_height_m IS NOT NULL OR economic_value IS NOT NULL;
    RAISE NOTICE 'Species with characteristics: %', species_with_characteristics;

    SELECT COUNT(*) INTO species_with_altitude
    FROM tree_species_coefficients
    WHERE min_altitude_m IS NOT NULL AND max_altitude_m IS NOT NULL;
    RAISE NOTICE 'Species with altitude ranges: %', species_with_altitude;

    IF species_with_characteristics >= 15 THEN
        RAISE NOTICE 'SUCCESS: At least 15 species have characteristics';
    END IF;

    RAISE NOTICE '=================================================';
END $$;


-- ============================================================================
-- COMMIT TRANSACTION
-- ============================================================================

COMMIT;

-- Final success message
DO $$
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'PHASE 1B MIGRATION COMPLETED SUCCESSFULLY';
    RAISE NOTICE '=================================================';
    RAISE NOTICE '10 high-priority species added/updated';
    RAISE NOTICE 'New characteristic columns added to all species';
    RAISE NOTICE 'Next step: Test frontend and analysis functions';
    RAISE NOTICE '=================================================';
END $$;
