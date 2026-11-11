/**
 * NTFP inventory page: the small pure rules behind the panels (what is sent, how a finding is grouped, which warning says what).
 * Nothing here touches the network or React, so it is tested on its own (lib/__tests__/ntfp.test.ts).
 */
import type { NtfpAah, NtfpCardStatus, NtfpDesignRequest, NtfpFactValue, NtfpFinding, NtfpHarvestRow, NtfpSpecies, NtfpSpeciesChoice, NtfpPartResult, NtfpPlot, NtfpObservationRecord, NtfpSpeciesEntry, NtfpReviewCard, NtfpReviewEdits, NtfpReviewRow, NtfpValueStatus } from '../services/api';

/** What the user has chosen for one species on the Species tab. A blank number means "use the guideline's default". */
export interface NtfpPick {
  plot_sqm: number | null;
  intensity_pct: number | null;
  growth_class: string | null;
}

export const GROWTH_CLASSES = ['tree', 'shrub', 'climber', 'herb', 'fungus', 'lichen'] as const;

/** Schedule-7 part group letter -> the i18n key segment (the key files carry no Devanagari letters in key names). */
export const PART_KEYS: Record<string, string> = { 'क': 'root', 'ख': 'bark', 'ग': 'leaf', 'घ': 'flower', 'ङ': 'fruit', 'च': 'whole', 'छ': 'resin' };
export const partKey = (group: string | null | undefined): string => (group && PART_KEYS[group]) || 'whole';

export const emptyPick = (): NtfpPick => ({ plot_sqm: null, intensity_pct: null, growth_class: null });

/** A species with no method card cannot be designed until its growth class is chosen. */
export const needsGrowthClass = (sp: Pick<NtfpSpecies, 'growth_class'>, pick: NtfpPick | undefined): boolean =>
  !sp.growth_class && !(pick && pick.growth_class);

/** The request for the design endpoints. Blank numbers are left out so the server applies the guideline's defaults. */
export function buildDesignRequest(
  picks: Record<string, NtfpPick>,
  shape: 'square' | 'circular',
  seed: number | null,
  minPlots: number,
): NtfpDesignRequest {
  const species: NtfpSpeciesChoice[] = Object.entries(picks).map(([species_key, p]) => {
    const c: NtfpSpeciesChoice = { species_key };
    if (p.plot_sqm != null && p.plot_sqm > 0) c.plot_sqm = p.plot_sqm;
    if (p.intensity_pct != null && p.intensity_pct > 0) c.intensity_pct = p.intensity_pct;
    if (p.growth_class) c.growth_class = p.growth_class;
    return c;
  });
  const req: NtfpDesignRequest = { species, plot_shape: shape, min_plots: minPlots };
  if (seed != null && seed >= 1) req.seed = seed;
  return req;
}

/** The first thing wrong with the picks, as a message key, or null when a design can be asked for. */
export function designProblem(species: NtfpSpecies[], picks: Record<string, NtfpPick>): string | null {
  const keys = Object.keys(picks);
  if (!keys.length) return 'ntfp.design.problemNoSpecies';
  const byKey = new Map(species.map((s) => [s.species_key, s]));
  for (const k of keys) {
    const sp = byKey.get(k);
    if (sp && needsGrowthClass(sp, picks[k])) return 'ntfp.design.problemGrowthClass';
    const pct = picks[k].intensity_pct;
    if (pct != null && (pct <= 0 || pct > 100)) return 'ntfp.design.problemIntensity';
  }
  return null;
}

/** Findings for one sheet, errors first, in row order. */
export function sortFindings(findings: NtfpFinding[]): NtfpFinding[] {
  const rank = (f: NtfpFinding) => (f.severity === 'error' ? 0 : 1);
  return [...findings].sort((a, b) => rank(a) - rank(b) || (a.row ?? 0) - (b.row ?? 0));
}

