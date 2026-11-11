/**
 * A short string that changes ONLY after the user's colours for an Analysis map have stopped changing AND had time to reach
 * the server.
 *
 * The colours are saved to the forest by `useLayerRenderers` after a 600 ms pause, and the hazard tiles / legend are drawn by
 * the SERVER from what it has saved. Re-requesting the tiles the instant a swatch moves would fetch the OLD colours (and the
 * browser would cache them), so tile layers and legends key on this version instead of on the live value.
 */
import { useEffect, useState } from 'react';
import { useWorkspaceStore } from '../store/workspaceStore';
import { analysisRendererKey, type AnalysisMapId } from '../lib/analysisMaps';

export const SAVE_SETTLE_MS = 1200; // useLayerRenderers' 600 ms debounce + the request

export function useSettledColours(id: AnalysisMapId | null | undefined): string {
  const live = useWorkspaceStore((s) => (id ? JSON.stringify(s.layerRenderers[analysisRendererKey(id)] ?? null) : 'null'));
  const [settled, setSettled] = useState(live);
  useEffect(() => {
    if (live === settled) return;
    const t = window.setTimeout(() => setSettled(live), SAVE_SETTLE_MS);
    return () => window.clearTimeout(t);
  }, [live, settled]);
  // a different map starts settled on its own saved colours
  useEffect(() => setSettled(live), [id]); // eslint-disable-line react-hooks/exhaustive-deps
  let h = 7;
  for (let i = 0; i < settled.length; i++) h = (h * 31 + settled.charCodeAt(i)) | 0;
  return settled === 'null' ? '0' : (h >>> 0).toString(36);
}
