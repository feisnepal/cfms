/**
 * parseBoundaryFile.ts — parsing of a boundary file picked in the workspace-based
 * create flow. Supported: GeoJSON (.geojson/.json), KML (.kml) and KMZ (.kmz,
 * unzipped → KML), ESRI Shapefile (.shp/.zip), and GeoPackage (.gpkg, handled
 * server-side because a browser cannot decode SQLite). Each file is reduced to a
 * single boundary **Feature** (Polygon or MultiPolygon). For multi-island
 * shapefiles (e.g. Japan) every outer ring / island is preserved: split
 * fragments within an island are dissolved into one Polygon part, and each
 * island becomes a separate part of the resulting MultiPolygon so the downstream
 * auto-block service can build one block per island.
 */
import type { Feature, Geometry, MultiPolygon, Polygon, Position } from 'geojson';
import * as turf from '@turf/turf';
import JSZip from 'jszip';

type P = Feature<Polygon | MultiPolygon>;

/** Formats that can be parsed into a boundary polygon (client-side or via API). */
export const BOUNDARY_PARSE_EXTS = new Set(['geojson', 'json', 'kml', 'kmz', 'shp', 'zip', 'gpkg']);

export function parseBoundaryFile(file: File): Promise<Feature> {
  const ext = file.name.split('.').pop()?.toLowerCase();
  if (!ext || !BOUNDARY_PARSE_EXTS.has(ext)) {
    throw new Error(
      `Forest-boundary import supports GeoJSON (.geojson/.json), KML (.kml/.kmz), ESRI Shapefile (.shp/.zip) and GeoPackage (.gpkg) — got "${file.name}".`,
    );
  }
  if (ext === 'shp') return parseShapefile(file);
  if (ext === 'zip') return parseShapefileZip(file);
  if (ext === 'kmz') return parseKmz(file);
  if (ext === 'gpkg') return parseGpkg(file);
  return file.text().then((text) => {
    if (ext === 'kml') return kmlToBoundary(text);
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new Error('Invalid GeoJSON: could not parse file contents');
    }
    return toBoundaryFeature(parsed);
  });
}

/**
 * GeoPackage is SQLite, which browsers cannot parse, so the file is uploaded to
 * the backend `POST /forests/boundary/parse-file` endpoint. The backend runs the
 * same Feature-to-Polygon pipeline as the workspace import and returns a single
 * Polygon/MultiPolygon boundary Feature in EPSG:4326.
 */
async function parseGpkg(file: File): Promise<Feature> {
  const { forestApi } = await import('../services/api');
  return forestApi.parseBoundaryFileServerSide(file);
}

// ── ESRI Shapefile (.shp) binary parsing ────────────────────────────────────
// Minimal reader for the polygon boundary case. Supports Polygon (5) and
// MultiPoint (8) geometries; only the first polygon is used as the boundary.
// Coordinates are little-endian doubles in the file's CRS (assumed lon/lat).

interface ShapeRecord {
  shapeType: number;
  rings?: Array<Array<[number, number]>>;
  points?: Array<[number, number]>;
}

