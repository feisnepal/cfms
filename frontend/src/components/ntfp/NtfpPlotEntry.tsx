/**
 * NtfpPlotEntry — the bottom sheet for typing in what was found in one sample plot (owner, 2026-10-22).
 *
 * Opened by a click on the plot's icon on the map. One card per species of the plot: the count (0 where it was looked for and not found, empty where
 * not surveyed), mature and small plants, and the fresh and dry weight of each weighed plant. Saving sends the whole plot; the server checks it with
 * the same rules as the Excel form and writes nothing if anything is wrong. Large inputs: this is meant to be used standing in the forest on a phone.
 */
import { useEffect, useState } from 'react';
import { Alert, Button, Drawer, Input, InputNumber, Space, message } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { ntfpApi, type NtfpFinding, type NtfpObservationRecord, type NtfpPlotExtras } from '../../services/api';
import NtfpPlotHere from './NtfpPlotHere';
import NtfpPlotPhotos from './NtfpPlotPhotos';
import { enqueue, isNetworkFailure, type OutboxItem } from '../../services/ntfpOutbox';
import { apiErrorText } from '../../lib/apiErrorText';
import { draftIsEmpty, draftProblem, draftsFor, draftToEntry, errorKey, type EntryDraft, type Position } from '../../lib/ntfp';

interface Props {
  open: boolean;
  calculationId: string;
  plotNumber: number | null;
  stratum?: string;
  speciesKeys: string[];
  names: Record<string, string>;
  /** the stored records of this plot */
  stored: NtfpObservationRecord[];
  onClose: () => void;
  onSaved: () => void;
  /** the position check or the photos of the plot changed (the map shows them) */
  onExtrasChanged?: () => void;
  /** what is kept on the phone for this forest, waiting for a signal */
  pending?: OutboxItem[];
}

const today = () => new Date().toISOString().slice(0, 10);

