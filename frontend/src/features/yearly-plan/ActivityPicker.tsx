import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Empty, Input, Space, Spin, Tag, Typography } from 'antd';
import { CheckCircleFilled, CloseCircleFilled, DownOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { formatNumber } from '../../i18n/numberFormat';
import { ACTIVITY_KINDS, activityKindLabel } from '../../lib/activityKinds';
import { ACTIVITY_KIND_ICONS } from '../../lib/activityKindIcons';
import { formatYears } from '../../lib/activityFeatureLabel';
import {
  buildActivityIndex,
  highlightSegments,
  searchActivities,
  suggestActivities,
  toCatalogueActivity,
  type CatalogueActivity,
  type RawPotentialActivity,
  type SearchHit,
} from '../../lib/activitySearch';
import {
  buildBrowseTree,
  countBy,
  filterHits,
  groupByProgramme,
  hasActiveFilters,
  mapPhrase,
  NO_FILTERS,
  programmeSlug,
  readRecent,
  rememberRecent,
  unitSlug,
  type MapPhrase,
  type PickerFilters,
} from './activityCatalogue';

const { Text } = Typography;

export interface ActivityPickerProps {
  /** The master list exactly as the API returns it. */
  activities: RawPotentialActivity[];
  /** Master-list id → the plan years it is planned in (empty = in the plan, years not known). */
  inPlan?: Record<number, number[]>;
  /** "Choose": add an activity that is not in the plan yet. */
  onChoose: (activity: CatalogueActivity) => void;
  /** "Open in plan": open an activity that already is a line of the plan. */
  onOpen?: (activity: CatalogueActivity) => void;
  loading?: boolean;
  /** The master list could not be loaded. */
  failed?: boolean;
  onRetry?: () => void;
  /** Master-list id whose "Choose" is running (its button spins, the rest stay usable). */
  busyId?: number | null;
  autoFocus?: boolean;
}

const HIGHLIGHT: React.CSSProperties = {
  background: '#fff1a8',
  color: 'inherit',
  padding: 0,
  borderRadius: 2,
};

/** A displayed text with the words the person typed marked. */
const Highlighted: React.FC<{ text: string; query: string }> = ({ text, query }) => (
  <>
    {highlightSegments(text, query).map((seg, i) =>
      seg.hit ? (
        <mark key={i} style={HIGHLIGHT}>
          {seg.text}
        </mark>
      ) : (
        <React.Fragment key={i}>{seg.text}</React.Fragment>
      ),
    )}
  </>
);

/** The map symbol as a small icon: the kind's own, a plain pin for "generic", a barred circle for "no map". */
const KindGlyph: React.FC<{ kind: string | null; none?: boolean; size?: number }> = ({ kind, none, size = 15 }) => {
  const meta = kind ? ACTIVITY_KINDS[kind] : undefined;
  const name = none ? 'ban' : (meta?.icon ?? 'mapPin');
  const color = none ? '#8c8c8c' : (meta?.color ?? '#1677ff');
  const nodes = ACTIVITY_KIND_ICONS[name] ?? ACTIVITY_KIND_ICONS.mapPin;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ flex: 'none' }}
    >
      {nodes.map(([tag, attrs], i) => React.createElement(tag, { ...attrs, key: i }))}
    </svg>
  );
};

const Chip: React.FC<{
  pressed: boolean;
  onClick: () => void;
  children: React.ReactNode;
  testId?: string;
}> = ({ pressed, onClick, children, testId }) => (
  <button
    type="button"
    aria-pressed={pressed}
    data-testid={testId}
    onClick={onClick}
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      minHeight: 36,
      padding: '4px 12px',
      borderRadius: 18,
      border: `1px solid ${pressed ? '#1677ff' : '#d9d9d9'}`,
      background: pressed ? '#e6f4ff' : '#fff',
      color: pressed ? '#0958d9' : 'inherit',
      fontWeight: pressed ? 600 : 400,
      cursor: 'pointer',
      fontSize: 13,
    }}
  >
    {pressed && <CheckCircleFilled aria-hidden="true" style={{ fontSize: 12 }} />}
    {children}
  </button>
);

