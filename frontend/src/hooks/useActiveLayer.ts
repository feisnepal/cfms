import { useState, useEffect, useCallback } from 'react';
import type L from 'leaflet';
import type { GeoJSON } from 'geojson';
import { useWorkspaceStore } from '../store/workspaceStore';
import { getLayerConfig } from '../lib/layerRegistry';
import { getLayerStyle } from '../lib/layerStyles';
import type { ColumnDef, DataSource, LayerTypeConfig, LayerGeomanMode, ToolbarButtonConfig } from '../lib/layerRegistry';

interface ActiveLayerState {
  config: LayerTypeConfig | null;
  features: GeoJSON.Feature[];
  isLoading: boolean;
  error: string | null;
  isLocked: boolean;
  geomanOptions: LayerGeomanMode[];
  toolbarButtons: ToolbarButtonConfig[];
  columns: ColumnDef[];
  styleFunction: (feature: GeoJSON.Feature) => L.PathOptions;
  dataSource: DataSource;
}

export function useActiveLayer(
  calculationId: string | null,
  isStructureLocked: boolean = false,
): ActiveLayerState {
  const store = useWorkspaceStore();
  const layerId = store.activeLayerId;

  const config = layerId ? (getLayerConfig(layerId) ?? null) : null;
  const [features, setFeatures] = useState<GeoJSON.Feature[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!config || !calculationId) {
      setFeatures([]);
      setIsLoading(false);
      return;
    }

    const perfMark = performance.mark(`useActiveLayer:fetch-${config.id}`);
    setIsLoading(true);
    setError(null);
    store.setLoading(`features:${config.id}`, true);

    config.dataSource.fetch(calculationId)
      .then((fetched) => {
        setFeatures(fetched || []);
        store.setFeatureCount(config.id, fetched?.length || 0);
        performance.mark(`useActiveLayer:fetch-end-${config.id}`);
        performance.measure(`useActiveLayer:fetch-${config.id}`,
          `useActiveLayer:fetch-${config.id}`, `useActiveLayer:fetch-end-${config.id}`);
      })
      .catch((err) => {
        const msg = err?.message || `Failed to load ${config.id}`;
        setError(msg);
        store.setError(`features:${config.id}`, msg);
      })
      .finally(() => {
        setIsLoading(false);
        store.setLoading(`features:${config.id}`, false);
      });
  }, [config?.id, calculationId]);

  const isLocked = config
    ? (typeof config.editable === 'function'
        ? !config.editable({ structure_locked: isStructureLocked })
        : !config.editable)
    : true;

  const geomanOptions = config?.geomanModes || [];
  const toolbarButtons = config
    ? getToolbarConfig(config)
    : [];
  const columns = config?.columns || [];
  const dataSource = config?.dataSource || nullDataSource;

  const styleFunction = useCallback(
    (feature: GeoJSON.Feature): L.PathOptions => {
      if (!config) return {};
      const baseStyle = getLayerStyle(config.styleKey);
      if (!baseStyle) return {};

      const subType = getSubTypeModifier(config, feature);
      const selectionStyle = store.isFeatureSelected(config.id, feature.properties?.id)
        ? SELECTION_STYLE
        : {};

      return { ...baseStyle, ...subType, ...selectionStyle };
    },
    [config, store.selection],
  );

  return {
    config,
    features,
    isLoading,
    error,
    isLocked,
    geomanOptions,
    toolbarButtons,
    columns,
    styleFunction,
    dataSource,
  };
}

const SELECTION_STYLE: L.PathOptions = {
  color: '#FFD700',
  weight: 4,
  fillColor: '#FFD700',
  fillOpacity: 0.3,
  dashArray: '6, 3',
};

function getSubTypeModifier(config: LayerTypeConfig, feature: GeoJSON.Feature): L.PathOptions {
  if (config.id !== 'activity_features') return {};
  const geomType = feature.geometry.type;
  if (geomType === 'Point') return getLayerStyle('activity_points') || {};
  if (geomType === 'LineString') return getLayerStyle('activity_lines') || {};
  return getLayerStyle('activity_polygons') || {};
}

const nullDataSource: DataSource = {
  fetch: async () => [],
  create: async () => { throw new Error('Read-only layer'); },
  update: async () => { throw new Error('Read-only layer'); },
  delete: async () => { throw new Error('Read-only layer'); },
};

function getToolbarConfig(config: LayerTypeConfig): ToolbarButtonConfig[] {
  return config.geomanModes.map((mode) => ({
    mode: mode.mode,
    label: mode.label,
    icon: mode.icon,
  }));
}
