/** The fire-line tick-list (FIRELINE_RIVERBANK_PLAN.md, FL-5).
 *
 *  Every boundary between two units and every road inside the forest is a fire line by default (option B); here the owner unticks
 *  the ones that are not, draws a line of their own with a width for every segment, and changes widths afterwards. Ticks are
 *  staged and applied in one batch, so the totals can move live without a server round trip per click. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import L from 'leaflet';
import { fireLineApi, riverBankApi, type FireLineDrawn, type FireLinePlanActivity, type FireLinePlanResult, type FireLineRow, type FireLineSummary } from '../services/api';
import { useT } from '../i18n/hooks';
import { FloatingPanel } from './FloatingPanel';
import { FireLineDrawEditor } from './FireLineDrawEditor';
import './FireLinePanel.css';
import {
  KIND_DEFAULT_SIDE, KIND_GROUPS, chainOrder, groupByPair, type PairGroup, errorMessage, filterRows, pendingChanges, projectedTotals, stageAll, statusMessage, wanted,
  type Group, type StripKind,
} from '../lib/fireLines';

export interface FireLinePanelProps {
  /** which strip this panel edits: fire lines (the default) or river banks */
  kind?: StripKind;
  map: L.Map | null;
  calculationId: string;
  structureLocked?: boolean;
  onClose: () => void;
  /** the stored fire lines changed: reload the map layers */
  onChanged: () => void;
}

const SIZES = ['m', 'l', 'xl'] as const;
const SIZE_WIDTH: Record<(typeof SIZES)[number], number> = { m: 440, l: 620, xl: 840 };
const GUIDE_SEEN_KEY = 'fireLinePanel.guideSeen';

type Editing =
  | { mode: 'create'; centerline: GeoJSON.LineString }
  | { mode: 'edit'; centerline: GeoJSON.LineString; stripId: string; widths: number[]; name: string };