export const ActivityPicker: React.FC<ActivityPickerProps> = ({
  activities,
  inPlan = {},
  onChoose,
  onOpen,
  loading,
  failed,
  onRetry,
  busyId = null,
  autoFocus,
}) => {
  const { t, i18n } = useTranslation();
  const isNepali = i18n.language?.startsWith('ne');
  const fmt = useCallback((n: number) => formatNumber(n), []);

  const index = useMemo(() => buildActivityIndex(activities.map(toCatalogueActivity)), [activities]);
  const total = index.items.length;

  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<PickerFilters>(NO_FILTERS);
  const [recent, setRecent] = useState<number[]>(() => readRecent());
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [showUnits, setShowUnits] = useState(false);
  const [showSymbols, setShowSymbols] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const isInPlan = useCallback((id: number) => Object.prototype.hasOwnProperty.call(inPlan, id), [inPlan]);
  const ctx = useMemo(() => ({ inPlan: isInPlan, recent }), [isInPlan, recent]);

  // What the typing found, before the chips narrow it (the chips' counts are read from this).
  const queryHits = useMemo(() => searchActivities(index, query), [index, query]);
  const hits = useMemo(() => filterHits(queryHits, filters, ctx), [queryHits, filters, ctx]);

  const searching = query.trim() !== '' || hasActiveFilters(filters);
  const nothingFound = searching && hits.length === 0;
  const showTree = !searching || nothingFound;

  const unitChips = useMemo(() => countBy(queryHits, (a) => a.unit || null), [queryHits]);
  const kindChips = useMemo(() => countBy(queryHits, (a) => a.mapKind), [queryHits]);

  const suggestions = useMemo(
    () => (nothingFound && query.trim() ? suggestActivities(index, query, 3) : []),
    [nothingFound, query, index],
  );

  const groups = useMemo(() => groupByProgramme(hits), [hits]);
  // The browse tree lists everything while nothing is typed, and — so a failed search is never a dead end —
  // everything again, fully opened, when nothing matches.
  const allHits = useMemo(() => searchActivities(index, ''), [index]);
  const tree = useMemo(() => buildBrowseTree(nothingFound ? allHits : hits), [nothingFound, allHits, hits]);

  // ---- which activities are on screen right now, in order (for the arrow keys)
  const treeKey = (project: string, programme: string) => `g:${project}|${programme}`;
  const isOpen = (key: string) => nothingFound || open.has(key);
  const visibleIds = useMemo(() => {
    const ids: number[] = [];
    if (!showTree) {
      groups.forEach((g) => g.hits.forEach((h) => ids.push(h.activity.id)));
    } else {
      tree.forEach((p) => {
        p.programmes.forEach((g) => {
          if (isOpen(treeKey(p.project, g.programme))) g.hits.forEach((h) => ids.push(h.activity.id));
        });
      });
    }
    return ids;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nothingFound, showTree, groups, tree, open]);

  // keep the active row valid and in view
  useEffect(() => {
    if (activeId !== null && !visibleIds.includes(activeId)) setActiveId(null);
  }, [visibleIds, activeId]);
  useEffect(() => {
    if (activeId === null) return;
    const el = listRef.current?.querySelector<HTMLElement>(`#ap-opt-${activeId}`);
    el?.scrollIntoView?.({ block: 'nearest' });
  }, [activeId]);

  const byId = useMemo(() => new Map(index.items.map((it) => [it.activity.id, it.activity])), [index]);

  const act = useCallback(
    (a: CatalogueActivity) => {
      if (isInPlan(a.id)) {
        onOpen?.(a);
        return;
      }
      setRecent(rememberRecent(a.id));
      onChoose(a);
    },
    [isInPlan, onChoose, onOpen],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (visibleIds.length === 0) return;
      e.preventDefault();
      const at = activeId === null ? -1 : visibleIds.indexOf(activeId);
      const next = e.key === 'ArrowDown' ? Math.min(at + 1, visibleIds.length - 1) : Math.max(at - 1, 0);
      setActiveId(visibleIds[next]);
    } else if (e.key === 'Enter') {
      const target = activeId ?? (query.trim() && !showTree ? visibleIds[0] : null);
      const a = target === null ? undefined : byId.get(target);
      if (a) {
        e.preventDefault();
        act(a);
      }
    } else if (e.key === 'Escape') {
      if (query !== '') {
        e.preventDefault();
        setQuery('');
        setActiveId(null);
      }
    }
  };

  const toggleOpen = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const expandAll = () => {
    const all = new Set<string>();
    tree.forEach((p) => p.programmes.forEach((g) => all.add(treeKey(p.project, g.programme))));
    setOpen(all);
  };
  const collapseAll = () => setOpen(new Set());

  const setFilter = (patch: Partial<PickerFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const toggleIn = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  // ---- pieces
  const unitText = (unit: string): string => {
    const slug = unitSlug(unit);
    return slug ? t(`yearlyPlan.find.unit.${slug}`) : t('yearlyPlan.find.unit.other', { unit });
  };
  const mapText = (p: MapPhrase) => t(`yearlyPlan.find.map.${p}`);

  const renderRow = (a: CatalogueActivity, opts: { showProgramme: boolean; option: boolean; suggestion?: boolean }) => {
    const planned = isInPlan(a.id);
    const years = inPlan[a.id] ?? [];
    const phrase = mapPhrase(a);
    // suggestions are a shortcut for the mouse / finger; the arrow keys walk the browse tree below them
    const active = !opts.suggestion && activeId === a.id;
    const englishShown = !isNepali && a.nameEn;
    return (
      <li
        key={a.id}
        id={opts.suggestion ? `ap-sug-${a.id}` : `ap-opt-${a.id}`}
        role={opts.option ? 'option' : undefined}
        aria-selected={opts.option ? active : undefined}
        data-testid={opts.suggestion ? `suggestion-row-${a.id}` : `activity-row-${a.id}`}
        data-in-plan={planned ? 'true' : 'false'}
        // A row becomes the active one when the mouse MOVES over it — not merely when it appears under a resting
        // pointer (a list re-rendering beneath the mouse reports a "mouse enter" too), which used to steal the row
        // someone had just reached with the arrow keys.
        onMouseMove={opts.suggestion ? undefined : (e) => { if ((e.movementX || e.movementY) && activeId !== a.id) setActiveId(a.id); }}
        onClick={() => act(a)}
        style={{
          listStyle: 'none',
          display: 'flex',
          gap: 12,
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          padding: '10px 12px',
          minHeight: 48,
          borderBottom: '1px solid #f0f0f0',
          borderLeft: `3px solid ${planned ? '#52c41a' : 'transparent'}`,
          background: active ? '#f0f7ff' : undefined,
          outline: active ? '2px solid #1677ff' : undefined,
          outlineOffset: -2,
          cursor: 'pointer',
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 15,
              lineHeight: 1.5,
              overflowWrap: 'anywhere',
              whiteSpace: 'normal',
            }}
          >
            <Highlighted text={a.name} query={query} />
          </div>
          {englishShown && (
            <div
              style={{
                fontSize: 13,
                color: '#595959',
                overflowWrap: 'anywhere',
              }}
            >
              <Highlighted text={a.nameEn as string} query={query} />
            </div>
          )}
          {opts.showProgramme && a.programme && (
            <div
              style={{
                fontSize: 12,
                color: '#8c8c8c',
                overflowWrap: 'anywhere',
              }}
            >
              {a.programme}
            </div>
          )}
          <Space size={[12, 2]} wrap style={{ marginTop: 4 }}>
            <span
              data-testid={`map-badge-${a.id}`}
              style={{
                display: 'inline-flex',
                gap: 5,
                alignItems: 'center',
                fontSize: 12,
                color: '#595959',
              }}
            >
              <KindGlyph kind={a.mapKind} none={phrase === 'none'} />
              {mapText(phrase)}
              {a.mapKind && phrase !== 'none' && <span>· {activityKindLabel(a.mapKind, i18n.language)}</span>}
            </span>
            {a.unit && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {unitText(a.unit)}
              </Text>
            )}
            {planned && (
              <Tag color="green" icon={<CheckCircleFilled />} style={{ margin: 0 }} data-testid={`in-plan-${a.id}`}>
                {years.length > 0
                  ? t('yearlyPlan.find.card.inPlanYears', {
                      years: formatYears(years, fmt),
                    })
                  : t('yearlyPlan.find.card.inPlan')}
              </Tag>
            )}
          </Space>
        </div>
        <Button
          type={planned ? 'default' : 'primary'}
          loading={busyId === a.id}
          style={{ flex: 'none', minHeight: 40, minWidth: 96 }}
          onClick={(e) => {
            e.stopPropagation();
            act(a);
          }}
        >
          {planned ? t('yearlyPlan.find.card.open') : t('yearlyPlan.find.card.choose')}
        </Button>
      </li>
    );
  };

  const groupNote = (programme: string) => {
    const slug = programmeSlug(programme);
    return slug ? t(`yearlyPlan.find.programme.${slug}`) : '';
  };
  const mapCount = (hs: SearchHit[]) => hs.filter((h) => h.activity.requiresMap).length;

  // ---- render
  if (loading) {
    return (
      <div data-testid="activity-picker-loading" style={{ padding: 24, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (failed) {
    return (
      <div data-testid="activity-picker-failed" role="alert" style={{ padding: 16 }}>
        <Text>{t('yearlyPlan.find.loadFailed')}</Text>{' '}
        {onRetry && <Button onClick={onRetry}>{t('common.retry', { defaultValue: 'Retry' })}</Button>}
      </div>
    );
  }
  if (total === 0) {
    return (
      <div data-testid="activity-picker-empty" style={{ padding: 16 }}>
        <Empty description={t('yearlyPlan.find.noneYet')} />
      </div>
    );
  }

  return (
    <section className="activity-picker" data-testid="activity-picker" aria-label={t('yearlyPlan.find.title')}>
      <div style={{ marginBottom: 8 }}>
        <Text strong style={{ fontSize: 16 }}>
          {t('yearlyPlan.find.title')}
        </Text>
      </div>

      <Input
        size="large"
        data-testid="activity-search"
        autoFocus={autoFocus}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={t('yearlyPlan.find.placeholder')}
        aria-label={t('yearlyPlan.find.searchLabel')}
        role="combobox"
        aria-expanded={visibleIds.length > 0}
        aria-controls="ap-list"
        aria-activedescendant={activeId === null ? undefined : `ap-opt-${activeId}`}
        autoComplete="off"
        prefix={<SearchOutlined aria-hidden="true" />}
        suffix={
          query ? (
            <button
              type="button"
              aria-label={t('yearlyPlan.find.clear')}
              data-testid="activity-search-clear"
              onClick={() => {
                setQuery('');
                setActiveId(null);
              }}
              style={{
                border: 0,
                background: 'none',
                cursor: 'pointer',
                padding: 4,
                color: '#8c8c8c',
                display: 'inline-flex',
              }}
            >
              <CloseCircleFilled />
            </button>
          ) : undefined
        }
      />
      <div style={{ fontSize: 12, color: '#8c8c8c', margin: '4px 2px 8px' }}>{t('yearlyPlan.find.hint')}</div>

      {/* filter chips */}
      <div data-testid="activity-filters" aria-label={t('yearlyPlan.find.filters.title')} role="group">
        <Space size={[8, 8]} wrap>
          <Chip
            testId="chip-map"
            pressed={filters.map === 'map'}
            onClick={() => setFilter({ map: filters.map === 'map' ? 'any' : 'map' })}
          >
            {t('yearlyPlan.find.filters.map')}
          </Chip>
          <Chip
            testId="chip-nomap"
            pressed={filters.map === 'nomap'}
            onClick={() => setFilter({ map: filters.map === 'nomap' ? 'any' : 'nomap' })}
          >
            {t('yearlyPlan.find.filters.noMap')}
          </Chip>
          <Chip
            testId="chip-inplan"
            pressed={filters.plan === 'in'}
            onClick={() => setFilter({ plan: filters.plan === 'in' ? 'any' : 'in' })}
          >
            {t('yearlyPlan.find.filters.inPlan')}
          </Chip>
          <Chip
            testId="chip-notinplan"
            pressed={filters.plan === 'not'}
            onClick={() => setFilter({ plan: filters.plan === 'not' ? 'any' : 'not' })}
          >
            {t('yearlyPlan.find.filters.notInPlan')}
          </Chip>
          <Chip testId="chip-recent" pressed={filters.recentOnly} onClick={() => setFilter({ recentOnly: !filters.recentOnly })}>
            {t('yearlyPlan.find.filters.recent')}
          </Chip>
          <Button
            type="text"
            size="small"
            data-testid="toggle-symbols"
            aria-expanded={showSymbols}
            icon={showSymbols ? <DownOutlined /> : <RightOutlined />}
            onClick={() => setShowSymbols((v) => !v)}
          >
            {t('yearlyPlan.find.filters.symbol')}
          </Button>
          <Button
            type="text"
            size="small"
            data-testid="toggle-units"
            aria-expanded={showUnits}
            icon={showUnits ? <DownOutlined /> : <RightOutlined />}
            onClick={() => setShowUnits((v) => !v)}
          >
            {t('yearlyPlan.find.filters.unit')}
          </Button>
          {hasActiveFilters(filters) && (
            <Button type="link" size="small" data-testid="clear-filters" onClick={() => setFilters(NO_FILTERS)}>
              {t('yearlyPlan.find.filters.clear')}
            </Button>
          )}
        </Space>
        {showSymbols && (
          <div data-testid="symbol-chips" style={{ marginTop: 8 }}>
            <Space size={[8, 8]} wrap>
              {kindChips.map((k) => (
                <Chip
                  key={k.value}
                  testId={`chip-kind-${k.value}`}
                  pressed={filters.kinds.includes(k.value)}
                  onClick={() => setFilter({ kinds: toggleIn(filters.kinds, k.value) })}
                >
                  <KindGlyph kind={k.value} size={14} />
                  {activityKindLabel(k.value, i18n.language) || k.value} ({fmt(k.count)})
                </Chip>
              ))}
            </Space>
          </div>
        )}
        {showUnits && (
          <div data-testid="unit-chips" style={{ marginTop: 8 }}>
            <Space size={[8, 8]} wrap>
              {unitChips.map((u) => (
                <Chip
                  key={u.value}
                  testId={`chip-unit-${u.value}`}
                  pressed={filters.units.includes(u.value)}
                  onClick={() => setFilter({ units: toggleIn(filters.units, u.value) })}
                >
                  {u.value} ({fmt(u.count)})
                </Chip>
              ))}
            </Space>
          </div>
        )}
      </div>

      {/* live count */}
      <div aria-live="polite" data-testid="activity-count" style={{ fontSize: 13, color: '#595959', margin: '10px 2px 6px' }}>
        {t('yearlyPlan.find.showing', {
          n: fmt(hits.length),
          total: fmt(total),
        })}
      </div>

      <div
        ref={listRef}
        id="ap-list"
        data-testid="activity-list"
        style={{
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        {filters.recentOnly && recent.length === 0 && (
          <div data-testid="recent-none" style={{ padding: 12, color: '#8c8c8c' }}>
            {t('yearlyPlan.find.filters.recentNone')}
          </div>
        )}

        {nothingFound && (
          <div data-testid="no-match" role="status" style={{ padding: 12, background: '#fffbe6' }}>
            <div style={{ marginBottom: 8 }}>
              {query.trim() ? t('yearlyPlan.find.noMatch', { query: query.trim() }) : t('yearlyPlan.find.noMatchFilters')}
            </div>
            {suggestions.length > 0 && (
              <>
                <Text strong style={{ fontSize: 13 }}>
                  {t('yearlyPlan.find.closest')}
                </Text>
                <ul
                  data-testid="suggestions"
                  role="listbox"
                  aria-label={t('yearlyPlan.find.closest')}
                  style={{ margin: '4px 0 0', padding: 0, background: '#fff' }}
                >
                  {suggestions.map((s) =>
                    renderRow(s, {
                      showProgramme: true,
                      option: true,
                      suggestion: true,
                    }),
                  )}
                </ul>
              </>
            )}
          </div>
        )}

        {!showTree &&
          groups.map((g) => (
            <div key={g.programme} data-testid="result-group">
              <div
                style={{
                  padding: '8px 12px',
                  background: '#fafafa',
                  borderBottom: '1px solid #f0f0f0',
                }}
              >
                <Text strong>{g.programme || '—'}</Text>{' '}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  ({fmt(g.hits.length)})
                </Text>
              </div>
              <ul role="listbox" aria-label={t('yearlyPlan.find.resultsLabel')} style={{ margin: 0, padding: 0 }}>
                {g.hits.map((h) => renderRow(h.activity, { showProgramme: false, option: true }))}
              </ul>
            </div>
          ))}

        {showTree && (
          <div data-testid="browse-tree">
            <div
              style={{
                padding: '8px 12px',
                background: '#fafafa',
                borderBottom: '1px solid #f0f0f0',
                display: 'flex',
                gap: 8,
                alignItems: 'center',
                flexWrap: 'wrap',
              }}
            >
              <Text strong>{t('yearlyPlan.find.browseTitle')}</Text>
              <Button size="small" type="link" onClick={expandAll} data-testid="expand-all">
                {t('yearlyPlan.find.expandAll')}
              </Button>
              <Button size="small" type="link" onClick={collapseAll} data-testid="collapse-all">
                {t('yearlyPlan.find.collapseAll')}
              </Button>
            </div>
            {tree.map((p) => {
              const flat = p.programmes.length === 1 && p.programmes[0].programme === p.project;
              return (
                <div key={p.project || '—'} data-testid="tree-project">
                  {!flat && (
                    <div
                      data-testid="tree-project-heading"
                      style={{
                        padding: '8px 12px',
                        background: '#f5f5f5',
                        borderBottom: '1px solid #f0f0f0',
                        overflowWrap: 'anywhere',
                      }}
                    >
                      <Text strong>{p.project || '—'}</Text>{' '}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        ({fmt(p.total)})
                      </Text>
                    </div>
                  )}
                  {p.programmes.map((g) => {
                    const gKey = treeKey(p.project, g.programme);
                    const gOpen = isOpen(gKey);
                    const note = groupNote(g.programme);
                    return (
                      <div key={g.programme || '—'} data-testid="tree-programme" style={{ paddingLeft: flat ? 0 : 16 }}>
                        <button
                          type="button"
                          aria-expanded={gOpen}
                          onClick={() => toggleOpen(gKey)}
                          data-testid="tree-programme-toggle"
                          style={{
                            width: '100%',
                            textAlign: 'left',
                            padding: '10px 12px',
                            border: 0,
                            borderBottom: '1px solid #f0f0f0',
                            background: '#fff',
                            cursor: 'pointer',
                            display: 'flex',
                            gap: 8,
                            alignItems: 'flex-start',
                            minHeight: 44,
                          }}
                        >
                          <span style={{ paddingTop: 4 }}>
                            {gOpen ? <DownOutlined aria-hidden="true" /> : <RightOutlined aria-hidden="true" />}
                          </span>
                          <span style={{ overflowWrap: 'anywhere' }}>
                            <Text strong>{g.programme || '—'}</Text>
                            <div style={{ fontSize: 12, color: '#8c8c8c' }}>
                              {t('yearlyPlan.find.groupCount', {
                                n: fmt(g.hits.length),
                                map: fmt(mapCount(g.hits)),
                              })}
                            </div>
                            {note && <div style={{ fontSize: 13, color: '#595959' }}>{note}</div>}
                          </span>
                        </button>
                        {gOpen && (
                          <ul style={{ margin: 0, padding: 0 }}>
                            {g.hits.map((h) =>
                              renderRow(h.activity, {
                                showProgramme: false,
                                option: false,
                              }),
                            )}
                          </ul>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
};

export default ActivityPicker;
