/**
 * Runs a queue of (file → canonical purpose) pairs from {@link AddDataDialog}
 * through the existing per-file {@link ImportPurposeDialog}, one at a time.
 *
 * The canonical schema purpose ids are mapped to the workspace's legacy purpose
 * ids; a purpose with no mapping is reported and skipped. Tabular purposes
 * (households, field inventory, trees-with-a-spreadsheet) run the same pipeline
 * as their dedicated tab inside ImportPurposeDialog.
 *
 * UNIFIED_UPLOAD_PLAN.md §4.2 — Phase 1 wiring, ahead of the unified commit
 * pipeline.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { message } from 'antd';
import { useT } from '../i18n/hooks';
import { useWorkspaceStore } from '../store/workspaceStore';
import ImportPurposeDialog from './ImportPurposeDialog';
import type { ResolvedUpload } from './AddDataDialog';
import type { UploadFinding } from '../lib/uploadFindings';
import { CANON_TO_LEGACY_PURPOSE as CANON_TO_LEGACY } from '../lib/uploadPurposeMap';
import { emitDataImported } from '../lib/uploadEvents';

interface BulkImportRunnerProps {
  items: ResolvedUpload[];
  calculationId: string;
  /** Whether the forest already has a boundary (drives ImportPurposeDialog's
   *  restrictToGeometry for the first file on a boundary-less draft). */
  hasBoundary: boolean;
  /** Called once every file has been processed or the user aborts, with the
   *  findings the run produced (UP-4.3: the caller shows them in one report). */
  onDone: (findings: UploadFinding[]) => void;
}

export default function BulkImportRunner({
  items,
  calculationId,
  hasBoundary,
  onDone,
}: BulkImportRunnerProps) {
  const t = useT();
  const store = useWorkspaceStore();

  const { supported, unsupportedCount } = useMemo(() => {
    const list = items.filter((i) => CANON_TO_LEGACY[i.purposeId]);
    // Boundary first: on a boundary-less draft ImportPurposeDialog restricts the
    // first file to a geometry purpose, so it must be the boundary.
    list.sort(
      (a, b) =>
        (a.purposeId === 'forest_boundary' ? 0 : 1) -
        (b.purposeId === 'forest_boundary' ? 0 : 1),
    );
    return { supported: list, unsupportedCount: items.length - list.length };
  }, [items]);

  const [idx, setIdx] = useState(0);
  const done = idx >= supported.length;
  // Findings from every file, gathered so the caller can show one report.
  const findingsRef = useRef<UploadFinding[]>([]);
  const collectFindings = (list: UploadFinding[]) => {
    if (list?.length) findingsRef.current = [...findingsRef.current, ...list];
  };

  useEffect(() => {
    if (unsupportedCount > 0) {
      message.info(t('addData.someOnTabs', { count: unsupportedCount }));
    }
    if (supported.length > 0) {
      message.info(t('addData.importingCount', { count: supported.length }));
    }
    // once, on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (done) {
      void store.refreshAll();
      emitDataImported(supported.map((i) => i.purposeId)); // tabs holding imported data (field inventory ...) and the readiness reload
      onDone(findingsRef.current);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done]);

  if (done) return null;

  const current = supported[idx];
  const advance = () => setIdx((i) => i + 1);

  return (
    <>
      {createPortal(
        <div
          className="fixed top-2 left-1/2 -translate-x-1/2 z-[10000] bg-gray-900 text-white text-xs px-3 py-1.5 rounded-full shadow-lg"
          role="status"
          aria-live="polite"
        >
          {t('addData.progress', { current: idx + 1, total: supported.length })} ·{' '}
          <span className="font-mono">{current.file.name}</span>
        </div>,
        document.body,
      )}
      <ImportPurposeDialog
        key={`${current.file.name}:${idx}`}
        file={current.file}
        calculationId={calculationId}
        fixedPurpose={CANON_TO_LEGACY[current.purposeId]}
        restrictToGeometry={!hasBoundary && idx === 0}
        onBoundarySaved={() => store.bumpGeometryVersion()}
        onFindings={collectFindings}
        tabularCrsEpsg={current.crsEpsg}
        tabularCorrections={current.corrections}
        tabularRenumber={current.renumber}
        onComplete={advance}
        onCancel={advance}
      />
    </>
  );
}
