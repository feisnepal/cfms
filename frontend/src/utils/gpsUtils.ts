/**
 * GPS utility functions — coordinate transformation and CSV parsing.
 *
 * Parses GPS point data from CSV files (via PapaParse), reprojects
 * coordinates between EPSG codes (via proj4), and converts between
 * degrees/minutes/seconds and decimal degrees.
 */
import Papa from 'papaparse';
import proj4 from 'proj4';

proj4.defs([
  ['EPSG:4326', '+proj=longlat +datum=WGS84 +no_defs'],
  ['EPSG:32644', '+proj=utm +zone=44 +datum=WGS84 +units=m +no_defs'], // UTM Zone 44N
  ['EPSG:32645', '+proj=utm +zone=45 +datum=WGS84 +units=m +no_defs'], // UTM Zone 45N
]);

export interface GPSPoint {
  id: string;
  latitude: number;
  longitude: number;
  name?: string;
  elevation?: number;
  order?: number;
}

export interface CoordinateTransformOptions {
  fromEPSG: string;
  toEPSG?: string; // defaults to EPSG:4326
}

/**
 * Parse CSV file containing GPS coordinates
 * Expected columns: latitude, longitude, name (optional), elevation (optional)
 */
export const parseCSVCoordinates = (
  file: File
): Promise<GPSPoint[]> => {
  return new Promise((resolve, reject) => {
    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
        try {
          const points: GPSPoint[] = results.data.map((row: any, index: number) => {
            // Try different column name variations
            const lat = parseFloat(
              row.latitude || row.lat || row.Latitude || row.LAT || row.y || row.Y
            );
            const lon = parseFloat(
              row.longitude || row.lon || row.lng || row.Longitude || row.LON || row.x || row.X
            );

            if (isNaN(lat) || isNaN(lon)) {
              throw new Error(`Invalid coordinates in row ${index + 1}: lat=${lat}, lon=${lon}`);
            }

            return {
              id: `gps-${index}`,
              latitude: lat,
              longitude: lon,
              name: row.name || row.Name || row.point_name || `Point ${index + 1}`,
              elevation: row.elevation || row.elev || row.alt || row.altitude ?
                parseFloat(row.elevation || row.elev || row.alt || row.altitude) : undefined,
              order: index,
            };
          });

          resolve(points);
        } catch (error) {
          reject(error);
        }
      },
      error: (error) => {
        reject(new Error(`CSV parsing error: ${error.message}`));
      },
    });
  });
};

/**
 * Parse pasted coordinates from text
 * Supports formats:
 * - "lat, lon" (one per line)
 * - "lat lon" (space-separated)
 * - "lon, lat" (if lon is negative or > 90)
 */
export const parsePastedCoordinates = (text: string): GPSPoint[] => {
  const lines = text.split('\n').filter(line => line.trim());
  const points: GPSPoint[] = [];

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return;

    // Split by comma or whitespace
    const parts = trimmed.split(/[,\s]+/).map(p => parseFloat(p.trim()));

    if (parts.length < 2) {
      throw new Error(`Invalid format in line ${index + 1}: "${line}"`);
    }

    let lat = parts[0];
    let lon = parts[1];

    // Auto-detect if coordinates are swapped (lon, lat instead of lat, lon)
    // If first number is > 90 or < -90, it's likely longitude
    if (Math.abs(lat) > 90 && Math.abs(lon) <= 90) {
      [lat, lon] = [lon, lat]; // swap
    }

    if (isNaN(lat) || isNaN(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      throw new Error(`Invalid coordinates in line ${index + 1}: lat=${lat}, lon=${lon}`);
    }

    points.push({
      id: `pasted-${index}`,
      latitude: lat,
      longitude: lon,
      name: `Point ${index + 1}`,
      order: index,
    });
  });

  return points;
};

/**
 * Parse GPX file (GPS exchange format)
 */
export const parseGPXFile = (file: File): Promise<GPSPoint[]> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = (e) => {
      const xmlText = e.target?.result as string;

      try {
        const parser = new DOMParser();
        const doc = parser.parseFromString(xmlText, 'text/xml');

        const parseError = doc.querySelector('parsererror');
        if (parseError) {
          reject(new Error(`GPX parsing error: ${parseError.textContent}`));
          return;
        }

        const points: GPSPoint[] = [];

        // Parse waypoints (wpt)
        const waypoints = doc.querySelectorAll('wpt');
        waypoints.forEach((wpt, index) => {
          points.push({
            id: `gpx-wpt-${index}`,
            latitude: parseFloat(wpt.getAttribute('lat')!),
            longitude: parseFloat(wpt.getAttribute('lon')!),
            name: wpt.querySelector('name')?.textContent || `Waypoint ${index + 1}`,
            elevation: wpt.querySelector('ele')?.textContent
              ? parseFloat(wpt.querySelector('ele')!.textContent!)
              : undefined,
            order: index,
          });
        });

        // Parse track points (trkpt)
        const trackpoints = doc.querySelectorAll('trkpt');
        trackpoints.forEach((trkpt, index) => {
          points.push({
            id: `gpx-trk-${index}`,
            latitude: parseFloat(trkpt.getAttribute('lat')!),
            longitude: parseFloat(trkpt.getAttribute('lon')!),
            name: `Track Point ${index + 1}`,
            elevation: trkpt.querySelector('ele')?.textContent
              ? parseFloat(trkpt.querySelector('ele')!.textContent!)
              : undefined,
            order: points.length + index,
          });
        });

        // Parse route points (rtept)
        const routepoints = doc.querySelectorAll('rtept');
        routepoints.forEach((rtept, index) => {
          points.push({
            id: `gpx-rte-${index}`,
            latitude: parseFloat(rtept.getAttribute('lat')!),
            longitude: parseFloat(rtept.getAttribute('lon')!),
            name: rtept.querySelector('name')?.textContent || `Route Point ${index + 1}`,
            elevation: rtept.querySelector('ele')?.textContent
              ? parseFloat(rtept.querySelector('ele')!.textContent!)
              : undefined,
            order: points.length + index,
          });
        });

        if (points.length === 0) {
          reject(new Error('No GPS points found in GPX file'));
          return;
        }

        resolve(points);
      } catch (error) {
        reject(new Error(`Error parsing GPX data: ${error}`));
      }
    };

    reader.onerror = () => {
      reject(new Error('Failed to read GPX file'));
    };

    reader.readAsText(file);
  });
};

