import { getAllLayerConfigs } from '../lib/layerRegistry';
import { SUB_AREA_COLORS, BLOCK_COLORS, SUB_BLOCK_COLORS, COMPARTMENT_COLORS, SUB_COMPARTMENT_COLORS, STYLE_PRESETS, PROTECTION_WC_COLOR, layerStyleKey, type CustomLayerStyle } from '../lib/layerStyles';
import { rendererLegendRows, type RendererSpec } from '../lib/layerRenderers';
import { resolveRasterLegend } from '../lib/rasterLegends';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import { AnalysisLegendSection } from './AnalysisLegendSection';
import { useTranslation } from 'react-i18next';
import { ACTIVITY_KINDS, ACTIVITY_KIND_IDS, activityKindCountKey, activityKindLabel } from '../lib/activityKinds';

const LAYER_LABEL_KEYS: Record<string, string> = {
  boundary: 'layer.forestBoundary',
  user_group: 'layer.userGroupBoundary',
  blocks: 'layer.blocks',
  sub_blocks: 'layer.subBlocks',
  compartments: 'layer.compartments',
  sub_compartments: 'layer.subCompartments',
  sub_areas: 'layer.subAreas',
  activity_features: 'layer.activityFeatures',
  sample_plots: 'layer.samplePlots',
  stem_mapping: 'layer.stemMapping',
  fieldbook: 'layer.fieldbook',
};

export function LegendPanel() {
  const store = useWorkspaceStore();
  const t = useT();
  const { i18n } = useTranslation();
  const layerConfigs = getAllLayerConfigs();

  const visibleLayers = layerConfigs.filter(c => store.layerVisibility[c.id] !== false);
  const activeRasterLayers = store.rasterCatalog.filter(r => store.activeRasterLayers.includes(r.id));

  // Protection Working Circle: show the "no felling" row only when a
  // `working_circle === 'protection'` unit is present on a visible unit layer.
  const protectionUnitCount = (['blocks', 'sub_blocks', 'compartments', 'sub_compartments'] as const)
    .filter(id => store.layerVisibility[id] !== false)
    .reduce((n, id) => n + (store.featureCounts[`${id}:protection`] ?? 0), 0);

  return (
    <div className="legend-panel" data-testid="legend-panel">
      <div className="legend-header">{t('legend.legend')}</div>
      <div className="legend-items">
        {visibleLayers.map(config => {
          const count = store.featureCounts[config.id] ?? 0;
          const layerKey = LAYER_LABEL_KEYS[config.id] || config.label;
          const custom = store.customLayerStyles[layerStyleKey(config.id, 'builtin', store.calculationId)] as CustomLayerStyle | undefined;
          // P4.4 — a thematic renderer replaces the single swatch with one row
          // per class / bucket.
          const renderer = store.layerRenderers[config.id] as RendererSpec | undefined;
          if (renderer) {
            const rows = rendererLegendRows(renderer);
            return (
              <div key={config.id} className="legend-thematic" data-testid={`legend-thematic-${config.id}`}>
                <div className="legend-thematic-head">
                  <span className="legend-label">{t(layerKey)}</span>
                  <span className="legend-thematic-field">{renderer.field}</span>
                </div>
                {rows.map((r, i) => (
                  <div key={i} className="legend-item legend-thematic-row">
                    <span className="legend-swatch" style={{ background: r.color }} />
                    <span className="legend-label">{r.label}</span>
                  </div>
                ))}
              </div>
            );
          }
          // Activity Features: one row per symbol kind actually on the map, in its colour.
          const kindRows = config.id === 'activity_features'
            ? ACTIVITY_KIND_IDS.filter((k) => (store.featureCounts[activityKindCountKey(k)] ?? 0) > 0)
            : [];
          return (
            <div key={config.id}>
              <div className="legend-item">
                <span className="legend-swatch" style={{ background: swatchColour(config.id, custom) }} />
                <span className="legend-label">{t(layerKey)}</span>
                {count > 0 && <span className="legend-count">{count}</span>}
              </div>
              {kindRows.map((k) => (
                <div key={k} className="legend-item legend-kind-row" data-testid={`legend-kind-${k}`} style={{ paddingLeft: 14 }}>
                  <span
                    className="legend-swatch"
                    style={{ background: ACTIVITY_KINDS[k].color, borderRadius: ACTIVITY_KINDS[k].geom === 'point' ? '50%' : undefined }}
                  />
                  <span className="legend-label">{activityKindLabel(k, i18n.language)}</span>
                  <span className="legend-count">{store.featureCounts[activityKindCountKey(k)]}</span>
                </div>
              ))}
            </div>
          );
        })}

        <AnalysisLegendSection />

        {protectionUnitCount > 0 && (
          <div className="legend-item" data-testid="legend-protection-wc">
            <span
              className="legend-swatch"
              style={{ background: PROTECTION_WC_COLOR, border: '1px dashed #065F46' }}
            />
            <span className="legend-label">{t('legend.protectionWorkingCircle')}</span>
            <span className="legend-count">{protectionUnitCount}</span>
          </div>
        )}

        {activeRasterLayers.length > 0 && (
          <>
            <div className="legend-section-title">{t('raster.overlays')}</div>
            {activeRasterLayers.map(raster => {
              const legend = resolveRasterLegend(raster.id);
              return (
                <div key={raster.id} className="legend-raster-group">
                  <div className="legend-raster-name">{t('raster.name', { name: raster.name })}</div>
                  {legend.map((item, idx) => (
                    <div key={idx} className="legend-item">
                      <span className="legend-swatch" style={{ background: item.color }} />
                      <span className="legend-label">{item.label}</span>
                      {item.range && <span className="legend-range">{item.range}</span>}
                    </div>
                  ))}
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}

function getLayerSwatchColor(layerId: string): string {
  switch (layerId) {
    case 'boundary': return '#228B22';
    case 'user_group': return STYLE_PRESETS.user_group.color || '#4338CA';
    case 'blocks': return BLOCK_COLORS[0];
    case 'sub_blocks': return SUB_BLOCK_COLORS[0];
    case 'compartments': return COMPARTMENT_COLORS[0];
    case 'sub_compartments': return SUB_COMPARTMENT_COLORS[0];
    case 'sub_areas': return '#8B4513';
    case 'activity_features': return '#1E90FF';
    case 'stem_mapping': return STYLE_PRESETS.stem_mapping.fillColor || '#7C3AED';
    default: return '#999';
  }
}

/** The legend swatch follows a user's custom fill/stroke choice (P1.3). A
 *  palette layer only shows a flat custom colour when "override palette" is on. */
function swatchColour(layerId: string, custom?: CustomLayerStyle): string {
  if (custom) {
    const palette = ['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas'].includes(layerId);
    if (!palette || custom.__flat) return custom.fillColor || custom.color || getLayerSwatchColor(layerId);
  }
  return getLayerSwatchColor(layerId);
}

export default LegendPanel;
