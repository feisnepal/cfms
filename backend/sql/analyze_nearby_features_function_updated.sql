-- PostgreSQL Function: analyze_nearby_features (Updated Version)
-- Returns all nearby features (within 100m of boundary) organized by direction
-- Distance measured from BOUNDARY, Direction from CENTROID
-- FORMAT: "Feature Name Direction (Azimuth°) Distance km"

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
    v_north_features TEXT[];
    v_east_features TEXT[];
    v_south_features TEXT[];
    v_west_features TEXT[];
    v_feature_name TEXT;
    v_azimuth DOUBLE PRECISION;
    v_distance_km DOUBLE PRECISION;
    v_direction TEXT;
    v_formatted_feature TEXT;
BEGIN
    -- Convert WKT to geometry (assume SRID 4326)
    v_geom := ST_Force2D(ST_GeomFromText(p_geom_wkt, 4326));
    v_centroid := ST_Centroid(v_geom);

    -- Initialize arrays
    v_north_features := ARRAY[]::TEXT[];
    v_east_features := ARRAY[]::TEXT[];
    v_south_features := ARRAY[]::TEXT[];
    v_west_features := ARRAY[]::TEXT[];

    -- 1. Query admin.esa_forest_Boundary (description + " Boundary")
    FOR v_feature_name, v_azimuth, v_distance_km IN
        SELECT DISTINCT
            CONCAT(description, ' Boundary') as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(
                ST_Transform(v_geom, 32645),
                ST_Transform(geom, 32645)
            ) / 1000.0 as distance_km
        FROM admin."esa_forest_Boundary"
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND description IS NOT NULL
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            -- Determine direction
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_direction := 'North';
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_direction := 'East';
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_direction := 'South';
            ELSE
                v_direction := 'West';
            END IF;

            -- Format: "Feature Name Direction (Azimuth°) Distance km"
            v_formatted_feature := format(
                '%s %s (%s°) %s km',
                v_feature_name,
                v_direction,
                ROUND(v_azimuth::NUMERIC, 0),
                ROUND(v_distance_km::NUMERIC, 2)
            );

            -- Append to appropriate direction array
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_formatted_feature);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_formatted_feature);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_formatted_feature);
            ELSE
                v_west_features := array_append(v_west_features, v_formatted_feature);
            END IF;
        END IF;
    END LOOP;

    -- 2. Query admin.settlement (vil_name)
    FOR v_feature_name, v_azimuth, v_distance_km IN
        SELECT DISTINCT
            vil_name as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(shape, v_centroid))) as azimuth,
            ST_Distance(
                ST_Transform(v_geom, 32645),
                ST_Transform(shape, 32645)
            ) / 1000.0 as distance_km
        FROM admin.settlement
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(shape, 32645), 100)
            AND vil_name IS NOT NULL
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_direction := 'North';
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_direction := 'East';
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_direction := 'South';
            ELSE
                v_direction := 'West';
            END IF;

            v_formatted_feature := format(
                '%s %s (%s°) %s km',
                v_feature_name,
                v_direction,
                ROUND(v_azimuth::NUMERIC, 0),
                ROUND(v_distance_km::NUMERIC, 2)
            );

            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_formatted_feature);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_formatted_feature);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_formatted_feature);
            ELSE
                v_west_features := array_append(v_west_features, v_formatted_feature);
            END IF;
        END IF;
    END LOOP;

    -- 3. Query river.river_line (river_name, if null use features)
    FOR v_feature_name, v_azimuth, v_distance_km IN
        SELECT DISTINCT
            COALESCE(river_name, features) as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(
                ST_Transform(v_geom, 32645),
                ST_Transform(geom, 32645)
            ) / 1000.0 as distance_km
        FROM river.river_line
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (river_name IS NOT NULL OR features IS NOT NULL)
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_direction := 'North';
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_direction := 'East';
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_direction := 'South';
            ELSE
                v_direction := 'West';
            END IF;

            v_formatted_feature := format(
                '%s %s (%s°) %s km',
                v_feature_name,
                v_direction,
                ROUND(v_azimuth::NUMERIC, 0),
                ROUND(v_distance_km::NUMERIC, 2)
            );

            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_formatted_feature);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_formatted_feature);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_formatted_feature);
            ELSE
                v_west_features := array_append(v_west_features, v_formatted_feature);
            END IF;
        END IF;
    END LOOP;

    -- 4. Query river.ridge (ridge_name)
    FOR v_feature_name, v_azimuth, v_distance_km IN
        SELECT DISTINCT
            ridge_name as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(
                ST_Transform(v_geom, 32645),
                ST_Transform(geom, 32645)
            ) / 1000.0 as distance_km
        FROM river.ridge
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND ridge_name IS NOT NULL
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_direction := 'North';
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_direction := 'East';
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_direction := 'South';
            ELSE
                v_direction := 'West';
            END IF;

            v_formatted_feature := format(
                '%s %s (%s°) %s km',
                v_feature_name,
                v_direction,
                ROUND(v_azimuth::NUMERIC, 0),
                ROUND(v_distance_km::NUMERIC, 2)
            );

            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_formatted_feature);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_formatted_feature);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_formatted_feature);
            ELSE
                v_west_features := array_append(v_west_features, v_formatted_feature);
            END IF;
        END IF;
    END LOOP;

    -- 5. Query infrastructure.education_facilities (name)
    FOR v_feature_name, v_azimuth, v_distance_km IN
        SELECT DISTINCT
            name as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(
                ST_Transform(v_geom, 32645),
                ST_Transform(geom, 32645)
            ) / 1000.0 as distance_km
        FROM infrastructure.education_facilities
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND name IS NOT NULL
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_direction := 'North';
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_direction := 'East';
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_direction := 'South';
            ELSE
                v_direction := 'West';
            END IF;

            v_formatted_feature := format(
                '%s %s (%s°) %s km',
                v_feature_name,
                v_direction,
                ROUND(v_azimuth::NUMERIC, 0),
                ROUND(v_distance_km::NUMERIC, 2)
            );

            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_formatted_feature);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_formatted_feature);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_formatted_feature);
            ELSE
                v_west_features := array_append(v_west_features, v_formatted_feature);
            END IF;
        END IF;
    END LOOP;

    -- 6. Query infrastructure.health_facilities (concat hf_type + vdc_name1)
    FOR v_feature_name, v_azimuth, v_distance_km IN
        SELECT DISTINCT
            CONCAT(hf_type, ' ', vdc_name1) as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(
                ST_Transform(v_geom, 32645),
                ST_Transform(geom, 32645)
            ) / 1000.0 as distance_km
        FROM infrastructure.health_facilities
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (hf_type IS NOT NULL OR vdc_name1 IS NOT NULL)
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_direction := 'North';
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_direction := 'East';
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_direction := 'South';
            ELSE
                v_direction := 'West';
            END IF;

            v_formatted_feature := format(
                '%s %s (%s°) %s km',
                v_feature_name,
                v_direction,
                ROUND(v_azimuth::NUMERIC, 0),
                ROUND(v_distance_km::NUMERIC, 2)
            );

            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_formatted_feature);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_formatted_feature);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_formatted_feature);
            ELSE
                v_west_features := array_append(v_west_features, v_formatted_feature);
            END IF;
        END IF;
    END LOOP;

    -- 7. Query infrastructure.poi (name, if null name_en, if null name_ne, if null amenity)
    FOR v_feature_name, v_azimuth, v_distance_km IN
        SELECT DISTINCT
            COALESCE(name, name_en, name_ne, amenity) as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(
                ST_Transform(v_geom, 32645),
                ST_Transform(geom, 32645)
            ) / 1000.0 as distance_km
        FROM infrastructure.poi
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND (name IS NOT NULL OR name_en IS NOT NULL OR name_ne IS NOT NULL OR amenity IS NOT NULL)
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_direction := 'North';
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_direction := 'East';
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_direction := 'South';
            ELSE
                v_direction := 'West';
            END IF;

            v_formatted_feature := format(
                '%s %s (%s°) %s km',
                v_feature_name,
                v_direction,
                ROUND(v_azimuth::NUMERIC, 0),
                ROUND(v_distance_km::NUMERIC, 2)
            );

            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_formatted_feature);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_formatted_feature);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_formatted_feature);
            ELSE
                v_west_features := array_append(v_west_features, v_formatted_feature);
            END IF;
        END IF;
    END LOOP;

    -- 8. Query infrastructure.road (name only, skip if null)
    FOR v_feature_name, v_azimuth, v_distance_km IN
        SELECT DISTINCT
            name as name,
            degrees(ST_Azimuth(v_centroid, ST_ClosestPoint(geom, v_centroid))) as azimuth,
            ST_Distance(
                ST_Transform(v_geom, 32645),
                ST_Transform(geom, 32645)
            ) / 1000.0 as distance_km
        FROM infrastructure.road
        WHERE ST_DWithin(ST_Transform(v_geom, 32645), ST_Transform(geom, 32645), 100)
            AND name IS NOT NULL
    LOOP
        IF v_feature_name IS NOT NULL AND v_feature_name != '' THEN
            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_direction := 'North';
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_direction := 'East';
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_direction := 'South';
            ELSE
                v_direction := 'West';
            END IF;

            v_formatted_feature := format(
                '%s %s (%s°) %s km',
                v_feature_name,
                v_direction,
                ROUND(v_azimuth::NUMERIC, 0),
                ROUND(v_distance_km::NUMERIC, 2)
            );

            IF v_azimuth >= 315 OR v_azimuth < 45 THEN
                v_north_features := array_append(v_north_features, v_formatted_feature);
            ELSIF v_azimuth >= 45 AND v_azimuth < 135 THEN
                v_east_features := array_append(v_east_features, v_formatted_feature);
            ELSIF v_azimuth >= 135 AND v_azimuth < 225 THEN
                v_south_features := array_append(v_south_features, v_formatted_feature);
            ELSE
                v_west_features := array_append(v_west_features, v_formatted_feature);
            END IF;
        END IF;
    END LOOP;

    -- Build result JSONB with formatted strings
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
