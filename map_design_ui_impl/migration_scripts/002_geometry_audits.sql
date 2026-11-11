-- Migration 002: Geometry edit audit trail
-- Source: map_designing_UI_report.md §15.2 G8 + §15.3 QA.12
-- Fix: 2026-07-28 — replaced JSONB GiST indexes (invalid) with GIN + removed spatial (audit is for replay, not spatial queries)
-- Date: 2026-07-28

-- ============================================================================
-- PART 1: geometry_audits table
-- ============================================================================
-- Design note: geometry is stored as JSONB (GeoJSON) for audit replay fidelity.
-- Spatial queries on audit data are not a use case — we track who changed what, not spatial overlap.
-- If spatial audit queries become needed, add dual-storage with PostGIS GEOMETRY columns.

CREATE TABLE IF NOT EXISTS geometry_audits (
    id BIGSERIAL PRIMARY KEY,
    calculation_id INTEGER NOT NULL REFERENCES calculations(id) ON DELETE CASCADE,
    layer_type VARCHAR(50) NOT NULL CHECK (layer_type IN (
        'forest_boundary', 'blocks', 'sub_areas', 'activity_features'
    )),
    operation VARCHAR(20) NOT NULL CHECK (operation IN (
        'CREATE', 'UPDATE', 'DELETE', 'SPLIT', 'MERGE', 'VERTEX_EDIT',
        'RENAME', 'DUPLICATE', 'RESHAPE', 'BUFFER', 'CLIP'
    )),
    feature_id VARCHAR(100),
    previous_geometry JSONB,  -- GeoJSON; no spatial index needed (audit log is append-only)
    new_geometry JSONB,       -- GeoJSON; see note above
    previous_properties JSONB,
    new_properties JSONB,
    user_id INTEGER NOT NULL REFERENCES users(id),
    session_id VARCHAR(100),
    undo_stack_id VARCHAR(100),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- PART 2: Indexes
-- ============================================================================
-- B-tree indexes for filter/sort query patterns (the actual audit use case)

CREATE INDEX idx_geometry_audits_calculation_id
ON geometry_audits (calculation_id);

CREATE INDEX idx_geometry_audits_layer_type
ON geometry_audits (layer_type);

CREATE INDEX idx_geometry_audits_operation
ON geometry_audits (operation);

CREATE INDEX idx_geometry_audits_user_id
ON geometry_audits (user_id);

CREATE INDEX idx_geometry_audits_created_at
ON geometry_audits (created_at DESC);

-- Composite index for the most common query: all audits for a calculation+layer, newest first
CREATE INDEX idx_geometry_audits_calc_layer
ON geometry_audits (calculation_id, layer_type, created_at DESC);

-- GIN indexes for JSONB query patterns (not GiST — JSONB is not a PostGIS geometry)
-- Used for property-based queries like "find all audits where feature name was 'C1'"
CREATE INDEX idx_geometry_audits_prev_props
ON geometry_audits USING GIN (previous_properties jsonb_path_ops)
WHERE previous_properties IS NOT NULL;

CREATE INDEX idx_geometry_audits_new_props
ON geometry_audits USING GIN (new_properties jsonb_path_ops)
WHERE new_properties IS NOT NULL;

-- GIN index on metadata for tag-based queries
CREATE INDEX idx_geometry_audits_metadata
ON geometry_audits USING GIN (metadata jsonb_path_ops)
WHERE metadata IS NOT NULL;

-- Index for undo_stack_id to support undo/redo replay
CREATE INDEX idx_geometry_audits_undo_stack
ON geometry_audits (undo_stack_id)
WHERE undo_stack_id IS NOT NULL;

-- ============================================================================
-- PART 3: Auto-vacuum tuning (high-write table)
-- ============================================================================

ALTER TABLE geometry_audits SET (
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_analyze_scale_factor = 0.05
);

-- ============================================================================
-- PART 4: Audit logging function
-- ============================================================================

CREATE OR REPLACE FUNCTION log_geometry_audit(
    p_calculation_id INTEGER,
    p_layer_type VARCHAR,
    p_operation VARCHAR,
    p_feature_id VARCHAR DEFAULT NULL,
    p_previous_geometry JSONB DEFAULT NULL,
    p_new_geometry JSONB DEFAULT NULL,
    p_previous_properties JSONB DEFAULT NULL,
    p_new_properties JSONB DEFAULT NULL,
    p_user_id INTEGER DEFAULT NULL,
    p_session_id VARCHAR DEFAULT NULL,
    p_undo_stack_id VARCHAR DEFAULT NULL,
    p_metadata JSONB DEFAULT NULL
) RETURNS BIGINT AS $$
DECLARE
    v_id BIGINT;
BEGIN
    INSERT INTO geometry_audits (
        calculation_id, layer_type, operation, feature_id,
        previous_geometry, new_geometry,
        previous_properties, new_properties,
        user_id, session_id, undo_stack_id, metadata
    ) VALUES (
        p_calculation_id, p_layer_type, p_operation, p_feature_id,
        p_previous_geometry, p_new_geometry,
        p_previous_properties, p_new_properties,
        COALESCE(p_user_id, current_setting('app.current_user_id', TRUE)::INTEGER),
        COALESCE(p_session_id, current_setting('app.current_session_id', TRUE)),
        p_undo_stack_id, p_metadata
    )
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- PART 5: Retention cleanup
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_old_geometry_audits()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM geometry_audits
    WHERE created_at < NOW() - INTERVAL '1 year'
    RETURNING 1 INTO v_deleted;

    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- Schedule weekly cleanup via pg_cron (if available)
-- SELECT cron.schedule('cleanup-geometry-audits', '0 3 * * 0',
--     'SELECT cleanup_old_geometry_audits()'
-- );

COMMENT ON TABLE geometry_audits IS
'Tracks all geometry mutations for audit trail and undo/redo support.
Retained for 1 year, then auto-cleaned. Geometry stored as GeoJSON JSONB.
No spatial indexes — audit trail queries are by calculation_id/layer_type/user_id, not spatial overlap.
See migration 003 (forest_boundary_audits) for PostGIS GEOMETRY columns with spatial indexes.';

-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- DROP TABLE IF EXISTS geometry_audits CASCADE;
-- DROP FUNCTION IF EXISTS log_geometry_audit;
-- DROP FUNCTION IF EXISTS cleanup_old_geometry_audits;
