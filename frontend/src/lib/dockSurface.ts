/**
 * dockSurface — the `?feature=` deep-link param for the tabbed calc shell
 * (Option C W1f, the first slice of the W1 "WorkspaceShell" merge after W1e
 * deleted the old dual nav).
 *
 *   feature = "<layerId>:<featureId>"   e.g. "sample_plots:42"
 *
 * Names exactly one selected feature so it survives a reload or a shared
 * link — mirrors `calcSurface.ts`'s `?surface=` param, but for *what's
 * selected* rather than *which panel is open*. The two coexist in the same
 * query string (the shell's `setUrlParams` merges rather than replaces).
 *
 * `layerId` is free-form on purpose: it covers every built-in `LayerTypeId`
 * plus imported-layer ids (`imported:<uuid>`), and this module doesn't need
 * to know the difference — only `workspaceStore.selection` does. Nothing
 * consumes this beyond seeding/syncing `workspaceStore.selection` yet; a dock
 * panel that reacts to it is W1g+.
 */

export interface DockFeatureRef {
  layerId: string;
  featureId: string;
}

const SEP = ':';

/** `"<layerId>:<featureId>"` — the value that goes in `?feature=`. */
export function toFeatureParam(ref: DockFeatureRef): string {
  return `${ref.layerId}${SEP}${ref.featureId}`;
}

/**
 * Parse a `?feature=` value into `{ layerId, featureId }`. Splits on the
 * *last* `:` — an imported layer's `workspaceStore.selection.layerId` is
 * itself `imported:<uuid>` (see `AttributeTable.tsx`'s `selectionKey`), and
 * feature ids in this codebase never contain a colon, so the last colon is
 * always the layerId/featureId boundary. Returns `null` for a missing /
 * malformed value (no colon, or nothing on either side of it).
 */
export function parseFeatureParam(raw: string | null | undefined): DockFeatureRef | null {
  if (!raw) return null;
  const i = raw.lastIndexOf(SEP);
  if (i <= 0 || i === raw.length - 1) return null;
  return { layerId: raw.slice(0, i), featureId: raw.slice(i + 1) };
}
