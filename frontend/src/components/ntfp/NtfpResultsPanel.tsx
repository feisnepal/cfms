/** NtfpResultsPanel — frequency, density, importance value, yield and stock per species, from the records uploaded so far. */
import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Spin, Table, Tag, Tooltip } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { ntfpApi, type NtfpPartResult, type NtfpResults, type NtfpSpeciesResult } from '../../services/api';
import { apiErrorText } from '../../lib/apiErrorText';
import { formatDecimal } from '../../i18n/numberFormat';
import { partKey, trustOf, warningKey, yieldOf } from '../../lib/ntfp';

interface Props {
  calculationId: string;
  /** bump to re-read after records change */
  refreshKey: number;
}

const TRUST_COLOUR = { good: 'green', fair: 'gold', poor: 'red', unknown: 'default' } as const;

export default function NtfpResultsPanel({ calculationId, refreshKey }: Props) {
  const t = useT();
  const [data, setData] = useState<NtfpResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await ntfpApi.results(calculationId));
    } catch (err: any) {
      setData(null);
      // 404 no_design is the normal state of a forest that has not started: say so rather than showing an error
      setError(err?.response?.data?.detail?.code === 'no_design' ? 'no_design' : apiErrorText(err, t('ntfp.error.generic')));
    } finally {
      setLoading(false);
    }
  }, [calculationId, t]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  if (loading && !data) return <Spin />;
  if (error === 'no_design') return <Alert type="info" showIcon title={t('ntfp.results.needDesign')} />;
  if (error) return <Alert type="error" showIcon title={error} />;
  if (!data) return null;
  if (data.survey.pairs_recorded === 0) return <Alert type="info" showIcon title={t('ntfp.results.noRecords')} />;

  const n = (v: number | null | undefined, d = 1) => (v == null ? '—' : formatDecimal(v, d));

  const partColumns = [
    { title: t('ntfp.results.colPart'), dataIndex: 'part_group', render: (g: string | null) => (g ? t(`ntfp.part.${partKey(g)}`) : '—') },
    { title: t('ntfp.results.colSamples'), dataIndex: 'samples' },
    {
      title: t('ntfp.results.colMeanFresh'), key: 'mf',
      render: (_: unknown, p: NtfpPartResult) => (p.scale_factor > 1 && p.mean_whole_fresh_g != null ? (
        <span>{n(p.mean_fresh_g, 0)}<span style={{ fontSize: 12 }}> → {t('ntfp.results.scaledTo', { whole: n(p.mean_whole_fresh_g, 0), factor: n(p.scale_factor, 2) })}</span></span>
      ) : n(p.mean_fresh_g, 0)),
    },
    {
      title: t('ntfp.results.colCf'), key: 'cf',
      render: (_: unknown, p: NtfpPartResult) => (p.conversion_factor == null ? '—' : (
        <span>{n(p.conversion_factor, 3)}{p.conversion_factor_reference != null && <span style={{ fontSize: 12 }}> ({t('ntfp.results.guideline')} {n(p.conversion_factor_reference, 3)})</span>}</span>
      )),
    },
    {
      title: t('ntfp.results.colYield'), key: 'y',
      render: (_: unknown, p: NtfpPartResult) => {
        const y = yieldOf(p);
        return y.value == null ? '—' : <span>{n(y.value, 2)} <Tag>{t(y.basis === 'dry' ? 'ntfp.results.dry' : 'ntfp.results.fresh')}</Tag></span>;
      },
    },
    { title: t('ntfp.results.colStock'), key: 's', render: (_: unknown, p: NtfpPartResult) => n(p.stock_dry_kg ?? p.stock_fresh_kg, 0) },
    {
      title: t('ntfp.results.colPrice'), key: 'pr',
      render: (_: unknown, p: NtfpPartResult) => (p.price ? (
        <Tooltip title={p.price.note}>
          <span>{p.price.npr_per_unit} / {p.price.unit}{p.price.estimated && <Tag color="orange" style={{ marginLeft: 4 }}>{t('ntfp.species.estimated')}</Tag>}</span>
        </Tooltip>
      ) : '—'),
    },
    { title: '', key: 'w', render: (_: unknown, p: NtfpPartResult) => p.warnings.map((w) => <Tag key={w} color="orange">{t(warningKey(w))}</Tag>) },
  ];

  const columns = [
    { title: t('ntfp.species.colName'), key: 'name', render: (_: unknown, s: NtfpSpeciesResult) => (
      <div><strong>{s.nepali_name || s.label}</strong><div style={{ fontStyle: 'italic', fontSize: 12 }}>{s.scientific_name ?? ''}</div></div>
    ) },
    { title: t('ntfp.results.colPlots'), key: 'pl', render: (_: unknown, s: NtfpSpeciesResult) => `${s.plots_surveyed} / ${s.plots_present}` },
    { title: t('ntfp.results.colFrequency'), dataIndex: 'frequency_pct', render: (v: number | null) => n(v, 1) },
    {
      title: t('ntfp.results.colDensity'), key: 'd',
      render: (_: unknown, s: NtfpSpeciesResult) => (
        <span>{n(s.density_per_ha, 1)}{' '}
          <Tooltip title={s.density_precision_pct == null ? t('ntfp.results.precisionUnknown') : t('ntfp.results.precisionHint', { p: n(s.density_precision_pct, 0) })}>
            <Tag color={TRUST_COLOUR[trustOf(s.density_precision_pct)]}>{s.density_precision_pct == null ? '?' : `±${n(s.density_precision_pct, 0)}%`}</Tag>
          </Tooltip>
        </span>
      ),
    },
    { title: t('ntfp.results.colIvi'), key: 'ivi', render: (_: unknown, s: NtfpSpeciesResult) => (s.ivi == null ? '—' : <span>{n(s.ivi, 1)} <Tag>#{s.ivi_rank}</Tag></span>) },
    { title: '', key: 'w', render: (_: unknown, s: NtfpSpeciesResult) => s.warnings.map((w) => <Tag key={w} color="orange">{t(warningKey(w))}</Tag>) },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span>{t('ntfp.results.summary', { done: data.survey.pairs_recorded, all: data.survey.pairs_assigned, ha: n(data.forest_area_ha, 1) })}</span>
        <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>{t('ntfp.results.refresh')}</Button>
      </div>
      <Alert type="info" showIcon style={{ marginBottom: 12 }} title={t('ntfp.results.iviNote')} description={t('ntfp.results.fractionNote')} />
      <Table<NtfpSpeciesResult> size="small" rowKey="species_key" dataSource={data.species} columns={columns} pagination={false}
        expandable={{
          rowExpandable: (s) => s.parts.length > 0,
          expandedRowRender: (s) => <Table size="small" pagination={false} rowKey={(p) => String(p.part_group)} dataSource={s.parts} columns={partColumns} />,
        }} />
    </div>
  );
}
