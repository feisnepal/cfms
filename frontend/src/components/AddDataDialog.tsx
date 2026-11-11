/**
 * "Add data" — the one front door for every kind of forest data.
 *
 * UNIFIED_UPLOAD_PLAN.md §4.2–4.6, UPLOAD_EXPERIENCE_PLAN.md UP-4. Drop the
 * filled Forest Data Workbook, or any loose data files, or several at once; the
 * dialog classifies each by name and by content against the canonical schema
 * (`GET /uploads/schema`), enforces the boundary-first rule, and shows a review
 * list.
 *
 * Pressing "Add data" runs the same per-file pipeline each dedicated screen uses
 * (UP-4.1/UP-4.3) — the per-file purpose dialog opens on top, one file at a
 * time — and then shows the SAME grouped {@link UploadReport} the tabs show, right
 * here in the dialog, before it closes.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Modal, Select, Spin, Tag, Upload, message } from 'antd';
import type { UploadFile } from 'antd/es/upload/interface';
import { useT } from '../i18n/hooks';
import { formatDecimal } from '../i18n/numberFormat';
import { uploadApi, type ForestOverlap, type CoordinateSystemInfo } from '../services/api';
import {
  classifyFile,
  fileExt,
  type Classification,
  type UploadPurpose,
  type UploadSchema,
} from '../lib/classifyUpload';
import { WORKSPACE_IMPORTABLE_PURPOSES } from '../lib/uploadPurposeMap';
import BulkImportRunner from './BulkImportRunner';
import DownloadTemplateButton from './DownloadTemplateButton';
import { UploadReport } from './UploadReport';
import { problemRowsFromFindings, type AcceptedCorrection, type UploadFinding } from '../lib/uploadFindings';
import i18n from '../i18n';

const SKIP = '__skip__';

export interface ResolvedUpload {
  file: File;
  purposeId: string;
  /** The coordinate system the user chose for a table with coordinates (degrees / UTM zone); undefined = the file as it is. */
  crsEpsg?: number | null;
  /** Proposed replacements the user accepted for this file (set when it is imported again from the report). */
  corrections?: AcceptedCorrection[];
  /** Renumber the sample plots 1..N in order (set when it is imported again from the report). */
  renumber?: boolean;
}

interface AddDataDialogProps {
  open: boolean;
  /** The forest this upload belongs to. */
  calculationId: string;
  /** Whether the forest already has a boundary — drives the boundary-first gate. */
  hasBoundary: boolean;
  onClose: () => void;
  /**
   * Canonical purpose ids the caller can actually import. A file resolved to a
   * purpose outside this set cannot be submitted — the user must re-pick or skip
   * it. Defaults to what the map workspace supports.
   */
  importablePurposeIds?: readonly string[];
  /** Files already dropped on the workspace before the dialog opened: they are added as if dropped in the dialog. */
  initialFiles?: File[];
  /** Called once the dialog has taken `initialFiles`, so the caller can forget them. */
  onInitialFilesTaken?: () => void;
}

interface Row {
  key: string;
  file: File;
  classification: Classification | null; // null while still classifying
  /** The purpose the user has chosen — starts from the classification. */
  purposeId: string | typeof SKIP | null;
  /** What the file's *contents* look like (UP-4.2), when the server could read them. */
  serverBest?: string | null;
  /** Where the file's features sit against this forest (read from the file's own coordinates). */
  overlap?: ForestOverlap;
  /** The content read has finished (answered or failed): only then is an unrecognised file safe to guess about. */
  contentRead?: boolean;
  /** For a table with coordinates: what the numbers look like, and the system the user chose (null = must still be chosen). */
  coordinates?: CoordinateSystemInfo;
  crsEpsg?: number | null;
}

/** A file whose own declaration cannot be trusted as it stands: the numbers contradict it, its rows disagree, or it names a system we cannot read yet. */
function declarationNeedsChoice(info: CoordinateSystemInfo): boolean {
  const d = info.declared;
  return info.declared_ok === false || !!d?.mixed || !!d?.unsupported?.length;
}

/** The tables whose import takes a coordinate system: a field inventory, and a stem-mapping (tree) table. A GIS file carries its own. */
function takesCoordinateSystem(r: Row): boolean {
  return r.purposeId === 'field_inventory' || (['trees', 'sample_plots'].includes(r.purposeId ?? '') && ['csv', 'xlsx', 'xls'].includes(fileExt(r.file.name)));
}

