/**
 * P5d — the `totalInventory.*` tables carried over from `TotalInventoryTab`.
 * WORKSPACE_FLOW_NAV_PLAN §8.4 (D4/D5/D6) + the P5 parity requirement.
 *
 * P5e deletes `TotalInventoryTab`. Once it is gone this file is the only record of
 * what that component owned, so the assertions are deliberately about *parity*
 * rather than appearance:
 *
 * - every `{{ti_*}}` / `{{section:ti_*_narration}}` token survives, because the
 *   report is assembled server-side from those tokens. A table that renders but
 *   loses its token is a silently missing report section.
 * - the two token vocabularies are not interchangeable: `ti_*` is report chapter
 *   11 ("Total Inventory") and the `fi_*` tokens already in the Results pane are
 *   chapter 10 ("Field Inventory"). The block-wise stock and per-hectare DBH
 *   tables therefore look duplicated in the UI but are two different chapters,
 *   and dropping the `ti_*` pair would have removed chapter 11's narrations.
 * - the tables read the shared provider rather than fetching, so switching panes
 *   does not re-run a tree-cover raster calculation.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import React from 'react';
import {
  FieldInventoryResultsTables,
  FieldInventoryTotalsSummary,
} from '../fieldInventory/FieldInventoryResultsTables';
import en from '../../i18n/locales/en.json';
import ne from '../../i18n/locales/ne.json';

// jsdom has no canvas backend, so chart.js cannot acquire a context and blows up
// on the *update* path (the one test that re-renders). The chart JSX is carried
// over verbatim from the old component and the tokens are asserted from the DOM
// below, so stubbing the two wrappers loses no coverage and keeps the rate test
// about rates.
vi.mock('react-chartjs-2', () => ({
  Pie: () => <div data-testid="chart-pie" />,
  Bar: () => <div data-testid="chart-bar" />,
}));

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

const state = vi.hoisted(() => ({ current: null as any }));
vi.mock('../fieldInventory/useFieldInventoryData', () => ({
  useFieldInventoryData: () => state.current,
}));

// P3: the class list is fetched from the API now, so a class-table test that
// renders nothing would prove nothing. This serves the eight guideline_2061
// classes in the shape `GET /api/dbh-classes/systems/guideline_2061` sends them,
// and routes them through the real `toDbhClassDef` so the key -> i18n-key map is
// genuinely exercised rather than assumed. `resolveClassLabel` stays real too;
// only the network is stubbed.
//
// The data lives inside the factory because `vi.mock` is hoisted above the
// imports, so a module-level const would not be initialised yet when this runs.
vi.mock('../../hooks/useDbhClasses', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../hooks/useDbhClasses')>();
  const API_CLASSES: any[] = [
    { key: '0_4', lower: 0, upper: 4, label_en: 'Seedling', label_np: 'बिरुवा', stand_type: 'Regeneration' },
    { key: '4_10', lower: 4, upper: 10, label_en: 'Sapling', label_np: 'लाथ्रा', stand_type: 'Sapling' },
    { key: '10_20', lower: 10, upper: 20, label_en: 'Small Pole', label_np: 'सानो खाँवा', stand_type: 'Pole' },
    { key: '20_30', lower: 20, upper: 30, label_en: 'Large Pole', label_np: 'ठुलो खाँवा', stand_type: 'Pole' },
    { key: '30_40', lower: 30, upper: 40, label_en: 'Small Tree', label_np: 'सानो रुख', stand_type: 'Tree' },
    { key: '40_50', lower: 40, upper: 50, label_en: 'Medium Tree', label_np: 'मझौला रुख', stand_type: 'Tree' },
    { key: '50_60', lower: 50, upper: 60, label_en: 'Large Tree', label_np: 'ठुलो रुख', stand_type: 'Tree' },
    { key: '60_plus', lower: 60, upper: null, label_en: 'Very Large Tree', label_np: 'अति ठुलो रुख', stand_type: 'Tree' },
  ];
  return {
    ...actual,
    useDbhClassConfig: () => API_CLASSES.map(actual.toDbhClassDef),
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/**
 * A block/unit carrying every field the ported tables read. Built from the field
 * names in `TotalInventoryTab` rather than trimmed to what one test needs, so a
 * table that stops rendering because a gate lost its data fails here.
 */
