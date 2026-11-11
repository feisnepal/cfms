import { describe, expect, it, beforeEach } from 'vitest';
import { buildExportFeatures } from '../layerExportView';
import { parseColour, registerStyleResolvers, symbolFromPathStyle, isProbing } from '../layerSymbology';
import { geojsonToKml } from '../geojsonToKml';
import type { ColumnDef } from '../layerRegistry';

const poly = (props: Record<string, unknown>): GeoJSON.Feature => ({
  type: 'Feature',
  properties: props,
  geometry: { type: 'Polygon', coordinates: [[[85, 27], [85.01, 27], [85.01, 27.01], [85, 27]]] },
});

const COLUMNS: ColumnDef[] = [
  { key: '#', label: '#', width: 40, getValue: (_f, i) => i + 1 },
  { key: 'name', label: 'Name', width: 100 },
  { key: 'area', label: 'Area (ha)', width: 100, getValue: (f) => (f.properties?.area_hectares as number).toFixed(2) },
  { key: 'type', label: 'Type', width: 100, getValue: (f) => f.properties?.type ?? '-' },
  { key: '__actions__', label: '', width: 30 },
];

describe('a layer as the attribute table shows it', () => {
  beforeEach(() => registerStyleResolvers({}));

  it('writes every table column under the heading the table shows, with the table\'s own values', () => {
    const out = buildExportFeatures({
      columns: COLUMNS,
      features: [poly({ name: 'A', area_hectares: 12.5, type: 'Sal' }), poly({ name: 'B', area_hectares: 3, type: '-' })],
      header: (c) => c.label,
      layerKey: 'blocks',
    });
    expect(Object.keys(out[0].properties!)).toEqual(['Name', 'Area (ha)', 'Type']);
    // "12.50" is a number written as text by the table: it becomes a number so QGIS can sort and sum it
    expect(out.map((f) => f.properties!['Area (ha)'])).toEqual([12.5, 3]);
    // the table's "-" for an empty cell is an empty cell
    expect(out[1].properties!.Type).toBeNull();
    expect(out[0]._name).toBe('A');
  });

  it('keeps a text column as text, even when some cells look like numbers', () => {
    const cols: ColumnDef[] = [{ key: 'code', label: 'Code', width: 90 }];
    const out = buildExportFeatures({ columns: cols, features: [poly({ code: '007' }), poly({ code: 'A1' })], header: (c) => c.label, layerKey: 'x' });
    expect(out.map((f) => f.properties!.Code)).toEqual(['007', 'A1']);
  });

  it('two columns with the same heading both survive', () => {
    const cols: ColumnDef[] = [{ key: 'a', label: 'Area', width: 90 }, { key: 'b', label: 'Area', width: 90 }];
    const out = buildExportFeatures({ columns: cols, features: [poly({ a: 'x', b: 'y' })], header: (c) => c.label, layerKey: 'x' });
    expect(out[0].properties).toEqual({ Area: 'x', Area_2: 'y' });
  });

  it('asks the map for each feature\'s look, without the selection highlight', () => {
    let probedWhileAsking = false;
    registerStyleResolvers({
      blocks: (f) => {
        probedWhileAsking = isProbing();
        return { color: '#112233', fillColor: '#ff0000', weight: 2, fillOpacity: 0.4 };
      },
    });
    const out = buildExportFeatures({ columns: COLUMNS, features: [poly({ name: 'A', area_hectares: 1 })], header: (c) => c.label, layerKey: 'blocks' });
    expect(probedWhileAsking).toBe(true);
    expect(isProbing()).toBe(false);
    expect(out[0]._symbol).toMatchObject({ fill: '#ff0000', stroke: '#112233', weight: 2, fillOpacity: 0.4 });
  });
});

describe('colours and path styles', () => {
  it('reads hex, rgb() and rgba() colours', () => {
    expect(parseColour('#abc').hex).toBe('#aabbcc');
    expect(parseColour('rgba(255, 0, 0, 0.5)')).toEqual({ hex: '#ff0000', alpha: 0.5 });
    expect(parseColour('rgb(0,128,0)').hex).toBe('#008000');
    expect(parseColour('nonsense', '#123456').hex).toBe('#123456');
  });

  it('uses Leaflet\'s own defaults for what a style leaves out', () => {
    expect(symbolFromPathStyle({})).toMatchObject({ stroke: '#3388ff', weight: 3, strokeOpacity: 1, fillOpacity: 0.2 });
    expect(symbolFromPathStyle({ fill: false }).fillOpacity).toBe(0);
    expect(symbolFromPathStyle({ stroke: false }).weight).toBe(0);
  });
});

describe('KML carries the look', () => {
  it('writes one shared Style per distinct look and points each placemark at it (colours as aabbggrr)', () => {
    const sym = { fill: '#ff0000', fillOpacity: 0.5, stroke: '#0000ff', strokeOpacity: 1, weight: 2, dashArray: null, radius: 6 };
    const a = { ...poly({ name: 'A' }), _symbol: sym };
    const b = { ...poly({ name: 'B' }), _symbol: sym };
    const c = { ...poly({ name: 'C' }), _symbol: { ...sym, fill: '#00ff00' } };
    const kml = geojsonToKml([a, b, c], 'L');
    expect(kml.match(/<Style id=/g)).toHaveLength(2);
    expect(kml.match(/<styleUrl>#s1<\/styleUrl>/g)).toHaveLength(2);
    expect(kml).toContain('<PolyStyle><color>800000ff</color>');
    expect(kml).toContain('<LineStyle><color>ffff0000</color><width>2</width>');
  });

  it('a feature with no look has no styleUrl, as before', () => {
    expect(geojsonToKml([poly({ name: 'A' })], 'L')).not.toContain('styleUrl');
  });
});

describe('KML fields like the GeoPackage', () => {
  it('writes every table column as a typed field with its value (ExtendedData), besides the description', () => {
    const kml = geojsonToKml([poly({ Name: 'A', 'Area (ha)': 12.5, Trees: 3, Note: null }), poly({ Name: 'B', 'Area (ha)': 3, Trees: 4 })], 'L');
    expect(kml).toContain('<SimpleField name="Area (ha)" type="double"/>');
    expect(kml).toContain('<SimpleField name="Trees" type="int"/>');
    expect(kml).toContain('<SimpleField name="Name" type="string"/>');
    expect(kml).toContain('<SchemaData schemaUrl="#layer_fields"><SimpleData name="Name">A</SimpleData><SimpleData name="Area (ha)">12.5</SimpleData>');
    expect(kml).not.toMatch(/name="Note">/);
    expect(kml).toContain('<description>');
  });
});

describe('choice columns export the label the table shows, not the code', () => {
  it('slope class 1 is "< 19°", not 1', () => {
    const cols: ColumnDef[] = [{
      key: 'dominant_slope_band', label: 'Slope Class', width: 90,
      select: [{ value: '1', label: '< 19°' }, { value: '2', label: '19–31°' }],
      getValue: (f) => (f.properties?.dominant_slope_band != null ? String(f.properties.dominant_slope_band) : ''),
    }];
    const out = buildExportFeatures({ columns: cols, features: [poly({ dominant_slope_band: 1 }), poly({ dominant_slope_band: 2 }), poly({})], header: (c) => c.label, layerKey: 'x' });
    expect(out.map((f) => f.properties!['Slope Class'])).toEqual(['< 19°', '19–31°', null]);
    expect(geojsonToKml(out, 'L')).toContain('&lt; 19°');
  });
});
