import { recoverFromWorldView } from '../lib/mapZoom';
import { useEffect, useMemo, useState, useCallback } from 'react';
import { MapContainer, TileLayer, GeoJSON, Polyline, useMap, Pane, LayersControl } from 'react-leaflet';
import L from 'leaflet';
import type { Feature, FeatureCollection } from 'geojson';
import { useWorkspaceStore } from '../store/workspaceStore';
import type { WorkspaceState } from '../store/workspaceStore';
import { activityKindMarker, activityKindPathStyle } from '../lib/activityKinds';
import { buildFieldbookLines } from '../lib/fieldbookLines';
import { createFieldbookIcon, FIELDBOOK_INTERNAL_COLOR } from '../lib/fieldbookIcon';
import { FIELDBOOK_COLOR, getLayerStyle, getStyleForSubAreaCategory, getStyleForActivityFeature, stableUnitColor, defaultImportedLabelField, applyWorkingCircleStyle, resolveLayerStyle, resolveFeatureStyle, resolveRendererStyle, analysisUnitStyle, applyLayerAlpha, layerStyleKey, SUB_AREA_COLORS, type LayerStyle, type CustomLayerStyle, type FeatureStyleOverride } from '../lib/layerStyles';
import { rendererColorFor, type RendererSpec } from '../lib/layerRenderers';
import { isProbing, registerStyleResolvers } from '../lib/layerSymbology';
import { analysisHoverFact, compareFact, hoverFactHtml } from '../lib/analysisHover';
import { UnitFactsCard } from './map/UnitFactsCard';
import { chartSlug, resolveAnalysisRenderer, isFiMap, isUnitLayerId, isSfmMap, isHazardMap, isDotsMap, dotsKind, hazardLayerKey, analysisLabelLine } from '../lib/analysisMaps';
import { HouseholdDotsLayer } from './map/HouseholdDotsLayer';
import { useHazardHouseholds } from '../hooks/useHazardHouseholds';
import { useHazardUnits } from '../hooks/useHazardUnits';
import { useSettledColours } from '../hooks/useSettledColours';
import { useFieldGlyphs } from '../hooks/useFieldGlyphs';
import { useFieldInventoryUnits, useUnitAnalysis, useUnitMapSync } from '../hooks/useUnitMap';
import { FieldGlyphLayer } from './map/FieldGlyphLayer';
import {
  getLayerConfig,
  SLOPE_BAND_LABEL, ASPECT_LABEL, CANOPY_CLASS_LABEL, ESA_LANDCOVER_LABEL, FOREST_HEALTH_LABEL,
} from '../lib/layerRegistry';
import { StemMappingClusters } from './map/StemMappingClusters';
import { MapGrid } from './MapGrid';
import { MapNorthArrow } from './MapNorthArrow';
import { MapScaleBar } from './MapScaleBar';
import { getFeatureEmoji } from '../lib/pointSymbols';
import { purposeLeafletStyle, purposePointToLayer } from '../lib/purposeStyleMap';
import { createFreshPointIcon } from '../lib/pointIcons';
import { getTouchGeomanOptions } from '../lib/touchGeometry';
import { MapController } from './MapController';
import { MapApiProvider, type MapApi } from './MapApiContext';
import { registerFeatureLayer } from '../lib/featureLayerRegistry';
import { useTileToken, withTileToken } from '../hooks/useTileToken';
import { useT } from '../i18n/hooks';
import i18n from '../i18n';
import { sfmApi, type SfmBlockTypeInfo } from '../services/api';
import { useSfmBlockTypes } from '../hooks/useSfmBlockTypes';
import { escapeHtml, loadForestTypes, typeCardHtml } from '../lib/sfmForestTypes';
import { buildRasterTileUrl } from '../lib/rasterLegends';
import { autoBlockFeatureStyle, defaultLabelField } from '../lib/autoBlockLayerStyles';
import { UserGroupPoiOverlays } from './UserGroupPoiOverlays';

// The workspace map's own zoom ceiling. Base-map tile providers stop having
// real imagery well before this (OSM/Esri/Carto top out at z19, OpenTopoMap
// at z17 — see BASE_MAP_OPTIONS) — but this map is a digitizing surface, not
// a basemap viewer: sub-areas, blocks and individual trees are vectors with
// no native-resolution ceiling of their own, and detailed digitizing (e.g.
// placing/editing a single tree point) needs to zoom in past whatever the
// raster happens to support. Past a provider's own maxZoom the basemap just
// gets Leaflet's normal upscaled/blurry overzoom -- the same tradeoff every
// GIS desktop tool makes -- rather than the whole map silently refusing to
// zoom in any further.
const WORKSPACE_MAX_ZOOM = 22;

const SELECTED_STYLE: L.PathOptions = {
  fillColor: '#FFD700',
  fillOpacity: 0.5,
  color: '#FF8C00',
  weight: 3,
  dashArray: undefined,
};

/** Phase G — numbered divIcon for Sample Plot points (amber ring = legacy parity).
 *  Owner report 2026-10-02: selecting a point (map click or its attribute-table
 *  row) never showed ANY selection colour, unlike a polygon feature -- because
 *  `applySelection`/`SELECTED_STYLE` only ever touches `L.PathOptions`
 *  (stroke/fill), which a Marker's own divIcon never reads. `isSelected` swaps
 *  this icon to the same gold/orange pair `SELECTED_STYLE` uses for every
 *  other layer, with a thicker ring, while keeping the plot number visible
 *  exactly where it always was. */
function createSamplePlotIcon(plotNumber: number | null, isSelected = false) {
  return L.divIcon({
    className: 'custom-sample-plot-marker',
    html: `
      <div style="
        background-color: ${isSelected ? '#FF8C00' : '#fbbf24'};
        width: 18px;
        height: 18px;
        border-radius: 50%;
        border: ${isSelected ? '3px solid #FFD700' : '2px solid #fff'};
        box-shadow: ${isSelected ? '0 0 0 2px rgba(255,140,0,0.4), 0 1px 4px rgba(0,0,0,0.6)' : '0 1px 3px rgba(0,0,0,0.5)'};
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        color: #1f2937;
        font-size: 9px;
        line-height: 1;
        font-family: 'Noto Sans Devanagari', 'Nirmala UI', 'Mangal', Arial, sans-serif;
        text-shadow: 0 0 1px rgba(255,255,255,0.6);
      ">
        ${plotNumber ?? ''}
      </div>
    `,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -9],
  });
}

function getFeatureId(feature: Feature): string | undefined {
  // A raster/Auto-Block feature (`layer_features()`, auto_block_service.py)
  // carries its id at the GeoJSON Feature's own top-level `id`, not inside
  // `properties` -- every built-in/imported feature puts it in `properties`.
  // Without this fallback, a raster feature's id was always undefined here,
  // so its click handler bailed out silently and it could never be selected.
  return feature.properties?.id || feature.properties?.featureId || (feature as any).id;
}

/** True while a pure "draw new geometry" tool is armed. These are the tools
 *  where an existing feature must never intercept a click at all -- not for
 *  selection, not for hit-testing -- because the whole point is to draw
 *  regardless of what's underneath (see `interactive` on every registry
 *  GeoJSON layer in MapCanvas below). Deliberately NOT split/merge/move/
 *  vertex_edit/subarea_category, whose interaction model is clicking
 *  existing features on purpose. */
function isDigitizingToolbarMode(toolbarMode: unknown): boolean {
  return toolbarMode === 'draw_polygon' || toolbarMode === 'draw_point' || toolbarMode === 'draw_line';
}

export { isDigitizingToolbarMode };

/** Owner directive 2026-10-02: the layer panel is the only way to arm a layer
 *  for selection — a click on a feature whose layer isn't already active must
 *  be a no-op, never an implicit activation. Mirrors the three mutually
 *  exclusive "active layer" fields the store already keeps (builtin /
 *  imported / raster); there is deliberately no fourth combined field. */
function isLayerActiveForSelection(store: WorkspaceState, layerId: string): boolean {
  if (layerId.startsWith('raster:')) {
    return store.activeRasterLayerId === layerId.slice('raster:'.length);
  }
  if (layerId.startsWith('imported:')) {
    const importedId = Number(layerId.slice('imported:'.length));
    return !Number.isNaN(importedId) && store.activeImportedLayerId === importedId;
  }
  return store.activeLayerId === layerId;
}

export { isLayerActiveForSelection };

