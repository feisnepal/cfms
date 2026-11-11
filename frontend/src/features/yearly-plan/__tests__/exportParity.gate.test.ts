/**
 * The two screens that export the yearly plan — the map workspace and the yearly-activities page — must
 * produce the same file (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.3). They do because both call the ONE server
 * exporter through the shared menu; this gate fails the build if either screen grows a CSV builder of its own
 * again, or drops the shared menu.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const src = (rel: string) => readFileSync(resolve(__dirname, '../../..', rel), 'utf8');

const SCREENS: Array<[string, string]> = [
  ['the map workspace', 'components/MapWorkspace.tsx'],
  ['the yearly-activities page', 'components/YearlyActivities/YearlyActivitiesPage.tsx'],
];

describe('one exporter for both screens', () => {
  it.each(SCREENS)('%s uses the shared Export menu', (_name, file) => {
    expect(src(file)).toContain("features/yearly-plan/PlanExportMenu");
  });

  it.each(SCREENS)('%s builds no CSV of its own', (_name, file) => {
    const text = src(file);
    expect(text).not.toMatch(/text\/csv/);
    expect(text).not.toMatch(/csvContent/);
    expect(text).not.toMatch(/handleExportCSV/);
  });

  it('the shared menu reaches the server only through the shared downloader', () => {
    const menu = src('features/yearly-plan/PlanExportMenu.tsx');
    const files = src('features/yearly-plan/planExport.ts');
    expect(menu).toContain("from './planExport'");
    expect(files).toContain("'yearly-plan'");
    expect(files).toContain("'activity-features'");
    expect(files).toContain("'/export'");
    expect(files).not.toMatch(/text\/csv/);
  });

  it('the workspace\'s own table export is named as the current view, so two files never differ silently', () => {
    const table = src('components/AttributeTable.tsx');
    expect(table).toContain('_view.csv');
    expect(table).toContain('_view.geojson');
  });
});
