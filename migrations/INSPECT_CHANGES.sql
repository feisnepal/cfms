-- ============================================================================
-- INSPECTION SCRIPT: Compare Test vs Production
-- Description: Shows what will change when migration runs
-- Date: 2026-02-15
-- Usage: Run this on BOTH cf_db and cf_db_test to compare
-- ============================================================================

\echo '================================================================='
\echo 'DATABASE INSPECTION REPORT'
\echo '================================================================='
\echo ''
\echo 'Current Database: '
SELECT current_database();
\echo ''

-- ============================================================================
-- SECTION 1: FOREST TYPES OVERVIEW
-- ============================================================================

\echo ''
\echo '1. FOREST TYPES:'
\echo '-----------------------------------------------------------------'

SELECT
    COUNT(*) as total_forest_types,
    COUNT(CASE WHEN class_number IS NOT NULL THEN 1 END) as with_class_number,
    COUNT(CASE WHEN class_number IS NULL THEN 1 END) as without_class_number
FROM forest_types;

\echo ''
\echo 'Forest Types List:'
SELECT
    COALESCE(class_number::text, 'NULL') as class,
    forest_type_name
FROM forest_types
ORDER BY class_number NULLS LAST, forest_type_name;

\echo ''

-- ============================================================================
-- SECTION 2: SPECIES OVERVIEW
-- ============================================================================

\echo '2. SPECIES OVERVIEW:'
\echo '-----------------------------------------------------------------'

SELECT
    COUNT(*) as total_species,
    COUNT(CASE WHEN scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp') THEN 1 END) as generic_placeholders,
    COUNT(CASE WHEN local_name = 'Unknown' OR local_name IS NULL THEN 1 END) as unknown_local_names,
    COUNT(CASE WHEN max_height_m IS NOT NULL THEN 1 END) as with_height_data,
    COUNT(CASE WHEN min_altitude_m IS NOT NULL AND max_altitude_m IS NOT NULL THEN 1 END) as with_altitude_data
FROM tree_species_coefficients;

\echo ''

-- ============================================================================
-- SECTION 3: GENERIC PLACEHOLDERS (Should be removed)
-- ============================================================================

\echo '3. GENERIC PLACEHOLDER SPECIES (should be 0 after migration):'
\echo '-----------------------------------------------------------------'

SELECT
    scientific_name,
    local_name,
    'SHOULD BE REMOVED' as status
FROM tree_species_coefficients
WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp')
ORDER BY scientific_name;

\echo ''

-- ============================================================================
-- SECTION 4: ALL SPECIES WITH CHARACTERISTICS
-- ============================================================================

\echo '4. ALL SPECIES (showing characteristics):'
\echo '-----------------------------------------------------------------'

SELECT
    scientific_name,
    local_name,
    COALESCE(max_height_m::text, '-') as height_m,
    COALESCE(min_altitude_m::text || '-' || max_altitude_m::text, '-') as altitude_range,
    COALESCE(growth_rate, '-') as growth,
    COALESCE(economic_value, '-') as econ_value,
    CASE WHEN nitrogen_fixing THEN 'YES' ELSE '-' END as n_fixing
FROM tree_species_coefficients
ORDER BY scientific_name;

\echo ''

-- ============================================================================
-- SECTION 5: NEW SPECIES (will be added in Phase 1B)
-- ============================================================================

\echo '5. PRIORITY SPECIES STATUS (should all exist after migration):'
\echo '-----------------------------------------------------------------'

SELECT
    species_name,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM tree_species_coefficients
            WHERE scientific_name = species_name
        ) THEN 'EXISTS'
        ELSE 'MISSING'
    END as status
FROM (VALUES
    ('Castanopsis tribuloides'),
    ('Castanopsis indica'),
    ('Quercus lanata'),
    ('Myrica esculenta'),
    ('Engelhardia spicata'),
    ('Terminalia chebula'),
    ('Toona ciliata'),
    ('Betula utilis'),
    ('Acer spp.'),
    ('Rhododendron campanulatum')
) AS t(species_name)
ORDER BY status DESC, species_name;

