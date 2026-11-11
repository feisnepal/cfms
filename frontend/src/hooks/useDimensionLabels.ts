import { useMemo } from 'react';

export type DimensionMode = 'block' | 'compartment';

export interface DimensionLabels {
  mode: DimensionMode;
  isCompartment: boolean;

  unitLabel: string;
  unitLabelPlural: string;
  unitLabelLower: string;
  unitLabelPluralLower: string;
  unitLabelAbbr: string;

  unitLabelNp: string;
  unitLabelPluralNp: string;
  unitNameHeaderNp: string;
  unitNameHeaderPluralNp: string;
  unitNameHeaderEn: string;

  subUnitLabel: string;
  subUnitLabelPlural: string;
  subUnitLabelNp: string;
  subUnitLabelPluralNp: string;
  subUnitNameHeaderNp: string;

  labelForLevel: (level: number) => string;
  labelForLevelNp: (level: number) => string;

  unitWiseNp: (suffix: string) => string;
  unitWiseNpShort: string;
  perUnitNp: string;
  unitTotalNp: string;
  allUnitsNp: string;

  current: string;
  other: string;
}

interface UseDimensionLabelsOptions {
  hasCompartments?: boolean;
}

// FS-4a.1: block mode used to read "Block" at every depth, including a sub-block,
// because only the compartment side branched on level -- an easy miss while sub-blocks
// did not exist. Mirrors app.services.forest_units.labels.
const LABEL_FOR_LEVEL_BLOCK = (level: number) =>
  level >= 2 ? 'Sub-Block' : 'Block';
const LABEL_FOR_LEVEL_BLOCK_NP = (level: number) =>
  level >= 2 ? 'उप-ब्लक' : 'ब्लक';

const LABEL_FOR_LEVEL_COMPARTMENT = (level: number) =>
  level >= 2 ? 'Sub-Compartment' : 'Compartment';
const LABEL_FOR_LEVEL_COMPARTMENT_NP = (level: number) =>
  level >= 2 ? 'उप-कम्पार्टमेन्ट' : 'कम्पार्टमेन्ट';

const BLOCK_LABELS: DimensionLabels = {
  mode: 'block',
  isCompartment: false,
  current: 'Block',
  other: 'Compartment',
  unitLabel: 'Block',
  unitLabelPlural: 'Blocks',
  unitLabelLower: 'block',
  unitLabelPluralLower: 'blocks',
  unitLabelAbbr: 'Blk',
  unitLabelNp: 'ब्लक',
  unitLabelPluralNp: 'ब्लकहरू',
  unitNameHeaderNp: 'ब्लकको नाम',
  unitNameHeaderPluralNp: 'ब्लकको नामहरू',
  unitNameHeaderEn: 'Block Name',
  subUnitLabel: 'Sub-Block',
  subUnitLabelPlural: 'Sub-Blocks',
  subUnitLabelNp: 'उप-ब्लक',
  subUnitLabelPluralNp: 'उप-ब्लकहरू',
  subUnitNameHeaderNp: 'उप-ब्लकको नाम',
  labelForLevel: LABEL_FOR_LEVEL_BLOCK,
  labelForLevelNp: LABEL_FOR_LEVEL_BLOCK_NP,
  unitWiseNp: (suffix: string) => `ब्लक अनुसार ${suffix}`,
  unitWiseNpShort: 'ब्लक अनुसार',
  perUnitNp: 'प्रति-ब्लक',
  unitTotalNp: 'ब्लक जम्मा',
  allUnitsNp: 'सबै ब्लकहरू',
};

const COMPARTMENT_LABELS: DimensionLabels = {
  mode: 'compartment',
  isCompartment: true,
  current: 'Compartment',
  other: 'Block',
  unitLabel: 'Compartment',
  unitLabelPlural: 'Compartments',
  unitLabelLower: 'compartment',
  unitLabelPluralLower: 'compartments',
  unitLabelAbbr: 'Cmp',
  unitLabelNp: 'कम्पार्टमेन्ट',
  unitLabelPluralNp: 'कम्पार्टमेन्टहरू',
  unitNameHeaderNp: 'कम्पार्टमेन्टको नाम',
  unitNameHeaderPluralNp: 'कम्पार्टमेन्टको नामहरू',
  unitNameHeaderEn: 'Compartment Name',
  subUnitLabel: 'Sub-Compartment',
  subUnitLabelPlural: 'Sub-Compartments',
  subUnitLabelNp: 'उप-कम्पार्टमेन्ट',
  subUnitLabelPluralNp: 'उप-कम्पार्टमेन्टहरू',
  subUnitNameHeaderNp: 'उप-कम्पार्टमेन्टको नाम',
  labelForLevel: LABEL_FOR_LEVEL_COMPARTMENT,
  labelForLevelNp: LABEL_FOR_LEVEL_COMPARTMENT_NP,
  unitWiseNp: (suffix: string) => `कम्पार्टमेन्ट अनुसार ${suffix}`,
  unitWiseNpShort: 'कम्पार्टमेन्ट अनुसार',
  perUnitNp: 'प्रति-कम्पार्टमेन्ट',
  unitTotalNp: 'कम्पार्टमेन्ट जम्मा',
  allUnitsNp: 'सबै कम्पार्टमेन्टहरू',
};

export function useDimensionLabels(
  options: UseDimensionLabelsOptions
): DimensionLabels {
  return useMemo(() => {
    return options.hasCompartments ? COMPARTMENT_LABELS : BLOCK_LABELS;
  }, [options.hasCompartments]);
}

export function useDimensionLabelsFromCalculation(
  calculation: { result_data?: Record<string, unknown> | null } | null | undefined
): DimensionLabels {
  const hasCompartments = hasCompartmentsFromResultData(calculation?.result_data);
  return useDimensionLabels({ hasCompartments });
}

/**
 * The branch of the structure rule a forest uses, as the API reports it (`stream` on the block list and
 * compartment-tree responses - backend `forest_units.mode.forest_stream`). `undecided` = a boundary with no units yet.
 */
export type ForestStream = 'block' | 'compartment' | 'undecided';

/**
 * Whether the forest is a compartment forest, preferring the API's `stream` and falling back to `fallback`
 * (the old `result_data` rule) when the response carries none. New code should read `stream`; the fallback keeps
 * older responses and cached payloads working.
 */
export function hasCompartmentsFromStream(
  stream: ForestStream | string | null | undefined,
  fallback: boolean
): boolean {
  if (stream === 'compartment') return true;
  if (stream === 'block' || stream === 'undecided') return false;
  return fallback;
}

export function hasCompartmentsFromResultData(
  resultData: Record<string, unknown> | null | undefined
): boolean {
  if (!resultData) return false;
  const compartments = resultData['compartments'];
  if (Array.isArray(compartments) && compartments.length > 0) return true;
  return resultData['polygon_type'] === 'compartment';
}

/**
 * Which per-unit analysis array to read from `result_data` — `'compartments'`
 * when a block was divided into compartments (a populated array), else
 * `'blocks'`. Mirrors the backend `PolygonSource.for_result_data`, so the
 * Analysis view shows the same units the analyser ran on. Deliberately stricter
 * than `hasCompartmentsFromResultData`: it requires the array to be non-empty,
 * not just `polygon_type === 'compartment'`.
 */
export function analysisUnitKey(
  resultData: Record<string, unknown> | null | undefined
): 'blocks' | 'compartments' {
  const compartments = resultData?.['compartments'];
  return Array.isArray(compartments) && compartments.length > 0 ? 'compartments' : 'blocks';
}