/** Warning codes the results can carry, each mapped to its i18n key. An unknown code gets the generic key, never a raw code on screen. */
const WARNING_KEYS: Record<string, string> = {
  not_surveyed: 'ntfp.warn.notSurveyed',
  few_plots: 'ntfp.warn.fewPlots',
  survey_incomplete: 'ntfp.warn.surveyIncomplete',
  not_found: 'ntfp.warn.notFound',
  no_weights: 'ntfp.warn.noWeights',
  no_dry_weights: 'ntfp.warn.noDryWeights',
  few_samples: 'ntfp.warn.fewSamples',
  cf_differs_from_guideline: 'ntfp.warn.cfDiffers',
  fewer_plots_than_wanted: 'ntfp.warn.fewerPlotsThanWanted',
  area_too_narrow_for_whole_plots: 'ntfp.warn.areaTooNarrow',
};
export const warningKey = (code: string): string => WARNING_KEYS[code] ?? 'ntfp.warn.other';

/** Server error code -> message key for the actions of this page. */
const ERROR_KEYS: Record<string, string> = {
  has_records: 'ntfp.error.hasRecords',
  no_design: 'ntfp.error.noDesign',
  no_geometry: 'ntfp.error.noGeometry',
  unknown_species: 'ntfp.error.unknownSpecies',
  growth_class_needed: 'ntfp.design.problemGrowthClass',
  bad_number: 'ntfp.design.problemIntensity',
  'file.wrong_type': 'ntfp.collect.wrongType',
  'file.too_large': 'ntfp.collect.tooLarge',
  'file.empty': 'ntfp.collect.emptyFile',
  'harvest.exceeds_stock': 'ntfp.harvest.errExceeds',
  'harvest.unknown_row': 'ntfp.harvest.errUnknown',
  'harvest.duplicate': 'ntfp.harvest.errDuplicate',
  'harvest.bad_value': 'ntfp.harvest.errBadValue',
  'harvest.nothing_planned': 'ntfp.harvest.errNothingPlanned',
  'harvest.no_activity': 'ntfp.harvest.errNoActivity',
  mode_conflict: 'ntfp.entry.modeConflict',
  'photo.wrong_type': 'ntfp.photo.errType',
  'photo.too_large': 'ntfp.photo.errSize',
  'photo.too_many': 'ntfp.photo.errMany',
  'photo.empty': 'ntfp.photo.errEmpty',
  unknown_plot: 'ntfp.entry.unknownPlot',
};
export const errorKey = (code: string | undefined): string | null => (code && ERROR_KEYS[code]) || null;

/** How far a result can be trusted, from its precision: the 95 % half-width as a share of the estimate. */
export type Trust = 'good' | 'fair' | 'poor' | 'unknown';
export const trustOf = (precisionPct: number | null | undefined): Trust =>
  precisionPct == null ? 'unknown' : precisionPct <= 20 ? 'good' : precisionPct <= 50 ? 'fair' : 'poor';

/** Share of the species-and-plot pairs of a design that have been recorded, as a whole percentage. */
export const progressPct = (recorded: number, assigned: number): number => (assigned > 0 ? Math.min(100, Math.round((recorded / assigned) * 100)) : 0);

/** A part's dry-yield figure, or its fresh one when no dry weights exist yet (and which it is). */
export function yieldOf(p: Pick<NtfpPartResult, 'yield_dry_kg_ha' | 'yield_fresh_kg_ha'>): { value: number | null; basis: 'dry' | 'fresh' } {
  return p.yield_dry_kg_ha != null ? { value: p.yield_dry_kg_ha, basis: 'dry' } : { value: p.yield_fresh_kg_ha, basis: 'fresh' };
}

/** Plots by species for the map legend: how many plot positions carry each species. */
export function plotsPerSpecies(plots: Array<{ species_keys: string[] }>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of plots) for (const k of p.species_keys) out[k] = (out[k] ?? 0) + 1;
  return out;
}

// ── the plots on the map: what has been recorded, and what to show on each icon ─────────────────────────────────────────────────

export type PlotLayer = 'status' | 'count' | string;   // 'species:<key>' colours by that species' count

