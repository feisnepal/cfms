-- ============================================================================
-- VERIFICATION QUERIES - Run after import
-- ============================================================================

\echo '=========================================='
\echo 'FOREST TYPES VERIFICATION'
\echo '=========================================='

-- Total forest types
SELECT COUNT(*) as total_forest_types FROM forest_types;

-- Forest types with class numbers
SELECT COUNT(*) as types_with_class_number
FROM forest_types WHERE class_number IS NOT NULL;

-- Forest types without class numbers (should be 0)
SELECT COUNT(*) as types_missing_class_number
FROM forest_types WHERE class_number IS NULL;

-- List new forest types (Classes 20, 21, 23)
SELECT id, forest_type_name, class_number, pixel_value
FROM forest_types
WHERE class_number IN (20, 21, 23)
ORDER BY class_number;

-- All forest types ordered by class
SELECT class_number, forest_type_name, pixel_value
FROM forest_types
WHERE class_number IS NOT NULL
ORDER BY class_number;

\echo ''
\echo '=========================================='
\echo 'SPECIES VERIFICATION'
\echo '=========================================='

-- Total species count
SELECT COUNT(*) as total_species FROM tree_species_coefficients;

-- Check generic placeholders removed (should return 0 rows)
SELECT scientific_name, local_name
FROM tree_species_coefficients
WHERE scientific_name IN ('Broadleaved', 'Coniferious', 'Hill spp', 'Terai spp');

-- Check taxonomy updates
SELECT scientific_name, local_name, family
FROM tree_species_coefficients
WHERE scientific_name IN ('Syzygium cumini', 'Haldina cordifolia');

-- List 10 new priority species
SELECT scientific_name, local_name, family,
       min_altitude_m, max_altitude_m,
       growth_rate, economic_value
FROM tree_species_coefficients
WHERE scientific_name IN (
    'Castanopsis tribuloides', 'Quercus glauca', 'Lyonia ovalifolia',
    'Symplocos ramosissima', 'Castanopsis indica', 'Machilus gamblei',
    'Syzygium cumini', 'Haldina cordifolia', 'Ficus religiosa', 'Ficus benghalensis'
)
ORDER BY scientific_name;

-- Species with new characteristic data (should have non-null values)
SELECT COUNT(*) as species_with_altitude_data
FROM tree_species_coefficients
WHERE min_altitude_m IS NOT NULL OR max_altitude_m IS NOT NULL;

SELECT COUNT(*) as species_with_growth_rate
FROM tree_species_coefficients
WHERE growth_rate IS NOT NULL;

SELECT COUNT(*) as species_with_economic_value
FROM tree_species_coefficients
WHERE economic_value IS NOT NULL;

\echo ''
\echo '=========================================='
\echo 'BACKUP TABLES VERIFICATION'
\echo '=========================================='

-- Check backup tables exist
SELECT
    'forest_types_backup_20260215' as table_name,
    COUNT(*) as row_count
FROM forest_types_backup_20260215
UNION ALL
SELECT
    'tree_species_coefficients_backup_20260215',
    COUNT(*)
FROM tree_species_coefficients_backup_20260215
UNION ALL
SELECT
    'forest_species_association_backup_20260215',
    COUNT(*)
FROM forest_species_association_backup_20260215;

\echo ''
\echo '=========================================='
\echo 'COLUMN STRUCTURE VERIFICATION'
\echo '=========================================='

-- Check new columns in forest_types
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'forest_types'
  AND column_name = 'class_number';

-- Check new columns in tree_species_coefficients
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'tree_species_coefficients'
  AND column_name IN (
      'min_altitude_m', 'max_altitude_m', 'growth_rate',
      'economic_value', 'nitrogen_fixing', 'main_uses',
      'ecological_role', 'rarity_status', 'family'
  )
ORDER BY column_name;

\echo ''
\echo 'Verification complete!'