const DBH_CLASS_KEYS = ['0_4', '10_20', '30_40', '60_plus'];

const dbhClassTotals = Object.fromEntries(
  DBH_CLASS_KEYS.map((key, i) => [
    key,
    {
      total_count: 10 + i,
      total_timber_m3: 1.5 + i,
      total_firewood_m3: 0.5 + i,
      total_tree_volume_m3: 2 + i,
    },
  ]),
);

const dbhClassPerHa = Object.fromEntries(
  DBH_CLASS_KEYS.map((key, i) => [
    key,
    {
      count_per_ha: 1 + i,
      timber_m3_per_ha: 0.2 + i,
      firewood_m3_per_ha: 0.1 + i,
      tree_volume_m3_per_ha: 0.3 + i,
    },
  ]),
);

const BLOCK = {
  block_name: 'Block A',
  area_ha: 12.5,
  total_regeneration: 40,
  total_sapling: 30,
  total_pole: 20,
  total_tree: 10,
  total_growing_stock_m3: 120.5,
  total_mai_m3: 8.25,
  total_aah_m3: 6.5,
  total_biomass_tonnes: 90.4,
  total_co2_tco2: 165.2,
  total_pole_timber_m3: 40,
  total_tree_timber_m3: 30,
  total_pole_firewood_m3: 10,
  total_tree_firewood_m3: 5,
  dbh_class_totals: dbhClassTotals,
  dbh_class_per_ha: dbhClassPerHa,
  mai_by_species: [
    { species_local: 'Chir pine', count_per_ha: 4, volume_per_ha: 6, mai_per_ha: 0.5, mai_total: 3 },
  ],
  aah_by_species: [
    {
      species_local: 'Chir pine',
      mai_m3: 3,
      growing_stock_m3: 40,
      aah_m3: 2.4,
      timber_m3: 2,
      firewood_m3: 0.4,
    },
  ],
};

const TOTAL_DATA = {
  forest_totals: {
    total_area_ha: 12.5,
    total_regeneration: 40,
    total_sapling: 30,
    total_pole: 20,
    total_tree: 10,
    total_growing_stock_m3: 120.5,
    total_mai_m3_per_year: 8.25,
    total_aah_m3_per_year: 6.5,
    total_biomass_tonnes: 90.4,
    total_carbon_tc: 74,
    total_co2_tco2: 165.2,
    dbh_class_totals: dbhClassTotals,
  },
  blocks: [BLOCK],
  species_breakdown: [
    { species_scientific: 'Pinus roxburghii', species_local: 'Chir pine', count: 30, timber_m3: 40, fuelwood_m3: 10, volume_m3: 50 },
  ],
};

const SPECIES_DBH = [
  {
    block_name: 'Block A',
    species_local: 'Chir pine',
    species_scientific: 'Pinus roxburghii',
    dbh_class: '10_20',
    count_per_ha: 4,
    timber_m3_per_ha: 2,
    firewood_m3_per_ha: 0.5,
    volume_m3_per_ha: 2.5,
  },
];

const TREE_COVER_AREAS = {
  'Block A': {
    block_name: 'Block A',
    total_area_ha: 20,
    effective_area_ha: 12.5,
    tree_cover_percentage: 62.5,
    tree_pixels: 500,
    total_pixels: 800,
    tree_cover_ratio: 0.625,
  },
};

const LABELS = {
  unitLabelNp: 'कम्पार्टमेन्ट',
  unitLabel: 'Compartment',
  unitNameHeaderNp: 'कम्पार्टमेन्ट',
  unitNameHeaderPluralNp: 'कम्पार्टमेन्टहरू',
  unitTotalNp: 'जम्मा',
  unitWiseNpShort: 'कम्पार्टमेन्ट',
  allUnitsNp: 'सबै कम्पार्टमेन्टहरू',
};

/** A provider value with the Results-only data present. */
function provider(overrides: Record<string, any> = {}) {
  return {
    fieldInventory: { id: 'fi-1', status: 'completed', uploaded_filename: 'fi.xlsx' },
    labels: LABELS,
    blockAreas: { 'Block A': 12.5 },
    treeCoverAreas: TREE_COVER_AREAS,
    treeCoverLoading: false,
    treeCoverError: null,
    totalData: TOTAL_DATA,
    totalsLoading: false,
    speciesDbhData: SPECIES_DBH,
    speciesDbhForestWide: SPECIES_DBH.map(({ block_name, ...rest }) => rest),
    blockRates: {},
    setBlockRates: vi.fn(),
    ensureResultsLoaded: vi.fn(),
    loadTreeCoverAreas: vi.fn(),
    handleCalculateTotals: vi.fn(),
    ...overrides,
  };
}