export interface PlotSummary { assigned: number; recorded: number; plants: number; status: 'none' | 'partial' | 'done'; counts: Record<string, number> }

export const PLOT_STATUS_COLOUR: Record<PlotSummary['status'], string> = { none: '#9e9e9e', partial: '#fb8c00', done: '#2e7d32' };

/** Per plot: how many of its species have a record, the plants counted, and the status (grey = nothing, amber = some, green = all). */
export const plotSummaries = (plots: NtfpPlot[], observations: NtfpObservationRecord[]): Record<number, PlotSummary> => {
  const out: Record<number, PlotSummary> = {};
  plots.forEach((p) => { out[p.plot_number] = { assigned: p.species_keys.length, recorded: 0, plants: 0, status: 'none', counts: {} }; });
  observations.forEach((o) => {
    const s = out[o.plot_number];
    if (!s) return;
    s.recorded += 1;
    s.plants += o.count_total;
    s.counts[o.species_key] = o.count_total;
  });
  Object.values(out).forEach((s) => { s.status = s.recorded === 0 ? 'none' : s.recorded >= s.assigned ? 'done' : 'partial'; });
  return out;
};

/** The marker colour of a plot on the chosen layer. A count layer is a green ramp scaled to the largest count; a plot not surveyed is grey. */
export const layerColour = (layer: PlotLayer, s: PlotSummary | undefined, maxValue: number): string => {
  if (!s) return PLOT_STATUS_COLOUR.none;
  if (layer === 'status') return PLOT_STATUS_COLOUR[s.status];
  const v = layer === 'count' ? (s.recorded ? s.plants : null) : (layer.startsWith('species:') ? (layer.slice(8) in s.counts ? s.counts[layer.slice(8)] : null) : null);
  if (v == null) return PLOT_STATUS_COLOUR.none;
  if (v === 0) return '#eeeeee';
  const t = maxValue > 0 ? Math.min(1, v / maxValue) : 0;
  const from = [200, 230, 201], to = [27, 94, 32];
  return `rgb(${from.map((c, i) => Math.round(c + (to[i] - c) * t)).join(',')})`;
};

/** The value written on a plot's icon: "3/5" (species recorded of species assigned) on the status layer, the number counted on a count layer. */
export const layerLabel = (layer: PlotLayer, s: PlotSummary | undefined): string => {
  if (!s) return '';
  if (layer === 'status') return `${s.recorded}/${s.assigned}`;
  if (layer === 'count') return s.recorded ? String(s.plants) : '';
  const k = layer.slice(8);
  return k in s.counts ? String(s.counts[k]) : '';
};

// ── "I am here": the phone's position ─────────────────────────────────────────────────────────────────────────────────────────

export interface Position { latitude: number; longitude: number; accuracy_m: number | null }

/** Why a position could not be read, as the i18n key to show. */
export type PositionFailure = 'denied' | 'unavailable' | 'timeout' | 'unsupported';
export const positionFailureKey = (f: PositionFailure): string => `ntfp.here.fail.${f}`;

/** Read the phone's position once, with the best accuracy it can give. Rejects with a `PositionFailure`. The browser only offers a position on https or localhost. */
export const readPosition = (timeoutMs = 20000): Promise<Position> => new Promise((resolve, reject) => {
  if (typeof navigator === 'undefined' || !navigator.geolocation) { reject('unsupported' as PositionFailure); return; }
  navigator.geolocation.getCurrentPosition(
    (p) => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy_m: Number.isFinite(p.coords.accuracy) ? Math.round(p.coords.accuracy * 10) / 10 : null }),
    (e) => reject((e.code === 1 ? 'denied' : e.code === 3 ? 'timeout' : 'unavailable') as PositionFailure),
    { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
  );
});

/** What to tell the person: the i18n key of the verdict's message. */
export const verdictKey = (v: 'at' | 'far' | 'uncertain'): string => `ntfp.here.${v}`;

/** The ring round a plot's icon on the map: blue = checked at the plot, red = checked and far away, none = not checked or uncertain. */
export const VERDICT_RING: Record<string, string> = { at: '#1565c0', far: '#c62828' };

