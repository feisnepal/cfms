import L from 'leaflet';

/**
 * "Zoom to Layer" (owner report 2026-10-02: match QGIS/ArcGIS exactly).
 * Both fit the layer's own bounding box to the canvas edge-to-edge, with
 * only a small margin -- not a fixed pixel gutter that eats a bigger
 * fraction of a small map panel than a big one. `bounds.pad()` expands the
 * extent by a FRACTION of its own size (5% each side here) before fitting,
 * so the margin scales with the layer, matching that behaviour, rather than
 * `fitBounds`'s own `padding` option, which is a fixed pixel count
 * regardless of zoom or panel size.
 *
 * SSOT for every "zoom to layer" call site (MapWorkspace's own zoomToLayer
 * and post-import zoom, LayerPanel's raster-layer zoom) -- one constant to
 * change if the margin ever needs revisiting, rather than N call sites each
 * guessing their own pixel number.
 */
export const ZOOM_TO_LAYER_BOUNDS_PAD = 0.05;

/** Nepal's extent (south-west, north-east): what a map shows when there is nothing of the forest to fit to. */
export const NEPAL_BOUNDS = L.latLngBounds([26.3, 80.0], [30.5, 88.3]);

/** Below this the map shows a continent or the whole earth, which is never the view anyone wants here. */
export const MIN_USEFUL_ZOOM = 5;

/** The map's container has no size (a hidden panel): a fit then computes the lowest zoom, the whole earth. */
export function isMapHidden(map: L.Map): boolean {
  const size = map.getSize();
  return size.x === 0 || size.y === 0;
}

/**
 * Fit the map to ``bounds`` -- but only once it can be seen.
 *
 * The workspace keeps its panels mounted and hides them with CSS, so the map often exists with a 0x0 container (the page was
 * opened on another step, or the user is on one). Leaflet's ``fitBounds`` on a map with no size picks zoom 0, the whole earth, and
 * the one-time "zoom to the forest" never ran again, so returning to the Map showed the globe. A fit asked for while hidden now
 * waits for the next resize (the container being shown) and runs then. Invalid bounds fall back to Nepal's extent.
 */
export function fitBoundsWhenVisible(map: L.Map, bounds: L.LatLngBounds, options?: L.FitBoundsOptions): void {
  const target = bounds.isValid() ? bounds : NEPAL_BOUNDS;
  if (isMapHidden(map)) {
    map.once('resize', () => fitBoundsWhenVisible(map, bounds, options));
    return;
  }
  map.fitBounds(target, options);
}

/** If the map is showing the globe (from any cause), bring it to Nepal's extent. Returns whether it did. */
export function recoverFromWorldView(map: L.Map): boolean {
  if (isMapHidden(map) || map.getZoom() >= MIN_USEFUL_ZOOM) return false;
  map.fitBounds(NEPAL_BOUNDS, { animate: false });
  return true;
}

export function zoomToLayerBounds(map: L.Map, bounds: L.LatLngBounds, maxZoom = 18): void {
  if (!bounds.isValid()) return;
  fitBoundsWhenVisible(map, bounds.pad(ZOOM_TO_LAYER_BOUNDS_PAD), { maxZoom });
}
