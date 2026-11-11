/**
 * SfmComparePanel — side-by-side "Guideline vs My adjustments" report
 * (SV-1.9). Renders the compare payload: forest-level roll-up deltas, a
 * divergence table of only the blocks whose outputs differ, felling-series
 * and sampling-intensity deltas, and the per-row source tags.
 */
import { SfmTypeTag } from './SfmTypeTag';
import React from 'react';
import { Alert, Table, Tag } from 'antd';
import { useT } from '../../i18n/hooks';
import type {
  SfmCompareBlockRow,
  SfmCompareResponse,
} from '../../services/api';

interface Props {
  compare: SfmCompareResponse;
}

const fmt = (n: number | null | undefined, dp = 1): string =>
  n === null || n === undefined || Number.isNaN(n) ? '—' : n.toFixed(dp);

export const SfmComparePanel: React.FC<Props> = ({ compare }) => {
  const t = useT();
  const fs = compare.forest;

  const sourceLabel = (kind: 'workspace' | 'raster') =>
    kind === 'workspace' ? t('sfm.sourceWorkspace') : t('sfm.sourceRaster');

  const Pair: React.FC<{
    before: React.ReactNode;
    after: React.ReactNode;
  }> = ({ before, after }) => (
    <span>
      <span>{before}</span>
      <span style={{ color: '#bbb', margin: '0 6px' }}>→</span>
      <span>{after}</span>
    </span>
  );

  const SourceTag: React.FC<{ kind: 'workspace' | 'raster' }> = ({ kind }) => (
    <Tag
      color={kind === 'workspace' ? 'blue' : 'default'}
      style={{ marginLeft: 8, fontSize: 10, lineHeight: '14px' }}
    >
      {sourceLabel(kind)}
    </Tag>
  );

  const Stat: React.FC<{ label: string; value: React.ReactNode }> = ({
    label,
    value,
  }) => (
    <div style={{ minWidth: 180 }}>
      <div
        style={{
          fontSize: 11,
          color: '#888',
          textTransform: 'uppercase',
          letterSpacing: 0.4,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 600 }}>{value}</div>
    </div>
  );

  if (compare.identical) {
    return (
      <div
        style={{
          marginTop: 16,
          padding: 16,
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
        }}
      >
        <h4 style={{ margin: '0 0 8px' }}>{t('sfm.compare')}</h4>
        <span style={{ fontSize: 12, color: '#888' }}>{t('sfm.compareHint')}</span>
        <div style={{ marginTop: 12 }}>
          <Alert type="info" showIcon message={t('sfm.compareEmpty')} />
        </div>
      </div>
    );
  }

  const columns = [
    {
      title: t('sfm.block.name'),
      key: 'block_name',
      render: (r: SfmCompareBlockRow) => (
        <span>
          <strong>{r.block_name}</strong>
          {r.area_source === 'workspace' ? (
            <SourceTag kind="workspace" />
          ) : (
            <Tag style={{ marginLeft: 8, fontSize: 10, lineHeight: '14px' }}>
              {t('sfm.sourceArea')}
            </Tag>
          )}
        </span>
      ),
    },
    {
      title: t('sfm.deltaBand'),
      key: 'slope_band',
      render: (r: SfmCompareBlockRow) =>
        r.slope_band ? (
          <span>
            <Pair before={fmt(r.slope_band.before)} after={fmt(r.slope_band.after)} />
            <SourceTag kind={r.slope_source} />
          </span>
        ) : (
          '—'
        ),
    },
    {
      title: t('sfm.deltaOrientation'),
      key: 'orientation',
      render: (r: SfmCompareBlockRow) =>
        r.orientation ? (
          <span>
            <Pair before={r.orientation.before ?? '—'} after={r.orientation.after ?? '—'} />
            <SourceTag kind={r.orientation_source} />
          </span>
        ) : (
          '—'
        ),
    },
    {
      title: t('sfm.deltaStratum'),
      key: 'stratum',
      render: (r: SfmCompareBlockRow) =>
        r.stratum ? (
          <Pair
            before={r.stratum.before?.stratum ?? '—'}
            after={r.stratum.after?.stratum ?? '—'}
          />
        ) : (
          '—'
        ),
    },
    {
      title: t('sfm.deltaType'),
      key: 'type_no',
      render: (r: SfmCompareBlockRow) =>
        r.type_no ? (
          <Pair
            before={r.type_no.before != null ? <SfmTypeTag n={r.type_no.before} /> : '—'}
            after={r.type_no.after != null ? <SfmTypeTag n={r.type_no.after} /> : '—'}
          />
        ) : (
          '—'
        ),
    },
    {
      title: t('sfm.deltaPrescription'),
      key: 'prescription',
      render: (r: SfmCompareBlockRow) =>
        r.prescription ? (
          <Pair before={r.prescription.before ?? '—'} after={r.prescription.after ?? '—'} />
        ) : (
          '—'
        ),
    },
    {
      title: t('sfm.deltaWorkingCircle'),
      key: 'working_circle',
      render: (r: SfmCompareBlockRow) =>
        r.working_circle ? (
          <Pair
            before={r.working_circle.before ?? '—'}
            after={r.working_circle.after ?? '—'}
          />
        ) : (
          '—'
        ),
    },
  ];

  return (
    <div
      style={{
        marginTop: 16,
        padding: 16,
        background: '#fafafa',
        border: '1px solid #f0f0f0',
        borderRadius: 8,
      }}
    >
      <h4 style={{ margin: '0 0 4px' }}>{t('sfm.compare')}</h4>
      <span style={{ fontSize: 12, color: '#888' }}>{t('sfm.compareHint')}</span>

      {fs.production_area_ha ||
      fs.protection_area_ha ||
      fs.total_annual_harvest_m3 ? (
        <div
          style={{
            display: 'flex',
            gap: 24,
            flexWrap: 'wrap',
            alignItems: 'flex-start',
            margin: '16px 0',
          }}
        >
          {fs.production_area_ha && (
            <Stat
              label={t('sfm.summary.productionArea')}
              value={
                <Pair
                  before={`${fmt(fs.production_area_ha.before)} ${t('sfm.unit.ha')}`}
                  after={`${fmt(fs.production_area_ha.after)} ${t('sfm.unit.ha')}`}
                />
              }
            />
          )}
          {fs.protection_area_ha && (
            <Stat
              label={t('sfm.summary.protectionArea')}
              value={
                <Pair
                  before={`${fmt(fs.protection_area_ha.before)} ${t('sfm.unit.ha')}`}
                  after={`${fmt(fs.protection_area_ha.after)} ${t('sfm.unit.ha')}`}
                />
              }
            />
          )}
          {fs.total_annual_harvest_m3 && (
            <Stat
              label={t('sfm.summary.allowableHarvest')}
              value={
                <Pair
                  before={`${fmt(fs.total_annual_harvest_m3.before)} ${t('sfm.unit.m3PerYear')}`}
                  after={`${fmt(fs.total_annual_harvest_m3.after)} ${t('sfm.unit.m3PerYear')}`}
                />
              }
            />
          )}
        </div>
      ) : null}

      {fs.felling_series && fs.felling_series.length > 0 && (
        <Table
          rowKey={(r) => String(r.type_no)}
          size="small"
          pagination={false}
          style={{ marginBottom: 16 }}
          columns={[
            { title: t('sfm.deltaHarvest'), key: 't', render: (r: (typeof fs.felling_series)[0]) => <SfmTypeTag n={r.type_no} /> },
            { title: t('sfm.series.heading'), dataIndex: 'branch', key: 'branch' },
            {
              title: t('sfm.series.annualHarvest'),
              key: 'a',
              render: (r: (typeof fs.felling_series)[0]) => (
                <Pair
                  before={fmt(r.annual_harvest_m3.before)}
                  after={fmt(r.annual_harvest_m3.after)}
                />
              ),
            },
          ]}
          dataSource={fs.felling_series}
        />
      )}

      {fs.sampling && fs.sampling.length > 0 && (
        <Table
          rowKey={(r) => r.block_name}
          size="small"
          pagination={false}
          style={{ marginBottom: 16 }}
          columns={[
            { title: t('sfm.block.name'), dataIndex: 'block_name', key: 'block_name' },
            {
              title: t('sfm.deltaStratum'),
              key: 's',
              render: (r: (typeof fs.sampling)[0]) =>
                `${r.stratum.before ?? '—'} → ${r.stratum.after ?? '—'}`,
            },
            {
              title: t('sfm.deltaIntensity'),
              key: 'i',
              render: (r: (typeof fs.sampling)[0]) => (
                <Pair
                  before={`${fmt(r.intensity_pct.before, 2)}%`}
                  after={`${fmt(r.intensity_pct.after, 2)}%`}
                />
              ),
            },
          ]}
          dataSource={fs.sampling}
        />
      )}

      {compare.blocks.length > 0 ? (
        <Table
          rowKey="block_name"
          size="small"
          pagination={false}
          columns={columns}
          dataSource={compare.blocks}
        />
      ) : null}
    </div>
  );
};

export default SfmComparePanel;