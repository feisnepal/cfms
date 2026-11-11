/**
 * "Species in view" legend for Stem Mapping -- rendered by the layer panel directly under the
 * Stem Mapping row (it used to float over the map).
 *
 * Lists only the species that are actually on screen (21 swatches for a forest that has 7 would be
 * noise) with their tree count. Clicking a row isolates that species: the rest stay on the map but
 * dim, so the stand context is not lost. Click it again, or "Show all", to clear. A key at the
 * bottom explains the shapes.
 *
 * The counts come from the map (TreeClustersLayer -> store.stemLegend); the isolation is written
 * back to the same slice and read by the map. It exists only while the layer is visible and its
 * species colouring is the active renderer -- a user-chosen renderer has its own legend panel.
 */
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import { OTHER_COLOR, OTHER_KEY, PRIME_SPECIES_FIELD, primeSpeciesByCode } from '../lib/primeSpecies';
import type { RendererSpec } from '../lib/layerRenderers';

export function StemMappingLegendSection() {
  const t = useT();
  const visible = useWorkspaceStore((s) => s.layerVisibility.stem_mapping !== false);
  const renderer = useWorkspaceStore((s) => s.layerRenderers.stem_mapping) as RendererSpec | undefined;
  const { counts, isolated } = useWorkspaceStore((s) => s.stemLegend);
  const setIsolated = useWorkspaceStore((s) => s.setStemIsolated);

  if (!visible) return null; // the whole group belongs to the layer row: it hides when the layer does
  // No stored renderer yet = the species default (it is seeded on load); anything else is the user's own.
  if (renderer && renderer.field !== PRIME_SPECIES_FIELD) return null;

  const rows = Object.entries(counts)
    .map(([key, count]) => {
      if (key === OTHER_KEY) {
        return { key, count, color: OTHER_COLOR, name: t('stemMapLegend.otherSpecies', 'Other species') as string };
      }
      const sp = primeSpeciesByCode(key);
      return { key, count, color: sp?.color ?? OTHER_COLOR, name: sp?.name ?? key };
    })
    .sort((a, b) => (a.key === OTHER_KEY ? 1 : b.key === OTHER_KEY ? -1 : b.count - a.count));

  const total = rows.reduce((sum, r) => sum + r.count, 0);

  return (
    <div
      className="stem-legend-section"
      data-testid="stem-species-legend"
      style={{ margin: '2px 8px 8px 30px', fontSize: 12, lineHeight: 1.35 }}
    >
      {rows.length === 0 ? (
        <p style={{ margin: 0, color: '#777' }} data-testid="stem-legend-hint">
          {t('stemMapLegend.zoomHint', 'Zoom in on the map to see the species in view')}
        </p>
      ) : (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 2 }}>
            <strong>{t('stemMapLegend.title', 'Species in view')}</strong>
            {isolated !== null && (
              <button
                type="button"
                onClick={() => setIsolated(null)}
                style={{ color: '#1677ff', cursor: 'pointer', background: 'none', border: 0, padding: 0 }}
              >
                {t('stemMapLegend.showAll', 'Show all')}
              </button>
            )}
          </div>
          {rows.map((r) => {
            const active = isolated === r.key;
            const dim = isolated !== null && !active;
            return (
              <button
                key={r.key}
                type="button"
                data-testid={`stem-legend-row-${r.key}`}
                aria-pressed={active}
                onClick={() => setIsolated(active ? null : r.key)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6, width: '100%', textAlign: 'left',
                  padding: '2px 4px', border: 0, borderRadius: 3, cursor: 'pointer',
                  background: active ? '#e6f4ff' : 'transparent', opacity: dim ? 0.45 : 1,
                }}
              >
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: r.color, flex: '0 0 auto' }} />
                <span style={{ flex: 1, fontStyle: r.key === OTHER_KEY ? 'normal' : 'italic' }}>{r.name}</span>
                <span style={{ color: '#666' }}>{r.count.toLocaleString()}</span>
              </button>
            );
          })}
          <div style={{ marginTop: 5, paddingTop: 4, borderTop: '1px solid #eee', color: '#444' }}>
            <span>● {t('stemMapLegend.felling', 'Felling tree')}</span>{'  '}
            <span>★ {t('stemMapLegend.mother', 'Mother tree')}</span>{'  '}
            <span>· {t('stemMapLegend.seedling', 'Seedling')}</span>
          </div>
          <div data-testid="stem-legend-total" style={{ marginTop: 3, color: '#222', fontWeight: 600 }}>
            {t('stemMapLegend.totalInView', 'Total trees in view')}: {total.toLocaleString()}
          </div>
        </>
      )}
    </div>
  );
}
