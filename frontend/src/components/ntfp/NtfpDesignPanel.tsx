/** NtfpDesignPanel — lay the sample plots out (preview first), save the design, and see it on the map. */
import { useMemo, useState } from 'react';
import { Alert, Button, InputNumber, Popconfirm, Radio, Space, Table, Tag, message } from 'antd';
import { useT } from '../../i18n/hooks';
import { ntfpApi, type NtfpDesign, type NtfpSpecies } from '../../services/api';
import { apiErrorText } from '../../lib/apiErrorText';
import { buildDesignRequest, designProblem, errorKey, plotsPerSpecies, warningKey, type NtfpPick } from '../../lib/ntfp';
import NtfpPlotMap from './NtfpPlotMap';

interface Props {
  calculationId: string;
  boundary?: any;
  species: NtfpSpecies[];
  picks: Record<string, NtfpPick>;
  stored: NtfpDesign | null;
  hasRecords: boolean;
  onStored: (d: NtfpDesign | null) => void;
}

export default function NtfpDesignPanel({ calculationId, boundary, species, picks, stored, hasRecords, onStored }: Props) {
  const t = useT();
  const [shape, setShape] = useState<'square' | 'circular'>((stored?.plot_shape as 'square' | 'circular') ?? 'square');
  const [seed, setSeed] = useState<number | null>(null);
  const [minPlots, setMinPlots] = useState<number>(stored?.min_plots ?? 3);
  const [preview, setPreview] = useState<NtfpDesign | null>(null);
  const [busy, setBusy] = useState<'preview' | 'save' | 'delete' | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const shown = preview ?? stored;
  const problemKey = designProblem(species, picks);
  const names = useMemo(() => {
    const m: Record<string, string> = {};
    species.forEach((s) => { m[s.species_key] = s.nepali_name; });
    shown?.species.forEach((s) => { m[s.species_key] = m[s.species_key] ?? s.label; });
    return m;
  }, [species, shown]);

  const fail = (err: any) => {
    const code = err?.response?.data?.detail?.code as string | undefined;
    const key = errorKey(code);
    setProblem(key ? t(key) : apiErrorText(err, t('ntfp.error.generic')));
  };

  const run = async (kind: 'preview' | 'save') => {
    setProblem(null);
    setBusy(kind);
    try {
      const body = buildDesignRequest(picks, shape, seed, minPlots);
      if (kind === 'preview') {
        setPreview(await ntfpApi.previewDesign(calculationId, body));
      } else {
        const saved = await ntfpApi.createDesign(calculationId, body);
        setPreview(null);
        onStored(saved);
        message.success(t('ntfp.design.saved'));
      }
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    setProblem(null);
    setBusy('delete');
    try {
      await ntfpApi.deleteDesign(calculationId);
      setPreview(null);
      onStored(null);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const perSpecies = shown ? plotsPerSpecies(shown.plots) : {};

  return (
    <div>
      <p>{t('ntfp.design.intro')}</p>
      {hasRecords && <Alert type="warning" showIcon style={{ marginBottom: 12 }} title={t('ntfp.design.lockedByRecords')} />}
      <Space wrap style={{ marginBottom: 12 }} align="center">
        <Radio.Group value={shape} onChange={(e) => setShape(e.target.value)} disabled={hasRecords}
          options={[{ value: 'square', label: t('ntfp.design.square') }, { value: 'circular', label: t('ntfp.design.circular') }]} />
        <span>{t('ntfp.design.minPlots')} <InputNumber min={1} max={50} value={minPlots} onChange={(v) => setMinPlots(Number(v ?? 3))} disabled={hasRecords} aria-label={t('ntfp.design.minPlots')} /></span>
        <span>{t('ntfp.design.seed')} <InputNumber min={1} value={seed ?? undefined} placeholder={stored ? String(stored.seed) : t('ntfp.design.seedRandom')} onChange={(v) => setSeed(v == null ? null : Number(v))} disabled={hasRecords} aria-label={t('ntfp.design.seed')} /></span>
        <Button onClick={() => run('preview')} loading={busy === 'preview'} disabled={!!problemKey || hasRecords}>{t('ntfp.design.preview')}</Button>
        {stored ? (
          <Popconfirm title={t('ntfp.design.replaceConfirm')} okText={t('ntfp.design.replace')} cancelText={t('common.cancel')} onConfirm={() => run('save')} disabled={!!problemKey || hasRecords}>
            <Button type="primary" loading={busy === 'save'} disabled={!!problemKey || hasRecords}>{t('ntfp.design.replace')}</Button>
          </Popconfirm>
        ) : (
          <Button type="primary" onClick={() => run('save')} loading={busy === 'save'} disabled={!!problemKey}>{t('ntfp.design.save')}</Button>
        )}
        {stored && (
          <Popconfirm title={t('ntfp.design.deleteConfirm')} okText={t('common.delete')} cancelText={t('common.cancel')} onConfirm={remove} disabled={hasRecords}>
            <Button danger loading={busy === 'delete'} disabled={hasRecords}>{t('ntfp.design.delete')}</Button>
          </Popconfirm>
        )}
      </Space>
      {problemKey && <Alert type="info" showIcon style={{ marginBottom: 12 }} title={t(problemKey)} />}
      {problem && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={problem} />}

      {!shown ? (
        <Alert type="info" showIcon title={t('ntfp.design.none')} />
      ) : (
        <>
          <p style={{ marginBottom: 8 }}>
            {preview ? <Tag color="blue">{t('ntfp.design.previewTag')}</Tag> : <Tag color="green">{t('ntfp.design.savedTag')}</Tag>}
            {t('ntfp.design.summary', { plots: shown.plots.length, seed: shown.seed })}
          </p>
          {shown.warnings.length > 0 && (
            <Alert type="warning" showIcon style={{ marginBottom: 12 }} title={shown.warnings.map((w) => t(warningKey(w))).join(' · ')} />
          )}
          <NtfpPlotMap boundary={boundary} plots={shown.plots} transects={shown.transects} names={names} />
          <h4 style={{ marginTop: 16 }}>{t('ntfp.design.speciesTitle')}</h4>
          <Table size="small" pagination={false} rowKey="species_key" dataSource={shown.species}
            columns={[
              { title: t('ntfp.species.colName'), key: 'n', render: (_: unknown, s) => names[s.species_key] ?? s.label },
              { title: t('ntfp.design.colPlotSize'), dataIndex: 'plot_sqm', render: (v: number) => t('ntfp.species.plotSqm', { n: v }) },
              { title: t('ntfp.design.colIntensity'), key: 'i', render: (_: unknown, s) => <>{`${s.intensity_pct}% → ${s.intensity_achieved_pct}%`}{s.below_guideline && <Tag color="orange" style={{ marginLeft: 6 }}>{t('ntfp.design.belowGuideline')}</Tag>}</> },
              { title: t('ntfp.design.colPlots'), key: 'p', render: (_: unknown, s) => perSpecies[s.species_key] ?? s.plots },
            ]} />
          {shown.species.some((sp) => sp.below_guideline) && <Alert type="warning" showIcon style={{ marginTop: 8 }} title={t('ntfp.design.belowGuidelineNote')} />}
          <h4 style={{ marginTop: 16 }}>{t('ntfp.design.strataTitle')}</h4>
          <Table size="small" pagination={false} rowKey="name" dataSource={shown.strata}
            columns={[
              { title: t('ntfp.design.colStratum'), dataIndex: 'name' },
              { title: t('ntfp.design.colArea'), dataIndex: 'area_ha', render: (v: number) => `${v} ha` },
              { title: t('ntfp.design.colWanted'), dataIndex: 'plots_wanted' },
              { title: t('ntfp.design.colLaid'), dataIndex: 'plots_laid' },
              { title: t('ntfp.design.colSpacing'), dataIndex: 'spacing_m', render: (v: number) => `${v} m` },
            ]} />
        </>
      )}
    </div>
  );
}
