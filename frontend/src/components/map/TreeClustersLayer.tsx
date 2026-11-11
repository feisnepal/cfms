/**
 * Canvas-rendered tree cluster markers — U06.
 * Individual trees share one canvas renderer (stemCanvas.ts) to avoid SVG DOM overhead:
 * colour = prime species, size = DBH class (zoom-scaled), shape = tree group (mother = star).
 * Clusters (point_count) render below the density / zoom switch, individuals above it.
 */
/* eslint-disable react/prop-types -- typed via TS component props; the rule is a false positive for TS function components */

import { useEffect, useMemo } from 'react';
import { CircleMarker, Marker, Popup, useMap } from 'react-leaflet';
import L, { type LeafletMouseEvent } from 'leaflet';
import { TreeClusterTileData } from '../../hooks/useTreeClusters';
import { rendererColorFor, type RendererSpec } from '../../lib/layerRenderers';
import { matchFeature, type AttributeFilter } from '../../lib/attributeFilter';
import { OTHER_COLOR, OTHER_KEY, PRIME_SPECIES_FIELD, PRIME_SPECIES_RENDERER } from '../../lib/primeSpecies';
import { stemRadius, stemShape, treeGroupOf } from '../../lib/stemSymbols';
import { getStemCanvasRenderer } from './stemCanvas';

// --- Cluster bubble (the QGIS Point Cluster look: a coloured disc with the
// count written on it) ---
// A DOM icon per cluster, not the canvas path individuals use: correct,
// because clusters are capped at 500/tile (TOTAL_CAP, tree_clusters.py) and
// there are typically far fewer than that on screen at once, so the DOM cost
// this reintroduces is trivial -- unlike doing it for potentially thousands
// of individual trees, which is the exact cost this whole pipeline exists to
// avoid.
function clusterRadius(count: number, zoomHint: boolean): number {
  if (zoomHint) return 26; // a dense (drill-in) cell is the largest bubble
  // Continuous, not three fixed buckets: grows with sqrt(count) so a cluster
  // of 400 visibly outsizes one of 4, the way QGIS / every recognizable
  // cluster map scales its bubbles.
  return Math.min(24, 14 + Math.sqrt(count) * 1.3);
}

// The TRUE tree count, compact: 324 · 1.2k · 7.4k · 35k.
function clusterLabel(count: number): string {
  if (count < 1000) return String(count);
  if (count < 10000) return `${(count / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return `${Math.round(count / 1000)}k`;
}

function clusterIcon(count: number, zoomHint: boolean): L.DivIcon {
  const r = clusterRadius(count, zoomHint);
  const d = Math.round(r * 2);
  const bg = zoomHint ? '#ff4d4f' : '#1890ff'; // red = dense cell (click to drill in), blue = normal
  const label = clusterLabel(count);
  return L.divIcon({
    className: 'tree-cluster-bubble',
    html: `<div style="
      width:${d}px;height:${d}px;border-radius:50%;
      background:${bg};border:2px solid #fff;
      box-shadow:0 1px 4px rgba(0,0,0,0.45);
      display:flex;align-items:center;justify-content:center;
      color:#fff;font-weight:700;font-family:inherit;
      font-size:${r >= 20 ? 13 : 11}px;line-height:1;
    ">${label}</div>`,
    iconSize: [d, d],
    iconAnchor: [d / 2, d / 2],
  });
}

// --- Tree Cluster Marker Component ---
interface TreeClusterMarkerProps {
  feature: GeoJSON.Feature<GeoJSON.Point>;
  mapZoom: number;
  onZoomToCluster?: (center: [number, number], zoom: number) => void;
  /** The Style Layer dialog's active renderer for stem_mapping, if the
   *  default DBH-band one has been replaced (e.g. "colour by species") —
   *  falls back to PRIME_SPECIES_RENDERER (colour by prime species). */
  renderer?: RendererSpec;
  /** Species isolation: this tree is not the isolated species -> drawn faint and inert. */
  dimmed?: boolean;
  /**
   * Click on an INDIVIDUAL tree → select its row in the attribute table.
   * There is no per-tree popup: DBH class is already the colour and DBH
   * magnitude the radius, so the popup only repeated a number the table row
   * carries. Not wired for cluster bubbles — those keep click-to-zoom.
   */
  onSelectTree?: (treeId: string) => void;
}