// ── the sample plots as a layer of the map workspace ──────────────────────────────────────────────────────────────────────────

/** The print map this layer stands for (a backend test checks that it exists). */
export const NTFP_PLOTS_SPEC_KEY = 'unit__ntfp_plots';
export const NTFP_PLOTS_PLACEHOLDER = `thememap:${NTFP_PLOTS_SPEC_KEY}`;
/** Above the forest's own layers, so a plot can be clicked. */
export const NTFP_PLOTS_PANE = 'cfNtfpPlots';
export const NTFP_PLOTS_PANE_Z = '620';

const layerKey = (calculationId: string) => `cf_ntfp_plots_layer_${calculationId}`;
export const readNtfpLayerOn = (calculationId: string | undefined): boolean => {
  if (!calculationId) return false;
  try { return localStorage.getItem(layerKey(calculationId)) === '1'; } catch { return false; }   // storage blocked: the layer starts switched off
};
export const writeNtfpLayerOn = (calculationId: string | undefined, on: boolean): void => {
  if (!calculationId) return;
  try { localStorage.setItem(layerKey(calculationId), on ? '1' : '0'); } catch { /* nothing remembered, nothing breaks */ }
};

// ── the stages of the survey, as a guided strip ───────────────────────────────────────────────────────────────────────────────

export type StageKey = 'species' | 'design' | 'collect' | 'results' | 'harvest';
/** done = finished; current = the one to do next; todo = can be done, not next; locked = needs an earlier stage first (still reachable: nothing is hidden). */
export type StageStatus = 'done' | 'current' | 'todo' | 'locked';

export interface StageInput {
  picked: number;            // species ticked on the Species tab
  designSpecies: number;     // species in the saved design (0: none saved)
  plots: number;             // plots in the saved design
  hasDesign: boolean;
  recorded: number;          // species-in-plot records brought in
  assigned: number;          // species-in-plot pairs the design asks for
  plannedRows: number | null; // harvest rows with a planned quantity (null: not known yet)
}

export interface Stage { key: StageKey; status: StageStatus; detailKey: string; params: Record<string, number> }

/**
 * Where the survey stands, stage by stage, and what the next stage says it needs. Pure, so the strip and the tests agree. The first stage that is neither done nor locked is the
 * current one. A stage is never hidden or refused because an earlier one is open: `locked` only says what it is waiting for.
 */
export const ntfpStages = (i: StageInput): Stage[] => {
  const stage = (key: StageKey, status: StageStatus, detailKey: string, params: Record<string, number> = {}): Stage => ({ key, status, detailKey, params });
  const complete = i.assigned > 0 && i.recorded >= i.assigned;
  const raw: Stage[] = [
    i.hasDesign ? stage('species', 'done', 'ntfp.stage.speciesDone', { n: i.designSpecies })
      : i.picked > 0 ? stage('species', 'todo', 'ntfp.stage.speciesPicked', { n: i.picked })
      : stage('species', 'todo', 'ntfp.stage.speciesNone'),
    i.hasDesign ? stage('design', 'done', 'ntfp.stage.designDone', { n: i.plots })
      : i.picked > 0 ? stage('design', 'todo', 'ntfp.stage.designReady')
      : stage('design', 'locked', 'ntfp.stage.designNeedsSpecies'),
    !i.hasDesign ? stage('collect', 'locked', 'ntfp.stage.collectNeedsDesign')
      : complete ? stage('collect', 'done', 'ntfp.stage.collectDone', { done: i.recorded, all: i.assigned })
      : i.recorded > 0 ? stage('collect', 'todo', 'ntfp.stage.collectPartly', { done: i.recorded, all: i.assigned })
      : stage('collect', 'todo', 'ntfp.stage.collectNone', { all: i.assigned }),
    i.recorded > 0 ? stage('results', 'done', 'ntfp.stage.resultsReady') : stage('results', 'locked', 'ntfp.stage.resultsNeedsRecords'),
    i.recorded === 0 ? stage('harvest', 'locked', 'ntfp.stage.harvestNeedsRecords')
      : (i.plannedRows ?? 0) > 0 ? stage('harvest', 'done', 'ntfp.stage.harvestDone', { n: i.plannedRows ?? 0 })
      : stage('harvest', 'todo', 'ntfp.stage.harvestNone'),
  ];
  const next = raw.findIndex((s) => s.status === 'todo');
  return raw.map((s, idx) => (idx === next ? { ...s, status: 'current' as StageStatus } : s));
};

