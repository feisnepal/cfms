import { useEffect, useRef } from 'react';
import { useWorkspaceStore } from '../store/workspaceStore';
import { forestApi } from '../services/api';
import type { GraduatedRenderer, RendererSpec } from '../lib/layerRenderers';
import { PRIME_SPECIES_RENDERER } from '../lib/primeSpecies';

// Prior shipped defaults for the DBH auto-seed below. A forest whose stored
// `stem_mapping` renderer matches one of these byte-for-byte was never opened
// in the Style Layer dialog -- it's still riding the very first auto-seed,
// which persisted (result_data.layer_renderers, not localStorage) and so
// never noticed when DBH_CLASS_RENDERER's own colours changed later (2026-09-05,
// the traffic-light recolour, was invisible on any forest already seeded
// under the old red/yellow/blue/green scheme -- restarting the server or using
// a private browser window doesn't touch server-persisted result_data, so
// neither made the stale colours go away). Anything that doesn't match
// exactly is presumed to be an intentional customization and is left alone.
// Append here (never remove/edit existing entries) the next time
// the default changes, so this keeps carrying forward.
//
// 2026-10-04: the default became "colour by prime species" (PRIME_SPECIES_RENDERER).
// The second snapshot below is the traffic-light DBH default it replaced, so a forest
// that never opened the Style dialog moves to the species colouring too.
const LEGACY_DBH_RENDERER_SNAPSHOTS: GraduatedRenderer[] = [
  {
    mode: 'graduated',
    field: 'dbh_cm',
    method: 'equal',
    breaks: [10, 20, 30, 40, 50, 60, 70],
    colors: ['#8B0000', '#E57373', '#CC9900', '#FFE066', '#00008B', '#64B5F6', '#81C784', '#1B5E20'],
    ramp: 'custom',
  },
  {
    mode: 'graduated',
    field: 'dbh_cm',
    method: 'equal',
    breaks: [10, 20, 30, 40, 50, 60, 70],
    colors: ['#C8E6C9', '#81C784', '#388E3C', '#FBC02D', '#FF8A65', '#E53935', '#D81B60', '#880E4F'],
    ramp: 'custom',
  },
];

function graduatedRendererEquals(a: GraduatedRenderer, b: GraduatedRenderer): boolean {
  return (
    a.field === b.field &&
    a.method === b.method &&
    a.ramp === b.ramp &&
    JSON.stringify(a.breaks) === JSON.stringify(b.breaks) &&
    JSON.stringify(a.colors) === JSON.stringify(b.colors)
  );
}

/** True if `spec` is exactly one of the historical DBH-renderer snapshots above. */
function isStaleAutoSeededDbhRenderer(spec: RendererSpec | undefined): boolean {
  if (!spec || spec.mode !== 'graduated') return false;
  return LEGACY_DBH_RENDERER_SNAPSHOTS.some((legacy) => graduatedRendererEquals(spec, legacy));
}

/**
 * Loads the calculation's thematic renderer specs from
 * `result_data.layer_renderers` into the workspace store on mount, and writes
 * them back (debounced) whenever they change — the P4 counterpart of
 * `MapCompositionService`, using the same `/result-data` merge-patch endpoint.
 * WORKSPACE_LAYER_STYLING_PLAN.md P4.1 (decision D8 — server, never localStorage).
 */
export function useLayerRenderers(calculationId: string | null): void {
  const layerRenderers = useWorkspaceStore((s) => s.layerRenderers);
  const hydrateLayerRenderers = useWorkspaceStore((s) => s.hydrateLayerRenderers);
  const hydratedFor = useRef<string | null>(null);

  useEffect(() => {
    if (!calculationId) return;
    let cancelled = false;
    forestApi.getCalculation(calculationId)
      .then((calc) => {
        if (cancelled) return;
        const stored = (calc.result_data?.layer_renderers ?? {}) as Record<string, RendererSpec>;
        // Stem Mapping ships with "colour by prime species" turned on, not as an
        // opt-in preset — seed it once per forest, on first load, so it's
        // there before anyone opens the Style Layer dialog. After this it is
        // ordinary renderer state: replacing or clearing it (dialog) sticks,
        // same as any user-chosen renderer. The one exception is a renderer
        // that still matches an old shipped default exactly (never touched
        // in the dialog) — that gets refreshed to the current default too,
        // so a palette revision reaches forests that were seeded before it
        // shipped, not just newly-opened ones.
        const needsSeed = !stored.stem_mapping || isStaleAutoSeededDbhRenderer(stored.stem_mapping);
        const seeded = needsSeed ? { ...stored, stem_mapping: PRIME_SPECIES_RENDERER } : stored;
        hydrateLayerRenderers(seeded);
        hydratedFor.current = calculationId;
      })
      .catch(() => {
        if (!cancelled) hydratedFor.current = calculationId;
      });
    return () => { cancelled = true; };
  }, [calculationId, hydrateLayerRenderers]);

  useEffect(() => {
    // Only persist once this calc's specs have been loaded — otherwise the
    // initial empty `{}` would clobber a saved set before the GET returns.
    if (!calculationId || hydratedFor.current !== calculationId) return;
    const id = window.setTimeout(() => {
      forestApi.updateResultData(calculationId, { layer_renderers: layerRenderers }).catch(() => { /* best-effort */ });
    }, 600);
    return () => window.clearTimeout(id);
  }, [calculationId, layerRenderers]);
}
