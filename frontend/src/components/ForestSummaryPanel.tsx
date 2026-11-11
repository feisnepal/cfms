/** The Forest summary: a floating panel over the map with the forest-wide picture (verdict, eight headline tiles, five
 *  themes) and the Decisions needed tab. Every figure comes from the server (the same data as the OP document); the panel
 *  only lays it out. It follows the workspace's Forest / User group choice. */
import { useEffect, useRef, useState } from 'react';
import api from '../services/api';
import { downloadFromApi } from '../utils/download';
import { useTranslation } from 'react-i18next';
import { useT } from '../i18n/hooks';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useFloatingPanelState } from '../hooks/useFloatingPanelState';
import { useDecisions, useForestSummary } from '../hooks/useForestSummary';
import { analysisMapFor, formatValue, localDigits, unitKey, unitLabel, type NumeralLang, type SummaryTile } from '../lib/forestSummary';
import { DecisionsTab } from './DecisionsTab';
import { FloatingPanel } from './FloatingPanel';

const DEFAULT_STATE = { position: { x: 16, y: 16 }, collapsed: false, open: true };
type Tab = 'summary' | 'decisions';

function TileValue({ tile, lang }: { tile: SummaryTile; lang: NumeralLang }) {
  const t = useT();
  if (tile.state === 'forest_only') return <b>{t('forestSummary.forestOnly')}</b>;
  if (tile.state !== 'ready' || tile.value == null) {
    return (
      <b className="fs-na">
        {t('forestSummary.notComputed')}
        {tile.source_step != null ? ` (${t('forestSummary.step', { defaultValue: 'step' })} ${localDigits(tile.source_step, lang)})` : ''}
      </b>
    );
  }
  return (
    <b>
      {formatValue(tile.value, lang)} <small>{unitKey(tile.unit) ? t(`forestSummary.units.${unitKey(tile.unit)}`, { defaultValue: unitLabel(tile.unit) }) : unitLabel(tile.unit)}</small>
      {tile.of != null ? <small> / {formatValue(tile.of, lang)}</small> : null}
    </b>
  );
}

