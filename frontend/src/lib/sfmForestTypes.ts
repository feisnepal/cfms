/**
 * Pure helpers for the 14 अनुसूची-१ forest types shown inline in the Sustainable Forest Management tab.
 * No React, no i18n call: callers pass `t`. Kept pure so the wording rules can be unit-tested.
 */
import type { SfmBranch, SfmPrescription, SfmYieldStep } from '../services/api';

/** One colour per orientation, so a user reads production / conservation / protection at a glance. */
export const ORIENTATION_COLOR: Record<string, string> = {
  Production: '#389e0d',
  Conservation: '#1677ff',
  Protection: '#d4380d',
  Restoration: '#d48806',
  'Multi-use': '#722ed1',
};

export const orientationColor = (o: string | undefined): string => ORIENTATION_COLOR[o ?? ''] ?? '#8c8c8c';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type T = (...args: any[]) => any;

/** "≥ 200 m³/ha → 1%", "150–200 m³/ha → 0.5%", "< 150 m³/ha → 0.5%". */
export function formatYieldStep(step: SfmYieldStep, t: T): string {
  const { gs_per_ha_min: min, gs_per_ha_max: max, pct } = step;
  let range: string;
  if (min != null && max != null) range = t('sfm.ref.stepRange', { min, max });
  else if (min != null) range = t('sfm.ref.stepGe', { min });
  else if (max != null) range = t('sfm.ref.stepLt', { max });
  else range = t('sfm.ref.stepAny');
  return `${range} → ${t('sfm.ref.pctPerYear', { pct })}`;
}

/** The branch a tooltip leads with: "adequate" regeneration when the type has one, else its single "default". */
export function primaryBranchKey(p: SfmPrescription): string | null {
  const keys = Object.keys(p.branches ?? {});
  if (keys.includes('adequate')) return 'adequate';
  if (keys.includes('default')) return 'default';
  return keys[0] ?? null;
}

/** Harvest lines for one branch: the volume steps when it has them, otherwise the rule's own note (both languages). */
export function harvestLines(branch: SfmBranch, t: T): string[] {
  const y = branch.yield_rules;
  if (y?.steps && y.steps.length > 0) return y.steps.map((s) => formatYieldStep(s, t));
  if (y?.target_stems_per_ha && y.target_stems_per_ha.length > 0) {
    return [t('sfm.ref.targetStems', { range: y.target_stems_per_ha.join('–') })];
  }
  const note = [y?.note_ne, y?.note_en].filter(Boolean) as string[];
  return note;
}

export function slopeKey(p: SfmPrescription): string {
  return p.slope_band != null ? `sfm.ref.slopeBand.${p.slope_band}` : 'sfm.ref.slopeBand.any';
}

export const escapeHtml = (s: unknown): string =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));

export interface MapBlockType {
  type_no: number;
  proposed_type_no?: number | null;
  overridden?: boolean;
  confidence?: number | null;
  reasons?: string[];
}

/**
 * The hover card for a block on the workspace map: the same facts as the "Type N" tooltip, as an HTML string
 * (Leaflet tooltips take markup). Every dynamic value is escaped. A block whose type the user changed says so.
 */
export function typeCardHtml(p: SfmPrescription, block: MapBlockType | undefined, blockName: string, t: T): string {
  const key = primaryBranchKey(p);
  const branch = key ? p.branches[key] : null;
  const lines = branch ? harvestLines(branch, t) : [];
  const zones = (p.zone_triggers ?? []).map((z) => t(`sfm.zone.${z}`, z)).join(', ') || '—';
  const groups = (p.species_groups ?? []).map((g) => t(`sfm.ref.group.${g}`, g)).join(', ') || '—';
  const dot = `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${orientationColor(p.orientation)};margin-right:6px"></span>`;
  const e = escapeHtml;
  return [
    `<div class="sfm-card">`,
    `<div style="font-weight:600;font-size:13px">${e(blockName)} · ${e(t('sfm.typeNo', { n: p.type_no }))}</div>`,
    `<div style="font-weight:600">${e(p.name_ne)}</div><div style="color:#555">${e(p.name_en)}</div>`,
    `<div style="margin:5px 0">${dot}<strong>${e(t(`sfm.orientation.${p.orientation}`, p.orientation))}</strong>${
      block?.overridden && block.proposed_type_no != null
        ? ` <span style="color:#d46b08">· ${e(t('sfm.ref.overridden', { n: block.proposed_type_no }))}</span>`
        : ''
    }</div>`,
    p.notes_ne || p.notes_en
      ? `<div>${e(p.notes_ne)}</div><div style="color:#555">${e(p.notes_en)}</div>`
      : '',
    `<div style="border-top:1px solid #eee;margin-top:5px;padding-top:5px">`,
    `<span style="color:#888">${e(t('sfm.ref.zone'))}:</span> ${e(zones)} · <span style="color:#888">${e(t('sfm.ref.species'))}:</span> ${e(groups)}`,
    `<div><span style="color:#888">${e(t('sfm.ref.slope'))}:</span> ${e(t(slopeKey(p)))}</div>`,
    branch
      ? `<div style="margin-top:4px;color:#888">${e(t('sfm.ref.harvest'))} — ${e(t(`sfm.ref.branch.${key}`, key ?? ''))}</div>${lines
          .map((l) => `<div>• ${e(l)}</div>`)
          .join('')}<div><span style="color:#888">${e(t('sfm.ref.system'))}:</span> ${e(branch.system_ne)}<div style="color:#555">${e(branch.system_en)}</div></div>`
      : '',
    `</div>`,
    block?.reasons && block.reasons.length
      ? `<div style="border-top:1px solid #eee;margin-top:5px;padding-top:5px"><div style="color:#888">${e(t('sfm.ref.thisBlock'))}</div>${block.reasons
          .map((r) => `<div>• ${e(r)}</div>`)
          .join('')}</div>`
      : '',
    `<div style="margin-top:5px;color:#888">${e(t('sfm.ref.mapHint'))}</div>`,
    `</div>`,
  ].join('');
}

// ── one fetch, shared by every tag on the page ───────────────────────────
let cache: Promise<Record<number, SfmPrescription>> | null = null;

export function loadForestTypes(
  fetcher: () => Promise<SfmPrescription[]>,
): Promise<Record<number, SfmPrescription>> {
  if (!cache) {
    cache = fetcher()
      .then((rows) => Object.fromEntries(rows.map((r) => [r.type_no, r])))
      .catch((e) => {
        cache = null; // a failed load must be retryable, not remembered
        throw e;
      });
  }
  return cache;
}

/** Test hook: forget the cached fetch. */
export function resetForestTypesCache(): void {
  cache = null;
}
