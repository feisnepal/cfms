import { App } from 'antd';
import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  getUnitSizeReview,
  mergeFeatures,
  UnitSizeCandidate,
  UnitSizeSummary,
} from '../../services/api';
import MergeUnitConfirm from './MergeUnitConfirm';
import UnitSizeTable from './UnitSizeTable';

interface UnitSizeReviewPanelProps {
  calculationId: string;
  /** The field rule of thumb, in percent. Omitted means the server default. */
  reviewPct?: number;
  onLinkToSampling?: () => void;
}

/**
 * P8 tier 1 - review unit sizes *before* a sampling design exists, and act on a
 * proposal.
 *
 * The merge reuses the existing `geometry/merge-features` endpoint rather than a
 * second merge path, so `structure_write` does the invalidation (SFM, render caches,
 * stale flags, tree/plot unit reassignment) exactly once, in one place.
 *
 * `layer_type` is not chosen here. The server derives it from each unit's own row,
 * so a sub-compartment cannot be merged into a block - the wrong merge is
 * unexpressible rather than merely discouraged.
 */
export const UnitSizeReviewPanel: React.FC<UnitSizeReviewPanelProps> = ({
  calculationId,
  reviewPct,
  onLinkToSampling,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [candidates, setCandidates] = useState<UnitSizeCandidate[]>([]);
  const [summary, setSummary] = useState<UnitSizeSummary | null>(null);
  const [mmuHa, setMmuHa] = useState<number | undefined>(undefined);
  const [resolvedPct, setResolvedPct] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<UnitSizeCandidate | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(async () => {
    if (!calculationId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getUnitSizeReview(calculationId, reviewPct);
      setCandidates(data.candidates || []);
      setSummary(data.summary || null);
      setMmuHa(data.mmu_ha);
      setResolvedPct(data.review_pct);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [calculationId, reviewPct]);

  useEffect(() => {
    void load();
  }, [load]);

  const doMerge = useCallback(async () => {
    if (!pending || !pending.id || !pending.neighbour_id || !pending.layer_type) {
      message.error(t('sampling.unitReview.mergeFailed'));
      setPending(null);
      return;
    }
    setConfirming(true);
    try {
      await mergeFeatures(calculationId, pending.layer_type, [pending.id, pending.neighbour_id]);
      message.success(t('sampling.unitReview.mergeDone', { name: pending.block_name }));
      setPending(null);
      // The unit is gone now, so the review must be re-read rather than patched.
      await load();
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t('sampling.unitReview.mergeFailed')
      );
    } finally {
      setConfirming(false);
    }
  }, [pending, calculationId, message, t, load]);

  return (
    <div>
      <UnitSizeTable
        candidates={candidates}
        summary={summary || undefined}
        mmuHa={mmuHa}
        reviewPct={resolvedPct}
        loading={loading}
        error={error}
        onLinkToSampling={onLinkToSampling}
        onMergeRequest={setPending}
      />
      <MergeUnitConfirm
        candidate={pending}
        open={pending !== null}
        confirming={confirming}
        onConfirm={() => void doMerge()}
        onCancel={() => setPending(null)}
      />
    </div>
  );
};

export default UnitSizeReviewPanel;
