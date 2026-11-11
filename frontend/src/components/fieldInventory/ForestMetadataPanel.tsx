/**
 * Forest Metadata — the record behind the report cover page.
 *
 * WORKSPACE_FLOW_NAV_PLAN D5. This pane exists because those facts used to live
 * in `ReportTab`'s component state, which meant the .docx cover page was whatever
 * one person had typed at the moment they pressed Generate. They are a record
 * now, so they are fetched once, saved explicitly, and read by the server.
 *
 * The form opens *seeded* rather than empty: the GET returns what the
 * calculation's own analysis already knows (province, district, palika, ward and
 * the forest name) and marks it `persisted: false` until somebody saves. That
 * split is the honest one — the values are suggestions, and until they are saved
 * they are not a record, which is why an unsaved forest is labelled as such
 * instead of looking filled in.
 *
 * Why the report controls are here and not in a separate step: they are the
 * *use* of this record, and the endpoint reads the record itself. There is no
 * form to fill and nothing to pass in, so the only thing left to choose is which
 * sections to write.
 */
import { NationalCodeBuilder, NationalCodeStatus } from './NationalCodeBuilder';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Checkbox, Progress, Spin, Tag, message } from 'antd';
import { forestMetadataApi, reportApi, FOREST_METADATA_FIELDS, FOREST_METADATA_OPTIONAL_FIELDS } from '../../services/api';
import type { ForestMetadata } from '../../services/api';
import { useT } from '../../i18n/hooks';
import { readDetail } from '../../hooks/useErrorHandler';
import i18n from '../../i18n';
import { NepaliDatePicker } from '../OperationalPlan/NepaliDatePicker';
import { ReportSectionFixLinks } from '../Report/ReportSectionFixLinks';
import { formatNumber } from '../../i18n/numberFormat';

/** One row of the form: which key, and which existing label to reuse. */
const FIELD_LABELS: Record<string, string> = {
  forest_name: 'reports.tab.forestName',
  group_name: 'reports.tab.groupName',
  province: 'reports.tab.province',
  district: 'reports.tab.district',
  palika: 'reports.tab.municipality',
  ward: 'reports.tab.ward',
  cf_national_code: 'reports.tab.cfNationalCode',
  fy_start: 'reports.tab.fyStart',
  fy_end: 'reports.tab.fyEnd',
};

/**
 * The two that never had a label: the old form dropped them, so they were
 * unreachable and `build_cover_page` printed a placeholder for them.
 */
const EXTRA_LABELS: Record<string, string> = {
  division: 'forestMetadata.division',
  sub_division: 'forestMetadata.subDivision',
};

const LOCATION_KEYS = ['province', 'district', 'palika', 'ward'] as const;

type MetadataField = (typeof FOREST_METADATA_FIELDS)[number] | (typeof FOREST_METADATA_OPTIONAL_FIELDS)[number];
/** Everything the form stores, mandatory first. */
const DATE_OPTIONAL = new Set<string>(['cf_handover_date', 'cf_first_renewal_date', 'constitution_approved_year']);
const MULTILINE_OPTIONAL = new Set<string>(['cf_history_note', 'cf_boundary_east', 'cf_boundary_south', 'cf_boundary_west', 'cf_boundary_north', 'main_non_timber_fp', 'ug_boundary_east', 'ug_boundary_south', 'ug_boundary_west', 'ug_boundary_north']);
const ALL_KEYS: readonly MetadataField[] = [...FOREST_METADATA_FIELDS, ...FOREST_METADATA_OPTIONAL_FIELDS];
/** The one value per field, as text. Every field is a string or absent. */
const textOf = (record: ForestMetadata, field: MetadataField): string =>
  (record[field as MetadataField] as string | null | undefined) ?? '';

interface SectionInfo {
  section: string;
  title_ne: string;
  title_en: string;
  status: 'available' | 'missing_data' | 'manual_input';
  auto_generate: boolean;
  /** the kinds of report data this section still lacks (status missing_data) */
  missing?: string[];
}

