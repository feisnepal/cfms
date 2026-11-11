import React, { useState } from 'react';
import { Tooltip } from 'antd';
import { WarningOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';

interface StructureStale {
  analysis?: boolean;
  sampling?: boolean;
  field_inventory?: boolean;
  since?: string;
  change?: string | null;
}

interface Props {
  /** `calculation.result_data`, as fetched — the banner reads its own key from it. */
  resultData: Record<string, unknown> | null | undefined;
  /** Stable id for the calculation, so a dismissal is remembered per forest. */
  calculationId?: string;
}

/**
 * FS-1b.7 (forest-structure work, part 1 of the consequence hook, D11): a structural edit
 * (divide / cut / merge / promote-to-unit / bulk geometry save, ...) marks
 * `result_data['structure_stale']` via `forest_units.write.on_structure_changed`. This says so.
 *
 * **When it shows (owner 2026-09-29, "why do I always see this ribbon"):** only for the
 * domains the forest ACTUALLY holds data for. The backend writes the flag for the
 * intersection of `STALE_DOMAINS` with what exists — a sampling design, a field-inventory
 * upload, a completed analysis — so a forest with none of them (the whole first session)
 * gets no flag at all, and one with only a field inventory is not told to re-run sampling.
 * Each domain is also un-marked the moment it is actually recomputed
 * (`clear_stale_domains`), so a re-run you have already done stops being reported.
 *
 * **Why it is small:** it used to be a full-width `Alert` with a title and a two-line
 * body, sitting above the whole page. It is now one line that names the affected
 * domains, with the explanation in a tooltip — the warning matters, the paragraph does
 * not need permanent screen space. The close button is remembered per calculation, so
 * dismissing it does not bring it back on the next tab switch, but a NEW structural edit
 * (a different `since`) does bring it back.
 */
export const StructureStaleBanner: React.FC<Props> = ({ resultData, calculationId }) => {
  const t = useT();
  const [dismissedSince, setDismissedSince] = useState<string | null>(null);

  const stale = (resultData as { structure_stale?: StructureStale } | null | undefined)
    ?.structure_stale;
  if (!stale || !(stale.analysis || stale.sampling || stale.field_inventory)) return null;

  // A dismissal only covers the change it was made against. Keyed on `since`, not on
  // the calculation, so the next divide/merge raises it again.
  if (stale.since && dismissedSince === stale.since) return null;

  const domains: string[] = [];
  if (stale.analysis) domains.push(t('structure.stale.domains.analysis'));
  if (stale.sampling) domains.push(t('structure.stale.domains.sampling'));
  if (stale.field_inventory) domains.push(t('structure.stale.domains.fieldInventory'));

  return (
    <div
      className="structure-stale-strip"
      data-testid="structure-stale-banner"
      data-calculation-id={calculationId}
      role="status"
    >
      <WarningOutlined className="structure-stale-strip-icon" aria-hidden="true" />
      <Tooltip title={t('structure.stale.body')} placement="bottomLeft">
        <span
          className="structure-stale-strip-text"
          // The full sentence is still announced, and is the tooltip — it is
          // simply no longer taking up screen space permanently.
          aria-label={`${t('structure.stale.title')} — ${t('structure.stale.body')}`}
        >
          <span className="structure-stale-strip-title">{t('structure.stale.short')}</span>
          <span className="structure-stale-strip-domains">{domains.join(', ')}</span>
        </span>
      </Tooltip>
      <button
        type="button"
        className="structure-stale-strip-close"
        aria-label={t('structure.stale.dismiss')}
        title={t('structure.stale.dismiss')}
        onClick={() => setDismissedSince(stale.since ?? 'x')}
      >
        ×
      </button>
    </div>
  );
};

export default StructureStaleBanner;
