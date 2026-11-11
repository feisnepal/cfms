import { afterEach, describe, it, expect, vi } from 'vitest';
import { toBoundaryFeature, kmlToBoundary, parseBoundaryFile, BOUNDARY_PARSE_EXTS } from '../parseBoundaryFile';
import { forestApi } from '../../services/api';
import JSZip from 'jszip';

vi.mock('../../services/api', () => ({
  forestApi: {
    parseBoundaryFileServerSide: vi.fn().mockResolvedValue({
      type: 'Feature' as const,
      geometry: {
        type: 'Polygon' as const,
        coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
      },
      properties: {},
    }),
  },
}));

afterEach(() => {
  vi.clearAllMocks();
});

const polygon = { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };

/** Build a minimal ESRI Polygon (.shp) byte buffer with a single ring. */
function buildTestShapefile(rings: Array<Array<[number, number]>>): Blob {
  const numParts = rings.length;
  const numPoints = rings.reduce((n, r) => n + r.length, 0);
  const contentLen = 4 + 32 + 4 + 4 + 4 * numParts + 16 * numPoints;
  const recordWords = Math.ceil(contentLen / 2);
  const totalBytes = 100 + 8 + contentLen;
  const fileWords = Math.ceil(totalBytes / 2);
  const buf = new ArrayBuffer(totalBytes);
  const dv = new DataView(buf);
  // main header (100 bytes)
  dv.setInt32(0, 9994, false); // file code
  dv.setInt32(24, fileWords, false); // file length (16-bit words)
  dv.setInt32(28, 1000, false); // version
  dv.setInt32(32, 5, false); // shape type = Polygon
  // record header (8 bytes)
  dv.setInt32(100, 1, false); // record number
  dv.setInt32(104, recordWords, false); // content length (16-bit words)
  // record content
  let p = 108;
  dv.setInt32(p, 5, true); p += 4; // shape type = Polygon
  dv.setFloat64(p, 0, true); p += 8; // xmin
  dv.setFloat64(p, 0, true); p += 8; // ymin
  dv.setFloat64(p, 1, true); p += 8; // xmax
  dv.setFloat64(p, 1, true); p += 8; // ymax
  dv.setInt32(p, numParts, true); p += 4;
  dv.setInt32(p, numPoints, true); p += 4;
  let start = 0;
  for (let i = 0; i < numParts; i++) {
    dv.setInt32(p, start, true); p += 4;
    start += rings[i].length;
  }
  for (const ring of rings) {
    for (const [x, y] of ring) {
      dv.setFloat64(p, x, true); p += 8;
      dv.setFloat64(p, y, true); p += 8;
    }
  }
  return new Blob([buf], { type: 'application/octet-stream' });
}

describe('toBoundaryFeature', () => {
  it('accepts a bare Polygon geometry', () => {
    const f = toBoundaryFeature(polygon);
    expect(f.type).toBe('Feature');
    expect(f.geometry.type).toBe('Polygon');
  });

  it('accepts a Feature with a polygon geometry', () => {
    const f = toBoundaryFeature({ type: 'Feature', geometry: polygon, properties: { name: 'x' } });
    expect(f.geometry.type).toBe('Polygon');
  });

  it('picks the first polygon from a FeatureCollection', () => {
    const fc = {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} },
        { type: 'Feature', geometry: polygon, properties: {} },
      ],
    };
    expect(toBoundaryFeature(fc).geometry.type).toBe('Polygon');
  });

  it('rejects non-polygon geometries', () => {
    expect(() => toBoundaryFeature({ type: 'Point', coordinates: [0, 0] })).toThrow();
    expect(() => toBoundaryFeature(null)).toThrow();
  });
});