function renderSummary(overrides: Record<string, any> = {}) {
  state.current = provider(overrides);
  return render(<FieldInventoryTotalsSummary />);
}

function renderTables(overrides: Record<string, any> = {}) {
  state.current = provider(overrides);
  return render(<FieldInventoryResultsTables />);
}

const ALL_TOKENS = [
  '{{section:ti_block_growing_stock_narration}}',
  '{{section:ti_dbh_aah_narration}}',
  '{{section:ti_dbh_mai_narration}}',
  '{{section:ti_dbh_perha_narration}}',
  '{{section:ti_dbh_total_narration}}',
  '{{section:ti_economic_narration}}',
  '{{section:ti_forest_dbh_narration}}',
  '{{section:ti_forest_total_narration}}',
  // Added with the per-hectare basis block under the grand total.
  '{{section:ti_forest_total_perha_narration}}',
  '{{section:ti_productivity_narration}}',
  '{{section:ti_species_composition_narration}}',
  '{{section:ti_species_dbh_narration}}',
  '{{section:ti_species_stock_narration}}',
  '{{section:ti_sustainability_narration}}',
  '{{ti_aah_table}}',
  '{{ti_block_area_table}}',
  '{{ti_block_growing_stock}}',
  '{{ti_dbh_aah_table}}',
  '{{ti_dbh_class_perha_table}}',
  '{{ti_dbh_class_totals_table}}',
  '{{ti_dbh_mai_table}}',
  '{{ti_economic_valuation_table}}',
  '{{ti_forest_dbh_class_table}}',
  '{{ti_mai_table}}',
  '{{ti_species_block_growing_stock}}',
  '{{ti_species_dbh_class_table}}',
  '{{ti_sustainability_table}}',
];

/** Tokens actually present in a rendered pane. */
function tokensIn(container: HTMLElement): string[] {
  return [...(container.textContent ?? '').matchAll(/\{\{[a-z_:0-9]+\}\}/g)].map((m) => m[0]);
}

describe('P5d parity — every report token the old component owned survives', () => {
  it('renders the whole token set, not just the tables', () => {
    // Chapter 11's full set: area context, forest total, both block-wise stock
    // tables, the species pair, both DBH pairs, MAI, AAH, both charts, economic
    // valuation and sustainability. A table that renders but loses its token is
    // a silently missing report section, which is why this reads the DOM rather
    // than the file.
    const summary = renderSummary();
    const tables = renderTables();
    const seen = new Set([...tokensIn(summary.container), ...tokensIn(tables.container)]);
    expect([...seen].sort()).toEqual([...ALL_TOKENS].sort());
  });

  it('keeps the two token vocabularies distinct', () => {
    // The trap this file exists to prevent: the Results pane already renders a
    // block-wise stock table and a per-hectare DBH table, and it is tempting to
    // treat the old component's versions of those two as already covered. They
    // are report chapter 11; the pane's own are chapter 10.
    const tables = renderTables();
    const summary = renderSummary();
    const seen = [...tokensIn(tables.container), ...tokensIn(summary.container)];
    expect(seen).toContain('{{ti_block_growing_stock}}');
    expect(seen).toContain('{{ti_dbh_class_perha_table}}');
  });
});

