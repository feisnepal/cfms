import { useWorkspaceStore, type UserGroupPoiType } from '../store/workspaceStore';
import { useUserGroupAnalysisStatus } from '../hooks/useUserGroupAnalysisStatus';
import { useT } from '../i18n/hooks';

const POI_TYPES: Array<{ type: UserGroupPoiType; labelKey: string; icon: string }> = [
  { type: 'education', labelKey: 'workspace.userGroup.poiEducation', icon: '🏫' },
  { type: 'health', labelKey: 'workspace.userGroup.poiHealth', icon: '🏥' },
  { type: 'poi', labelKey: 'workspace.userGroup.poiPoints', icon: '📍' },
  { type: 'rivers', labelKey: 'workspace.userGroup.poiRivers', icon: '💧' },
];

const RASTER_IDS = ['ug_landcover', 'ug_biomass'] as const;

/**
 * Analysis-gated results section under the `user_group` layer (BG-2/D6).
 * Only rendered when the calculation has a user-group analysis; offers the
 * POI toggles (store slice) and the land-cover/biomass raster toggles.
 */
export function UserGroupAnalysisSection({ calculationId }: { calculationId?: string | null }) {
  const t = useT();
  const store = useWorkspaceStore();
  const { hasAnalysis, loading } = useUserGroupAnalysisStatus(calculationId);

  if (loading) return null;
  if (!hasAnalysis || !calculationId) return null;
  // The whole group belongs to the layer row — it hides when the layer does.
  if (store.layerVisibility.user_group === false) return null;

  return (
    <div
      className="user-group-analysis-section"
      data-testid="user-group-analysis-section"
      role="group"
      aria-label={t('workspace.userGroup.analysisTitle')}
    >
      <div className="ug-section-title">{t('workspace.userGroup.analysisTitle')}</div>
      <div className="ug-section-toggles" role="group" aria-label={t('workspace.userGroup.poiLabel')}>
        {POI_TYPES.map(({ type, labelKey, icon }) => {
          const active = !!store.userGroupPoiVisible[type];
          return (
            <button
              key={type}
              type="button"
              className="ug-toggle"
              aria-pressed={active}
              onClick={() => store.toggleUserGroupPoi(type)}
            >
              <span aria-hidden="true">{icon}</span> {t(labelKey)}
            </button>
          );
        })}
      </div>
      <div className="ug-section-toggles" role="group" aria-label={t('workspace.userGroup.rasterLabel')}>
        {RASTER_IDS.map((id) => {
          const meta = store.rasterCatalog.find((r) => r.id === id);
          const active = store.activeRasterLayers.includes(id);
          return (
            <button
              key={id}
              type="button"
              className="ug-toggle ug-raster"
              aria-pressed={active}
              onClick={() => store.toggleRasterLayer(id)}
            >
              {meta?.name ?? t(id === 'ug_landcover' ? 'workspace.userGroup.landcoverOverlay' : 'workspace.userGroup.biomassOverlay')}
            </button>
          );
        })}
      </div>
    </div>
  );
}