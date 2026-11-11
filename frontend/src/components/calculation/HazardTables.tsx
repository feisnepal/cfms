/**
 * HazardTables — the tabular half of the Hazard & Erosion context
 * (HAZARD_EROSION_CONTEXT_PLAN.md P4).
 *
 * One `<Tabs>` over the Devanagari-keyed list-of-dict tables from
 * `GET /calculations/{id}/hazard-erosion/tables` — RUSLE per-unit + AOI
 * comparison, LSI by class / by unit, FS by unit, the landslide AOI comparison,
 * and the PII-safe household priority / settlement roll-up / driver-count
 * tables. The priority-households tab is sortable by score, filterable by tole
 * and dominant driver, and exports the filtered view to CSV client-side.
 *
 * Column headers are the dict keys verbatim (already Devanagari). No household
 * row ever carries a surname, caste or coordinate — the endpoint guarantees it.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Tabs, Table, Button, Empty, Spin, Alert } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../../i18n/hooks';
import { hazardErosionApi, type HazardErosionTables, type HazardTableRow } from '../../services/api';
import { HazardVarChip } from './HazardVarChip';

/** endpoint table key → canonical OP variable (P4) */
const TABLE_KEY_TO_VAR: Record<string, string> = {
  soil_loss_by_unit: 'hazard_erosion_by_unit_table',
  soil_loss_aoi_comparison: 'hazard_erosion_aoi_comparison_table',
  lsi_area_by_class: 'hazard_landslide_area_by_class_table',
  lsi_by_unit: 'hazard_landslide_by_unit_table',
  fs_by_unit: 'hazard_slope_by_unit_table',
  hazard_aoi_comparison: 'hazard_landslide_aoi_comparison_table',
  hh_priority_table: 'hazard_household_priority_table',
  hh_settlement_rollup_table: 'hazard_household_settlement_rollup_table',
  hh_driver_counts: 'hazard_household_driver_counts_table',
};

interface Props {
  calculationId: string;
  /** bump to re-fetch (after a param save / recompute) */
  refreshKey?: number;
}

/** display order + which tables belong on which side */
const TABLE_KEYS: (keyof HazardErosionTables)[] = [
  'soil_loss_by_unit',
  'soil_loss_aoi_comparison',
  'lsi_area_by_class',
  'lsi_by_unit',
  'fs_by_unit',
  'hazard_aoi_comparison',
  'hh_priority_table',
  'hh_settlement_rollup_table',
  'hh_driver_counts',
];

const HH_SCORE_KEY = 'जोखिम_अंक';
const HH_TOLE_KEY = 'टोल';
const HH_DRIVER_KEY = 'प्रमुख_कारक';

const cell = (v: string | number | null): React.ReactNode => {
  if (v === null || v === undefined || v === '') return '—';
  return v;
};

const humanize = (k: string): string => k.replace(/_/g, ' ');

const uniq = (xs: (string | number | null)[]): string[] =>
  Array.from(new Set(xs.map((x) => String(x ?? '')))).filter((x) => x !== '');

/** RFC-4180-ish CSV of the given rows (BOM so Excel reads the Devanagari). */
const toCsv = (rows: HazardTableRow[]): string => {
  if (!rows.length) return '';
  const cols = Object.keys(rows[0]);
  const esc = (v: unknown): string => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [cols.join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))];
  const bom = String.fromCharCode(0xfeff); // so Excel reads the Devanagari
  return bom + lines.join('\r\n');
};

