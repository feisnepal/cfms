-- PostgreSQL Function: analyze_nearby_features (BY TYPE - Closest Only)
-- Groups features by TYPE and shows only the closest of each type
-- E.g., "River/Stream" instead of listing 15 individual rivers

CREATE OR REPLACE FUNCTION analyze_nearby_features(
    p_geom_wkt TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_geom GEOMETRY;
    v_centroid GEOMETRY;
    v_result JSONB;
    v_north_features TEXT;
    v_east_features TEXT;
    v_south_features TEXT;
    v_west_features TEXT;
BEGIN
    -- Convert WKT to geometry (assume SRID 4326)
    v_geom := ST_Force2D(ST_GeomFromText(p_geom_wkt, 4326));
    v_centroid := ST_Centroid(v_geom);

    -- Combine all features from all sources with CTE
    WITH all_features AS (
        -- 1. ESA Forest Boundaries - Type: "Boundary"
        SELECT
            'Boundary' as feature_type,
            description as feature_detail,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645)) / 1000.0 as distance_km
        FROM admin."esa_forest_Boundary"
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND description IS NOT NULL

        UNION ALL

        -- 2. Settlements - Type: "Settlement"
        SELECT
            'Settlement' as feature_type,
            vil_name as feature_detail,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(shape, v_centroid))) as azimuth,
            ST_Distance(ST_Transform(v_geom, 32645), ST_Transform(shape, 32645)) / 1000.0 as distance_km
        FROM admin.settlement
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(shape, 32645), 100)
            AND vil_name IS NOT NULL

        UNION ALL

        -- 3. Rivers - Type: "River/Stream"
        SELECT
            'River/Stream' as feature_type,
            COALESCE(river_name, features) as feature_detail,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645)) / 1000.0 as distance_km
        FROM river.river_line
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (river_name IS NOT NULL OR features IS NOT NULL)

        UNION ALL

        -- 4. Ridges - Each ridge name is a unique feature type
        SELECT
            ridge_name as feature_type,
            ridge_name as feature_detail,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645)) / 1000.0 as distance_km
        FROM river.ridge
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND ridge_name IS NOT NULL

        UNION ALL

        -- 5. Education Facilities - Type: "School/Education"
        SELECT
            'School/Education' as feature_type,
            name as feature_detail,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645)) / 1000.0 as distance_km
        FROM infrastructure.education_facilities
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND name IS NOT NULL

        UNION ALL

        -- 6. Health Facilities - Type: "Health Facility"
        SELECT
            'Health Facility' as feature_type,
            CONCAT(hf_type, ' ', vdc_name1) as feature_detail,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645)) / 1000.0 as distance_km
        FROM infrastructure.health_facilities
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (hf_type IS NOT NULL OR vdc_name1 IS NOT NULL)

        UNION ALL

        -- 7. Points of Interest - Type: amenity or "POI"
        SELECT
            COALESCE(amenity, 'POI') as feature_type,
            COALESCE(name, name_en, name_ne, amenity) as feature_detail,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645)) / 1000.0 as distance_km
        FROM infrastructure.poi
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (name IS NOT NULL OR name_en IS NOT NULL OR name_ne IS NOT NULL OR amenity IS NOT NULL)

        UNION ALL

        -- 8. Roads - Type: "Road"
        SELECT
            'Road' as feature_type,
            name as feature_detail,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645)) / 1000.0 as distance_km
        FROM infrastructure.road
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND name IS NOT NULL
    ),
    -- Add direction classification
    features_with_direction AS (
        SELECT
            feature_type,
            feature_detail,
            azimuth,
            distance_km,
            CASE
                WHEN azimuth >= 315 OR azimuth < 45 THEN 'North'
                WHEN azimuth >= 45 AND azimuth < 135 THEN 'East'
                WHEN azimuth >= 135 AND azimuth < 225 THEN 'South'
                ELSE 'West'
            END as direction
        FROM all_features
        WHERE feature_type IS NOT NULL AND feature_type != ''
    ),
    -- Keep only the CLOSEST occurrence of each FEATURE TYPE per direction
    closest_by_type AS (
        SELECT DISTINCT ON (feature_type, direction)
            feature_type,
            feature_detail,
            direction,
            azimuth,
            distance_km
        FROM features_with_direction
        ORDER BY feature_type, direction, distance_km ASC
    ),
    -- Format and aggregate by direction
    formatted_features AS (
        SELECT
            direction,
            string_agg(
                format('%s %s (%s°) %s km',
                    COALESCE(feature_detail, feature_type),
                    direction,
                    ROUND(azimuth::NUMERIC, 0),
                    ROUND(distance_km::NUMERIC, 2)
                ),
                ', '
                ORDER BY distance_km ASC
            ) as features_text
        FROM closest_by_type
        GROUP BY direction
    )
    -- Build final result
    SELECT
        COALESCE(MAX(CASE WHEN direction = 'North' THEN features_text END), NULL),
        COALESCE(MAX(CASE WHEN direction = 'East' THEN features_text END), NULL),
        COALESCE(MAX(CASE WHEN direction = 'South' THEN features_text END), NULL),
        COALESCE(MAX(CASE WHEN direction = 'West' THEN features_text END), NULL)
    INTO v_north_features, v_east_features, v_south_features, v_west_features
    FROM formatted_features;

    -- Build result JSONB
    v_result := jsonb_build_object(
        'features_north', v_north_features,
        'features_east', v_east_features,
        'features_south', v_south_features,
        'features_west', v_west_features
    );

    RETURN v_result;

EXCEPTION
    WHEN OTHERS THEN
        -- Return empty result on any error
        RETURN jsonb_build_object(
            'features_north', NULL,
            'features_east', NULL,
            'features_south', NULL,
            'features_west', NULL,
            'error', SQLERRM
        );
END;
$$;

-- Grant execute permission
GRANT EXECUTE ON FUNCTION analyze_nearby_features(TEXT) TO PUBLIC;
