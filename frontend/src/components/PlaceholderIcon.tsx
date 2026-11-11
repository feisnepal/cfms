/**
 * The placeholder icon at the right edge of an Analysis-map / chart row.
 *
 * Every workspace map stands for ONE map variable on the Map-variables page (its "placeholder"): the page's map is the
 * reference, and the workspace map starts with its default colours. This icon opens a small card with the token (to copy into a
 * template), the page's description, default swatches and thumbnail, a reset to the placeholder look, and — for template
 * designers and super-admins only, because the page is restricted to them — a link to the page.
 *
 * The card's content mounts only when it is opened, so a closed icon costs nothing (no request, no provider needed).
 */
import { useEffect, useState } from 'react';
import { Popover, Spin, message } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import i18n from '../i18n';
import { useAuth } from '../contexts/AuthContext';
import { operationalPlanApi } from '../services/api';
import { analysisMapDef, analysisRendererKey, hasCustomColours, placeholderToken, type AnalysisMapId } from '../lib/analysisMaps';
import type { RendererSpec } from '../lib/layerRenderers';

const DESIGNER_ROLES = ['super_admin', 'template_designer'];

interface MapVarRow {
  key: string;
  label_ne: string;
  label_en: string;
  description_ne: string;
  description_en: string;
  section_en: string;
  section_ne: string;
  palette_swatch: string[];
}

/** Can this role open the Map-variables page? (Mirrors the route guard in App.tsx.) */
export const canOpenMapVariablesPage = (role: string | undefined | null): boolean => !!role && DESIGNER_ROLES.includes(role);

function Thumbnail({ token }: { token: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    let obj: string | null = null;
    operationalPlanApi
      .mapVariablePreviewObjectUrl(token)
      .then((u: string) => (live ? ((obj = u), setUrl(u)) : URL.revokeObjectURL(u)))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [token]);
  if (failed) return null;
  if (!url) return <div style={{ height: 90, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin size="small" /></div>;
  return <img src={url} alt="" style={{ width: '100%', borderRadius: 4, display: 'block', background: '#fafafa' }} />;
}

function Card({ id, calculationId }: { id: AnalysisMapId; calculationId?: string }) {
  const t = useT();
  const store = useWorkspaceStore();
  const { user } = useAuth();
  const token = placeholderToken(id)!;
  const ne = String(i18n.language || '').startsWith('ne');
  const def = analysisMapDef(id);
  const { data } = useQuery({
    queryKey: ['map-variables'],
    queryFn: async () => (await operationalPlanApi.listMapVariables()) as { variables?: MapVarRow[]; items?: MapVarRow[] } | MapVarRow[],
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  const list: MapVarRow[] = Array.isArray(data) ? data : (data?.variables ?? data?.items ?? []);
  const row = list.find((r) => r.key === token);
  const saved = store.layerRenderers as Record<string, RendererSpec | undefined>;
  const custom = hasCustomColours(id, saved);
  const name = (row && (ne ? row.label_ne : row.label_en)) || t(def?.labelKey ?? '', { defaultValue: def?.fallbackLabel });
  const description = row && (ne ? row.description_ne : row.description_en);
  return (
    <div style={{ width: 260, fontSize: 12 }} data-testid={`placeholder-card-${id}`}>
      <div style={{ fontWeight: 600, marginBottom: 2 }}>{name}</div>
      {row?.section_en && <div style={{ opacity: 0.65, marginBottom: 4 }}>{ne ? row.section_ne : row.section_en}</div>}
      {description && <div style={{ marginBottom: 6 }}>{description}</div>}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <code data-testid="placeholder-token" style={{ flex: 1, wordBreak: 'break-all' }}>{token}</code>
        <button
          type="button"
          className="analysis-link"
          onClick={() => {
            void navigator.clipboard?.writeText(token).then(() => message.success(t('analysisMaps.placeholder.copied', { defaultValue: 'Copied' })));
          }}
        >
          {t('analysisMaps.placeholder.copy', { defaultValue: 'Copy' })}
        </button>
      </div>
      {row?.palette_swatch?.length ? (
        <div style={{ display: 'flex', gap: 2, marginBottom: 6 }} aria-hidden="true">
          {row.palette_swatch.map((c, i) => <span key={i} style={{ width: 16, height: 10, background: c, border: '1px solid #ccc' }} />)}
        </div>
      ) : null}
      {/* the page's own thumbnail: default colours, never this forest's recoloured map — the placeholder is the reference */}
      <Thumbnail token={token} />
      <div className="analysis-note" style={{ margin: '6px 0' }}>
        {t('analysisMaps.placeholder.note', { defaultValue: 'This is the map variable the layer stands for. Your colours here never change its default.' })}
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="analysis-link"
          disabled={!custom}
          onClick={() => store.setLayerRenderer(analysisRendererKey(id), null)}
          data-testid="placeholder-reset"
        >
          {t('analysisMaps.placeholder.reset', { defaultValue: 'Reset to placeholder look' })}
        </button>
        {canOpenMapVariablesPage(user?.role) && (
          <a
            className="analysis-link"
            href={`/templates/map-variables?${calculationId ? `calc_id=${calculationId}&` : ''}q=${encodeURIComponent(token)}`}
            target="_blank"
            rel="noreferrer"
            data-testid="placeholder-open-page"
          >
            {t('analysisMaps.placeholder.openPage', { defaultValue: 'Open on the Map-variables page' })}
          </a>
        )}
      </div>
    </div>
  );
}

export function PlaceholderIcon({ id, calculationId }: { id: AnalysisMapId; calculationId?: string }) {
  const t = useT();
  const custom = useWorkspaceStore((s) => hasCustomColours(id, s.layerRenderers as Record<string, RendererSpec | undefined>));
  if (!placeholderToken(id)) return null;
  return (
    <Popover
      trigger="click"
      placement="right"
      content={<Card id={id} calculationId={calculationId} />}
      destroyOnHidden
    >
      <button
        type="button"
        className={`placeholder-icon${custom ? ' placeholder-icon-custom' : ''}`}
        aria-label={t('analysisMaps.placeholder.aria', { defaultValue: 'Map variable placeholder' })}
        title={custom
          ? t('analysisMaps.placeholder.customTitle', { defaultValue: 'Map variable placeholder — your colours differ from the default' })
          : t('analysisMaps.placeholder.title', { defaultValue: 'Map variable placeholder' })}
        data-testid={`placeholder-icon-${id}`}
      >
        🗺
      </button>
    </Popover>
  );
}