export function TreeClusterMarker({ feature, mapZoom, onZoomToCluster, renderer, dimmed, onSelectTree }: TreeClusterMarkerProps) {
  const [lng, lat] = feature.geometry.coordinates;
  const props = feature.properties as { point_count?: number; zoom_hint?: boolean; [key: string]: any };
  const isCluster = typeof props.point_count === 'number';

  if (isCluster) {
    // `point_count` is capped at CAP_CLUSTER (500) by the backend; `actual_count`
    // is the real number of trees in the cell. Show the truth ("7.4k"), not the
    // cap ("500+"). `zoom_hint` just means "dense cell — click to drill in" and
    // still drives the red colour + click-to-zoom.
    const count = typeof props.actual_count === 'number' ? props.actual_count : (props.point_count ?? 1);
    const zoomHint = props.zoom_hint === true;
    return (
      <Marker
        position={[lat, lng]}
        icon={clusterIcon(count, zoomHint)}
        eventHandlers={{
          click: () => onZoomToCluster?.([lat, lng], mapZoom + 2),
        }}
      >
        <Popup>{`${count.toLocaleString()} trees — click to zoom in`}</Popup>
      </Marker>
    );
  }

  const dbhCm: number | undefined = typeof props.dbh_cm === 'number' ? props.dbh_cm : undefined;
  const effectiveRenderer = renderer ?? PRIME_SPECIES_RENDERER;
  const group = treeGroupOf(props.tree_group);
  const shape = stemShape(group);
  // Size is always DBH-graded (and zoom-scaled); colour is the renderer's; shape is the group's.
  const radius = stemRadius(dbhCm, group, mapZoom);
  const fillColor =
    group === 'seedling'
      ? OTHER_COLOR
      : rendererColorFor(effectiveRenderer, props[effectiveRenderer.field]) ?? OTHER_COLOR;
  const treeId = props.id != null ? String(props.id) : null;
  const selectable = !!onSelectTree && !!treeId && !dimmed;
  // Mother trees get a dark outline so the star holds up on every species colour.
  const outlined = shape === 'star' && !dimmed;
  const style = {
    fillColor,
    fillOpacity: dimmed ? 0.12 : group === 'seedling' ? 0.6 : 0.85,
    stroke: outlined,
    color: '#111111',
    weight: 1,
    opacity: 0.9,
  };

  return (
    <CircleMarker
      center={[lat, lng]}
      radius={radius}
      fillColor={fillColor}
      pathOptions={style}
      renderer={getStemCanvasRenderer()}
      interactive={selectable}
      // `shape` is read by the star-drawing canvas (stemCanvas.ts); react-leaflet
      // forwards unknown props to the Leaflet marker's options.
      {...({ shape } as object)}
      eventHandlers={
        selectable
          ? {
              click: (e: LeafletMouseEvent) => {
                // Keep the click off the map's background handler, which would
                // clear the selection we're about to make (same guard the
                // MapCanvas feature-click handler uses).
                L.DomEvent.stopPropagation(e);
                onSelectTree!(treeId!);
              },
            }
          : undefined
      }
    />
  );
}

// --- Tree Clusters Layer (renders all tiles' features) ---
interface TreeClustersLayerProps {
  tiles: Map<string, { data: TreeClusterTileData | null; state: 'idle' | 'loading' | 'error' | 'ready' }>;
  mapZoom: number;
  onZoomToCluster?: (center: [number, number], zoom: number) => void;
  visible?: boolean;
  renderer?: RendererSpec;
  /** P4.6's "show only matches on map" filter, already scoped to `stem_mapping`
   *  by the caller (the same filter object other layers pass through
   *  `filterForMap`). Only ever meaningful against individual-tree features —
   *  a cluster bubble has no per-tree properties to test, so it always passes. */
  filter?: AttributeFilter | null;
  /** Click on an individual tree → select its attribute-table row. */
  onSelectTree?: (treeId: string) => void;
  /** Isolated species row key (prime code as string, or OTHER_KEY); null = show all. */
  isolated?: string | null;
  /** Tree count per species in view (prime code as string, or OTHER_KEY). The legend is drawn by
   *  the layer panel under the Stem Mapping row, not on the map -- this is how it gets its rows. */
  onSpeciesCounts?: (counts: Map<string, number>) => void;
}

/** The legend row a tree belongs to: its prime species code, or OTHER_KEY. */
function speciesKeyOf(f: GeoJSON.Feature<GeoJSON.Point>): string {
  const c = f.properties?.[PRIME_SPECIES_FIELD];
  return c == null ? OTHER_KEY : String(c);
}

// A viewport spanning several dense z>=18 tiles can carry many thousands of
// individual trees; mounting that many <CircleMarker>/<Popup> in one
// synchronous render is what froze the tab ("page unresponsive"), and toggling
// the attribute filter re-triggered it. The backend already caps individuals
// per tile (INDIVIDUAL_CAP); this caps the on-screen sum. Clusters are never
// capped — they are bounded per tile and there are few of them.
export const MAX_INDIVIDUAL_MARKERS = 2500;

