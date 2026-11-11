/**
 * "Type N" — the one place a अनुसूची-१ forest type is shown to the user.
 *
 * Every place the SFM tab used to print `t('sfm.typeNo', { n })` now renders this, so a user who sees "Type 7"
 * can hover to learn what it is (name in both languages, orientation, zone, species, slope, the harvest steps)
 * and click to open the full reference panel — without leaving the page (owner, 2026-10-06).
 */
import React from 'react';
import { Popover } from 'antd';
import { useT } from '../../i18n/hooks';
import { useSfmForestTypes } from '../../hooks/useSfmForestTypes';
import { useSfmTypeReference } from './SfmTypeReference';
import {
  harvestLines,
  orientationColor,
  primaryBranchKey,
  slopeKey,
} from '../../lib/sfmForestTypes';
import type { SfmPrescription } from '../../services/api';

/** What the classifier said about ONE block, shown under the type's own description. */
export interface SfmTypeBlockContext {
  reasons: string[];
  confidence?: number;
  needsReview?: boolean;
}

const dot = (color: string): React.CSSProperties => ({
  display: 'inline-block',
  width: 9,
  height: 9,
  borderRadius: '50%',
  background: color,
  marginInlineEnd: 6,
});

export const SfmTypeCard: React.FC<{ p: SfmPrescription; block?: SfmTypeBlockContext; onOpen?: () => void }> = ({
  p,
  block,
  onOpen,
}) => {
  const t = useT();
  const branchKey = primaryBranchKey(p);
  const branch = branchKey ? p.branches[branchKey] : null;
  const lines = branch ? harvestLines(branch, t) : [];
  const zones = (p.zone_triggers ?? []).map((z) => t(`sfm.zone.${z}`, z)).join(', ') || '—';
  const groups = (p.species_groups ?? []).map((g) => t(`sfm.ref.group.${g}`, g)).join(', ') || '—';

  return (
    <div style={{ width: 380, fontSize: 12, lineHeight: 1.45 }} data-testid={`sfm-type-card-${p.type_no}`}>
      <div style={{ fontWeight: 600, fontSize: 13 }}>
        {t('sfm.typeNo', { n: p.type_no })} · {p.name_ne}
      </div>
      <div style={{ color: '#555' }}>{p.name_en}</div>
      <div style={{ margin: '6px 0' }}>
        <span style={dot(orientationColor(p.orientation))} />
        <strong>{t(`sfm.orientation.${p.orientation}`, p.orientation)}</strong>
      </div>
      {(p.notes_ne || p.notes_en) && (
        <div style={{ marginBottom: 6 }}>
          {p.notes_ne && <div>{p.notes_ne}</div>}
          {p.notes_en && <div style={{ color: '#555' }}>{p.notes_en}</div>}
        </div>
      )}
      <div style={{ borderTop: '1px solid #eee', paddingTop: 6 }}>
        <div>
          <span style={{ color: '#888' }}>{t('sfm.ref.zone')}:</span> {zones} ·{' '}
          <span style={{ color: '#888' }}>{t('sfm.ref.species')}:</span> {groups}
        </div>
        <div>
          <span style={{ color: '#888' }}>{t('sfm.ref.slope')}:</span> {t(slopeKey(p))}
          <div style={{ color: '#888' }}>{t('sfm.ref.slope45')}</div>
        </div>
        {branch && (
          <div style={{ marginTop: 6 }}>
            <div style={{ color: '#888' }}>
              {t('sfm.ref.harvest')} — {t(`sfm.ref.branch.${branchKey}`, branchKey ?? '')}
            </div>
            {lines.map((l, i) => (
              <div key={i}>• {l}</div>
            ))}
            <div style={{ marginTop: 2 }}>
              <span style={{ color: '#888' }}>{t('sfm.ref.system')}:</span> {branch.system_ne}
              <div style={{ color: '#555' }}>{branch.system_en}</div>
              {branch.felling_cycle_years != null && (
                <div>
                  {t('sfm.ref.fellingCycle')}: {t('sfm.ref.years', { n: branch.felling_cycle_years })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
      {block && block.reasons.length > 0 && (
        <div style={{ borderTop: '1px solid #eee', marginTop: 6, paddingTop: 6 }}>
          <div style={{ color: '#888' }}>{t('sfm.ref.thisBlock')}</div>
          {block.reasons.map((r, i) => (
            <div key={i}>• {r}</div>
          ))}
          {block.confidence != null && (
            <div style={{ opacity: 0.8 }}>{t('sfm.block.confidence', { pct: (block.confidence * 100).toFixed(0) })}</div>
          )}
        </div>
      )}
      {onOpen ? (
        <button
          type="button"
          data-testid={`sfm-type-card-open-${p.type_no}`}
          onClick={(e) => {
            e.stopPropagation();
            onOpen();
          }}
          style={{
            marginTop: 6,
            padding: 0,
            border: 0,
            background: 'none',
            color: '#1677ff',
            cursor: 'pointer',
            font: 'inherit',
            textDecoration: 'underline',
          }}
        >
          {t('sfm.ref.moreDetails')} ›
        </button>
      ) : (
        <div style={{ marginTop: 6, color: '#888' }}>{t('sfm.ref.moreDetails')} ›</div>
      )}
    </div>
  );
};

interface TagProps {
  n: number;
  block?: SfmTypeBlockContext;
  /** Replace the default "Type N" text (the reference table shows the bare number). */
  children?: React.ReactNode;
}

export const SfmTypeTag: React.FC<TagProps> = ({ n, block, children }) => {
  const t = useT();
  const { types } = useSfmForestTypes();
  const reference = useSfmTypeReference();
  const label = children ?? t('sfm.typeNo', { n });
  const p = types?.[n];

  // Until the types arrive (or if they never do) the tag is just its label -- never a broken tooltip.
  if (!p) return <span data-testid={`sfm-type-tag-${n}`}>{label}</span>;

  return (
    <Popover
      mouseEnterDelay={0.2}
      placement="right"
      content={<SfmTypeCard p={p} block={block} onOpen={reference ? () => reference.open(n) : undefined} />}
    >
      <span
        data-testid={`sfm-type-tag-${n}`}
        role={reference ? 'button' : undefined}
        tabIndex={reference ? 0 : undefined}
        onClick={reference ? (e) => { e.stopPropagation(); reference.open(n); } : undefined}
        onKeyDown={reference ? (e) => { if (e.key === 'Enter') reference.open(n); } : undefined}
        style={{
          cursor: reference ? 'pointer' : 'help',
          borderBottom: '1px dotted #8c8c8c',
        }}
      >
        <span style={dot(orientationColor(p.orientation))} />
        {label}
      </span>
    </Popover>
  );
};

export default SfmTypeTag;
