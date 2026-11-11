-- Migration 003: Forest boundary overlap resolution audit + dispute system
-- Source: map_designing_UI_report.md §11.8 + §11.11
-- Fix: 2026-07-28 — reordered tables (boundary_disputes before forest_boundary_audits),
--       added pending_boundary_submissions for concurrent overlap prevention
-- Date: 2026-07-28

-- ============================================================================
-- PART 1: Boundary Status Column on calculations
-- ============================================================================

ALTER TABLE calculations
ADD COLUMN boundary_status VARCHAR(20) NOT NULL DEFAULT 'draft'
CHECK (boundary_status IN ('draft', 'validated', 'approved', 'disputed'));

ALTER TABLE calculations
ADD COLUMN boundary_status_changed_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE calculations
ADD COLUMN boundary_status_changed_by UUID REFERENCES users(id);

CREATE INDEX idx_calculations_boundary_status
ON calculations (boundary_status)
WHERE boundary_status IN ('draft', 'disputed');

COMMENT ON COLUMN calculations.boundary_status IS
'draft=being created, validated=auto-clipped awaiting verification,
approved=super admin verified ground truth, disputed=challenged by another user';

-- ============================================================================
-- PART 2: Pending Boundary Submissions (concurrent overlap prevention)
-- ============================================================================
-- Solves the race condition where two users submit boundaries that overlap each
-- other but neither exists in calculations yet. See code review §11.
-- Entries expire after 5 minutes (cleaned by trigger or periodic cleanup).

CREATE TABLE IF NOT EXISTS pending_boundary_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    proposed_geometry GEOMETRY(Polygon, 4326) NOT NULL,
    proposed_area_ha DECIMAL(10,4),
    calculation_id INTEGER REFERENCES calculations(id),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'confirmed', 'expired', 'rejected'
    )),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW() + INTERVAL '5 minutes',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pbs_session ON pending_boundary_submissions (session_id);
CREATE INDEX idx_pbs_status ON pending_boundary_submissions (status)
    WHERE status = 'pending';
CREATE INDEX idx_pbs_expires ON pending_boundary_submissions (expires_at)
    WHERE status = 'pending';

-- GiST index for spatial overlap check against pending submissions
CREATE INDEX idx_pbs_geom
ON pending_boundary_submissions USING GIST (proposed_geometry)
WHERE status = 'pending';

COMMENT ON TABLE pending_boundary_submissions IS
'In-flight boundary submissions for concurrent overlap prevention.
Two-phase commit: preview() inserts pending row, confirm() resolves it.
Expired entries cleaned by fn_expire_stale_pending_submissions().';

-- Cleanup function for expired pending submissions
CREATE OR REPLACE FUNCTION fn_expire_stale_pending_submissions()
RETURNS INTEGER AS $$
DECLARE
    v_expired INTEGER;
BEGIN
    UPDATE pending_boundary_submissions
    SET status = 'expired'
    WHERE status = 'pending' AND expires_at < NOW()
    RETURNING 1 INTO v_expired;

    RETURN v_expired;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- PART 3: Boundary Disputes Table (defined BEFORE forest_boundary_audits to resolve FK order)
-- ============================================================================

CREATE TABLE IF NOT EXISTS boundary_disputes (
    id BIGSERIAL PRIMARY KEY,
    forest_id_a INTEGER NOT NULL REFERENCES calculations(id) ON DELETE CASCADE,
    forest_id_b INTEGER NOT NULL REFERENCES calculations(id) ON DELETE CASCADE,
    forest_a_boundary GEOMETRY(Polygon, 4326),
    forest_b_boundary GEOMETRY(Polygon, 4326),
    forest_a_proposed_geometry GEOMETRY(Polygon, 4326),
    overlap_area GEOMETRY(Polygon, 4326),
    overlap_area_ha DECIMAL(10,4),
    filed_by_user_id INTEGER NOT NULL REFERENCES users(id),
    filed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    reason_np TEXT NOT NULL,
    reason_en TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN (
        'open', 'under_review', 'resolved', 'dismissed'
    )),
    assigned_to_dfo_id INTEGER REFERENCES users(id),
    dfo_edited_forest_id INTEGER REFERENCES calculations(id),
    dfo_new_boundary GEOMETRY(Polygon, 4326),
    dfo_reason_np TEXT,
    dfo_resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_forest_a_status VARCHAR(20),
    resolved_forest_b_status VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_bd_forest_a ON boundary_disputes (forest_id_a);