/**
 * Transform coordinates from one EPSG code to another
 */
export const transformCoordinates = (
  points: GPSPoint[],
  options: CoordinateTransformOptions
): GPSPoint[] => {
  const { fromEPSG, toEPSG = 'EPSG:4326' } = options;

  // If already in target projection, return as-is
  if (fromEPSG === toEPSG) {
    return points;
  }

  try {
    return points.map(point => {
      // For UTM, input is (easting, northing) i.e., (x, y) i.e., (lon, lat)
      // For WGS84, input is (longitude, latitude) i.e., (lon, lat)
      const inputCoords = fromEPSG.includes('326')
        ? [point.longitude, point.latitude]  // UTM: treat as easting, northing
        : [point.longitude, point.latitude]; // WGS84: lon, lat

      const [lon, lat] = proj4(fromEPSG, toEPSG, inputCoords);

      return {
        ...point,
        latitude: lat,
        longitude: lon,
      };
    });
  } catch (error) {
    throw new Error(`Coordinate transformation failed: ${error}`);
  }
};

/**
 * Validate GPS point coordinates
 */
export const validateGPSPoint = (point: GPSPoint): { valid: boolean; error?: string } => {
  // Check latitude range (-90 to 90)
  if (point.latitude < -90 || point.latitude > 90) {
    return { valid: false, error: `Invalid latitude: ${point.latitude} (must be between -90 and 90)` };
  }

  // Check longitude range (-180 to 180)
  if (point.longitude < -180 || point.longitude > 180) {
    return { valid: false, error: `Invalid longitude: ${point.longitude} (must be between -180 and 180)` };
  }

  // Check if coordinates are not zero (common error)
  if (point.latitude === 0 && point.longitude === 0) {
    return { valid: false, error: 'Coordinates cannot be (0, 0)' };
  }

  return { valid: true };
};

/**
 * Convert GPS points to GeoJSON Point features
 */
export const gpsPointsToGeoJSON = (points: GPSPoint[]) => {
  return {
    type: 'FeatureCollection',
    features: points.map(point => ({
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: [point.longitude, point.latitude],
      },
      properties: {
        id: point.id,
        name: point.name,
        elevation: point.elevation,
        order: point.order,
      },
    })),
  };
};

/**
 * Convert GPS points to polygon by connecting them in order
 */
export const gpsPointsToPolygon = (points: GPSPoint[]) => {
  if (points.length < 3) {
    throw new Error('At least 3 points are required to create a polygon');
  }

  // Sort by order
  const sorted = [...points].sort((a, b) => (a.order || 0) - (b.order || 0));

  // Create coordinate array
  const coordinates = sorted.map(p => [p.longitude, p.latitude]);

  // Close the polygon (first point = last point)
  if (
    coordinates[0][0] !== coordinates[coordinates.length - 1][0] ||
    coordinates[0][1] !== coordinates[coordinates.length - 1][1]
  ) {
    coordinates.push(coordinates[0]);
  }

  return {
    type: 'Feature',
    geometry: {
      type: 'Polygon',
      coordinates: [coordinates],
    },
    properties: {
      created_from: 'gps_points',
      point_count: points.length,
    },
  };
};

/**
 * Detect likely EPSG code based on coordinate ranges
 * Nepal is roughly between:
 * - Latitude: 26-31°N
 * - Longitude: 80-89°E
 * - UTM Zone 44N: ~200,000-900,000 easting, ~2,800,000-3,500,000 northing
 * - UTM Zone 45N: ~200,000-900,000 easting, ~2,800,000-3,500,000 northing
 */
export const detectEPSG = (points: GPSPoint[]): string => {
  if (points.length === 0) return 'EPSG:4326';

  const firstPoint = points[0];
  const lat = firstPoint.latitude;
  const lon = firstPoint.longitude;

  // Check if it's WGS84 (lat/lon in degrees)
  if (lat >= 26 && lat <= 31 && lon >= 80 && lon <= 89) {
    return 'EPSG:4326';
  }

  // Check if it's UTM (very large numbers)
  if (lat > 1000000 && lon > 100000 && lon < 1000000) {
    // Likely UTM - easting is lon, northing is lat
    // Zone 44 covers 81-87°E, Zone 45 covers 87-93°E
    // Estimate zone based on easting
    if (lon < 500000) {
      return 'EPSG:32644'; // UTM Zone 44N
    } else {
      return 'EPSG:32645'; // UTM Zone 45N
    }
  }

  // Default to WGS84
  return 'EPSG:4326';
};