/** A table whose UTM coordinates can be read in more than one way (or in none we offer) cannot be imported until the user chooses. */
function needsCoordinateChoice(r: Row): boolean {
  return takesCoordinateSystem(r) && !!r.coordinates?.has_coordinates && r.crsEpsg === null && (r.coordinates.candidates?.length ?? 0) > 0;
}

/** A file that belongs to some other forest: none of its features touch this one. The boundary itself and the user group are exempt (a
 *  user group may sit beside the forest; its own distance check warns). */
function isOutsideForest(r: Row, hasBoundary: boolean): boolean {
  if (!hasBoundary || r.overlap?.status !== 'outside') return false;
  return !!r.purposeId && r.purposeId !== SKIP && r.purposeId !== 'forest_boundary' && r.purposeId !== 'user_group_boundary';
}

export default function AddDataDialog({
  open,
  calculationId,
  hasBoundary,
  onClose,
  importablePurposeIds,
  initialFiles,
  onInitialFilesTaken,
}: AddDataDialogProps) {
  const t = useT();
  /** Which screen the dialog is showing: pick files → run the imports → report. */
  const [phase, setPhase] = useState<'select' | 'running' | 'done'>('select');
  const [submitted, setSubmitted] = useState<ResolvedUpload[]>([]);
  const [report, setReport] = useState<UploadFinding[]>([]);
  const importable = useMemo(
    () =>
      importablePurposeIds
        ? new Set(importablePurposeIds)
        : WORKSPACE_IMPORTABLE_PURPOSES,
    [importablePurposeIds],
  );
  const isImportable = useCallback(
    (id: string | null | undefined) => !!id && importable.has(id),
    [importable],
  );
  const [schema, setSchema] = useState<UploadSchema | null>(null);
  const [schemaError, setSchemaError] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [downloading, setDownloading] = useState<'xlsx' | 'gpkg' | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setSchemaError(false);
    uploadApi
      .getSchema()
      .then((s) => {
        if (!cancelled) setSchema(s);
      })
      .catch(() => {
        if (!cancelled) setSchemaError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      setRows([]);
      setPhase('select');
      setSubmitted([]);
      setReport([]);
    }
  }, [open]);

  const purposes: UploadPurpose[] = useMemo(
    () => (schema ? [...schema.purposes].sort((a, b) => a.order - b.order) : []),
    [schema],
  );

  const purposeLabel = useCallback(
    (id: string | null | undefined) =>
      purposes.find((p) => p.id === id)?.label_en ?? id ?? '',
    [purposes],
  );

  const addFile = useCallback(
    (file: File) => {
      const key = `${file.name}:${file.size}:${file.lastModified}`;
      setRows((prev) => {
        if (prev.some((r) => r.key === key)) return prev;
        return [...prev, { key, file, classification: null, purposeId: null }];
      });
      if (!schema) return;
      classifyFile(file, schema)
        .then((classification) => {
          setRows((prev) =>
            prev.map((r) =>
              r.key === key
                ? { ...r, classification, purposeId: classification.purposeId }
                : r,
            ),
          );
        })
        .catch(() => {
          setRows((prev) =>
            prev.map((r) =>
              r.key === key
                ? { ...r, classification: { purposeId: null, via: 'none' } }
                : r,
            ),
          );
        });
      // C2: for a table, which coordinate system are the numbers in? Pre-select the answer; ask only when it is unsure.
      if (['csv', 'xlsx', 'xls'].includes(fileExt(file.name))) {
        uploadApi
          .coordinateSystem?.(file, hasBoundary ? calculationId : undefined)
          .then((info) => {
            if (!info?.has_coordinates) return;
            setRows((prev) =>
              prev.map((r) => (r.key === key ? { ...r, coordinates: info, crsEpsg: declarationNeedsChoice(info) ? null : info.suggested_epsg ?? null } : r)),
            );
          })
          .catch(() => undefined); // the question is an aid: the import still reports a bad file
      }
      // UP-4.2: identify the file by what is *in* it, not just its name. The
      // content read fills a blank the name left, and (kept on the row) powers
      // the "this looks like X" hint when the user picks something else.
      uploadApi
        .classifyUpload(file, undefined, hasBoundary ? calculationId : undefined)
        .then((c) => {
          if (!c?.best) {
            setRows((prev) => prev.map((r) => (r.key === key ? { ...r, contentRead: true, overlap: c?.forest_overlap } : r)));
            return;
          }
          setRows((prev) =>
            prev.map((r) => {
              if (r.key !== key) return r;
              const recognized = r.purposeId && r.purposeId !== SKIP;
              return {
                ...r,
                serverBest: c.best,
                contentRead: true,
                overlap: c.forest_overlap,
                purposeId: recognized ? r.purposeId : c.best,
                classification: recognized
                  ? r.classification
                  : { purposeId: c.best, via: 'content' },
              };
            }),
          );
        })
        .catch(() => {
          setRows((prev) => prev.map((r) => (r.key === key ? { ...r, contentRead: true } : r)));
        });
    },
    [schema, hasBoundary, calculationId],
  );

  // The forest has no boundary yet, so a spatial file nothing else claims is most likely it: say so and preselect it (the user can
  // change it) instead of refusing with "this forest has no boundary". Only when exactly one file could be the boundary.
  useEffect(() => {
    if (hasBoundary || rows.length === 0) return;
    if (rows.some((r) => r.purposeId === 'forest_boundary')) return;
    // Any map format (point, line, polygon or mixed - points and lines are turned into a polygon on import). A CSV / Excel sheet is NOT
    // guessed: coordinates may belong to trees, plots or households, so the server decides from the columns (a sheet of nothing but
    // coordinates is identified as boundary points by content).
    const spatial = new Set(['geojson', 'json', 'kml', 'kmz', 'gpx', 'zip', 'gpkg', 'shp']);
    const candidates = rows.filter(
      (r) => r.purposeId === null && r.classification !== null && r.contentRead && spatial.has(fileExt(r.file.name)),
    );
    if (candidates.length !== 1) return;
    const key = candidates[0].key;
    setRows((prev) =>
      prev.map((r) =>
        r.key === key ? { ...r, purposeId: 'forest_boundary', classification: { purposeId: 'forest_boundary', via: 'guess' } } : r,
      ),
    );
  }, [rows, hasBoundary]);

  // Files dropped on the workspace (not in the dialog) arrive here once the schema is loaded, so they are classified like any other drop.
  useEffect(() => {
    if (!open || !schema || !initialFiles?.length) return;
    initialFiles.forEach((f) => addFile(f));
    onInitialFilesTaken?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, schema, initialFiles]);

  const removeRow = useCallback((key: string) => {
    setRows((prev) => prev.filter((r) => r.key !== key));
  }, []);

  const setRowPurpose = useCallback((key: string, value: string) => {
    setRows((prev) =>
      prev.map((r) => (r.key === key ? { ...r, purposeId: value } : r)),
    );
  }, []);

  const setRowCrs = useCallback((key: string, epsg: number) => {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, crsEpsg: epsg } : r)));
  }, []);

  const resolved: ResolvedUpload[] = useMemo(
    () =>
      rows
        .filter((r) => r.purposeId && r.purposeId !== SKIP && isImportable(r.purposeId))
        .map((r) => ({ file: r.file, purposeId: r.purposeId as string, crsEpsg: takesCoordinateSystem(r) ? r.crsEpsg : undefined })),
    [rows, isImportable],
  );

  // A row blocks submit while it has no purpose, or a purpose this caller cannot
  // import here. The workspace maps every schema purpose, so the default set
  // admits all of them; callers can narrow it via `importablePurposeIds`.
  const anyBlocked = rows.some(
    (r) =>
      r.purposeId === null ||
      isOutsideForest(r, hasBoundary) ||
      needsCoordinateChoice(r) ||
      (r.purposeId !== SKIP && !isImportable(r.purposeId)),
  );
  const boundaryProvided =
    hasBoundary || resolved.some((r) => r.purposeId === 'forest_boundary');
  const boundaryGateBlocks = rows.length > 0 && !boundaryProvided;
  const canSubmit =
    resolved.length > 0 && !anyBlocked && !boundaryGateBlocks;

  const handleDownload = async (format: 'xlsx' | 'gpkg') => {
    setDownloading(format);
    try {
      await uploadApi.downloadWorkbook(format);
    } catch {
      message.error(t('addData.downloadFailed'));
    } finally {
      setDownloading(null);
    }
  };

  const handleSubmit = () => {
    if (!canSubmit) return;
    setSubmitted(resolved);
    setReport([]);
    setPhase('running');
  };

  /** The user accepts the proposed replacements for a refused file: import that file again with them (the others are already in). */
  const handleApplyCorrections = (finding: UploadFinding) => {
    const proposals = (finding.where.proposals ?? []).filter((p) => p.new != null);
    const item = submitted.find((s) => s.file.name === finding.where.file) ?? (submitted.length === 1 ? submitted[0] : undefined);
    if (!item || proposals.length === 0) return;
    setSubmitted([{ ...item, corrections: proposals.map((p) => ({ row: p.row, column: p.column, value: p.new as number })) }]);
    setReport([]);
    setPhase('running');
  };

  /** The user lets us renumber the sample plots 1..N in order: import that file again. */
  const handleRenumber = (finding: UploadFinding) => {
    const item = submitted.find((s) => s.file.name === finding.where.file) ?? (submitted.length === 1 ? submitted[0] : undefined);
    if (!item) return;
    setSubmitted([{ ...item, renumber: true }]);
    setReport([]);
    setPhase('running');
  };

  /** Every file has been handled: show what needs fixing, in this dialog. */
  const handleRunDone = (findings: UploadFinding[]) => {
    setReport(findings);
    setPhase('done');
  };

  const purposeOptions = useMemo(
    () => [
      ...purposes.map((p) => ({
        value: p.id,
        label: isImportable(p.id)
          ? p.label_en
          : `${p.label_en} ${t('addData.ownTabSuffix')}`,
        disabled: !isImportable(p.id),
      })),
      { value: SKIP, label: t('addData.skip') },
    ],
    [purposes, t, isImportable],
  );

  const footer =
    phase === 'running' ? null : phase === 'done' ? (
      <div className="flex justify-end">
        <Button type="primary" onClick={onClose}>{t('addData.done')}</Button>
      </div>
    ) : (
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-gray-500 flex items-center gap-2 flex-wrap">
          <DownloadTemplateButton />
          {t('addData.downloadWorkbook')}:{' '}
          <Button type="link" size="small" loading={downloading === 'xlsx'} onClick={() => handleDownload('xlsx')}>
            {t('addData.downloadExcel')}
          </Button>
          <Button type="link" size="small" loading={downloading === 'gpkg'} onClick={() => handleDownload('gpkg')}>
            {t('addData.downloadGpkg')}
          </Button>
        </span>
        <span className="flex gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="primary" disabled={!canSubmit} onClick={handleSubmit}>
            {resolved.length > 0 ? t('addData.addCount', { count: resolved.length }) : t('addData.add')}
          </Button>
        </span>
      </div>
    );

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t('addData.title')}
      width={720}
      centered
      destroyOnHidden
      mask={{ closable: phase !== 'running' }}
      keyboard={phase !== 'running'}
      closable={phase !== 'running'}
      footer={footer}
    >
      {phase === 'running' ? (
        <div className="py-10 text-center space-y-2">
          <Spin />
          <p className="text-sm text-gray-600">{t('addData.running')}</p>
          <p className="text-xs text-gray-500">{t('addData.runningHint')}</p>
        </div>
      ) : phase === 'done' ? (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">{t('addData.reportIntro')}</p>
          {report.length > 0 ? (
            <UploadReport
              findings={report}
              problemRows={problemRowsFromFindings(report, i18n.language === 'ne' ? 'ne' : 'en')}
              fileName="add_data_problem_rows"
              onApplyCorrections={handleApplyCorrections}
              onRenumber={handleRenumber}
            />
          ) : (
            <Alert type="success" showIcon message={t('addData.reportClean')} />
          )}
        </div>
      ) : schemaError ? (
        <Alert type="error" showIcon message={t('addData.schemaError')} />
      ) : !schema ? (
        <div className="py-8 text-center">
          <Spin />
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">{t('addData.subtitle')}</p>

          <Upload.Dragger
            multiple
            showUploadList={false}
            fileList={[] as UploadFile[]}
            beforeUpload={(file) => {
              addFile(file as unknown as File);
              return false;
            }}
          >
            <p className="text-sm font-medium text-gray-700">
              {t('addData.dropzone')}
            </p>
            <p className="text-xs text-gray-500">{t('addData.dropzoneHint')}</p>
          </Upload.Dragger>

          {boundaryGateBlocks && (
            <Alert
              type="error"
              showIcon
              message={t('addData.boundaryFirstTitle')}
              description={t('addData.boundaryFirst')}
            />
          )}

          {rows.length > 0 && (
            <div className="border border-gray-200 rounded-md divide-y divide-gray-100">
              {rows.map((r) => (
                <RowItem
                  key={r.key}
                  row={r}
                  purposeOptions={purposeOptions}
                  purposeLabel={purposeLabel}
                  blocked={
                    r.purposeId !== null &&
                    r.purposeId !== SKIP &&
                    !isImportable(r.purposeId)
                  }
                  onPurpose={(v) => setRowPurpose(r.key, v)}
                  onCrs={(v) => setRowCrs(r.key, v)}
                  onRemove={() => removeRow(r.key)}
                  t={t}
                />
              ))}
            </div>
          )}
        </div>
      )}
      {phase === 'running' && calculationId && (
        <BulkImportRunner
          items={submitted}
          calculationId={calculationId}
          hasBoundary={hasBoundary}
          onDone={handleRunDone}
        />
      )}
    </Modal>
  );
}

