/**
 * Find, zoom to and select units BY NAME — what "jump to the top unit", "select this class in the table" and "zoom to this class"
 * all need.
 *
 * The map's unit features live in the feature-layer registry (feature id -> Leaflet layer); each unit layer stamps the layer it
 * belongs to on its features (`__unitLayerId`, set in MapCanvas's onEachFeature). A unit name is unique within a forest, so a
 * name finds its feature whatever level it is on (block, compartment, sub-block, sub-compartment).
 */
import type L from 'leaflet';
import { getFeatureLayerRegistry } from './featureLayerRegistry';
import { analysisMapDef, isFiMap, resolveAnalysisRenderer, type AnalysisMapId } from './analysisMaps';
import { rendererColorFor, type RendererSpec } from './layerRenderers';
import { sfmPropsFor } from './sfmFeatureProps';
import type { SfmBlockTypeInfo } from '../services/api';
import type { UnitMapData } from './unitMapProps';

export interface FoundUnit {
  id: string;
  name: string;
  layerId: string | null;
  layer: L.Layer;
}

type UnitLayer = L.Layer & { feature?: { properties?: Record<string, unknown> }; __unitLayerId?: string; getBounds?: () => L.LatLngBounds };

/** Every registered unit feature whose name is in `names`. */
export function findUnits(names: string[]): FoundUnit[] {
  const want = new Set(names);
  const out: FoundUnit[] = [];
  getFeatureLayerRegistry().forEach((id, layer) => {
    const l = layer as UnitLayer;
    const name = String(l.feature?.properties?.name ?? '');
    if (want.has(name) && l.__unitLayerId) out.push({ id, name, layerId: l.__unitLayerId, layer });
  });
  return out;
}

/** Fit the map to the named units. Returns how many were found (0 = nothing moved). */
export function zoomToUnits(map: L.Map | null | undefined, names: string[]): number {
  if (!map) return 0;
  const found = findUnits(names);
  let bounds: L.LatLngBounds | null = null;
  for (const u of found) {
    const b = (u.layer as UnitLayer).getBounds?.();
    if (b && b.isValid()) bounds = bounds ? bounds.extend(b) : b;
  }
  if (!bounds) return 0;
  map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
  return found.length;
}

/** The layer most of the found units sit on, with their feature ids — the selection the attribute table understands. */
export function selectionFor(names: string[]): { layerId: string; ids: string[] } | null {
  const found = findUnits(names);
  if (found.length === 0) return null;
  const count = new Map<string, number>();
  for (const u of found) count.set(u.layerId!, (count.get(u.layerId!) ?? 0) + 1);
  const layerId = [...count.entries()].sort((a, b) => b[1] - a[1])[0][0];
  return { layerId, ids: found.filter((u) => u.layerId === layerId).map((u) => u.id) };
}

export interface ClassContext {
  unitMap: UnitMapData | null | undefined;
  sfmBlockTypes: Record<string, SfmBlockTypeInfo> | undefined;
  saved: Record<string, RendererSpec | undefined>;
}

/** The unit names whose class colour is `colour` on the active unit-class map (SFM or field inventory). */
export function unitsOfClass(id: AnalysisMapId | null | undefined, colour: string | null, ctx: ClassContext): string[] {
  if (!id || !colour) return [];
  const want = colour.toLowerCase();
  if (isFiMap(id)) {
    if (!ctx.unitMap || ctx.unitMap.state !== 'ready') return [];
    return Object.entries(ctx.unitMap.units).filter(([, u]) => (u.color || '').toLowerCase() === want).map(([n]) => n);
  }
  if (id === 'sfm_type' || id === 'sfm_orientation' || id === 'sfm_stock') {
    const spec = resolveAnalysisRenderer(id, ctx.saved);
    if (!spec) return [];
    const field = (spec as { field: string }).field;
    return Object.entries(ctx.sfmBlockTypes ?? {})
      .filter(([, info]) => {
        const v = (sfmPropsFor(info) as Record<string, unknown>)[field];
        return (rendererColorFor(spec, v) ?? '').toLowerCase() === want;
      })
      .map(([n]) => n);
  }
  return [];
}

export const hasClassUnits = (id: AnalysisMapId | null | undefined): boolean => !!id && (isFiMap(id) || !!analysisMapDef(id)?.group?.startsWith('sfm'));
