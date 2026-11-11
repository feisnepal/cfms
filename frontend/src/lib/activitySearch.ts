/**
 * Finding an activity in the master list (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.11).
 *
 * The list is tiny (136 rows), so it is searched in the browser on every keystroke: no database
 * extension, still usable on a weak connection after the first load. Everything here is pure and
 * deterministic — the same typing always gives the same order — and unit-tested against real names.
 *
 * What a person can type:
 *   - any part of a Nepali name, in any order, the start of a word being enough;
 *   - the usual Nepali spelling variants (ब/व, ि/ी, ु/ू, श/ष/स, the nasals, ZWJ …) — see
 *     `normalizeActivityText`;
 *   - English or romanised Nepali (`name_en` + `search_terms`, seeded per activity);
 *   - a one-letter typo in a word of four letters or more.
 */

/** One master-list row as the picker needs it. */
export interface CatalogueActivity {
  id: number;
  /** The Nepali name — always the primary label. */
  name: string;
  nameEn: string | null;
  searchTerms: string | null;
  programme: string;
  project: string;
  unit: string;
  requiresMap: boolean;
  mapKind: string | null;
  /** the shape this activity is drawn as when it is not its kind's own (the shape belongs to the activity, not to its unit) */
  mapGeom?: 'point' | 'line' | 'polygon' | null;
  description: string | null;
}

/** The row exactly as `GET /yearly-activities/potential-activities` returns it (loosely typed by design). */
export interface RawPotentialActivity {
  id: number;
  activity?: string | null;
  activities?: string | null;
  program?: string | null;
  progarms?: string | null;
  project_name?: string | null;
  unit?: string | null;
  requires_map?: boolean | null;
  map_kind?: string | null;
  map_geom?: string | null;
  name_en?: string | null;
  search_terms?: string | null;
  description?: string | null;
}

export function toCatalogueActivity(raw: RawPotentialActivity): CatalogueActivity {
  return {
    id: Number(raw.id),
    name: (raw.activity ?? raw.activities ?? '').trim(),
    nameEn: raw.name_en?.trim() || null,
    searchTerms: raw.search_terms?.trim() || null,
    programme: (raw.program ?? raw.progarms ?? '').trim(),
    project: (raw.project_name ?? '').trim(),
    unit: (raw.unit ?? '').trim(),
    requiresMap: Boolean(raw.requires_map),
    mapKind: raw.map_kind || null,
    mapGeom: raw.map_geom === 'point' || raw.map_geom === 'line' || raw.map_geom === 'polygon' ? raw.map_geom : null,
    description: raw.description?.trim() || null,
  };
}

// ---------------------------------------------------------------------------------------------
// Spelling rules — one function, so the index and the query can never disagree.
// ---------------------------------------------------------------------------------------------

const DEVANAGARI_DIGITS = '०१२३४५६७८९';

/**
 * Text as it is compared, never as it is shown.
 *
 *   ब → व · ी → ि · ू → ु · ई → इ · ऊ → उ · श, ष → स · ँ → ं · a nasal + halant before a consonant
 *   (ङ् ञ् ण् न् म्) → ं · visarga and nukta dropped · zero-width joiners dropped · Devanagari digits →
 *   0–9 · Latin lower-cased · every run of punctuation / space → one space.
 *
 * So `वन सिमांकन`, `बन सिमाङ्कन` and `बन सिमांकन` are all the same text.
 */
export function normalizeActivityText(input: string | null | undefined): string {
  if (!input) return '';
  let s = input.normalize('NFC');
  s = s.replace(/[\u200B-\u200D\u2060\u00AD\uFEFF]/g, ''); // zero-width space / joiners, soft hyphen, BOM
  s = s.replace(/[०-९]/g, (d) => String(DEVANAGARI_DIGITS.indexOf(d)));
  s = s.toLowerCase();
  s = s
    .replace(/ब/g, 'व')
    .replace(/ी/g, 'ि')
    .replace(/ू/g, 'ु')
    .replace(/ई/g, 'इ')
    .replace(/ऊ/g, 'उ')
    .replace(/[शष]/g, 'स')
    .replace(/[ः़]/g, '')
    .replace(/[ङञणनम]्(?=[क-ह])/g, 'ं')
    .replace(/ँ/g, 'ं');
  // everything that is not a letter, digit or combining mark is a separator
  s = s.replace(/[^\p{L}\p{N}\p{M}]+/gu, ' ');
  return s.replace(/\s+/g, ' ').trim();
}

/** The words of a text, normalised. */
export function wordsOf(input: string | null | undefined): string[] {
  const n = normalizeActivityText(input);
  return n ? n.split(' ') : [];
}

// ---------------------------------------------------------------------------------------------
// Typo tolerance
// ---------------------------------------------------------------------------------------------