function makeClickHandler(layerId: string) {
  return (e: L.LeafletMouseEvent) => {
    // Read the LIVE store, never a snapshot captured when this feature's layer
    // last mounted. The built-in GeoJSON layers are NOT remounted every time
    // the toolbar mode changes, so a click handler bound while `toolbarMode`
    // was null (the normal case) would otherwise still believe no tool is
    // armed — and on a click during a draw gesture it would fire
    // selectFeatures() AND L.DomEvent.stopPropagation(), which (a) selects
    // whatever feature sits under the cursor and (b) eats the click before it
    // reaches the map, so Geoman never places the vertex. That is exactly the
    // "can only digitize where no other layer is visible" bug: over empty
    // space there is no feature to intercept, so it works; over a rendered
    // feature it silently blocks. `useWorkspaceStore.getState()` here matches
    // what MapEventCapture's background-click handler already does.
    const store = useWorkspaceStore.getState();
    // While a map-draw/gesture tool is running (e.g. split cut-line), clicking
    // on a feature must NOT touch selection: every selectFeatures() call
    // dispatches a NEW selection object, which tears down + re-arms the tool
    // effect mid-gesture and wipes the partially drawn line. Only pure
    // select / vertex_edit modes mutate selection on feature click.
    if (store.toolbarMode === 'split' || store.toolbarMode === 'merge'
      || store.toolbarMode === 'move'
      || isDigitizingToolbarMode(store.toolbarMode) || store.toolbarMode === 'subarea_category') {
      return;
    }
    const target = e.target as any;
    const feat = target.feature as Feature;
    if (!feat) return;
    const fid = getFeatureId(feat);
    if (!fid) return;
    const fidString = String(fid);
    // Owner directive 2026-10-02: no more click-to-activate. A feature is only
    // selectable when the user has already armed its layer from the layer
    // panel -- clicking a feature on any other layer is a no-op, guarding
    // against accidentally selecting/editing the wrong layer's features.
    if (!isLayerActiveForSelection(store, layerId)) {
      return;
    }
    if (e.originalEvent.ctrlKey || e.originalEvent.metaKey) {
      store.toggleFeatureSelection(layerId, fidString);
    } else {
      store.selectFeatures(layerId, [fidString]);
    }
    // Stop the click from bubbling to the map's background handler, which would
    // immediately clear the selection we just made.
    L.DomEvent.stopPropagation(e);
  };
}

export { makeClickHandler };

/** The layers whose features are units the SFM tab classifies. */
const SFM_UNIT_LAYERS = new Set(['blocks', 'sub_blocks', 'compartments', 'sub_compartments']);

/**
 * Hover over a classified unit: a card with the type's name (both languages), orientation, harvest steps and, for
 * this unit, why it was classified so (or that the user changed it). A tooltip, so it never takes the click: clicking
 * still selects the feature.
 */
function attachTypeHover(layer: L.Layer, blockName: string, info: SfmBlockTypeInfo) {
  let tip: L.Tooltip | null = null;
  let hovering = false;
  const ne = String(i18n.language || '').startsWith('ne');
  const reasons = String((ne ? info.reasons_ne : info.reasons_en) || '')
    .split(' · ')
    .map((s) => s.trim())
    .filter(Boolean);
  layer.on({
    mouseover: (e: L.LeafletMouseEvent) => {
      hovering = true;
      const map = (layer as unknown as { _map?: L.Map })._map;
      if (!map) return;
      loadForestTypes(() => sfmApi.getForestTypes())
        .then((types) => {
          const p = info.type_no != null ? types[info.type_no] : undefined;
          if (!p || !hovering) return; // unknown type, or the pointer already left
          tip = L.tooltip({ sticky: true, direction: 'right', className: 'sfm-hover-card', opacity: 1, offset: [14, 0] })
            .setLatLng(e.latlng)
            .setContent(typeCardHtml(p, { ...info, type_no: p.type_no, reasons }, blockName, (k: string, o?: unknown) => i18n.t(k, o as never)));
          tip.addTo(map);
        })
        .catch(() => undefined); // reference data unavailable: the label alone still shows
    },
    mousemove: (e: L.LeafletMouseEvent) => {
      tip?.setLatLng(e.latlng);
    },
    mouseout: () => {
      hovering = false;
      if (tip) {
        tip.remove();
        tip = null;
      }
    },
  });
}

/** The app's translator as a plain function (what the pure label / hover helpers take). */
const tr = (k: string, o?: Record<string, unknown>): string => String(i18n.t(k, o as never));

/** A tooltip that follows the pointer over a unit — the card with the unit's class and value for the active analysis map. */
function attachFactHover(layer: L.Layer, html: string) {
  let tip: L.Tooltip | null = null;
  layer.on({
    mouseover: (e: L.LeafletMouseEvent) => {
      const map = (layer as unknown as { _map?: L.Map })._map;
      if (!map) return;
      tip = L.tooltip({ sticky: true, direction: 'right', className: 'sfm-hover-card', opacity: 1, offset: [14, 0] }).setLatLng(e.latlng).setContent(html);
      tip.addTo(map);
    },
    mousemove: (e: L.LeafletMouseEvent) => tip?.setLatLng(e.latlng),
    mouseout: () => {
      tip?.remove();
      tip = null;
    },
  });
}

function makeOnEachFeature(
  layerId: string,
  showLabels: boolean,
  store: WorkspaceState,
) {
  return (feature: Feature, layer: L.Layer) => {
    const customField = store.builtinLabelField[layerId] ?? null;
    const text = customField
      ? getLabelTextForImported(feature, customField)
      : getLabelText(feature, layerId);
    const perLayer = store.layerLabelsVisible[layerId] !== false;
    // A unit the SFM tab has classified: say its forest type on the map ("Block-1 / Type-7") and on hover
    const sfm = SFM_UNIT_LAYERS.has(layerId) ? store.sfmBlockTypes?.[String(feature.properties?.name ?? '')] : undefined;
    // an analysis map on: the unit's label carries that map's main summary (same line as the print map)
    const summary = SFM_UNIT_LAYERS.has(layerId) && !customField
      ? analysisLabelLine(store.activeAnalysisMap, (feature.properties ?? {}) as Record<string, unknown>, i18n.language, tr)
      : null;
    if (summary) {
      createLabelTooltip(layer, `${escapeHtml(text)}<br/>${escapeHtml(summary)}`, showLabels && perLayer);
    } else if (sfm && !customField) {
      // "Type-7", or what the block is when it has no type: "Non-forest" / "No plots"
      const second =
        sfm.type_no != null
          ? i18n.t('sfm.ref.typeDash', { n: sfm.type_no })
          : i18n.t(sfm.state === 'non_forest' ? 'sfm.state.nonForest' : 'sfm.state.noPlots');
      createLabelTooltip(layer, `${escapeHtml(text)}<br/>${escapeHtml(second)}`, showLabels && perLayer);
    } else {
      createLabelTooltip(layer, text, showLabels && perLayer);
    }
    // hover: while an analysis map is on, the card says what the legend says for THIS unit (class + value); otherwise the
    // forest-type card. One switch ("Hover info") turns both off.
    const fact = store.showHoverInfo && SFM_UNIT_LAYERS.has(layerId) && store.activeAnalysisMap
      ? analysisHoverFact(store.activeAnalysisMap, (feature.properties ?? {}) as Record<string, unknown>, {
          lang: i18n.language,
          t: tr,
          saved: store.layerRenderers as Record<string, RendererSpec | undefined>,
          unitLegend: store.unitMap && store.unitMap.state === 'ready' ? store.unitMap.legend : undefined,
        })
      : null;
    // the unit layer this feature belongs to: what lets "zoom to / select these units" find it by name
    if (SFM_UNIT_LAYERS.has(layerId)) (layer as unknown as { __unitLayerId?: string }).__unitLayerId = layerId;
    if (fact) {
      const props = (feature.properties ?? {}) as Record<string, unknown>;
      const second = store.compareMap
        ? compareFact(store.compareMap, props, { lang: i18n.language, t: tr, saved: store.layerRenderers as Record<string, RendererSpec | undefined> })
        : null;
      attachFactHover(layer, hoverFactHtml(String(feature.properties?.name ?? ''), fact, second));
    }
    else if (store.showHoverInfo && sfm && sfm.type_no != null) attachTypeHover(layer, String(feature.properties?.name ?? ''), sfm);
    layer.on({ click: makeClickHandler(layerId) });
    // Exploring (an analysis map or chart is on): a click opens the unit's card — WITHOUT needing its layer armed in the panel,
    // because looking at a unit is not editing it. It runs after makeClickHandler, so an armed layer is selected first.
    if (SFM_UNIT_LAYERS.has(layerId)) {
      layer.on({
        click: (e: L.LeafletMouseEvent) => {
          const s = useWorkspaceStore.getState();
          if (!s.activeAnalysisMap && !s.activeChart) return;
          if (s.toolbarMode === 'split' || s.toolbarMode === 'merge' || s.toolbarMode === 'move' || isDigitizingToolbarMode(s.toolbarMode) || s.toolbarMode === 'subarea_category') return;
          const fid = getFeatureId(feature);
          if (!fid) return;
          if (!isLayerActiveForSelection(s, layerId)) s.clearSelection(); // as before: a click on an unarmed layer clears the selection
          s.setInspectedUnit({ layerId, id: String(fid) });
          L.DomEvent.stopPropagation(e); // the map's background click would otherwise close the card at once
        },
      });
    }
    registerFeatureLayer(feature, layer);
  };
}

