import type L from 'leaflet';
import type { Feature } from 'geojson';

/**
 * FeatureLayerRegistry — E-0 spike (E0.1).
 *
 * Maps a GeoJSON feature id → the real `L.Polygon`/`L.Polyline`/`L.Marker`
 * instance react-leaflet created for it.  react-leaflet `<GeoJSON>` layers are
 * keyed and recreated on every refresh, so this Map must be re-populated by
 * every layer's `onEachFeature` and cleaned up on layer `remove`.  No separate
 * cache/timing is needed beyond the leaflet layer lifecycle.
 */
class FeatureLayerRegistry {
  private store = new Map<string, L.Layer>();
  readonly instanceId = Math.random().toString(36).slice(2, 8);

  get size(): number {
    return this.store.size;
  }

  // DEV-only DOM trace so headless probes can see writes across eval worlds.
  private trace(msg: string): void {
    if (!import.meta.env.DEV) return;
    if (typeof document !== 'undefined' && document.documentElement) {
      const d = document.documentElement;
      const log = d.dataset.regLog ? JSON.parse(d.dataset.regLog) : [];
      log.push(this.instanceId + ' ' + msg + ' (size=' + this.store.size + ') t=' + Date.now());
      d.dataset.regLog = JSON.stringify(log.slice(-20));
    }
  }

  /** Register a feature→layer mapping (was called once per feature in onEachFeature). */
  register(featureId: string, layer: L.Layer): void {
    this.store.set(featureId, layer);
    this.trace(`register ${featureId}`);
    // Re-register when react-leaflet's `useLayerLifecycle` re-creates the
    // LeafletContext provider: it calls removeLayer/addLayer on the *same*
    // L.GeoJSON instance. The child feature layers fire 'remove' (→ guard
    // deletes the old mapping) and 'add' on re-attach, but addData/onEachFeature
    // do NOT re-run — so without this listener the mapping vanishes and
    // geoman-edit/split effects can't resolve the live layer.
    layer.on('add', () => {
      if (this.store.get(featureId) !== layer) {
        this.store.set(featureId, layer);
        this.trace(`readd ${featureId} (size=${this.store.size})`);
      }
    });
    layer.on('remove', () => {
      // Only evict when the removed layer is STILL the current entry — a remount
      // may remove an old copy while a newer copy is already registered.
      if (this.store.get(featureId) === layer) {
        this.store.delete(featureId);
        this.trace(`remove ${featureId}`);
      }
    });
  }

  /** Resolve the live layer instance for a feature id, or undefined. */
  get(featureId: string): L.Layer | undefined {
    return this.store.get(featureId);
  }

  has(featureId: string): boolean {
    return this.store.has(featureId);
  }

  clear(): void {
    this.store.clear();
    this.trace('clear');
  }

  /** Iterate over all registered feature layers. */
  forEach(callback: (id: string, layer: L.Layer) => void): void {
    for (const [id, layer] of this.store.entries()) {
      callback(id, layer);
    }
  }
}

/** Module-level singleton so MapCanvas can fill it and MapWorkspace can read it. */
const registry = new FeatureLayerRegistry();

// DEV-only: expose for browser/E2E debugging (removed in prod builds).
if (import.meta.env.DEV) {
  (window as any).__featureReg = registry;
}

export function getFeatureLayerRegistry(): FeatureLayerRegistry {
  if (import.meta.env.DEV && typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.dataset.regGetId = registry.instanceId;
  }
  return registry;
}

/** Convenience: register every feature in an onEachFeature handler. */
export function registerFeatureLayer(feature: Feature, layer: L.Layer): void {
  const id = feature.properties?.id ?? feature.properties?.featureId;
  if (id == null) return;
  getFeatureLayerRegistry().register(String(id), layer);
}

export default FeatureLayerRegistry;