\echo ''

-- ============================================================================
-- SECTION 6: UPDATED SPECIES NAMES (taxonomy updates)
-- ============================================================================

\echo '6. TAXONOMY UPDATES (should show new names after migration):'
\echo '-----------------------------------------------------------------'

SELECT
    old_name,
    new_name,
    CASE
        WHEN EXISTS (SELECT 1 FROM tree_species_coefficients WHERE scientific_name = new_name)
        THEN 'NEW NAME EXISTS'
        WHEN EXISTS (SELECT 1 FROM tree_species_coefficients WHERE scientific_name = old_name)
        THEN 'OLD NAME STILL PRESENT'
        ELSE 'NEITHER EXISTS'
    END as status
FROM (VALUES
    ('Eugenia jambolana', 'Syzygium cumini'),
    ('Adina cordifolia', 'Haldina cordifolia')
) AS t(old_name, new_name);

\echo ''

-- ============================================================================
-- SECTION 7: FOREST TYPE CLASS COVERAGE
-- ============================================================================

\echo '7. FOREST TYPE CLASS NUMBER COVERAGE:'
\echo '-----------------------------------------------------------------'

\echo 'Classes 1-25 that exist:'
SELECT class_number, forest_type_name
FROM forest_types
WHERE class_number BETWEEN 1 AND 25
ORDER BY class_number;

\echo ''
\echo 'Missing classes (should be empty after migration):'
SELECT generate_series as missing_class
FROM generate_series(1, 25)
WHERE generate_series NOT IN (
    SELECT class_number FROM forest_types WHERE class_number IS NOT NULL
)
ORDER BY generate_series;

\echo ''

-- ============================================================================
-- SECTION 8: DATA QUALITY CHECKS
-- ============================================================================

\echo '8. DATA QUALITY:'
\echo '-----------------------------------------------------------------'

SELECT
    'Species with NULL local names' as check_type,
    COUNT(*)::text as count
FROM tree_species_coefficients
WHERE local_name IS NULL OR local_name = ''
UNION ALL
SELECT
    'Species with invalid altitude ranges (min > max)',
    COUNT(*)::text
FROM tree_species_coefficients
WHERE min_altitude_m IS NOT NULL
  AND max_altitude_m IS NOT NULL
  AND min_altitude_m >= max_altitude_m
UNION ALL
SELECT
    'Orphaned species associations',
    COUNT(*)::text
FROM forest_species_association fsa
WHERE NOT EXISTS (SELECT 1 FROM tree_species_coefficients WHERE id = fsa.species_id);

\echo ''

-- ============================================================================
-- SECTION 9: COLUMN EXISTENCE CHECK
-- ============================================================================

\echo '9. NEW COLUMNS IN tree_species_coefficients:'
\echo '-----------------------------------------------------------------'

SELECT
    column_name,
    data_type,
    CASE WHEN is_nullable = 'YES' THEN 'NULLABLE' ELSE 'NOT NULL' END as nullable
FROM information_schema.columns
WHERE table_name = 'tree_species_coefficients'
  AND column_name IN (
    'max_height_m', 'max_dbh_cm', 'min_altitude_m', 'max_altitude_m',
    'growth_rate', 'economic_value', 'nitrogen_fixing',
    'main_uses', 'ecological_role', 'rarity_status', 'family'
  )
ORDER BY column_name;

\echo ''

-- ============================================================================
-- SECTION 10: BACKUP TABLES CHECK
-- ============================================================================

\echo '10. BACKUP TABLES (should exist after Phase 1A on test):'
\echo '-----------------------------------------------------------------'

SELECT
    table_name,
    CASE
        WHEN table_name LIKE '%backup%' THEN 'BACKUP TABLE'
        ELSE 'PRODUCTION TABLE'
    END as type
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name LIKE '%backup%'
ORDER BY table_name;

\echo ''
\echo '================================================================='
\echo 'INSPECTION COMPLETE'
\echo '================================================================='
\echo ''
\echo 'Compare this output between cf_db (production) and cf_db_test'
\echo 'to see what will change when migration runs.'
\echo ''
