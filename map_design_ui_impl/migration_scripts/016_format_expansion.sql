-- Migration: workspace_layers table
-- Part of Phase 1.1: Workspace Import Infrastructure
-- Run via: psql -U postgres -d cf_db -f 016_format_expansion.sql

CREATE TABLE IF NOT EXISTS workspace_layers (
    id SERIAL PRIMARY KEY,
    calculation_id INTEGER NOT NULL REFERENCES calculations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    purpose VARCHAR(50) NOT NULL DEFAULT 'custom',
    source_format VARCHAR(10) NOT NULL,
    feature_count INTEGER DEFAULT 0,
    file_size_bytes INTEGER,
    geometry_types JSONB,
    layer_data JSONB,
    layer_metadata JSONB,
    layer_hash VARCHAR(64),
    is_draft BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    created_by INTEGER REFERENCES users(id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_workspace_layers_calc_id ON workspace_layers(calculation_id);
CREATE INDEX IF NOT EXISTS idx_workspace_layers_calc_draft ON workspace_layers(calculation_id, is_draft);
CREATE INDEX IF NOT EXISTS idx_workspace_layers_calc_purpose ON workspace_layers(calculation_id, purpose);
CREATE INDEX IF NOT EXISTS idx_workspace_layers_calc_hash ON workspace_layers(calculation_id, layer_hash);

-- DOWN
-- DROP TABLE IF EXISTS workspace_layers CASCADE;
