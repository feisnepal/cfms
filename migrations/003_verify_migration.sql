-- ============================================================================
-- VERIFICATION SCRIPT: Phase 1A and 1B Migrations
-- Description: Comprehensive checks to verify migration success
-- Date: 2026-02-15
-- Database: cf_db (PostgreSQL)
-- Usage: Run this script AFTER 001 and 002 migrations to verify results
-- ============================================================================

\echo '================================================================='
\echo 'MIGRATION VERIFICATION REPORT'
\echo '================================================================='
\echo ''

-- ============================================================================
-- CHECK 1: BACKUP TABLES EXIST
-- ============================================================================

\echo '1. BACKUP TABLE VERIFICATION:'
\echo '-----------------------------------------------------------------'

SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'forest_types_backup_20260215')
        THEN '✓ forest_types_backup_20260215 exists'
        ELSE '✗ forest_types_backup_20260215 MISSING'
    END AS backup_status
UNION ALL
SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tree_species_coefficients_backup_20260215')
        THEN '✓ tree_species_coefficients_backup_20260215 exists'
        ELSE '✗ tree_species_coefficients_backup_20260215 MISSING'
    END
UNION ALL
SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'forest_species_association_backup_20260215')
        THEN '✓ forest_species_association_backup_20260215 exists'
        ELSE '✗ forest_species_association_backup_20260215 MISSING'
    END;

\echo ''


-- ============================================================================
-- CHECK 2: FOREST TYPES COUNT AND CLASS NUMBERS
-- ============================================================================

\echo '2. FOREST TYPES VERIFICATION:'
\echo '-----------------------------------------------------------------'

SELECT
    COUNT(*) as total_forest_types,
    COUNT(class_number) as forest_types_with_class,
    COUNT(*) - COUNT(class_number) as forest_types_without_class
FROM forest_types;

\echo ''
\echo 'Expected: 25 total forest types, all with class numbers'
\echo ''
\echo 'Forest types by class number:'
SELECT
    class_number,
    forest_type_name
FROM forest_types
ORDER BY class_number;

\echo ''


-- ============================================================================
-- CHECK 3: GENERIC PLACEHOLDERS REMOVED
-- ============================================================================

\echo '3. GENERIC PLACEHOLDER VERIFICATION:'
\echo '-----------------------------------------------------------------'

SELECT
    CASE
        WHEN COUNT(*) = 0 THEN '✓ All generic placeholders removed'
        ELSE '✗ WARNING: ' || COUNT(*) || ' generic placeholders still exist'
    END as placeholder_status,
    COUNT(*) as placeholder_count
FROM tree_species_coefficients
WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp', 'Unknown');

\echo ''
\echo 'Remaining generic entries (should be empty):'
SELECT scientific_name, local_name
FROM tree_species_coefficients
WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp', 'Unknown')
   OR local_name = 'Unknown';

\echo ''


-- ============================================================================
-- CHECK 4: NEW COLUMNS ADDED
-- ============================================================================

\echo '4. NEW COLUMN VERIFICATION:'
\echo '-----------------------------------------------------------------'

SELECT
    column_name,
    data_type,
    CASE WHEN is_nullable = 'YES' THEN 'NULL' ELSE 'NOT NULL' END as nullable
FROM information_schema.columns
WHERE table_name = 'tree_species_coefficients'
  AND column_name IN (
    'max_height_m', 'max_dbh_cm', 'min_altitude_m', 'max_altitude_m',
    'growth_rate', 'economic_value', 'nitrogen_fixing',
    'main_uses', 'ecological_role', 'rarity_status', 'family'
  )
ORDER BY column_name;

\echo ''
\echo 'Expected: 11 new columns (max_height_m, max_dbh_cm, min_altitude_m, max_altitude_m, growth_rate, economic_value, nitrogen_fixing, main_uses, ecological_role, rarity_status, family)'
\echo ''


-- ============================================================================
-- CHECK 5: PRIORITY SPECIES ADDED
-- ============================================================================