export const ForestMetadataPanel: React.FC<{ calculationId: string }> = ({ calculationId }) => {
  const t = useT();

  const [record, setRecord] = useState<ForestMetadata | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  const [sections, setSections] = useState<SectionInfo[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [includeImages, setIncludeImages] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  // An error is a translation *key* plus, optionally, a message the server
  // wrote. Keeping the key untranslated until render is what lets `load` depend
  // on calculationId alone -- see below.
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportErrorRaw, setReportErrorRaw] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const reportErrorText = reportErrorRaw ?? (reportError ? t(reportError) : null);
  const failWith = (key: string, raw: string | null = null) => {
    setReportError(key);
    setReportErrorRaw(raw);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const data = await forestMetadataApi.get(calculationId);
      setRecord(data);
      const next: Record<string, string> = {};
      for (const key of ALL_KEYS) {
        const value = textOf(data, key);
        if (value !== '') next[key] = value;
      }
      setDraft(next);
    } catch {
      // The message is chosen at render time, not here, so this callback needs
      // `calculationId` and nothing else. Capturing `t` would put its identity in
      // the dependency list of the effect below, and one render in which `t`
      // changed would refetch the record.
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [calculationId]);

  useEffect(() => {
    load();
  }, [load]);

  // Section availability is a property of the calculation, not of the record, so
  // it is fetched here rather than stored — and it is the one thing on this pane
  // that does not depend on the metadata having been saved.
  useEffect(() => {
    let cancelled = false;
    reportApi
      .getAvailableSections(calculationId)
      .then((data: any) => {
        if (cancelled) return;
        const list: SectionInfo[] = data?.sections ?? [];
        setSections(list);
        setSelected(
          list.filter((s) => s.status === 'available' && s.auto_generate).map((s) => s.section),
        );
      })
      .catch(() => {
        if (!cancelled) setSections([]);
      });
    return () => {
      cancelled = true;
    };
  }, [calculationId]);

  const setField = (key: string, value: string) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  // Compare against what the record holds, so an untouched form does not offer a
  // save that would do nothing. A cleared field counts as a change, because
  // clearing is how a mistyped value is removed.
  const dirty = useMemo(() => {
    if (!record) return false;
    return ALL_KEYS.some((key) => (draft[key] ?? '') !== textOf(record, key));
  }, [draft, record]);

  const handleSave = async () => {
    setSaving(true);
    try {
      // Send every field, including the blanks, so clearing is expressible.
      const payload: Record<string, string> = {};
      for (const key of ALL_KEYS) payload[key] = draft[key] ?? '';
      const res = await forestMetadataApi.save(calculationId, payload);
      // Display what was actually stored, not what was typed: the backend
      // normalises blank to NULL and may reject or adjust a value.
      await load();
      const text =
        i18n.language === 'ne'
          ? (res?.message_np ?? res?.message)
          : (res?.message ?? res?.message_np);
      message.success(text || t('forestMetadata.saved'));
    } catch (err: any) {
      // The server's own reason, not a blanket failure. It rejects a save with
      // nothing in it, and it knows the fiscal-year rules the form does not --
      // "Could not save the forest details" would hide all of that.
      const detail = readDetail(err?.response?.data?.detail ?? err?.response?.data ?? err);
      message.error(detail || t('forestMetadata.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const pollRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  /**
   * Cleared on unmount, which is a second thing the interval needs and not the
   * same as it: `stopPolling` can only cancel an interval that already exists,
   * but the POST is still in flight when the pane goes away. That request
   * resolves into the dead component and would start the interval *after* the
   * cleanup has run, leaving it to poll forever with nothing left to poll for.
   */
  const aliveRef = React.useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      stopPolling();
    };
  }, [stopPolling]);

  const handleGenerate = async () => {
    if (selected.length === 0) {
      failWith('reports.tab.selectAtLeastOne');
      return;
    }
    setGenerating(true);
    setProgress(0);
    setCompletedCount(0);
    setReportError(null);
    setReportErrorRaw(null);
    // Fixed now rather than read inside the poll, so editing the tick boxes
    // mid-generation cannot change the denominator underneath the progress text.
    const total = selected.length;
    setTotalCount(total);
    try {
      // No metadata argument: the server reads the record. A record that has
      // never been saved still produces a document, seeded from the analysis.
      const result = await reportApi.generateReport(calculationId, selected, includeImages);
      if (!aliveRef.current) return;
      setJobId(result.job_id);
      stopPolling();

      pollRef.current = setInterval(async () => {
        try {
          const status = await reportApi.getReportStatus(result.job_id);
          setProgress(status.progress ?? 0);
          setCompletedCount(status.sections_completed?.length ?? 0);
          if (status.status === 'completed') {
            stopPolling();
            setGenerating(false);
            message.success(t('reports.tab.msgGenerated'));
          } else if (status.status === 'failed') {
            stopPolling();
            setGenerating(false);
            failWith('reports.tab.generationFailed', status.error || null);
          }
        } catch {
          stopPolling();
          setGenerating(false);
          failWith('reports.tab.startFailed');
        }
      }, 2000);
    } catch {
      setGenerating(false);
      failWith('reports.tab.startFailed');
    }
  };

  const handleDownload = async () => {
    if (!jobId) return;
    try {
      await reportApi.downloadReport(jobId);
    } catch {
      failWith('reports.tab.downloadFailed');
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex justify-center" data-testid="forest-metadata-loading">
        <Spin />
      </div>
    );
  }

  if (loadFailed) {
    return (
      <div className="p-4" data-testid="forest-metadata-error">
        <Alert
          type="error"
          message={t('forestMetadata.loadFailed')}
          showIcon
          action={<Button onClick={load}>{t('common.retry')}</Button>}
        />
      </div>
    );
  }

  const saved = record?.persisted === true;
  // The whole form is mandatory (owner, 2026-10-11): an empty field is shown red, and the step stays red until every field is saved.
  const emptyFields = FOREST_METADATA_FIELDS.filter((key) => !(draft[key] ?? '').trim());
  const updated = record?.updated_at
    ? new Date(record.updated_at).toLocaleString(i18n.language === 'ne' ? 'ne-NP' : 'en-GB')
    : null;

  return (
    <div className="p-4 space-y-4 bg-gray-50 min-h-full" data-testid="forest-metadata-panel">
      {/* ---- the record ------------------------------------------------- */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-lg font-semibold text-gray-800">{t('forestMetadata.title')}</h3>
          {saved ? (
            <Tag color="green" data-testid="forest-metadata-saved">
              {t('forestMetadata.savedBadge')}
            </Tag>
          ) : (
            <Tag color="orange" data-testid="forest-metadata-unsaved">
              {t('forestMetadata.unsavedBadge')}
            </Tag>
          )}
        </div>
        <p className="text-sm text-gray-600 mb-4">
          {saved ? t('forestMetadata.savedHint') : t('forestMetadata.unsavedHint')}
        </p>
        {updated && (
          <p className="text-xs text-gray-500 mb-3" data-testid="forest-metadata-updated">
            {t('forestMetadata.lastUpdated', { when: updated })}
          </p>
        )}

        {emptyFields.length > 0 && (
          <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2" data-testid="fm-missing">
            {t('forestMetadata.missingCount', { count: emptyFields.length, total: FOREST_METADATA_FIELDS.length })}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {FOREST_METADATA_FIELDS.map((key) => {
            const labelKey = FIELD_LABELS[key] ?? EXTRA_LABELS[key];
            const empty = emptyFields.includes(key);
            const isLocation = (LOCATION_KEYS as readonly string[]).includes(key);
            return (
              <div key={key} className={key === 'cf_national_code' ? 'md:col-span-2' : ''}>
                <label className={`block text-xs font-medium mb-1 ${empty ? 'text-red-700' : 'text-gray-600'}`} htmlFor={`fm-${key}`}>
                  {t(labelKey)}
                  <span className="ml-0.5 text-red-600" aria-hidden="true">*</span>
                  {!saved && isLocation && (
                    <span className="ml-1 text-gray-400">({t('reports.tab.autoFilledShort')})</span>
                  )}
                </label>
                <input
                  id={`fm-${key}`}
                  data-testid={`fm-${key}`}
                  className={`w-full border rounded px-2 py-1.5 text-sm ${empty ? 'border-red-500 bg-red-50' : 'border-gray-300'}`}
                  aria-invalid={empty || undefined}
                  aria-required="true"
                  value={draft[key] ?? ''}
                  onChange={(e) => setField(key, e.target.value)}
                />
                {key === 'cf_national_code' && (
                  <>
                    <NationalCodeStatus value={draft[key] ?? ''} />
                    <NationalCodeBuilder
                      value={draft[key] ?? ''}
                      onUse={(code) => setField(key, code)}
                      calculationId={calculationId}
                      hints={{
                        province: draft.province ?? '',
                        palika: draft.palika ?? '',
                        district: draft.district ?? '',
                        serial: '',
                      }}
                    />
                  </>
                )}
              </div>
            );
          })}
        </div>

        {/* ---- optional plan details of the forest: every plan reads them; the plan's own form wins when filled ---- */}
        <div className="mt-6 border-t pt-4" data-testid="fm-optional">
          <h4 className="text-sm font-semibold text-gray-800">{t('forestMetadata.optional.title')}</h4>
          <p className="text-xs text-gray-500 mb-3">{t('forestMetadata.optional.hint')}</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {FOREST_METADATA_OPTIONAL_FIELDS.map((key) => (
              <div key={key} className={MULTILINE_OPTIONAL.has(key) ? 'md:col-span-2' : ''}>
                <label className="block text-xs font-medium mb-1 text-gray-600" htmlFor={`fm-${key}`}>
                  {t(`forestMetadata.optional.${key}`)}
                </label>
                {MULTILINE_OPTIONAL.has(key) ? (
                  <textarea
                    id={`fm-${key}`}
                    data-testid={`fm-${key}`}
                    rows={3}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                    value={draft[key] ?? ''}
                    onChange={(e) => setField(key, e.target.value)}
                  />
                ) : DATE_OPTIONAL.has(key) ? (
                  <div data-testid={`fm-${key}`}>
                    <NepaliDatePicker value={draft[key] ?? ''} onChange={(v) => setField(key, v)} />
                  </div>
                ) : (
                  <input
                    id={`fm-${key}`}
                    data-testid={`fm-${key}`}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                    value={draft[key] ?? ''}
                    onChange={(e) => setField(key, e.target.value)}
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <Button
            type="primary"
            onClick={handleSave}
            loading={saving}
            disabled={!dirty}
            data-testid="fm-save"
          >
            {t('forestMetadata.save')}
          </Button>
          <Button onClick={load} disabled={saving}>
            {t('common.refresh')}
          </Button>
        </div>
      </div>

      {/* ---- what the record is for -------------------------------------- */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">{t('reports.tab.selectSections')}</h3>
        <p className="text-sm text-gray-600 mb-3">{t('forestMetadata.reportHint')}</p>

        {sections.length === 0 ? (
          <p className="text-sm text-gray-500">{t('reports.tab.sectionsFailed')}</p>
        ) : (
          <div className="space-y-1" data-testid="fm-sections">
            {sections.map((s) => (
              <label key={s.section} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={selected.includes(s.section)}
                  disabled={s.status !== 'available'}
                  onChange={(e) =>
                    setSelected((prev) =>
                      e.target.checked
                        ? [...prev, s.section]
                        : prev.filter((x) => x !== s.section),
                    )
                  }
                />
                <span className={s.status === 'available' ? '' : 'text-gray-400'}>
                  {i18n.language === 'ne' ? s.title_ne : s.title_en}
                </span>
                {s.status !== 'available' && (
                  <span className="text-xs text-gray-400">
                    ({s.status === 'missing_data'
                      ? t('reports.tab.missingData')
                      : t('reports.tab.manualInput')})
                  </span>
                )}
                <ReportSectionFixLinks calculationId={calculationId} status={s.status} missing={s.missing} titleNe={s.title_ne} />
              </label>
            ))}
          </div>
        )}

        <div className="mt-3">
          <Checkbox
            checked={includeImages}
            onChange={(e) => setIncludeImages(e.target.checked)}
            data-testid="fm-include-images"
          >
            {t('reports.tab.includeImages')}
          </Checkbox>
        </div>

        {reportErrorText && (
          <Alert
            type="error"
            message={reportErrorText}
            showIcon
            className="mt-3"
            closable
            onClose={() => {
              setReportError(null);
              setReportErrorRaw(null);
            }}
          />
        )}

        <div className="mt-4 flex items-center gap-2">
          <Button
            type="primary"
            onClick={handleGenerate}
            loading={generating}
            disabled={sections.length === 0}
            data-testid="fm-generate"
          >
            {t('reports.tab.generateSelected')}
          </Button>
          <Button onClick={handleDownload} disabled={!jobId} data-testid="fm-download">
            {t('reports.tab.downloadDocx')}
          </Button>
        </div>

        {generating && (
          <div className="mt-3" data-testid="fm-progress">
            <Progress percent={Math.round(progress ?? 0)} size="small" />
            <p className="text-xs text-gray-600">
              {/* Counted from the job, not from the checkbox list: the two can
                  disagree while a report is running. */}
              {t('reports.tab.msgProgress', {
                done: formatNumber(completedCount),
                total: formatNumber(totalCount),
              })}
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default ForestMetadataPanel;
