-- Migration 001: Add structure_locked column to calculations + structure_lock_audits
-- Source: map_designing_UI_report.md §14.8; code review 2026-07-28
-- Date: 2026-07-28

-- ============================================================================
-- PART 1: structure_locked flag on calculations
-- ============================================================================

ALTER TABLE calculations
ADD COLUMN structure_locked BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX idx_calculations_structure_locked
ON calculations (structure_locked)
WHERE structure_locked = TRUE;

-- Add a generated column to avoid correlated subquery in partial index
-- This replaces the invalid pattern: WHERE id IN (SELECT ... FROM operational_plans)
ALTER TABLE calculations
ADD COLUMN has_submitted_op BOOLEAN NOT NULL DEFAULT FALSE;

-- Trigger to keep has_submitted_op in sync
CREATE OR REPLACE FUNCTION fn_update_has_submitted_op()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'submitted' AND (OLD.status IS DISTINCT FROM 'submitted') THEN
        UPDATE calculations SET has_submitted_op = TRUE WHERE id = NEW.calculation_id;
    ELSIF OLD.status = 'submitted' AND (NEW.status IS DISTINCT FROM 'submitted') THEN
        UPDATE calculations SET has_submitted_op = FALSE WHERE id = NEW.calculation_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE INDEX idx_calculations_has_submitted_op
ON calculations (has_submitted_op)
WHERE has_submitted_op = TRUE;

-- ============================================================================
-- PART 2: Auto-lock trigger on OP submission
-- ============================================================================

CREATE OR REPLACE FUNCTION fn_auto_lock_structure_on_op_submit()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'submitted' AND (OLD.status IS DISTINCT FROM 'submitted') THEN
        UPDATE calculations
        SET structure_locked = TRUE
        WHERE id = NEW.calculation_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_auto_lock_structure ON operational_plans;
CREATE TRIGGER trg_auto_lock_structure
AFTER UPDATE OF status ON operational_plans
FOR EACH ROW
EXECUTE FUNCTION fn_auto_lock_structure_on_op_submit();

DROP TRIGGER IF EXISTS trg_update_has_submitted_op ON operational_plans;
CREATE TRIGGER trg_update_has_submitted_op
AFTER UPDATE OF status ON operational_plans
FOR EACH ROW
EXECUTE FUNCTION fn_update_has_submitted_op();

-- ============================================================================
-- PART 3: Structure Lock Audit Trail
-- ============================================================================

CREATE TABLE IF NOT EXISTS structure_lock_audits (
    id BIGSERIAL PRIMARY KEY,
    calculation_id INTEGER NOT NULL REFERENCES calculations(id) ON DELETE CASCADE,
    transition VARCHAR(20) NOT NULL CHECK (transition IN (
        'auto_lock', 'dfo_unlock', 'dfo_lock', 'admin_unlock', 'admin_lock'
    )),
    from_state BOOLEAN NOT NULL,
    to_state BOOLEAN NOT NULL,
    triggered_by_user_id INTEGER REFERENCES users(id),
    reason_np TEXT,
    session_id VARCHAR(100),
    source_ip VARCHAR(45),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sla_calculation_id ON structure_lock_audits (calculation_id);
CREATE INDEX idx_sla_transition ON structure_lock_audits (transition);
CREATE INDEX idx_sla_created_at ON structure_lock_audits (created_at DESC);

COMMENT ON TABLE structure_lock_audits IS
'Audit trail for every structure_locked transition.
Required by §14.8 for DFO unlock accountability.';

-- Trigger to auto-log structure_locked changes
CREATE OR REPLACE FUNCTION fn_audit_structure_lock_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.structure_locked IS DISTINCT FROM NEW.structure_locked THEN
        INSERT INTO structure_lock_audits (
            calculation_id, transition,
            from_state, to_state,
            triggered_by_user_id,
            created_at
        ) VALUES (
            NEW.id,
            CASE
                WHEN NEW.structure_locked = TRUE THEN 'auto_lock'
                ELSE 'admin_unlock'
            END,
            OLD.structure_locked,
            NEW.structure_locked,
            current_setting('app.current_user_id', TRUE)::INTEGER,
            NOW()
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_structure_lock ON calculations;
CREATE TRIGGER trg_audit_structure_lock
AFTER UPDATE OF structure_locked ON calculations
FOR EACH ROW
EXECUTE FUNCTION fn_audit_structure_lock_change();

-- ============================================================================
-- PART 4: Comments
-- ============================================================================

COMMENT ON COLUMN calculations.structure_locked IS
'When TRUE, block and sub-area geometry mutations are blocked (HTTP 423).
Automatically set to TRUE when OP status becomes "submitted".
Can be toggled by SUPER_ADMIN (DFO) via PATCH /admin/calculations/{id}/structure-lock';

COMMENT ON COLUMN calculations.has_submitted_op IS
'Denormalized flag for partial index filtering. Kept in sync by trigger trg_update_has_submitted_op.';

-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- DROP TRIGGER IF EXISTS trg_audit_structure_lock ON calculations;
-- DROP FUNCTION IF EXISTS fn_audit_structure_lock_change;
-- DROP TABLE IF EXISTS structure_lock_audits CASCADE;
-- DROP TRIGGER IF EXISTS trg_update_has_submitted_op ON operational_plans;
-- DROP TRIGGER IF EXISTS trg_auto_lock_structure ON operational_plans;
-- DROP FUNCTION IF EXISTS fn_auto_lock_structure_on_op_submit;
-- DROP FUNCTION IF EXISTS fn_update_has_submitted_op;
-- DROP INDEX IF EXISTS idx_calculations_has_submitted_op;
-- DROP INDEX IF EXISTS idx_calculations_structure_locked;
-- ALTER TABLE calculations DROP COLUMN has_submitted_op;
-- ALTER TABLE calculations DROP COLUMN structure_locked;