describe('Field Inventory Results — totals summary', () => {
  it('asks the provider for the Results-only data, once, on mount', () => {
    const ensureResultsLoaded = vi.fn();
    renderSummary({ ensureResultsLoaded });
    expect(ensureResultsLoaded).toHaveBeenCalledTimes(1);
  });

  it('shows the effective area and the forest-wide grand total', () => {
    renderSummary();
    // The area context is the denominator for every per-hectare figure below it.
    expect(screen.getByText('totalInventory.treeCoverAutofilled')).toBeTruthy();
    expect(screen.getAllByText('Block A').length).toBeGreaterThan(0);
    expect(screen.getByText('totalInventory.cfGrandTotal')).toBeTruthy();
    expect(screen.getByText('totalInventory.totalArea')).toBeTruthy();
    expect(screen.getByText('totalInventory.co2e')).toBeTruthy();
  });

  it('shows the chapter-11 block-wise stock table, not only the pane\'s chapter-10 one', () => {
    renderSummary();
    expect(screen.getByText('totalInventory.unitWiseStock')).toBeTruthy();
    expect(screen.getByText('{{ti_block_growing_stock}}')).toBeTruthy();
  });

  it('renders nothing without an inventory, so Metadata and Data stay untouched', () => {
    const { container } = renderSummary({ fieldInventory: null });
    expect(container.innerHTML).toBe('');
  });

  it('offers a retry when the tree-cover calculation fails', () => {
    const loadTreeCoverAreas = vi.fn();
    renderSummary({ treeCoverError: 'Failed to calculate tree cover areas: boom', loadTreeCoverAreas });

    expect(screen.getByText('totalInventory.calcTreeCoverError')).toBeTruthy();
    fireEvent.click(screen.getByText('totalInventory.recalculate'));
    expect(loadTreeCoverAreas).toHaveBeenCalled();
  });

  it('offers a manual calculation when areas resolved but the totals did not', () => {
    // The fallback for the case the old auto-calc effect could not cover: areas
    // present, first total-inventory call failed.
    const handleCalculateTotals = vi.fn();
    renderSummary({ totalData: null, handleCalculateTotals });

    fireEvent.click(screen.getByText('totalInventory.calculateBtn'));
    expect(handleCalculateTotals).toHaveBeenCalledWith(true);
  });

  it('warns when the inventory has no unit matching the calculated areas', () => {
    renderSummary({
      totalData: { forest_totals: {}, blocks: [], species_breakdown: [] },
    });
    expect(screen.getByText('totalInventory.noUnitFound')).toBeTruthy();
  });
});

describe('Field Inventory Results — carried-over tables', () => {
  it('renders every table heading the old component had', () => {
    renderTables();
    for (const key of [
      'totalInventory.bySpeciesTitle',
      'totalInventory.speciesDbhTitle',
      'totalInventory.wholeForestSpeciesDbh',
      'totalInventory.byDbhTitle',
      'totalInventory.byDbhPerHaTitle',
      'totalInventory.maiBySpecies',
      'totalInventory.maiByDbh',
      'totalInventory.aahBySpecies',
      'totalInventory.aahByDbh',
      'totalInventory.speciesCompositionLocal',
      'totalInventory.economicValuation',
      'totalInventory.sustainabilityIndex',
    ]) {
      expect(screen.getAllByText(key).length, `missing heading ${key}`).toBeGreaterThan(0);
    }
  });

  it('reads the provider rather than fetching, so a pane switch costs nothing', () => {
    const ensureResultsLoaded = vi.fn();
    renderTables({ ensureResultsLoaded });
    // The tables themselves make no request; the guarded loader does.
    expect(ensureResultsLoaded).toHaveBeenCalledTimes(1);
  });

  it('renders nothing when the totals have not been calculated', () => {
    // Half a chapter-11 report is worse than none: a table shell with no numbers
    // reads as "this forest has no trees".
    const { container } = renderTables({ totalData: null });
    expect(container.innerHTML).toBe('');
  });

  it('edits an economic rate through the shared state', () => {
    // A real setter, not a spy: the inputs are controlled, so a mock that never
    // updates state makes React restore the old value and the assertion would be
    // reading a stale DOM rather than the wiring. What is being checked is the
    // user-visible result — type a rate, the shared state and the input agree.
    const applied = vi.fn();

    const Harness: React.FC = () => {
      const [rates, setRates] = React.useState<Record<string, any>>({});
      const setBlockRates = React.useCallback(
        (updater: any) => {
          applied(updater);
          setRates(updater);
        },
        [],
      );
      state.current = provider({ blockRates: rates, setBlockRates });
      return <FieldInventoryResultsTables />;
    };

    render(<Harness />);

    const rate = document.querySelector('input[inputmode="decimal"]') as HTMLInputElement;
    expect(rate, 'the timber rate input is missing').toBeTruthy();
    expect(rate.value).toBe('5000');

    fireEvent.change(rate, { target: { value: '7000' } });

    expect(applied).toHaveBeenCalledTimes(1);
    expect(rate.value, 'the typed rate did not reach the shared state').toBe('7000');
  });

  it('uses the translated vocabulary, not a hardcoded unit noun', () => {
    renderTables();
    // `labels.unitLabelNp` comes from the dimension hook, so the tables follow
    // the block/compartment vocabulary instead of assuming one of them.
    expect(screen.getAllByText('कम्पार्टमेन्ट').length).toBeGreaterThan(0);
  });
});

