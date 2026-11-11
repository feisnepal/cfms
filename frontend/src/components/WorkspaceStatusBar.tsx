import { useState, useEffect } from 'react';
import type L from 'leaflet';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';

interface WorkspaceStatusBarProps {
  map: L.Map | null;
}

export function WorkspaceStatusBar({ map }: WorkspaceStatusBarProps) {
  const store = useWorkspaceStore();
  const t = useT();
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [zoom, setZoom] = useState<number>(0);

  useEffect(() => {
    if (!map) return;

    const updateCoords = (e: L.LeafletMouseEvent) => {
      setCoords({ lat: e.latlng.lat, lng: e.latlng.lng });
    };

    const updateZoom = () => {
      setZoom(map.getZoom());
    };

    map.on('mousemove', updateCoords);
    map.on('zoomend', updateZoom);

    setZoom(map.getZoom());

    return () => {
      map.off('mousemove', updateCoords);
      map.off('zoomend', updateZoom);
    };
  }, [map]);

  const activeLayerLabel = store.activeLayerId || t('workspace.statusNone');
  const selectionCount = store.selection.featureIds.length;
  const digitizeCtx = store.activeDigitizeContext;

  return (
    <div className="workspace-status-bar" role="status" aria-live="polite">
      <span className="status-coords">
        {coords
          ? `${coords.lat.toFixed(6)}, ${coords.lng.toFixed(6)}`
          : t('workspace.statusCoords')}
      </span>
      <span className="status-zoom">{t('workspace.statusZoom')}: {zoom}</span>
      <span className="status-layer">{t('workspace.statusLayer')}: {store.activeLayerId || t('workspace.statusNone')}</span>
      {digitizeCtx && (
        <span className="status-digitize" style={{ color: '#2563eb', fontWeight: 600 }}>
          ✏️ {t('workspace.statusDigitizeMode', { purpose: digitizeCtx.layer.purpose })}
        </span>
      )}
      {selectionCount > 0 && (
        <button
          type="button"
          className="status-selection"
          onClick={() => {
            store.clearSelection();
            store.selectFeatureGlobal(null);
          }}
          title={t('workspace.statusClearSelectionHint')}
        >
          {t('workspace.statusSelection', { count: selectionCount })} ✕
        </button>
      )}
    </div>
  );
}
