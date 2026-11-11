import { useState, useCallback, useRef } from 'react';

export interface ImportLayerOptions {
  calculationId: string;
  file: File;
  crsEpsg?: number;
  /** Purpose is optional — when omitted the layer is imported unassigned. */
  purpose?: string;
  customName?: string;
  gpxTypes?: string[];
  replaceExisting?: boolean;
}

export interface ImportResult {
  success: boolean;
  layerId?: number;
  layerName?: string;
  featureCount?: number;
  geometryTypes?: string[];
  /** Import purpose chosen by the user (e.g. 'blocks', 'boundary'). */
  purpose?: string;
  warning?: string;
  error?: string;
  errorCode?: string;
  /** Whether the import resulted in a conversion to a builtin layer. */
  converted?: boolean;
  /** Whether the backend auto-corrected swapped longitude/latitude values. */
  swappedFixed?: boolean;
}

interface UseImportLayerReturn {
  importLayer: (options: ImportLayerOptions) => Promise<ImportResult>;
  isImporting: boolean;
  progress: number;
  progressMessage: string;
  reset: () => void;
}

const PROGRESS_STEPS = [
  { pct: 10, msg: 'Validating file...' },
  { pct: 25, msg: 'Checking format...' },
  { pct: 40, msg: 'Parsing geometry...' },
  { pct: 55, msg: 'Validating constraints...' },
  { pct: 70, msg: 'Checking boundaries...' },
  { pct: 85, msg: 'Saving to workspace...' },
  { pct: 100, msg: 'Import complete!' },
];

export function useImportLayer(): UseImportLayerReturn {
  const [isImporting, setIsImporting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const abortRef = useRef(false);

  const reset = useCallback(() => {
    setProgress(0);
    setProgressMessage('');
    setIsImporting(false);
    abortRef.current = false;
  }, []);

  const simulateProgress = useCallback(() => {
    let step = 0;
    const tick = () => {
      if (abortRef.current) return;
      if (step < PROGRESS_STEPS.length) {
        setProgress(PROGRESS_STEPS[step].pct);
        setProgressMessage(PROGRESS_STEPS[step].msg);
        step++;
        const delay = step === PROGRESS_STEPS.length - 1 ? 500 : 800;
        setTimeout(tick, delay);
      }
    };
    tick();
  }, []);

  const importLayer = useCallback(async (options: ImportLayerOptions): Promise<ImportResult> => {
    setIsImporting(true);
    setProgress(0);
    setProgressMessage('Starting import...');
    abortRef.current = false;
    simulateProgress();

    try {
      const formData = new FormData();
      formData.append('file', options.file);
      // Only send purpose when one was chosen. FormData coerces values to strings,
      // so appending `undefined` would send the literal text "undefined" and the
      // backend would treat the layer as purposed instead of unassigned.
      if (options.purpose) formData.append('purpose', options.purpose);
      if (options.customName) formData.append('custom_name', options.customName);
      if (options.crsEpsg) formData.append('crs_epsg', String(options.crsEpsg));
      if (options.gpxTypes && options.gpxTypes.length > 0) {
        formData.append('gpx_types', options.gpxTypes.join(','));
      }
      if (options.replaceExisting) formData.append('replace_existing', 'true');

      const baseUrl = import.meta.env.VITE_API_URL ?? '';
      const url = `${baseUrl}/api/v1/workspace/${options.calculationId}/import-layer`;

      const token = localStorage.getItem('access_token');
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch(url, {
        method: 'POST',
        body: formData,
        headers,
        credentials: 'include',
      });

      const data = await response.json();

      if (!response.ok) {
        abortRef.current = true;
        setProgress(0);
        setIsImporting(false);
        return {
          success: false,
          error: data.detail || data.message || 'Import failed',
          errorCode: data.error_code,
        };
      }

      abortRef.current = true;
      setProgress(100);
      setProgressMessage('Import complete!');
      setIsImporting(false);

      return {
        success: true,
        layerId: data.id,
        layerName: data.name,
        featureCount: data.feature_count,
        geometryTypes: data.geometry_types,
        warning: data.warnings,
        swappedFixed: Boolean(data.swapped_fixed),
      };
    } catch (err) {
      abortRef.current = true;
      setProgress(0);
      setIsImporting(false);
      return {
        success: false,
        error: err instanceof Error ? err.message : 'Network error',
        errorCode: 'NETWORK_ERROR',
      };
    }
  }, [simulateProgress]);

  return { importLayer, isImporting, progress, progressMessage, reset };
}
