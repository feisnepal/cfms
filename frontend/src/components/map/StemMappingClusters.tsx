/**
 * Stem Mapping's on-map rendering: viewport-tile clustering, not a flat
 * GeoJSON of every tree.
 *
 * Reported symptom: the layer "becomes unresponsive" for a forest with a
 * large tree count -- because the old rendering fetched every tree's
 * GeoJSON feature up front and gave each one its own Leaflet circleMarker
 * (thousands of individual SVG/vector layers). This reuses the U05/U06
 * pipeline that was built for exactly this problem and never wired into any
 * shell: `cluster_inventory_trees` (server-side PostGIS tile clustering,
 * cached, rate-limited) + `useVisibleTreeClusterTiles` (viewport-scoped,
 * queued tile fetches) + `TreeClustersLayer` (one shared L.Canvas renderer
 * for every marker, not one DOM/SVG element per tree). At z<18 the server
 * returns aggregated cluster counts; at z>=18 (zoomed into a stand) it
 * returns individual trees, styled here by the same DBH-band colour/size
 * scale the rest of Stem Mapping uses.
 */
import { useCallback, useEffect, useState } from 'react';
import { useMap } from 'react-leaflet';
import { useWorkspaceStore } from '../../store/workspaceStore';
import { useVisibleTreeClusterTiles } from '../../hooks/useTreeClusters';
import { TreeClustersLayer } from './TreeClustersLayer';

// getViewportTiles / tileXY take [lng, lat] pairs — [[west, south], [east, north]] —
// not Leaflet's usual [lat, lng] order (lib/mapOverlays.ts, lib/webmercator.ts).
type LngLatBounds = [[number, number], [number, number]];

// Permanent scale-based visibility (not a user toggle): below this zoom a
// whole-forest dot cloud has no reading value, so Stem Mapping draws only the
// hint. From here up it renders whatever the tile carries — the backend
// (tree_clusters.py) returns aggregated cluster bubbles below ZOOM_INDIVIDUALS
// and individual trees at or above it.
const MIN_VISIBLE_ZOOM = 13;
// Backend crossover (ZOOM_INDIVIDUALS in tree_clusters.py): cluster bubbles
// below, individual trees at/above. The attribute filter only bites on
// individuals, so the "zoom in for the filter" hint points here, not at
// MIN_VISIBLE_ZOOM.
const ZOOM_INDIVIDUALS = 18;

function ZoomInHint({ filterActive }: { filterActive?: boolean }) {
  return (
    <div
      className="leaflet-control stem-mapping-zoom-hint"
      style={{
        position: 'absolute',
        top: '10px',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 1000,
        padding: '6px 12px',
        background: 'rgba(255,255,255,0.95)',
        borderRadius: '4px',
        boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        fontSize: '12px',
        fontFamily: 'inherit',
        pointerEvents: 'none',
      }}
    >
      {filterActive
        ? `The table filter applies to individual trees — zoom in to ${ZOOM_INDIVIDUALS}+ to see it on the map`
        : `Zoom in to see Stem Mapping (from zoom ${MIN_VISIBLE_ZOOM}+)`}
    </div>
  );
}

export function StemMappingClusters({ visible }: { visible: boolean }) {
  const map = useMap();
  const calcId = useWorkspaceStore((s) => s.calculationId);
  const geometryVersion = useWorkspaceStore((s) => s.geometryVersion);
  // The Style Layer dialog's active renderer (defaults to DBH-band, seeded by
  // useLayerRenderers) — read here so a "colour by species" override still
  // takes effect on the clustered view, not just the pre-clustering one.
  const renderer = useWorkspaceStore((s) => s.layerRenderers.stem_mapping);
  // P4.6 "show only matches on map" — scoped here (not inside TreeClustersLayer)
  // the same way MapWorkspace's `mapFeatures` memo scopes it per layer: only
  // pass it through when it actually targets this layer.
  const tableFilter = useWorkspaceStore((s) => s.tableFilter);
  const filter = tableFilter?.layerId === 'stem_mapping' ? tableFilter : null;
  const [viewport, setViewport] = useState<{ bounds: LngLatBounds; zoom: number } | null>(null);
  // Species isolation + the "species in view" counts live in the store: the legend is drawn by the
  // layer panel under the Stem Mapping row (a viewing aid, so session-only).
  const isolated = useWorkspaceStore((s) => s.stemLegend.isolated);
  const setStemLegendCounts = useWorkspaceStore((s) => s.setStemLegendCounts);
  const setStemIsolated = useWorkspaceStore((s) => s.setStemIsolated);
  const reportSpeciesCounts = useCallback(
    (counts: Map<string, number>) => setStemLegendCounts(Object.fromEntries(counts)),
    [setStemLegendCounts],
  );

  // Click an individual tree → select its row in the Stem Mapping attribute
  // table (replaces the removed per-tree popup — the row carries the exact
  // numbers; the marker's colour/size already read as DBH class). Live store
  // via getState(), same pattern as MapCanvas's feature-click handler.
  const handleSelectTree = useCallback((treeId: string) => {
    useWorkspaceStore.getState().selectFeatures('stem_mapping', [treeId], 'replace');
  }, []);

  const sync = useCallback(() => {
    const b = map.getBounds();
    setViewport({
      bounds: [[b.getWest(), b.getSouth()], [b.getEast(), b.getNorth()]],
      zoom: map.getZoom(),
    });
  }, [map]);

  // Only track the viewport (and therefore only fetch tiles) while the layer
  // is actually visible — panning around with it hidden must cost nothing.
  useEffect(() => {
    if (!visible) return;
    sync();
    map.on('moveend', sync);
    map.on('zoomend', sync);
    return () => {
      map.off('moveend', sync);
      map.off('zoomend', sync);
    };
  }, [map, visible, sync]);

  const belowMinZoom = viewport != null && viewport.zoom < MIN_VISIBLE_ZOOM;

  // Below MIN_VISIBLE_ZOOM this costs nothing beyond the moveend/zoomend
  // listeners already attached above — no tile fetch is issued at all, same
  // as the `visible: false` case below.
  const { tiles } = useVisibleTreeClusterTiles(
    calcId,
    geometryVersion,
    viewport?.bounds ?? null,
    viewport?.zoom ?? -1,
    visible && !belowMinZoom,
  );

  // Nothing on screen to describe -> empty legend, and drop any isolation left over.
  const showing = visible && viewport != null && !belowMinZoom;
  useEffect(() => {
    if (!showing) {
      setStemLegendCounts({});
      setStemIsolated(null);
    }
  }, [showing, setStemLegendCounts, setStemIsolated]);
  useEffect(() => () => {
    setStemLegendCounts({});
    setStemIsolated(null);
  }, [setStemLegendCounts, setStemIsolated]);

  if (!visible || !viewport) return null;

  if (belowMinZoom) {
    return <ZoomInHint filterActive={!!filter} />;
  }

  return (
    <TreeClustersLayer
      tiles={tiles}
      mapZoom={viewport.zoom}
      onZoomToCluster={(center, zoom) => map.setView(center, zoom)}
      visible={visible}
      renderer={renderer}
      filter={filter}
      onSelectTree={handleSelectTree}
      isolated={isolated}
      onSpeciesCounts={reportSpeciesCounts}
    />
  );
}