export function FireLinePanel({ kind = 'fire_line', map, calculationId, structureLocked = false, onClose, onChanged }: FireLinePanelProps) {
  const t = useT();
  const river = kind === 'river_bank';
  const api = river ? riverBankApi : fireLineApi;
  // the words that differ for a river bank live under riverBanks.*; everything else is shared
  const w = (key: string, params?: Record<string, unknown>) => t(`${river ? 'riverBanks' : 'fireLines'}.${key}`, params);
  const groups: Group[] = KIND_GROUPS[kind];
  const [data, setData] = useState<FireLineSummary | null>(null);
  const [staged, setStaged] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [position, setPosition] = useState({ x: 16, y: 72 });
  const [collapsed, setCollapsed] = useState(false);
  const [size, setSize] = useState<(typeof SIZES)[number]>('m');
  // the corner grip gives a free size; the size button goes back to a preset width with automatic height
  const [dragged, setDragged] = useState<{ width: number; height: number } | null>(null);
  const panelWidth = Math.min(dragged?.width ?? SIZE_WIDTH[size], Math.max(320, window.innerWidth - 32));
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  // the short guide opens by itself the first time; the "How this works" chip brings it back
  const [guideOpen, setGuideOpen] = useState(() => {
    try { return window.localStorage.getItem(GUIDE_SEEN_KEY) !== '1'; } catch { return true; }
  });
  const u = (key: string, params?: Record<string, unknown>) => t(`fireLines.ui.${key}`, { thing: w('ui.thing'), things: w('ui.things'), ...params });
  // the yearly plan: give the fire lines a plan line, starting at each strip's own length
  const [planOpen, setPlanOpen] = useState(false);
  const [activities, setActivities] = useState<FireLinePlanActivity[] | null>(null);
  const [activityId, setActivityId] = useState<number | ''>('');
  const [includeRoads, setIncludeRoads] = useState(false);
  const [planResult, setPlanResult] = useState<FireLinePlanResult | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.list(calculationId));
      setError(null);
    } catch (err) {
      setError(errorMessage(err, t('fireLines.loadFailed')));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId]);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = data?.rows ?? [];
  const shown = useMemo(() => filterRows(rows, filter), [rows, filter]);
  const changes = useMemo(() => pendingChanges(rows, staged), [rows, staged]);
  const totals = useMemo(() => projectedTotals(rows, staged), [rows, staged]);
  const status = statusMessage(data?.status);

  const run = async (job: () => Promise<FireLineSummary | void>, afterStage = false) => {
    setBusy(true);
    setError(null);
    try {
      const next = await job();
      if (next) setData(next);
      if (afterStage) setStaged({});
      onChanged();
    } catch (err) {
      setError(errorMessage(err, t('fireLines.saveFailed')));
    } finally {
      setBusy(false);
    }
  };

  const apply = () => run(() => api.decide(calculationId, changes), true);

  const openPlan = async () => {
    const next = !planOpen;
    setPlanOpen(next);
    setPlanResult(null);
    if (next && activities === null) {
      try {
        const { activities: list } = await fireLineApi.planOptions(calculationId);
        setActivities(list);
        if (list.length === 1) setActivityId(list[0].id);
      } catch (err) {
        setActivities([]);
        setError(errorMessage(err, t('fireLines.loadFailed')));
      }
    }
  };

  const createPlanLines = async () => {
    if (activityId === '') return;
    setBusy(true);
    setError(null);
    try {
      setPlanResult(await fireLineApi.plan(calculationId, { potential_activity_id: Number(activityId), include_roads: includeRoads }));
    } catch (err) {
      setError(errorMessage(err, t('fireLines.saveFailed')));
    } finally {
      setBusy(false);
    }
  };
  const regenerate = () => run(() => api.regenerate(calculationId));

  // ---- the ticked lines are drawn on the map (centre lines, in the strip colour); ticking a row also brings its line into view
  const [focusKeys, setFocusKeys] = useState<string[]>([]);
  const [pickKey, setPickKey] = useState<string | null>(null);
  useEffect(() => {
    if (!map) return undefined;
    const colour = river ? '#1e40af' : '#c62828';
    const group = L.layerGroup();
    for (const r of rows) {
      const line = r.centerline as GeoJSON.LineString | null | undefined;
      if (!line?.coordinates?.length || !wanted(r, staged)) continue;
      const focus = focusKeys.includes(r.unit_key);
      L.polyline(line.coordinates.map(([x, y]) => [y, x] as [number, number]), {
        color: focus ? '#ffb300' : colour, weight: focus ? 6 : 4, opacity: 0.95, interactive: false,
      }).addTo(group);
    }
    group.addTo(map);
    return () => { group.remove(); };
  }, [map, rows, staged, focusKeys, river]);

  const showPair = (members: FireLineRow[]) => {
    setFocusKeys(members.map((m) => m.unit_key));
    const pts = members.flatMap((m) => ((m.centerline as GeoJSON.LineString | null | undefined)?.coordinates ?? []).map(([x, y]) => [y, x] as [number, number]));
    if (!map || !pts.length) return;
    const bounds = L.latLngBounds(pts);
    if (bounds.isValid() && !map.getBounds().contains(bounds)) map.fitBounds(bounds, { padding: [80, 80], maxZoom: 18 });
  };

  // ---- drawing: one Geoman line, then the editor takes over
  const stopDraw = useCallback(() => {
    if (!map) return;
    const pm = (map as unknown as { pm?: { disableDraw?: (shape?: string) => void } }).pm;
    pm?.disableDraw?.('Line');
    map.off('pm:create');
    setDrawing(false);
  }, [map]);

  const startDraw = () => {
    if (!map) return;
    const pm = (map as unknown as { pm?: { enableDraw?: (shape: string, opts?: object) => void } }).pm;
    if (!pm?.enableDraw) return;
    setEditing(null);
    setDrawing(true);
    pm.enableDraw('Line', { finishOn: 'dblclick', snappable: false, templineStyle: { color: '#c62828' }, hintlineStyle: { color: '#c62828', dashArray: [5, 5] } });
    map.once('pm:create', (e: { layer?: L.Polyline }) => {
      const layer = e.layer;
      if (!layer) return;
      const line = (layer.toGeoJSON() as GeoJSON.Feature<GeoJSON.LineString>).geometry;
      layer.remove();
      setDrawing(false);
      if (line?.coordinates?.length >= 2) setEditing({ mode: 'create', centerline: line });
    });
  };

  useEffect(() => stopDraw, [stopDraw]);

  const finished = () => {
    setEditing(null);
    void load();
    onChanged();
  };

  const renderPair = (p: PairGroup) => {
    const members = p.rows;
    const on = members.filter((m) => wanted(m, staged)).length;
    const editable = members.filter((m) => m.strip_id && m.centerline);
    const edit = (m: FireLineRow) => setEditing({ mode: 'edit', centerline: m.centerline as GeoJSON.LineString, stripId: m.strip_id as string, widths: m.segment_widths_m ?? [], name: m.name });
    return (
      <li key={p.key} className="flp-row" data-testid="fire-line-row">
        <input
          type="checkbox"
          aria-label={p.name}
          title={u('tip.row')}
          checked={on === members.length}
          ref={(el) => { if (el) el.indeterminate = on > 0 && on < members.length; }}
          disabled={structureLocked || busy}
          onChange={() => { const next = on !== members.length; if (next) showPair(members); setStaged((s) => stageAll(members, s, next)); }}
        />
        <span className="flp-row__name" title={u('tip.name')} onClick={() => showPair(members)}>{p.name}</span>
        {members.some((m) => m.edited) && <span className="flp-tag">{t('fireLines.edited')}</span>}
        {members.length > 1 && <span className="flp-tag">{u('pieces', { n: members.length })}</span>}
        <span className="flp-row__len">{Math.round(p.length_m)} m · {p.area_ha.toFixed(3)} ha</span>
        {editable.length > 0 && !structureLocked && (
          <button
            type="button"
            className="flp-mini"
            data-testid="fire-line-widths"
            title={u('tip.widths')}
            onClick={() => (editable.length === 1 ? edit(editable[0]) : setPickKey(pickKey === p.key ? null : p.key))}
          >
            {t('fireLines.widths')}
          </button>
        )}
        {pickKey === p.key && editable.length > 1 && (
          <span className="flp-pieces">
            <small>{u('piecesPick')}</small>
            {editable.map((m, n) => (
              <button key={m.unit_key} type="button" className="flp-mini" data-testid="fire-line-piece" onClick={() => { setPickKey(null); edit(m); }}>
                {n + 1} · {Math.round(m.length_m)} m
              </button>
            ))}
          </span>
        )}
      </li>
    );
  };

  const renderDrawn = (d: FireLineDrawn) => (
    <li key={d.strip_id} className="flp-row" data-testid="fire-line-drawn">
      <span className="flp-row__name">{d.name}</span>
      <span className="flp-row__len">{Math.round(d.length_m)} m · {d.area_ha.toFixed(3)} ha</span>
      {d.centerline && !structureLocked && (
        <button type="button" className="flp-mini" title={u('tip.widths')} onClick={() => setEditing({ mode: 'edit', centerline: d.centerline as GeoJSON.LineString, stripId: d.strip_id, widths: d.segment_widths_m, name: d.name })}>
          {t('fireLines.widths')}
        </button>
      )}
    </li>
  );

  const stepNames = river ? (['review', 'apply', 'edit'] as const) : (['review', 'apply', 'edit', 'plan'] as const);
  const guideSteps = ['s1', 's2', 's3', 's4'] as const;
  const stepNow = status ? 0 : changes.length ? 1 : 2;
  const sizeIndex = Math.max(0, SIZES.indexOf(size));
  const dockLeft = () => setPosition({ x: 16, y: position.y });
  const dockRight = () => setPosition({ x: Math.max(16, window.innerWidth - panelWidth - 16), y: position.y });
  const closeGuide = () => {
    setGuideOpen(false);
    try { window.localStorage.setItem(GUIDE_SEEN_KEY, '1'); } catch { /* private window: the guide simply shows again */ }
  };

  return (
    <FloatingPanel
      title={w('title')}
      position={position}
      onPositionChange={setPosition}
      collapsed={collapsed}
      onCollapsedChange={setCollapsed}
      onClose={() => {
        stopDraw();
        onClose();
      }}
      testId="fire-line-panel"
      width={panelWidth}
      height={dragged?.height ?? null}
      onResize={setDragged}
      resizeLabel={u('tip.resize')}
      viewport
    >
      <div className={`flp${river ? ' flp--river' : ''}`}>
        <div className="flp-toolbar">
          <button type="button" className={`flp-chip${guideOpen ? ' flp-chip--on' : ''}`} data-testid="fire-line-guide-toggle" aria-pressed={guideOpen} title={u('tip.guide')} onClick={() => (guideOpen ? closeGuide() : setGuideOpen(true))}>
            ❓ {u('guideOpen')}
          </button>
          <span className="flp-toolbar__spacer" />
          <button type="button" className="flp-chip" data-testid="fire-line-dock-left" title={u('tip.dockLeft')} aria-label={u('tip.dockLeft')} onClick={dockLeft}>◧</button>
          <button type="button" className="flp-chip" data-testid="fire-line-dock-right" title={u('tip.dockRight')} aria-label={u('tip.dockRight')} onClick={dockRight}>◨</button>
          <button type="button" className="flp-chip" data-testid="fire-line-size" title={u('tip.size')} aria-label={u('tip.size')} onClick={() => { setDragged(null); setSize(SIZES[(sizeIndex + 1) % SIZES.length]); }}>⤢</button>
        </div>

        <ol className="flp-steps" title={u('stepTip')} data-testid="fire-line-steps">
          {stepNames.map((s, i) => (
            <li key={s} className={`flp-step${i === stepNow ? ' flp-step--active' : ''}`} aria-current={i === stepNow ? 'step' : undefined}>
              <span className="flp-step__n">{i + 1}</span>
              <span className="flp-step__t">{u(`steps.${s}`)}</span>
            </li>
          ))}
        </ol>

        {guideOpen && (
          <section className="flp-guide" data-testid="fire-line-guide">
            <h4 className="flp-guide__title">{u('guideTitle')}</h4>
            <div className="flp-guide__grid">
              {guideSteps.map((s, i) => (
                <div key={s} className="flp-guide__card">
                  <b>{['✅', '💾', '✏️', river ? '🛡️' : '📅'][i]} {i + 1}. {i === 3 ? w(`ui.${s}t`) : u(`${s}t`)}</b>
                  <p>{i === 3 ? w(`ui.${s}`) : u(s)}</p>
                </div>
              ))}
            </div>
            <p className="flp-guide__tip">🎨 {u('tipMap')}</p>
            <p className="flp-guide__tip">🔗 {u('tipOrder')}</p>
            <button type="button" className="flp-mini" data-testid="fire-line-guide-close" onClick={closeGuide} style={{ alignSelf: 'flex-end' }}>{u('guideGot')}</button>
          </section>
        )}

        <p className="flp-intro">{w('intro')}</p>
        {status && <div role="status" className="flp-status" data-testid="fire-line-status">⚠️ {t(river ? status.key.replace('fireLines.', 'riverBanks.') : status.key, status.params)}</div>}
        {error && <div role="alert" className="flp-error">{error}</div>}

        <div className="flp-totals" data-testid="fire-line-totals">
          {groups.filter((g) => totals[g].count > 0 || rows.some((r) => r.group === g)).map((g: Group) => (
            <div key={g} className="flp-total">
              <b>{w(`group.${g}`)}</b>: {w('totals', { count: totals[g].count, km: totals[g].km.toFixed(2), ha: totals[g].ha.toFixed(3) })}
            </div>
          ))}
          {data?.totals.drawn && (
            <div className="flp-total"><b>{w('group.drawn')}</b>: {w('totals', { count: data.totals.drawn.count, km: data.totals.drawn.km.toFixed(2), ha: data.totals.drawn.ha.toFixed(3) })}</div>
          )}
        </div>

        <div className="flp-filter">
          <input data-testid="fire-line-filter" placeholder={t('fireLines.filter')} title={u('tip.filter')} value={filter} onChange={(e) => setFilter(e.target.value)} />
          <button type="button" className="flp-chip" data-testid="fire-line-select-all" title={u('tip.selectAll')} disabled={structureLocked || busy} onClick={() => setStaged((s) => stageAll(shown, s, true))}>{t('fireLines.selectAll')}</button>
          <button type="button" className="flp-chip" data-testid="fire-line-select-none" title={u('tip.selectNone')} disabled={structureLocked || busy} onClick={() => setStaged((s) => stageAll(shown, s, false))}>{t('fireLines.selectNone')}</button>
        </div>

        {data && rows.length === 0 && !status && <div className="flp-hint">{t('fireLines.none')} {u('empty')}</div>}
        {groups.map((g) => {
          const inGroup = chainOrder(shown.filter((r) => r.group === g));
          if (!inGroup.length) return null;
          const groupRows = rows.filter((r) => r.group === g);
          const nOn = groupRows.filter((r) => wanted(r, staged)).length;
          const pairs = groupByPair(groupRows);
          const pairsOn = pairs.filter((p) => p.rows.some((m) => wanted(m, staged))).length;
          const closed = !!folded[g];
          return (
            <section key={g} className="flp-group" data-testid={`fire-line-group-${g}`}>
              <div className="flp-group__head">
                <label title={u('tip.groupTick')}>
                  <input
                    type="checkbox"
                    data-testid={`fire-line-group-tick-${g}`}
                    aria-label={w(`group.${g}`)}
                    checked={nOn === groupRows.length}
                    ref={(el) => { if (el) el.indeterminate = nOn > 0 && nOn < groupRows.length; }}
                    disabled={structureLocked || busy}
                    onChange={() => setStaged((s) => stageAll(groupRows, s, nOn !== groupRows.length))}
                  />
                  <span className={`flp-dot flp-dot--${g}`} />
                  <b>{w(`group.${g}`)}</b>
                </label>
                <span className="flp-badge" title={u('groupCount', { on: pairsOn, all: pairs.length })}>{pairsOn}/{pairs.length}</span>
                <button type="button" className={`flp-fold${closed ? ' flp-fold--closed' : ''}`} aria-expanded={!closed} title={u('tip.fold')} aria-label={u('tip.fold')} onClick={() => setFolded((f) => ({ ...f, [g]: !f[g] }))}>
                  <span className="flp-fold__chev" aria-hidden="true">▾</span>
                </button>
              </div>
              {!closed && <ul className="flp-list">{groupByPair(inGroup).map(renderPair)}</ul>}
            </section>
          );
        })}

        {(data?.drawn.length ?? 0) > 0 && (
          <section className="flp-group" data-testid="fire-line-group-drawn">
            <div className="flp-group__head">
              <span className="flp-dot flp-dot--drawn" />
              <b style={{ flex: 1 }}>{w('group.drawn')}</b>
            </div>
            <ul className="flp-list">{data?.drawn.map(renderDrawn)}</ul>
          </section>
        )}

        {drawing && <p className="flp-hint" data-testid="fire-line-draw-hint">{t('fireLines.drawEditor.hint')}</p>}

        {!river && planOpen && (
          <div className="flp-plan" data-testid="fire-line-plan">
            <p className="flp-hint">{t('fireLines.plan.intro')}</p>
            {activities !== null && activities.length === 0 && <div data-testid="fire-line-plan-none">{t('fireLines.plan.none')}</div>}
            {activities !== null && activities.length > 0 && (
              <>
                <label style={{ display: 'block' }}>
                  {t('fireLines.plan.activity')}
                  <select data-testid="fire-line-plan-activity" value={activityId} onChange={(e) => setActivityId(e.target.value === '' ? '' : Number(e.target.value))} style={{ width: '100%' }}>
                    <option value="" />
                    {activities.map((a) => <option key={a.id} value={a.id}>{a.activity} ({a.unit})</option>)}
                  </select>
                </label>
                <label style={{ display: 'block' }}>
                  <input type="checkbox" data-testid="fire-line-plan-roads" checked={includeRoads} onChange={(e) => setIncludeRoads(e.target.checked)} /> {t('fireLines.plan.includeRoads')}
                </label>
                <button type="button" className="flp-mini" data-testid="fire-line-plan-create" disabled={busy || activityId === ''} onClick={createPlanLines}>
                  {t('fireLines.plan.create')}
                </button>
              </>
            )}
            {planResult && (
              <div data-testid="fire-line-plan-result" role="status">
                {t('fireLines.plan.result', { created: planResult.created, existing: planResult.existing, roads: planResult.skipped_roads })}
                {planResult.no_unit.length > 0 && <div>{t('fireLines.plan.noUnit', { n: planResult.no_unit.length })}</div>}
              </div>
            )}
          </div>
        )}

        <div className="flp-actions">
          <button type="button" className="flp-act flp-act--primary" data-testid="fire-line-apply" title={u('tip.apply')} disabled={!changes.length || busy || structureLocked} onClick={apply}>
            <span className="flp-act__icon" aria-hidden="true">💾</span>
            <span className="flp-act__text"><b>{t('fireLines.apply', { n: changes.length })}</b><small>{changes.length ? u('pending', { n: changes.length }) : u('hint.apply')}</small></span>
          </button>
          <button type="button" className="flp-act" data-testid="fire-line-reset" title={u('tip.reset')} disabled={!changes.length || busy} onClick={() => setStaged({})}>
            <span className="flp-act__icon" aria-hidden="true">↩️</span>
            <span className="flp-act__text"><b>{t('fireLines.reset')}</b><small>{u('hint.reset')}</small></span>
          </button>
          <button type="button" className="flp-act" data-testid="fire-line-regenerate" title={u('tip.regenerate')} disabled={busy || structureLocked} onClick={regenerate}>
            <span className="flp-act__icon" aria-hidden="true">🔄</span>
            <span className="flp-act__text"><b>{t('fireLines.regenerate')}</b><small>{u('hint.regenerate')}</small></span>
          </button>
          <button type="button" className="flp-act" data-testid="fire-line-draw" title={u('tip.draw')} disabled={busy || structureLocked || drawing || !map} onClick={startDraw}>
            <span className="flp-act__icon" aria-hidden="true">✏️</span>
            <span className="flp-act__text"><b>{w('draw')}</b><small>{u('hint.draw')}</small></span>
          </button>
          {!river && (
            <button type="button" className="flp-act" data-testid="fire-line-plan-toggle" aria-expanded={planOpen} title={u('tip.plan')} disabled={structureLocked} onClick={openPlan}>
              <span className="flp-act__icon" aria-hidden="true">📅</span>
              <span className="flp-act__text"><b>{t('fireLines.plan.open')}</b><small>{u('hint.plan')}</small></span>
            </button>
          )}
        </div>
      </div>

      {editing && (
        <FireLineDrawEditor
          key={editing.mode === 'edit' ? editing.stripId : 'new'}
          calculationId={calculationId}
          map={map}
          mode={editing.mode}
          centerline={editing.centerline}
          initialWidths={editing.mode === 'edit' ? editing.widths : undefined}
          initialName={editing.mode === 'edit' ? editing.name : undefined}
          stripId={editing.mode === 'edit' ? editing.stripId : null}
          api={api}
          defaultSide={KIND_DEFAULT_SIDE[kind]}
          createTitleKey={river ? 'riverBanks.drawEditorTitle' : 'fireLines.drawEditor.title'}
          onClose={() => setEditing(null)}
          onDone={finished}
        />
      )}
    </FloatingPanel>
  );
}