interface RowItemProps {
  row: Row;
  purposeOptions: { value: string; label: string; disabled?: boolean }[];
  purposeLabel: (id: string | null | undefined) => string;
  /** The row's purpose is real but the caller cannot import it here. */
  blocked: boolean;
  onPurpose: (value: string) => void;
  onCrs: (epsg: number) => void;
  onRemove: () => void;
  t: ReturnType<typeof useT>;
}

function RowItem({
  row,
  purposeOptions,
  purposeLabel,
  blocked,
  onPurpose,
  onCrs,
  onRemove,
  t,
}: RowItemProps) {
  const c = row.classification;
  const sizeKb = formatDecimal(row.file.size / 1024, 1);

  let hint: React.ReactNode = null;
  if (!c) {
    hint = <Tag>{t('addData.classifying')}</Tag>;
  } else if (c.via === 'name' && c.purposeId) {
    hint = <Tag color="green">{t('addData.matchedByName')}</Tag>;
  } else if (c.via === 'content' && c.purposeId) {
    hint = <Tag color="green">{t('addData.matchedByContent')}</Tag>;
  } else if (c.via === 'guess' && c.purposeId) {
    hint = <Tag color="gold">{t('addData.matchedByGuess')}</Tag>;
  } else if (c.via === 'sheet' && c.sheets) {
    hint = (
      <Tag color="blue">
        {t('addData.workbookSheets', { count: c.sheets.length })}
      </Tag>
    );
  } else if (c.via === 'zip-entry' && c.sheets) {
    hint = (
      <Tag color="blue">
        {t('addData.bundleLayers', { count: c.sheets.length })}
      </Tag>
    );
  } else {
    hint = <Tag color="orange">{t('addData.notRecognized')}</Tag>;
  }

  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2">
      <span className="font-mono text-xs text-gray-800 truncate max-w-[220px]" title={row.file.name}>
        {row.file.name}
      </span>
      <span className="text-xs text-gray-400">
        {t('addData.fileSize', { size: sizeKb })}
      </span>
      {hint}
      <span className="ml-auto flex items-center gap-2">
        <Select
          size="small"
          style={{ width: 190 }}
          value={row.purposeId ?? undefined}
          placeholder={t('addData.chooseType')}
          options={purposeOptions}
          onChange={onPurpose}
          status={row.purposeId === null || blocked ? 'warning' : undefined}
        />
        <Button size="small" type="text" onClick={onRemove}>
          {t('addData.remove')}
        </Button>
      </span>

      {blocked && (
        <p className="w-full text-xs text-amber-600 pl-1">
          {t('addData.ownTab', { type: purposeLabel(row.purposeId) })}
        </p>
      )}

      {takesCoordinateSystem(row) && row.coordinates?.has_coordinates && (
        <CoordinateSystemRow row={row} onCrs={onCrs} t={t} />
      )}

      {row.overlap?.status === 'outside' && row.purposeId && row.purposeId !== SKIP && row.purposeId !== 'forest_boundary' && row.purposeId !== 'user_group_boundary' && (
        <p className="w-full text-xs text-red-600 pl-1" data-testid="outside-forest">
          {row.overlap.distance_km != null
            ? t('addData.outsideForestNear', { count: row.overlap.features, km: row.overlap.distance_km })
            : t('addData.outsideForest', { count: row.overlap.features })}
        </p>
      )}
      {row.overlap?.status === 'partial' && (
        <p className="w-full text-xs text-amber-600 pl-1" data-testid="partly-outside-forest">
          {t('addData.partlyOutside', { outside: row.overlap.outside, total: row.overlap.features })}
        </p>
      )}

      {row.serverBest &&
        row.purposeId &&
        row.purposeId !== SKIP &&
        row.serverBest !== row.purposeId && (
          <p className="w-full text-xs text-amber-600 pl-1">
            {t('addData.looksLike', { type: purposeLabel(row.serverBest) })}{' '}
            <Button size="small" type="link" onClick={() => onPurpose(row.serverBest as string)}>
              {t('addData.useSuggested', { type: purposeLabel(row.serverBest) })}
            </Button>
          </p>
        )}

      {c?.sheets && c.sheets.length > 0 && (
        <ul className="w-full pl-4 mt-1 space-y-0.5">
          {c.sheets.map((s) => (
            <li key={s.name} className="text-xs text-gray-500">
              {s.name} →{' '}
              {s.purposeId ? (
                <span className="text-gray-700">{purposeLabel(s.purposeId)}</span>
              ) : (
                <span className="text-orange-500">{t('addData.chooseType')}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The coordinate-system question for a table with coordinates: pre-selected from the numbers, and a plain question when they do not decide. */
function CoordinateSystemRow({ row, onCrs, t }: { row: Row; onCrs: (epsg: number) => void; t: ReturnType<typeof useT> }) {
  const info = row.coordinates as CoordinateSystemInfo;
  const labels = info.labels ?? {};
  const options = [4326, 32644, 32645].map((epsg) => ({ value: epsg, label: labels[String(epsg)] ?? String(epsg) }));
  const rowList = (rows: number[]) => rows.slice(0, 8).join(', ') + (rows.length > 8 ? ' …' : '');
  const missing = info.missing_rows ?? [];
  const strays = info.strays ?? [];
  return (
    <div className="w-full pl-1 space-y-1" data-testid="coordinate-system">
      <div className="flex items-center gap-2 text-xs text-gray-700">
        <span>{t('addData.coord.label')}</span>
        <Select
          size="small"
          style={{ width: 190 }}
          value={row.crsEpsg ?? undefined}
          placeholder={t('addData.coord.choose')}
          options={options}
          onChange={onCrs}
          status={row.crsEpsg === null ? 'warning' : undefined}
        />
        {row.crsEpsg != null && info.declared_ok === true && info.declared_epsg === row.crsEpsg && <Tag color="green">{t('addData.coord.declared')}</Tag>}
        {row.crsEpsg != null && info.declared_ok !== true && info.suggested_epsg === row.crsEpsg && <Tag color="green">{t('addData.coord.detected')}</Tag>}
      </div>
      {info.declared_ok === false && info.declared_epsg != null && (
        <p className="text-xs text-amber-600" data-testid="declared-mismatch">
          {t('addData.coord.declaredMismatch', {
            declared: labels[String(info.declared_epsg)] ?? info.declared_epsg,
            fits: info.suggested_epsg != null ? labels[String(info.suggested_epsg)] ?? info.suggested_epsg : t('addData.coord.noSystem'),
          })}
        </p>
      )}
      {info.declared?.mixed && <p className="text-xs text-amber-600">{t('addData.coord.declaredMixed', { values: info.declared.values.join(', ') })}</p>}
      {!!info.declared?.unsupported?.length && <p className="text-xs text-amber-600">{t('addData.coord.declaredUnsupported', { code: info.declared.unsupported[0] })}</p>}
      {!!info.declared?.blank_rows?.length && (
        <p className="text-xs text-amber-600">{t('addData.coord.declaredBlank', { count: info.declared.blank_rows.length, rows: rowList(info.declared.blank_rows) })}</p>
      )}
      {info.ambiguous && row.crsEpsg === null && <p className="text-xs text-amber-600">{t('addData.coord.ambiguous')}</p>}
      {info.none_fit && row.crsEpsg === null && <p className="text-xs text-amber-600">{t('addData.coord.noneFit')}</p>}
      {info.dominant === 'swapped_utm' && <p className="text-xs text-amber-600">{t('addData.coord.swappedUtm')}</p>}
      {missing.length > 0 && <p className="text-xs text-amber-600">{t('addData.coord.missing', { count: missing.length, rows: rowList(missing) })}</p>}
      {strays.length > 0 && (
        <p className="text-xs text-amber-600">{t('addData.coord.strays', { count: strays.length, rows: rowList(strays.map(([r]) => r)) })}</p>
      )}
    </div>
  );
}
