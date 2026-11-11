-- ============================================================================
-- ROLLBACK SCRIPT: Phase 1A and 1B
-- Description: Restores database to state before Phase 1 migrations
-- Date: 2026-02-15
-- Database: cf_db (PostgreSQL)
-- WARNING: This will undo all changes made by 001 and 002 migration scripts
-- ============================================================================

-- Start transaction
BEGIN;

DO $$
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'ROLLBACK: Restoring Database to Pre-Migration State';
    RAISE NOTICE '=================================================';
END $$;

-- ============================================================================
-- STEP 1: VERIFY BACKUP TABLES EXIST
-- ============================================================================

DO $$
DECLARE
    forest_types_backup_exists BOOLEAN;
    species_backup_exists BOOLEAN;
    association_backup_exists BOOLEAN;
BEGIN
    -- Check if backup tables exist
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'forest_types_backup_20260215'
    ) INTO forest_types_backup_exists;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'tree_species_coefficients_backup_20260215'
    ) INTO species_backup_exists;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'forest_species_association_backup_20260215'
    ) INTO association_backup_exists;

    IF NOT forest_types_backup_exists THEN
        RAISE EXCEPTION 'Backup table forest_types_backup_20260215 not found. Cannot rollback safely.';
    END IF;

    IF NOT species_backup_exists THEN
        RAISE EXCEPTION 'Backup table tree_species_coefficients_backup_20260215 not found. Cannot rollback safely.';
    END IF;

    IF NOT association_backup_exists THEN
        RAISE EXCEPTION 'Backup table forest_species_association_backup_20260215 not found. Cannot rollback safely.';
    END IF;

    RAISE NOTICE 'All backup tables found. Proceeding with rollback...';
END $$;


-- ============================================================================
-- STEP 2: DROP CURRENT TABLES
-- ============================================================================

DROP TABLE IF EXISTS forest_species_association CASCADE;
DROP TABLE IF EXISTS tree_species_coefficients CASCADE;
DROP TABLE IF EXISTS forest_types CASCADE;

RAISE NOTICE 'Dropped current tables';


-- ============================================================================
-- STEP 3: RESTORE FROM BACKUPS
-- ============================================================================

-- Restore forest_types
CREATE TABLE forest_types AS
SELECT * FROM forest_types_backup_20260215;

-- Restore tree_species_coefficients
CREATE TABLE tree_species_coefficients AS
SELECT * FROM tree_species_coefficients_backup_20260215;

-- Restore forest_species_association
CREATE TABLE forest_species_association AS
SELECT * FROM forest_species_association_backup_20260215;

RAISE NOTICE 'Restored tables from backups';


-- ============================================================================
-- STEP 4: RECREATE PRIMARY KEYS AND INDEXES
-- ============================================================================

-- Add primary key to forest_types
ALTER TABLE forest_types ADD PRIMARY KEY (id);

-- Add primary key to tree_species_coefficients
ALTER TABLE tree_species_coefficients ADD PRIMARY KEY (id);

-- Add primary key to forest_species_association
ALTER TABLE forest_species_association ADD PRIMARY KEY (id);

-- Recreate unique constraint on scientific_name if it existed
DO $$
BEGIN
    BEGIN
        ALTER TABLE tree_species_coefficients
        ADD CONSTRAINT tree_species_coefficients_scientific_name_key
        UNIQUE (scientific_name);
    EXCEPTION WHEN duplicate_key THEN
        RAISE NOTICE 'Unique constraint on scientific_name already exists or has duplicates';
    END;
END $$;

-- Recreate foreign keys
DO $$
BEGIN
    BEGIN
        ALTER TABLE forest_species_association
        ADD CONSTRAINT forest_species_association_forest_type_id_fkey
        FOREIGN KEY (forest_type_id) REFERENCES forest_types(id);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'Could not recreate forest_type_id foreign key';
    END;

    BEGIN
        ALTER TABLE forest_species_association
        ADD CONSTRAINT forest_species_association_species_id_fkey
        FOREIGN KEY (species_id) REFERENCES tree_species_coefficients(id);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'Could not recreate species_id foreign key';
    END;
