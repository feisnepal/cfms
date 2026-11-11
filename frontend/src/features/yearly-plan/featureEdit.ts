/**
 * Editing a drawn place from the activity-features table (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.6 / P2):
 * its name, the plan years it applies to, and its map symbol.
 *
 * One saved edit is one undo entry. The edit is saved first and only then put on the undo stack, so a
 * refused edit never leaves an entry that would "undo" something that never happened. When the server says a
 * chosen year is not planned for the activity, the person is asked whether to plan it too — nothing is
 * planned behind their back — and the retry is what is remembered.
 */
import { ActivityFeatureApiError, YEAR_NOT_PLANNED } from '../../lib/activityFeaturePayload';
import { featureYears } from '../../lib/activityFeatureLabel';
import { createAttributeEditOperation } from '../../lib/operationFactories';
import type { GeometryOperation } from '../../lib/editOperations';

export type FeatureEditColumn = 'name' | 'years' | 'kind';
export type FeatureEditResult = 'saved' | 'declined' | 'failed' | 'ignored';

export interface FeatureEditDeps {
  calcId: string;
  /** PATCH the feature: `payload.properties` carries what changed. */
  update: (featureId: string, payload: { properties: Record<string, unknown> }) => Promise<unknown>;
  /** Ask "plan these years too?"; resolves true to go ahead. */
  confirmPlanYears: (activityName: string, years: number[]) => Promise<boolean>;
  /** Remember a saved edit for Ctrl+Z / Ctrl+Shift+Z. */
  pushOp: (op: GeometryOperation) => void;
  /** The table and map should re-read the layer (after a save, and after a refused edit). */
  refresh: () => void;
  /** Tell the person, in plain words, that the edit could not be saved. */
  report: (error: unknown) => void;
  userId?: string;
}

const LABELS: Record<FeatureEditColumn, string> = { name: 'Edit name', years: 'Edit years', kind: 'Edit symbol' };

const isEditColumn = (key: string): key is FeatureEditColumn => key === 'name' || key === 'years' || key === 'kind';

/** "1,2, 3" → [1, 2, 3], sorted, unique, only real plan years. */
export function parseYears(value: string): number[] {
  const seen = new Set<number>();
  value
    .split(',')
    .map((part) => Number(part.trim()))
    .forEach((n) => {
      if (Number.isInteger(n) && n >= 1 && n <= 10) seen.add(n);
    });
  return [...seen].sort((a, b) => a - b);
}

/** What was there before, in the same shape as the new value, so undo can put it back. */
function previousProperties(feature: GeoJSON.Feature, column: FeatureEditColumn): Record<string, unknown> {
  const props = feature.properties ?? {};
  if (column === 'years') return { years: featureYears(props) };
  if (column === 'kind') return { kind: typeof props.kind === 'string' ? props.kind : '' };
  return { name: typeof props.name === 'string' ? props.name : '' };
}

function nextProperties(column: FeatureEditColumn, value: string): Record<string, unknown> | null {
  if (column === 'years') {
    const years = parseYears(value);
    return years.length > 0 ? { years } : null; // a place always belongs to at least one year
  }
  if (column === 'kind') return { kind: value };
  return { name: value.trim() };
}

/** Save one edit of one cell. Never throws; the outcome says what happened. */
export async function saveActivityFeatureEdit(
  feature: GeoJSON.Feature,
  column: string,
  value: string,
  deps: FeatureEditDeps,
): Promise<FeatureEditResult> {
  if (!isEditColumn(column)) return 'ignored';
  const rawId = feature.properties?.id ?? (feature as { id?: unknown }).id;
  if (rawId === undefined || rawId === null || rawId === '') return 'ignored';
  const featureId = String(rawId);
  const next = nextProperties(column, value);
  if (!next) return 'ignored';

  const previous = previousProperties(feature, column);
  const unchanged = JSON.stringify(previous) === JSON.stringify(next);
  if (unchanged) return 'ignored';

  const remember = (properties: Record<string, unknown>) =>
    deps.pushOp(
      createAttributeEditOperation(
        deps.calcId,
        'activity_features',
        featureId,
        LABELS[column],
        { properties: previous },
        { properties },
        deps.userId ?? 'user',
      ),
    );

  try {
    await deps.update(featureId, { properties: next });
    remember(next);
    deps.refresh();
    return 'saved';
  } catch (error) {
    if (column === 'years' && error instanceof ActivityFeatureApiError && error.code === YEAR_NOT_PLANNED) {
      const activity = String(feature.properties?.activity_name ?? '');
      const go = await deps.confirmPlanYears(activity, error.years);
      if (!go) {
        deps.refresh(); // the table shows the saved years again
        return 'declined';
      }
      const withPlan = { ...next, plan_years: true };
      try {
        await deps.update(featureId, { properties: withPlan });
        remember(withPlan);
        deps.refresh();
        return 'saved';
      } catch (retryError) {
        deps.report(retryError);
        deps.refresh();
        return 'failed';
      }
    }
    deps.report(error);
    deps.refresh();
    return 'failed';
  }
}
