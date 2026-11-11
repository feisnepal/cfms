import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

/**
 * Guard against the gap Phase 4i closed.
 *
 * Batches 4a-4f were verified with a grep that looked at JSX text nodes and
 * simple string props. That pattern set is blind to four shapes which turn out
 * to be common in this codebase, and 56 user-facing strings shipped English-only
 * because of it:
 *
 *   <Tag color="green">Auto</Tag>          text inside a component's children
 *   okText={cond ? 'Approve' : 'Reject'}   ternary in a prop
 *   detail || 'Failed to save'             error fallback
 *   title={`Copy ${name}`}                 template-literal prop
 *
 * This test applies the widened pattern set to every source file and fails on
 * anything not explicitly allowed below. A new hardcoded string cannot reach
 * main without either a translation key or an entry in ALLOWED, which forces
 * the "is this chrome or data?" decision to be made and recorded.
 */

const SRC = join(__dirname, '..', '..');
const SCAN_DIRS = ['components', 'pages'];

/**
 * Files the Nepali-first plan puts out of scope (rule 9: legacy flows).
 * `pages/CalculationDetail.tsx` and its orphaned Compartment module / MapEditor
 * were deleted in Single Workspace A5b/A5c cleanup; what remains here is the
 * analysis + area-accounting bodies that were ported into the tabbed shell.
 */
const LEGACY_PREFIXES = [
  // Verbatim extraction of the deleted CalculationDetail's analysis body
  // (Single Workspace A2): the detailed block-wise tables, geometry warning and
  // A5 boundary map, still rendered by the tabbed shell. Same rule-9 deferral —
  // Nepali conversion of this legacy content is tracked separately.
  'components/calculation/AnalysisTab.tsx',
  // Ported from the same deleted page (Single Workspace A5c): the sub-areas
  // Table 1–3 area-accounting block, already Nepali-first for Tables 2/3.
  // Same rule-9 deferral for the remaining English chrome.
  'components/calculation/SubAreaTablesTab.tsx',
  // Superseded by BlockSplitterPro, which MapCreationWizard actually imports.
  'components/MapCreation/BlockSplitter.tsx',
  'components/MapCreation/BlockSplitterNew.tsx',
];

/**
 * Literals that are data rather than UI copy, keyed by the file that holds
 * them. Each is a deliberate non-conversion:
 *
 *   sort comparands            `roleOrder.indexOf(a.role || 'Associate')`
 *   lookup keys                `LABEL_KEY[x.remark || 'Normal']` - resolved via t()
 *   grouping keys              stable map keys whose *display* resolves separately
 *   persisted names            written to the DB; translating changes stored data
 *   filename components        `(forestName || 'Forest').replace(...)`
 *   OP variable tokens         `{{section:x}}` - the plan's own syntax
 *   generated-output strings   drawn into an exported PNG (Phase 5 owns these)
 */
const ALLOWED: Record<string, string[]> = {
  'components/AttributeTable.tsx': ['Forest Boundary', 'Unnamed'],
  'components/BiodiversityTab.tsx': ['Other'],
  'components/DetailDescription/SectionCard.tsx': [
    '{{section:${sectionKey}:full}}', '{{section:${sectionKey}}}',
  ],
  'components/LayerStyleDialog.tsx': [
    "${t('layerPanel.styleFillColorAria')} ${c}",
    "${t('layerPanel.styleStrokeColorAria')} ${c}",
  ],
  'components/MapCreation/SubAreaManager.tsx': ['Sub-area'],
  'components/MapsTab.tsx': ['Forest'],
  // The workspace shows the forest label using the DB name, defaulting to this
  // literal fallback when the row's name is empty — same pattern as MapsTab.
  'components/MapWorkspace.tsx': ['Forest'],
  'components/SpeciesTable.tsx': ['Associate', 'Common', 'Medium'],
  'components/TreeMappingTab.tsx': ['Normal'],
  'components/UserGroup/MapExportPanel.tsx': ['Forest', 'User Group Map'],
  'components/YearlyActivities/YearlyActivitiesPage.tsx': ['None', 'Uncategorized', 'Unnamed'],
  // Both halves of the same audit note written to the translations history.
  'pages/AdminTranslationsPage.tsx': ['Marked reviewed', 'Flagged for review'],
  'components/ExportButton.tsx': ['Forest'],
};

const PATTERNS: Array<[string, RegExp]> = [
  ['tag-child', /<(?:Tag|Text|Title|Button|Option|Badge)\b[^>]*>\s*([A-Z][A-Za-z0-9 ./%()&+-]{2,60})\s*</g],
  ['ternary', /\?\s*'([A-Z][^']{2,70})'\s*:\s*'([A-Z][^']{2,70})'/g],
  ['or-fallback', /\|\|\s*'([A-Z][^']{3,90})'/g],
  ['tpl-prop', /(?:title|label|placeholder|message|okText|tip)=\{`([^`]*[A-Za-z]{3}[^`]*)`\}/g],
  ['jsx-text', />\s*([A-Z][a-z][^<>{}]{3,80})\s*</g],
];

/** Comparisons, css, urls and known non-copy tokens. */
const IGNORE_LINE = new RegExp(
  [
    'type ===', "=== '", "!== '", 'className', 'http', 'Noto Sans', 'Segoe UI', 'EPSG',
    // `Promise<Foo>` in a type annotation looks like a JSX text node to the
    // jsx-text pattern; a real text node never sits inside an arrow signature.
    'Promise<',
    "'(Polygon|MultiPolygon|Point|LineString|Feature|FeatureCollection|Enter|Escape|Tab)'",
  ].join('|'),
);

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === '__tests__') continue;
      out.push(...walk(full));
    } else if (entry.endsWith('.tsx')) {
      out.push(full);
    }
  }
  return out;
}

describe('no hardcoded user-facing strings (Phase 4i regression gate)', () => {
  it('finds no unkeyed literal outside the documented allowlist', () => {
    const findings: string[] = [];

    for (const dir of SCAN_DIRS) {
      for (const file of walk(join(SRC, dir))) {
        const rel = relative(SRC, file).split(sep).join('/');
        if (LEGACY_PREFIXES.some((p) => rel === p || rel.startsWith(p))) continue;
        const allowed = ALLOWED[rel] ?? [];
        const lines = readFileSync(file, 'utf-8').split('\n');

        lines.forEach((line, i) => {
          if (IGNORE_LINE.test(line)) return;
          for (const [tag, rx] of PATTERNS) {
            rx.lastIndex = 0;
            let m: RegExpExecArray | null;
            while ((m = rx.exec(line)) !== null) {
              for (const group of m.slice(1)) {
                if (!group) continue;
                const value = group.trim();
                // A template whose only words are interpolations carries no
                // copy of its own: `${label} (${labelNp})` is a layout, not a
                // string to translate.
                if (!/[A-Za-z]{3}/.test(value.replace(/\$\{[^}]*\}/g, ''))) continue;
                if (/^[A-Z_0-9]+$/.test(value)) continue;
                if (allowed.includes(value)) continue;
                findings.push(`${rel}:${i + 1} [${tag}] ${value}`);
                break;
              }
            }
          }
        });
      }
    }

    expect(findings).toEqual([]);
  });
});