async function readShapefileShp(shp: File): Promise<ShapeRecord[]> {
  const buf = await shp.arrayBuffer();
  const dv = new DataView(buf);
  if (dv.byteLength < 100) throw new Error('Invalid .shp file: too short');
  // Header: file code int32 must be 9994.
  if (dv.getInt32(0, false) !== 9994) {
    throw new Error('Invalid .shp file: bad file code');
  }
  const fileLengthWords = dv.getInt32(24, false);
  const fileLengthBytes = Math.min(dv.byteLength, fileLengthWords * 2);

  const records: ShapeRecord[] = [];
  let offset = 100;
  while (offset < fileLengthBytes) {
    // each record: 8-byte header (recNum int32, contentLength int32) then content
    const contentLength = dv.getInt32(offset + 4, false);
    const contentStart = offset + 8;
    const contentEnd = contentStart + contentLength * 2;
    if (contentEnd > dv.byteLength) break;
    const shapeType = dv.getInt32(contentStart, true);
    if (shapeType === 0) {
      shapeType; // null shape — skip
    } else if (shapeType === 5 || shapeType === 15) {
      // Polygon / PolygonZ: box(4*8) then numParts, numPoints, parts[], points[]
      let p = contentStart + 32 + 4;
      const numParts = dv.getInt32(p, true); p += 4;
      const numPoints = dv.getInt32(p, true); p += 4;
      const parts: number[] = [];
      for (let i = 0; i < numParts; i++) { parts.push(dv.getInt32(p, true)); p += 4; }
      const pts: Array<[number, number]> = [];
      for (let i = 0; i < numPoints; i++) {
        pts.push([dv.getFloat64(p, true), dv.getFloat64(p + 8, true)]);
        p += 16;
      }
      // rebuild rings from part start indices
      const rings: Array<Array<[number, number]>> = [];
      for (let i = 0; i < numParts; i++) {
        const start = parts[i];
        const end = i + 1 < numParts ? parts[i + 1] : numPoints;
        rings.push(pts.slice(start, end));
      }
      records.push({ shapeType, rings });
    } else if (shapeType === 8) {
      // MultiPoint
      let p = contentStart + 32 + 4;
      const numPoints = dv.getInt32(p, true); p += 4;
      const pts: Array<[number, number]> = [];
      for (let i = 0; i < numPoints; i++) {
        pts.push([dv.getFloat64(p, true), dv.getFloat64(p + 8, true)]);
        p += 16;
      }
      records.push({ shapeType, points: pts });
    }
    offset = contentEnd;
    if (contentLength <= 0) break;
  }

  if (records.length === 0) {
    throw new Error('No polygon features found in the .shp file');
  }
  return records;
}

/**
 * Merge all polygon records/into a single boundary Feature.
 * Each record's rings are classified by geometry (not winding — the ESRI spec
 * stores shells clockwise and holes counter-clockwise, while most OGC/GIS
 * exports do the reverse, so winding is not a reliable discriminator):
 *   - a single-ring record is by definition the outer ring;
 *   - in a multi-ring record the ring with the largest |area| is the shell,
 *     other rings are holes when inside the shell, else separate islands.
 * All outer rings become candidate islands; adjacent/split fragments sharing
 * an edge are dissolved via turf union so each resulting island is one
 * Polygon. Holes belonging to an outer ring are attached as inner rings. When
 * more than one island survives, they are emitted as the parts of a single
 * MultiPolygon Feature (single boundary feature contract).
 */
function shapeRecordsToBoundary(records: ShapeRecord[]): Feature {
  const polys = records.filter((r) => (r.rings?.length ?? 0) > 0);
  if (polys.length === 0) {
    const mp = records.find((r) => (r.points?.length ?? 0) > 0);
    if (mp?.points?.length) {
      return {
        type: 'Feature',
        geometry: { type: 'MultiPoint', coordinates: mp.points },
        properties: {},
      };
    }
    throw new Error('No polygon feature found in the shapefile');
  }

  const outer: Position[][] = [];
  const holes: Position[][] = [];
  for (const rec of polys) {
    const rings = rec.rings!;
    if (rings.length === 1) {
      // A single-ring record cannot be a hole — treat it as the outer ring
      // regardless of winding (accepts both ESRI and OGC conventions).
      const closed = toClosedRing(rings[0]);
      if (closed.length >= 4) outer.push(closed);
    } else {
      // Largest-|area| ring is the shell; smaller rings are holes when their
      // centroid sits inside the shell, otherwise they are separate islands.
      const measured = rings
        .map((r) => {
          const closed = toClosedRing(r);
          const pts = closed.map((p) => [p[0], p[1]] as [number, number]);
          return { closed, area: Math.abs(ringAreaSigned(pts)) };
        })
        .sort((a, b) => b.area - a.area);
      const shell = measured[0].closed;
      if (shell.length < 4) continue;
      outer.push(shell);
      const shellPoly = turf.polygon([shell], {});
      for (let i = 1; i < measured.length; i++) {
        const ring = measured[i].closed;
        if (ring.length < 4) continue;
        const centroid = turf.centroid(turf.polygon([ring], {}));
        if (turf.booleanPointInPolygon(centroid, shellPoly)) holes.push(ring);
        else outer.push(ring);
      }
    }
  }
  if (outer.length === 0) {
    throw new Error('Shapefile polygon outer rings have too few points');
  }

  const islands = attachHoles(unionOuterRings(outer), holes);

  let geom: Geometry;
  if (islands.length === 1) {
    geom = islands[0].geometry as Geometry;
  } else {
    const multipoly: MultiPolygon = {
      type: 'MultiPolygon',
      coordinates: islands.map((p) => (p.geometry as any).coordinates),
    };
    geom = multipoly;
  }
  return {
    type: 'Feature',
    geometry: geom,
    properties: {},
  };
}

