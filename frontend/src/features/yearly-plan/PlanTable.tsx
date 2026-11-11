import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Drawer, Empty, Popconfirm, Segmented, Spin, Table, Tag, Typography, message } from 'antd';
import { ExpandAltOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../../i18n/hooks';
import { formatNumber, parseLocaleNumber } from '../../i18n/numberFormat';
import { yearlyActivitiesApi, yearlyPlanApi, type PlanLineEdit, type YearlyPlanLine } from '../../services/api';
import type { RawPotentialActivity } from '../../lib/activitySearch';
import { InlineAddRow } from './InlineAddRow';
import { YearInputCell } from './YearInputCell';
import { formatQuantity } from './format';
import { planErrorKind, planSaveErrorMessage } from './planErrors';
import { DefaultCellEditor, YearCellEditor } from './PlanCellEditors';
import { changedFields, checkAmount, defaultEdit, saveOutcome, undoEdit, yearEdit, type PlanField } from './planEdit';
import { PLAN_YEAR_NUMBERS, planTotalBudget, sortPlanLines, yearCell, type TableView } from './planTableRules';

const { Text } = Typography;

interface SwitchProps {
  value: TableView;
  onChange: (view: TableView) => void;
}

/** "Features | Plan": the same dock panel shows the places drawn on the map, or the yearly plan behind them. */
export const TableViewSwitch: React.FC<SwitchProps> = ({ value, onChange }) => {
  const t = useT();
  return (
    <div style={{ padding: '6px 8px', borderBottom: '1px solid #e5e7eb', flex: '0 0 auto' }}>
      <Segmented
        size="small"
        block
        data-testid="table-view-switch"
        aria-label={t('yearlyPlan.planTable.viewLabel') as string}
        value={value}
        onChange={(v) => onChange(v as TableView)}
        options={[
          { value: 'features', label: t('yearlyPlan.planTable.viewFeatures') as string },
          { value: 'plan', label: t('yearlyPlan.planTable.viewPlan') as string },
        ]}
      />
    </div>
  );
};

/**
 * One year of one plan line: the quantity above the budget. A year with quantity 0 and budget 0 is "nothing planned"
 * and is dimmed to a "—"; a year with only one of them 0 (voluntary work, or money with no countable output) shows
 * that 0 plainly, because it is a real, chosen value (plan §5.4).
 */
const YearGridCell: React.FC<{ line: YearlyPlanLine; year: number }> = ({ line, year }) => {
  const t = useT();
  const cell = yearCell(line, year);
  const n = formatNumber(year);
  if (!cell.planned) {
    return (
      <span
        data-testid={`year-${line.id}-${year}`}
        data-planned="false"
        title={t('yearlyPlan.planTable.yearNotPlanned', { n }) as string}
        aria-label={t('yearlyPlan.planTable.yearNotPlanned', { n }) as string}
        style={{ color: '#bfbfbf' }}
      >
        —
      </span>
    );
  }
  const quantity = formatQuantity(cell.quantity);
  const budget = formatNumber(cell.budget);
  const summary = t('yearlyPlan.planTable.yearSummary', { n, quantity, budget }) as string;
  return (
    <div data-testid={`year-${line.id}-${year}`} data-planned="true" title={summary} aria-label={summary} style={{ lineHeight: 1.25 }}>
      <div style={{ color: '#1f2937' }}>{quantity}</div>
      <div style={{ fontSize: 11, color: '#6b7280' }}>{budget}</div>
    </div>
  );
};

interface Props {
  calculationId: string;
  /** bump after the map or the wizard changes the plan so the table re-reads it */
  refreshKey?: number | string;
  /** open the add-activity wizard */
  onAddActivity?: () => void;
  /** toolbar items after "Add activity" (the export menu) */
  extraToolbar?: React.ReactNode;
  /** select this line's places on the map (the Location cell of a line that has some) */
  onSelectPlaces?: (line: YearlyPlanLine) => void;
  /** open the wizard at "where" for a line that can be drawn but has no place yet */
  onShowOnMap?: (line: YearlyPlanLine) => void;
  /** the plan was changed from this table (a line was confirmed): the host re-reads what else shows it */
  onPlanChanged?: () => void;
  /** this table is the wide copy shown in the drawer (it has no "Wider view" button of its own) */
  embedded?: boolean;
  /** show the numbers without letting them be changed (someone who is not the owner of the plan) */
  readOnly?: boolean;
  /** a mappable line's location and drawn places, opened by the host (a link under its Location cell) */
  onOpenDetails?: (line: YearlyPlanLine) => void;
  /** no "Wider view" button: the table already has the whole page */
  noExpand?: boolean;
  /** the activity catalogue: when given (and the plan is editable) the table ends with an empty row to pick the next activity from, and each row can be removed */
  activities?: RawPotentialActivity[];
  /** the Yearly Activities step: year cells are typed into directly (one number per cell, Tab / Enter / paste) instead of opening a panel */
  gridMode?: boolean;
  /** grid mode: a Draw button on each row that needs a place; the host takes the user to the map */
  onDrawOnMap?: (line: YearlyPlanLine) => void;
  /** "Open full plan": the yearly-activities page (the map's plan table offers it; the pages themselves do not) */
  onOpenFullPlan?: () => void;
}

/** Below this width the Activity column is not pinned: pinned at 260 px it would cover the whole 20 % dock. */
const PIN_ACTIVITY_MIN_WIDTH = 640;

/**
 * Table B — the Yearly Plan (plan §5.2): one row per plan line, whether or not the activity has anything drawn on
 * the map. This is the same plan the yearly-activities page shows, read through the same route, so a number
 * edited on either screen is the number on both.
 */
export const PlanTable: React.FC<Props> = ({ calculationId, refreshKey = 0, onAddActivity, extraToolbar, onSelectPlaces, onShowOnMap, onPlanChanged, embedded = false, readOnly = false, onOpenDetails, noExpand = false, onOpenFullPlan, activities, gridMode = false, onDrawOnMap }) => {
  const t = useT();
  const rootRef = useRef<HTMLDivElement>(null);
  const [narrow, setNarrow] = useState(false);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      if (width > 0) setNarrow(width < PIN_ACTIVITY_MIN_WIDTH);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const [lines, setLines] = useState<YearlyPlanLine[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [notOwner, setNotOwner] = useState(false);
  const latest = useRef(0);

  const load = useCallback(async () => {
    const ticket = ++latest.current;
    setLoading(true);
    try {
      const plan = await yearlyPlanApi.getPlan(calculationId);
      if (ticket !== latest.current) return;
      setLines(plan.lines);
      setFailed(false);
      setNotOwner(false);
    } catch (err) {
      if (ticket === latest.current) {
        // D9: the plan routes answer 404 to anyone who is not the owner — say so plainly instead of "could not load"
        if (planErrorKind(err) === 'notOwner') setNotOwner(true);
        else setFailed(true);
      }
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, [calculationId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const [confirming, setConfirming] = useState<string | null>(null);
  const confirm = useCallback(
    async (line: YearlyPlanLine) => {
      setConfirming(line.id);
      try {
        await yearlyPlanApi.confirmLine(calculationId, line.id, line.version);
        message.success(t('yearlyPlan.confirm.done'));
        await load();
        onPlanChanged?.();
      } catch (err) {
        message.error(planSaveErrorMessage(err, t));
      } finally {
        setConfirming(null);
      }
    },
    [calculationId, load, onPlanChanged, t],
  );

  // ---- editing (plan §4.7, §4.8): every change saves at once; the last one can be undone
  interface EditStatus {
    kind: 'saved' | 'filled' | 'undone';
    lineId: string;
    before?: YearlyPlanLine;
  }
  const [status, setStatus] = useState<EditStatus | null>(null);
  const [filled, setFilled] = useState<{ lineId: string; years: number[] } | null>(null);
  const [saving, setSaving] = useState(false);
  // one save at a time: a second edit made while one is on its way would carry a version that is about to be stale
  const inFlight = useRef(false);

  const replaceLine = useCallback((updated: YearlyPlanLine) => {
    // keep what the edit response does not carry (the derived location) from the row already on screen
    setLines((prev) => (prev ? prev.map((l) => (l.id === updated.id ? { ...l, ...updated } : l)) : prev));
  }, []);

  const failed_ = useCallback(
    (err: unknown) => {
      message.error(planSaveErrorMessage(err, t));
      if (planErrorKind(err) === 'saveConflict') void load(); // someone else changed it: show what is there now
    },
    [load, t],
  );

  const editLine = useCallback(
    async (line: YearlyPlanLine, edit: PlanLineEdit): Promise<boolean> => {
      if (inFlight.current) return false; // the editor stays open with what was typed; press again once it has saved
      inFlight.current = true;
      setSaving(true);
      try {
        const result = await yearlyPlanApi.updateLine(calculationId, line.id, edit);
        replaceLine(result.plan_line);
        const outcome = saveOutcome(result.filled_years);
        setStatus({ kind: outcome, lineId: line.id, before: line });
        setFilled(result.filled_years.length > 0 ? { lineId: line.id, years: result.filled_years } : null);
        onPlanChanged?.();
        return true;
      } catch (err) {
        failed_(err);
        return false;
      } finally {
        inFlight.current = false;
        setSaving(false);
      }
    },
    [calculationId, failed_, onPlanChanged, replaceLine],
  );

  const undo = useCallback(async () => {
    if (!status?.before || inFlight.current) return;
    const current = (lines ?? []).find((l) => l.id === status.lineId);
    inFlight.current = true;
    setSaving(true);
    try {
      const result = await yearlyPlanApi.updateLine(calculationId, status.lineId, undoEdit(status.before, current?.version ?? status.before.version + 1));
      replaceLine(result.plan_line);
      setStatus({ kind: 'undone', lineId: status.lineId });
      setFilled(null);
      onPlanChanged?.();
    } catch (err) {
      failed_(err);
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }, [calculationId, failed_, lines, onPlanChanged, replaceLine, status]);

  // ---- the structure of the plan: a new row by picking an activity, and removing a row (owner, 2026-10-15)
  const addByPick = useCallback(
    async (activityId: number): Promise<boolean> => {
      try {
        await yearlyPlanApi.addLine(calculationId, { potential_activity_id: activityId, years: [1] });
        await load();
        onPlanChanged?.();
        return true;
      } catch (err) {
        message.error(planSaveErrorMessage(err, t));
        return false;
      }
    },
    [calculationId, load, onPlanChanged, t],
  );
  const removeLine = useCallback(
    async (line: YearlyPlanLine) => {
      try {
        await yearlyActivitiesApi.deleteProposedActivity(line.id);
        await load();
        onPlanChanged?.();
      } catch (err) {
        message.error(planSaveErrorMessage(err, t));
      }
    },
    [load, onPlanChanged, t],
  );
  const inPlanIds = useMemo(() => new Set((lines ?? []).map((l) => l.potential_activity_id)), [lines]);
  const canChangeStructure = !readOnly && !notOwner && !!activities;

  // ---- the spreadsheet grid (owner, 2026-10-15): one number per year cell - the quantity or the budget
  const [metric, setMetric] = useState<PlanField>('quantity');
  const grid = gridMode && !readOnly && !notOwner;
  const rows = useMemo(() => sortPlanLines(lines ?? []), [lines]);
  const commitBusy = useRef(false);

  const commitYear = useCallback(
    async (line: YearlyPlanLine, year: number, text: string): Promise<boolean> => {
      if (commitBusy.current) return true; // the same Enter also blurs the cell: the save is already on its way
      const check = checkAmount(metric, 'year', text, parseLocaleNumber);
      if (!check.ok) {
        message.error(t('yearlyPlan.planTable.editInvalid'));
        return false;
      }
      const cell = yearCell(line, year);
      const changes = changedFields(cell, {
        quantity: metric === 'quantity' ? check.value : cell.quantity,
        budget: metric === 'budget' ? check.value : cell.budget,
      });
      if (Object.keys(changes).length === 0) return true;
      commitBusy.current = true;
      try {
        return await editLine(line, yearEdit(line, year, changes));
      } finally {
        commitBusy.current = false;
      }
    },
    [editLine, metric, t],
  );

  const moveTo = useCallback((row: number, col: number) => {
    rootRef.current?.querySelector<HTMLInputElement>(`input[data-grid-row="${row}"][data-grid-col="${col}"]`)?.focus();
  }, []);

  /** A block copied from Excel: rows go down the plan lines, columns go along the years, from the cell it was pasted into. */
  const pasteBlock = useCallback(
    async (text: string, row: number, col: number) => {
      if (inFlight.current) return;
      const cells = text.replace(/\r/g, '').split('\n').filter((r, i, all) => !(i === all.length - 1 && r === '')).map((r) => r.split('\t'));
      const perLine = new Map<string, { line: YearlyPlanLine; years: { year: number; quantity?: number; budget?: number }[] }>();
      for (let ri = 0; ri < cells.length; ri += 1) {
        const line = rows[row + ri];
        if (!line) break;
        for (let ci = 0; ci < cells[ri].length; ci += 1) {
          const year = col + ci + 1;
          const token = cells[ri][ci].trim();
          if (year > PLAN_YEAR_NUMBERS.length || token === '') continue;
          const check = checkAmount(metric, 'year', token, parseLocaleNumber);
          if (!check.ok) {
            message.error(t('yearlyPlan.planTable.pasteInvalid', { value: token }));
            return; // nothing is applied when any cell is not a number
          }
          const entry = perLine.get(line.id) ?? { line, years: [] };
          entry.years.push({ year, [metric]: check.value });
          perLine.set(line.id, entry);
        }
      }
      if (perLine.size === 0) return;
      inFlight.current = true;
      setSaving(true);
      let count = 0;
      try {
        for (const { line, years } of perLine.values()) {
          const result = await yearlyPlanApi.updateLine(calculationId, line.id, { years, expected_version: line.version });
          replaceLine(result.plan_line);
          count += years.length;
        }
        message.success(t('yearlyPlan.planTable.pasteDone', { n: formatNumber(count) }));
      } catch (err) {
        failed_(err);
      } finally {
        inFlight.current = false;
        setSaving(false);
        onPlanChanged?.();
      }
    },
    [calculationId, failed_, metric, onPlanChanged, replaceLine, rows, t],
  );
  const total = useMemo(() => planTotalBudget(rows), [rows]);

  const columns: ColumnsType<YearlyPlanLine> = [
    {
      title: t('yearlyPlan.planTable.colActivity') as string,
      dataIndex: 'activity',
      key: 'activity',
      width: narrow ? 190 : 260,
      fixed: narrow ? undefined : 'left',
      // the full name, wrapped — a long activity name is never cut off (plan §4.11)
      render: (name: string | null) => <span style={{ overflowWrap: 'anywhere' }}>{name ?? '—'}</span>,
    },
    {
      title: t('yearlyPlan.planTable.colProgramme') as string,
      dataIndex: 'program',
      key: 'program',
      width: 200,
      render: (v: string | null) => <span style={{ overflowWrap: 'anywhere' }}>{v ?? '—'}</span>,
    },
    { title: t('yearlyPlan.planTable.colUnit') as string, dataIndex: 'unit', key: 'unit', width: 90, render: (v: string | null) => v ?? '—' },
    {
      title: t('yearlyPlan.planTable.colQuantity') as string,
      dataIndex: 'default_quantity',
      key: 'default_quantity',
      width: 110,
      align: 'right',
      render: (v: number, line: YearlyPlanLine) => {
        // What the drawn places measure (D4): never applied by itself — shown, and one press adopts it
        const measured = line.measured_quantity;
        const differs = typeof measured === 'number' && Math.abs(measured - Number(v)) > 0.005;
        return (
          <div>
            <DefaultCellEditor
              testId={`default-quantity-${line.id}`}
              field="quantity"
              value={v}
              display={formatQuantity(v)}
              readOnly={readOnly}
              onCommit={(next) => editLine(line, defaultEdit(line, { quantity: next }))}
            />
            {differs && !readOnly && (
              <div style={{ fontSize: 11, color: '#6b7280', lineHeight: 1.3, marginTop: 2 }} data-testid={`measured-hint-${line.id}`}>
                {t('yearlyPlan.planTable.measured', { value: formatQuantity(measured), unit: line.unit ?? '' })}{' '}
                <Button
                  type="link"
                  size="small"
                  data-testid={`use-measured-${line.id}`}
                  onClick={() => void editLine(line, defaultEdit(line, { quantity: Number(measured) }))}
                  style={{ padding: 0, height: 'auto', fontSize: 11 }}
                >
                  {t('yearlyPlan.planTable.useMeasured')}
                </Button>
              </div>
            )}
          </div>
        );
      },
    },
    {
      title: t('yearlyPlan.planTable.colBudget') as string,
      dataIndex: 'default_yearly_budget',
      key: 'default_yearly_budget',
      width: 130,
      align: 'right',
      render: (v: number, line: YearlyPlanLine) => (
        <DefaultCellEditor
          testId={`default-budget-${line.id}`}
          field="budget"
          value={Number(v) || 0}
          display={formatNumber(Number(v) || 0)}
          readOnly={readOnly}
          onCommit={(next) => editLine(line, defaultEdit(line, { budget: next }))}
        />
      ),
    },
    ...PLAN_YEAR_NUMBERS.map((year) => ({
      title: t('yearlyPlan.planTable.yearShort', { n: formatNumber(year) }) as string,
      key: `year-${year}`,
      width: 78,
      align: 'right' as const,
      render: (_: unknown, line: YearlyPlanLine, rowIndex: number) => grid ? (
        <YearInputCell
          testId={`year-input-${line.id}-${year}`}
          row={rowIndex}
          col={year - 1}
          shown={yearCell(line, year).planned ? String(yearCell(line, year)[metric]) : ''}
          filled={filled?.lineId === line.id && filled.years.includes(year)}
          onCommit={(text) => commitYear(line, year, text)}
          onPasteBlock={(text, r, c) => void pasteBlock(text, r, c)}
          onMove={moveTo}
        />
      ) : (
        <YearCellEditor
          testId={`year-edit-${line.id}-${year}`}
          year={year}
          cell={yearCell(line, year)}
          readOnly={readOnly}
          filled={filled?.lineId === line.id && filled.years.includes(year)}
          onCommit={(changes) => editLine(line, yearEdit(line, year, changes))}
        >
          <YearGridCell line={line} year={year} />
        </YearCellEditor>
      ),
    })),
    ...(grid && onDrawOnMap
      ? [
          {
            title: '',
            key: 'draw',
            width: 120,
            render: (_: unknown, line: YearlyPlanLine) =>
              line.requires_map ? (
                <Button size="small" data-testid={`draw-${line.id}`} onClick={() => onDrawOnMap(line)}>
                  {t('yearlyPlan.planTable.drawOnMap')}
                </Button>
              ) : (
                ''
              ),
          },
        ]
      : []),
    ...(grid
      ? [
          {
            title: t('yearlyPlan.planTable.colSubArea') as string,
            key: 'sub_areas',
            width: 170,
            render: (_: unknown, line: YearlyPlanLine) => {
              const links = line.sub_areas ?? [];
              if (links.length === 0) return '';
              return (
                <div data-testid={`sub-areas-${line.id}`} style={{ lineHeight: 1.3, overflowWrap: 'anywhere' }}>
                  {links.map((s) => (
                    <div key={s.id} data-matches={s.matches} style={{ fontWeight: s.matches ? 600 : 400 }}>
                      {s.name}
                    </div>
                  ))}
                </div>
              );
            },
          },
        ]
      : []),
    {
      title: t('yearlyPlan.planTable.colLocation') as string,
      key: 'location',
      width: 190,
      // Only where a location applies (plan §4.4b, D26): blank for an activity that needs no map — unless places
      // exist anyway, which are never hidden.
      render: (_: unknown, line: YearlyPlanLine) => {
        const locationCell = (): React.ReactNode => {
        const count = Number(line.feature_count) || 0;
        if (line.location_mode === 'not_applicable' && count === 0) return '';
        if (count > 0) {
          const units = (line.location_units ?? []).join(', ');
          const label = t('yearlyPlan.planTable.placesCount', { n: formatNumber(count) }) as string;
          return (
            <div style={{ lineHeight: 1.3 }}>
              {onSelectPlaces ? (
                <Button
                  type="link"
                  size="small"
                  data-testid={`select-places-${line.id}`}
                  title={t('yearlyPlan.planTable.selectPlaces') as string}
                  aria-label={`${label}. ${t('yearlyPlan.planTable.selectPlaces')}`}
                  onClick={() => onSelectPlaces(line)}
                  style={{ padding: 0, height: 'auto' }}
                >
                  {label}
                </Button>
              ) : (
                <span>{label}</span>
              )}
              {units && (
                <div data-testid={`location-units-${line.id}`} style={{ fontSize: 11, color: '#6b7280', overflowWrap: 'anywhere' }}>
                  {t('yearlyPlan.planTable.inUnits', { units })}
                </div>
              )}
            </div>
          );
        }
        if (line.location_mode === 'whole_forest') return <span data-testid={`whole-forest-${line.id}`}>{t('yearlyPlan.planTable.wholeForest')}</span>;
        // no place drawn, but blocks / sub-areas were chosen for the activity (the yearly-activities pages)
        if (line.location_mode === 'units') {
          return (
            <span data-testid={`assigned-units-${line.id}`} style={{ overflowWrap: 'anywhere' }}>
              {t('yearlyPlan.planTable.inUnits', { units: (line.location_units ?? []).join(', ') })}
            </span>
          );
        }
        // a mappable activity with nothing chosen yet
        return (
          <div style={{ lineHeight: 1.3 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>{t('yearlyPlan.planTable.needsLocation')}</Text>
            {onShowOnMap && (
              <div>
                <Button type="link" size="small" data-testid={`show-on-map-${line.id}`} onClick={() => onShowOnMap(line)} style={{ padding: 0, height: 'auto' }}>
                  {t('yearlyPlan.planTable.showOnMap')}
                </Button>
              </div>
            )}
          </div>
        );
        };
        const cell = locationCell();
        // the host's own place to say where an activity applies and to see its drawn places (yearly-activities pages)
        const canOpen = onOpenDetails && !readOnly && (line.requires_map || (Number(line.feature_count) || 0) > 0);
        if (!canOpen) return cell;
        return (
          <div>
            {cell}
            <Button type="link" size="small" data-testid={`location-details-${line.id}`} onClick={() => onOpenDetails(line)} style={{ padding: 0, height: 'auto' }}>
              {t('yearlyPlan.home.locationDetails')}
            </Button>
          </div>
        );
      },
    },
    {
      title: t('yearlyPlan.planTable.colTotal') as string,
      dataIndex: 'total_budget',
      key: 'total_budget',
      width: 140,
      align: 'right',
      render: (v: number) => formatNumber(Number(v) || 0),
    },
    {
      title: t('yearlyPlan.planTable.colReview') as string,
      key: 'review',
      width: 210,
      // "Starting numbers" while the line is unreviewed and a number is still the value the system started with;
      // "Confirmed" once the person said they are right. A line with real numbers that was never confirmed is quiet.
      render: (_: unknown, line: YearlyPlanLine) => {
        const fields = line.placeholder_fields ?? [];
        if (!line.reviewed_at && fields.length > 0) {
          const both = fields.includes('quantity') && fields.includes('budget');
          const title = t(`yearlyPlan.planTable.reviewTitle${both ? 'Both' : fields.includes('quantity') ? 'Quantity' : 'Budget'}`) as string;
          return (
            <div style={{ lineHeight: 1.4 }}>
              <Tag color="orange" data-testid={`review-badge-${line.id}`} title={title} style={{ marginInlineEnd: 6 }}>
                {t('yearlyPlan.planTable.reviewPlaceholder')}
              </Tag>
              <Button
                size="small"
                data-testid={`review-confirm-${line.id}`}
                loading={confirming === line.id}
                disabled={confirming !== null}
                onClick={() => void confirm(line)}
              >
                {t('yearlyPlan.confirm.button')}
              </Button>
            </div>
          );
        }
        if (line.reviewed_at) {
          return (
            <Text type="secondary" data-testid={`review-confirmed-${line.id}`} style={{ fontSize: 12 }}>
              {t('yearlyPlan.planTable.reviewConfirmed')}
            </Text>
          );
        }
        return '';
      },
    },
    ...(canChangeStructure
      ? [
          {
            title: '',
            key: 'remove',
            width: 56,
            render: (_: unknown, line: YearlyPlanLine) => (
              <Popconfirm
                title={t('yearlyPlan.planTable.removeConfirm') as string}
                okText={t('yearlyPlan.planTable.removeOk') as string}
                cancelText={t('yearlyPlan.planTable.removeCancel') as string}
                onConfirm={() => removeLine(line)}
              >
                <Button type="text" size="small" danger data-testid={`remove-line-${line.id}`} aria-label={t('yearlyPlan.planTable.removeRow') as string}>
                  ×
                </Button>
              </Popconfirm>
            ),
          },
        ]
      : []),
  ];

  return (
    <div ref={rootRef} data-testid="plan-table" style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}>
      {notOwner && (
        <div role="status" data-testid="plan-table-not-owner" style={{ padding: 12 }}>
          <Text>{t('yearlyPlan.planTable.notOwner')}</Text>
        </div>
      )}
      <div style={{ display: notOwner ? 'none' : 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', flex: '0 0 auto', flexWrap: 'wrap' }}>
        {onAddActivity && (
          <Button size="small" type="primary" data-testid="plan-table-add" onClick={onAddActivity}>
            {t('yearlyPlan.wizard.addButton')}
          </Button>
        )}
        {grid && (
          <Segmented
            size="small"
            data-testid="plan-metric-switch"
            aria-label={t('yearlyPlan.planTable.metricLabel') as string}
            value={metric}
            onChange={(v) => setMetric(v as PlanField)}
            options={[
              { value: 'quantity', label: t('yearlyPlan.planTable.metricQuantity') as string },
              { value: 'budget', label: t('yearlyPlan.planTable.metricBudget') as string },
            ]}
          />
        )}
        {extraToolbar}
        {onOpenFullPlan && !embedded && (
          <Button size="small" onClick={onOpenFullPlan} data-testid="plan-table-full-plan">
            {t('yearlyPlan.planTable.openFullPlan')}
          </Button>
        )}
        {!embedded && !noExpand && (
          <Button size="small" icon={<ExpandAltOutlined />} data-testid="plan-table-expand" onClick={() => setExpanded(true)}>
            {t('yearlyPlan.planTable.expand')}
          </Button>
        )}
        {lines && (
          <Text type="secondary" data-testid="plan-table-summary" style={{ marginLeft: 'auto', fontSize: 12 }}>
            {t('yearlyPlan.planTable.summary', { n: formatNumber(rows.length), total: formatNumber(total) })}
          </Text>
        )}
      </div>

      {lines && rows.length > 0 && (
        <Text type="secondary" data-testid="plan-table-grid-hint" style={{ fontSize: 12, padding: '0 8px 6px', flex: '0 0 auto' }}>
          {t('yearlyPlan.planTable.gridHint')}
        </Text>
      )}

      {status && (
        <div
          role="status"
          data-testid="plan-table-status"
          data-kind={status.kind}
          style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 8px 6px', flex: '0 0 auto', flexWrap: 'wrap' }}
        >
          <Text style={{ fontSize: 12, color: '#237804' }}>
            {status.kind === 'filled'
              ? t('yearlyPlan.planTable.filledForAll')
              : status.kind === 'undone'
                ? t('yearlyPlan.planTable.undone')
                : t('yearlyPlan.saved.ok')}
          </Text>
          {status.kind !== 'undone' && status.before && (
            <Button size="small" type="link" data-testid="plan-table-undo" loading={saving} onClick={() => void undo()} style={{ padding: 0, height: 'auto' }}>
              {t('yearlyPlan.planTable.undo')}
            </Button>
          )}
        </div>
      )}

      {failed && !lines && !notOwner && (
        <div role="alert" data-testid="plan-table-failed" style={{ padding: 12 }}>
          <Text>{t('yearlyPlan.planTable.loadFailed')}</Text>{' '}
          <Button size="small" onClick={() => void load()}>
            {t('yearlyPlan.planTable.retry')}
          </Button>
        </div>
      )}

      {!lines && !failed && !notOwner && (
        <div style={{ padding: 16, textAlign: 'center' }} data-testid="plan-table-loading">
          <Spin size="small" /> <Text type="secondary">{t('yearlyPlan.planTable.loading')}</Text>
        </div>
      )}

      {lines && rows.length === 0 && (
        <Empty
          data-testid="plan-table-empty"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('yearlyPlan.planTable.empty') as string}
          style={{ margin: '16px 8px' }}
        />
      )}

      {lines && rows.length > 0 && (
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
          <Table<YearlyPlanLine>
            size="small"
            rowKey="id"
            loading={loading}
            columns={columns}
            dataSource={rows}
            pagination={false}
            scroll={{ x: 'max-content' }}
            sticky
            summary={
              grid
                ? () => (
                    <Table.Summary fixed>
                      <Table.Summary.Row data-testid="plan-year-totals">
                        <Table.Summary.Cell index={0} colSpan={5} align="right">
                          <Text strong>{t('yearlyPlan.planTable.yearTotals')}</Text>
                        </Table.Summary.Cell>
                        {PLAN_YEAR_NUMBERS.map((year) => (
                          <Table.Summary.Cell key={year} index={year + 4} align="right">
                            <Text strong data-testid={`year-total-${year}`}>
                              {formatNumber(rows.reduce((sum, l) => sum + (yearCell(l, year).planned ? yearCell(l, year).budget : 0), 0))}
                            </Text>
                          </Table.Summary.Cell>
                        ))}
                        <Table.Summary.Cell index={15} colSpan={Math.max(1, columns.length - 15)} />
                      </Table.Summary.Row>
                    </Table.Summary>
                  )
                : undefined
            }
          />
        </div>
      )}
      {canChangeStructure && lines && <InlineAddRow activities={activities!} inPlan={inPlanIds} onPick={addByPick} />}
      {!embedded && (
        <Drawer
          open={expanded}
          onClose={() => setExpanded(false)}
          placement="right"
          width="min(1400px, 96vw)"
          title={t('yearlyPlan.planTable.expandedTitle') as string}
          destroyOnHidden
          styles={{ body: { display: 'flex', flexDirection: 'column', padding: 0 } }}
        >
          <PlanTable
            embedded
            calculationId={calculationId}
            refreshKey={refreshKey}
            onAddActivity={onAddActivity && (() => { setExpanded(false); onAddActivity(); })}
            extraToolbar={extraToolbar}
            onSelectPlaces={onSelectPlaces && ((line) => { setExpanded(false); onSelectPlaces(line); })}
            onShowOnMap={onShowOnMap && ((line) => { setExpanded(false); onShowOnMap(line); })}
            onPlanChanged={onPlanChanged}
            onOpenDetails={onOpenDetails && ((line) => { setExpanded(false); onOpenDetails(line); })}
            readOnly={readOnly}
            activities={activities}
          />
        </Drawer>
      )}
    </div>
  );
};

export default PlanTable;
