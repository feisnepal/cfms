/**
 * The two named files of the yearly plan (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.3, D10/D11), fetched from the ONE
 * server exporter so the map workspace and the yearly-activities page can never produce different files:
 *
 *   - `plan`     — the Yearly plan: every activity, also those that need no map;
 *   - `features` — the Activity features: one row per drawn place.
 *
 * Both are built from saved data on the server. Neither screen builds a CSV of its own.
 */
import { downloadFromApi } from '../../utils/download';

export type PlanExportKind = 'plan' | 'features';
export type PlanExportLang = 'en' | 'ne';

/** The exporter's URL (the same for every screen). */
export function planExportUrl(calculationId: string, kind: PlanExportKind): string {
  const part = kind === 'plan' ? 'yearly-plan' : 'activity-features';
  return '/api/yearly-activities/calculations/' + calculationId + '/' + part + '/export';
}

/** The language for headers, from the UI language. */
export function planExportLang(uiLanguage: string | undefined): PlanExportLang {
  return uiLanguage?.startsWith('ne') ? 'ne' : 'en';
}

/** Download one of the two files. The server names the file; the name below is only a fallback. */
export async function downloadPlanFile(calculationId: string, kind: PlanExportKind, lang: PlanExportLang): Promise<void> {
  await downloadFromApi(
    planExportUrl(calculationId, kind),
    kind === 'plan' ? 'yearly-plan.csv' : 'activity-features.csv',
    { format: 'csv', lang },
  );
}