// ── what is waiting to be sent ────────────────────────────────────────────────────────────────────────────────────────────────

/**
 * The stored records with the plots saved offline laid over them, so the map and the sheet show what was typed even before it is sent. A queued plot save replaces what is stored for
 * that plot: its species with a count become records, its empty species are gone (a save of an empty species clears it).
 */
export const overlayPending = (observations: NtfpObservationRecord[], pending: { plotNumber: number; entries?: NtfpSpeciesEntry[] }[]): NtfpObservationRecord[] => {
  let out = observations;
  pending.forEach((p) => {
    const keep = out.filter((o) => o.plot_number !== p.plotNumber || !(p.entries ?? []).some((e) => e.species_key === o.species_key));
    const added = (p.entries ?? []).filter((e) => e.count_total != null).map((e): NtfpObservationRecord => ({
      plot_number: p.plotNumber, species_key: e.species_key, visit_date: e.visit_date ?? null, count_total: e.count_total ?? 0, count_mature: e.count_mature ?? null,
      count_small: e.count_small ?? null, clumps: e.clumps ?? null, tillers: e.tillers ?? null, notes: e.notes ?? null, source: 'manual',
      weights: e.weights.filter((w) => w.fresh_weight_g != null).map((w, i) => ({ sample_no: w.sample_no ?? i + 1, part_group: w.part_group ?? null, fresh_weight_g: w.fresh_weight_g ?? 0, dry_weight_g: w.dry_weight_g ?? null, notes: w.notes ?? null })),
    }));
    out = [...keep, ...added];
  });
  return out;
};

// ── entering one plot on the map ────────────────────────────────────────────────────────────────────────────────────────────

export interface EntryDraft {
  species_key: string; visit_date: string; count_total: number | null; count_mature: number | null; count_small: number | null;
  clumps: number | null; tillers: number | null; notes: string; weights: { fresh: number | null; dry: number | null }[];
}

/** One draft per species of the plot, filled from what is stored (a species with no record is an empty draft: not surveyed). */
export const draftsFor = (speciesKeys: string[], stored: NtfpObservationRecord[]): EntryDraft[] =>
  speciesKeys.map((k) => {
    const o = stored.find((x) => x.species_key === k);
    return {
      species_key: k, visit_date: o?.visit_date ?? '', count_total: o?.count_total ?? null, count_mature: o?.count_mature ?? null, count_small: o?.count_small ?? null,
      clumps: o?.clumps ?? null, tillers: o?.tillers ?? null, notes: o?.notes ?? '',
      weights: (o?.weights ?? []).map((w) => ({ fresh: w.fresh_weight_g, dry: w.dry_weight_g })),
    };
  });

export const draftIsEmpty = (d: EntryDraft): boolean =>
  !d.visit_date && d.count_total == null && d.count_mature == null && d.count_small == null && d.clumps == null && d.tillers == null && !d.notes.trim() && d.weights.length === 0;

/** The request row. An empty draft is sent as just its key: the server clears that species' record. */
export const draftToEntry = (d: EntryDraft): NtfpSpeciesEntry => (draftIsEmpty(d) ? { species_key: d.species_key, weights: [] } : {
  species_key: d.species_key, visit_date: d.visit_date || null, count_total: d.count_total, count_mature: d.count_mature, count_small: d.count_small,
  clumps: d.clumps, tillers: d.tillers, notes: d.notes.trim() || null,
  weights: d.weights.filter((w) => w.fresh != null || w.dry != null).map((w, i) => ({ sample_no: i + 1, fresh_weight_g: w.fresh, dry_weight_g: w.dry })),
});