export function ForestSummaryPanel({ calculationId }: { calculationId: string }) {
  const t = useT();
  const { i18n } = useTranslation();
  const lang: NumeralLang = i18n.language?.toLowerCase().startsWith('ne') ? 'ne' : 'en';
  const store = useWorkspaceStore();
  const open = store.forestSummaryOpen;
  const area = store.analysisArea;
  const [tab, setTab] = useState<Tab>('summary');
  const [openThemes, setOpenThemes] = useState<Record<string, boolean>>({ hazard: true });
  const [exportNote, setExportNote] = useState<'copied' | 'copyFailed' | 'downloadFailed' | null>(null);

  const panel = useFloatingPanelState(`forest-summary:${calculationId}`, DEFAULT_STATE);
  const { summary, status } = useForestSummary(calculationId, area, lang, store.geometryVersion, open);
  const decisions = useDecisions(calculationId, open);

  // What was saved wins the first time it loads (a panel the user closed stays closed); after that the store decides and
  // the choice is saved, so reopening it from the layer panel is remembered too.
  const savedOpen = panel.state.open;
  const syncedOpen = useRef(false);
  useEffect(() => {
    if (!panel.loaded) return;
    if (!syncedOpen.current) {
      syncedOpen.current = true;
      if (savedOpen === false && open) store.setForestSummaryOpen(false);
      return;
    }
    if (open !== savedOpen) panel.update({ open });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panel.loaded, open, savedOpen]);

  if (!open) return null;

  const showOnMap = (sourceMap: string | null) => {
    const id = analysisMapFor(sourceMap);
    if (id) store.setActiveAnalysisMap(id);
  };
  const title = t('forestSummary.title');
  const exportUrl = `/api/calculations/${calculationId}/forest-summary/export`;
  const canExport = status === 'ready' && summary?.state === 'ready';
  const copyText = async () => {
    try {
      const r = await api.get<string>(exportUrl, { params: { area, lang }, responseType: 'text' });
      await navigator.clipboard.writeText(String(r.data).replace(/^\uFEFF/, ''));
      setExportNote('copied');
    } catch {
      setExportNote('copyFailed'); // clipboard refused (older app views) or the request failed: Download still works
    }
  };
  const downloadText = async () => {
    try {
      await downloadFromApi(exportUrl, 'ForestSummary_Report.txt', { area, lang });
      setExportNote(null);
    } catch {
      setExportNote('downloadFailed');
    }
  };
  const openCount = decisions.data?.open_count ?? 0;

  return (
    <FloatingPanel
      title={title}
      position={panel.state.position}
      onPositionChange={(position) => panel.update({ position })}
      collapsed={panel.state.collapsed}
      onCollapsedChange={(collapsed) => panel.update({ collapsed })}
      onClose={() => {
        store.setForestSummaryOpen(false);
        panel.update({ open: false });
      }}
      testId="forest-summary-panel"
      labels={{
        collapse: t('forestSummary.collapse', { defaultValue: 'Collapse' }),
        expand: t('forestSummary.expand', { defaultValue: 'Expand' }),
        close: t('forestSummary.close', { defaultValue: 'Close' }),
        move: t('forestSummary.move', { defaultValue: 'Move (drag, or use the arrow keys)' }),
      }}
    >
      <div className="fs-toolbar">
        <div className="fs-seg" role="group" aria-label={t('analysisMaps.area', { defaultValue: 'Area' })}>
          {(['forest', 'user_group'] as const).map((a) => (
            <button key={a} type="button" aria-pressed={area === a} onClick={() => store.setAnalysisArea(a)}>
              {a === 'forest' ? t('forestSummary.areaForest') : t('forestSummary.areaUserGroup')}
            </button>
          ))}
        </div>
        {canExport && (
          <div className="fs-export">
            <button type="button" onClick={() => void copyText()}>{t('forestSummary.copyText')}</button>
            <button type="button" onClick={() => void downloadText()}>{t('forestSummary.downloadText')}</button>
          </div>
        )}
      </div>
      {exportNote && (
        <div className="fs-note" role="status" data-testid="export-note">
          {exportNote === 'copied'
            ? t('forestSummary.copied', { defaultValue: 'Copied.' })
            : exportNote === 'copyFailed'
              ? t('forestSummary.copyFailed', { defaultValue: 'Could not copy. Use Download instead.' })
              : t('forestSummary.downloadFailed', { defaultValue: 'Could not download the file.' })}
        </div>
      )}

      <div className="fs-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'summary'} onClick={() => setTab('summary')}>
          {t('forestSummary.tabSummary')}
        </button>
        <button type="button" role="tab" aria-selected={tab === 'decisions'} onClick={() => setTab('decisions')}>
          {t('forestSummary.tabDecisions')}
          {openCount > 0 && <span className="fs-badge" data-testid="decisions-badge">{localDigits(openCount, lang)}</span>}
        </button>
      </div>

      {tab === 'decisions' ? (
        <DecisionsTab lang={lang} data={decisions.data} status={decisions.status} saving={decisions.saving} saveError={decisions.saveError} answer={decisions.answer} />
      ) : status === 'forbidden' ? (
        <div className="fs-note" role="alert">{t('forestSummary.forbidden', { defaultValue: 'You cannot open this forest.' })}</div>
      ) : status === 'error' ? (
        <div className="fs-note" role="alert">{t('forestSummary.failed', { defaultValue: 'Could not load the summary.' })}</div>
      ) : !summary || status === 'loading' || status === 'preparing' || summary.state !== 'ready' ? (
        <div className="fs-note" role="status">
          {status === 'preparing' ? t('forestSummary.preparing') : t('forestSummary.loading', { defaultValue: 'Loading…' })}
        </div>
      ) : (
        <div className="fs-summary" data-testid="forest-summary">
          {summary.verdict && <p className="fs-verdict" data-testid="forest-summary-verdict">{summary.verdict}</p>}
          <div className="fs-tiles">
            {summary.tiles.map((tile) => (
              <button
                key={tile.key}
                type="button"
                className={`fs-tile${tile.state === 'ready' ? '' : ' fs-tile--na'}`}
                data-testid={`tile-${tile.key}`}
                disabled={!analysisMapFor(tile.source_map)}
                onClick={() => showOnMap(tile.source_map)}
                title={analysisMapFor(tile.source_map) ? t('forestSummary.showOnMap') : undefined}
              >
                <TileValue tile={tile} lang={lang} />
                <span>
                  {t(`forestSummary.tiles.${tile.key}`)}
                  {tile.key === 'area' && tile.unit_count ? ` · ${localDigits(tile.unit_count, lang)}` : ''}
                </span>
              </button>
            ))}
          </div>
          <div className="fs-themes">
            {summary.themes.map((theme) => {
              const expanded = !!openThemes[theme.key];
              const headline = theme.rows.find((r) => r.key === theme.headline) ?? theme.rows[0];
              const mapId = theme.rows.map((r) => analysisMapFor(r.source_map)).find(Boolean) ?? null;
              return (
                <div key={theme.key} className="fs-theme" data-testid={`theme-${theme.key}`}>
                  <button
                    type="button"
                    className="fs-theme__head"
                    aria-expanded={expanded}
                    onClick={() => setOpenThemes((o) => ({ ...o, [theme.key]: !expanded }))}
                  >
                    <span aria-hidden="true" className="floating-panel__chevron" style={{ transform: expanded ? 'none' : 'rotate(-90deg)' }}>▾</span>
                    <b>{t(`forestSummary.themes.${theme.key}`)}</b>
                    {headline && <span className="fs-theme__sum"><TileValue tile={headline} lang={lang} /></span>}
                  </button>
                  {expanded && (
                    <div className="fs-theme__body">
                      {theme.rows.map((row) => (
                        <div key={row.key} className="fs-row">
                          <span>{t(row.key in { households: 1, soil_loss: 1, priority_households: 1, condition_moderate: 1, condition_weak: 1 } ? `forestSummary.rows.${row.key}` : `forestSummary.tiles.${row.key}`)}</span>
                          <TileValue tile={row} lang={lang} />
                        </div>
                      ))}
                      {mapId && <button type="button" className="fs-link" onClick={() => store.setActiveAnalysisMap(mapId)}>{t('forestSummary.showOnMap')}</button>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="fs-basis" data-testid="forest-summary-basis">
            {t('forestSummary.basis')}: {summary.basis?.collected_at ? localDigits(summary.basis.collected_at.slice(0, 10), lang) : '—'}
            {summary.basis?.hazard_method === 'quantile' ? ` · ${t('forestSummary.relativeNote', { defaultValue: 'Landslide classes are relative to this forest.' })}` : ''}
          </div>
        </div>
      )}
    </FloatingPanel>
  );
}