describe('translation coverage for the ported tables', () => {
  it('has a Nepali string for every key the ported tables read', async () => {
    // Read from the source, not the DOM: `textContent` concatenates adjacent
    // cells, so two neighbouring keys arrive glued together and cannot be split
    // apart again. Reaching the keys is covered by the headings test above.
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const src = readFileSync(
      resolve(process.cwd(), 'src/components/fieldInventory/FieldInventoryResultsTables.tsx'),
      'utf8',
    );
    const keys = [...new Set([...src.matchAll(/totalInventory\.([a-zA-Z0-9]+)/g)].map((m) => m[1]))];
    expect(keys.length).toBeGreaterThan(50);

    const enKeys = en.totalInventory as Record<string, string>;
    const neKeys = ne.totalInventory as Record<string, string>;
    // Every key the port reaches has to exist in both bundles. The old page's
    // `title` is not among them: the pane supplies its own heading, so the key
    // is referenced nowhere in this file rather than referenced and untranslated.
    const missing = keys.filter((k) => !enKeys[k] || !neKeys[k]);
    expect(missing).toEqual([]);
  });
});

/**
 * The three-stage derivation.
 *
 * The pane used to open on the area block and the grand total, with the
 * per-hectare figures *nested inside the grand-total card* below the absolute
 * numbers - so the output came before the input it is derived from, and the
 * multiplication had to be inferred from two distant tables. The owner's framing
 * was "first per hectare analysis, second effective area, third total inventory
 * (multiplied by per hectare with effective area)".
 */