/** Fewest letters in a word before one typo is tolerated. */
export const FUZZY_MIN_LETTERS = 4;

/** Is `a` at most one edit (substitution, insertion, deletion or swap of neighbours) from `b`? */
export function withinOneEdit(a: string, b: string): boolean {
  if (a === b) return true;
  const la = a.length;
  const lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  let i = 0;
  while (i < la && i < lb && a[i] === b[i]) i += 1;
  if (la === lb) {
    if (a.slice(i + 1) === b.slice(i + 1)) return true; // one substitution
    return i + 1 < la && a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2); // swap
  }
  return la > lb ? a.slice(i + 1) === b.slice(i) : b.slice(i + 1) === a.slice(i);
}

/**
 * A typed word that is one typo away from the START of an indexed word (so half-typed words still work).
 * Compared against the indexed word cut to one letter shorter, equal and one longer than the query.
 */
export function fuzzyPrefix(query: string, word: string): boolean {
  if (query.length < FUZZY_MIN_LETTERS || word.length < 3) return false;
  for (let len = query.length - 1; len <= query.length + 1; len += 1) {
    if (withinOneEdit(query, word.slice(0, len))) return true;
  }
  return false;
}

/** Plain Levenshtein distance (only used for the "closest suggestions" list, on short words). */
function levenshtein(a: string, b: string): number {
  const prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i += 1) {
    let diag = prev[0];
    prev[0] = i;
    for (let j = 1; j <= b.length; j += 1) {
      const above = prev[j];
      prev[j] = Math.min(prev[j] + 1, prev[j - 1] + 1, diag + (a[i - 1] === b[j - 1] ? 0 : 1));
      diag = above;
    }
  }
  return prev[b.length];
}

// ---------------------------------------------------------------------------------------------
// Index + ranking
// ---------------------------------------------------------------------------------------------

interface IndexedActivity {
  activity: CatalogueActivity;
  nameNorm: string;
  enNorm: string;
  nameWords: string[];
  enWords: string[];
  termWords: string[];
  groupWords: string[];
  /** Position of the activity's programme in the master list (first appearance), for stable ties. */
  programmeOrder: number;
}

export interface ActivityIndex {
  items: IndexedActivity[];
  /** Programmes in master-list order. */
  programmes: string[];
}

export function buildActivityIndex(activities: CatalogueActivity[]): ActivityIndex {
  const ordered = [...activities].sort((a, b) => a.id - b.id);
  const programmes: string[] = [];
  ordered.forEach((a) => {
    if (!programmes.includes(a.programme)) programmes.push(a.programme);
  });
  const items = ordered.map<IndexedActivity>((activity) => ({
    activity,
    nameNorm: normalizeActivityText(activity.name),
    enNorm: normalizeActivityText(activity.nameEn),
    nameWords: wordsOf(activity.name),
    enWords: wordsOf(activity.nameEn),
    termWords: wordsOf(activity.searchTerms),
    groupWords: [...wordsOf(activity.programme), ...wordsOf(activity.project)],
    programmeOrder: programmes.indexOf(activity.programme),
  }));
  return { items, programmes };
}

// Score tiers: exact name → start of a name word → English / search words → programme or project → near-match.
const S = {
  NAME_EXACT_WORD: 100,
  NAME_PREFIX: 90,
  EN_EXACT: 65,
  EN_PREFIX: 55,
  GROUP_EXACT: 35,
  GROUP_PREFIX: 30,
  FUZZY_NAME: 25,
  FUZZY_EN: 20,
  FUZZY_GROUP: 10,
  WHOLE_NAME: 1000,
  WHOLE_EN: 900,
  NAME_STARTS_WITH_QUERY: 200,
  NAME_CONTAINS_QUERY: 50,
} as const;

function bestWordScore(q: string, it: IndexedActivity): number {
  let best = 0;
  const note = (n: number) => {
    if (n > best) best = n;
  };
  for (const w of it.nameWords) {
    if (w === q) note(S.NAME_EXACT_WORD);
    else if (w.startsWith(q)) note(S.NAME_PREFIX);
  }
  if (best >= S.NAME_PREFIX) return best;
  for (const w of it.enWords) {
    if (w === q) note(S.EN_EXACT);
    else if (w.startsWith(q)) note(S.EN_PREFIX);
  }
  for (const w of it.termWords) {
    if (w === q) note(S.EN_EXACT);
    else if (w.startsWith(q)) note(S.EN_PREFIX);
  }
  for (const w of it.groupWords) {
    if (w === q) note(S.GROUP_EXACT);
    else if (w.startsWith(q)) note(S.GROUP_PREFIX);
  }
  if (best > 0) return best;
  // a typo: only when nothing matched cleanly
  if (q.length >= FUZZY_MIN_LETTERS) {
    if (it.nameWords.some((w) => fuzzyPrefix(q, w))) return S.FUZZY_NAME;
    if (it.enWords.some((w) => fuzzyPrefix(q, w)) || it.termWords.some((w) => fuzzyPrefix(q, w))) return S.FUZZY_EN;
    if (it.groupWords.some((w) => fuzzyPrefix(q, w))) return S.FUZZY_GROUP;
  }
  return 0;
}