/** Ensure a ring is closed (first === last point). */
function toClosedRing(ring: Array<[number, number]>): Position[] {
  const pts: Position[] = ring.map(([x, y]) => [x, y] as Position);
  if (pts.length < 2) return pts;
  const first = pts[0];
  const last = pts[pts.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) pts.push(first);
  return pts;
}

/**
 * Union outer rings that touch or overlap so each disjoint island is one Polygon.
 * Returns an array of Polygon features (one per island). Uses turf v7's
 * FeatureCollection-union which merges all touching/overlapping members.
 */
function unionOuterRings(rings: Position[][]): P[] {
  if (rings.length === 0) return [];
  const feats: P[] = rings.map((r) => turf.polygon([r], {}) as P);
  if (feats.length === 1) return [feats[0]];
  const fc = turf.featureCollection(feats);
let u: Feature<Polygon | MultiPolygon> | null;
  try {
    u = turf.union(fc);
  } catch {
    return feats; // disjoint or invalid → leave as separate islands.
  }
  if (!u || !u.geometry) return feats;
  if (u.geometry.type === 'Polygon') return [u as P];
  if (u.geometry.type === 'MultiPolygon') {
    return (u.geometry.coordinates as any[]).map((coords) =>
      turf.polygon(coords as any, {}) as P,
    );
  }
  // union collapsed everything into a single Polygon/MultiPolygon.
  return [u as P];
}

/** Attach each hole to the island polygon that geometrically contains it. */
function attachHoles(
  islands: P[],
  holes: Position[][],
): P[] {
  const result: P[] = islands.map((p) =>
    turf.polygon(p.geometry!.coordinates as any, {}) as P,
  );
  for (const hole of holes) {
    const holePoly = turf.polygon([hole], {});
    const c = turf.centroid(holePoly);
    for (let i = 0; i < result.length; i++) {
      if (turf.booleanPointInPolygon(c, result[i])) {
        const coords = (result[i].geometry.coordinates as any[]).slice();
        coords.push(hole as any);
        result[i] = turf.polygon(coords, {});
        break;
      }
    }
  }
  return result;
}

function ringAreaSigned(ring: Array<[number, number]>): number {
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x0, y0] = ring[i];
    const [x1, y1] = ring[(i + 1) % ring.length];
    sum += x0 * y1 - x1 * y0;
  }
  return sum / 2;
}

async function parseShapefileZip(zipFile: File): Promise<Feature> {
  const entries = await JSZip.loadAsync(await zipFile.arrayBuffer());
  const shpName = Object.keys(entries.files).find((n) =>
    !entries.files[n].dir && n.toLowerCase().endsWith('.shp'),
  );
  if (!shpName) throw new Error('No .shp found inside the ZIP archive');
  const shpBlob = await entries.file(shpName)!.async('blob');
  const shpFile = new File([shpBlob], shpName, { type: 'application/octet-stream' });
  const records = await readShapefileShp(shpFile);
  return shapeRecordsToBoundary(records);
}

