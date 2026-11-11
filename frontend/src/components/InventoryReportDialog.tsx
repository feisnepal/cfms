/**
 * "Inventory by sub-unit": the field inventory per undivided unit, a roll-up row for every divided parent and a forest total,
 * with the problems found between the stored inventory and the forest's current units listed above the table.
 *
 * The numbers are the server's (the very values the maps and the Operational Plan read). A roll-up's per-hectare figures are the
 * area-weighted mean of its sub-units that have data, and it says how much of its area that is. Nothing here is computed.
 */
import { useState } from 'react';
import { Button, Modal, Spin, message } from 'antd';
import { useT } from '../i18n/hooks';
import { downloadInventoryReportXlsx, useFieldInventoryReport, type ReportRow } from '../hooks/useFieldInventoryReport';

const fmt = (v: number | null | undefined, digits = 1): string =>
  v == null ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: digits });

const COLUMNS: Array<[string, string]> = [
  ['unit', 'Unit'], ['area', 'Area (ha)'], ['plots', 'Plots'], ['regen', 'Regeneration /ha'], ['sapling', 'Saplings /ha'],
  ['pole', 'Poles /ha'], ['tree', 'Trees /ha'], ['gs', 'Growing stock (m³/ha)'], ['gst', 'Growing stock (m³)'],
  ['mai', 'MAI (m³/ha/yr)'], ['aah', 'AAH (m³/ha/yr)'], ['cond', 'Condition'], ['cov', 'Covered'],
];

const cell = { padding: '2px 6px', textAlign: 'right' as const };

interface Props {
  calculationId: string;
  open: boolean;
  onClose: () => void;
  geometryVersion?: number;
}

export function InventoryReportDialog({ calculationId, open, onClose, geometryVersion = 0 }: Props) {
  const t = useT();
  const q = useFieldInventoryReport(calculationId, open, geometryVersion);
  const [rollups, setRollups] = useState(true);
  const [busy, setBusy] = useState(false);
  const data = q.data;
  const ready = data && data.state === 'ready' ? data : null;
  const rows: ReportRow[] = ready ? (rollups ? ready.rows : ready.rows.filter((r) => r.kind === 'unit')) : [];
  const shown: ReportRow[] = ready && ready.total ? [...rows, ready.total] : rows;

  const download = async () => {
    setBusy(true);
    try {
      await downloadInventoryReportXlsx(calculationId);
    } catch {
      message.error(t('inventoryReport.downloadFailed', { defaultValue: 'The workbook could not be downloaded.' }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={1100}
      title={t('inventoryReport.title', { defaultValue: 'Inventory by sub-unit' })}
      footer={[
        <label key="roll" style={{ marginRight: 12, fontSize: 12 }}>
          <input type="checkbox" checked={rollups} onChange={(e) => setRollups(e.target.checked)} data-testid="inventory-report-rollups" />{' '}
          {t('inventoryReport.showRollups', { defaultValue: 'Show roll-ups of divided units' })}
        </label>,
        <Button key="xlsx" onClick={download} loading={busy} disabled={!ready} data-testid="inventory-report-download">
          {t('inventoryReport.download', { defaultValue: 'Download Excel' })}
        </Button>,
        <Button key="close" type="primary" onClick={onClose}>{t('inventoryReport.close', { defaultValue: 'Close' })}</Button>,
      ]}
    >
      {q.isLoading && <Spin />}
      {q.isError && <div role="alert">{t('inventoryReport.failed', { defaultValue: 'The report could not be loaded.' })}</div>}
      {data && data.state !== 'ready' && (
        <div data-testid="inventory-report-empty">{t('inventoryReport.none', { defaultValue: 'No field inventory has been processed for this forest yet.' })}</div>
      )}
      {data && data.problems.length > 0 && (
        <ul data-testid="inventory-problems" style={{ margin: '0 0 10px', paddingLeft: 18, fontSize: 12 }}>
          {data.problems.map((p, i) => (
            <li key={`${p.code}-${p.unit}-${i}`} data-severity={p.severity} style={{ color: p.severity === 'error' ? '#b71c1c' : '#8a6d00' }}>
              <b aria-hidden="true">{p.severity === 'error' ? '⛔' : '⚠'}</b> {p.message}
            </li>
          ))}
        </ul>
      )}
      {ready && (
        <div style={{ overflow: 'auto', maxHeight: '60vh' }}>
          <table data-testid="inventory-report" style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
            <thead>
              <tr>
                {COLUMNS.map(([k, label]) => (
                  <th key={k} style={{ textAlign: k === 'unit' || k === 'cond' ? 'left' : 'right', padding: '3px 6px', borderBottom: '1px solid #bbb', position: 'sticky', top: 0, background: '#f1f8e9' }}>
                    {t(`inventoryReport.col.${k}`, { defaultValue: label })}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={`${r.kind}-${r.name}`} data-kind={r.kind} style={{ fontWeight: r.kind === 'unit' ? 400 : 700, background: r.kind === 'total' ? '#e8f5e9' : undefined, opacity: r.has_data ? 1 : 0.55 }}>
                  <td style={{ padding: '2px 6px', paddingLeft: 6 + (r.depth > 1 ? (r.depth - 1) * 14 : 0) }}>
                    {r.kind === 'total' ? t('inventoryReport.total', { defaultValue: 'Forest total' }) : r.name}
                  </td>
                  <td style={cell}>{fmt(r.area_ha, 2)}</td>
                  <td style={cell}>{r.plots}</td>
                  <td style={cell}>{fmt(r.regeneration_per_ha, 0)}</td>
                  <td style={cell}>{fmt(r.sapling_per_ha, 0)}</td>
                  <td style={cell}>{fmt(r.pole_per_ha, 0)}</td>
                  <td style={cell}>{fmt(r.tree_per_ha, 0)}</td>
                  <td style={cell}>{fmt(r.growing_stock_m3_per_ha, 1)}</td>
                  <td style={cell}>{fmt(r.growing_stock_m3, 0)}</td>
                  <td style={cell}>{fmt(r.mai_m3_per_ha, 2)}</td>
                  <td style={cell}>{fmt(r.aah_m3_per_ha, 2)}</td>
                  <td style={{ ...cell, textAlign: 'left' }}>{r.forest_condition ?? ''}</td>
                  <td style={cell}>{r.has_data || r.kind !== 'unit' ? `${fmt(r.covered_pct, 0)}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 11, opacity: 0.7, marginTop: 6 }}>
            {t('inventoryReport.note', {
              defaultValue:
                'A divided unit is shown as a roll-up of its sub-units: per-hectare figures are the area-weighted mean of the sub-units that have data, totals are per-hectare × area. "Covered" is the share of its area with inventory behind it.',
            })}
          </div>
        </div>
      )}
    </Modal>
  );
}