const downloadCsv = (name: string, rows: HazardTableRow[]): void => {
  const blob = new Blob([toCsv(rows)], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL?.(blob);
  if (!url) return;
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL?.(url);
};

type KeyedRow = HazardTableRow & { __key: number };
const keyed = (rows: HazardTableRow[]): KeyedRow[] =>
  rows.map((r, i) => ({ ...r, __key: i }));

/** generic read-only table: columns straight from the first row's keys */
const GenericTable: React.FC<{ rows: HazardTableRow[] }> = ({ rows }) => {
  const columns: ColumnsType<KeyedRow> = useMemo(
    () =>
      (rows[0] ? Object.keys(rows[0]) : []).map((k) => ({
        title: humanize(k),
        dataIndex: k,
        key: k,
        render: (v: string | number | null) => cell(v),
      })),
    [rows],
  );
  return (
    <Table<KeyedRow>
      size="small"
      rowKey="__key"
      columns={columns}
      dataSource={keyed(rows)}
      pagination={rows.length > 12 ? { pageSize: 12, size: 'small' } : false}
      scroll={{ x: 'max-content' }}
    />
  );
};

/** household priority table: sort by score, filter by tole / driver, CSV. */
const PriorityTable: React.FC<{ rows: HazardTableRow[] }> = ({ rows }) => {
  const t = useT();
  const source = useMemo(() => keyed(rows), [rows]);
  const [view, setView] = useState<KeyedRow[]>(source);
  useEffect(() => setView(source), [source]);

  const columns: ColumnsType<KeyedRow> = useMemo(() => {
    const keys = rows[0] ? Object.keys(rows[0]) : [];
    return keys.map((k) => {
      const col: ColumnsType<KeyedRow>[number] = {
        title: humanize(k),
        dataIndex: k,
        key: k,
        render: (v: string | number | null) => cell(v),
      };
      if (k === HH_SCORE_KEY) {
        col.sorter = (a, b) => Number(a[k] ?? 0) - Number(b[k] ?? 0);
        col.defaultSortOrder = 'descend';
      }
      if (k === HH_TOLE_KEY || k === HH_DRIVER_KEY) {
        col.filters = uniq(rows.map((r) => r[k])).map((v) => ({ text: v, value: v }));
        col.onFilter = (value, record) => String(record[k] ?? '') === value;
      }
      return col;
    });
  }, [rows]);

  const exportRows = useMemo<HazardTableRow[]>(
    () =>
      view.map((r) => {
        const rest: HazardTableRow = { ...r };
        delete (rest as Record<string, unknown>).__key;
        return rest;
      }),
    [view],
  );

  return (
    <>
      <div style={{ marginBottom: 8, textAlign: 'right' }}>
        <Button
          size="small"
          icon={<DownloadOutlined />}
          disabled={!exportRows.length}
          onClick={() => downloadCsv('household_priority.csv', exportRows)}
        >
          {t('hazardErosion.tables.exportCsv')}
        </Button>
      </div>
      <Table<KeyedRow>
        size="small"
        rowKey="__key"
        columns={columns}
        dataSource={source}
        pagination={rows.length > 15 ? { pageSize: 15, size: 'small' } : false}
        scroll={{ x: 'max-content' }}
        onChange={(_p, _f, _s, extra) => setView(extra.currentDataSource)}
      />
    </>
  );
};

export const HazardTables: React.FC<Props> = ({ calculationId, refreshKey = 0 }) => {
  const t = useT();
  const [data, setData] = useState<HazardErosionTables | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setFailed(false);
    hazardErosionApi
      .tables(calculationId)
      .then((d) => {
        if (live) setData(d);
      })
      .catch(() => {
        if (live) setFailed(true);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [calculationId, refreshKey]);

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (failed || !data) {
    return (
      <Alert type="error" showIcon message={t('hazardErosion.tables.loadFailed')} />
    );
  }

  const present = TABLE_KEYS.filter((k) => Array.isArray(data[k]) && (data[k] as unknown[]).length > 0);
  if (!present.length) {
    return <Empty description={t('hazardErosion.tables.none')} />;
  }

  const items = present.map((k) => {
    const rows = data[k] as HazardTableRow[];
    const varKey = TABLE_KEY_TO_VAR[k];
    return {
      key: k,
      label: (
        <span>
          {t(`hazardErosion.tables.${k}`)}
          {varKey && <HazardVarChip tokenKey={varKey} />}
        </span>
      ),
      children:
        k === 'hh_priority_table' ? <PriorityTable rows={rows} /> : <GenericTable rows={rows} />,
    };
  });

  return (
    <div style={{ marginTop: 16 }}>
      <h4 style={{ margin: '0 0 8px' }}>{t('hazardErosion.tables.heading')}</h4>
      <Tabs size="small" items={items} />
    </div>
  );
};

export default HazardTables;
