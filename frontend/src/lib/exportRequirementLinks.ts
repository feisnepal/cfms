/**
 * Where each mandatory export step is done, so the checklist can take the user straight there.
 *
 * Keys are the `key` of `backend/app/services/operational_plan/export_requirements.py`. A destination is a calc-shell
 * surface (`<group>/<context>`, see `calcSurface.ts`) plus, optionally, a pane inside it and a dialog to open.
 * Households and the committee are not pages of their own: they open over the Map (`open=`).
 */
import { toSurfaceId } from './calcSurface';

export interface RequirementLink {
  group: 'base' | 'field' | 'analysis' | 'plan';
  context: string;
  /** a pane of that page (`?pane=`), when the page has tabs */
  pane?: string;
  /** a dialog to open over the page (`?open=`) */
  open?: 'households' | 'committee';
  /** the plan chapter to open and type in (`?node=`, matched by its title) */
  node?: string;
}

export const REQUIREMENT_LINKS: Record<string, RequirementLink> = {
  raster: { group: 'base', context: 'unified' },
  sampling: { group: 'field', context: 'sampling' },
  field_inventory: { group: 'field', context: 'fieldinventory' },
  biodiversity: { group: 'field', context: 'biodiversity' },
  households: { group: 'base', context: 'unified', open: 'households' },
  yearly_activities: { group: 'plan', context: 'yearly' },
  sub_areas_planned: { group: 'plan', context: 'yearly' },
  cba: { group: 'analysis', context: 'cba' },
  committee: { group: 'base', context: 'unified', open: 'committee' },
  metadata: { group: 'field', context: 'forestmetadata' },
};

/** The URL of the page that completes a requirement, or null for a key this map does not know. */
export function requirementUrl(calculationId: string, key: string): string | null {
  const link = REQUIREMENT_LINKS[key];
  if (!link || !calculationId) return null;
  const params = new URLSearchParams({ surface: toSurfaceId(link.group, link.context) });
  if (link.pane) params.set('pane', link.pane);
  if (link.open) params.set('open', link.open);
  if (link.node) params.set('node', link.node);
  return `/calculations/${calculationId}?${params.toString()}`;
}

/** Report-data names (`sections-available` -> `missing`) -> the page that provides them, with a short label in both languages. */
export const DATA_KEY_LINKS: Record<string, { link: RequirementLink; ne: string; en: string }> = {
  basic_info: { link: { group: 'base', context: 'unified' }, ne: 'वनको नक्सा र विवरण', en: 'Forest map and details' },
  boundary: { link: { group: 'base', context: 'unified' }, ne: 'वनको सिमाना', en: 'Forest boundary' },
  blocks: { link: { group: 'base', context: 'unified' }, ne: 'ब्लक / कम्पार्टमेन्ट', en: 'Blocks / compartments' },
  raster_analysis: { link: { group: 'base', context: 'unified' }, ne: 'इकाईहरूको विश्लेषण', en: 'Analysis of the units' },
  user_group: { link: { group: 'base', context: 'usergroup' }, ne: 'उपभोक्ता समूह नक्सा', en: 'User group map' },
  households: { link: { group: 'base', context: 'unified', open: 'households' }, ne: 'घरधुरी विवरण', en: 'Household information' },
  committees: { link: { group: 'base', context: 'unified', open: 'committee' }, ne: 'वन उपभोक्ता समिति', en: 'Forest user committee' },
  sampling: { link: { group: 'field', context: 'sampling' }, ne: 'नमुना प्लट', en: 'Sample plots' },
  inventory: { link: { group: 'field', context: 'fieldinventory' }, ne: 'क्षेत्र सूची', en: 'Field inventory' },
  species: { link: { group: 'field', context: 'biodiversity' }, ne: 'प्रजाति अभिलेख', en: 'Species records' },
  biodiversity: { link: { group: 'field', context: 'biodiversity' }, ne: 'जैविक विविधता', en: 'Biodiversity' },
  activities: { link: { group: 'plan', context: 'yearly' }, ne: 'वार्षिक कार्यक्रम योजना', en: 'Yearly activities plan' },
};

/** Sections you write by hand are typed in the Operational Plan (its chapters are editable text). */
export const MANUAL_SECTION_LINK: RequirementLink = { group: 'plan', context: 'mgmtplan' };

function urlOf(calculationId: string, link: RequirementLink): string {
  const params = new URLSearchParams({ surface: toSurfaceId(link.group, link.context) });
  if (link.pane) params.set('pane', link.pane);
  if (link.open) params.set('open', link.open);
  return `/calculations/${calculationId}?${params.toString()}`;
}

/** Links for a report section: one per missing kind of data, or the plan editor for a hand-written one. */
export function reportSectionFixes(
  calculationId: string,
  status: string,
  missing: string[] | undefined,
  titleNe?: string,
): { key: string; url: string; ne: string; en: string }[] {
  if (!calculationId) return [];
  if (status === 'manual_input') {
    return [{ key: 'manual', url: urlOf(calculationId, { ...MANUAL_SECTION_LINK, node: titleNe }), ne: 'अपरेसनल प्लानमा लेख्नुहोस्', en: 'Write it in the Operational Plan' }];
  }
  if (status !== 'missing_data') return [];
  const seen = new Set<string>();
  const out: { key: string; url: string; ne: string; en: string }[] = [];
  for (const k of missing ?? []) {
    const d = DATA_KEY_LINKS[k];
    if (!d) continue;
    const url = urlOf(calculationId, d.link);
    if (seen.has(url)) continue;
    seen.add(url);
    out.push({ key: k, url, ne: d.ne, en: d.en });
  }
  return out;
}
