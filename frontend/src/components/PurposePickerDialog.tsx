import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { message } from 'antd';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import {
  PURPOSES,
  allowedGeometryTypes,
  purposeLabel,
  autoNameForPurpose,
  nextPurposeName,
  type GeometryType,
} from '../lib/purposeGeometryRules';

interface PurposePickerDialogProps {
  calculationId: string;
  onCreated: () => void;
  onCancel: () => void;
  /** Restrict the offered purposes to geometry-typed ones (Forest boundary / Block).
   *  Used for the first add on a boundary-less draft. */
  restrictToGeometry?: boolean;
}

/** Geometry-typed purposes allowed for the first add on a boundary-less draft. */
const GEOMETRY_PURPOSES = ['boundary', 'blocks'];

const GEOM_LABEL_KEY: Record<GeometryType, string> = {
  Point: 'digitize.geom.point',
  LineString: 'digitize.geom.line',
  Polygon: 'digitize.geom.polygon',
};

function drawModeForToolbar(mode: 'point' | 'line' | 'polygon') {
  return mode === 'point' ? 'draw_point' : mode === 'line' ? 'draw_line' : 'draw_polygon';
}

export default function PurposePickerDialog({ calculationId, onCreated, onCancel, restrictToGeometry = false }: PurposePickerDialogProps) {
  const t = useT();
  const createDigitizeLayer = useWorkspaceStore((s) => s.createDigitizeLayer);
  const importedLayers = useWorkspaceStore((s) => s.importedLayers);
  const importedLayerNames = useMemo(
    () => importedLayers.map((l) => l.name),
    [importedLayers],
  );
  const setActiveDigitizeContext = useWorkspaceStore((s) => s.setActiveDigitizeContext);
  const setActiveImportedLayer = useWorkspaceStore((s) => s.setActiveImportedLayer);
  const setToolbarMode = useWorkspaceStore((s) => s.setToolbarMode);

  const [purpose, setPurpose] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const availablePurposes = restrictToGeometry
    ? PURPOSES.filter((p) => GEOMETRY_PURPOSES.includes(p.id))
    : PURPOSES;

  const selectedPurpose = useMemo(
    () => (purpose ? PURPOSES.find((p) => p.id === purpose) ?? null : null),
    [purpose],
  );

  const allowed = useMemo(
    () => (purpose ? allowedGeometryTypes(purpose) : []),
    [purpose],
  );

  const handlePurposeSelect = (id: string) => {
    setPurpose(id);
    const info = PURPOSES.find((p) => p.id === id);
    setName(
      autoNameForPurpose(id)
        ? nextPurposeName(id, importedLayerNames)
        : info?.label ?? '',
    );
    setError(null);
  };

  const handleCreate = async () => {
    if (!purpose || !selectedPurpose) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t('digitize.picker.nameRequired'));
      return;
    }
    setCreating(true);
    setError(null);
    try {
      console.log('[PurposePickerDialog] Creating digitize layer:', { purpose, name: trimmed });
      const layer = await createDigitizeLayer(calculationId, purpose, trimmed);
      console.log('[PurposePickerDialog] Layer created:', layer);
      setActiveDigitizeContext({ mode: 'draft', layer });
      setActiveImportedLayer(layer.id);
      const firstMode = allowed.length > 0 ? drawModeForToolbar(allowed[0].toLowerCase() as 'point' | 'line' | 'polygon') : 'draw_point';
      console.log('[PurposePickerDialog] Setting toolbar mode:', firstMode);
      setToolbarMode(firstMode);
      message.success(t('digitize.picker.msgCreated', { name: trimmed }));
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('digitize.picker.createFailed'));
      setCreating(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[9999] p-4">
      <div className="bg-white rounded-lg max-w-xl w-full max-h-[90vh] overflow-y-auto p-6 space-y-5">
        <h2 className="text-xl font-bold text-gray-900">{t('digitize.picker.title')}</h2>
        <p className="text-sm text-gray-600">
          {t('digitize.picker.subtitle')}
        </p>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md text-sm" role="alert">
            {error}
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">{t('digitize.picker.purpose')}</label>
          <div className="grid grid-cols-2 gap-2">
            {availablePurposes.map((p) => (
              <button
                key={p.id}
                type="button"
                disabled={creating}
                onClick={() => handlePurposeSelect(p.id)}
                className={`px-3 py-2 text-sm rounded-md border text-left transition-colors
                  ${purpose === p.id
                    ? 'border-green-500 bg-green-50 text-green-800'
                    : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}
                  ${creating ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                <span className="block font-medium">{t(p.labelKey)}</span>
                <span className="block text-xs text-gray-400 mt-1">{t(p.descKey)}</span>
              </button>
            ))}
          </div>
        </div>

        {purpose && (
          <div className="bg-gray-50 border border-gray-200 rounded-md px-3 py-2 text-xs text-gray-600">
            {t('digitize.picker.allowedGeometry')} <span className="font-medium text-gray-800">{allowed.map((g) => t(GEOM_LABEL_KEY[g])).join(', ')}</span>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{t('digitize.picker.layerName')}</label>
          <input
            type="text"
            value={name}
            disabled={creating}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); }}
            placeholder={selectedPurpose ? t(selectedPurpose.labelKey) : t('digitize.picker.phLayerName')}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-green-500 focus:border-green-500"
          />
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={onCancel}
            disabled={creating}
            className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleCreate}
            disabled={creating || !purpose}
            className="px-4 py-2 border border-transparent rounded-md text-sm font-medium text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {creating ? t('digitize.picker.creating') : t('digitize.picker.createAndDraw')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
