import type L from 'leaflet';
import type { Feature } from 'geojson';

/**
 * E-0 spike helpers — prove the Geoman-on-registry-layer path (E0.1/E0.2/E0.3)
 * BEFORE committing to the full E-2 editing pipeline.
 *
 * - E0.1 (lookup + pm.enable): resolve the live `L.Layer` for a feature id from
 *   the feature layer registry, then enable Geoman edit markers on it.
 * - E0.2 (lifecycle): listen for `pm:editstart / pm:vertexdrag / pm:markerdragend
 *   / pm:vertexadded / pm:vertexremoved / pm:edit / pm:editend`.
 * - E0.3 (throttle): `pm:edit` fires continuously during a drag — it must NOT
 *   POST. Only drag-release (`pm:markerdragend`) and `pm:editend / pm:vertexadded
 *   / pm:vertexremoved` are save points. One POST per drag-release.
 *
 * This is a SPIKING harness, deliberately small. If the gate fails (lookup or
 * pm.enable can't reach a rendered layer) we pivot to a non-Geoman vertex
 * editor instead — see IMPLEMENTATION_PLAN_FEATURE_EDITING.md Phase E-0.
 */

export interface GeomanSpikeSaveOptions {
  /** Called on every drag-release with the edited layer's geometry. */
  onSave: (feature: Feature) => Promise<void> | void;
  /** Called on continuous drag move (pm:edit) — must never POST. */
  onDragMove?: () => void;
}

/**
 * Enable Geoman editing on a registry-resolved layer and return a cleanup fn.
 * The layer is whatever react-leaflet created for the feature (raw L.Polygon…).
 */
export function enableRegistryLayerGeoman(
  map: L.Map | null,
  registry: { get(fid: string): L.Layer | undefined },
  featureId: string,
  opts: GeomanSpikeSaveOptions,
): () => void {
  const noop = () => {};
  if (!map || !featureId) return noop;
  const layer = registry.get(featureId);
  if (!layer) return noop;

  const pmLayer: any = layer as any;
  if (pmLayer.pm) pmLayer.pm.disable();
  pmLayer.pm.enable({
    edit: true,
    drag: true,
    snap: true,
    allowSelfIntersection: false,
  });

  const handleDragMove = () => opts.onDragMove?.(); // E0.3: just a counter/log
  const handleDragEnd = () => {
    try {
      const feature = (layer as any).toGeoJSON() as Feature;
      void opts.onSave(feature);
    } catch (err) {
      console.error('[GeomanSpike] save failed at drag-release:', err);
    }
  };
  const handleVertexChange = () => {
    try {
      const feature = (layer as any).toGeoJSON() as Feature;
      void opts.onSave(feature);
    } catch (err) {
      console.error('[GeomanSpike] save failed after vertex change:', err);
    }
  };

  map.on('pm:edit', handleDragMove);
  layer.on('pm:markerdragend', handleDragEnd);
  layer.on('pm:vertexadded', handleVertexChange);
  layer.on('pm:vertexremoved', handleVertexChange);

  return () => {
    map.off('pm:edit', handleDragMove);
    layer.off('pm:markerdragend', handleDragEnd);
    layer.off('pm:vertexadded', handleVertexChange);
    layer.off('pm:vertexremoved', handleVertexChange);
    try {
      if (pmLayer.pm?.enabled()) pmLayer.pm.disable();
    } catch {
      /* leaflet layer may already be destroyed */
    }
  };
}