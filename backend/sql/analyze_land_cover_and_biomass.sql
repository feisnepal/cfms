-- ============================================================================
-- Function: analyze_land_cover_and_biomass
-- Purpose: Perform comprehensive land cover and biomass analysis for user group maps
--          with community forest overlap exclusion
-- ============================================================================

CREATE OR REPLACE FUNCTION analyze_land_cover_and_biomass(
    p_user_group_geom geometry,
    p_forest_boundary_geom geometry
)
RETURNS TABLE(
    -- Summary statistics
    user_group_area_ha numeric,
    forest_overlap_area_ha numeric,
    net_analysis_area_ha numeric,

    -- Land cover classification (ESA World Cover)
    land_cover_class integer,
    land_cover_name text,
    land_cover_area_ha numeric,
    land_cover_percentage numeric,

    -- Biomass statistics (AGB 2022)
    avg_biomass_mg_per_ha numeric,
    min_biomass_mg_per_ha numeric,
    max_biomass_mg_per_ha numeric,
    total_biomass_mg numeric,

    -- Timber volume estimation (using conversion factor 0.67)
    avg_volume_m3_per_ha numeric,
    total_volume_m3 numeric,

    -- Detailed statistics
    pixel_count integer
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_net_geom geometry;
    v_net_area_ha numeric;
    v_overlap_area_ha numeric;
    v_user_group_area_ha numeric;
BEGIN
    -- Ensure geometries are valid
    p_user_group_geom := ST_MakeValid(p_user_group_geom);
    p_forest_boundary_geom := ST_MakeValid(p_forest_boundary_geom);

    -- Calculate areas
    v_user_group_area_ha := ST_Area(p_user_group_geom::geography) / 10000;

    -- Calculate overlap area
    IF ST_Intersects(p_user_group_geom, p_forest_boundary_geom) THEN
        v_overlap_area_ha := ST_Area(ST_Intersection(p_user_group_geom, p_forest_boundary_geom)::geography) / 10000;
    ELSE
        v_overlap_area_ha := 0;
    END IF;

    -- Calculate net geometry (user group - forest overlap)
    IF v_overlap_area_ha > 0 THEN
        v_net_geom := ST_Difference(p_user_group_geom, p_forest_boundary_geom);
    ELSE
        v_net_geom := p_user_group_geom;
    END IF;

    -- Calculate net area
    v_net_area_ha := ST_Area(v_net_geom::geography) / 10000;

    -- Return land cover and biomass analysis for each land cover class
    RETURN QUERY
    WITH land_cover_stats AS (
        SELECT
            (ST_ValueCount(ST_Clip(ew.rast, v_net_geom))).*
        FROM rasters.esa_world_cover ew
        WHERE ST_Intersects(ew.rast, v_net_geom)
    ),
    land_cover_summary AS (
        SELECT
            lc.value::integer AS class_code,
            CASE lc.value::integer
                WHEN 10 THEN 'Tree cover'
                WHEN 20 THEN 'Shrubland'
                WHEN 30 THEN 'Grassland'
                WHEN 40 THEN 'Cropland'
                WHEN 50 THEN 'Built-up'
                WHEN 60 THEN 'Bare / sparse vegetation'
                WHEN 70 THEN 'Snow and ice'
                WHEN 80 THEN 'Permanent water bodies'
                WHEN 90 THEN 'Herbaceous wetland'
                WHEN 95 THEN 'Mangroves'
                WHEN 100 THEN 'Moss and lichen'
                ELSE 'Unknown'
            END AS class_name,
            SUM(lc.count) AS pixel_count,
            -- ESA World Cover pixel size: 0.00008333 dd (~9.28m)
            -- Pixel area = (9.28m)^2 = ~86.12 m^2
            SUM(lc.count) * 86.12 / 10000 AS area_ha
        FROM land_cover_stats lc
        GROUP BY lc.value
    ),
    biomass_stats AS (
        SELECT
            lcs.class_code,
            lcs.class_name,
            lcs.area_ha,
            lcs.pixel_count,
            COALESCE(AVG((ST_ValueCount(ST_Clip(agb.rast, v_net_geom))).value::numeric), 0) AS avg_biomass,
            COALESCE(MIN((ST_ValueCount(ST_Clip(agb.rast, v_net_geom))).value::numeric), 0) AS min_biomass,
            COALESCE(MAX((ST_ValueCount(ST_Clip(agb.rast, v_net_geom))).value::numeric), 0) AS max_biomass
        FROM land_cover_summary lcs
        LEFT JOIN rasters.agb_2022_nepal agb ON ST_Intersects(agb.rast, v_net_geom)
        GROUP BY lcs.class_code, lcs.class_name, lcs.area_ha, lcs.pixel_count
    )
    SELECT
        v_user_group_area_ha,
        v_overlap_area_ha,
        v_net_area_ha,
        bs.class_code,
        bs.class_name,
        ROUND(bs.area_ha, 4),
        ROUND((bs.area_ha / NULLIF(v_net_area_ha, 0) * 100), 2),
        ROUND(bs.avg_biomass, 2),
        ROUND(bs.min_biomass, 2),
        ROUND(bs.max_biomass, 2),
        ROUND(bs.avg_biomass * bs.area_ha, 2),
        -- Timber volume calculation: biomass * 0.67 (wood density conversion factor)
        ROUND(bs.avg_biomass * 0.67, 2),
        ROUND(bs.avg_biomass * 0.67 * bs.area_ha, 2),
        bs.pixel_count::integer
    FROM biomass_stats bs
    ORDER BY bs.area_ha DESC;

END;
$$;

-- ============================================================================
-- Grant permissions
-- ============================================================================
GRANT EXECUTE ON FUNCTION analyze_land_cover_and_biomass(geometry, geometry) TO postgres;

-- ============================================================================
-- Example usage:
-- ============================================================================
-- SELECT * FROM analyze_land_cover_and_biomass(
--     (SELECT extent_geometry FROM public.user_group_extents WHERE id = 1),
--     (SELECT boundary_geom FROM public.calculations WHERE id = 'uuid-here')
-- );
