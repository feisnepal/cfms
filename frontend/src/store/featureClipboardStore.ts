/**
 * The feature clipboard: what the toolbar Copy last took, waiting for a Paste.
 *
 * A store of its own rather than a slice of `workspaceStore`: it has nothing to
 * do with layers or selection beyond "what was copied", it must survive
 * switching the active layer (that is the whole point), and it is deliberately
 * NOT persisted — a clipboard that outlives the tab and pastes stale geometry
 * into a forest that has since changed is worse than an empty one.
 */
import { create } from 'zustand';
import type { GeoJSON } from 'geojson';

export interface FeatureClipboard {
  /** Calculation the features came from — a paste never crosses calculations. */
  calcId: string;
  /** Layer key the features came from (`blocks`, `imported-12`, …). */
  sourceLayerKey: string;
  /** Human label for toasts / tooltips. */
  sourceLabel: string;
  /** True when nothing was selected and the whole layer was copied. */
  wholeLayer: boolean;
  /** Cleaned, single-part features (see `toClipboardFeatures`). */
  features: GeoJSON.Feature[];
  copiedAt: number;
}

interface FeatureClipboardState {
  clipboard: FeatureClipboard | null;
  setClipboard: (clipboard: FeatureClipboard) => void;
  clearClipboard: () => void;
}

export const useFeatureClipboardStore = create<FeatureClipboardState>((set) => ({
  clipboard: null,
  setClipboard: (clipboard) => set({ clipboard }),
  clearClipboard: () => set({ clipboard: null }),
}));