export default function NtfpPlotEntry({ open, calculationId, plotNumber, stratum, speciesKeys, names, stored, onClose, onSaved, onExtrasChanged, pending = [] }: Props) {
  const t = useT();
  const [drafts, setDrafts] = useState<EntryDraft[]>([]);
  const [date, setDate] = useState(today());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [findings, setFindings] = useState<NtfpFinding[]>([]);
  const [extras, setExtras] = useState<NtfpPlotExtras | null>(null);
  const [position, setPosition] = useState<Position | null>(null);

  const loadExtras = () => {
    if (plotNumber == null) return;
    ntfpApi.plotExtras(calculationId, plotNumber).then(setExtras).catch(() => setExtras(null));   // without them the sheet still works: no check shown, no photos
  };

  // the sheet starts from what is stored for the plot each time it is opened for a plot
  useEffect(() => {
    if (!open) return;
    const d = draftsFor(speciesKeys, stored);
    setDrafts(d);
    setDate(d.find((x) => x.visit_date)?.visit_date || today());
    setError(null);
    setFindings([]);
    setPosition(null);
    setExtras(null);
    loadExtras();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when a plot is opened, not on every refresh of the records
  }, [open, plotNumber]);

  const patch = (key: string, p: Partial<EntryDraft>) => setDrafts((ds) => ds.map((d) => (d.species_key === key ? { ...d, ...p } : d)));
  const setWeight = (key: string, i: number, p: Partial<{ fresh: number | null; dry: number | null }>) =>
    setDrafts((ds) => ds.map((d) => (d.species_key === key ? { ...d, weights: d.weights.map((w, j) => (j === i ? { ...w, ...p } : w)) } : d)));

  const save = async () => {
    setError(null);
    setFindings([]);
    const filled = drafts.map((d) => (draftIsEmpty(d) ? d : { ...d, visit_date: date }));
    for (const d of filled) {
      const key = draftProblem(d);
      if (key) {
        setError(`${names[d.species_key] ?? d.species_key}: ${t(key)}`);
        return;
      }
    }
    if (plotNumber == null) return;
    setSaving(true);
    const entries = filled.map(draftToEntry);
    const keep = async () => {
      await enqueue({ calcId: calculationId, kind: 'plot', plotNumber, entries });
      message.info(t('ntfp.offline.savedPlot', { n: plotNumber }));
      onSaved();
      onClose();
    };
    try {
      if (typeof navigator !== 'undefined' && navigator.onLine === false) { await keep(); return; }
      const res = await ntfpApi.savePlot(calculationId, plotNumber, entries);
      message.success(t('ntfp.entry.saved', { n: plotNumber, obs: res.observations_written, w: res.weights_written }));
      onSaved();
      onClose();
    } catch (err: any) {
      if (isNetworkFailure(err)) {
        try { await keep(); } catch (e2) { setError(apiErrorText(e2, t('ntfp.error.generic'))); }   // no signal: the plot waits on the phone
        return;
      }
      const detail = err?.response?.data?.detail;
      if (detail?.code === 'plot.invalid' && Array.isArray(detail.findings)) {
        setFindings((detail.findings as NtfpFinding[]).filter((f) => f.severity === 'error'));
        setError(t('ntfp.entry.refused'));
      } else {
        const key = errorKey(detail?.code);
        setError(key ? t(key) : apiErrorText(err, t('ntfp.error.generic')));
      }
    } finally {
      setSaving(false);
    }
  };

  const num = (v: number | null, onChange: (n: number | null) => void, label: string, max = 1_000_000) => (
    <InputNumber size="large" min={0} max={max} precision={0} inputMode="numeric" value={v} onChange={(n) => onChange(n == null ? null : Number(n))} aria-label={label} style={{ width: '100%' }} />
  );

  return (
    <Drawer open={open} onClose={onClose} placement="bottom" size="88vh" destroyOnHidden
      title={t('ntfp.entry.title', { n: plotNumber ?? '' })}
      extra={<Space><Button size="large" onClick={onClose}>{t('common.cancel')}</Button><Button size="large" type="primary" loading={saving} onClick={() => void save()}>{t('ntfp.entry.save')}</Button></Space>}>
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        {stratum && <p style={{ marginBottom: 8 }}>{t('ntfp.entry.stratum', { name: stratum })}</p>}
        {plotNumber != null && (
          <NtfpPlotHere calculationId={calculationId} plotNumber={plotNumber} presence={extras?.presence ?? null}
            queued={pending.some((i) => i.kind === 'presence' && i.plotNumber === plotNumber && i.state === 'waiting')}
            onQueued={(pos) => { setPosition(pos); onExtrasChanged?.(); }}
            onChecked={(p, pos) => { setPosition(pos); setExtras((e) => ({ plot_number: plotNumber, photos: e?.photos ?? [], presence: p })); onExtrasChanged?.(); }} />
        )}
        <Alert type="info" showIcon style={{ marginBottom: 12 }} title={t('ntfp.collect.zeroRule')} />
        <label style={{ display: 'block', marginBottom: 12 }}>
          <div>{t('ntfp.entry.date')}</div>
          <Input size="large" type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} aria-label={t('ntfp.entry.date')} />
        </label>
        {error && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={error} />}
        {findings.length > 0 && (
          <ul style={{ marginBottom: 12, paddingLeft: 18 }}>
            {findings.map((f, i) => <li key={i}>{f.species_key ? `${names[f.species_key] ?? f.species_key}: ` : ''}{f.message}</li>)}
          </ul>
        )}
        {drafts.map((d) => {
          const name = names[d.species_key] ?? d.species_key;
          return (
            <section key={d.species_key} aria-label={name} style={{ border: '1px solid #d9d9d9', borderRadius: 8, padding: 12, marginBottom: 12 }}>
              <h4 style={{ margin: '0 0 8px' }}>{name}</h4>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8 }}>
                <label><div>{t('ntfp.entry.total')}</div>{num(d.count_total, (n) => patch(d.species_key, { count_total: n }), `${t('ntfp.entry.total')} ${name}`)}</label>
                <label><div>{t('ntfp.entry.mature')}</div>{num(d.count_mature, (n) => patch(d.species_key, { count_mature: n }), `${t('ntfp.entry.mature')} ${name}`)}</label>
                <label><div>{t('ntfp.entry.small')}</div>{num(d.count_small, (n) => patch(d.species_key, { count_small: n }), `${t('ntfp.entry.small')} ${name}`)}</label>
              </div>
              {(d.count_total ?? 0) > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontWeight: 600 }}>{t('ntfp.entry.weights')}</div>
                  {d.weights.map((w, i) => (
                    <Space key={i} align="end" style={{ display: 'flex', marginTop: 8 }}>
                      <label><div>{t('ntfp.entry.fresh', { n: i + 1 })}</div>
                        <InputNumber size="large" min={0} inputMode="decimal" value={w.fresh} onChange={(n) => setWeight(d.species_key, i, { fresh: n == null ? null : Number(n) })} aria-label={`${t('ntfp.entry.fresh', { n: i + 1 })} ${name}`} style={{ width: 130 }} /></label>
                      <label><div>{t('ntfp.entry.dry')}</div>
                        <InputNumber size="large" min={0} inputMode="decimal" value={w.dry} onChange={(n) => setWeight(d.species_key, i, { dry: n == null ? null : Number(n) })} aria-label={`${t('ntfp.entry.dry')} ${i + 1} ${name}`} style={{ width: 130 }} /></label>
                      <Button size="large" icon={<DeleteOutlined />} aria-label={t('ntfp.entry.removeWeight')} onClick={() => patch(d.species_key, { weights: d.weights.filter((_, j) => j !== i) })} />
                    </Space>
                  ))}
                  <Button size="large" icon={<PlusOutlined />} style={{ marginTop: 8 }} onClick={() => patch(d.species_key, { weights: [...d.weights, { fresh: null, dry: null }] })}>
                    {t('ntfp.entry.addWeight')}
                  </Button>
                </div>
              )}
              <label style={{ display: 'block', marginTop: 12 }}>
                <div>{t('ntfp.entry.notes')}</div>
                <Input size="large" maxLength={500} value={d.notes} onChange={(e) => patch(d.species_key, { notes: e.target.value })} aria-label={`${t('ntfp.entry.notes')} ${name}`} />
              </label>
            </section>
          );
        })}
        {plotNumber != null && (
          <NtfpPlotPhotos calculationId={calculationId} plotNumber={plotNumber} photos={extras?.photos ?? []} position={position} onChanged={() => { loadExtras(); onExtrasChanged?.(); }}
            pending={pending.filter((i) => i.kind === 'photo' && i.plotNumber === plotNumber)} onQueued={() => onExtrasChanged?.()} />
        )}
      </div>
    </Drawer>
  );
}