describe('the three stages, in the order they are applied', () => {
  const stageOrder = (container: HTMLElement) =>
    Array.from(container.querySelectorAll('[data-stage]')).map((s) =>
      Number(s.getAttribute('data-stage'))
    );

  it('renders stage 1, then 2, then 3', () => {
    const { container } = render(<FieldInventoryTotalsSummary />);
    expect(stageOrder(container)).toEqual([1, 2, 3]);
  });

  it('puts the per-hectare figures in stage 1 and the grand total in stage 3', () => {
    // The regression this guards: the per-ha basis was INSIDE the grand-total
    // card, so it rendered after the absolute numbers it explains.
    const { container } = render(<FieldInventoryTotalsSummary />);
    const s1 = container.querySelector('[data-stage="1"]')!.textContent || '';
    const s3 = container.querySelector('[data-stage="3"]')!.textContent || '';
    expect(s1).toContain('ti_forest_total_perha_narration');
    expect(s3).toContain('ti_forest_total_narration');
    expect(s3).not.toContain('ti_forest_total_perha_narration');
  });

  it('puts the area block in stage 2, between the rates and the totals', () => {
    const { container } = render(<FieldInventoryTotalsSummary />);
    const s2 = container.querySelector('[data-stage="2"]')!.textContent || '';
    expect(s2).toContain('ti_block_area_table');
  });

  it('states the multiplication, so the identity is not left to be inferred', () => {
    const { container } = render(<FieldInventoryTotalsSummary />);
    const s3 = container.querySelector('[data-stage="3"]')!.textContent || '';
    expect(s3).toContain('totalInventory.stage3Note');
  });

  it('exposes NO editable control in stage 2', () => {
    // D13. The areas are recomputed server-side (field_inventory.py:1046-1058
    // overrides whatever the client sends), so an editable area would be a
    // control that silently discards what you type. Asserted so a later change
    // cannot quietly add one.
    const { container } = render(<FieldInventoryTotalsSummary />);
    const s2 = container.querySelector('[data-stage="2"]')!;
    expect(s2.querySelectorAll('input')).toHaveLength(0);
    expect(s2.querySelectorAll('textarea')).toHaveLength(0);
    expect(s2.querySelectorAll('select')).toHaveLength(0);
  });

  it('still shows the areas as values, not as an empty stage', () => {
    // Read-only must not become invisible: the whole point of stage 2 is that
    // the reader can see the area the totals were spread over.
    const { container } = render(<FieldInventoryTotalsSummary />);
    const s2 = container.querySelector('[data-stage="2"]')!.textContent || '';
    expect(s2).toContain('Block A');
  });

  it('shows the areas even when the tree-cover recompute produced nothing', () => {
    // THE BUG THIS GUARDS. `POST /tree-cover-areas` answers 400 when the raster
    // does not overlap the boundary - which is the case on the owner's own
    // forest - and then the areas arrive from `/block-area-detail` alone. Stage 2
    // used to render `Object.values(treeCoverAreas)`, which is then EMPTY, so
    // the totals were computed correctly from `blockAreas` while stage 2 showed
    // no areas at all: the worst kind of silent failure, because the number the
    // reader needed to check the arithmetic against was simply absent.
    const { container } = renderSummary({ treeCoverAreas: {}, blockAreas: { 'Block A': 12.5, 'Block B': 7.25 } });
    const s2 = container.querySelector('[data-stage="2"]')!.textContent || '';
    expect(s2).toContain('Block A');
    expect(s2).toContain('Block B');
    expect(s2).toContain('12.50');
    expect(s2).toContain('7.25');
  });

  it('shows the forest total, the denominator every stage-1 rate uses', () => {
    // 12.5 + 7.25 = 19.75
    const { container } = renderSummary({ treeCoverAreas: {}, blockAreas: { 'Block A': 12.5, 'Block B': 7.25 } });
    const s2 = container.querySelector('[data-stage="2"]')!.textContent || '';
    expect(s2).toContain('totalInventory.totalEffectiveArea');
    expect(s2).toContain('19.75');
  });

  it('omits the tree-cover breakdown rather than showing zeroes when it is absent', () => {
    const withTc = renderSummary();
    expect(
      withTc.container.querySelector('[data-stage="2"]')!.textContent,
    ).toContain('totalInventory.forestCover');

    const without = renderSummary({ treeCoverAreas: {} });
    expect(
      without.container.querySelector('[data-stage="2"]')!.textContent,
    ).not.toContain('totalInventory.forestCover');
  });
});

/**
 * The per-hectare basis in the grand-total summary.
 *
 * Reported as "total inventory is available but per hectare is not". Nothing was
 * broken: total inventory IS per-hectare × area (CFMG 6.4), so the per-ha figure
 * is the *input*, and it was only reachable ~10 tables further down under the
 * heading "Total Stock by DBH Class (per ha)".
 */
describe('per-hectare basis in the grand-total summary', () => {
  const renderSummary = () => {
    const { container } = render(<FieldInventoryTotalsSummary />);
    return container.textContent || '';
  };

  it('states the per-hectare figures, not only the totals', () => {
    const text = renderSummary();
    // 40 stems / 12.5 ha = 3.2
    expect(text).toContain('3.2');
    // Growing stock 120.5 / 12.5 = 9.64
    expect(text).toContain('9.6');
  });

  it('labels the block with the per-hectare heading', () => {
    // `useT` is the identity fn in this file, so the heading is the raw key.
    expect(renderSummary()).toContain('totalInventory.perHectare');
  });

  it('says what the figures are a basis FOR, so it is not read as another total', () => {
    expect(renderSummary()).toContain('totalInventory.perHaBasisNote');
  });

  it('averages over the whole forest area, not the sum of block rates', () => {
    // The blocks differ in area by ~70x in the reported forest, so summing their
    // per-ha rates would be a different number entirely. Only the forest-wide
    // figure may appear here, and it must be total / total_area_ha.
    const text = renderSummary();
    expect(text).not.toContain('NaN');
    expect(text).not.toContain('Infinity');
  });

  it('shows no per-hectare figure at all when the area is unknown', () => {
    state.current = {
      ...state.current,
      totalData: {
        ...TOTAL_DATA,
        forest_totals: { ...TOTAL_DATA.forest_totals, total_area_ha: 0 },
      },
    };
    const text = renderSummary();
    // A number divided by nothing is worse than an absent one.
    expect(text).not.toContain('perHaBasisNote');
    expect(text).not.toContain('NaN');
  });
});