function TreeCapNotice({ shown, total }: { shown: number; total: number }) {
  return (
    <div
      className="leaflet-control stem-mapping-cap-hint"
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
      {`Showing ${shown.toLocaleString()} of ${total.toLocaleString()} trees — zoom in or narrow the filter`}
    </div>
  );
}

export function TreeClustersLayer({
  tiles,
  mapZoom,
  onZoomToCluster,
  visible = true,
  renderer,
  filter,
  onSelectTree,
  isolated = null,
  onSpeciesCounts,
}: TreeClustersLayerProps) {
  const { clusters, individuals, matchCount } = useMemo(() => {
    if (!visible) return { clusters: [], individuals: [], matchCount: 0 };
    const clusterFeats: GeoJSON.Feature<GeoJSON.Point>[] = [];
    const individualFeats: GeoJSON.Feature<GeoJSON.Point>[] = [];
    for (const { data, state } of tiles.values()) {
      if (state === 'ready' && data?.features) {
        for (const f of data.features as GeoJSON.Feature<GeoJSON.Point>[]) {
          if (typeof f.properties?.point_count === 'number') clusterFeats.push(f);
          else individualFeats.push(f);
        }
      }
    }
    // The filter only bites on individual trees — a cluster bubble has no
    // per-tree properties to test, so it always shows.
    const matched = filter
      ? individualFeats.filter((f) => matchFeature(f, filter.field, filter.op, filter.value))
      : individualFeats;
    return {
      clusters: clusterFeats,
      individuals: matched.length > MAX_INDIVIDUAL_MARKERS ? matched.slice(0, MAX_INDIVIDUAL_MARKERS) : matched,
      matchCount: matched.length,
    };
  }, [tiles, visible, filter]);

  // The legend describes the species colouring, so it only exists while that
  // renderer is the active one; a user-chosen renderer has its own legend panel.
  const speciesColoured = (renderer ?? PRIME_SPECIES_RENDERER).field === PRIME_SPECIES_FIELD;
  const speciesCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const f of individuals) {
      const k = speciesKeyOf(f);
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    return counts;
  }, [individuals]);

  useEffect(() => {
    onSpeciesCounts?.(speciesColoured ? speciesCounts : new Map());
  }, [speciesCounts, speciesColoured, onSpeciesCounts]);

  return (
    <>
      {clusters.map((feature, idx) => (
        <TreeClusterMarker
          key={`c-${feature.geometry.coordinates[0]}-${feature.geometry.coordinates[1]}-${idx}`}
          feature={feature}
          mapZoom={mapZoom}
          onZoomToCluster={onZoomToCluster}
          renderer={renderer}
        />
      ))}
      {individuals.map((feature, idx) => (
        <TreeClusterMarker
          key={`t-${feature.properties?.id ?? idx}`}
          feature={feature}
          mapZoom={mapZoom}
          onZoomToCluster={onZoomToCluster}
          renderer={renderer}
          dimmed={isolated !== null && speciesColoured && speciesKeyOf(feature) !== isolated}
          onSelectTree={onSelectTree}
        />
      ))}
      {matchCount > individuals.length && (
        <TreeCapNotice shown={individuals.length} total={matchCount} />
      )}
    </>
  );
}

// --- Loading / Error Overlay Indicators ---
interface TreeClusterStatusProps {
  tiles: Map<string, { data: TreeClusterTileData | null; state: 'idle' | 'loading' | 'error' | 'ready' }>;
  position?: 'topright' | 'bottomright' | 'topleft' | 'bottomleft';
}

export function TreeClusterStatus({ tiles, position = 'topright' }: TreeClusterStatusProps) {
  const map = useMap();
  const loadingCount = Array.from(tiles.values()).filter((t) => t.state === 'loading').length;
  const errorCount = Array.from(tiles.values()).filter((t) => t.state === 'error').length;

  if (loadingCount === 0 && errorCount === 0) return null;

  return (
    <div
      className="leaflet-control tree-cluster-status"
      style={{
        position: 'absolute',
        [position.replace('top', 'top').replace('bottom', 'bottom').replace('left', 'left').replace('right', 'right')]: '10px',
        zIndex: 1000,
        padding: '6px 10px',
        background: 'rgba(255,255,255,0.95)',
        borderRadius: '4px',
        boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        fontSize: '12px',
        fontFamily: 'inherit',
        pointerEvents: 'none',
      }}
    >
      {loadingCount > 0 && (
        <span style={{ color: '#1890ff', marginRight: errorCount > 0 ? '8px' : 0 }}>
          Loading tree clusters… ({loadingCount})
        </span>
      )}
      {errorCount > 0 && (
        <span style={{ color: '#ff4d4f' }}>
          {errorCount} tile(s) failed — stale data shown
        </span>
      )}
    </div>
  );
}