interface MapCanvasProps {
  onMapReady: (map: L.Map) => void;
  boundaryFeatures: Feature[] | null;
  userGroupFeatures?: Feature[] | null;
  blockFeatures: Feature[] | null;
  subBlockFeatures?: Feature[] | null;
  compartmentFeatures: Feature[] | null;
  subCompartmentFeatures: Feature[] | null;
  subAreaFeatures: Feature[] | null;
  activityFeatures: Feature[] | null;
  samplePlotFeatures: Feature[] | null;
  fieldbookFeatures?: Feature[] | null;
  onSubAreaCreated?: (feature: Feature) => void;
  // Owner report 2026-10-02 (rules 1/2/4): dragging a Sample Plot marker
  // reports the gesture up rather than calling the API itself -- keeps
  // MapCanvas pure rendering, same as every other cross-cutting mutation
  // (onSubAreaCreated above). `revert` snaps the marker back to where it
  // was if the move is rejected (outside the boundary, or field inventory
  // data already exists for this forest).
  onSamplePlotMoved?: (feature: Feature, lng: number, lat: number, revert: () => void) => void;
}

function MapEventCapture({ onMapReady }: { onMapReady: (map: L.Map) => void }) {
  const map = useMap();
  const store = useWorkspaceStore();
  const digitizeCtx = store.activeDigitizeContext;
  const toolbarMode = store.toolbarMode;

  useEffect(() => {
    onMapReady(map);
    const container = map.getContainer();
    // Crosshair whenever an editing/drawing tool is armed (digitize context or
    // a geometry-editor tool: split/merge/move/draw/vertex/category), so the
    // pointer reads as "ready to edit" — normal arrow otherwise.
    const editing =
      !!digitizeCtx ||
      (toolbarMode !== null && toolbarMode !== 'select');
    if (editing) {
      container.style.cursor = 'crosshair';
      container.focus();
    } else {
      container.style.cursor = '';
    }

    let timer: number | undefined;
    // After a resize (the panel being shown again), a map that is sitting on the globe -- whatever put it there -- goes to Nepal's
    // extent. A fit that was waiting for the map to become visible has already run by then (it runs inside invalidateSize).
    const refresh = () => {
      map.invalidateSize();
      recoverFromWorldView(map);
    };
    const settle = window.setTimeout(refresh, 120);
    const ro = new ResizeObserver(() => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(refresh, 150);
    });
    ro.observe(container);
    return () => {
      ro.disconnect();
      window.clearTimeout(settle);
      if (timer) window.clearTimeout(timer);
    };
  }, [map, onMapReady, digitizeCtx, toolbarMode]);

  // Click empty map → clear the selection (QGIS-style). A click that hits a
  // feature calls L.DomEvent.stopPropagation, so it never reaches here.
  useEffect(() => {
    const onBgClick = () => {
      const s = useWorkspaceStore.getState();
      if (s.activeDigitizeContext) return;
      if (s.toolbarMode && s.toolbarMode !== 'select') return;
      if (s.selection.featureIds.length || s.selectedFeatureId) {
        s.clearSelection();
        s.selectFeatureGlobal(null);
      }
    };
    map.on('click', onBgClick);
    return () => {
      map.off('click', onBgClick);
    };
  }, [map]);

  return null;
}

function getLabelText(feature: Feature, layerId: string): string {
  if (layerId === 'boundary') return feature.properties?.name || 'Forest Boundary';
  if (layerId === 'user_group') return feature.properties?.name || 'User Group Boundary';
  // A protection-working-circle unit is felling-free: mark its map label with a
  // shield so it reads as protected even before the legend is consulted.
  const wc = feature.properties?.working_circle === 'protection' ? '🛡 ' : '';
  if (layerId === 'blocks') return wc + (feature.properties?.name || `Block ${feature.properties?.id || ''}`);
  if (layerId === 'sub_blocks') return wc + (feature.properties?.name || `Sub-Block ${feature.properties?.id || ''}`);
  if (layerId === 'compartments') return wc + (feature.properties?.name || feature.properties?.compartment_code || `Compartment ${feature.properties?.id || ''}`);
  if (layerId === 'sub_compartments') return wc + (feature.properties?.name || feature.properties?.compartment_code || `Sub-Compartment ${feature.properties?.id || ''}`);
  if (layerId === 'sub_areas') return feature.properties?.name || feature.properties?.category || 'Sub-Area';
  if (layerId === 'activity_features') return feature.properties?.display_label || feature.properties?.name || 'Activity';
  return '';
}

function createLabelTooltip(layer: L.Layer, labelText: string, showLabels: boolean) {
  if (!showLabels || !labelText) return;
  
  const tooltip = L.tooltip({
    permanent: true,
    direction: 'center',
    className: 'feature-label',
    offset: [0, 0],
    opacity: 0.95,
    sticky: true,
  }).setContent(labelText);
  
  layer.bindTooltip(tooltip);
}

// Auto-Block source classification fields (SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN
// follow-on) store an integer code — the map label should read the same
// human-readable band/direction/class the attribute table shows (e.g. "31–45°"),
// not the raw code, when a user picks one of these as the label field.
const CODE_LABEL_LOOKUP: Partial<Record<string, Record<number, string>>> = {
  dominant_slope_band: SLOPE_BAND_LABEL,
  dominant_aspect: ASPECT_LABEL,
  dominant_canopy_class: CANOPY_CLASS_LABEL,
  dominant_landcover: ESA_LANDCOVER_LABEL,
  dominant_health_class: FOREST_HEALTH_LABEL,
};

function getLabelTextForImported(
  feature: Feature,
  labelField: string | null | undefined,
): string {
  if (!labelField) return '';
  const val = feature.properties?.[labelField];
  if (val === null || val === undefined) return '';
  const lookup = CODE_LABEL_LOOKUP[labelField];
  if (lookup && typeof val === 'number') return lookup[val] ?? String(val);
  return String(val);
}

function getLabelDirection(geoType: string): string {
  switch (geoType) {
    case 'Point':
    case 'MultiPoint':
      return 'bottom';
    case 'LineString':
    case 'MultiLineString':
      return 'center';
    case 'Polygon':
    case 'MultiPolygon':
      return 'center';
    default:
      return 'center';
  }
}

function createLabelTooltipForImported(
  layer: L.Layer,
  labelText: string,
  showLabels: boolean,
  geometryType: string,
) {
  if (!showLabels || !labelText) return;

  const direction = getLabelDirection(geometryType);
  const offset = direction === 'bottom' ? [0, 15] : [0, 0];

  const tooltip = L.tooltip({
    permanent: true,
    direction: direction as any,
    className: 'feature-label imported-feature-label',
    offset: offset as L.PointExpression,
    opacity: 0.8,
    sticky: geometryType === 'Polygon' || geometryType === 'MultiPolygon',
  }).setContent(labelText);

  layer.bindTooltip(tooltip);
}