async function parseShapefile(shpFile: File): Promise<Feature> {
  const records = await readShapefileShp(shpFile);
  return shapeRecordsToBoundary(records);
}

/** Unzip a KMZ archive and parse its KML document into a boundary feature. */
async function parseKmz(file: File): Promise<Feature> {
  const zip = await JSZip.loadAsync(await file.arrayBuffer());
  const kmlEntry = Object.keys(zip.files).find((name) =>
    !zip.files[name].dir && name.toLowerCase().endsWith('.kml'),
  );
  if (!kmlEntry) {
    throw new Error('No KML document found inside the KMZ archive');
  }
  const text = await zip.file(kmlEntry)!.async('string');
  return kmlToBoundary(text);
}

/** Coerce any GeoJSON value into a single polygon boundary feature. */
export function toBoundaryFeature(data: unknown): Feature {
  if (!data || typeof data !== 'object') {
    throw new Error('No boundary found in the file');
  }
  const obj = data as { type?: string; geometry?: Geometry; features?: unknown[] };
  if (obj.type === 'Feature' && obj.geometry) {
    const geometry = obj.geometry;
    if (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') {
      return { type: 'Feature', geometry, properties: {} };
    }
    throw new Error('The file must contain a Polygon or MultiPolygon boundary');
  }
  if (obj.type === 'FeatureCollection' && Array.isArray(obj.features)) {
    for (const f of obj.features) {
      try {
        return toBoundaryFeature(f);
      } catch {
        /* keep scanning for a polygon feature */
      }
    }
    throw new Error('No Polygon boundary found in the FeatureCollection');
  }
  if (obj.type === 'Polygon' || obj.type === 'MultiPolygon') {
    return { type: 'Feature', geometry: obj as Geometry, properties: {} };
  }
  throw new Error('Unsupported GeoJSON type — expected a Polygon boundary');
}

/**
 * Extract a boundary Polygon from a KML document, Feature-to-Polygon style.
 *
 * Search order across ALL Placemarks (not just the first):
 *   1. a `<Polygon>` ring (explicit polygon, preserved as-is);
 *   2. a closed `<LineString>` ring (first === last coordinate, like ArcGIS
 *      "Feature to Polygon" accepts) — converted to a Polygon directly;
 *   3. an open `<LineString>` with ≥ 4 coordinates — closed by appending its
 *      first point (a traced-out ridge line, Google-Earth "path" style).
 * Only the first matching ring is used and becomes the boundary's outer ring.
 */
export function kmlToBoundary(text: string): Feature {
  const doc = new DOMParser().parseFromString(text, 'text/xml');
  const placemarks = Array.from(doc.getElementsByTagName('Placemark'));

  let preferredRing: Position[] | null = null;
  for (const placemark of placemarks) {
    const polygon = placemark.getElementsByTagName('Polygon')[0];
    const coordsText = polygon
      ? polygon.getElementsByTagName('coordinates')[0]?.textContent?.trim()
      : placemark.getElementsByTagName('LineString')[0]?.getElementsByTagName('coordinates')[0]?.textContent?.trim();
    if (!coordsText) continue;

    const ring: Position[] = coordsText
      .split(/\s+/)
      .filter(Boolean)
      .map((c) => {
        const [lng, lat] = c.split(',').map(Number);
        if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
          throw new Error('Invalid coordinate in KML file');
        }
        return [lng, lat];
      });
    if (ring.length < 4) continue;

    if (polygon) {
      preferredRing = ring;
      break;
    }
    if (!preferredRing) {
      preferredRing = ring;
    }
  }

  if (!preferredRing) {
    throw new Error('No polygon found in the KML file');
  }
  let ring = preferredRing;
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) {
    ring = [...ring, first];
  }
  if (ring.length < 4) {
    throw new Error('KML polygon needs at least 4 coordinates');
  }
  return {
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [ring] },
    properties: {},
  };
}
