/**
 * SfmFellingSeriesStrip — one row per felling series
 * (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P4).
 *
 * A felling series = production blocks grouped by effective_type_no. Columns:
 * type · method · N/C/R · GS≥40 · % · annual harvest. Stem-count / prior-only
 * / protection series render "—" for the harvest.
 */
import { SfmTypeTag } from './SfmTypeTag';
import React from 'react';
import { Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../../i18n/hooks';
import type { SfmFellingSeries } from '../../services/api';
import { SfmVarChip } from './SfmVarChip';

interface Props {
  series: SfmFellingSeries[];
  lang: string;
}

const fmt = (n: number | null | undefined, dp = 1): string =>
  n === null || n === undefined || Number.isNaN(n) ? '—' : n.toFixed(dp);

export const SfmFellingSeriesStrip: React.FC<Props> = ({ series, lang }) => {
  const t = useT();
  const ne = lang.startsWith('ne');

  const columns: ColumnsType<SfmFellingSeries> = [
    {
      title: t('sfm.series.type'),
      dataIndex: 'type_no',
      key: 'type_no',
      render: (n: number) => <SfmTypeTag n={n} />,
      width: 90,
    },
    {
      title: t('sfm.series.method'),
      dataIndex: 'method',
      key: 'method',
      render: (m: string | null) => (m ? t(`sfm.method.${m}`, m) : '—'),
    },
    {
      title: t('sfm.series.structuring'),
      key: 'ncr',
      width: 130,
      render: (_: unknown, r: SfmFellingSeries) => {
        const parts: string[] = [];
        if (r.N != null) parts.push(`N ${r.N}`);
        if (r.C != null) parts.push(`C ${r.C}`);
        if (r.R != null) parts.push(`R ${r.R}`);
        return parts.length ? parts.join(' · ') : '—';
      },
    },
    {
      title: t('sfm.series.gs40'),
      dataIndex: 'gs_ge40_m3',
      key: 'gs_ge40_m3',
      align: 'right',
      render: (v: number | null) => fmt(v),
    },
    {
      title: t('sfm.series.pct'),
      dataIndex: 'pct',
      key: 'pct',
      align: 'right',
      render: (v: number | null) => (v == null ? '—' : `${v}%`),
    },
    {
      title: t('sfm.series.annualHarvest'),
      dataIndex: 'annual_harvest_m3',
      key: 'annual_harvest_m3',
      align: 'right',
      render: (v: number | null, r: SfmFellingSeries) => {
        if (v == null) {
          const note = ne ? r.note_ne : r.note_en;
          return (
            <Tooltip title={note || undefined}>
              <span style={{ color: '#999' }}>—</span>
            </Tooltip>
          );
        }
        if (v === 0) {
          return <Tag color="default">{t('sfm.series.salvageOnly')}</Tag>;
        }
        return <b>{fmt(v)}</b>;
      },
    },
  ];

  return (
    <Table<SfmFellingSeries>
      size="small"
      rowKey="id"
      dataSource={series}
      columns={columns}
      pagination={false}
      title={() => (
        <b>
          {t('sfm.series.heading')}
          <SfmVarChip tokenKey="sfm_yield_table" />
        </b>
      )}
      locale={{ emptyText: t('sfm.series.none') }}
    />
  );
};

export default SfmFellingSeriesStrip;