describe('kmlToBoundary', () => {
  it('extracts the outer ring of a KML polygon', () => {
    const kml = `<?xml version="1.0"?><kml><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>0,0 1,0 1,1 0,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>`;
    const f = kmlToBoundary(kml);
    expect(f.geometry.type).toBe('Polygon');
    expect((f.geometry as any).coordinates[0]).toHaveLength(4);
  });

  it('converts a closed LineString ring into a Polygon (Feature-to-Polygon)', () => {
    const kml = `<?xml version="1.0"?><kml><Placemark><LineString><coordinates>0,0 1,0 1,1 0,1 0,0</coordinates></LineString></Placemark></kml>`;
    const f = kmlToBoundary(kml);
    expect(f.geometry.type).toBe('Polygon');
    const ring = (f.geometry as any).coordinates[0];
    expect(ring[0]).toEqual([0, 0]);
    expect(ring[ring.length - 1]).toEqual([0, 0]);
  });

  it('closes an open LineString trace by appending its first point', () => {
    const kml = `<?xml version="1.0"?><kml><Placemark><LineString><coordinates>0,0 1,0 1,1 0,1</coordinates></LineString></Placemark></kml>`;
    const f = kmlToBoundary(kml);
    expect(f.geometry.type).toBe('Polygon');
    const ring = (f.geometry as any).coordinates[0];
    expect(ring).toHaveLength(5);
    expect(ring[ring.length - 1]).toEqual([0, 0]);
  });

  it('prefers a Polygon over an earlier LineString in the document', () => {
    const kml = `<?xml version="1.0"?><kml><Placemark><LineString><coordinates>0,0 5,5 0,0</coordinates></LineString></Placemark><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>0,0 1,0 1,1 0,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>`;
    const f = kmlToBoundary(kml);
    const ring = (f.geometry as any).coordinates[0];
    expect(ring[1]).toEqual([1, 0]);
  });

  it('throws when the document has no polygon or usable ring', () => {
    expect(() => kmlToBoundary('<kml></kml>')).toThrow();
    expect(() => kmlToBoundary('<kml><Placemark><LineString><coordinates>0,0 1,1</coordinates></LineString></Placemark></kml>')).toThrow();
  });
});