/** An immediate hint before saving (the server checks everything again): the i18n key of the first obvious mistake, or null. */
export const draftProblem = (d: EntryDraft): string | null => {
  if (draftIsEmpty(d)) return null;
  if (d.count_total == null) return 'ntfp.entry.needTotal';
  if ((d.count_mature ?? 0) + (d.count_small ?? 0) > d.count_total) return 'ntfp.entry.partsExceed';
  if (d.weights.some((w) => w.fresh != null && w.dry != null && w.dry > w.fresh)) return 'ntfp.entry.dryExceeds';
  if (d.weights.length > 0 && d.count_total === 0) return 'ntfp.entry.weighNothing';
  return null;
};

/** A plot position's marker colour: by how many species it carries (1 = pale, more = darker). */
export const plotColour = (nSpecies: number): string => (nSpecies >= 3 ? '#1b5e20' : nSpecies === 2 ? '#43a047' : '#a5d6a7');

// ── the annual harvest plan (phase 5b) ──────────────────────────────────────────────────────────────────────────────────────────

export type WeightBasis = 'fresh' | 'dry';

/** What the user has typed for one (species, part) row. A null quantity means "no harvest planned". */
export interface HarvestEdit { quantity: number | null; basis: WeightBasis; price: number | null; unit: 'kg' | 'piece' }

export const harvestKey = (r: Pick<NtfpHarvestRow, 'species_key' | 'part_group'>): string => `${r.species_key}|${r.part_group}`;

/** The standing stock a quantity is measured against: the dry stock, or the fresh stock. */
export const stockOf = (r: Pick<NtfpHarvestRow, 'stock_fresh_kg' | 'stock_dry_kg'>, basis: WeightBasis): number | null =>
  basis === 'dry' ? r.stock_dry_kg : r.stock_fresh_kg;

const round2 = (x: number): number => Math.round(x * 100) / 100;

/** The share-of-stock helper: a share of the stock as a quantity. The guideline gives no share, so the owner chooses it. */
export const quantityFromShare = (stock: number | null, pct: number | null): number | null =>
  stock == null || pct == null || pct < 0 ? null : round2((stock * pct) / 100);

export const shareFromQuantity = (stock: number | null, qty: number | null): number | null =>
  stock == null || stock <= 0 || qty == null ? null : round2((qty / stock) * 100);

/** A quantity above the whole standing stock (kg rows only) is a typing error: nobody harvests more in a year than is there. */
export const harvestProblem = (stock: number | null, qty: number | null, unit: 'kg' | 'piece'): 'exceedsStock' | 'negative' | null => {
  if (qty == null) return null;
  if (qty < 0) return 'negative';
  return unit === 'kg' && stock != null && qty > stock ? 'exceedsStock' : null;
};

export const valueOf = (qty: number | null, price: number | null): number | null => (qty == null || price == null ? null : round2(qty * price));

/** The starting edit of a row: the saved plan, or nothing planned with the dry basis when dry weights exist (else fresh). */
export function initialEdit(r: NtfpHarvestRow): HarvestEdit {
  if (r.plan) return { quantity: r.plan.annual_quantity, basis: r.plan.weight_basis, price: r.plan.price_override, unit: r.plan.unit };
  return { quantity: null, basis: r.stock_dry_kg != null ? 'dry' : 'fresh', price: null, unit: r.price?.unit === 'piece' ? 'piece' : 'kg' };
}

/** The rows to send: only those with a quantity above zero. An unplanned row is simply not in the plan. */
export function harvestPayload(rows: NtfpHarvestRow[], edits: Record<string, HarvestEdit>) {
  return rows.flatMap((r) => {
    const e = edits[harvestKey(r)];
    if (!e || e.quantity == null || e.quantity <= 0) return [];
    return [{ species_key: r.species_key, part_group: r.part_group, annual_quantity: e.quantity, unit: e.unit, weight_basis: e.basis, price_override: e.price }];
  });
}