CREATE INDEX idx_bd_forest_b ON boundary_disputes (forest_id_b);
CREATE INDEX idx_bd_status ON boundary_disputes (status)
    WHERE status = 'open';
CREATE INDEX idx_bd_filed_by ON boundary_disputes (filed_by_user_id);
CREATE INDEX idx_bd_assigned_dfo ON boundary_disputes (assigned_to_dfo_id)
    WHERE assigned_to_dfo_id IS NOT NULL;

-- GiST spatial index on overlap_area for DFO review map
CREATE INDEX idx_bd_overlap_area
ON boundary_disputes USING GIST (overlap_area)
WHERE overlap_area IS NOT NULL;

-- ============================================================================
-- PART 4: Forest Boundary Audits Table (with FK to boundary_disputes, which now exists)
-- ============================================================================

CREATE TABLE IF NOT EXISTS forest_boundary_audits (
    id BIGSERIAL PRIMARY KEY,
    forest_id INTEGER NOT NULL REFERENCES calculations(id) ON DELETE CASCADE,
    submitted_geometry GEOMETRY(Polygon, 4326),
    submitted_area_ha DECIMAL(10,4),
    submitted_by_user_id INTEGER NOT NULL REFERENCES users(id),
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    resolved_geometry GEOMETRY(Polygon, 4326),
    resolved_area_ha DECIMAL(10,4),
    overlap_removed_ha DECIMAL(10,4),
    overlap_percentage DECIMAL(5,2),
    overlap_with_forest_ids INTEGER[],
    overlap_with_forest_names TEXT[],
    pending_submission_id UUID REFERENCES pending_boundary_submissions(id),
    resolution_method VARCHAR(30) NOT NULL CHECK (resolution_method IN (
        'auto_clip', 'auto_approve', 'user_confirmed', 'admin_override', 'snap_only', 'rejected'
    )),
    auto_approve BOOLEAN NOT NULL DEFAULT FALSE,
    user_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    user_confirmed_at TIMESTAMP WITH TIME ZONE,
    dispute_id BIGINT REFERENCES boundary_disputes(id),
    rejection_reason TEXT,
    dfo_user_id INTEGER REFERENCES users(id),
    dfo_reason_np TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_fba_forest_id ON forest_boundary_audits (forest_id);
CREATE INDEX idx_fba_submitted_by ON forest_boundary_audits (submitted_by_user_id);
CREATE INDEX idx_fba_method ON forest_boundary_audits (resolution_method);
CREATE INDEX idx_fba_submitted_at ON forest_boundary_audits (submitted_at DESC);
CREATE INDEX idx_fba_dispute_id ON forest_boundary_audits (dispute_id)
    WHERE dispute_id IS NOT NULL;
CREATE INDEX idx_fba_pending_id ON forest_boundary_audits (pending_submission_id)
    WHERE pending_submission_id IS NOT NULL;

-- GiST spatial indexes for PostGIS GEOMETRY columns (valid — GEOMETRY type, not JSONB)
CREATE INDEX idx_fba_submitted_geom
ON forest_boundary_audits USING GIST (submitted_geometry)
WHERE submitted_geometry IS NOT NULL;

CREATE INDEX idx_fba_resolved_geom
ON forest_boundary_audits USING GIST (resolved_geometry)
WHERE resolved_geometry IS NOT NULL;

-- ============================================================================
-- PART 5: Update trigger for boundary_disputes.updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION fn_update_boundary_dispute_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_boundary_disputes_updated_at ON boundary_disputes;
CREATE TRIGGER trg_boundary_disputes_updated_at
BEFORE UPDATE ON boundary_disputes
FOR EACH ROW
EXECUTE FUNCTION fn_update_boundary_dispute_timestamp();

-- ============================================================================
-- PART 6: Function to find nearby forests within 200m
-- ============================================================================

CREATE OR REPLACE FUNCTION find_nearby_forests(
    p_boundary GEOMETRY,
    p_exclude_forest_id INTEGER DEFAULT NULL,
    p_radius_meters INTEGER DEFAULT 200
)
RETURNS TABLE(
    forest_id INTEGER,
    forest_name VARCHAR,
    boundary_status VARCHAR,
    distance_meters DECIMAL(10,2),
    boundary GEOMETRY,
    boundary_geojson JSON
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id AS forest_id,
        c.name AS forest_name,
        c.boundary_status,
        ROUND(ST_Distance(
            c.boundary_geom::geography,
            ST_Centroid(p_boundary)::geography
        )::DECIMAL, 2) AS distance_meters,
        c.boundary_geom AS boundary,
        ST_AsGeoJSON(c.boundary_geom)::JSON AS boundary_geojson
    FROM calculations c
    WHERE c.boundary_geom IS NOT NULL
      AND ST_DWithin(
          c.boundary_geom::geography,
          p_boundary::geography,
          p_radius_meters
      )
      AND (p_exclude_forest_id IS NULL OR c.id != p_exclude_forest_id)
    ORDER BY distance_meters ASC;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- PART 7: Function to check overlap percentage
-- ============================================================================

CREATE OR REPLACE FUNCTION calculate_overlap_percentage(
    p_new_boundary GEOMETRY,
    p_existing_boundary GEOMETRY
)
RETURNS TABLE(
    overlap_area_ha DECIMAL(10,4),
    new_area_ha DECIMAL(10,4),
    overlap_percentage DECIMAL(5,2),
    is_auto_approve BOOLEAN,
    requires_confirmation BOOLEAN,
    requires_rejection BOOLEAN
) AS $$
DECLARE
    v_overlap_sqm DECIMAL;
    v_new_sqm DECIMAL;
    v_pct DECIMAL;
BEGIN
    v_new_sqm := ST_Area(p_new_boundary::geography);
    v_overlap_sqm := ST_Area(
        ST_Intersection(p_new_boundary, p_existing_boundary)::geography
    );

    overlap_area_ha := ROUND(v_overlap_sqm / 10000, 4);
    new_area_ha := ROUND(v_new_sqm / 10000, 4);

    IF v_new_sqm > 0 THEN
        v_pct := (v_overlap_sqm / v_new_sqm) * 100;
    ELSE
        v_pct := 0;
    END IF;

    overlap_percentage := ROUND(v_pct, 2);

    -- Thresholds from design doc §11.10
    is_auto_approve := v_pct <= 40;
    requires_confirmation := v_pct > 40 AND v_pct <= 80;
    requires_rejection := v_pct > 80;

    RETURN NEXT;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- PART 8: Function to check overlap with pending submissions
-- ============================================================================

CREATE OR REPLACE FUNCTION check_pending_overlaps(
    p_proposed_geometry GEOMETRY,
    p_current_session_id UUID DEFAULT NULL
)
RETURNS TABLE(
    session_id UUID,
    user_id INTEGER,
    overlap_area_ha DECIMAL(10,4),
    overlap_percentage DECIMAL(5,2)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        pbs.session_id,
        pbs.user_id,
        ROUND(ST_Area(ST_Intersection(pbs.proposed_geometry, p_proposed_geometry)::geography) / 10000, 4),
        ROUND(
            ST_Area(ST_Intersection(pbs.proposed_geometry, p_proposed_geometry)::geography) /
            NULLIF(ST_Area(p_proposed_geometry::geography), 0) * 100,
        2)
    FROM pending_boundary_submissions pbs
    WHERE pbs.status = 'pending'
      AND pbs.expires_at > NOW()
      AND ST_Intersects(pbs.proposed_geometry, p_proposed_geometry)
      AND (p_current_session_id IS NULL OR pbs.session_id != p_current_session_id)
    ORDER BY overlap_percentage DESC;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE forest_boundary_audits IS
'Audit trail for every forest boundary submission and overlap resolution.
Retains both submitted and resolved geometry for full traceability.
references pending_boundary_submissions for concurrent submission tracking.';

COMMENT ON TABLE boundary_disputes IS
'Tracks boundary disputes between two forests.
DFO/super_admin reviews and resolves with mandatory Nepali reason.';

-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- DROP FUNCTION IF EXISTS check_pending_overlaps;
-- DROP FUNCTION IF EXISTS calculate_overlap_percentage;
-- DROP FUNCTION IF EXISTS find_nearby_forests;
-- DROP FUNCTION IF EXISTS fn_expire_stale_pending_submissions;
-- DROP TRIGGER IF EXISTS trg_boundary_disputes_updated_at ON boundary_disputes;
-- DROP FUNCTION IF EXISTS fn_update_boundary_dispute_timestamp;
-- DROP TABLE IF EXISTS forest_boundary_audits CASCADE;
-- DROP TABLE IF EXISTS boundary_disputes CASCADE;
-- DROP TABLE IF EXISTS pending_boundary_submissions CASCADE;
-- DROP INDEX IF EXISTS idx_calculations_boundary_status;
-- ALTER TABLE calculations DROP COLUMN boundary_status;