describe('parseBoundaryFile (purpose-first boundary import)', () => {
  it('parses a valid GeoJSON file', async () => {
    const file = new File([JSON.stringify(polygon)], 'b.geojson', { type: 'application/geo+json' });
    const f = await parseBoundaryFile(file);
    expect(f.geometry.type).toBe('Polygon');
  });

  it('parses a KMZ archive by unzipping its KML document', async () => {
    const kml = `<?xml version="1.0"?><kml><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>0,0 1,0 1,1 0,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>`;
    const zip = new JSZip();
    zip.file('doc.kml', kml);
    const buf = await zip.generateAsync({ type: 'blob' });
    const file = new File([buf], 'b.kmz', { type: 'application/vnd.google-earth.kmz' });
    const f = await parseBoundaryFile(file);
    expect(f.geometry.type).toBe('Polygon');
  });

  it('parses an ESRI Shapefile (.shp) polygon boundary', async () => {
    const shp = buildTestShapefile([
      [[0, 0], [1, 0], [1, 1], [0, 0]],
    ]);
    const file = new File([shp], 'b.shp', { type: 'application/octet-stream' });
    const f = await parseBoundaryFile(file);
    expect(f.geometry.type).toBe('Polygon');
    const ring = (f.geometry as any).coordinates[0];
    expect(ring.length).toBeGreaterThanOrEqual(4);
  });

  it('parses a zipped ESRI Shapefile (.zip) boundary', async () => {
    const shp = buildTestShapefile([
      [[0, 0], [1, 0], [1, 1], [0, 0]],
    ]);
    const zip = new JSZip();
    zip.file('boundary.shp', shp);
    const buf = await zip.generateAsync({ type: 'blob' });
    const file = new File([buf], 'sundar.zip', { type: 'application/zip' });
    const f = await parseBoundaryFile(file);
    expect(f.geometry.type).toBe('Polygon');
  });

  it('parses a multi-island shapefile into a MultiPolygon with one part per island', async () => {
    // Two disjoint islands (squared-off, CCW winding).
    const islandA = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]] as [number, number][];
    const islandB = [[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]] as [number, number][];
    const shp = buildTestShapefile([islandA, islandB]);
    const file = new File([shp], 'islands.shp', { type: 'application/octet-stream' });
    const f = await parseBoundaryFile(file);
    expect(f.geometry.type).toBe('MultiPolygon');
    expect((f.geometry as any).coordinates).toHaveLength(2);
  });

  it('dissolves split fragments of one island into a single polygon part', async () => {
    // Two adjacent squares sharing an edge → must merge into one island.
    const frag1 = [[0, 0], [0.5, 0], [0.5, 1], [0, 1], [0, 0]] as [number, number][];
    const frag2 = [[0.5, 0], [1, 0], [1, 1], [0.5, 1], [0.5, 0]] as [number, number][];
    const shp = buildTestShapefile([frag1, frag2]);
    const file = new File([shp], 'split.shp', { type: 'application/octet-stream' });
    const f = await parseBoundaryFile(file);
    // Adjacent fragments that overlap along a shared edge union into one island.
    const nParts =
      f.geometry.type === 'MultiPolygon'
        ? (f.geometry as any).coordinates.length
        : 1;
    expect(nParts).toBe(1);
  });

  it('attaches holes to their containing island in a shapefile', async () => {
    // One record: outer shell (CCW) + inner hole (CW).
    const shell = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]] as [number, number][];
    const hole = [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]] as [number, number][]; // clockwise
    const shp = buildTestShapefile([shell, hole]);
    const file = new File([shp], 'island_hole.shp', { type: 'application/octet-stream' });
    const f = await parseBoundaryFile(file);
    expect(f.geometry.type).toBe('Polygon');
    // one shell ring + one hole ring.
    expect((f.geometry as any).coordinates).toHaveLength(2);
  });

  it('accepts an ESRI-convention shapefile whose outer rings are clockwise', async () => {
    // The ESRI Shapefile spec stores shells clockwise (e.g. sundar.zip). The
    // classifier must not require CCW winding for a single-ring record.
    const cwRing = [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]] as [number, number][];
    const shp = buildTestShapefile([cwRing]);
    const file = new File([shp], 'sundar.shp', { type: 'application/octet-stream' });
    const f = await parseBoundaryFile(file);
    expect(f.geometry.type).toBe('Polygon');
    expect((f.geometry as any).coordinates).toHaveLength(1);
  });

  it('handles an ESRI-convention record with a clockwise shell and CCW hole', async () => {
    const shell = [[0, 0], [0, 4], [4, 4], [4, 0], [0, 0]] as [number, number][]; // CW
    const hole = [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]] as [number, number][]; // CCW
    const shp = buildTestShapefile([shell, hole]);
    const file = new File([shp], 'sundar_hole.shp', { type: 'application/octet-stream' });
    const f = await parseBoundaryFile(file);
    expect(f.geometry.type).toBe('Polygon');
    expect((f.geometry as any).coordinates).toHaveLength(2);
  });

  it('rejects a bogus .shp file with a shapefile error', async () => {
    const file = new File(['nonsense'], 'b.shp', { type: 'application/octet-stream' });
    await expect(parseBoundaryFile(file)).rejects.toThrow(/\.shp/);
  });

  it('rejects an unsupported format with a clear message', async () => {
    const file = new File(['nonsense'], 'b.docx', { type: 'application/octet-stream' });
    expect(() => parseBoundaryFile(file)).toThrow(/supports/);
  });

  it('throws Invalid GeoJSON for non-JSON content with a supported extension', async () => {
    const file = new File(['not json'], 'b.geojson', { type: 'application/geo+json' });
    await expect(parseBoundaryFile(file)).rejects.toThrow(/Invalid GeoJSON/);
  });

  it('lists .gpkg as a supported boundary format', () => {
    expect(BOUNDARY_PARSE_EXTS.has('gpkg')).toBe(true);
  });

  it('parses a GeoPackage by uploading it to the backend parser', async () => {
    const file = new File(['fake-gpkg-bytes'], 'b.gpkg', { type: 'application/geopackage+sqlite3' });
    const f = await parseBoundaryFile(file);
    expect(f.type).toBe('Feature');
    expect(f.geometry.type).toBe('Polygon');
    expect(forestApi.parseBoundaryFileServerSide).toHaveBeenCalledTimes(1);
    expect(forestApi.parseBoundaryFileServerSide).toHaveBeenCalledWith(file);
  });

  it('propagates a backend parse failure for a corrupt .gpkg', async () => {
    vi.mocked(forestApi.parseBoundaryFileServerSide).mockRejectedValueOnce(new Error('Could not read the boundary file'));
    const file = new File(['not really a geopackage'], 'bad.gpkg', { type: 'application/geopackage+sqlite3' });
    await expect(parseBoundaryFile(file)).rejects.toThrow(/Could not read the boundary file/);
  });
});
