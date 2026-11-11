import type { GeoJSON } from 'geojson';
import type { FeatureSymbol } from './layerSymbology';

/** A feature that carries its own look (`_symbol`) and the name to show (`_name`), as the layer export builds them. */
type ExportFeature = GeoJSON.Feature & { _symbol?: FeatureSymbol; _name?: string };

/** KML writes colour as aabbggrr. */
function kmlColour(hex: string, opacity: number): string {
  const h = hex.replace('#', '').padEnd(6, '0');
  const a = Math.max(0, Math.min(255, Math.round(opacity * 255))).toString(16).padStart(2, '0');
  return `${a}${h.slice(4, 6)}${h.slice(2, 4)}${h.slice(0, 2)}`;
}

function styleBody(sym: FeatureSymbol): string {
  const line = `<LineStyle><color>${kmlColour(sym.stroke, sym.strokeOpacity)}</color><width>${Math.max(0, sym.weight)}</width></LineStyle>`;
  const poly = `<PolyStyle><color>${kmlColour(sym.fill, sym.fillOpacity)}</color><fill>${sym.fillOpacity > 0 ? 1 : 0}</fill><outline>${sym.strokeOpacity > 0 && sym.weight > 0 ? 1 : 0}</outline></PolyStyle>`;
  const icon = `<IconStyle><color>${kmlColour(sym.fill, Math.max(sym.fillOpacity, 0.6))}</color><scale>${Math.max(0.4, sym.radius / 8).toFixed(2)}</scale><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle>`;
  return `${icon}${line}${poly}`;
}

function escapeXml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function coordStr(pos: GeoJSON.Position): string {
  return `${pos[0]},${pos[1]}${pos[2] != null ? `,${pos[2]}` : ''}`;
}

function coordinatesBlock(positions: GeoJSON.Position[]): string {
  return positions.map(coordStr).join(' ');
}

function buildMulti(parts: string[]): string {
  if (parts.length === 0) return '';
  return `<MultiGeometry>${parts.join('')}</MultiGeometry>`;
}

function buildPolygon(rings: GeoJSON.Position[][]): string {
  const outer = rings[0] || [];
  let kml = `<Polygon><outerBoundaryIs><LinearRing><coordinates>${coordinatesBlock(outer)}</coordinates></LinearRing></outerBoundaryIs>`;
  for (let i = 1; i < rings.length; i++) {
    kml += `<innerBoundaryIs><LinearRing><coordinates>${coordinatesBlock(rings[i])}</coordinates></LinearRing></innerBoundaryIs>`;
  }
  return kml + '</Polygon>';
}

function buildGeometry(geom: GeoJSON.Geometry | null): string {
  if (!geom) return '';
  switch (geom.type) {
    case 'Point':
      return `<Point><coordinates>${coordStr(geom.coordinates)}</coordinates></Point>`;
    case 'MultiPoint':
      return buildMulti(geom.coordinates.map((c) => `<Point><coordinates>${coordStr(c)}</coordinates></Point>`));
    case 'LineString':
      return `<LineString><coordinates>${coordinatesBlock(geom.coordinates)}</coordinates></LineString>`;
    case 'MultiLineString':
      return buildMulti(geom.coordinates.map((line) => `<LineString><coordinates>${coordinatesBlock(line)}</coordinates></LineString>`));
    case 'Polygon':
      return buildPolygon(geom.coordinates);
    case 'MultiPolygon':
      return buildMulti(geom.coordinates.map(buildPolygon));
    case 'GeometryCollection':
      return buildMulti(geom.geometries.map(buildGeometry));
    default:
      return '';
  }
}

function buildDescription(props: Record<string, unknown> | null | undefined): string {
  if (!props) return '';
  const lines: string[] = [];
  for (const [k, v] of Object.entries(props)) {
    if (k.startsWith('geo_')) continue;
    if (v == null || typeof v === 'object') continue;
    lines.push(`${escapeXml(k)}: ${escapeXml(v)}`);
  }
  return lines.join('<br/>');
}

const SCHEMA_ID = 'layer_fields';

