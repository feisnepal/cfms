/** NtfpCollectPanel — take the Excel form to the plots, bring it back, and see how much of the survey is in. */
import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Popconfirm, Progress, Segmented, Select, Table, Tag, Upload, message } from 'antd';
import { DownloadOutlined, UploadOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { ntfpApi, type NtfpDesign, type NtfpEntryMode, type NtfpFinding, type NtfpPlotBadge, type NtfpRecords, type NtfpUploadResult } from '../../services/api';
import { downloadFromApi } from '../../utils/download';
import { apiErrorText } from '../../lib/apiErrorText';
import { PLOT_STATUS_COLOUR, errorKey, overlayPending, plotSummaries, progressPct, sortFindings, type PlotLayer } from '../../lib/ntfp';
import NtfpPlotMap from './NtfpPlotMap';
import NtfpPlotEntry from './NtfpPlotEntry';
import NtfpOutboxBar from './NtfpOutboxBar';
import { useOfflineReady } from '../../pwa/useOfflineReady';
import { useNtfpOutbox } from '../../hooks/useNtfpOutbox';

interface Props {
  calculationId: string;
  hasDesign: boolean;
  records: NtfpRecords | null;
  onChanged: () => void;
  /** the saved design and the forest boundary: the map way of entering needs them */
  design?: NtfpDesign | null;
  boundary?: any;
}

export default function NtfpCollectPanel({ calculationId, hasDesign, records, onChanged, design, boundary }: Props) {
  const t = useT();
  // a forest's records come either from the uploaded form or from the map, never both: the stored records decide, and while there are none the user chooses
  const [choice, setChoice] = useState<NtfpEntryMode>('upload');
  const mode: NtfpEntryMode = records?.mode ?? choice;
  const locked = !!records?.mode;
  const [layer, setLayer] = useState<PlotLayer>('status');
  const [plotOpen, setPlotOpen] = useState<number | null>(null);
  // what was saved on the phone while there was no signal, and is sent when there is
  const outbox = useNtfpOutbox(calculationId, () => { onChanged(); });
  const offlineReady = useOfflineReady();   // is this page saved on the phone for opening without a signal
  // the "I am here" verdict and the photo count of every plot, for the map
  const [badges, setBadges] = useState<Record<string, NtfpPlotBadge>>({});
  const loadBadges = useCallback(() => {
    ntfpApi.allExtras(calculationId).then((r) => setBadges(r.plots)).catch(() => setBadges({}));   // the map is still usable without the rings
  }, [calculationId]);
  useEffect(() => { if (hasDesign && mode === 'manual') loadBadges(); }, [hasDesign, mode, loadBadges]);
  const [busy, setBusy] = useState<'download' | 'upload' | 'delete' | null>(null);
  const [findings, setFindings] = useState<NtfpFinding[]>([]);
  const [outcome, setOutcome] = useState<NtfpUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const download = async () => {
    setError(null);
    setBusy('download');
    try {
      await downloadFromApi(ntfpApi.formPath(calculationId), 'NTFP_Form.xlsx');
    } catch (err: any) {
      setError(err?.message || t('ntfp.error.generic'));
    } finally {
      setBusy(null);
    }
  };

  const upload = async (file: File) => {
    setError(null);
    setOutcome(null);
    setFindings([]);
    setBusy('upload');
    try {
      const res = await ntfpApi.uploadForm(calculationId, file);
      setOutcome(res);
      setFindings(res.findings);
      message.success(t('ntfp.collect.imported', { obs: res.observations_written, w: res.weights_written }));
      onChanged();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (detail?.code === 'form.invalid' && Array.isArray(detail.findings)) {
        setFindings(detail.findings as NtfpFinding[]);
        setError(t('ntfp.collect.refused'));
      } else {
        const key = errorKey(detail?.code);
        setError(key ? t(key) : apiErrorText(err, t('ntfp.error.generic')));
      }
    } finally {
      setBusy(null);
    }
  };

  const clear = async () => {
    setBusy('delete');
    try {
      await ntfpApi.deleteRecords(calculationId);
      setFindings([]);
      setOutcome(null);
      onChanged();
    } catch (err) {
      setError(apiErrorText(err, t('ntfp.error.generic')));
    } finally {
      setBusy(null);
    }
  };

  if (!hasDesign) return <Alert type="info" showIcon title={t('ntfp.collect.needDesign')} />;
  const pct = records ? progressPct(records.pairs_recorded, records.pairs_assigned) : 0;
  const names: Record<string, string> = {};
  design?.species.forEach((s) => { names[s.species_key] = s.label; });
  const pendingPlots = outbox.waiting.filter((i) => i.kind === 'plot');
  const shownObservations = overlayPending(records?.observations ?? [], pendingPlots);   // what was typed offline shows at once
  const summaries = design ? plotSummaries(design.plots, shownObservations) : undefined;
  const plot = design?.plots.find((p) => p.plot_number === plotOpen) ?? null;
  const clearButton = records && records.pairs_recorded > 0 && (
    <Popconfirm title={t('ntfp.collect.clearConfirm')} okText={t('common.delete')} cancelText={t('common.cancel')} onConfirm={clear}>
      <Button danger loading={busy === 'delete'}>{t('ntfp.collect.clear')}</Button>
    </Popconfirm>
  );

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 4 }}>{t('ntfp.collect.wayTitle')}</div>
        <Segmented<NtfpEntryMode> value={mode} onChange={setChoice}
          options={[
            { value: 'upload', label: t('ntfp.collect.wayUpload'), disabled: locked && mode !== 'upload' },
            { value: 'manual', label: t('ntfp.collect.wayManual'), disabled: locked && mode !== 'manual' },
          ]} />
        {locked && <div style={{ marginTop: 4, fontSize: 12 }}>{t(mode === 'upload' ? 'ntfp.collect.lockedUpload' : 'ntfp.collect.lockedManual')}</div>}
      </div>
      {mode === 'upload' ? (
        <>
          <ol style={{ paddingLeft: 18 }}>
            <li>{t('ntfp.collect.step1')}</li>
            <li>{t('ntfp.collect.step2')}</li>
            <li>{t('ntfp.collect.step3')}</li>
          </ol>
          <Alert type="info" showIcon style={{ margin: '8px 0 12px' }} title={t('ntfp.collect.zeroRule')} />
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
            <Button icon={<DownloadOutlined />} onClick={download} loading={busy === 'download'}>{t('ntfp.collect.download')}</Button>
            <Upload accept=".xlsx" showUploadList={false} beforeUpload={(f) => { void upload(f as File); return false; }} disabled={busy === 'upload'}>
              <Button icon={<UploadOutlined />} type="primary" loading={busy === 'upload'}>{t('ntfp.collect.upload')}</Button>
            </Upload>
            {clearButton}
          </div>
        </>
      ) : (
        <>
          <NtfpOutboxBar outbox={outbox} names={names} />
          {offlineReady !== 'unsupported' && (
            <div style={{ marginBottom: 8 }}>
              <Tag color={offlineReady === 'ready' ? 'green' : 'orange'}>{t(offlineReady === 'ready' ? 'ntfp.offline.ready' : 'ntfp.offline.notReady')}</Tag>
            </div>
          )}
          <Alert type="info" showIcon style={{ margin: '0 0 12px' }} title={t('ntfp.collect.mapHelp')} />
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
            <Select<PlotLayer> value={layer} onChange={setLayer} style={{ minWidth: 220 }} aria-label={t('ntfp.collect.layer')}
              options={[
                { value: 'status', label: t('ntfp.collect.layerStatus') },
                { value: 'count', label: t('ntfp.collect.layerCount') },
                ...(design?.species ?? []).map((s) => ({ value: `species:${s.species_key}`, label: t('ntfp.collect.layerSpecies', { name: s.label }) })),
              ]} />
            {layer === 'status' && (
              <span style={{ fontSize: 12 }}>
                <span style={{ marginRight: 12 }}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, border: '3px solid #1565c0', boxSizing: 'border-box', marginRight: 4 }} />{t('ntfp.here.legendAt')}</span>
                <span style={{ marginRight: 12 }}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, border: '3px solid #c62828', boxSizing: 'border-box', marginRight: 4 }} />{t('ntfp.here.legendFar')}</span>
                {(['none', 'partial', 'done'] as const).map((k) => (
                  <span key={k} style={{ marginRight: 12 }}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, background: PLOT_STATUS_COLOUR[k], marginRight: 4 }} />{t(`ntfp.collect.status.${k}`)}</span>
                ))}
              </span>
            )}
            {clearButton}
          </div>
          {design && (
            <NtfpPlotMap boundary={boundary} plots={design.plots} transects={design.transects} names={names} height={420}
              summaries={summaries} layer={layer} selected={plotOpen} onSelect={setPlotOpen}
              pending={new Set(outbox.waiting.map((i) => i.plotNumber))}
              verdicts={Object.fromEntries(Object.entries(badges).map(([k, v]) => [Number(k), v.verdict]))} />
          )}
          <NtfpPlotEntry open={plot != null} calculationId={calculationId} plotNumber={plot?.plot_number ?? null} stratum={plot?.stratum}
            speciesKeys={plot?.species_keys ?? []} names={names} stored={shownObservations.filter((o) => o.plot_number === plot?.plot_number)} pending={outbox.items}
            onClose={() => setPlotOpen(null)} onSaved={onChanged} onExtrasChanged={loadBadges} />
        </>
      )}

      {records && (
        <div style={{ maxWidth: 520, marginBottom: 16 }}>
          <div>{t('ntfp.collect.progress', { done: records.pairs_recorded, all: records.pairs_assigned, w: records.weights })}</div>
          <Progress percent={pct} />
        </div>
      )}

      {error && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={error} />}
      {outcome?.ok && findings.length === 0 && <Alert type="success" showIcon style={{ marginBottom: 12 }} title={t('ntfp.collect.imported', { obs: outcome.observations_written, w: outcome.weights_written })} />}
      {findings.length > 0 && (
        <Table<NtfpFinding> size="small" rowKey={(f) => `${f.sheet}-${f.row}-${f.column}-${f.code}`} dataSource={sortFindings(findings)} pagination={{ pageSize: 10, hideOnSinglePage: true }}
          columns={[
            { title: t('ntfp.collect.colSeverity'), dataIndex: 'severity', width: 90, render: (s: string) => <Tag color={s === 'error' ? 'red' : 'orange'}>{t(s === 'error' ? 'ntfp.collect.error' : 'ntfp.collect.warning')}</Tag> },
            { title: t('ntfp.collect.colSheet'), dataIndex: 'sheet', width: 90 },
            { title: t('ntfp.collect.colRow'), dataIndex: 'row', width: 70 },
            { title: t('ntfp.collect.colColumn'), dataIndex: 'column', width: 150 },
            { title: t('ntfp.collect.colMessage'), dataIndex: 'message' },
          ]} />
      )}
    </div>
  );
}
