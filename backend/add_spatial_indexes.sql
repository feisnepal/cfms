-- Add spatial indexes for User Group Map performance
-- This will significantly speed up ST_Intersects queries

-- Index on buildings.building.shape (6.3M rows - CRITICAL!)
CREATE INDEX IF NOT EXISTS idx_building_shape_gist
ON buildings.building USING GIST (shape);

-- Index on admin.settlement.shape (77K rows)
CREATE INDEX IF NOT EXISTS idx_settlement_shape_gist
ON admin.settlement USING GIST (shape);

-- Analyze tables to update statistics
ANALYZE buildings.building;
ANALYZE admin.settlement;

-- Vacuum to clean up
VACUUM ANALYZE buildings.building;
VACUUM ANALYZE admin.settlement;
