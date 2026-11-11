-- PostgreSQL Function: analyze_nearby_features
-- Returns all nearby features (within 100m) organized by direction (North, East, South, West)
-- Based on working implementation from E:\CF_application_STABLE_BACKUP_2025-11-30

CREATE OR REPLACE FUNCTION analyze_nearby_features(
    p_geom_wkt TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_geom GEOMETRY;
    v_centroid GEOMETRY;
    v_bbox GEOMETRY;
    v_result JSONB;
    v_north_features TEXT[];
    v_east_features TEXT[];
    v_south_features TEXT[];
    v_west_features TEXT[];
    v_feature_name TEXT;
    v_azimuth DOUBLE PRECISION;
BEGIN
    -- Convert WKT to geometry (assume SRID 4326)
    v_geom := ST_Force2D(ST_GeomFromText(p_geom_wkt, 4326));
    v_centroid := ST_Centroid(v_geom);
    v_bbox := ST_Envelope(v_geom);

    -- Initialize arrays
    v_north_features := ARRAY[]::TEXT[];
    v_east_features := ARRAY[]::TEXT[];
    v_south_features := ARRAY[]::TEXT[];
    v_west_features := ARRAY[]::TEXT[];

    -- Query river lines (river_name, features)
    FOR v_feature_name, v_azimuth IN
        SELECT DISTINCT
            COALESCE(river_name, features) as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth
        FROM river.river_line
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (river_name IS NOT NULL OR features IS NOT NULL)
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_feature_name);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_feature_name);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_feature_name);
            ELSIF v_azimuth >= 225 AND v_azimuth < 315 THEN
                v_west_features := array_append(v_west_features, v_feature_name);
            END IF;
        END IF;
    END LOOP;

    -- Query ridges (ridge_name)
    FOR v_feature_name, v_azimuth IN
        SELECT DISTINCT
            ridge_name as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth
        FROM river.ridge
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND ridge_name IS NOT NULL
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_feature_name);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_feature_name);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_feature_name);
            ELSIF v_azimuth >= 225 AND v_azimuth < 315 THEN
                v_west_features := array_append(v_west_features, v_feature_name);
            END IF;
        END IF;
    END LOOP;

    -- Query roads (name, name_en, highway)
    FOR v_feature_name, v_azimuth IN
        SELECT DISTINCT
            COALESCE(name, name_en, highway) as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth
        FROM infrastructure.road
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (name IS NOT NULL OR name_en IS NOT NULL OR highway IS NOT NULL)
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_feature_name);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_feature_name);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_feature_name);
            ELSIF v_azimuth >= 225 AND v_azimuth < 315 THEN
                v_west_features := array_append(v_west_features, v_feature_name);
            END IF;
        END IF;
    END LOOP;

    -- Query POI (name, name_en, amenity, shop, tourism)
    FOR v_feature_name, v_azimuth IN
        SELECT DISTINCT
            COALESCE(name, name_en, amenity, shop, tourism) as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth
        FROM infrastructure.poi
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (name IS NOT NULL OR name_en IS NOT NULL OR amenity IS NOT NULL OR shop IS NOT NULL OR tourism IS NOT NULL)
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_feature_name);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_feature_name);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_feature_name);
            ELSIF v_azimuth >= 225 AND v_azimuth < 315 THEN
                v_west_features := array_append(v_west_features, v_feature_name);
            END IF;
        END IF;
    END LOOP;

    -- Query health facilities (hf_type, vdc_name1)
    FOR v_feature_name, v_azimuth IN
        SELECT DISTINCT
            COALESCE(hf_type, vdc_name1) as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth
        FROM infrastructure.health_facilities
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (hf_type IS NOT NULL OR vdc_name1 IS NOT NULL)
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_feature_name);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_feature_name);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_feature_name);
            ELSIF v_azimuth >= 225 AND v_azimuth < 315 THEN
                v_west_features := array_append(v_west_features, v_feature_name);
            END IF;
        END IF;
    END LOOP;

    -- Query education facilities (name, name_en, amenity)
    FOR v_feature_name, v_azimuth IN
        SELECT DISTINCT
            COALESCE(name, name_en, amenity) as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth
        FROM infrastructure.education_facilities
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (name IS NOT NULL OR name_en IS NOT NULL OR amenity IS NOT NULL)
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_feature_name);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_feature_name);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_feature_name);
            ELSIF v_azimuth >= 225 AND v_azimuth < 315 THEN
                v_west_features := array_append(v_west_features, v_feature_name);
            END IF;
        END IF;
    END LOOP;

    -- Query buildings (use generic 'Building' label since table has no name column)
    FOR v_feature_name, v_azimuth IN
        SELECT DISTINCT
            'Building' as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(shape, v_centroid))) as azimuth
        FROM buildings.building
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(shape, 32645), 100)
        LIMIT 10  -- Limit buildings to avoid too many results
    LOOP
        IF v_azimuth >= 315 OR v_azimuth < 45 THEN
            v_north_features := array_append(v_north_features, v_feature_name);
        ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
            v_east_features := array_append(v_east_features, v_feature_name);
        ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
            v_south_features := array_append(v_south_features, v_feature_name);
        ELSIF v_azimuth >= 225 AND v_azimuth < 315 THEN
            v_west_features := array_append(v_west_features, v_feature_name);
        END IF;
    END LOOP;

    -- Query settlements (vil_name)
    FOR v_feature_name, v_azimuth IN
        SELECT DISTINCT
            vil_name as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(shape, v_centroid))) as azimuth
        FROM admin.settlement
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(shape, 32645), 100)
            AND vil_name IS NOT NULL
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_feature_name);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_feature_name);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_feature_name);
            ELSIF v_azimuth >= 225 AND v_azimuth < 315 THEN
                v_west_features := array_append(v_west_features, v_feature_name);
            END IF;
        END IF;
    END LOOP;

    -- Query forest boundaries (description, "boundary of")
    FOR v_feature_name, v_azimuth IN
        SELECT DISTINCT
            COALESCE(description, "boundary of") as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth
        FROM admin."esa_forest_Boundary"
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (description IS NOT NULL OR "boundary of" IS NOT NULL)
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_feature_name);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_feature_name);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_feature_name);
            ELSIF v_azimuth >= 225 AND v_azimuth < 315 THEN
                v_west_features := array_append(v_west_features, v_feature_name);
            END IF;
        END IF;
    END LOOP;

    -- Build result JSONB with comma-separated strings (matching current format)
    v_result := jsonb_build_object(
        'features_north', CASE
            WHEN array_length(v_north_features, 1) > 0 THEN
                array_to_string(v_north_features, ', ')
            ELSE NULL
        END,
        'features_east', CASE
            WHEN array_length(v_east_features, 1) > 0 THEN
                array_to_string(v_east_features, ', ')
            ELSE NULL
        END,
        'features_south', CASE
            WHEN array_length(v_south_features, 1) > 0 THEN
                array_to_string(v_south_features, ', ')
            ELSE NULL
        END,
        'features_west', CASE
            WHEN array_length(v_west_features, 1) > 0 THEN
                array_to_string(v_west_features, ', ')
            ELSE NULL
        END
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

-- Test query example:
-- SELECT analyze_nearby_features('POLYGON((85.06166514100008 27.41872503600006,...))');
