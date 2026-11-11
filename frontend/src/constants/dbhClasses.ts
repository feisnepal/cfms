/**
 * DBH class presentation.
 *
 * DBH_SSOT_PLAN P3 (owner's decision, 2026-09-27)
 * ------------------------------------------------
 * This file used to hold three hardcoded class lists -- `GUIDELINE_2061`,
 * `GUIDELINE_SIMPLE` and `DFO_EXPORT` -- plus two colour maps that embedded a
 * fourth and fifth copy of the same keys, ranges and stand types, plus a
 * `shortLabels` table inside `formatDetailedLabel` that was a sixth copy of the
 * names. None of that is now here.
 *
 * **Structure comes from the API; words come from the i18n bundle.** That split
 * was the owner's explicit call, and it is the right one because the two halves
 * have different owners:
 *
 *   * `key`, `lower`, `upper` and `stand_type` decide which class a stem falls
 *     into. Duplicating them in the frontend is how a per-hectare figure ends up
 *     computed against boundaries the database does not use. These come from
 *     `GET /api/dbh-classes/systems/{name}` via `useDbhClassConfig`, and nothing
 *     in this file may restate them.
 *   * The *words* are the super-admin's. This application has a translations
 *     editor and a Nepali-first i18n programme, and an editor there cannot write
 *     to the database. So the label stays in the bundle, and what is kept here is
 *     a key -> i18n-key **lookup**, which is a link and not a copy of the class
 *     list.
 *
 * Consequence worth stating: adding a class no longer means editing this file.
 * It means adding it to `dbh_class_systems`; this map only needs a new entry if
 * the new class needs a new word, and a class with no entry falls back to the
 * label the API sends.
 */

export interface DbhClassDef {
  key: string;
  lower: number;
  upper: number | null;
  labelEn: string;
  labelNp: string;
  /** i18n key for the label, when one exists. See the note above. */
  labelKey?: string;
  standType?: string | null;
}

export interface DbhClassConfig extends DbhClassDef {
  fillColor?: string;
  color?: string;
  radius?: number;
}

/**
 * Class key -> i18n key.
 *
 * A lookup, deliberately not a list: the class *set* is the database's, and a map
 * cannot disagree with it about which classes exist. Eight of the twenty-odd
 * classes across the five systems have no entry, and that is correct rather than
 * an omission - `guideline_simple`, `harvesting_cfmg` and `validation` are
 * rendered from the label the API sends, and only the eight `guideline_2061`
 * classes - the ones the Results tables show - need a curated translation.
 */
export const DBH_CLASS_LABEL_KEYS: Record<string, string> = {
  '0_4': 'dbhClass.seedling',
  '4_10': 'dbhClass.sapling',
  '10_20': 'dbhClass.smallPole',
  '20_30': 'dbhClass.largePole',
  '30_40': 'dbhClass.smallTree',
  '40_50': 'dbhClass.mediumTree',
  '50_60': 'dbhClass.largeTree',
  '60_plus': 'dbhClass.veryLargeTree',
};

/** The system the Results tables show, and the one the DBH rules are written in. */
export const DEFAULT_SYSTEM = 'guideline_2061';