export function MapCanvas({ onMapReady, boundaryFeatures, userGroupFeatures, blockFeatures, subBlockFeatures, compartmentFeatures, subCompartmentFeatures, subAreaFeatures, activityFeatures, samplePlotFeatures, fieldbookFeatures, onSubAreaCreated, onSamplePlotMoved }: MapCanvasProps) {
  const store = useWorkspaceStore();
  const t = useT();
  const tileToken = useTileToken(store.calculationId);
  useSfmBlockTypes(store.calculationId, store.geometryVersion);
  useHazardUnits(store.calculationId, store.geometryVersion);
  const dotsActive = isDotsMap(store.activeAnalysisMap);
  // the server draws hazard tiles from the colours it has SAVED: re-key them only once the user's change has reached it
  const tileColourVersion = useSettledColours(store.activeAnalysisMap);
  // field inventory: the active single-number map's per-unit colours (the server paints them) and the raw numbers for the table
  useUnitMapSync(store.calculationId, store.activeAnalysisMap, store.geometryVersion, tileColourVersion);
  useFieldInventoryUnits(store.calculationId, store.geometryVersion);
  useUnitAnalysis(store.calculationId, store.geometryVersion);
  const glyphs = useFieldGlyphs(store.calculationId, chartSlug(store.activeChart), store.geometryVersion, useSettledColours(store.activeChart));
  const dots = useHazardHouseholds(
    store.calculationId, dotsActive ? dotsKind(store.activeAnalysisMap!) : null, store.analysisArea, store.geometryVersion,
  );
  // changes whenever any unit's type does, so the unit layers redraw their labels and hover cards
  const hazardKey = Object.entries(store.hazardUnits ?? {})
    .map(([k, v]) => `${k}:${v.soil?.mean}:${v.lsi?.dominant.index}:${v.fs?.unsafe_pct}:${v.prone?.high_pct}`)
    .join('|');
  const fiUnitsKey = `${Object.keys(store.fieldInventoryUnits ?? {}).length}`;
  const unitMapKey = store.unitMap && store.unitMap.state === 'ready'
    ? Object.entries(store.unitMap.units).map(([k, v]) => `${k}:${v.color}:${v.text}`).join('|') : '';
  const sfmKey = `${store.activeAnalysisMap ?? ''}>${store.compareMap ?? ''}>f${fiUnitsKey}#${unitMapKey.length}:${unitMapKey.split('').reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7)}#${store.showHoverInfo ? 'h' : 'n'}#${hazardKey}#` + Object.entries(store.sfmBlockTypes ?? {})
    .map(([k, v]) => `${k}:${v.type_no}:${v.state}:${v.orientation}:${v.gs_ge40_m3_per_ha}:${v.slope_band}`)
    .join('|');
  const activeBaseMap = store.activeBaseMap;
  const baseMapOptions = store.baseMapOptions;
  const activeOption = baseMapOptions.find((o) => o.id === activeBaseMap) || baseMapOptions[0];
  const showLabels = store.showLabels;
  const selection = store.selection;
  const importedLayers = store.importedLayers;

  // A digitizing tool (drawing brand-new geometry) must be able to draw
  // ANYWHERE, regardless of what other layers happen to be visible
  // underneath, and must never pick up a click as "select this feature"
  // instead of "place a vertex here". Leaflet Markers default to
  // bubblingMouseEvents: false — a click on an existing point feature (Sample
  // Plots, point-purpose imported layers, point Activity Features) never even
  // reaches the map's own click handler that Geoman listens on, so drawing is
  // silently blocked wherever an existing point sits, but works fine over
  // empty space or wherever that layer is unchecked (not rendered at all).
  // `interactive={false}` here is the general fix: no existing feature layer
  // (marker OR polygon/line path) can intercept clicks or receive hover/click
  // while a draw tool is armed, so behavior is identical whether the layer
  // underneath is checked or unchecked, and selection can never fire during
  // a draw gesture. Deliberately NOT applied to split/merge/move/vertex_edit
  // — those tools' whole interaction model is clicking existing features.
  const isDigitizing = isDigitizingToolbarMode(store.toolbarMode);

  // react-leaflet v5's GeoJSON updater only ever re-applies `style` (see the
  // `key` comment further down) — a changed `interactive` prop is silently
  // ignored on an already-mounted layer. So `interactive={!isDigitizing}`
  // alone never takes effect when you *enter* a draw tool with layers already
  // on screen. Folding this token into every built-in layer key remounts them
  // when the draw tool arms/disarms, so the fresh Leaflet layer is built with
  // the right `interactive` value (and markers with bubblingMouseEvents:false
  // stop swallowing the draw click).
  const digitizeKey = isDigitizing ? 'd1' : 'd0';

  // MapApi state published to context
  const [mapApi, setMapApi] = useState<MapApi | null>(null);

  const handleMapReady = useCallback((api: MapApi | null) => {
    setMapApi(api);
  }, [onMapReady]);

  const isSelected = (feature?: Feature): boolean => {
    if (isProbing()) return false; // an export asking for a layer's look wants the layer's style, not the highlight
    if (!feature || !selection.layerId) return false;
    const fid = getFeatureId(feature);
    return !!fid && selection.featureIds.includes(fid);
  };

  const applySelection = (style: L.PathOptions, feature?: Feature): L.PathOptions => {
    if (!isSelected(feature)) return style;
    return { ...style, ...SELECTED_STYLE };
  };

  // A built-in layer's user-chosen style (right-click → Style Layer), scoped to
  // this calculation. `resolveLayerStyle` returns the base by reference when
  // there is nothing to apply, so the no-override path is unchanged.
  const customFor = (layerId: string): CustomLayerStyle | undefined =>
    store.customLayerStyles[layerStyleKey(layerId, 'builtin', store.calculationId)] as unknown as CustomLayerStyle | undefined;

  // The nullable per-feature `style` override carried on a unit / sub-area row
  // (P3). Applied above the custom layer style + working-circle treatment;
  // selection still wins on top.
  const featureOverride = (feature?: Feature): FeatureStyleOverride | undefined =>
    (feature?.properties?.style as FeatureStyleOverride | null | undefined) ?? undefined;

  // P4 — a thematic renderer (categorized / graduated) for this layer, keyed by
  // bare layer id. Its per-feature colour sits above the custom layer style +
  // palette, below the per-feature `style` override.
  const rendererColour = (bareKey: string, feature?: Feature): string | null => {
    // An active SFM analysis map colours every unit layer (the user's own colours for it, else the system default);
    // a unit the SFM tab has not classified reads neutral grey, never "no colour".
    if (isFiMap(store.activeAnalysisMap) && isUnitLayerId(bareKey)) {
      // the server's colour for this unit (the print renderer's own); a unit with no inventory summary reads neutral grey
      return (feature?.properties?.um_color as string | undefined) ?? '#bdbdbd';
    }
    if (isSfmMap(store.activeAnalysisMap) && isUnitLayerId(bareKey)) {
      const aSpec = resolveAnalysisRenderer(store.activeAnalysisMap, store.layerRenderers as Record<string, RendererSpec | undefined>);
      if (!aSpec || !feature) return null;
      return rendererColorFor(aSpec, feature.properties?.[aSpec.field]) ?? '#bdbdbd';
    }
    const spec = store.layerRenderers[bareKey] as RendererSpec | undefined;
    if (!spec || !feature) return null;
    return rendererColorFor(spec, feature.properties?.[spec.field]);
  };

  // P5.2 — multiply the resolved style by the layer's whole-layer alpha before
  // the selection highlight (which must stay fully opaque).
  const withAlpha = (layerId: string, style: L.PathOptions): L.PathOptions =>
    applyLayerAlpha(style as LayerStyle, store.layerAlpha[layerStyleKey(layerId, 'builtin', store.calculationId)]) as L.PathOptions;

  const boundaryStyle = (feature?: Feature) => applySelection(
    withAlpha('boundary', resolveLayerStyle({ base: (getLayerStyle('forest_boundary') as LayerStyle) || {}, custom: customFor('boundary') }) as L.PathOptions),
    feature,
  );
  const userGroupStyle = (feature?: Feature) => {
    const base = (getLayerStyle('user_group') as LayerStyle) || {};
    // A machine-generated ring (auto-buffer) reads as dotted; a drawn / imported
    // catchment keeps the default dash. USER_GROUP_BOUNDARY_PLAN.md P5.
    const withSource = feature?.properties?.source_type === 'auto_buffer' ? { ...base, dashArray: '2, 5' } : base;
    return applySelection(withAlpha('user_group', resolveLayerStyle({ base: withSource, custom: customFor('user_group') }) as L.PathOptions), feature);
  };
  // a class isolated from the legend: every unit of another class fades, so the chosen one stands out
  const dimmed = (style: L.PathOptions, bareKey: string, feature?: Feature): L.PathOptions => {
    const hl = store.analysisHighlight;
    if (!hl || !isUnitLayerId(bareKey)) return style;
    const c = rendererColour(bareKey, feature);
    return c && c.toLowerCase() === hl ? style : { ...style, fillOpacity: 0.05, opacity: 0.25 };
  };

  // A unit coloured by an analysis map keeps a dark outline (its boundary stays visible); any other thematic renderer paints the stroke
  // in the fill's colour as before.
  const unitThemedStyle = (wc: LayerStyle, bareKey: string, feature?: Feature): LayerStyle => {
    const colour = rendererColour(bareKey, feature);
    const analysisOn = (isSfmMap(store.activeAnalysisMap) || isFiMap(store.activeAnalysisMap)) && isUnitLayerId(bareKey);
    return analysisOn ? analysisUnitStyle(wc, colour) : resolveRendererStyle(wc, colour);
  };

  const blockStyle = (feature?: Feature) => {
    const base = (getLayerStyle('blocks') as LayerStyle) || {};
    const c = stableUnitColor(feature?.properties?.id as string | undefined);
    const resolved = resolveLayerStyle({ base, custom: customFor('blocks'), usesPalette: true, paletteColor: c });
    const wc = applyWorkingCircleStyle(resolved, feature?.properties?.working_circle);
    const themed = unitThemedStyle(wc, 'blocks', feature);
    return applySelection(dimmed(withAlpha('blocks', resolveFeatureStyle(themed, featureOverride(feature)) as L.PathOptions), 'blocks', feature), feature);
  };
  const subBlockStyle = (feature?: Feature) => {
    const base = (getLayerStyle('sub_blocks') as LayerStyle) || {};
    const c = stableUnitColor(feature?.properties?.id as string | undefined);
    const resolved = resolveLayerStyle({ base, custom: customFor('sub_blocks'), usesPalette: true, paletteColor: c });
    const wc = applyWorkingCircleStyle(resolved, feature?.properties?.working_circle);
    const themed = unitThemedStyle(wc, 'sub_blocks', feature);
    return applySelection(dimmed(withAlpha('sub_blocks', resolveFeatureStyle(themed, featureOverride(feature)) as L.PathOptions), 'sub_blocks', feature), feature);
  };
  const compartmentStyle = (feature?: Feature) => {
    const base = (getLayerStyle('compartments') as LayerStyle) || {};
    const c = stableUnitColor(feature?.properties?.id as string | undefined);
    const resolved = resolveLayerStyle({ base, custom: customFor('compartments'), usesPalette: true, paletteColor: c });
    const wc = applyWorkingCircleStyle(resolved, feature?.properties?.working_circle);
    const themed = unitThemedStyle(wc, 'compartments', feature);
    return applySelection(dimmed(withAlpha('compartments', resolveFeatureStyle(themed, featureOverride(feature)) as L.PathOptions), 'compartments', feature), feature);
  };
  const subCompartmentStyle = (feature?: Feature) => {
    const base = (getLayerStyle('sub_compartments') as LayerStyle) || {};
    const c = stableUnitColor(feature?.properties?.id as string | undefined);
    const resolved = resolveLayerStyle({ base, custom: customFor('sub_compartments'), usesPalette: true, paletteColor: c });
    const wc = applyWorkingCircleStyle(resolved, feature?.properties?.working_circle);
    const themed = unitThemedStyle(wc, 'sub_compartments', feature);
    return applySelection(dimmed(withAlpha('sub_compartments', resolveFeatureStyle(themed, featureOverride(feature)) as L.PathOptions), 'sub_compartments', feature), feature);
  };
  const subAreaStyle = (feature?: Feature) => {
    const cat = feature?.properties?.category;
    const base = (cat ? getStyleForSubAreaCategory(cat) : getLayerStyle('sub_areas_default')) as LayerStyle;
    const idx = feature?.properties?.colorIndex ?? 0;
    const paletteColor = SUB_AREA_COLORS[idx % SUB_AREA_COLORS.length];
    const resolved = resolveLayerStyle({ base, custom: customFor('sub_areas'), usesPalette: true, paletteColor });
    const themed = resolveRendererStyle(resolved, rendererColour('sub_areas', feature));
    return applySelection(
      withAlpha('sub_areas', resolveFeatureStyle(themed, featureOverride(feature)) as L.PathOptions),
      feature,
    );
  };
  const activityStyle = (feature?: Feature) => {
    if (!feature) return {};
    return applySelection(
      withAlpha('activity_features', resolveLayerStyle({
        // The feature's kind decides its symbol (nursery / road / plantation ...); a feature with
        // none keeps the generic per-geometry style.
        base: (activityKindPathStyle(feature.properties?.kind, feature.geometry.type) ?? getStyleForActivityFeature(feature.geometry.type)) as LayerStyle,
        custom: customFor('activity_features'),
      }) as L.PathOptions),
      feature,
    );
  };
  // Exports (KML / GeoPackage) ask for each feature's look through these, so a file carries exactly what the map draws.
  useEffect(() => {
    const resolvers: Record<string, (f: Feature) => any> = {
      boundary: boundaryStyle, user_group: userGroupStyle, blocks: blockStyle, sub_blocks: subBlockStyle,
      compartments: compartmentStyle, sub_compartments: subCompartmentStyle, sub_areas: subAreaStyle, activity_features: activityStyle,
    };
    for (const l of importedLayers) {
      const custom = store.customLayerStyles[layerStyleKey(String(l.id), 'imported', store.calculationId)];
      const base: any = custom ? custom : purposeLeafletStyle(l.purpose, Boolean(l.isDraft));
      const style = l.isDraft ? { ...base, opacity: (base.opacity ?? 1) * 0.7 } : base;
      resolvers[`imported:${l.id}`] = () => style;
    }
    registerStyleResolvers(resolvers);
  });
  const isVisible = (layerId: string) => store.layerVisibility[layerId] !== false;

  // The Field Book's lines: outer rings close into a polygon outline; internal edges stay open (lib/fieldbookLines.ts)
  const fieldbookLines = useMemo(() => buildFieldbookLines(fieldbookFeatures), [fieldbookFeatures]);
  const boundaryOnEachFeature = useMemo(() => makeOnEachFeature('boundary', showLabels, store), [showLabels, store.builtinLabelField, store.layerLabelsVisible]);
  const userGroupOnEachFeature = useMemo(() => makeOnEachFeature('user_group', showLabels, store), [showLabels, store.builtinLabelField, store.layerLabelsVisible]);
  const blocksOnEachFeature = useMemo(() => makeOnEachFeature('blocks', showLabels, store), [showLabels, store.builtinLabelField, store.layerLabelsVisible, store.sfmBlockTypes, store.activeAnalysisMap, store.hazardUnits, store.showHoverInfo, store.unitMap, store.layerRenderers, store.compareMap]);
  const subBlocksOnEachFeature = useMemo(() => makeOnEachFeature('sub_blocks', showLabels, store), [showLabels, store.builtinLabelField, store.layerLabelsVisible, store.sfmBlockTypes, store.activeAnalysisMap, store.hazardUnits, store.showHoverInfo, store.unitMap, store.layerRenderers, store.compareMap]);
  const compartmentsOnEachFeature = useMemo(() => makeOnEachFeature('compartments', showLabels, store), [showLabels, store.builtinLabelField, store.layerLabelsVisible, store.sfmBlockTypes, store.activeAnalysisMap, store.hazardUnits, store.showHoverInfo, store.unitMap, store.layerRenderers, store.compareMap]);
  const subCompartmentsOnEachFeature = useMemo(() => makeOnEachFeature('sub_compartments', showLabels, store), [showLabels, store.builtinLabelField, store.layerLabelsVisible, store.sfmBlockTypes, store.activeAnalysisMap, store.hazardUnits, store.showHoverInfo, store.unitMap, store.layerRenderers, store.compareMap]);
  const subAreasOnEachFeature = useMemo(() => makeOnEachFeature('sub_areas', showLabels, store), [showLabels, store.builtinLabelField, store.layerLabelsVisible]);
  const activityOnEachFeature = useMemo(() => makeOnEachFeature('activity_features', showLabels, store), [showLabels, store.builtinLabelField, store.layerLabelsVisible]);
  const importedOnEachFeatures = useMemo(() => {
    const result: Record<number, (feature: Feature, layer: L.Layer) => void> = {};
    for (const l of importedLayers) {
      // Explicit user choice always wins; only fall back to an auto-pick
      // when nothing has been chosen yet (store.labelField[l.id] is
      // null/undefined) — a user who deliberately wants no label would
      // have no way to express that otherwise.
      const labelField = store.labelField[l.id]
        ?? defaultImportedLabelField(store.importedLayerFeatures[l.id] ?? []);
      const perLayerVisible = store.layerLabelsVisible[String(l.id)] !== false;
      const show = showLabels && perLayerVisible && !!labelField;
      result[l.id] = (feature: Feature, layer: L.Layer) => {
        const text = getLabelTextForImported(feature, labelField);
        createLabelTooltipForImported(layer, text, show, feature.geometry.type);
        // `imported:<id>` matches AttributeTable's own `selectionKey` and the
        // documented `?feature=` convention (dockSurface.ts) -- a bare id here
        // would never match the table's prefixed key and the two would select
        // under different identities.
        layer.on({ click: makeClickHandler(`imported:${l.id}`) });
        registerFeatureLayer(feature, layer);
      };
    }
    return result;
  }, [importedLayers, store.labelField, store.importedLayerFeatures, showLabels, store.layerLabelsVisible]);

  const touchOptions = getTouchGeomanOptions();

  return (
    <MapApiProvider value={mapApi}>
      <div className={`map-canvas ${touchOptions.containerClass}`} style={{ height: '100%', width: '100%', position: 'relative' }}>
        <MapContainer
          center={[28.3949, 84.1240]}
          zoom={8}
          maxZoom={WORKSPACE_MAX_ZOOM}
          style={{ height: '100%', width: '100%' }}
          zoomControl={true}
          doubleClickZoom={touchOptions.doubleClickZoom}
        >
          <MapEventCapture onMapReady={onMapReady} />

          <MapController
            onReady={handleMapReady}
          />

          {activeOption.url && (
            <TileLayer
              url={activeOption.url}
              attribution={activeOption.attribution}
              maxNativeZoom={activeOption.maxZoom}
              maxZoom={WORKSPACE_MAX_ZOOM}
            />
          )}

        {/* react-leaflet v5's GeoJSON updater never re-applies the `data` prop
            (only `style`), so each built-in layer key must include the
            geometryVersion clock. Bumping it (after merge/split/delete/draw)
            remounts the layer with the freshly fetched features — otherwise the
            map stays visually stale until a manual page reload. */}

        {/* DRAW (z) ORDER IS THIS JSX ORDER. Every built-in layer shares
            Leaflet's default overlay pane — no `createPane`, no per-layer
            `zIndex` — so the element that comes last renders on top. This
            sequence therefore mirrors `LAYER_REGISTRY[].order`, which is what
            the layer panel renders, and it is kept in step with it deliberately:
            before, the panel's order came from a partly-seeded `layerOrder` map
            and disagreed with this list, so the panel and the map showed
            different stacks. If you add a layer, place it here in registry
            order too, or it will draw in a slot the panel does not show. */}
        {isVisible('boundary') && boundaryFeatures && (
          <GeoJSON
            key={`boundary-v${store.geometryVersion}-l${store.layerLoadKeys['boundary'] ?? 0}-${digitizeKey}`}
            data={{ type: 'FeatureCollection', features: boundaryFeatures } as any}
            style={boundaryStyle}
            interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
            onEachFeature={boundaryOnEachFeature}
          />
        )}

        {isVisible('user_group') && userGroupFeatures && userGroupFeatures.length > 0 && (
          <GeoJSON
            key={`user_group-v${store.geometryVersion}-l${store.layerLoadKeys['user_group'] ?? 0}-${digitizeKey}`}
            data={{ type: 'FeatureCollection', features: userGroupFeatures } as FeatureCollection}
            style={userGroupStyle}
            interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
            onEachFeature={userGroupOnEachFeature}
          />
        )}

        {isVisible('blocks') && blockFeatures && (
          <GeoJSON
            key={`blocks-v${store.geometryVersion}-l${store.layerLoadKeys['blocks'] ?? 0}-${digitizeKey}-s${sfmKey.length}-${sfmKey.split('').reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7)}`}
            data={{ type: 'FeatureCollection', features: blockFeatures } as any}
            style={blockStyle}
            interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
            onEachFeature={blocksOnEachFeature}
          />
        )}

        {isVisible('sub_blocks') && subBlockFeatures && (
          <GeoJSON
            key={`sub_blocks-v${store.geometryVersion}-l${store.layerLoadKeys['sub_blocks'] ?? 0}-${digitizeKey}-s${sfmKey.length}-${sfmKey.split('').reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7)}`}
            data={{ type: 'FeatureCollection', features: subBlockFeatures } as any}
            style={subBlockStyle}
            interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
            onEachFeature={subBlocksOnEachFeature}
          />
        )}

        {isVisible('compartments') && compartmentFeatures && (
          <GeoJSON
            key={`compartments-v${store.geometryVersion}-l${store.layerLoadKeys['compartments'] ?? 0}-${digitizeKey}-s${sfmKey.length}-${sfmKey.split('').reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7)}`}
            data={{ type: 'FeatureCollection', features: compartmentFeatures } as any}
            style={compartmentStyle}
            interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
            onEachFeature={compartmentsOnEachFeature}
          />
        )}

        {isVisible('sub_compartments') && subCompartmentFeatures && (
          <GeoJSON
            key={`sub_compartments-v${store.geometryVersion}-l${store.layerLoadKeys['sub_compartments'] ?? 0}-${digitizeKey}-s${sfmKey.length}-${sfmKey.split('').reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7)}`}
            data={{ type: 'FeatureCollection', features: subCompartmentFeatures } as any}
            style={subCompartmentStyle}
            interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
            onEachFeature={subCompartmentsOnEachFeature}
          />
        )}

        {isVisible('sub_areas') && subAreaFeatures && (
          <GeoJSON
            key={`sub_areas-v${store.geometryVersion}-l${store.layerLoadKeys['sub_areas'] ?? 0}-${digitizeKey}`}
            data={{ type: 'FeatureCollection', features: subAreaFeatures } as any}
            style={subAreaStyle}
            interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
            onEachFeature={subAreasOnEachFeature}
          />
        )}

        {isVisible('sample_plots') && samplePlotFeatures && (
          <GeoJSON
            // The selection signature is folded into the key (same forced-
            // remount pattern `digitizeKey` already uses here) so a marker's
            // divIcon -- which pointToLayer only ever builds once at mount,
            // unlike a path's `style` callback -- actually re-renders gold/
            // orange when this point becomes (or stops being) selected.
            key={`sample_plots-v${store.geometryVersion}-l${store.layerLoadKeys['sample_plots'] ?? 0}-${digitizeKey}-${selection.layerId === 'sample_plots' ? selection.featureIds.join(',') : ''}`}
            data={{ type: 'FeatureCollection', features: samplePlotFeatures } as any}
            interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
            pointToLayer={(feature, latlng) =>
              L.marker(latlng, {
                icon: createSamplePlotIcon(feature.properties?.plot_number ?? null, isSelected(feature)),
                interactive: !isDigitizing,
                // Owner report 2026-10-02 (rule 1), tightened same day: an
                // UNselected plot is draggable the instant you touch it --
                // "very dangerous... user may touch the point and it may be
                // dragged easily without knowing what he was doing." Require
                // a deliberate click-to-select FIRST (the same click that
                // already gold/orange-highlights it); only a selected plot
                // can be dragged. Selection state is folded into this
                // GeoJSON's own `key` above, so `draggable` is recomputed
                // correctly whenever selection changes.
                draggable: !isDigitizing && isSelected(feature),
              })
            }
            onEachFeature={(feature, layer: any) => {
              layer.on({ click: makeClickHandler('sample_plots') });
              registerFeatureLayer(feature, layer);
              const originalLatLng = layer.getLatLng();
              layer.on('dragend', () => {
                const next = layer.getLatLng();
                onSamplePlotMoved?.(feature, next.lng, next.lat, () => layer.setLatLng(originalLatLng));
              });
              // Same field set as the Sampling tab's own "Sampling Points"
              // table + map popup (SamplingMapView) -- SFM stratum is a
              // separate, block-level axis from zone_type (see that
              // component's comment); elevation/UTM/topo/distance-from-
              // boundary come from the enriched fetch in layerRegistry.ts and
              // are omitted here when not available for this forest.
              // Named `plotProps`, not `props` — eslint-plugin-react's
              // react/prop-types heuristic treats ANY variable literally named
              // `props` as a component's props and demands a validator for
              // every key read off it, even here where this is a plain Leaflet
              // callback (no JSX, not a component) building an HTML string.
              const plotProps = feature.properties || {};
              const stratumLabel: Record<string, string> = {
                production: t('sampling.stratumLabelProduction'),
                conservation: t('sampling.stratumLabelConservation'),
                protection: t('sampling.stratumLabelProtection'),
              };
              const coords = feature.geometry?.type === 'Point' ? feature.geometry.coordinates : null;
              const rows: string[] = [
                `<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.blockLabel')}</td><td class="text-gray-800">${plotProps.block_name || '-'}</td></tr>`,
                `<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.zoneHeader')}</td><td class="text-gray-800">${plotProps.zone_type === 'protected' ? t('sampling.protected') : t('sampling.productive')}</td></tr>`,
              ];
              if (plotProps.stratum) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.sfmStratumHeader')}</td><td class="text-gray-800">${stratumLabel[plotProps.stratum] ?? plotProps.stratum}</td></tr>`);
              }
              if (coords) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.longitudeHeader')}</td><td class="font-mono text-gray-800">${Number(coords[0]).toFixed(7)}</td></tr>`);
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.latitudeHeader')}</td><td class="font-mono text-gray-800">${Number(coords[1]).toFixed(7)}</td></tr>`);
              }
              if (plotProps.elevation_m != null) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.elevationHeader')}</td><td class="text-gray-800">${plotProps.elevation_m}m</td></tr>`);
              }
              if (plotProps.utm_easting != null) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.utmEastingHeader')}</td><td class="font-mono text-gray-800">${Number(plotProps.utm_easting).toFixed(2)}</td></tr>`);
              }
              if (plotProps.utm_northing != null) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.utmNorthingHeader')}</td><td class="font-mono text-gray-800">${Number(plotProps.utm_northing).toFixed(2)}</td></tr>`);
              }
              if (plotProps.utm_zone) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.utmZoneHeader')}</td><td class="text-gray-800">${plotProps.utm_zone}</td></tr>`);
              }
              if (plotProps.topographic_context) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.nearestRidgeValleyHeader')}</td><td class="text-gray-800">${plotProps.topographic_context}</td></tr>`);
              }
              if (plotProps.distance_from_boundary != null) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.distanceFromBoundaryHeader')}</td><td class="text-gray-800">${Number(plotProps.distance_from_boundary).toFixed(2)}m</td></tr>`);
              }
              layer.bindPopup(`
                <table class="text-sm min-w-[180px]">
                  <tbody>
                    <tr><td class="pr-2 text-gray-500 align-top">${t('sampling.plotNum')}</td><td class="font-semibold text-red-600">${plotProps.plot_number ?? ''}</td></tr>
                    ${rows.join('')}
                  </tbody>
                </table>
              `);
            }}
          />
        )}

        {/* Stem Mapping — one point per surveyed tree (read-only, like Sample
            Plots), but rendered through the U05/U06 viewport-tile-cluster
            pipeline rather than a flat GeoJSON of every tree: a forest's tree
            count can run into the thousands, where fetching + laying out that
            many individual circleMarkers up front made the layer unresponsive. */}
        <StemMappingClusters visible={isVisible('stem_mapping')} />

        {isVisible('activity_features') && activityFeatures && (
          <GeoJSON
            key={`activity_features-v${store.geometryVersion}-l${store.layerLoadKeys['activity_features'] ?? 0}-${digitizeKey}`}
            data={{ type: 'FeatureCollection', features: activityFeatures } as any}
            style={activityStyle}
            // Points were drawn with Leaflet's stock blue pin whatever the activity: a badge in the
            // kind's colour with its icon says what the point is.
            pointToLayer={(feature, latlng) => {
              const { html, size } = activityKindMarker(feature.properties?.kind);
              return L.marker(latlng, {
                icon: L.divIcon({ className: 'activity-kind-marker', html, iconSize: [size, size], iconAnchor: [size / 2, size / 2], popupAnchor: [0, -size / 2] }),
                interactive: !isDigitizing,
              });
            }}
            interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
            onEachFeature={activityOnEachFeature}
          />
        )}

        {/* Field Book — one point per walked boundary vertex/interpolated
            point (fieldbook_map_layer_plan.md). Sky-blue numbered marker (Sample
            Plots are amber); vertex vs interpolated get a filled/hollow
            distinction (E3, see createFieldbookIcon). Flat GeoJSON layer, not
            clustered (E4) -- fieldbook point counts are perimeter-bound
            (tens to low hundreds), not tree-density-bound. */}
        {isVisible('fieldbook') && fieldbookFeatures && fieldbookLines.map((line) => (
          // Outer ring: solid sky-blue and CLOSED (back to its first point), so it reads as the forest polygon.
          // Internal edge: dashed violet and OPEN -- never closed, never joined to another edge.
          <Polyline
            key={`fieldbook-line-${line.id}-v${store.geometryVersion}-l${store.layerLoadKeys['fieldbook'] ?? 0}`}
            positions={line.positions}
            interactive={false}
            pathOptions={
              line.kind === 'outer'
                ? { color: FIELDBOOK_COLOR, weight: 3, opacity: 0.9 }
                : { color: FIELDBOOK_INTERNAL_COLOR, weight: 2, opacity: 0.85, dashArray: '6 6' }
            }
          />
        ))}
        {isVisible('fieldbook') && fieldbookFeatures && (
          <GeoJSON
            // See the matching comment on the sample_plots key above -- same
            // forced-remount reason.
            key={`fieldbook-v${store.geometryVersion}-l${store.layerLoadKeys['fieldbook'] ?? 0}-${digitizeKey}-${selection.layerId === 'fieldbook' ? selection.featureIds.join(',') : ''}`}
            data={{ type: 'FeatureCollection', features: fieldbookFeatures } as any}
            interactive={!isDigitizing}
            markersInheritOptions
            pointToLayer={(feature, latlng) =>
              L.marker(latlng, {
                icon: createFieldbookIcon(
                  feature.properties?.point_label ?? feature.properties?.point_number ?? null,
                  feature.properties?.point_type,
                  isSelected(feature),
                  feature.properties?.boundary_class,
                  !!feature.properties?.is_junction,
                ),
                interactive: !isDigitizing,
              })
            }
            onEachFeature={(feature, layer: any) => {
              layer.on({ click: makeClickHandler('fieldbook') });
              registerFeatureLayer(feature, layer);
              // Named `ptProps`, not `props` — see the sample-plot popup above
              // (react/prop-types false-triggers on any variable literally named
              // `props`, even outside a component).
              const ptProps = feature.properties || {};
              const coords = feature.geometry?.type === 'Point' ? feature.geometry.coordinates : null;
              const rows: string[] = [
                `<tr><td class="pr-2 text-gray-500 align-top">${t('fieldbook.colType')}</td><td class="text-gray-800">${ptProps.point_type === 'vertex' ? t('fieldbook.pointTypeVertex') : t('fieldbook.pointTypeInterpolated')}</td></tr>`,
              ];
              if (ptProps.remarks) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('attributeTable.col.remark')}</td><td class="text-gray-800">${ptProps.remarks}</td></tr>`);
              }
              if (ptProps.sub_area_name) {
                const cat = ptProps.sub_area_category ? ` (${ptProps.sub_area_category})` : '';
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('attributeTable.col.subArea')}</td><td class="text-gray-800">${ptProps.sub_area_name}${cat}</td></tr>`);
              }
              if (coords) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.longitudeHeader')}</td><td class="font-mono text-gray-800">${Number(coords[0]).toFixed(7)}</td></tr>`);
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('sampling.latitudeHeader')}</td><td class="font-mono text-gray-800">${Number(coords[1]).toFixed(7)}</td></tr>`);
              }
              if (ptProps.elevation != null) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('attributeTable.col.elevationM')}</td><td class="text-gray-800">${Number(ptProps.elevation).toFixed(1)}m</td></tr>`);
              }
              if (ptProps.utm_easting != null) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('attributeTable.col.utmEasting')}</td><td class="font-mono text-gray-800">${Number(ptProps.utm_easting).toFixed(2)}</td></tr>`);
              }
              if (ptProps.utm_northing != null) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('attributeTable.col.utmNorthing')}</td><td class="font-mono text-gray-800">${Number(ptProps.utm_northing).toFixed(2)}</td></tr>`);
              }
              if (ptProps.utm_zone) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('attributeTable.col.utmZone')}</td><td class="text-gray-800">${ptProps.utm_zone}</td></tr>`);
              }
              if (ptProps.azimuth_to_next != null) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('attributeTable.col.azimuthToNext')}</td><td class="text-gray-800">${Number(ptProps.azimuth_to_next).toFixed(1)}°</td></tr>`);
              }
              if (ptProps.distance_to_next != null) {
                rows.push(`<tr><td class="pr-2 text-gray-500 align-top">${t('attributeTable.col.distanceToNext')}</td><td class="text-gray-800">${Number(ptProps.distance_to_next).toFixed(1)}m</td></tr>`);
              }
              layer.bindPopup(`
                <table class="text-sm min-w-[180px]">
                  <tbody>
                    <tr><td class="pr-2 text-gray-500 align-top">${t('attributeTable.col.pointNumber')}</td><td class="font-semibold text-red-600">${ptProps.point_label ?? `P${ptProps.point_number ?? ''}`}</td></tr>
                    ${rows.join('')}
                  </tbody>
                </table>
              `);
            }}
          />
        )}

        {/* GD 2.2.3 (review #10): draft layers render on TOP of the imported stack
            (highest z-index = last in DOM) at 0.7 opacity so they read as WIP;
            finalized layers return to normal order. */}
        {importedLayers.filter((l) => l.visible)
          .sort((a, b) => Number(Boolean(a.isDraft)) - Number(Boolean(b.isDraft)))
          .map((l) => {
          const appendCtx = store.activeDigitizeContext?.mode === 'append' && store.activeDigitizeContext.layer.id === l.id
            ? store.activeDigitizeContext
            : null;
          const buffered = store.digitizeDraftFeatures[l.id];
          const features = l.isDraft
            ? (buffered ?? store.importedLayerFeatures[l.id] ?? null)
            : appendCtx && buffered && buffered.length > 0
              ? [...(store.importedLayerFeatures[l.id] ?? []), ...buffered]
              : (store.importedLayerFeatures[l.id] ?? null);
          if (!features || features.length === 0) return null;
          const ver = store.importedFeatureVersion[l.id] || 0;
          const onEachFeature = importedOnEachFeatures[l.id];
          const custom = store.customLayerStyles[layerStyleKey(String(l.id), 'imported', store.calculationId)];
          const baseStyle = custom
            ? custom
            : purposeLeafletStyle(l.purpose, Boolean(l.isDraft));
          const style = l.isDraft
            ? { ...baseStyle, opacity: (baseStyle.opacity ?? 1) * 0.7 }
            : baseStyle;
          const isPointPurpose = l.purpose === 'inventory' || l.purpose === 'sample_plot';
          // Unified Geometry Drawing plan, D1/Ask 1: `buffered != null` means
          // every feature in THIS render came from the click-to-digitize
          // session (not a prior bulk import) — see the `features` ternary
          // above. Those points aren't saved yet, so they get the fuchsia
          // numbered "freshly drawn" icon instead of the permanent
          // purpose/emoji icon; once flushed, `buffered` clears and the
          // layer reverts to its normal styling with zero behavior change.
          const isFreshlyDrawn = Boolean(l.isDraft) && buffered != null;
          return (
            <GeoJSON
              key={`imported-${l.id}-v${ver}-${l.isDraft ? 'draft' : 'saved'}-${digitizeKey}`}
              data={{ type: 'FeatureCollection', features } as any}
              style={style as any}
              interactive={!isDigitizing}
            // Leaflet's default point->Marker conversion does NOT inherit the
            // parent GeoJSON layer's `interactive` option unless this is set
            // (markersInheritOptions defaults to false) -- without it, a Point
            // feature converted via the built-in pointToLayer would stay
            // interactive even while a digitizing tool is armed.
            markersInheritOptions
              onEachFeature={onEachFeature}
              pointToLayer={(feature, latlng) => {
                // pointToLayer's own returned marker doesn't inherit the
                // GeoJSON-level `interactive` option above (Leaflet only
                // applies that to features it converts itself) -- set it
                // explicitly here too, same reasoning as sample_plots below.
                const marker = isFreshlyDrawn
                  ? L.marker(latlng, { icon: createFreshPointIcon(features.indexOf(feature) + 1) })
                  : isPointPurpose
                  ? purposePointToLayer(feature, latlng, l.purpose, undefined)
                  : (() => {
                      const emoji = getFeatureEmoji(feature);
                      return L.marker(latlng, {
                        icon: L.divIcon({
                          className: 'custom-point-icon',
                          html: `<span style="font-size:22px;line-height:1">${emoji}</span>`,
                          iconSize: [28, 28],
                          iconAnchor: [14, 14],
                        }),
                      });
                    })();
                marker.options.interactive = !isDigitizing;
                return marker;
              }}
            />
          );
        })}

        {/* H2.4 / S1-04: raster tiles are owner-gated now and need a tile
            token in the URL — Leaflet fetches them as <img>, which cannot send
            an Authorization header. Held back until the token arrives.
            Catalog entries may override the tile route + params (BG-1): the
            user-group overlays are served from `user-group-tiles/{landcover|
            biomass}/...` with `exclude_forest=true`, not `/tiles/{id}`. */}
        {(() => {
          const calcId = store.calculationId;
          if (!calcId || !tileToken) return null;
          return store.activeRasterLayers.map((id) => {
            const meta = store.rasterCatalog.find((r) => r.id === id);
            return (
              <TileLayer
                key={`raster-${id}`}
                url={withTileToken(buildRasterTileUrl(calcId, id, meta, Math.round(store.rasterOpacity * 255)), tileToken)!}
                opacity={store.rasterOpacity}
                zIndex={500}
                maxNativeZoom={18}
                maxZoom={WORKSPACE_MAX_ZOOM}
                minZoom={10}
              />
            );
          });
        })()}

        {/* Analysis maps, hazard kind: the backend's cached grid as tiles (never computed on request). Opacity is the
            layer's own; alpha is baked fully opaque so the slider is linear. */}
        {store.calculationId && tileToken && store.activeAnalysisMap && isHazardMap(store.activeAnalysisMap) && !isDotsMap(store.activeAnalysisMap) && (
          <TileLayer
            key={`hazard-${store.activeAnalysisMap}-${store.analysisArea}-v${store.geometryVersion}-c${tileColourVersion}`}
            url={withTileToken(`/api/calculations/${store.calculationId}/hazard-tiles/${hazardLayerKey(store.activeAnalysisMap)}/{z}/{x}/{y}.png?alpha=255&area=${store.analysisArea}&c=${tileColourVersion}`, tileToken)!}
            opacity={store.analysisOpacity}
            zIndex={450}
            maxNativeZoom={18}
            maxZoom={WORKSPACE_MAX_ZOOM}
            minZoom={10}
          />
        )}

        {dotsActive && <HouseholdDotsLayer data={dots.data} opacity={store.analysisOpacity} />}

        {store.activeChart && <FieldGlyphLayer data={glyphs.data} lang={i18n.language} />}

        <UnitFactsCard />

        {store.calculationId && <UserGroupPoiOverlays calculationId={store.calculationId} />}

        {/* Auto-Block layers (RS-2.16/P9/P2.20, owner directive 2026-10-01): a
            committed layer's geometry renders exactly like any built-in
            layer's — same GeoJSON-per-layer pattern imported layers use
            above, just keyed off `rasterLayers`/`rasterLayerFeatures`
            instead of `importedLayers`/`importedLayerFeatures`. Each
            source gets its own default colour (`autoBlockFeatureStyle`) —
            a flat tone for MMU/canopy, a ramp for slope/NASA/health/DEM
            keyed on the feature's own ordinal code, a categorical palette
            for aspect/landcover/forest_type — rather than one flat purple
            for every source. */}
        {store.rasterLayers
          .filter((l) => store.layerVisibility[`raster:${l.id}`] ?? true)
          .map((l) => {
            const features = store.rasterLayerFeatures[l.id];
            if (!features || features.length === 0) return null;
            const labelKey = defaultLabelField(l.source);
            // "Style…" (owner reminder 2026-10-01) writes into the SAME
            // `customLayerStyles` map builtin/imported layers use, keyed via
            // `layerStyleKey(id, 'builtin', calcId)` (safe: a raster layer's
            // UUID id can't collide with a real LayerTypeId string) — fold
            // it over the computed default exactly as a builtin layer would.
            const custom = store.customLayerStyles[layerStyleKey(l.id, 'builtin', store.calculationId)];
            // Owner report 2026-10-02: "Style..." categorical/graduated
            // classification never actually rendered for a raster layer —
            // `Classify` wrote a real RendererSpec into `store.layerRenderers`
            // (same as every built-in layer, e.g. `blockStyle` above reading
            // `rendererColour('blocks', feature)`), but this GeoJSON's own
            // `style` callback never looked at `layerRenderers` at all, only
            // at the flat `custom` override. A raster layer's renderer is
            // keyed by its bare UUID (no 'imported-' prefix, matching
            // `LayerStyleDialog`'s own `rendererKey` for layerType !== 'imported').
            const rendererSpec = store.layerRenderers[l.id] as RendererSpec | undefined;
            return (
              <GeoJSON
                key={`raster-layer-${l.id}`}
                data={{ type: 'FeatureCollection', features } as any}
                style={(feature) => {
                  const base = resolveLayerStyle({
                    base: autoBlockFeatureStyle(l.source, feature, l.promoted_as != null) as unknown as LayerStyle,
                    custom,
                  }) as LayerStyle;
                  const colour = rendererSpec && feature
                    ? rendererColorFor(rendererSpec, feature.properties?.[rendererSpec.field])
                    : null;
                  return applySelection(resolveRendererStyle(base, colour) as L.PathOptions, feature);
                }}
                onEachFeature={(feature, layer) => {
                  const props = (feature.properties ?? {}) as Record<string, unknown>;
                  const text = String(props[labelKey] ?? props['Name'] ?? '');
                  createLabelTooltipForImported(layer, text, showLabels, feature.geometry?.type ?? 'Polygon');
                  // `raster:<id>` matches AttributeTable's `selectionKey`
                  // (`raster:${activeRaster}`) -- without the prefix a map
                  // click and a table-row click select under different keys
                  // and the table row never highlights from a map click.
                  layer.on({ click: makeClickHandler(`raster:${l.id}`) });
                  registerFeatureLayer(feature, layer);
                }}
              />
            );
          })}

        <MapGrid />
        <MapNorthArrow />
        <MapScaleBar />
      </MapContainer>
    </div>
  </MapApiProvider>
);
}