/** Typed fields (QGIS / GDAL read ExtendedData/SchemaData as real attribute columns; a description is just one text blob). */
function fieldTypes(features: GeoJSON.Feature[]): Map<string, 'int' | 'double' | 'string'> {
  const out = new Map<string, 'int' | 'double' | 'string'>();
  const seen = new Map<string, unknown[]>();
  for (const f of features) {
    for (const [k, v] of Object.entries(f.properties ?? {})) {
      if (k.startsWith('geo_') || (v != null && typeof v === 'object')) continue;
      if (!seen.has(k)) seen.set(k, []);
      if (v != null && v !== '') seen.get(k)!.push(v);
    }
  }
  for (const [k, vals] of seen) {
    const numbers = vals.length > 0 && vals.every((v) => typeof v === 'number' && Number.isFinite(v));
    out.set(k, numbers ? (vals.every((v) => Number.isInteger(v)) ? 'int' : 'double') : 'string');
  }
  return out;
}

function schemaXml(types: Map<string, string>): string {
  if (types.size === 0) return '';
  const fields = Array.from(types, ([k, t]) => `<SimpleField name="${escapeXml(k)}" type="${t}"/>`).join('');
  return `    <Schema name="${SCHEMA_ID}" id="${SCHEMA_ID}">${fields}</Schema>\n`;
}

function extendedData(props: Record<string, unknown> | null | undefined, types: Map<string, string>): string {
  if (!props || types.size === 0) return '';
  const cells = Object.entries(props)
    .filter(([k, v]) => !k.startsWith('geo_') && v != null && v !== '' && typeof v !== 'object')
    .map(([k, v]) => `<SimpleData name="${escapeXml(k)}">${escapeXml(typeof v === 'object' ? JSON.stringify(v) : v)}</SimpleData>`)
    .join('');
  return cells ? `<ExtendedData><SchemaData schemaUrl="#${SCHEMA_ID}">${cells}</SchemaData></ExtendedData>\n      ` : '';
}

function buildPlacemark(feature: ExportFeature, index: number, styleIdOf?: (sym: FeatureSymbol) => string, types: Map<string, string> = new Map()): string {
  const props = feature.properties as Record<string, unknown> | null;
  const name = feature._name || props?.name || props?.id || `Feature ${index + 1}`;
  const description = buildDescription(props);
  const geom = buildGeometry(feature.geometry ?? null);
  const descKml = description ? `<description>${description}</description>\n      ` : '';
  const styleKml = feature._symbol && styleIdOf ? `<styleUrl>#${styleIdOf(feature._symbol)}</styleUrl>\n      ` : '';
  return `    <Placemark>\n      <name>${escapeXml(name)}</name>\n      ${descKml}${styleKml}${extendedData(props, types)}${geom}\n    </Placemark>`;
}

/**
 * Serialize GeoJSON features into a KML 2.2 document that opens in Google Earth,
 * QGIS, and Windows GIS viewers. Point/LineString/Polygon plus all Multi-*
 * and GeometryCollection variants are supported.
 */
export function geojsonToKml(features: GeoJSON.Feature[], layerName: string): string {
  // Features that carry a `_symbol` are drawn in it: one shared <Style> per distinct look.
  const styles = new Map<string, { id: string; sym: FeatureSymbol }>();
  const styleIdOf = (sym: FeatureSymbol): string => {
    const key = JSON.stringify(sym);
    let hit = styles.get(key);
    if (!hit) {
      hit = { id: `s${styles.size + 1}`, sym };
      styles.set(key, hit);
    }
    return hit.id;
  };
  const types = fieldTypes(features);
  const placemarks = features.map((f, i) => buildPlacemark(f as ExportFeature, i, styleIdOf, types)).join('\n');
  const styleBlocks = Array.from(styles.values()).map((v) => `    <Style id="${v.id}">${styleBody(v.sym)}</Style>\n`).join('');
  return `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>${escapeXml(layerName)}</name>
    <description>Exported from CFMS</description>
${schemaXml(types)}${styleBlocks}${placemarks}
  </Document>
</kml>`;
}
