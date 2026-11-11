-- ============================================================================
-- ADD SPECIES DATA - 10 New Priority Species
-- Run this AFTER SIMPLE_DIRECT_UPDATES.sql
-- Date: 2026-02-15
-- ============================================================================

BEGIN;

-- ============================================================================
-- INSERT 10 HIGH-PRIORITY SPECIES
-- ============================================================================

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

-- Species 2: Castanopsis indica
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Castanopsis indica', 'Katus/Dhalne Katus', 'Fagaceae', 30.00, NULL,
     600, 2400, 'Moderate', 'Medium', FALSE,
     'Timber, aboveground biomass, carbon storage',
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

-- Species 3: Quercus lanata
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Quercus lanata', 'Dhalne Banj', 'Fagaceae', 25.00, NULL,
     1000, 2500, 'Slow', 'Medium', FALSE,
     'Fodder, fuelwood, timber, carbon storage',
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

-- Species 4: Myrica esculenta
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Myrica esculenta', 'Kaphal', 'Myricaceae', 12.00, 40.00,
     900, 2100, 'Moderate', 'High', TRUE,
     'Edible fruit (bayberry), fodder, medicine, timber',
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

-- Species 5: Engelhardia spicata
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Engelhardia spicata', 'Mauwa', 'Juglandaceae', 20.00, 60.00,
     600, 2000, 'Moderate', 'Medium', FALSE,
     'Timber (light construction), fodder, fuelwood',
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

-- Species 6: Terminalia chebula
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Terminalia chebula', 'Harro', 'Combretaceae', 30.00, 100.00,
     200, 1500, 'Moderate', 'Very High', FALSE,
     'Medicinal (myrobalan - Ayurvedic), tannin, timber, dye',
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

-- Species 7: Toona ciliata
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Toona ciliata', 'Tooni', 'Meliaceae', 35.00, 150.00,
     200, 1500, 'Fast', 'Very High', FALSE,
     'High-value timber (furniture, carving), plantation species',
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

-- Species 8: Betula utilis
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Betula utilis', 'Bhojpatra', 'Betulaceae', 20.00, 80.00,
     3000, 4500, 'Moderate', 'High', FALSE,
     'Bark (traditional writing material, sacred texts), timber, medicine',
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

-- Species 9: Acer spp.
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Acer spp.', 'Kimbu', 'Aceraceae', 25.00, 60.00,
     2000, 3500, 'Moderate', 'Medium', FALSE,
     'Timber, fuelwood, ornamental',
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

-- Species 10: Rhododendron campanulatum
INSERT INTO tree_species_coefficients
    (scientific_name, local_name, family, max_height_m, max_dbh_cm,
     min_altitude_m, max_altitude_m, growth_rate, economic_value,
     nitrogen_fixing, main_uses, ecological_role, rarity_status)
VALUES
    ('Rhododendron campanulatum', 'Chimal/Gurans', 'Ericaceae', 5.00, NULL,
     3000, 4500, 'Slow', 'Low', FALSE,
     'Ornamental, medicine, fuelwood',
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

-- ============================================================================
-- UPDATE EXISTING SPECIES WITH NEW DATA
-- ============================================================================

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

-- Update Pinus wallichiana
UPDATE tree_species_coefficients SET
    family = 'Pinaceae',
    max_height_m = 50.00,
    max_dbh_cm = 100.00,
    min_altitude_m = 1200,
    max_altitude_m = 4300,
    growth_rate = 'Moderate',
    economic_value = 'High',
    nitrogen_fixing = FALSE,
    main_uses = 'Timber, construction',
    ecological_role = 'Temperate zone dominant, 4.1 million m³ stem volume in Nepal',
    rarity_status = 'Common'
WHERE scientific_name = 'Pinus wallichiana';

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

-- Update Syzygium cumini (formerly Eugenia jambolana)
UPDATE tree_species_coefficients SET
    family = 'Myrtaceae',
    max_height_m = 30.00,
    max_dbh_cm = 80.00,
    min_altitude_m = 0,
    max_altitude_m = 1800,
    growth_rate = 'Moderate',
    economic_value = 'Medium',
    nitrogen_fixing = FALSE,
    main_uses = 'Edible fruit (jamun), timber, medicine',
    ecological_role = 'Tropical and subtropical mixed forests, fruit tree',
    rarity_status = 'Common'
WHERE scientific_name = 'Syzygium cumini';

-- Success message
DO $$
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'SPECIES DATA ADDED SUCCESSFULLY';
    RAISE NOTICE '=================================================';
    RAISE NOTICE '10 new priority species added/updated';
    RAISE NOTICE '8 existing species updated with characteristics';
    RAISE NOTICE '=================================================';
END $$;

COMMIT;