END $$;

RAISE NOTICE 'Recreated primary keys and constraints';


-- ============================================================================
-- STEP 5: RECREATE INDEXES
-- ============================================================================

-- Create common indexes
CREATE INDEX IF NOT EXISTS idx_forest_types_name
    ON forest_types(forest_type_name);

CREATE INDEX IF NOT EXISTS idx_species_scientific_name
    ON tree_species_coefficients(scientific_name);

CREATE INDEX IF NOT EXISTS idx_species_local_name
    ON tree_species_coefficients(local_name);

CREATE INDEX IF NOT EXISTS idx_association_forest_type
    ON forest_species_association(forest_type_id);

CREATE INDEX IF NOT EXISTS idx_association_species
    ON forest_species_association(species_id);

RAISE NOTICE 'Recreated indexes';


-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
DECLARE
    ft_count INTEGER;
    species_count INTEGER;
    association_count INTEGER;
    backup_ft_count INTEGER;
    backup_species_count INTEGER;
    backup_association_count INTEGER;
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'ROLLBACK VERIFICATION:';
    RAISE NOTICE '=================================================';

    -- Count records in restored tables
    SELECT COUNT(*) INTO ft_count FROM forest_types;
    SELECT COUNT(*) INTO species_count FROM tree_species_coefficients;
    SELECT COUNT(*) INTO association_count FROM forest_species_association;

    -- Count records in backup tables
    SELECT COUNT(*) INTO backup_ft_count FROM forest_types_backup_20260215;
    SELECT COUNT(*) INTO backup_species_count FROM tree_species_coefficients_backup_20260215;
    SELECT COUNT(*) INTO backup_association_count FROM forest_species_association_backup_20260215;

    RAISE NOTICE 'Forest types: % (backup had %)', ft_count, backup_ft_count;
    RAISE NOTICE 'Species: % (backup had %)', species_count, backup_species_count;
    RAISE NOTICE 'Associations: % (backup had %)', association_count, backup_association_count;

    IF ft_count = backup_ft_count AND
       species_count = backup_species_count AND
       association_count = backup_association_count THEN
        RAISE NOTICE 'SUCCESS: All record counts match backup';
    ELSE
        RAISE WARNING 'WARNING: Record counts do not match backup exactly';
    END IF;

    RAISE NOTICE '=================================================';
END $$;


-- ============================================================================
-- STEP 6: OPTIONAL - KEEP BACKUP TABLES OR DROP THEM
-- ============================================================================

-- Uncomment the following lines to drop backup tables after successful rollback
-- WARNING: This will permanently delete your backup data

-- DROP TABLE IF EXISTS forest_types_backup_20260215;
-- DROP TABLE IF EXISTS tree_species_coefficients_backup_20260215;
-- DROP TABLE IF EXISTS forest_species_association_backup_20260215;

RAISE NOTICE 'Backup tables retained. Drop manually if no longer needed.';


-- ============================================================================
-- COMMIT TRANSACTION
-- ============================================================================

COMMIT;

-- Final message
DO $$
BEGIN
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'ROLLBACK COMPLETED SUCCESSFULLY';
    RAISE NOTICE '=================================================';
    RAISE NOTICE 'Database restored to pre-migration state';
    RAISE NOTICE 'Backup tables still exist for safety';
    RAISE NOTICE 'To permanently remove backups, run:';
    RAISE NOTICE '  DROP TABLE forest_types_backup_20260215;';
    RAISE NOTICE '  DROP TABLE tree_species_coefficients_backup_20260215;';
    RAISE NOTICE '  DROP TABLE forest_species_association_backup_20260215;';
    RAISE NOTICE '=================================================';
END $$;