export interface SearchHit {
  activity: CatalogueActivity;
  score: number;
  programmeOrder: number;
}

/** A word scored at or below this only matched through a typo. */
const FUZZY_CEILING = 25;

const byRank = (a: SearchHit, b: SearchHit) =>
  b.score - a.score || a.programmeOrder - b.programmeOrder || a.activity.id - b.activity.id;

/**
 * Every activity that matches ALL typed words (in any order), best first. An empty query returns the
 * whole list in master-list order. Deterministic: score, then programme order, then id.
 */
export function searchActivities(index: ActivityIndex, query: string): SearchHit[] {
  const qWords = wordsOf(query);
  if (qWords.length === 0) {
    return index.items.map((it) => ({ activity: it.activity, score: 0, programmeOrder: it.programmeOrder }));
  }
  const qNorm = qWords.join(' ');
  const hits: SearchHit[] = [];
  const viaTypo = new Set<CatalogueActivity>();
  for (const it of index.items) {
    let total = 0;
    let all = true;
    let typo = false;
    for (const q of qWords) {
      const s = bestWordScore(q, it);
      if (s === 0) {
        all = false;
        break;
      }
      if (s <= FUZZY_CEILING) typo = true;
      total += s;
    }
    if (!all) continue;
    if (typo) viaTypo.add(it.activity);
    if (it.nameNorm === qNorm) total += S.WHOLE_NAME;
    else if (it.enNorm && it.enNorm === qNorm) total += S.WHOLE_EN;
    else if (it.nameNorm.startsWith(qNorm)) total += S.NAME_STARTS_WITH_QUERY;
    else if (it.nameNorm.includes(qNorm)) total += S.NAME_CONTAINS_QUERY;
    hits.push({ activity: it.activity, score: total, programmeOrder: it.programmeOrder });
  }
  // Typo tolerance is for when typing found nothing clean: "trail" must not also list every "training".
  const clean = hits.filter((h) => !viaTypo.has(h.activity));
  return (clean.length > 0 ? clean : hits).sort(byRank);
}

/**
 * The closest activities when nothing matches — the "never a dead end" list. A typed word counts by how
 * many of its letters an indexed word shares at the start; when nothing is close at all, the first
 * activities of the master list are offered. Always returns `count` items (or fewer if the list is smaller).
 */
export function suggestActivities(index: ActivityIndex, query: string, count = 3): CatalogueActivity[] {
  const qWords = wordsOf(query);
  const scored = index.items.map((it) => {
    let total = 0;
    for (const q of qWords) {
      let best = 0;
      const pools = [it.nameWords, it.enWords, it.termWords];
      for (const pool of pools) {
        for (const w of pool) {
          const span = Math.min(q.length + 1, w.length);
          const d = levenshtein(q, w.slice(0, span));
          const sim = 1 - d / Math.max(q.length, span);
          if (sim > best) best = sim;
        }
      }
      // ignore accidental near-zero similarity
      if (best >= 0.5) total += best;
    }
    return { hit: { activity: it.activity, score: Math.round(total * 1000), programmeOrder: it.programmeOrder }, total };
  });
  const close = scored.filter((s) => s.total > 0).map((s) => s.hit).sort(byRank);
  const picked = close.slice(0, count).map((h) => h.activity);
  if (picked.length < count) {
    for (const it of index.items) {
      if (picked.length >= count) break;
      if (!picked.includes(it.activity)) picked.push(it.activity);
    }
  }
  return picked;
}

// ---------------------------------------------------------------------------------------------
// Highlighting
// ---------------------------------------------------------------------------------------------

export interface Segment {
  text: string;
  hit: boolean;
}

/**
 * Splits a displayed text into segments, marking the words the typed query matched. Works on whole
 * displayed words (normalisation can change a string's length, so character offsets would be wrong).
 */
export function highlightSegments(text: string, query: string): Segment[] {
  const qWords = wordsOf(query);
  if (!text) return [];
  if (qWords.length === 0) return [{ text, hit: false }];
  const parts = text.split(/([\s/,:;()\-–।.]+)/);
  const segments: Segment[] = [];
  for (const part of parts) {
    if (part === '') continue;
    const n = normalizeActivityText(part);
    const hit = n !== '' && qWords.some((q) => n.startsWith(q) || fuzzyPrefix(q, n));
    const last = segments[segments.length - 1];
    if (last && last.hit === hit) last.text += part;
    else segments.push({ text: part, hit });
  }
  return segments;
}
