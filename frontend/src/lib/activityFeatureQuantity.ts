import i18n from 'i18next';
import { formatQuantity } from '../features/yearly-plan/format';

/**
 * The quantity column of the Activity Features table (plan §5.2). The quantity belongs to the activity's plan
 * LINE, not to a place: every place of one activity shows the same number, and when more than one place shares
 * it the cell says so ("shared ×3") instead of implying each place has a quantity of its own.
 */
export interface FeatureQuantityProps {
  plan_quantity?: unknown;
  plan_unit?: unknown;
  shared_count?: unknown;
}

const unitOf = (p: FeatureQuantityProps | null | undefined): string =>
  typeof p?.plan_unit === 'string' ? p.plan_unit.trim() : '';

/** The plan line's quantity with its unit ("4 ha"), or "-" when the server did not send one. */
export function featureQuantityText(props: FeatureQuantityProps | null | undefined): string {
  const q = Number(props?.plan_quantity);
  if (props?.plan_quantity === null || props?.plan_quantity === undefined || !Number.isFinite(q)) return '-';
  const unit = unitOf(props);
  return unit ? `${formatQuantity(q)} ${unit}` : formatQuantity(q);
}

/** How many places share the quantity; 1 (or anything unreadable) means it is not shared. */
export function featureSharedCount(props: FeatureQuantityProps | null | undefined): number {
  const n = Number(props?.shared_count);
  return Number.isInteger(n) && n > 1 ? n : 1;
}

/** "shared ×3" — empty when the quantity belongs to one place only. */
export function featureSharedTag(props: FeatureQuantityProps | null | undefined): string {
  const n = featureSharedCount(props);
  return n > 1 ? String(i18n.t('yearlyPlan.planTable.sharedTag', { n: formatQuantity(n) })) : '';
}

/** The hover text of the tag. */
export function featureSharedTitle(props: FeatureQuantityProps | null | undefined): string {
  const n = featureSharedCount(props);
  return n > 1 ? String(i18n.t('yearlyPlan.planTable.sharedTitle', { n: formatQuantity(n) })) : '';
}