\echo '5. PRIORITY SPECIES VERIFICATION:'
\echo '-----------------------------------------------------------------'

\echo 'Checking for 10 high-priority species:'
SELECT
    scientific_name,
    local_name,
    CASE
        WHEN max_height_m IS NOT NULL THEN '✓'
        ELSE '✗'
    END as has_data
FROM tree_species_coefficients
WHERE scientific_name IN (
    'Castanopsis tribuloides',
    'Castanopsis indica',
    'Quercus lanata',
    'Myrica esculenta',
    'Engelhardia spicata',
    'Terminalia chebula',
    'Toona ciliata',
    'Betula utilis',
    'Acer spp.',
    'Rhododendron campanulatum'
)
ORDER BY scientific_name;

\echo ''

SELECT
    CASE
        WHEN COUNT(*) >= 10 THEN '✓ All 10 priority species present'
        ELSE '✗ WARNING: Only ' || COUNT(*) || ' of 10 priority species found'
    END as species_status
FROM tree_species_coefficients
WHERE scientific_name IN (
    'Castanopsis tribuloides', 'Castanopsis indica', 'Quercus lanata',
    'Myrica esculenta', 'Engelhardia spicata', 'Terminalia chebula',
    'Toona ciliata', 'Betula utilis', 'Acer spp.', 'Rhododendron campanulatum'
);

\echo ''


-- ============================================================================
-- CHECK 6: SPECIES WITH COMPLETE CHARACTERISTICS
-- ============================================================================

\echo '6. SPECIES CHARACTERISTICS VERIFICATION:'
\echo '-----------------------------------------------------------------'

SELECT
    COUNT(*) as total_species,
    COUNT(max_height_m) as with_height,
    COUNT(min_altitude_m) as with_min_altitude,
    COUNT(max_altitude_m) as with_max_altitude,
    COUNT(growth_rate) as with_growth_rate,
    COUNT(economic_value) as with_economic_value,
    COUNT(main_uses) as with_uses,
    COUNT(ecological_role) as with_ecology,
    COUNT(family) as with_family
FROM tree_species_coefficients;

\echo ''
\echo 'Species with complete altitude ranges:'
SELECT
    scientific_name,
    local_name,
    min_altitude_m,
    max_altitude_m,
    growth_rate,
    economic_value
FROM tree_species_coefficients
WHERE min_altitude_m IS NOT NULL
  AND max_altitude_m IS NOT NULL
ORDER BY min_altitude_m;

\echo ''


-- ============================================================================
-- CHECK 7: NITROGEN-FIXING SPECIES
-- ============================================================================

\echo '7. NITROGEN-FIXING SPECIES:'
\echo '-----------------------------------------------------------------'

SELECT
    scientific_name,
    local_name,
    family,
    ecological_role
FROM tree_species_coefficients
WHERE nitrogen_fixing = TRUE
ORDER BY scientific_name;

\echo ''


-- ============================================================================
-- CHECK 8: SPECIES BY ECONOMIC VALUE
-- ============================================================================

\echo '8. SPECIES BY ECONOMIC VALUE:'
\echo '-----------------------------------------------------------------'

SELECT
    economic_value,
    COUNT(*) as species_count
FROM tree_species_coefficients
WHERE economic_value IS NOT NULL
GROUP BY economic_value
ORDER BY
    CASE economic_value
        WHEN 'Very High' THEN 1
        WHEN 'High' THEN 2
        WHEN 'Medium' THEN 3
        WHEN 'Low' THEN 4
        ELSE 5
    END;

\echo ''
\echo 'Very High economic value species:'
SELECT scientific_name, local_name, main_uses
FROM tree_species_coefficients
WHERE economic_value = 'Very High'
ORDER BY scientific_name;

\echo ''


-- ============================================================================
-- CHECK 9: UPDATED SCIENTIFIC NAMES
-- ============================================================================

\echo '9. SCIENTIFIC NAME UPDATES:'
\echo '-----------------------------------------------------------------'

SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM tree_species_coefficients WHERE scientific_name = 'Syzygium cumini')
        THEN '✓ Syzygium cumini present (updated from Eugenia jambolana)'
        ELSE '✗ Syzygium cumini not found'
    END as update_status
UNION ALL
SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM tree_species_coefficients WHERE scientific_name = 'Haldina cordifolia')
        THEN '✓ Haldina cordifolia present (updated from Adina cordifolia)'
        ELSE '✗ Haldina cordifolia not found'
    END
UNION ALL
SELECT
    CASE
        WHEN NOT EXISTS (SELECT 1 FROM tree_species_coefficients WHERE scientific_name = 'Eugenia jambolana')
        THEN '✓ Eugenia jambolana removed (old synonym)'
        ELSE '⚠ Eugenia jambolana still present (should be removed)'
    END;

\echo ''


-- ============================================================================
-- CHECK 10: FOREST TYPE CLASS NUMBER COVERAGE
-- ============================================================================

\echo '10. FOREST TYPE CLASS NUMBER COVERAGE:'
\echo '-----------------------------------------------------------------'

\echo 'Missing class numbers (should include only non-standard classes):'
SELECT generate_series AS missing_class
FROM generate_series(1, 25)
WHERE generate_series NOT IN (SELECT class_number FROM forest_types WHERE class_number IS NOT NULL);

\echo ''


-- ============================================================================
-- CHECK 11: DATA QUALITY CHECKS
-- ============================================================================

\echo '11. DATA QUALITY CHECKS:'
\echo '-----------------------------------------------------------------'

\echo 'Species with altitude ranges (min should be less than max):'
SELECT
    scientific_name,
    min_altitude_m,
    max_altitude_m,
    CASE
        WHEN min_altitude_m < max_altitude_m THEN '✓ Valid'
        ELSE '✗ INVALID'
    END as validity
FROM tree_species_coefficients
WHERE min_altitude_m IS NOT NULL
  AND max_altitude_m IS NOT NULL
ORDER BY scientific_name;

\echo ''

\echo 'Species with invalid or missing local names:'
SELECT scientific_name, local_name
FROM tree_species_coefficients
WHERE local_name IS NULL OR local_name = '' OR local_name = 'Unknown'
ORDER BY scientific_name;

\echo ''


-- ============================================================================
-- SUMMARY STATISTICS
-- ============================================================================

\echo '================================================================='
\echo 'SUMMARY STATISTICS'
\echo '================================================================='

SELECT
    'Forest Types' as category,
    COUNT(*)::text as count,
    'Total forest types in database' as description
FROM forest_types
UNION ALL
SELECT
    'Forest Types with Class',
    COUNT(class_number)::text,
    'Forest types assigned to regulation classes'
FROM forest_types
UNION ALL
SELECT
    'Tree Species',
    COUNT(*)::text,
    'Total tree species in database'
FROM tree_species_coefficients
UNION ALL
SELECT
    'Species with Characteristics',
    COUNT(*)::text,
    'Species with at least one characteristic filled'
FROM tree_species_coefficients
WHERE max_height_m IS NOT NULL
   OR economic_value IS NOT NULL
   OR main_uses IS NOT NULL
UNION ALL
SELECT
    'Species with Altitude Data',
    COUNT(*)::text,
    'Species with complete altitude range'
FROM tree_species_coefficients
WHERE min_altitude_m IS NOT NULL
  AND max_altitude_m IS NOT NULL
UNION ALL
SELECT
    'Nitrogen-Fixing Species',
    COUNT(*)::text,
    'Species that fix atmospheric nitrogen'
FROM tree_species_coefficients
WHERE nitrogen_fixing = TRUE
UNION ALL
SELECT
    'High-Value Species',
    COUNT(*)::text,
    'Species with High or Very High economic value'
FROM tree_species_coefficients
WHERE economic_value IN ('High', 'Very High');

\echo ''
\echo '================================================================='
\echo 'VERIFICATION COMPLETE'
\echo '================================================================='
\echo ''
\echo 'Review the results above to confirm migration success.'
\echo 'If any checks show warnings (✗), investigate before proceeding.'
\echo ''