/** Whether the edits differ from what is saved (what the Save button waits for). */
export function harvestDirty(rows: NtfpHarvestRow[], edits: Record<string, HarvestEdit>): boolean {
  return rows.some((r) => {
    const a = initialEdit(r);
    const b = edits[harvestKey(r)] ?? a;
    return (a.quantity ?? 0) !== (b.quantity ?? 0) || (b.quantity ? a.basis !== b.basis || (a.price ?? null) !== (b.price ?? null) : false);
  });
}

// ── method cards and their sources ──────────────────────────────────────────────────────────────────────────────────────────────

/** Status of a card or a value -> its message key and tag colour. Provisional and derived are never shown as if documented. */
export const STATUS_KEY: Record<string, string> = {
  documented: 'ntfp.card.statusDocumented', derived: 'ntfp.card.statusDerived', provisional: 'ntfp.card.statusProvisional', expert_confirmed: 'ntfp.card.statusConfirmed',
};
export const STATUS_COLOUR: Record<string, string> = { documented: 'green', derived: 'blue', provisional: 'orange', expert_confirmed: 'purple' };
export const cardStatusKey = (s: NtfpCardStatus | NtfpValueStatus | null | undefined): string => (s ? STATUS_KEY[s] : 'ntfp.card.statusNone');
export const cardStatusColour = (s: NtfpCardStatus | NtfpValueStatus | null | undefined): string => (s ? STATUS_COLOUR[s] : 'default');

/** The card-status filter of the species list. */
export type CardFilter = 'all' | 'documented' | 'provisional' | 'expert_confirmed' | 'none';
export function matchesCardFilter(sp: Pick<NtfpSpecies, 'card_status' | 'has_method_card'>, f: CardFilter): boolean {
  if (f === 'all') return true;
  if (f === 'none') return !sp.has_method_card;
  return sp.card_status === f;
}

/** The i18n key of a card fact's field name. */
export const factFieldKey = (field: string): string => `ntfp.card.field.${field}`;

/** A number or a range as text: ``25`` ``4-25`` (the second number empty or equal gives one number). */
export function rangeText(a: number | null, b: number | null, unit?: string | null): string {
  if (a == null) return '';
  const n = (x: number) => String(Math.round(x * 10000) / 10000);
  const core = b == null || b === a ? n(a) : `${n(a)}-${n(b)}`;
  return unit ? `${core} ${unit}` : core;
}

/** What a reviewer changed in a card, as the endpoint's row: only the columns that differ from the card, and `confirmed` when nothing differs. */
export const reviewRow = (card: NtfpReviewCard, draft: NtfpReviewEdits): NtfpReviewRow => {
  const edits: Record<string, unknown> = {};
  (Object.keys(draft) as (keyof NtfpReviewEdits)[]).forEach((k) => {
    const v = draft[k];
    if (v !== undefined && v !== null && v !== card[k]) edits[k] = v;
  });
  return { species_key: card.species_key, confirmed: Object.keys(edits).length === 0, ...edits } as NtfpReviewRow;
};

/** The source line under a value: the source key and the table or page ("ANSAB2022, Annex 3, AAH table"). The year and the full title are in the tooltip. */
export const sourceLine = (v: Pick<NtfpFactValue, 'source_key' | 'source_year' | 'locator'>): string => v.source_key + (v.locator ? `, ${v.locator}` : '');

/** A quantity from the annual allowable harvest: the low and high end of ``stock x pct``; null when the stock or the figure is unknown. */
export function aahQuantity(stock: number | null, aah: Pick<NtfpAah, 'pct_min' | 'pct_max'> | null | undefined): { low: number; high: number } | null {
  if (stock == null || !aah || aah.pct_min == null) return null;
  const q = (p: number) => Math.round(((stock * p) / 100) * 100) / 100;
  return { low: q(aah.pct_min), high: q(aah.pct_max ?? aah.pct_min) };
}
